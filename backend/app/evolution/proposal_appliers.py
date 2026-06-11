"""Evolution-owned proposal appliers — registration hook for the proposal registry.

The evolution module owns the apply business logic for ``prompt_update``:
create a new CapabilityVersion plus prompt-revision CapabilityOverlay through
:class:`app.evolution.services.CapabilityVersioningService`. Apply-time
failures are wrapped in ``ProposalApplyError`` exactly as the pre-registry
central dispatch did, so the accept boundary keeps mapping them to HTTP 422.

Wired through ``app.modules.registry.register_proposal_appliers``. The applier
runs inside the accept transaction owned by ``ProposalService.accept`` and
must not commit; approval governance stays at the policy gate.
"""

from __future__ import annotations

from ..proposals import (
    ProposalApplierRegistry,
    ProposalApplyContext,
    ProposalApplyError,
    ProposalApplyResult,
)


def _apply_prompt_update(context: ProposalApplyContext) -> ProposalApplyResult:
    try:
        from .services import CapabilityVersioningService

        applied = CapabilityVersioningService(context.db).apply_prompt_update(context.proposal)
    except Exception as exc:  # noqa: BLE001
        raise ProposalApplyError(str(exc)) from exc
    return ProposalApplyResult(
        proposal=context.proposal,
        capability_version=applied.version,
        capability_overlay=applied.overlay,
    )


def register_proposal_appliers(registry: ProposalApplierRegistry) -> None:
    """Register every evolution-owned proposal applier."""
    registry.register("prompt_update", _apply_prompt_update)
