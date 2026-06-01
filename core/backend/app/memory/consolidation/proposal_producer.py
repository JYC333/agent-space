from __future__ import annotations
import uuid

import hashlib
import json
from sqlalchemy.orm import Session

from ...models import Proposal
from ..proposal_payload import merge_distinct_provenance_entries, strip_flat_provenance_keys
from ..source_monitoring import SourceMonitoringService, monitoring_snapshot
from .candidate import MemoryCandidate
from .constants import CONSOLIDATION_COMPILER_VERSION


def _new_id() -> str:
    return str(uuid.uuid4())


def _memory_candidate_hash(candidate: MemoryCandidate) -> str:
    d = {
        "candidate_type": candidate.candidate_type,
        "space_id": candidate.space_id,
        "operation": candidate.operation,
        "memory_type": candidate.memory_type,
        "suggested_layer": candidate.suggested_layer,
        "suggested_kind": candidate.suggested_kind,
        "summary": (candidate.summary or "")[:2000],
        "content": (candidate.content or "")[:2000],
        "entity_refs": candidate.entity_refs,
        "source_activity_ids": sorted(candidate.source_activity_ids),
    }
    blob = json.dumps(d, sort_keys=True, default=str).encode()
    return hashlib.sha256(blob).hexdigest()


def _activity_batch_hash(activity_ids: list[str]) -> str:
    blob = json.dumps(sorted(activity_ids), separators=(",", ":")).encode()
    return hashlib.sha256(blob).hexdigest()


