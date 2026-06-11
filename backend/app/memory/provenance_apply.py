from __future__ import annotations
import uuid

from typing import Any, Iterable

from sqlalchemy.orm import Session

from ..models import MemoryRelation, ProvenanceLink


def _new_id() -> str:
    return str(uuid.uuid4())


TARGET_MEMORY = "memory"
TARGET_POLICY = "policy"
TARGET_KNOWLEDGE = "knowledge"

# Values accepted by the ProvenanceLink.source_type CHECK constraint.
_VALID_PROVENANCE_SOURCE_TYPES = frozenset(
    {
        "activity",
        "proposal",
        "memory",
        "artifact",
        "run_step",
        "external_source",
        "user_confirmation",
        "intake_item",
        "source_snapshot",
        "extracted_evidence",
        "run_event",
    }
)


def source_refs_to_provenance_entries(source_refs: Any) -> list[dict[str, Any]]:
    """Normalise free-form ``source_refs`` pointers into ProvenanceLink entries.

    ``source_refs`` carry internal provenance pointers (e.g.
    ``{"type": "activity", "id": <id>, "source_trust": ...}``). Entries whose
    type is not a valid ProvenanceLink ``source_type`` are skipped rather than
    forced into an invalid row.
    """
    entries: list[dict[str, Any]] = []
    for ref in source_refs or []:
        if not isinstance(ref, dict):
            continue
        st = ref.get("source_type") or ref.get("type")
        sid = ref.get("source_id") or ref.get("id")
        if not isinstance(st, str) or not isinstance(sid, str):
            continue
        if st not in _VALID_PROVENANCE_SOURCE_TYPES:
            continue
        trust = ref.get("source_trust")
        evidence = ref.get("evidence_json")
        entries.append(
            {
                "source_type": st,
                "source_id": sid,
                "source_trust": trust if isinstance(trust, str) else None,
                "evidence_json": evidence if isinstance(evidence, dict) else None,
            }
        )
    return entries


def write_provenance_links(
    db: Session,
    *,
    space_id: str,
    target_type: str,
    target_id: str,
    entries: Iterable[dict[str, Any]],
) -> int:
    """Insert provenance rows; returns count inserted."""
    n = 0
    for e in entries:
        st = e.get("source_type")
        sid = e.get("source_id")
        if not isinstance(st, str) or not isinstance(sid, str):
            continue
        db.add(
            ProvenanceLink(
                id=_new_id(),
                space_id=space_id,
                target_type=target_type,
                target_id=target_id,
                source_type=st,
                source_id=sid,
                source_trust=e.get("source_trust") if isinstance(e.get("source_trust"), str) else None,
                evidence_json=e.get("evidence_json") if isinstance(e.get("evidence_json"), dict) else None,
            )
        )
        n += 1
    return n


def copy_provenance_to_memory(
    db: Session,
    *,
    space_id: str,
    from_memory_id: str,
    to_memory_id: str,
) -> int:
    rows = (
        db.query(ProvenanceLink)
        .filter(
            ProvenanceLink.space_id == space_id,
            ProvenanceLink.target_type == TARGET_MEMORY,
            ProvenanceLink.target_id == from_memory_id,
        )
        .all()
    )
    n = 0
    for pl in rows:
        db.add(
            ProvenanceLink(
                id=_new_id(),
                space_id=space_id,
                target_type=TARGET_MEMORY,
                target_id=to_memory_id,
                source_type=pl.source_type,
                source_id=pl.source_id,
                source_trust=pl.source_trust,
                evidence_json=dict(pl.evidence_json) if pl.evidence_json else None,
            )
        )
        n += 1
    return n


def record_memory_supersedes_relation(
    db: Session,
    *,
    space_id: str,
    new_memory_id: str,
    old_memory_id: str,
    proposal_id: str,
) -> None:
    db.add(
        MemoryRelation(
            id=_new_id(),
            space_id=space_id,
            source_type=TARGET_MEMORY,
            source_id=new_memory_id,
            target_type=TARGET_MEMORY,
            target_id=old_memory_id,
            relation_type="supersedes",
            created_from_proposal_id=proposal_id,
        )
    )
