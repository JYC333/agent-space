from __future__ import annotations
"""
MemoryProposalService — manage the proposal → approval → active memory workflow.
"""

from datetime import datetime, UTC
from typing import Optional
from ulid import ULID
from sqlalchemy.orm import Session

from ..models import MemoryProposal
from ..schemas import MemoryCreate, ProposalOut
from ..config import settings


def _new_id() -> str:
    return str(ULID())


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
    ) -> MemoryProposal:
        proposal = MemoryProposal(
            id=_new_id(),
            space_id=space_id,
            user_id=user_id,
            workspace_id=workspace_id,
            source_session_id=source_session_id,
            source_task_id=source_task_id,
            source_run_id=source_run_id,
            target_scope=target_scope,
            target_namespace=target_namespace,
            memory_type=memory_type,
            proposed_title=proposed_title,
            proposed_content=proposed_content,
            rationale=rationale,
            status="pending",
        )
        self.db.add(proposal)
        self.db.commit()
        self.db.refresh(proposal)
        return proposal

    def count_proposals(self, space_id: str, user_id: str, status: str | None = "pending") -> int:
        from sqlalchemy import func as _func
        q = self.db.query(_func.count(MemoryProposal.id)).filter(
            MemoryProposal.space_id == space_id,
            MemoryProposal.user_id == user_id,
        )
        if status:
            q = q.filter(MemoryProposal.status == status)
        return q.scalar() or 0

    def list_proposals(
        self,
        space_id: str,
        user_id: str,
        status: str | None = "pending",
        limit: int = 50,
        offset: int = 0,
    ) -> list[MemoryProposal]:
        q = self.db.query(MemoryProposal).filter(
            MemoryProposal.space_id == space_id,
            MemoryProposal.user_id == user_id,
        )
        if status:
            q = q.filter(MemoryProposal.status == status)
        return q.order_by(MemoryProposal.created_at.desc()).offset(offset).limit(limit).all()

    def get(self, proposal_id: str) -> MemoryProposal | None:
        return self.db.query(MemoryProposal).filter(MemoryProposal.id == proposal_id).first()

    def accept(
        self,
        proposal_id: str,
        space_id: str,
        user_id: str,
    ) -> tuple[MemoryProposal, "Memory"] | None:
        from .store import MemoryStore
        from ..models import Memory

        proposal = self.get(proposal_id)
        if not proposal or proposal.status != "pending":
            return None
        if proposal.space_id != space_id or proposal.user_id != user_id:
            return None

        # Create the memory
        store = MemoryStore(self.db)
        mem_data = MemoryCreate(
            title=proposal.proposed_title,
            content=proposal.proposed_content,
            type=proposal.memory_type,
            scope=proposal.target_scope,
            namespace=proposal.target_namespace,
            space_id=proposal.space_id,
            owner_user_id=proposal.user_id,
            workspace_id=proposal.workspace_id,
        )
        memory = store.create(mem_data, created_by=user_id)

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
    ) -> MemoryProposal | None:
        proposal = self.get(proposal_id)
        if not proposal or proposal.status != "pending":
            return None
        if proposal.space_id != space_id or proposal.user_id != user_id:
            return None

        proposal.status = "rejected"
        proposal.decided_at = datetime.now(UTC)
        self.db.commit()
        self.db.refresh(proposal)
        return proposal
