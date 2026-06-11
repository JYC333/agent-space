from __future__ import annotations
import uuid
"""
MemoryEvolver — fitness-based memory lifecycle management.

``dry_run=False`` persists **Proposal** rows only (archive / update paths).
Durable MemoryEntry mutations occur only after proposal acceptance via
``ProposalApplyService``. Fitness scores are computed in-process and are not
written back to rows (avoids silent ORM mutation during evolution).
"""

import hashlib
import math
from datetime import datetime, UTC
from typing import Optional

from sqlalchemy.orm import Session

from ..models import MemoryEntry
from .consolidation.candidate import MemoryCandidate
from .consolidation.constants import MEMORY_EVOLVER_COMPILER_VERSION
from .consolidation.proposal_producer import MemoryProposalProducer


_DECAY_LAMBDA: dict[str, float] = {
    "system": 0.0,
    "agent": 0.2,
    "user": 0.05,
    "workspace": 0.05,
    "space": 0.02,
    "capability": 0.03,
}

_ARCHIVE_THRESHOLD = 0.05


def _recency_decay(memory: MemoryEntry, now: Optional[datetime] = None) -> float:
    now = now or datetime.now(UTC)
    reference = memory.last_accessed_at or memory.created_at
    now_cmp = now.replace(tzinfo=None) if now.tzinfo else now
    ref_cmp = reference.replace(tzinfo=None) if reference.tzinfo else reference
    days = max(0.0, (now_cmp - ref_cmp).total_seconds() / 86400)
    lam = _DECAY_LAMBDA.get(memory.scope_type, 0.05)
    return math.exp(-lam * days)


def _fitness(memory: MemoryEntry, now: Optional[datetime] = None) -> float:
    importance = memory.importance or 0.5
    confidence = memory.confidence or 1.0
    recency = _recency_decay(memory, now)
    access_factor = 0.7 + 0.3 * min(
        math.log1p(memory.access_count or 0) / math.log1p(100), 1.0
    )
    return importance * confidence * recency * access_factor


def _evolver_candidate_dedupe_key(memory_id: str, op: str) -> str:
    blob = f"{memory_id}:{op}:{MEMORY_EVOLVER_COMPILER_VERSION}".encode()
    return hashlib.sha256(blob).hexdigest()


class MemoryEvolver:
    """Produces lifecycle proposals; never archives or versions memory directly."""

    def __init__(self, db: Session):
        self.db = db

    def compute_fitness_scores(self, space_id: str) -> dict[str, float]:
        """Return {memory_id: fitness_score} without mutating ``MemoryEntry`` rows."""
        now = datetime.now(UTC)
        memories = (
            self.db.query(MemoryEntry)
            .filter(
                MemoryEntry.space_id == space_id,
                MemoryEntry.status == "active",
                MemoryEntry.deleted_at.is_(None),
            )
            .all()
        )
        return {m.id: _fitness(m, now) for m in memories}

    def decay_and_archive(
        self,
        space_id: str,
        dry_run: bool = True,
        *,
        acting_user_id: str | None = None,
    ) -> dict:
        """
        dry_run=True — report archive candidates only.
        dry_run=False — create ``memory_archive`` proposals (no direct status writes).
        """
        if not dry_run and acting_user_id is None:
            raise ValueError(
                "decay_and_archive(dry_run=False) requires acting_user_id "
                "(there is no default-user fallback)."
            )
        actor = acting_user_id
        scores = self.compute_fitness_scores(space_id)
        candidates = [mid for mid, score in scores.items() if score < _ARCHIVE_THRESHOLD]

        proposal_ids: list[str] = []
        if not dry_run and candidates:
            producer = MemoryProposalProducer(self.db)
            run_id = str(uuid.uuid4())
            for mid in candidates:
                mem = (
                    self.db.query(MemoryEntry)
                    .filter(
                        MemoryEntry.id == mid,
                        MemoryEntry.space_id == space_id,
                        MemoryEntry.deleted_at.is_(None),
                    )
                    .first()
                )
                if mem is None or mem.scope_type == "system":
                    continue
                cand = MemoryCandidate(
                    candidate_type="episodic_memory",
                    space_id=space_id,
                    scope_type=mem.scope_type,
                    operation="archive",
                    suggested_layer=mem.memory_layer,
                    suggested_kind=mem.memory_kind,
                    summary=f"Archive low-fitness memory {mem.id[:8]}…",
                    provenance_entries=[
                        {
                            "source_type": "memory",
                            "source_id": mem.id,
                            "source_trust": "internal_system",
                            "evidence_json": {"channel": "memory_evolver", "fitness": scores.get(mid)},
                        }
                    ],
                    source_trust="internal_system",
                    target_memory_id=mem.id,
                    workspace_id=mem.workspace_id,
                    subject_user_id=mem.subject_user_id,
                    visibility=mem.visibility,
                    memory_type=mem.memory_type,
                    rationale="Evolver: fitness below archive threshold.",
                    dedupe_key=_evolver_candidate_dedupe_key(mem.id, "archive"),
                )
                prop = producer.create_from_candidate(
                    cand,
                    acting_user_id=actor,
                    consolidation_run_id=run_id,
                    activity_ids_for_batch=[mem.id],
                    compiler_version=MEMORY_EVOLVER_COMPILER_VERSION,
                )
                if prop is not None:
                    proposal_ids.append(prop.id)
            self.db.commit()

        return {
            "space_id": space_id,
            "dry_run": dry_run,
            "evaluated": len(scores),
            "archive_candidates": len(candidates),
            "archive_proposals": proposal_ids,
            "decay_proposals": [],  # TODO: salience / confidence memory_update proposals
        }

    def evolve_space(self, space_id: str) -> dict:
        """Dry-run fitness pass + merge/synthesize placeholders (no mutations)."""
        result = self.decay_and_archive(space_id, dry_run=True)
        result["merge_candidates"] = 0
        result["synthesize_candidates"] = 0
        result["status"] = "stub — EvoMap integration pending"
        return result
