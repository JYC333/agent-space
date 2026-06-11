"""Space-created lifecycle dispatch.

When a new ``Space`` row exists (OAuth/login, ``POST /spaces``, system_core),
modules that need to initialize per-space state run their ``on_space_created``
hooks. This module owns **only** the dispatch mechanics — it holds no business
seeding logic and must **not** import product modules (``memory``,
``execution_planes``, ``knowledge``, ``capabilities``, ``workspace_profiles``,
``providers``, ``agents`` …). Each owning module keeps its seeding logic and
registers a hook by exposing ``register_space_created_hooks(registry)`` (see
``app.modules.registry.register_space_created_hooks``).

The DB may stay empty until the first login; nothing runs at app import time.
``on_space_created`` is invoked synchronously inside the caller's open DB
transaction (after the ``Space``/``SpaceMembership`` rows are flushed, before the
caller's single ``commit``). Hooks add rows through ``context.db`` and must not
commit; a hook that raises propagates unchanged, so the surrounding transaction
is never committed and the whole space creation rolls back atomically.

Hooks are **synchronous**. ``context.db`` is a sync, thread-bound SQLAlchemy
``Session`` that participates in the caller's open transaction; running a hook on
another thread (to drive an event loop) would share that Session across threads,
which is unsafe. Async hooks are therefore not supported — ``run`` rejects a hook
that returns an awaitable rather than silently leaking an un-awaited coroutine.
"""

from __future__ import annotations

import inspect
import logging
from dataclasses import dataclass
from typing import Callable

from sqlalchemy.orm import Session

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Context passed to every hook
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SpaceCreatedContext:
    """Everything a space-created hook needs to initialize per-space state.

    ``db`` is the caller's *open* session inside the space-creation transaction
    — hooks add rows to it and must not commit. ``seeded_by_user_id`` is the
    acting owner's ``users.id`` (used for audit); system records are space-owned
    with ``subject_user_id`` NULL.
    """

    db: Session
    space_id: str
    seeded_by_user_id: str


# A hook receives the context and returns nothing. Synchronous — see the module
# docstring for why async hooks are not supported. Structural callable type so
# the registry never imports the ORM.
SpaceCreatedHook = Callable[[SpaceCreatedContext], None]


# ---------------------------------------------------------------------------
# Typed errors
# ---------------------------------------------------------------------------

class SpaceCreatedHookError(Exception):
    """Base class for space-created hook registry errors."""


class DuplicateSpaceCreatedHookError(SpaceCreatedHookError):
    """Raised when a hook name is registered more than once (fail fast)."""

    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"a space-created hook is already registered with name {name!r}")


class InvalidSpaceCreatedHookError(SpaceCreatedHookError):
    """Raised when a hook name or callable is invalid."""


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _RegisteredHook:
    name: str
    hook: SpaceCreatedHook
    order: int


class SpaceCreatedHookRegistry:
    """Registers and dispatches space-created hooks in a deterministic order.

    The registry owns dispatch mechanics only; it holds no business logic and
    imports no product modules. Registration is explicit (``register``) and the
    instance is cheap to construct, so tests can build an isolated registry.

    Execution order is deterministic: hooks run by ascending ``order``, then by
    name — independent of registration order. Duplicate names fail fast. Hooks
    are synchronous (see the module docstring); a hook that raises propagates
    unchanged so the caller's transaction is not committed.
    """

    def __init__(self) -> None:
        self._hooks: dict[str, _RegisteredHook] = {}

    def register(self, name: str, hook: SpaceCreatedHook, order: int = 100) -> None:
        """Register ``hook`` under ``name`` at ``order``. Duplicate names fail fast."""
        if not name or not isinstance(name, str):
            raise InvalidSpaceCreatedHookError("hook name must be a non-empty string")
        if not callable(hook):
            raise InvalidSpaceCreatedHookError(f"hook {name!r} must be callable")
        if not isinstance(order, int):
            raise InvalidSpaceCreatedHookError(f"hook {name!r} order must be an int")
        if name in self._hooks:
            raise DuplicateSpaceCreatedHookError(name)
        self._hooks[name] = _RegisteredHook(name=name, hook=hook, order=order)
        log.debug("registered space-created hook name=%s order=%d", name, order)

    def _ordered(self) -> list[_RegisteredHook]:
        return sorted(self._hooks.values(), key=lambda h: (h.order, h.name))

    def registered_hooks(self) -> list[str]:
        """Return hook names in deterministic execution order."""
        return [h.name for h in self._ordered()]

    def run(self, context: SpaceCreatedContext) -> None:
        """Invoke every registered hook in deterministic order.

        Runs synchronously inside the caller's open transaction. A hook that
        raises propagates unchanged so the surrounding transaction is not
        committed. Hooks must be synchronous: one that returns an awaitable is
        rejected (rather than silently leaking an un-awaited coroutine), because
        ``context.db`` is a thread-bound sync Session — see the module docstring.
        """
        for registered in self._ordered():
            result = registered.hook(context)
            if inspect.isawaitable(result):
                # Close the coroutine so it does not emit a "never awaited"
                # warning, then fail loudly with a clear, actionable message.
                if hasattr(result, "close"):
                    result.close()
                raise InvalidSpaceCreatedHookError(
                    f"space-created hook {registered.name!r} returned an awaitable; "
                    "async hooks are not supported (context.db is a thread-bound "
                    "sync Session) — register a synchronous hook instead"
                )

    def clear(self) -> None:
        """Drop all registrations. For test isolation only."""
        self._hooks.clear()


# ---------------------------------------------------------------------------
# Process-wide instance (lazily built from the module registry)
# ---------------------------------------------------------------------------

_registry: SpaceCreatedHookRegistry | None = None


def _build_default_registry() -> SpaceCreatedHookRegistry:
    """Build a registry populated from each module's space-created hook.

    Imported lazily so this module never imports product modules at top level.
    """
    from ..modules.registry import register_space_created_hooks

    registry = SpaceCreatedHookRegistry()
    register_space_created_hooks(registry)
    return registry


def get_registry() -> SpaceCreatedHookRegistry:
    """Return the process-wide registry, building it on first use."""
    global _registry
    if _registry is None:
        _registry = _build_default_registry()
    return _registry


def init_registry(registry: SpaceCreatedHookRegistry) -> None:
    """Publish an explicit registry for this process (overrides lazy build)."""
    global _registry
    _registry = registry


def reset_registry() -> None:
    """Drop the process-wide registry so the next call rebuilds it. Tests only."""
    global _registry
    _registry = None


def on_space_created(db: Session, space_id: str, *, seeded_by_user_id: str) -> None:
    """Run all registered space-created hooks for a newly created ``Space``.

    Dispatches through :class:`SpaceCreatedHookRegistry`; modules own their own
    initialization logic. No concrete agents are seeded per space — built-in
    behavior comes from system AgentTemplates (global factories seeded once in
    ``bootstrap``); a concrete Agent is created only on demand via
    ``AgentTemplateService.create_agent_from_template`` (copy-on-create).
    """
    context = SpaceCreatedContext(
        db=db, space_id=space_id, seeded_by_user_id=seeded_by_user_id
    )
    get_registry().run(context)
