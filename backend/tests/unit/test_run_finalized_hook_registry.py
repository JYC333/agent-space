"""Tests for the RunFinalizedHookRegistry and its module-owned registration.

Covers the registry's dispatch mechanics (deterministic order, duplicate
detection, async support, failure wrapping) and verifies that the tasks-owned
RunEvaluation → TaskEvaluation bridge is registered exactly once through the
module registry — with no legacy direct ``runs -> tasks`` call path left in
finalization.
"""

from __future__ import annotations

import asyncio
import importlib
from pathlib import Path

import pytest

from app.modules.registry import Module, register_run_finalized_hooks
from app.runs import (
    DuplicateRunFinalizedHookError,
    RunFinalizedContext,
    RunFinalizedHookRegistry,
)
from app.runs.lifecycle_hooks import (
    InvalidRunFinalizedHookError,
    RunFinalizedHookFailure,
)


# The post-run side effects that existed before the registry refactor. Exact
# match guards against silent drift (an accidental drop or addition).
EXISTING_RUN_FINALIZED_HOOKS = {
    "tasks:task_evaluation_bridge",
}


def _ctx() -> RunFinalizedContext:
    # The dispatch-mechanics tests below never touch the DB, so a placeholder is
    # fine; hooks here only record that they ran.
    return RunFinalizedContext(
        db=None, run_id="run-1", space_id="space-1", run_evaluation_id="run-eval-1"
    )


# ---------------------------------------------------------------------------
# Dispatch mechanics
# ---------------------------------------------------------------------------

def test_duplicate_hook_name_fails_fast():
    registry = RunFinalizedHookRegistry()
    registry.register("dup", lambda ctx: None)
    with pytest.raises(DuplicateRunFinalizedHookError):
        registry.register("dup", lambda ctx: None)


def test_invalid_hook_registration_rejected():
    registry = RunFinalizedHookRegistry()
    with pytest.raises(InvalidRunFinalizedHookError):
        registry.register("", lambda ctx: None)
    with pytest.raises(InvalidRunFinalizedHookError):
        registry.register("not-callable", object())  # type: ignore[arg-type]
    with pytest.raises(InvalidRunFinalizedHookError):
        registry.register("bad-order", lambda ctx: None, order="first")  # type: ignore[arg-type]


def test_hooks_run_in_deterministic_order():
    registry = RunFinalizedHookRegistry()
    calls: list[str] = []
    # Register out of order on purpose: order, then name, decides execution.
    registry.register("b_second", lambda ctx: calls.append("b_second"), order=20)
    registry.register("c_third", lambda ctx: calls.append("c_third"), order=30)
    registry.register("a_first", lambda ctx: calls.append("a_first"), order=10)
    registry.register("d_tiebreak_b", lambda ctx: calls.append("d_tiebreak_b"), order=30)

    assert registry.registered_hooks() == ["a_first", "b_second", "c_third", "d_tiebreak_b"]
    registry.run(_ctx())
    assert calls == ["a_first", "b_second", "c_third", "d_tiebreak_b"]


def test_async_hook_is_supported():
    registry = RunFinalizedHookRegistry()
    calls: list[str] = []

    async def async_hook(ctx: RunFinalizedContext) -> None:
        await asyncio.sleep(0)
        ctx.skipped_reasons.append("async_ran")
        calls.append("async_hook")

    registry.register("sync_hook", lambda ctx: calls.append("sync_hook"), order=10)
    registry.register("async_hook", async_hook, order=20)

    ctx = _ctx()
    registry.run(ctx)

    assert calls == ["sync_hook", "async_hook"]
    assert ctx.skipped_reasons == ["async_ran"]


def test_async_hook_rejected_inside_running_event_loop():
    registry = RunFinalizedHookRegistry()

    async def async_hook(ctx: RunFinalizedContext) -> None:  # pragma: no cover - never awaited
        pass

    registry.register("async_hook", async_hook)

    async def dispatch_inside_loop() -> None:
        registry.run(_ctx())

    with pytest.raises(RunFinalizedHookFailure) as exc_info:
        asyncio.run(dispatch_inside_loop())
    assert exc_info.value.hook_name == "async_hook"
    assert isinstance(exc_info.value.__cause__, InvalidRunFinalizedHookError)
    assert "event loop is already running" in str(exc_info.value.__cause__)


def test_hook_exception_is_wrapped_with_hook_name():
    registry = RunFinalizedHookRegistry()
    original = RuntimeError("bridge exploded")

    def failing(ctx: RunFinalizedContext) -> None:
        raise original

    registry.register("task_evaluation_bridge", failing)

    with pytest.raises(RunFinalizedHookFailure) as exc_info:
        registry.run(_ctx())

    assert exc_info.value.hook_name == "task_evaluation_bridge"
    assert exc_info.value.__cause__ is original


