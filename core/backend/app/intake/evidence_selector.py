"""Context selection for linked extracted evidence."""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..models import EvidenceLink, ExtractedEvidence
from .trust import evidence_trust_to_context_metadata


@dataclass(frozen=True)
class SelectedEvidence:
    evidence: ExtractedEvidence
    link: EvidenceLink


class EvidenceSelector:
    """Select context-eligible evidence through explicit active links only."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def select_for_context(
        self,
        *,
        space_id: str,
        workspace_id: str | None = None,
        project_id: str | None = None,
        run_id: str | None = None,
        limit: int = 8,
    ) -> list[SelectedEvidence]:
        targets: list[tuple[str, str | None]] = [("space", space_id)]
        if workspace_id:
            targets.append(("workspace", workspace_id))
        if project_id:
            targets.append(("project", project_id))
        if run_id:
            targets.append(("run", run_id))

        target_predicates = [
            (EvidenceLink.target_type == target_type) & (EvidenceLink.target_id == target_id)
            for target_type, target_id in targets
        ]
        if not target_predicates:
            return []

        rows = (
            self.db.query(ExtractedEvidence, EvidenceLink)
            .join(EvidenceLink, EvidenceLink.evidence_id == ExtractedEvidence.id)
            .filter(
                ExtractedEvidence.space_id == space_id,
                ExtractedEvidence.status == "active",
                ExtractedEvidence.deleted_at.is_(None),
                EvidenceLink.space_id == space_id,
                EvidenceLink.status == "active",
                EvidenceLink.link_type.in_(["context_candidate", "supports", "mentions", "provenance"]),
                or_(*target_predicates),
            )
            .order_by(EvidenceLink.confidence.desc(), ExtractedEvidence.created_at.desc())
            .limit(limit)
            .all()
        )

        seen: set[str] = set()
        selected: list[SelectedEvidence] = []
        for evidence, link in rows:
            if evidence.id in seen:
                continue
            seen.add(evidence.id)
            selected.append(SelectedEvidence(evidence=evidence, link=link))
        return selected


def evidence_ref(selected: SelectedEvidence, *, section: str = "dynamic_tail") -> dict:
    evidence = selected.evidence
    link = selected.link
    trust_metadata = evidence_trust_to_context_metadata(evidence.trust_level)
    return {
        "source_type": "evidence",
        "source_id": evidence.id,
        "evidence_type": evidence.evidence_type,
        "intake_item_id": evidence.intake_item_id,
        "source_snapshot_id": evidence.source_snapshot_id,
        "artifact_id": evidence.artifact_id,
        "link_id": link.id,
        "link_type": link.link_type,
        "target_type": link.target_type,
        "target_id": link.target_id,
        "trust_level": evidence.trust_level,
        **trust_metadata,
        "section": section,
    }