def _proposal_dedupe_key(
    *,
    space_id: str,
    activity_ids: list[str],
    candidate: MemoryCandidate,
    compiler_version: str,
) -> str:
    payload = {
        "space_id": space_id,
        "activity_ids": sorted(activity_ids),
        "candidate_type": candidate.candidate_type,
        "suggested_layer": candidate.suggested_layer,
        "suggested_kind": candidate.suggested_kind,
        "operation": candidate.operation,
        "summary": (candidate.summary or "")[:4000],
        "content": (candidate.content or "")[:4000],
        "entity_refs": candidate.entity_refs,
        "compiler_version": compiler_version,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def proposal_blocks_on_dedupe(
    db: Session,
    *,
    space_id: str,
    proposal_dedupe_key: str,
) -> bool:
    rows = (
        db.query(Proposal)
        .filter(
            Proposal.space_id == space_id,
            Proposal.status.in_(("pending", "accepted")),
            Proposal.proposal_type.in_(
                ("memory_create", "memory_update", "memory_archive", "policy_change")
            ),
        )
        .all()
    )
    for r in rows:
        p = r.payload_json or {}
        if p.get("proposal_dedupe_key") == proposal_dedupe_key:
            return True
    return False


class MemoryProposalProducer:
    """Turns validated candidates into persisted Proposal rows only."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def create_from_candidate(
        self,
        candidate: MemoryCandidate,
        *,
        acting_user_id: str,
        consolidation_run_id: str,
        activity_ids_for_batch: list[str],
        compiler_version: str = CONSOLIDATION_COMPILER_VERSION,
    ) -> Proposal | None:
        prov = merge_distinct_provenance_entries(candidate.provenance_entries)
        proposal_dedupe_key = _proposal_dedupe_key(
            space_id=candidate.space_id,
            activity_ids=activity_ids_for_batch,
            candidate=candidate,
            compiler_version=compiler_version,
        )
        if proposal_blocks_on_dedupe(self._db, space_id=candidate.space_id, proposal_dedupe_key=proposal_dedupe_key):
            return None

        mch = _memory_candidate_hash(candidate)
        batch_hash = _activity_batch_hash(activity_ids_for_batch)
        monitor = SourceMonitoringService()
        risk = candidate.risk_level or "low"

        if candidate.candidate_type == "policy_candidate" or candidate.operation == "policy_change":
            pol = dict(candidate.policy_payload or {})
            pol.setdefault("operation", "create")
            pol.setdefault("domain", "memory")
            pol["provenance_entries"] = prov
            pol["source_trust"] = candidate.source_trust
            pol["proposal_dedupe_key"] = proposal_dedupe_key
            pol["memory_candidate_hash"] = mch
            pol["activity_batch_hash"] = batch_hash
            pol["consolidation_run_id"] = consolidation_run_id
            pol["compiler_version"] = compiler_version
            pol["candidate_dedupe_key"] = candidate.dedupe_key
            pol.setdefault("risk_level", risk)
            out = monitor.evaluate_policy_proposal(payload=pol, accept_context="direct_apply")
            pol["source_monitoring_result"] = monitoring_snapshot(out)
            pol = strip_flat_provenance_keys(pol)
            prop = Proposal(
                id=_new_id(),
                space_id=candidate.space_id,
                proposal_type="policy_change",
                status="pending",
                title=candidate.summary or "Policy change",
                summary=candidate.summary,
                payload_json=pol,
                rationale=candidate.rationale or "Consolidation policy candidate.",
                workspace_id=candidate.workspace_id,
                created_by_user_id=acting_user_id,
                risk_level="high",
                required_approver_role="admin",
            )
            self._db.add(prop)
            return prop

        if candidate.operation == "archive":
            if not candidate.target_memory_id:
                return None
            payload: dict[str, Any] = {
                "operation": "archive",
                "target_memory_id": candidate.target_memory_id,
                "target_layer": candidate.suggested_layer,
                "memory_kind": candidate.suggested_kind,
                "target_scope": candidate.scope_type,
                "target_namespace": candidate.suggested_kind or "user.default",
                "provenance_entries": prov,
                "source_trust": candidate.source_trust,
                "entity_refs": candidate.entity_refs or None,
                "relation_refs": candidate.relation_refs or None,
                "risk_level": risk,
                "proposal_dedupe_key": proposal_dedupe_key,
                "memory_candidate_hash": mch,
                "activity_batch_hash": batch_hash,
                "consolidation_run_id": consolidation_run_id,
                "compiler_version": compiler_version,
                "candidate_dedupe_key": candidate.dedupe_key,
                "event_time": candidate.event_time.isoformat() if candidate.event_time else None,
                "event_type": candidate.event_type,
            }
            out = monitor.evaluate_memory_proposal(
                proposal_type="memory_archive",
                payload=payload,
                accept_context="direct_apply",
            )
            payload["source_monitoring_result"] = monitoring_snapshot(out)
            payload = strip_flat_provenance_keys(payload)
            prop = Proposal(
                id=_new_id(),
                space_id=candidate.space_id,
                proposal_type="memory_archive",
                status="pending",
                title=candidate.summary or "Archive memory",
                summary=candidate.summary,
                payload_json=payload,
                rationale=candidate.rationale,
                workspace_id=candidate.workspace_id,
                created_by_user_id=acting_user_id,
                risk_level=risk,
            )
            self._db.add(prop)
            return prop

        if candidate.operation == "update":
            if not candidate.target_memory_id:
                return None
            payload = {
                "operation": "update",
                "target_memory_id": candidate.target_memory_id,
                "proposed_content": candidate.content or "",
                "proposed_title": candidate.summary,
                "title": candidate.summary,
                "content": candidate.content,
                "memory_type": candidate.memory_type,
                "target_layer": candidate.suggested_layer,
                "memory_kind": candidate.suggested_kind,
                "target_scope": candidate.scope_type,
                "target_namespace": candidate.suggested_kind or "user.default",
                "target_visibility": candidate.visibility,
                "provenance_entries": prov,
                "source_trust": candidate.source_trust,
                "entity_refs": candidate.entity_refs or None,
                "relation_refs": candidate.relation_refs or None,
                "risk_level": risk,
                "proposal_dedupe_key": proposal_dedupe_key,
                "memory_candidate_hash": mch,
                "activity_batch_hash": batch_hash,
                "consolidation_run_id": consolidation_run_id,
                "compiler_version": compiler_version,
                "candidate_dedupe_key": candidate.dedupe_key,
                "event_time": candidate.event_time.isoformat() if candidate.event_time else None,
                "event_type": candidate.event_type,
            }
            out = monitor.evaluate_memory_proposal(
                proposal_type="memory_update",
                payload=payload,
                accept_context="direct_apply",
            )
            payload["source_monitoring_result"] = monitoring_snapshot(out)
            payload = strip_flat_provenance_keys(payload)
            prop = Proposal(
                id=_new_id(),
                space_id=candidate.space_id,
                proposal_type="memory_update",
                status="pending",
                title=candidate.summary or "Memory update",
                summary=candidate.summary,
                payload_json=payload,
                rationale=candidate.rationale,
                workspace_id=candidate.workspace_id,
                created_by_user_id=acting_user_id,
                risk_level=risk,
            )
            self._db.add(prop)
            return prop

        # create path (memory_create)
        namespace = f"user.default.{candidate.memory_type}"
        if candidate.suggested_kind:
            namespace = f"user.default.{candidate.suggested_kind}"
        payload = {
            "operation": "create",
            "proposed_content": candidate.content or "",
            "content": candidate.content,
            "memory_type": candidate.memory_type,
            "target_layer": candidate.suggested_layer,
            "memory_kind": candidate.suggested_kind,
            "target_scope": candidate.scope_type,
            "target_namespace": namespace,
            "target_visibility": candidate.visibility,
            "sensitivity_level": "normal",
            "provenance_entries": prov,
            "source_trust": candidate.source_trust,
            "entity_refs": candidate.entity_refs or None,
            "relation_refs": candidate.relation_refs or None,
            "risk_level": risk,
            "proposal_dedupe_key": proposal_dedupe_key,
            "memory_candidate_hash": mch,
            "activity_batch_hash": batch_hash,
            "consolidation_run_id": consolidation_run_id,
            "compiler_version": compiler_version,
            "candidate_dedupe_key": candidate.dedupe_key,
            "event_time": candidate.event_time.isoformat() if candidate.event_time else None,
            "event_type": candidate.event_type,
        }
        if candidate.subject_user_id:
            payload["subject_user_id"] = candidate.subject_user_id
        ptype = "memory_create"
        out = monitor.evaluate_memory_proposal(
            proposal_type=ptype,
            payload=payload,
            accept_context="direct_apply",
        )
        payload["source_monitoring_result"] = monitoring_snapshot(out)
        payload = strip_flat_provenance_keys(payload)
        prop = Proposal(
            id=_new_id(),
            space_id=candidate.space_id,
            proposal_type=ptype,
            status="pending",
            title=candidate.summary or "Memory create",
            summary=candidate.summary,
            payload_json=payload,
            rationale=candidate.rationale,
            workspace_id=candidate.workspace_id,
            created_by_user_id=acting_user_id,
            risk_level=risk,
        )
        self._db.add(prop)
        return prop
