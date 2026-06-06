from __future__ import annotations
import uuid
"""
General proposal review: list, accept, reject — dispatches to ProposalApplyService.

Supported proposal types for accept():
  memory_create   — create a new active MemoryEntry
  memory_update   — append-only versioned update (requires target_memory_id)
  memory_archive  — status-based archive (requires target_memory_id)
  policy_change   — create / supersede a Policy version
  code_patch      — apply patch to workspace files
  egress_review   — metadata-only grant egress review marker
  follow_up_task  — create a Task row via ProposalApplyService
"""

from dataclasses import dataclass
from datetime import datetime, UTC
from typing import Any, Optional

from sqlalchemy.orm import Session
from sqlalchemy import and_, case, func, not_, or_
from sqlalchemy.orm.attributes import flag_modified

from ..db_uow import UnitOfWork
from ..models import AgentVersion, KnowledgeItem, KnowledgeItemRelation, MemoryEntry, Policy, Proposal, Run, Task, Workspace
from ..param_binding import duplicate_mapper
from ..policy.gateway import PolicyCheckRequest, PolicyGateway
from ..projects.service import assert_project_in_space
from ..schemas import MemoryCreate
from .proposal_payload import (
    activity_provenance_entry,
    strip_flat_provenance_keys,
)


_ALLOWED_URGENCY = frozenset({"low", "normal", "high", "critical"})


@dataclass
class ProposalAcceptResult:
    """Result of ``ProposalService.accept`` — varies by proposal type."""

    proposal: Proposal
    memory: Optional[MemoryEntry] = None
    policy: Optional[Policy] = None
    updated_paths: Optional[list[str]] = None
    egress_review: bool = False
    task: Optional[Task] = None
    agent_version: Optional[AgentVersion] = None
    knowledge_item: Optional[KnowledgeItem] = None
    knowledge_relation: Optional[KnowledgeItemRelation] = None


# ---------------------------------------------------------------------------
# Public re-exports. New code must use ProposalApplyService (apply_service.py).
# ---------------------------------------------------------------------------


class MemoryUpdateProposalApplier:
    """Public re-export. Delegates to ProposalApplyService."""

    def __init__(self, db: Session):
        self.db = db

    def apply(self, proposal: Proposal, *, user_id: str) -> MemoryEntry:
        from .apply_service import MemoryProposalApplier

        applier = MemoryProposalApplier(self.db)
        result = applier.apply_update(proposal, user_id=user_id)
        return result.memory


class CodePatchProposalApplier:
    """Apply a vetted ``code_patch`` proposal to workspace files (caller commits proposal state)."""

    def __init__(self, db: Session):
        self.db = db

    def apply(self, proposal: Proposal, *, space_id: str, user_id: str) -> list[str]:
        from .code_patch_apply import CodePatchApplyError, apply_code_patch_payload

        if not proposal.workspace_id:
            raise CodePatchApplyError("code_patch proposal missing workspace_id")
        ws = (
            self.db.query(Workspace)
            .filter(
                Workspace.id == proposal.workspace_id,
                Workspace.space_id == space_id,
            )
            .first()
        )
        if not ws:
            raise CodePatchApplyError("workspace not found for proposal")

        payload = proposal.payload_json or {}
        patch = payload.get("patch")
        if not isinstance(patch, dict):
            raise CodePatchApplyError("invalid patch payload")

        try:
            result = apply_code_patch_payload(
                self.db,
                workspace=ws,
                patch=patch,
                space_id=space_id,
                user_id=user_id,
                source_run_id=payload.get("source_run_id") or proposal.created_by_run_id,
                proposal_id=proposal.id,
            )
            return result.paths
        except CodePatchApplyError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise CodePatchApplyError(str(exc)) from exc


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
    return and_(Proposal.status == "pending", Proposal.expires_at.isnot(None), Proposal.expires_at < now)


def _new_id() -> str:
    return str(uuid.uuid4())


def _memory_provenance_entries(
    *,
    source_run_id: str | None,
    source_activity_id: str | None,
    source_evidence: str | None,
    activity_source_trust: str | None = None,
    activity_evidence_json: dict | None = None,
) -> list[dict]:
    entries: list[dict] = []
    if source_run_id:
        entries.append(
            {
                "source_type": "run_step",
                "source_id": source_run_id,
                "source_trust": "internal_system",
                "evidence_json": {"correlation": "source_run_id"},
            }
        )
    if source_activity_id:
        ev = dict(activity_evidence_json or {})
        if source_evidence is not None:
            ev.setdefault("note", str(source_evidence))
        entries.append(
            activity_provenance_entry(
                activity_id=source_activity_id,
                source_trust=activity_source_trust,
                evidence=ev,
            )
        )
    return entries


