from __future__ import annotations
"""
MemoryProposalService — manage the proposal → approval → active memory workflow.
"""

from datetime import datetime, UTC
from typing import Optional
from ulid import ULID
from sqlalchemy.orm import Session
from sqlalchemy import and_, case, func, not_, or_

from ..models import Proposal, Run
from ..param_binding import duplicate_mapper
from ..schemas import MemoryCreate


_ALLOWED_URGENCY = frozenset({"low", "normal", "high", "critical"})


def validate_proposal_review_fields(
    *,
    urgency: str | None = None,
    review_deadline: datetime | None = None,
    expires_at: datetime | None = None,
    now: datetime | None = None,
) -> None:
    """Validate urgency and temporal fields for proposal create/update."""
    from fastapi import HTTPException

    now = now or datetime.now(UTC)
    if urgency is not None and urgency not in _ALLOWED_URGENCY:
        raise HTTPException(status_code=422, detail=f"Invalid urgency {urgency!r}")
    if review_deadline is not None and review_deadline <= now:
        raise HTTPException(status_code=422, detail="review_deadline must be in the future")
    if review_deadline is not None and expires_at is not None:
        if expires_at <= review_deadline:
            raise HTTPException(
                status_code=422,
                detail="expires_at must be after review_deadline when both are set",
            )


def _urgency_priority_expr():
    return case(
        (Proposal.urgency == "critical", 4),
        (Proposal.urgency == "high", 3),
        (Proposal.urgency == "normal", 2),
        (Proposal.urgency == "low", 1),
        else_=0,
    )


def _expired_filter_sql(now: datetime):
    reviewable = Proposal.status.in_(["pending", "waiting_for_review"])
    return and_(reviewable, Proposal.expires_at.isnot(None), Proposal.expires_at < now)


def _new_id() -> str:
    return str(ULID())


def build_memory_update_proposal(
    proposal_id: str,
    space_id: str,
    user_id: str,
    *,
    workspace_id: str | None,
    proposed_title: str,
    proposed_content: str,
    rationale: str,
    memory_type: str,
    target_scope: str,
    target_namespace: str,
    source_session_id: str | None = None,
    source_task_id: str | None = None,
    source_run_id: str | None = None,
    source_activity_id: str | None = None,
    source_evidence: str | None = None,
    target_visibility: str = "private",
    risk_level: str = "low",
    owner_user_id: str | None = None,
    subject_user_id: str | None = None,
    sensitivity_level: str = "normal",
    selected_user_ids: list[str] | None = None,
    urgency: str = "normal",
    review_deadline: datetime | None = None,
    expires_at: datetime | None = None,
) -> Proposal:
    """Construct a canonical Proposal row for a memory_update workflow."""
    payload: dict = {
        "proposed_content": proposed_content,
        "memory_type": memory_type,
        "target_scope": target_scope,
        "target_namespace": target_namespace,
        "target_visibility": target_visibility,
        "sensitivity_level": sensitivity_level,
    }
    if source_session_id is not None:
        payload["source_session_id"] = source_session_id
    if source_task_id is not None:
        payload["source_task_id"] = source_task_id
    if source_run_id is not None:
        payload["source_run_id"] = source_run_id
    if source_activity_id is not None:
        payload["source_activity_id"] = source_activity_id
    if source_evidence is not None:
        payload["source_evidence"] = source_evidence
    if owner_user_id is not None:
        payload["owner_user_id"] = owner_user_id
    if subject_user_id is not None:
        payload["subject_user_id"] = subject_user_id
    if selected_user_ids is not None:
        payload["selected_user_ids"] = selected_user_ids

    return Proposal(
        id=proposal_id,
        space_id=space_id,
        proposal_type="memory_update",
        status="pending",
        title=proposed_title,
        summary=None,
        payload_json=payload,
        rationale=rationale,
        workspace_id=workspace_id,
        created_by_user_id=user_id,
        risk_level=risk_level,
        urgency=urgency,
        review_deadline=review_deadline,
        expires_at=expires_at,
    )


