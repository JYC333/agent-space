"""Unit tests for the centralized job handler registry.

Covers the registry mechanics (registration, lookup, dispatch of sync + async
handlers, typed errors), the worker dispatching through the registry, module-
owned registration coverage of every existing job type, the public facade, and
the boundary rule that the registry imports no product modules.
"""

from __future__ import annotations

import ast
import asyncio
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.jobs import (
    DuplicateJobHandlerError,
    JobHandler,
    JobHandlerRegistry,
    UnknownJobTypeError,
)
from app.jobs.worker import _run_job
from app.modules.registry import Module, register_job_handlers


# Authoritative set of durable-queue job types the system supports today. These
# are the three `registry.register(...)` calls owned by the jobs and
# daily_reports modules. (Intake's `snapshot`/`normalize_*`/`extract_text` etc.
# are a separate ExtractionJob subsystem, not durable-queue handlers.)
EXISTING_JOB_TYPES = {"agent_run", "memory_consolidation", "daily_capture_report"}


def _job(job_type: str):
    return SimpleNamespace(id="job-1", job_type=job_type, attempts=0, max_attempts=1)


# ---------------------------------------------------------------------------
# Registration + lookup
# ---------------------------------------------------------------------------

def test_register_and_get_returns_handler():
    registry = JobHandlerRegistry()
    handler = lambda job: {"ok": True}  # noqa: E731
    registry.register("t", handler)
    assert registry.get("t") is handler
    assert registry.registered_job_types() == ["t"]


def test_get_unknown_returns_none():
    assert JobHandlerRegistry().get("nope") is None


def test_registered_job_types_is_sorted():
    registry = JobHandlerRegistry()
    registry.register("b", lambda job: None)
    registry.register("a", lambda job: None)
    assert registry.registered_job_types() == ["a", "b"]


def test_duplicate_registration_fails_fast():
    registry = JobHandlerRegistry()
    registry.register("dup", lambda job: None)
    with pytest.raises(DuplicateJobHandlerError) as exc:
        registry.register("dup", lambda job: None)
    assert exc.value.job_type == "dup"


def test_register_rejects_empty_job_type():
    with pytest.raises(ValueError):
        JobHandlerRegistry().register("", lambda job: None)


def test_register_rejects_non_callable():
    with pytest.raises(TypeError):
        JobHandlerRegistry().register("t", object())


# ---------------------------------------------------------------------------
# dispatch — sync, async, unknown
# ---------------------------------------------------------------------------

def test_dispatch_invokes_registered_sync_handler_in_executor():
    registry = JobHandlerRegistry()
    seen: dict = {}

    def handler(job):
        seen["thread"] = threading.current_thread().name
        seen["job_id"] = job.id
        return {"handled": job.job_type}

    registry.register("sync", handler)
    result = asyncio.run(registry.dispatch(_job("sync")))

    assert result == {"handled": "sync"}
    assert seen["job_id"] == "job-1"
    # Sync handlers run in a thread-pool executor, not the event-loop thread.
    assert seen["thread"] != threading.current_thread().name


def test_dispatch_awaits_async_handler_on_loop():
    registry = JobHandlerRegistry()
    seen: dict = {}

    async def handler(job):
        seen["thread"] = threading.current_thread().name
        return {"async_handled": job.job_type}

    registry.register("async", handler)

    async def drive():
        main_thread = threading.current_thread().name
        result = await registry.dispatch(_job("async"))
        return main_thread, result

    main_thread, result = asyncio.run(drive())
    assert result == {"async_handled": "async"}
    # Async handlers are awaited on the loop thread (never the executor).
    assert seen["thread"] == main_thread


def test_dispatch_unknown_job_type_raises_typed_error():
    registry = JobHandlerRegistry()
    with pytest.raises(UnknownJobTypeError) as exc:
        asyncio.run(registry.dispatch(_job("missing")))
    assert exc.value.job_type == "missing"


def test_dispatch_propagates_handler_exception():
    registry = JobHandlerRegistry()

    def boom(job):
        raise RuntimeError("kaboom")

    registry.register("boom", boom)
    with pytest.raises(RuntimeError, match="kaboom"):
        asyncio.run(registry.dispatch(_job("boom")))


def test_dispatch_awaits_awaitable_returned_by_sync_callable():
    # A plain (non-coroutine) function that *returns* a coroutine must have its
    # result awaited, not reported back as an un-awaited coroutine object.
    registry = JobHandlerRegistry()

    async def _inner(job):
        return {"awaited": job.job_type}

    def handler(job):
        return _inner(job)

    assert not asyncio.iscoroutinefunction(handler)
    registry.register("returns_awaitable", handler)
    result = asyncio.run(registry.dispatch(_job("returns_awaitable")))
    assert result == {"awaited": "returns_awaitable"}


def test_dispatch_handles_async_callable_object():
    # A callable *instance* with an async __call__ is not detected by
    # iscoroutinefunction; dispatch must still await the produced coroutine.
    registry = JobHandlerRegistry()

    class _AsyncHandler:
        async def __call__(self, job):
            return {"obj": job.job_type}

    handler = _AsyncHandler()
    assert not asyncio.iscoroutinefunction(handler)
    registry.register("async_callable", handler)
    result = asyncio.run(registry.dispatch(_job("async_callable")))
    assert result == {"obj": "async_callable"}


# ---------------------------------------------------------------------------
# Worker dispatches through the registry (not if/elif or a module dict)
# ---------------------------------------------------------------------------

