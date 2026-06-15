"""Intake-owned provider for context-build evidence selection.

This is the concrete implementation behind ``intake.ContextEvidencePort``. It
encapsulates the evidence-selection + usage-link-recording + ref-shaping that the
``memory`` context builder previously performed by importing intake internals
(``EvidenceSelector`` / ``IntakeService`` / ``evidence_ref``) directly.

Keeping it intake-owned is a Stage 6 migration seam: when the context builder
moves to TypeScript it calls this through the published port, never reaching into
intake's internal modules. Behavior is unchanged from the inlined version.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .evidence_selector import EvidenceSelector, evidence_ref
from .ports import ContextEvidenceSelection
from .service import IntakeService

if TYPE_CHECKING:
    from sqlalchemy.orm import Session as DBSession


class IntakeContextEvidenceProvider:
    """Selects context-eligible evidence and records its used-in-context links."""

    def __init__(self, db: "DBSession") -> None:
        self.db = db

    def select_for_context(
        self,
        *,
        space_id: str,
        workspace_id: str | None,
        project_id: str | None,
        run_id: str | None,
    ) -> list[ContextEvidenceSelection]:
        selected_evidence = EvidenceSelector(self.db).select_for_context(
            space_id=space_id,
            workspace_id=workspace_id,
            project_id=project_id,
            run_id=run_id,
        )
        intake_service = IntakeService(self.db)
        out: list[ContextEvidenceSelection] = []
        for selected in selected_evidence:
            ev = selected.evidence
            if run_id:
                intake_service.create_evidence_link(
                    space_id=space_id,
                    evidence_id=ev.id,
                    target_type="run",
                    target_id=run_id,
                    link_type="used_in_context",
                    status="active",
                    created_by_run_id=run_id,
                )
            ref = evidence_ref(selected, section="dynamic_tail")
            item = {
                "id": ev.id,
                "title": ev.title,
                "content_excerpt": ev.content_excerpt,
                "evidence_type": ev.evidence_type,
                "trust_level": ev.trust_level,
                "source_uri": ev.source_uri,
                "artifact_id": ev.artifact_id,
                "link_id": selected.link.id,
                "target_type": selected.link.target_type,
                "target_id": selected.link.target_id,
            }
            out.append(ContextEvidenceSelection(item=item, ref=ref))
        return out


__all__ = ["IntakeContextEvidenceProvider"]