def build_memory_create_proposal(
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
    activity_source_trust: str | None = None,
    activity_evidence_json: dict | None = None,
    target_visibility: str = "space_shared",
    risk_level: str = "low",
    owner_user_id: str | None = None,
    subject_user_id: str | None = None,
    sensitivity_level: str = "normal",
    selected_user_ids: list[str] | None = None,
    urgency: str = "normal",
    review_deadline: datetime | None = None,
    expires_at: datetime | None = None,
    created_by_run_id: str | None = None,
    extra_provenance_entries: list[dict] | None = None,
) -> Proposal:
    """Construct a canonical Proposal row for a memory_create workflow."""
    payload: dict = {
        "operation": "create",
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
    if owner_user_id is not None:
        payload["owner_user_id"] = owner_user_id
    if subject_user_id is not None:
        payload["subject_user_id"] = subject_user_id
    if selected_user_ids is not None:
        payload["selected_user_ids"] = selected_user_ids

    prov = _memory_provenance_entries(
        source_run_id=source_run_id,
        source_activity_id=source_activity_id,
        source_evidence=source_evidence,
        activity_source_trust=activity_source_trust,
        activity_evidence_json=activity_evidence_json,
    )
    if extra_provenance_entries:
        prov.extend(extra_provenance_entries)
    if prov:
        payload["provenance_entries"] = prov
    payload = strip_flat_provenance_keys(payload)

    return Proposal(
        id=proposal_id,
        space_id=space_id,
        proposal_type="memory_create",
        status="pending",
        title=proposed_title,
        summary=None,
        payload_json=payload,
        rationale=rationale,
        workspace_id=workspace_id,
        created_by_user_id=user_id,
        created_by_run_id=created_by_run_id,
        risk_level=risk_level,
        urgency=urgency,
        review_deadline=review_deadline,
        expires_at=expires_at,
    )


def build_memory_update_proposal(
    proposal_id: str,
    space_id: str,
    user_id: str,
    *,
    target_memory_id: str,
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
    activity_source_trust: str | None = None,
    activity_evidence_json: dict | None = None,
    target_visibility: str = "space_shared",
    risk_level: str = "low",
    owner_user_id: str | None = None,
    subject_user_id: str | None = None,
    sensitivity_level: str = "normal",
    selected_user_ids: list[str] | None = None,
    urgency: str = "normal",
    review_deadline: datetime | None = None,
    expires_at: datetime | None = None,
    created_by_run_id: str | None = None,
    extra_provenance_entries: list[dict] | None = None,
) -> Proposal:
    """Construct a Proposal row for append-only memory_update (requires target_memory_id)."""
    payload: dict = {
        "operation": "update",
        "target_memory_id": target_memory_id,
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
    if owner_user_id is not None:
        payload["owner_user_id"] = owner_user_id
    if subject_user_id is not None:
        payload["subject_user_id"] = subject_user_id
    if selected_user_ids is not None:
        payload["selected_user_ids"] = selected_user_ids

    prov = _memory_provenance_entries(
        source_run_id=source_run_id,
        source_activity_id=source_activity_id,
        source_evidence=source_evidence,
        activity_source_trust=activity_source_trust,
        activity_evidence_json=activity_evidence_json,
    )
    if extra_provenance_entries:
        prov.extend(extra_provenance_entries)
    if prov:
        payload["provenance_entries"] = prov
    payload = strip_flat_provenance_keys(payload)

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
        created_by_run_id=created_by_run_id,
        risk_level=risk_level,
        urgency=urgency,
        review_deadline=review_deadline,
        expires_at=expires_at,
    )


def build_egress_review_proposal(
    proposal_id: str,
    space_id: str,
    user_id: str,
    *,
    source_run_id: str,
    grant_id: str,
    granting_user_id: str,
    target_object_type: str,
    target_visibility: str = "space_shared",
    target_space_id: str | None = None,
    review_deadline: datetime | None = None,
    expires_at: datetime | None = None,
) -> Proposal:
    """Construct a metadata-only egress_review proposal.

    This representation carries only safe grant/run metadata. It does not embed
    output text, personal_context_block, generated summaries, memory IDs, or raw
    personal memory.
    """
    target_space_id = target_space_id or space_id
    payload = {
        "target_space_id": target_space_id,
        "source_run_id": source_run_id,
        "grant_id": grant_id,
        "granting_user_id": granting_user_id,
        "target_object_type": target_object_type,
        "target_visibility": target_visibility,
        "raw_private_memory_included": False,
        "personal_summary_persisted": False,
        "requires_approval_type": "egress_granting_user",
        "required_approver_user_id": granting_user_id,
        "personal_context_derived": True,
        "egress_guard_required": True,
    }
    if expires_at is not None:
        payload["egress_review_expires_at"] = expires_at.isoformat()

    return Proposal(
        id=proposal_id,
        space_id=space_id,
        proposal_type="egress_review",
        status="pending",
        title="Grant-derived egress review",
        summary=None,
        payload_json=payload,
        rationale="Grant-derived output requires granting-user approval before apply.",
        created_by_user_id=user_id,
        created_by_run_id=source_run_id,
        risk_level="high",
        urgency="normal",
        review_deadline=review_deadline,
        expires_at=expires_at,
    )


class ProposalService:
    """List, count, accept, and reject proposals for a space.

    ``accept()`` delegates all durable writes to ``ProposalApplyService`` — the
    single durable write boundary for accepted proposals.
    """

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
        target_visibility: str = "space_shared",
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
        PolicyGateway(self.db).enforce(
            PolicyCheckRequest(
                action="proposal.create",
                actor_type="user",
                actor_id=user_id,
                space_id=space_id,
                resource_type="proposal",
                context={
                    "target_visibility": target_visibility,
                    "target_scope": target_scope,
                },
                metadata_json={
                    "proposal_type": "memory_create",
                    "workspace_id": workspace_id,
                    "source_run_id": source_run_id,
                    "sensitivity_level": sensitivity_level,
                    "urgency": urgency,
                },
            )
        )

        proposal = build_memory_create_proposal(
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

    def create_user_proposal(
        self,
        *,
        space_id: str,
        user_id: str,
        proposal_type: str,
        title: str,
        payload_json: dict,
        rationale: str,
        workspace_id: str | None = None,
        risk_level: str = "low",
        urgency: str = "normal",
        target_scope: str | None = None,
        target_visibility: str | None = None,
        target_memory_id: str | None = None,
        review_deadline: datetime | None = None,
        expires_at: datetime | None = None,
        policy_action: str = "proposal.create",
        policy_resource_type: str = "proposal",
        policy_resource_id: str | None = None,
        policy_context: dict[str, Any] | None = None,
        policy_metadata_json: dict[str, Any] | None = None,
    ) -> Proposal:
        """Create a user-origin proposal behind a proposal creation policy gate.

        Most user proposals use ``proposal.create``. Domain-specific proposal
        boundaries may pass a more precise action such as ``agent.config_update``
        so audit records express the concrete risk without duplicating records.
        """
        validate_proposal_review_fields(
            urgency=urgency,
            review_deadline=review_deadline,
            expires_at=expires_at,
        )
        base_context = {
            "target_visibility": target_visibility,
            "target_scope": target_scope,
        }
        if policy_context:
            base_context.update(policy_context)
        base_metadata = {
            "proposal_type": proposal_type,
            "workspace_id": workspace_id,
            "target_memory_id": target_memory_id,
            "sensitivity_level": payload_json.get("sensitivity_level"),
            "urgency": urgency,
        }
        if policy_metadata_json:
            base_metadata.update(policy_metadata_json)
        PolicyGateway(self.db).enforce(
            PolicyCheckRequest(
                action=policy_action,
                actor_type="user",
                actor_id=user_id,
                space_id=space_id,
                resource_type=policy_resource_type,
                resource_id=policy_resource_id,
                resource_space_id=space_id,
                context=base_context,
                metadata_json=base_metadata,
            )
        )

        proposal = Proposal(
            id=_new_id(),
            space_id=space_id,
            proposal_type=proposal_type,
            status="pending",
            title=title,
            summary=None,
            payload_json=payload_json,
            rationale=rationale,
            workspace_id=workspace_id,
            created_by_user_id=user_id,
            risk_level=risk_level,
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
        project_id: str | None = None,
        *,
        now: datetime | None = None,
    ) -> int:
        now = now or datetime.now(UTC)
        if project_id:
            assert_project_in_space(self.db, project_id, space_id)
        if urgency and urgency not in _ALLOWED_URGENCY:
            from fastapi import HTTPException

            raise HTTPException(status_code=422, detail=f"Invalid urgency {urgency!r}")
        run_for_instructed = duplicate_mapper(Run)
        # space_shared proposals are visible to any space user; private/restricted ones
        # are restricted to the creator or the user whose run created them.
        visible = or_(
            Proposal.visibility == "space_shared",
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
        if project_id:
            q = q.filter(Proposal.project_id == project_id)
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
        project_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
        *,
        now: datetime | None = None,
    ) -> list[Proposal]:
        now = now or datetime.now(UTC)
        if project_id:
            assert_project_in_space(self.db, project_id, space_id)
        if urgency and urgency not in _ALLOWED_URGENCY:
            from fastapi import HTTPException

            raise HTTPException(status_code=422, detail=f"Invalid urgency {urgency!r}")
        run_for_instructed = duplicate_mapper(Run)
        # space_shared proposals are visible to any space user; private/restricted ones
        # are restricted to the creator or the user whose run created them.
        visible = or_(
            Proposal.visibility == "space_shared",
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
        if project_id:
            q = q.filter(Proposal.project_id == project_id)
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

    def _reviewable_filter(self, space_id: str, user_id: str):
        """Return a SQLAlchemy filter expression for proposals in the user's reviewable inbox.

        "Reviewable" is a product inbox category, not a universal approval-authority claim:

        - owner: all proposals visible to the user (space_shared OR directly involved).
          Owners can approve all visible proposals under current policy.
        - admin: user-visible proposals where effective risk <= high.
          Admins can approve low/medium/high; proposals with risk_level='critical' are
          excluded because admins lack approval authority for critical effective risk.
          Effective risk is max(type_default, declared). Type defaults max at HIGH,
          so critical effective risk only arises when risk_level='critical'.
        - reviewer: user-visible proposals where effective risk <= medium.
          Effective risk = max(type_default, declared_risk). Both conditions must hold:
            1. proposal_type must be a MEDIUM-or-lower-default type (memory_create /
               memory_update / memory_archive / follow_up_task). HIGH-default types
               (code_patch / policy_change / egress_review) always have effective risk
               >= HIGH regardless of declared risk, so they are always excluded.
            2. declared risk_level must be 'low' or 'medium'.
        - member/guest/no membership: directly involved proposals only
          (created by this user, or run instructed by this user).
          Member/guest cannot approve; proposal.apply is denied by the policy gate.

        Returns a tuple (filter_expr, outerjoin_pair) for composing into a query.
        """
        from ..policy.approval import get_space_role

        role = get_space_role(self.db, user_id, space_id)
        run_for_instructed = duplicate_mapper(Run)
        directly_involved = or_(
            Proposal.created_by_user_id == user_id,
            run_for_instructed.instructed_by_user_id == user_id,
        )
        visible_to_user = or_(
            Proposal.visibility == "space_shared",
            directly_involved,
        )

        if role == "owner":
            reviewable = visible_to_user
        elif role == "admin":
            non_critical = or_(
                Proposal.risk_level == None,  # noqa: E711
                Proposal.risk_level != "critical",
            )
            reviewable = and_(visible_to_user, non_critical)
        elif role == "reviewer":
            from ..policy.proposal_apply import MEDIUM_DEFAULT_PROPOSAL_TYPES

            # Effective risk = max(type_default, declared_risk). Only include proposals
            # where both the type default and the declared risk are <= MEDIUM.
            # HIGH-default types (code_patch, policy_change, egress_review) always have
            # effective risk >= HIGH regardless of declared_risk.
            reviewer_risk = and_(
                Proposal.proposal_type.in_(MEDIUM_DEFAULT_PROPOSAL_TYPES),
                Proposal.risk_level.in_(["low", "medium"]),
            )
            reviewable = and_(visible_to_user, reviewer_risk)
        else:
            reviewable = directly_involved

        return reviewable, run_for_instructed

    def count_reviewable_proposals(self, space_id: str, user_id: str) -> int:
        """Count pending proposals in the user's reviewable inbox for this space.

        For owner/admin/reviewer this means approvable (or potentially approvable)
        proposals filtered by role. For member/guest this means directly involved
        proposals for visibility; approval authority is separate.
        """
        reviewable, run_for_instructed = self._reviewable_filter(space_id, user_id)
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
                reviewable,
                Proposal.status == "pending",
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
        """List pending proposals in the user's reviewable inbox for this space.

        For owner/admin/reviewer this means approvable (or potentially approvable)
        proposals filtered by role. For member/guest this means directly involved
        proposals for visibility; approval authority is separate.
        """
        reviewable, run_for_instructed = self._reviewable_filter(space_id, user_id)
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
                reviewable,
                Proposal.status == "pending",
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
        # space_shared proposals visible to any space user; private/restricted to creator/run-instructor.
        visible = or_(
            Proposal.visibility == "space_shared",
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
    ) -> ProposalAcceptResult | None:
        """Accept a pending proposal and apply it through ProposalApplyService.

        Source monitoring uses ``accept_context="explicit_user_accept"`` (fixed here;
        never taken from HTTP input — see ProposalApplyService for accept_context contract).

        Returns None when:
          - Proposal not found or already decided
          - preview=True  (dry-run proposals must never be applied)
          - Proposal does not belong to the requested space

        Raises PolicyGateBlocked when the acting user lacks approval authority
        for this proposal type and risk level in the space (HTTP callers: 403).
        Unsupported proposal types are denied at the policy gate with
        audit_code="unsupported_proposal_type".
        """
        proposal = self.get(proposal_id)
        if not proposal or proposal.status != "pending":
            return None
        if proposal.preview:
            return None
        if proposal.space_id != space_id:
            return None

        # Policy gate: enforce_proposal_apply writes one durable ALLOW record or
        # raises PolicyGateBlocked for the global HTTP handler to record.
        # ProposalRiskLevelError propagates to caller (invalid proposal.risk_level → 422).
        PolicyGateway(self.db).enforce_proposal_apply(
            user_id=user_id,
            space_id=space_id,
            proposal=proposal,
        )

        from .apply_service import ProposalApplyService, ProposalApplyError

        apply_svc = ProposalApplyService(self.db)
        try:
            result = apply_svc.apply(
                proposal,
                user_id=user_id,
                accept_context="explicit_user_accept",
            )
            proposal.status = "accepted"
            proposal.reviewed_at = datetime.now(UTC)
            proposal.reviewed_by = user_id

            if result.memory is not None:
                proposal.resulting_memory_id = result.memory.id

            if result.updated_paths is not None:
                payload = proposal.payload_json or {}
                data = dict(payload)
                data["applied_paths"] = result.updated_paths
                if result.code_patch_files is not None:
                    data["applied_files"] = result.code_patch_files
                data["applied_at"] = datetime.now(UTC).isoformat()
                proposal.payload_json = data
                flag_modified(proposal, "payload_json")

            if result.egress_review:
                payload = proposal.payload_json or {}
                data = dict(payload)
                data["egress_review_applied"] = True
                data["applied_at"] = datetime.now(UTC).isoformat()
                proposal.payload_json = data
                flag_modified(proposal, "payload_json")

            if result.knowledge_item is not None or result.knowledge_relation is not None:
                payload = proposal.payload_json or {}
                data = dict(payload)
                if result.knowledge_item is not None:
                    data["resulting_knowledge_item_id"] = result.knowledge_item.id
                if result.knowledge_relation is not None:
                    data["resulting_knowledge_relation_id"] = result.knowledge_relation.id
                data["applied_at"] = datetime.now(UTC).isoformat()
                proposal.payload_json = data
                flag_modified(proposal, "payload_json")

            try:
                UnitOfWork(self.db).commit()
            except Exception as exc:
                if result.code_patch_transaction is not None:
                    try:
                        result.code_patch_transaction.rollback()
                    except Exception as rollback_exc:
                        from .code_patch_apply import CodePatchPartialApplyError

                        UnitOfWork(self.db).rollback()
                        raise CodePatchPartialApplyError(
                            "code_patch DB update failed after file writes and file rollback failed; "
                            "proposal was not marked accepted"
                        ) from rollback_exc
                raise exc
        except ProposalApplyError as exc:
            UnitOfWork(self.db).rollback()
            from fastapi import HTTPException

            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception:
            UnitOfWork(self.db).rollback()
            raise
        self.db.refresh(proposal)

        return ProposalAcceptResult(
            proposal=proposal,
            memory=result.memory,
            policy=result.policy,
            updated_paths=result.updated_paths,
            egress_review=result.egress_review,
            task=result.task,
            agent_version=result.agent_version,
            knowledge_item=result.knowledge_item,
            knowledge_relation=result.knowledge_relation,
        )

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
        proposal.reviewed_at = datetime.now(UTC)
        self.db.commit()
        self.db.refresh(proposal)
        return proposal
