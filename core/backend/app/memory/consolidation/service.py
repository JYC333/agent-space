from __future__ import annotations
import uuid

import logging
from dataclasses import dataclass, field
from datetime import datetime, UTC
from types import SimpleNamespace
from typing import Sequence

from sqlalchemy.orm import Session

from ...db_uow import UnitOfWork
from ...models import ActivityRecord, Proposal
from .classifier import DefaultRuleBasedMemoryCandidateClassifier, MemoryCandidateClassifier
from .constants import CONSOLIDATION_COMPILER_VERSION
from .proposal_producer import MemoryProposalProducer
from .validator import MemoryCandidateValidator

log = logging.getLogger(__name__)


def _new_run_id() -> str:
    return str(uuid.uuid4())


@dataclass
class ConsolidationRunResult:
    consolidation_run_id: str
    proposals_created: list[str] = field(default_factory=list)
    activities_processed: list[str] = field(default_factory=list)
    activities_skipped: list[str] = field(default_factory=list)
    activities_failed: list[str] = field(default_factory=list)


class ActivityConsolidationService:
    """Selects pending Activity rows, classifies, validates, produces proposals only."""

    def __init__(
        self,
        db: Session,
        *,
        classifier: MemoryCandidateClassifier | None = None,
    ) -> None:
        self._db = db
        self._classifier: MemoryCandidateClassifier = classifier or DefaultRuleBasedMemoryCandidateClassifier()

    def run_pending(
        self,
        *,
        space_id: str,
        acting_user_id: str,
        batch_limit: int = 50,
        activity_ids: Sequence[str] | None = None,
    ) -> ConsolidationRunResult:
        run_id = _new_run_id()
        result = ConsolidationRunResult(consolidation_run_id=run_id)

        q = self._db.query(ActivityRecord).filter(
            ActivityRecord.space_id == space_id,
            ActivityRecord.consolidation_status == "pending",
        )
        if activity_ids:
            q = q.filter(ActivityRecord.id.in_(list(activity_ids)))
        rows = q.order_by(ActivityRecord.created_at.asc()).limit(batch_limit).all()

        keyfn = lambda r: (r.workspace_id or "", r.session_id or "", r.source_run_id or "")
        rows_sorted = sorted(rows, key=keyfn)
        activity_snapshots = [self._activity_snapshot(row) for row in rows_sorted]
        UnitOfWork(self._db).commit()

        validator = MemoryCandidateValidator(space_id=space_id, acting_user_id=acting_user_id)
        producer = MemoryProposalProducer(self._db)

        for record in activity_snapshots:
            aid = record.id
            try:
                created_ids: list[str] = []
                candidates = self._classifier.classify(
                    record, compiler_version=CONSOLIDATION_COMPILER_VERSION
                )
                if not candidates:
                    self._mark_activity_consolidation(aid, "skipped")
                    result.activities_skipped.append(aid)
                    continue

                any_reviewable = False
                for cand in candidates:
                    vr = validator.validate(cand)
                    if vr.decision in ("reject", "preview_only"):
                        continue
                    any_reviewable = True
                    prop = producer.create_from_candidate(
                        cand,
                        acting_user_id=acting_user_id,
                        consolidation_run_id=run_id,
                        activity_ids_for_batch=sorted({*cand.source_activity_ids, aid}),
                        compiler_version=CONSOLIDATION_COMPILER_VERSION,
                    )
                    if prop is not None:
                        created_ids.append(prop.id)

                if not created_ids:
                    self._mark_activity_consolidation(aid, "skipped")
                    result.activities_skipped.append(aid)
                    continue

                self._mark_activity_consolidation(aid, "proposals_generated")

                result.proposals_created.extend(created_ids)
                result.activities_processed.append(aid)
            except Exception:
                log.exception("activity consolidation failed for %s", aid)
                UnitOfWork(self._db).rollback()
                self._mark_activity_consolidation(aid, "failed")
                result.activities_failed.append(aid)

        return result

    def _mark_activity_consolidation(self, activity_id: str, consolidation_status: str) -> None:
        """Update consolidation_status and keep user-visible status in sync.

        consolidation_status values and their status mapping:
          proposals_generated → status = proposals_generated
          skipped             → status = processed (no proposals but processing ran cleanly)
          failed              → status unchanged
        """
        row = self._db.query(ActivityRecord).filter(ActivityRecord.id == activity_id).first()
        if row:
            row.consolidation_status = consolidation_status
            row.processed_at = datetime.now(UTC)
            if consolidation_status == "proposals_generated":
                row.status = "proposals_generated"
            elif consolidation_status == "skipped":
                if row.status not in ("proposals_generated", "archived"):
                    row.status = "processed"
            UnitOfWork(self._db).commit()

    @staticmethod
    def _activity_snapshot(record: ActivityRecord) -> SimpleNamespace:
        return SimpleNamespace(
            **{
                attr.key: getattr(record, attr.key)
                for attr in ActivityRecord.__mapper__.column_attrs
            }
        )

    def run_for_activity_ids(
        self,
        space_id: str,
        activity_ids: Sequence[str],
        *,
        acting_user_id: str,
    ) -> list[Proposal]:
        """Run consolidation for explicit ids; returns new Proposal ORM rows."""
        out = self.run_pending(
            space_id=space_id,
            acting_user_id=acting_user_id,
            batch_limit=max(len(activity_ids), 1),
            activity_ids=activity_ids,
        )
        if not out.proposals_created:
            return []
        return (
            self._db.query(Proposal)
            .filter(Proposal.id.in_(out.proposals_created))
            .order_by(Proposal.created_at.asc())
            .all()
        )


def run_memory_consolidation_job_payload(*, db: Session, payload: dict) -> dict:
    """Synchronous job body used by ``memory_consolidation`` queue handler."""
    space_id = str(payload.get("space_id") or "")
    user_id = str(payload.get("user_id") or "")
    if not space_id:
        raise ValueError("memory_consolidation job payload is missing space_id")
    if not user_id:
        raise ValueError("memory_consolidation job payload is missing user_id")
    batch_limit = int(payload.get("batch_limit") or 50)
    raw_ids = payload.get("activity_ids")
    activity_ids: list[str] | None = None
    if isinstance(raw_ids, list) and raw_ids:
        activity_ids = [str(x) for x in raw_ids]
    svc = ActivityConsolidationService(db)
    res = svc.run_pending(
        space_id=space_id,
        acting_user_id=user_id,
        batch_limit=batch_limit,
        activity_ids=activity_ids,
    )
    return {
        "consolidation_run_id": res.consolidation_run_id,
        "proposals_created": res.proposals_created,
        "activities_processed": res.activities_processed,
        "activities_skipped": res.activities_skipped,
        "activities_failed": res.activities_failed,
    }