class MemoryProposalService:
    def __init__(self, db: Session):
        self.db = db

    def create_proposal(
        self,
        space_id: str,
        user_id: str,
        target_scope: str,
        target_namespace: str,
        memory_type: str,
        proposed_title: str,
        proposed_content: str,
        rationale: str,
        workspace_id: str | None = None,
        source_session_id: str | None = None,
        source_task_id: str | None = None,
        source_run_id: str | None = None,
        target_visibility: str = "private",
        owner_user_id: str | None = None,
        subject_user_id: str | None = None,
        sensitivity_level: str = "normal",
        selected_user_ids: list[str] | None = None,
        urgency: str = "normal",
        review_deadline: datetime | None = None,
        expires_at: datetime | None = None,
    ) -> Proposal:
        validate_proposal_review_fields(
            urgency=urgency,
            review_deadline=review_deadline,
            expires_at=expires_at,
        )
        proposal = build_memory_update_proposal(
            _new_id(),
            space_id,
            user_id,
            workspace_id=workspace_id,
            proposed_title=proposed_title,
            proposed_content=proposed_content,
            rationale=rationale,
            memory_type=memory_type,
            target_scope=target_scope,
            target_namespace=target_namespace,
            source_session_id=source_session_id,
            source_task_id=source_task_id,
            source_run_id=source_run_id,
            target_visibility=target_visibility,
            owner_user_id=owner_user_id,
            subject_user_id=subject_user_id,
            sensitivity_level=sensitivity_level,
            selected_user_ids=selected_user_ids,
            urgency=urgency,
            review_deadline=review_deadline,
            expires_at=expires_at,
        )
        self.db.add(proposal)
        self.db.commit()
        self.db.refresh(proposal)
        return proposal

    def count_proposals(
        self,
        space_id: str,
        user_id: str,
        status: str | None = "pending",
        proposal_type: str | None = None,
        urgency: str | None = None,
        expired: bool | None = None,
        *,
        now: datetime | None = None,
    ) -> int:
        now = now or datetime.now(UTC)
        if urgency and urgency not in _ALLOWED_URGENCY:
            from fastapi import HTTPException

            raise HTTPException(status_code=422, detail=f"Invalid urgency {urgency!r}")
        run_for_instructed = duplicate_mapper(Run)
        visible = or_(
            Proposal.created_by_user_id == user_id,
            run_for_instructed.instructed_by_user_id == user_id,
        )
        q = (
            self.db.query(func.count(Proposal.id))
            .select_from(Proposal)
            .outerjoin(
                run_for_instructed,
                and_(
                    run_for_instructed.id == Proposal.created_by_run_id,
                    run_for_instructed.space_id == space_id,
                ),
            )
            .filter(Proposal.space_id == space_id, visible)
        )
        if status:
            q = q.filter(Proposal.status == status)
        if proposal_type:
            q = q.filter(Proposal.proposal_type == proposal_type)
        if urgency:
            q = q.filter(Proposal.urgency == urgency)
        if expired is True:
            q = q.filter(_expired_filter_sql(now))
        elif expired is False:
            q = q.filter(not_(_expired_filter_sql(now)))
        return q.scalar() or 0

    def list_proposals(
        self,
        space_id: str,
        user_id: str,
        status: str | None = "pending",
        proposal_type: str | None = None,
        urgency: str | None = None,
        expired: bool | None = None,
        limit: int = 50,
        offset: int = 0,
        *,
        now: datetime | None = None,
    ) -> list[Proposal]:
        now = now or datetime.now(UTC)
        if urgency and urgency not in _ALLOWED_URGENCY:
            from fastapi import HTTPException

            raise HTTPException(status_code=422, detail=f"Invalid urgency {urgency!r}")
        run_for_instructed = duplicate_mapper(Run)
        visible = or_(
            Proposal.created_by_user_id == user_id,
            run_for_instructed.instructed_by_user_id == user_id,
        )
        q = (
            self.db.query(Proposal)
            .outerjoin(
                run_for_instructed,
                and_(
                    run_for_instructed.id == Proposal.created_by_run_id,
                    run_for_instructed.space_id == space_id,
                ),
            )
            .filter(Proposal.space_id == space_id, visible)
        )
        if status:
            q = q.filter(Proposal.status == status)
        if proposal_type:
            q = q.filter(Proposal.proposal_type == proposal_type)
        if urgency:
            q = q.filter(Proposal.urgency == urgency)
        if expired is True:
            q = q.filter(_expired_filter_sql(now))
        elif expired is False:
            q = q.filter(not_(_expired_filter_sql(now)))

        prio = _urgency_priority_expr()
        q = q.order_by(
            prio.desc(),
            Proposal.review_deadline.asc().nulls_last(),
            Proposal.expires_at.asc().nulls_last(),
            Proposal.created_at.desc(),
        )
        return q.offset(offset).limit(limit).all()

    def count_reviewable_proposals(self, space_id: str, user_id: str) -> int:
        """Count pending + waiting_for_review visible to user (same rules as list_proposals)."""
        run_for_instructed = duplicate_mapper(Run)
        visible = or_(
            Proposal.created_by_user_id == user_id,
            run_for_instructed.instructed_by_user_id == user_id,
        )
        q = (
            self.db.query(func.count(Proposal.id))
            .select_from(Proposal)
            .outerjoin(
                run_for_instructed,
                and_(
                    run_for_instructed.id == Proposal.created_by_run_id,
                    run_for_instructed.space_id == space_id,
                ),
            )
            .filter(
                Proposal.space_id == space_id,
                visible,
                Proposal.status.in_(["pending", "waiting_for_review"]),
            )
        )
        return q.scalar() or 0

    def list_reviewable_proposals(
        self,
        space_id: str,
        user_id: str,
        *,
        limit: int = 20,
        offset: int = 0,
    ) -> list[Proposal]:
        """List pending + waiting_for_review visible to user (same visibility as list_proposals)."""
        run_for_instructed = duplicate_mapper(Run)
        visible = or_(
            Proposal.created_by_user_id == user_id,
            run_for_instructed.instructed_by_user_id == user_id,
        )
        q = (
            self.db.query(Proposal)
            .outerjoin(
                run_for_instructed,
                and_(
                    run_for_instructed.id == Proposal.created_by_run_id,
                    run_for_instructed.space_id == space_id,
                ),
            )
            .filter(
                Proposal.space_id == space_id,
                visible,
                Proposal.status.in_(["pending", "waiting_for_review"]),
            )
        )
        prio = _urgency_priority_expr()
        q = q.order_by(
            prio.desc(),
            Proposal.review_deadline.asc().nulls_last(),
            Proposal.expires_at.asc().nulls_last(),
            Proposal.created_at.desc(),
        )
        return q.offset(offset).limit(limit).all()

    def get_proposal_for_viewer(
        self,
        proposal_id: str,
        space_id: str,
        user_id: str,
    ) -> Proposal | None:
        """Return a proposal if it exists in ``space_id`` and matches global list visibility."""
        run_for_instructed = duplicate_mapper(Run)
        visible = or_(
            Proposal.created_by_user_id == user_id,
            run_for_instructed.instructed_by_user_id == user_id,
        )
        return (
            self.db.query(Proposal)
            .outerjoin(
                run_for_instructed,
                and_(
                    run_for_instructed.id == Proposal.created_by_run_id,
                    run_for_instructed.space_id == space_id,
                ),
            )
            .filter(Proposal.space_id == space_id, Proposal.id == proposal_id, visible)
            .first()
        )

    def count_proposals_for_run(
        self,
        run_id: str,
        space_id: str,
        status: str | None = None,
        proposal_type: str | None = None,
        urgency: str | None = None,
        expired: bool | None = None,
        *,
        now: datetime | None = None,
    ) -> int:
        """Count proposals linked to a Run (``created_by_run_id``), space-scoped."""
        now = now or datetime.now(UTC)
        if urgency and urgency not in _ALLOWED_URGENCY:
            from fastapi import HTTPException

            raise HTTPException(status_code=422, detail=f"Invalid urgency {urgency!r}")
        q = self.db.query(func.count(Proposal.id)).filter(
            Proposal.space_id == space_id,
            Proposal.created_by_run_id == run_id,
        )
        if status:
            q = q.filter(Proposal.status == status)
        if proposal_type:
            q = q.filter(Proposal.proposal_type == proposal_type)
        if urgency:
            q = q.filter(Proposal.urgency == urgency)
        if expired is True:
            q = q.filter(_expired_filter_sql(now))
        elif expired is False:
            q = q.filter(not_(_expired_filter_sql(now)))
        return q.scalar() or 0

    def list_proposals_for_run(
        self,
        run_id: str,
        space_id: str,
        status: str | None = None,
        proposal_type: str | None = None,
        urgency: str | None = None,
        expired: bool | None = None,
        limit: int = 50,
        offset: int = 0,
        *,
        now: datetime | None = None,
    ) -> list[Proposal]:
        """List proposals linked to a Run; same sort order as ``list_proposals``."""
        now = now or datetime.now(UTC)
        if urgency and urgency not in _ALLOWED_URGENCY:
            from fastapi import HTTPException

            raise HTTPException(status_code=422, detail=f"Invalid urgency {urgency!r}")
        q = self.db.query(Proposal).filter(
            Proposal.space_id == space_id,
            Proposal.created_by_run_id == run_id,
        )
        if status:
            q = q.filter(Proposal.status == status)
        if proposal_type:
            q = q.filter(Proposal.proposal_type == proposal_type)
        if urgency:
            q = q.filter(Proposal.urgency == urgency)
        if expired is True:
            q = q.filter(_expired_filter_sql(now))
        elif expired is False:
            q = q.filter(not_(_expired_filter_sql(now)))
        prio = _urgency_priority_expr()
        q = q.order_by(
            prio.desc(),
            Proposal.review_deadline.asc().nulls_last(),
            Proposal.expires_at.asc().nulls_last(),
            Proposal.created_at.desc(),
        )
        return q.offset(offset).limit(limit).all()

    def get(self, proposal_id: str) -> Proposal | None:
        return self.db.query(Proposal).filter(Proposal.id == proposal_id).first()

    def accept(
        self,
        proposal_id: str,
        space_id: str,
        user_id: str,
    ) -> tuple[Proposal, "MemoryEntry"] | None:
        from .store import MemoryStore
        from ..models import MemoryEntry

        proposal = self.get(proposal_id)
        if not proposal or proposal.status != "pending":
            return None
        if proposal.space_id != space_id or proposal.created_by_user_id != user_id:
            return None

        store = MemoryStore(self.db)
        payload = proposal.payload_json or {}
        vis = (payload.get("target_visibility") or "private").lower()
        sens = (payload.get("sensitivity_level") or "normal").lower()

        mem_data = MemoryCreate(
            title=proposal.title,
            content=proposal.proposed_content,
            type=proposal.memory_type,
            scope=proposal.target_scope,
            namespace=proposal.target_namespace,
            space_id=proposal.space_id,
            visibility=vis,
            sensitivity_level=sens,
            owner_user_id=payload.get("owner_user_id"),
            subject_user_id=payload.get("subject_user_id"),
            selected_user_ids=payload.get("selected_user_ids"),
            workspace_id=proposal.workspace_id,
            source_proposal_id=proposal.id,
        )
        memory = store.create(
            mem_data,
            acting_user_id=user_id,
            created_by=str(proposal.created_by_user_id or user_id),
            approved_by=str(user_id),
        )

        proposal.status = "accepted"
        proposal.decided_at = datetime.now(UTC)
        proposal.resulting_memory_id = memory.id
        self.db.commit()
        self.db.refresh(proposal)
        return proposal, memory

    def reject(
        self,
        proposal_id: str,
        space_id: str,
        user_id: str,
    ) -> Proposal | None:
        proposal = self.get(proposal_id)
        if not proposal or proposal.status != "pending":
            return None
        if proposal.space_id != space_id or proposal.created_by_user_id != user_id:
            return None

        proposal.status = "rejected"
        proposal.decided_at = datetime.now(UTC)
        self.db.commit()
        self.db.refresh(proposal)
        return proposal
