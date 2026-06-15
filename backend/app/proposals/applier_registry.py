"""Proposal applier registry — dispatch mechanics for accepted-proposal apply.

This module owns *only* the mechanics of mapping a ``proposal_type`` string to
a registered applier callable and invoking it. It contains **no business
logic** and must **not** import product modules (``memory``, ``knowledge``,
``agents``, ``evolution``, ``policy`` …). Proposal-owning modules keep their
apply business logic and register appliers by exposing
``register_proposal_appliers(registry)`` (see
``app.modules.registry.register_proposal_appliers``).

Ownership model
---------------
- ``proposals`` owns the proposal API, read model, status lifecycle, and this
  registry (registry-facing orchestration).
- The policy gate (``app.policy.check_proposal_apply_policy``) owns approval
  authority decisions and durable audit semantics; appliers never approve
  proposals or bypass that gate.
- Target modules (``memory``, ``knowledge``, ``agents``, ``evolution``) own
  their proposal apply business logic and register it here.
- ``ProposalApplyService`` (the durable write boundary) keeps the cross-cutting
  apply orchestration — accept-context guard, grant egress approval, source
  monitoring, digest invalidation — and dispatches the type-specific write
  through this registry.

The key is the existing proposal discriminator: ``Proposal.proposal_type``
(``memory_create``, ``code_patch``, ``knowledge_update`` …). There is no
separate target/action column on the Proposal model; the type string already
encodes both. This is not an event bus: one applier per proposal type, exactly
one applier invoked per apply.

Failure semantics
-----------------
Applier exceptions propagate unchanged so the caller's existing failure
mapping is preserved (``ProposalApplyError`` → HTTP 422,
``CodePatchApplyError`` → HTTP 400, egress errors, …). An unregistered
proposal type raises :class:`UnknownProposalApplierError`, which **is a**
:class:`ProposalApplyError` carrying the pre-registry message
(``unsupported proposal type: '<type>'``) so pre-registry failure handling and
failure codes are unchanged.

Appliers may be synchronous or ``async``. Proposal apply runs on sync request
paths (the accept endpoint is a sync ``def``), so an awaitable result is
driven to completion with ``asyncio.run`` on the same thread. If an applier
returns an awaitable while an event loop is already running in this thread,
dispatch fails fast instead of deadlocking.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional, Union

from sqlalchemy.orm import Session

log = logging.getLogger(__name__)


# The registry key is the existing proposal discriminator field:
# ``Proposal.proposal_type``.
ProposalApplierKey = str


# ---------------------------------------------------------------------------
# Context and result passed across the dispatch boundary
# ---------------------------------------------------------------------------

@dataclass
class ProposalApplyContext:
    """Everything an applier needs to apply one validated, accepted proposal.

    ``db`` is the caller's *open* session inside the accept transaction —
    appliers write through it and must not commit; ``ProposalService.accept``
    owns the commit/rollback boundary. ``proposal`` is the persisted Proposal
    ORM row (typed ``Any`` so this module never imports the ORM model) and
    ``user_id`` is the approving user.
    """

    db: Session
    proposal: Any
    user_id: str


@dataclass
class ProposalApplyResult:
    """Unified apply result — one optional slot per proposal target kind.

    Mirrors the pre-registry ``ApplyResult`` shape exactly: each applier fills
    the slot(s) it owns and the proposals API maps the populated slot to the
    response ``result_type``. Slots are typed ``Any`` so the registry never
    imports product ORM models.
    """

    proposal: Any = None
    memory: Any = None
    policy: Any = None
    updated_paths: Optional[list[str]] = None
    code_patch_files: Optional[list[dict[str, Any]]] = None
    code_patch_transaction: Any = None
    egress_review: bool = False
    task: Any = None
    agent_version: Any = None
    capability_version: Any = None
    capability_overlay: Any = None
    knowledge_item: Any = None
    knowledge_relation: Any = None


# An applier receives the context and returns a ProposalApplyResult, either
# synchronously or as an awaitable. Structural callable type so the registry
# never imports product modules.
ProposalApplier = Callable[
    [ProposalApplyContext],
    Union[ProposalApplyResult, Awaitable[ProposalApplyResult]],
]


# ---------------------------------------------------------------------------
# Typed errors
# ---------------------------------------------------------------------------

class ProposalApplyError(Exception):
    """Raised when a well-formed proposal cannot be applied (e.g. missing target).

    This is the proposal apply boundary error: ``ProposalService.accept``
    rolls back and maps it to HTTP 422. Appliers raise it (or a subclass) for
    apply-time validation/business failures.
    """


class ProposalApplierRegistryError(Exception):
    """Base class for proposal-applier registry errors."""


class DuplicateProposalApplierError(ProposalApplierRegistryError):
    """Raised when a proposal_type is registered more than once (fail fast)."""

    def __init__(self, proposal_type: str) -> None:
        self.proposal_type = proposal_type
        super().__init__(
            f"an applier is already registered for proposal type {proposal_type!r}"
        )


class InvalidProposalApplierError(ProposalApplierRegistryError):
    """Raised when a registration key or applier callable is invalid."""


class UnknownProposalApplierError(ProposalApplyError, ProposalApplierRegistryError):
    """Raised when applying a proposal whose type has no registered applier.

    Subclasses :class:`ProposalApplyError` with the pre-registry message so
    existing failure handling (rollback → HTTP 422) and failure-code semantics
    are preserved exactly.
    """

    def __init__(self, proposal_type: str) -> None:
        self.proposal_type = proposal_type
        super().__init__(f"unsupported proposal type: {proposal_type!r}")


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class ProposalApplierRegistry:
    """Maps ``proposal_type`` → applier and dispatches apply calls.

    The registry owns dispatch mechanics only; it holds no business logic and
    imports no product modules. Registration is explicit (``register``) and the
    instance is cheap to construct, so tests can build an isolated registry.
    """

    def __init__(self) -> None:
        self._appliers: dict[ProposalApplierKey, ProposalApplier] = {}

    def register(self, proposal_type: ProposalApplierKey, applier: ProposalApplier) -> None:
        """Register ``applier`` for ``proposal_type``. Duplicate types fail fast."""
        if not proposal_type or not isinstance(proposal_type, str):
            raise InvalidProposalApplierError("proposal_type must be a non-empty string")
        if not callable(applier):
            raise InvalidProposalApplierError(
                f"applier for proposal type {proposal_type!r} must be callable"
            )
        if proposal_type in self._appliers:
            raise DuplicateProposalApplierError(proposal_type)
        self._appliers[proposal_type] = applier
        log.debug(
            "registered proposal applier proposal_type=%s applier=%s",
            proposal_type,
            getattr(applier, "__name__", applier),
        )

    def get(self, proposal_type: ProposalApplierKey) -> ProposalApplier | None:
        """Return the applier for ``proposal_type`` or ``None`` if unregistered."""
        return self._appliers.get(proposal_type)

    def registered_appliers(self) -> list[ProposalApplierKey]:
        """Return the sorted list of registered proposal_type keys."""
        return sorted(self._appliers)

    def apply(self, context: ProposalApplyContext) -> ProposalApplyResult:
        """Invoke the applier for ``context.proposal.proposal_type``.

        Raises :class:`UnknownProposalApplierError` when no applier is
        registered for the type. Applier exceptions propagate unchanged so the
        caller's failure mapping is preserved. Async appliers are driven with
        ``asyncio.run`` — see the module docstring.
        """
        proposal_type = context.proposal.proposal_type
        applier = self._appliers.get(proposal_type)
        if applier is None:
            raise UnknownProposalApplierError(proposal_type)

        result = applier(context)
        if inspect.isawaitable(result):
            result = self._await(proposal_type, result)
        return result

    @staticmethod
    def _await(proposal_type: str, awaitable: Awaitable[ProposalApplyResult]) -> ProposalApplyResult:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(_drive(awaitable))
        # A running loop in this thread means asyncio.run would raise and
        # blocking here would deadlock the loop — fail fast with a clear error.
        if hasattr(awaitable, "close"):
            awaitable.close()
        raise InvalidProposalApplierError(
            f"applier for proposal type {proposal_type!r} returned an awaitable "
            "while an event loop is already running in this thread; proposal "
            "apply dispatch is synchronous — call it from a worker thread "
            "without a running loop"
        )

    def clear(self) -> None:
        """Drop all registrations. For test isolation only."""
        self._appliers.clear()


async def _drive(awaitable: Awaitable[ProposalApplyResult]) -> ProposalApplyResult:
    return await awaitable


# ---------------------------------------------------------------------------
# Process-wide instance (lazily built from the module registry)
# ---------------------------------------------------------------------------

_registry: ProposalApplierRegistry | None = None


def _build_default_registry() -> ProposalApplierRegistry:
    """Build a registry populated from each module's proposal-applier hook.

    Imported lazily so this module never imports product modules at top level.
    """
    from ..modules.registry import register_proposal_appliers

    registry = ProposalApplierRegistry()
    register_proposal_appliers(registry)
    return registry


def get_registry() -> ProposalApplierRegistry:
    """Return the process-wide registry, building it on first use."""
    global _registry
    if _registry is None:
        _registry = _build_default_registry()
    return _registry


def init_registry(registry: ProposalApplierRegistry) -> None:
    """Publish an explicit registry for this process (overrides lazy build)."""
    global _registry
    _registry = registry


def reset_registry() -> None:
    """Drop the process-wide registry so the next call rebuilds it. Tests only."""
    global _registry
    _registry = None
