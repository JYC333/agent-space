"""Public facade for the ``proposals`` module — the governance read/approve API.

Re-exports the symbols other modules import from ``proposals`` today
(``home``, ``tasks``, ``sessions``, ``knowledge``, ``memory``, ``runs``,
``activity``, ``agents``). Callers should depend on ``app.proposals`` rather
than ``proposals.read_model`` / ``proposals.approvals``.

Also exports the proposal applier registry public API
(``applier_registry``): proposal-owning modules import these types to
register their appliers via ``register_proposal_appliers(registry)`` — see
``app.modules.registry.register_proposal_appliers``. The registry owns apply
dispatch mechanics only; approval governance stays with the policy gate and
``ProposalService.accept``.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

from .applier_registry import (
    DuplicateProposalApplierError,
    InvalidProposalApplierError,
    ProposalApplier,
    ProposalApplierKey,
    ProposalApplierRegistry,
    ProposalApplierRegistryError,
    ProposalApplyContext,
    ProposalApplyError,
    ProposalApplyResult,
    UnknownProposalApplierError,
)
from .applier_registry import get_registry as get_proposal_applier_registry
from .approvals import (
    PersonalMemoryEgressApprovalError,
    is_grant_derived_proposal,
    validate_egress_granting_user_approval,
)
from .read_model import (
    compute_proposal_expired,
    proposal_to_out,
    proposal_to_summary_out,
)

_LAZY_EXPORTS: dict[str, str] = {
    "ApplyResult": "apply_service",
    "FollowUpTaskProposalApplier": "apply_service",
    "MemoryApplyResult": "apply_service",
    "MemoryProposalApplier": "apply_service",
    "PolicyApplyResult": "apply_service",
    "PolicyProposalApplier": "apply_service",
    "ProposalApplyService": "apply_service",
    "ProposalAcceptResult": "service",
    "ProposalService": "service",
    "build_egress_review_proposal": "service",
    "build_memory_create_proposal": "service",
    "build_memory_update_proposal": "service",
    "validate_proposal_review_fields": "service",
}

__all__ = [
    "compute_proposal_expired",
    "proposal_to_out",
    "proposal_to_summary_out",
    "PersonalMemoryEgressApprovalError",
    "is_grant_derived_proposal",
    "validate_egress_granting_user_approval",
    "DuplicateProposalApplierError",
    "InvalidProposalApplierError",
    "ProposalApplier",
    "ProposalApplierKey",
    "ProposalApplierRegistry",
    "ProposalApplierRegistryError",
    "ProposalApplyContext",
    "ProposalApplyError",
    "ProposalApplyResult",
    "UnknownProposalApplierError",
    "get_proposal_applier_registry",
] + sorted(_LAZY_EXPORTS)


def __getattr__(name: str) -> Any:
    submodule = _LAZY_EXPORTS.get(name)
    if submodule is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = importlib.import_module(f".{submodule}", __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))


if TYPE_CHECKING:
    from .apply_service import (
        ApplyResult as ApplyResult,
        FollowUpTaskProposalApplier as FollowUpTaskProposalApplier,
        MemoryApplyResult as MemoryApplyResult,
        MemoryProposalApplier as MemoryProposalApplier,
        PolicyApplyResult as PolicyApplyResult,
        PolicyProposalApplier as PolicyProposalApplier,
        ProposalApplyService as ProposalApplyService,
    )
    from .service import (
        ProposalAcceptResult as ProposalAcceptResult,
        ProposalService as ProposalService,
        build_egress_review_proposal as build_egress_review_proposal,
        build_memory_create_proposal as build_memory_create_proposal,
        build_memory_update_proposal as build_memory_update_proposal,
        validate_proposal_review_fields as validate_proposal_review_fields,
    )