def test_hook_registry_error_is_wrapped_with_hook_name():
    registry = RunFinalizedHookRegistry()
    original = InvalidRunFinalizedHookError("bad hook state")

    def failing(ctx: RunFinalizedContext) -> None:
        raise original

    registry.register("bad_hook", failing)

    with pytest.raises(RunFinalizedHookFailure) as exc_info:
        registry.run(_ctx())

    assert exc_info.value.hook_name == "bad_hook"
    assert exc_info.value.__cause__ is original


def test_hook_failure_stops_later_hooks():
    registry = RunFinalizedHookRegistry()
    calls: list[str] = []

    def failing(ctx: RunFinalizedContext) -> None:
        raise RuntimeError("boom")

    registry.register("a_failing", failing, order=10)
    registry.register("b_later", lambda ctx: calls.append("b_later"), order=20)

    with pytest.raises(RunFinalizedHookFailure):
        registry.run(_ctx())
    assert calls == []


def test_clear_resets_registry():
    registry = RunFinalizedHookRegistry()
    registry.register("once", lambda ctx: None)
    registry.clear()
    assert registry.registered_hooks() == []
    registry.register("once", lambda ctx: None)  # no duplicate error after clear


# ---------------------------------------------------------------------------
# Module-owned registration
# ---------------------------------------------------------------------------

def test_module_registration_covers_all_existing_hooks():
    registry = RunFinalizedHookRegistry()
    loaded = register_run_finalized_hooks(registry)

    assert loaded == ["tasks"]
    registered = {f"{loaded[0]}:{name}" for name in registry.registered_hooks()}
    assert registered == EXISTING_RUN_FINALIZED_HOOKS


def test_module_registration_is_idempotent_per_fresh_registry():
    first = RunFinalizedHookRegistry()
    second = RunFinalizedHookRegistry()
    assert register_run_finalized_hooks(first) == register_run_finalized_hooks(second)
    assert first.registered_hooks() == second.registered_hooks()


def test_register_run_finalized_hooks_fails_fast_on_bad_import():
    modules = [Module("ghost", "Ghost", "app.no_such_pkg", run_finalized_hooks="run_lifecycle")]
    with pytest.raises(ModuleNotFoundError):
        register_run_finalized_hooks(RunFinalizedHookRegistry(), modules=modules)


def test_register_run_finalized_hooks_fails_fast_on_missing_hook():
    # app.tasks.visibility imports cleanly but exposes no
    # register_run_finalized_hooks(registry).
    modules = [Module("tasks", "Tasks", "app.tasks", run_finalized_hooks="visibility")]
    with pytest.raises(RuntimeError, match="register_run_finalized_hooks"):
        register_run_finalized_hooks(RunFinalizedHookRegistry(), modules=modules)


def test_register_run_finalized_hooks_skips_disabled_optional_module():
    modules = [
        Module(
            "tasks", "Tasks", "app.tasks",
            always_on=False, run_finalized_hooks="run_lifecycle",
        )
    ]
    registry = RunFinalizedHookRegistry()
    assert register_run_finalized_hooks(registry, modules=modules) == []
    assert registry.registered_hooks() == []


# ---------------------------------------------------------------------------
# Boundary: dispatch module owns mechanics only
# ---------------------------------------------------------------------------

def test_registry_module_imports_no_product_modules():
    mod = importlib.import_module("app.runs.lifecycle_hooks")
    source = Path(mod.__file__).read_text(encoding="utf-8")
    for forbidden in ("app.tasks", "from ..tasks", "TaskEvaluationService", "evaluation_service"):
        assert forbidden not in source, (
            f"app.runs.lifecycle_hooks must own dispatch mechanics only; found {forbidden!r}"
        )


def test_finalization_no_longer_imports_tasks():
    mod = importlib.import_module("app.runs.finalization")
    source = Path(mod.__file__).read_text(encoding="utf-8")
    for forbidden in ("from ..tasks", "from app.tasks", "import app.tasks", "TaskEvaluationService("):
        assert forbidden not in source, (
            f"runs finalization must dispatch through lifecycle hooks; found {forbidden!r}"
        )


def test_tasks_run_lifecycle_registers_bridge_hook():
    mod = importlib.import_module("app.tasks.run_lifecycle")
    registry = RunFinalizedHookRegistry()
    mod.register_run_finalized_hooks(registry)
    assert registry.registered_hooks() == ["task_evaluation_bridge"]
