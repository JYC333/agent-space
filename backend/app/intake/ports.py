"""Published intake seams for cross-context callers.

``ContextEvidencePort`` is the narrow contract the ``memory`` context builder
depends on to fold linked evidence into a context package. Callers resolve it via
:func:`get_context_evidence_port` instead of importing intake internals
(``EvidenceSelector`` / ``IntakeService`` / ``evidence_ref``), so intake's
internal layout — and a future TS owner of either context — can change without
breaking the seam. Migration preparation only; intake stays the authority.

This module is intentionally import-light (a dataclass + Protocol + resolver) so
``import app.intake`` does not eagerly pull in intake's heavy service layer; the
concrete provider is imported lazily inside the resolver.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from sqlalchemy.orm import Session as DBSession


@dataclass(frozen=True)
class ContextEvidenceSelection:
    """Secret-free result of selecting one evidence item for a context build.

    ``item`` is the ``ContextPackage.evidence_items`` entry; ``ref`` is the
    matching source ref appended to the dynamic-tail and source ref lists.
    """

    item: dict
    ref: dict


@runtime_checkable
class ContextEvidencePort(Protocol):
    """Select context-eligible evidence and record its used-in-context links."""

    def select_for_context(
        self,
        *,
        space_id: str,
        workspace_id: str | None,
        project_id: str | None,
        run_id: str | None,
    ) -> list[ContextEvidenceSelection]:
        ...


def get_context_evidence_port(db: "DBSession") -> ContextEvidencePort:
    """Resolve the active context-evidence authority (intake-owned today)."""

    from .context_evidence import IntakeContextEvidenceProvider

    return IntakeContextEvidenceProvider(db)


__all__ = [
    "ContextEvidencePort",
    "ContextEvidenceSelection",
    "get_context_evidence_port",
]
