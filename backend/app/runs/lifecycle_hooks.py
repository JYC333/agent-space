"""Run-finalized lifecycle dispatch.

When ``PostRunFinalizationService`` finalizes a terminal ``Run`` (after the
deterministic ``RunEvaluation`` is created, before the ``RunFinalization`` row
is recorded), modules that own post-run side effects run their registered
run-finalized hooks. This module owns **only** the dispatch mechanics — it
holds no task-board or evaluation business logic and must **not** import
product modules (``tasks``, ``memory``, ``proposals`` …). Each owning module
keeps its logic and registers a hook by exposing
``register_run_finalized_hooks(registry)`` (see
``app.modules.registry.register_run_finalized_hooks``).

This is not a general event bus: it covers exactly the run-finalized lifecycle
point that previously forced ``runs`` to import ``tasks`` internals
(the RunEvaluation → TaskEvaluation bridge). ``runs`` keeps authority over the
finalization transaction; hooks write through ``context.db`` inside the
caller's open transaction and must not commit.

Failure semantics match the pre-hook behavior: a hook that raises aborts the
remaining hooks and surfaces as :class:`RunFinalizedHookFailure` carrying the
hook name; ``PostRunFinalizationService`` records a *failed* finalization with
``error_json["stage"]`` set to that hook name, exactly as the inline bridge
did with stage ``task_evaluation_bridge``.

Hooks may be synchronous or ``async``. Finalization runs on a worker thread
without a running event loop (the finalize endpoint is a sync ``def``), so an
awaitable result is driven to completion with ``asyncio.run`` on the same
thread — the thread-bound sync ``Session`` is never shared across threads. If
a hook returns an awaitable while an event loop is already running in this
thread, dispatch fails fast instead of deadlocking.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional, Union

from sqlalchemy.orm import Session

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Context passed to every hook
# ---------------------------------------------------------------------------

@dataclass
class RunFinalizedContext:
    """Everything a run-finalized hook needs, plus write-back result slots.

    ``db`` is the caller's *open* session inside the finalization transaction —
    hooks add rows to it and must not commit. ``run_id``/``space_id`` identify
    the terminal run being finalized and ``run_evaluation_id`` the freshly
    created deterministic ``RunEvaluation``.

    ``task_evaluation_id`` and ``skipped_reasons`` are write-back slots: they
    mirror the runs-owned ``RunFinalization.task_evaluation_id`` /
    ``skipped_reasons_json`` columns, so the owning hook reports its outcome
    without ``runs`` importing the owning module.
    """

    db: Session
    run_id: str
    space_id: str
    run_evaluation_id: str
    task_evaluation_id: Optional[str] = None
    skipped_reasons: list[str] = field(default_factory=list)


# A hook receives the context and returns nothing (or an awaitable of nothing).
# Structural callable type so the registry never imports product modules.
RunFinalizedHook = Callable[[RunFinalizedContext], Union[None, Awaitable[None]]]


# ---------------------------------------------------------------------------
# Typed errors
# ---------------------------------------------------------------------------

class RunFinalizedHookError(Exception):
    """Base class for run-finalized hook registry errors."""


class DuplicateRunFinalizedHookError(RunFinalizedHookError):
    """Raised when a hook name is registered more than once (fail fast)."""

    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"a run-finalized hook is already registered with name {name!r}")


class InvalidRunFinalizedHookError(RunFinalizedHookError):
    """Raised when a hook name or callable is invalid."""


class RunFinalizedHookFailure(RunFinalizedHookError):
    """Raised when a registered hook raises during dispatch.

    Carries ``hook_name`` so the finalizer can record the failed stage exactly
    as before; the original exception is chained as ``__cause__``.
    """

    def __init__(self, hook_name: str, original: BaseException) -> None:
        self.hook_name = hook_name
        super().__init__(f"run-finalized hook {hook_name!r} failed: {original}")
        self.__cause__ = original


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _RegisteredHook:
    name: str
    hook: RunFinalizedHook
    order: int


class RunFinalizedHookRegistry:
    """Registers and dispatches run-finalized hooks in a deterministic order.

    The registry owns dispatch mechanics only; it holds no business logic and
    imports no product modules. Registration is explicit (``register``) and the
    instance is cheap to construct, so tests can build an isolated registry.

    Execution order is deterministic: hooks run by ascending ``order``, then by
    name — independent of registration order. Duplicate names fail fast. A hook
    that raises stops dispatch and surfaces as :class:`RunFinalizedHookFailure`.
    """

    def __init__(self) -> None:
        self._hooks: dict[str, _RegisteredHook] = {}

    def register(self, name: str, hook: RunFinalizedHook, order: int = 100) -> None:
        """Register ``hook`` under ``name`` at ``order``. Duplicate names fail fast."""
        if not name or not isinstance(name, str):
            raise InvalidRunFinalizedHookError("hook name must be a non-empty string")
        if not callable(hook):
            raise InvalidRunFinalizedHookError(f"hook {name!r} must be callable")
        if not isinstance(order, int):
            raise InvalidRunFinalizedHookError(f"hook {name!r} order must be an int")
        if name in self._hooks:
            raise DuplicateRunFinalizedHookError(name)
        self._hooks[name] = _RegisteredHook(name=name, hook=hook, order=order)
        log.debug("registered run-finalized hook name=%s order=%d", name, order)

    def _ordered(self) -> list[_RegisteredHook]:
        return sorted(self._hooks.values(), key=lambda h: (h.order, h.name))

    def registered_hooks(self) -> list[str]:
        """Return hook names in deterministic execution order."""
        return [h.name for h in self._ordered()]

    def run(self, context: RunFinalizedContext) -> None:
        """Invoke every registered hook in deterministic order.

        Runs inside the caller's open finalization transaction. A hook that
        raises stops dispatch and surfaces as :class:`RunFinalizedHookFailure`
        (original exception chained) so the finalizer can record a failed
        finalization for that stage. Async hooks are driven with
        ``asyncio.run`` — see the module docstring.
        """
        for registered in self._ordered():
            try:
                result = registered.hook(context)
                if inspect.isawaitable(result):
                    self._await(registered.name, result)
            except Exception as exc:
                raise RunFinalizedHookFailure(registered.name, exc) from exc

    @staticmethod
    def _await(name: str, awaitable: Awaitable[None]) -> None:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(_drive(awaitable))
            return
        # A running loop in this thread means asyncio.run would raise and
        # blocking here would deadlock the loop — fail fast with a clear error.
        if hasattr(awaitable, "close"):
            awaitable.close()
        raise InvalidRunFinalizedHookError(
            f"run-finalized hook {name!r} returned an awaitable while an event "
            "loop is already running in this thread; finalization dispatch is "
            "synchronous — call it from a worker thread without a running loop"
        )

    def clear(self) -> None:
        """Drop all registrations. For test isolation only."""
        self._hooks.clear()


async def _drive(awaitable: Awaitable[None]) -> None:
    await awaitable


# ---------------------------------------------------------------------------
# Process-wide instance (lazily built from the module registry)
# ---------------------------------------------------------------------------

_registry: RunFinalizedHookRegistry | None = None


def _build_default_registry() -> RunFinalizedHookRegistry:
    """Build a registry populated from each module's run-finalized hook.

    Imported lazily so this module never imports product modules at top level.
    """
    from ..modules.registry import register_run_finalized_hooks

    registry = RunFinalizedHookRegistry()
    register_run_finalized_hooks(registry)
    return registry


def get_registry() -> RunFinalizedHookRegistry:
    """Return the process-wide registry, building it on first use."""
    global _registry
    if _registry is None:
        _registry = _build_default_registry()
    return _registry


def init_registry(registry: RunFinalizedHookRegistry) -> None:
    """Publish an explicit registry for this process (overrides lazy build)."""
    global _registry
    _registry = registry


def reset_registry() -> None:
    """Drop the process-wide registry so the next call rebuilds it. Tests only."""
    global _registry
    _registry = None