class _FakeQueue:
    def __init__(self) -> None:
        self.status = "claimed"
        self.result = None
        self.error = None

    async def start_job(self, job_id, worker_id=None):
        self.status = "running"

    async def complete_job(self, job_id, result=None, worker_id=None):
        self.status = "completed"
        self.result = result

    async def fail_job(self, job_id, error, worker_id=None):
        self.status = "failed"
        self.error = error

    async def append_event(self, job_id, event_type, message, data=None):
        pass


def test_worker_run_job_dispatches_via_registry():
    registry = JobHandlerRegistry()
    invoked: list[str] = []
    registry.register("via_registry", lambda job: (invoked.append(job.job_type), {"ok": True})[1])

    queue = _FakeQueue()
    asyncio.run(_run_job(_job("via_registry"), queue, asyncio.Semaphore(1), registry))

    assert invoked == ["via_registry"]
    assert queue.status == "completed"
    assert queue.result == {"ok": True}


def test_worker_run_job_unknown_type_fails_without_running():
    registry = JobHandlerRegistry()  # empty
    queue = _FakeQueue()
    asyncio.run(_run_job(_job("unregistered"), queue, asyncio.Semaphore(1), registry))

    # Unknown job_type fails fast and never transitions to 'running'.
    assert queue.status == "failed"
    assert "unregistered" in (queue.error or "")


def test_worker_run_job_handler_exception_marks_failed():
    registry = JobHandlerRegistry()

    def boom(job):
        raise RuntimeError("handler exploded")

    registry.register("explode", boom)
    queue = _FakeQueue()
    asyncio.run(_run_job(_job("explode"), queue, asyncio.Semaphore(1), registry))

    assert queue.status == "failed"
    assert "handler exploded" in (queue.error or "")


# ---------------------------------------------------------------------------
# Existing job type coverage via module-owned registration
# ---------------------------------------------------------------------------

def test_module_registration_covers_all_existing_job_types():
    registry = JobHandlerRegistry()
    loaded = register_job_handlers(registry)

    registered = set(registry.registered_job_types())
    missing = EXISTING_JOB_TYPES - registered
    assert not missing, f"existing job types no longer registered: {sorted(missing)}"
    # Exact match guards against silent drift (drops or accidental additions).
    assert registered == EXISTING_JOB_TYPES
    # jobs + daily_reports own the registration hooks.
    assert set(loaded) == {"jobs", "daily_reports"}


def test_module_registration_is_idempotent_per_fresh_registry():
    # A fresh registry per call avoids cross-startup duplicate registration.
    first = JobHandlerRegistry()
    register_job_handlers(first)
    second = JobHandlerRegistry()
    register_job_handlers(second)
    assert first.registered_job_types() == second.registered_job_types()


def test_register_job_handlers_fails_fast_on_bad_import():
    # A selected module declaring a non-importable job_handlers submodule must
    # fail at startup, not silently leave the worker without handlers.
    bad = Module("badmod", "Bad", "app.jobs", job_handlers="does_not_exist", always_on=True)
    with pytest.raises(ImportError):
        register_job_handlers(JobHandlerRegistry(), modules=[bad])


def test_register_job_handlers_fails_fast_on_missing_hook():
    # app.jobs.schemas exists but exposes no register_job_handlers(registry).
    nohook = Module("nohook", "NoHook", "app.jobs", job_handlers="schemas", always_on=True)
    with pytest.raises(RuntimeError, match="register_job_handlers"):
        register_job_handlers(JobHandlerRegistry(), modules=[nohook])


def test_register_job_handlers_skips_disabled_optional_module():
    # An optional, not-enabled module is skipped without importing — so a broken
    # job_handlers declaration on a disabled module does not break startup.
    disabled = Module(
        "optmod", "Opt", "app.jobs", job_handlers="does_not_exist", always_on=False
    )
    registry = JobHandlerRegistry()
    loaded = register_job_handlers(registry, enabled=None, modules=[disabled])
    assert loaded == []
    assert registry.registered_job_types() == []


# ---------------------------------------------------------------------------
# Public facade + boundary rule
# ---------------------------------------------------------------------------

def test_public_facade_exports_registry_api():
    import app.jobs as jobs_facade
    from app.jobs import registry as registry_module

    assert set(jobs_facade.__all__) == {
        "JobHandler",
        "JobHandlerRegistry",
        "DuplicateJobHandlerError",
        "UnknownJobTypeError",
    }
    assert jobs_facade.JobHandlerRegistry is registry_module.JobHandlerRegistry
    assert jobs_facade.DuplicateJobHandlerError is registry_module.DuplicateJobHandlerError
    assert jobs_facade.UnknownJobTypeError is registry_module.UnknownJobTypeError
    # JobHandler is a type alias usable for annotations.
    assert JobHandler is registry_module.JobHandler


def test_registry_module_imports_no_product_modules():
    """The registry owns dispatch mechanics only — it must not import product
    modules (daily_reports, automation, backups, memory, runs, knowledge, …)."""
    registry_path = Path(__file__).resolve().parents[2] / "app" / "jobs" / "registry.py"
    tree = ast.parse(registry_path.read_text(encoding="utf-8"))

    product_packages = {
        "daily_reports", "automation", "backups", "knowledge", "memory",
        "runs", "intake", "proposals", "agents", "tasks", "evolution",
        "capabilities", "providers", "scheduler",
    }
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
            # also catch `from . import x` / `from ..pkg import y`
            for alias in node.names:
                imported.add(alias.name.split(".")[0])

    leaked = imported & product_packages
    assert not leaked, f"registry.py imports product modules: {sorted(leaked)}"
