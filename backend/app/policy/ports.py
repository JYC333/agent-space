"""Interface-only seam over the active policy enforcement gateway.

``PolicyPort`` is a structural (``typing.Protocol``) contract describing the two
enforcement entrypoints cross-module callers use for sensitive actions and the
proposal-apply gate. During the TS migration the active implementation is
resolved through ``get_policy_port(db)``: Python ``PolicyGateway`` remains the
local implementation and a TS-backed gateway is used after the policy authority
flip.

The port exists so that callers can type-annotate against the seam and tests can
substitute a fake (see ``tests/support/fake_policy.py``) that records or scripts
decisions without a database. It is the model-/runtime-side analogue of the
existing ``providers.ProviderAdapter`` and ``runtimes.BaseRuntimeAdapter`` ports.

This is a migration seam only — enforcement semantics live in the active
authority (hard invariants → ``PolicyEngine``/TS port → durable audit). See
``.agent/architecture/TS_MIGRATION_STRATEGY.md``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional, Protocol, runtime_checkable

if TYPE_CHECKING:
    from .decisions import PolicyDecision
    from .gateway import PolicyCheckRequest


@runtime_checkable
class PolicyPort(Protocol):
    """The sensitive-action enforcement contract.

    Mirrors :class:`app.policy.gateway.PolicyGateway`. Implementations return a
    ``PolicyDecision`` on ALLOW and raise ``PolicyGateBlocked`` on DENY /
    REQUIRE_APPROVAL (the ``PolicyAuditPersistError`` failure mode is an
    implementation concern of the concrete gateway, not part of this seam).
    """

    def enforce(self, req: "PolicyCheckRequest") -> "PolicyDecision":
        ...

    def enforce_proposal_apply(
        self,
        user_id: str,
        space_id: str,
        proposal: Any,
        metadata_json: Optional[dict[str, Any]] = None,
    ) -> "PolicyDecision":
        ...


__all__ = ["PolicyPort"]
