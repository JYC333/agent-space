from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.jobs import JobHandlerRegistry
from app.jobs.worker import _run_job
from app.memory.consolidation.service import run_memory_consolidation_job_payload


class _FakeQueue:
    def __init__(self, *, event_writes_fail: bool = False) -> None:
        self.event_writes_fail = event_writes_fail
        self.status = "claimed"
        self.result = None
        self.error = None

    async def start_job(self, job_id: str, worker_id: str | None = None) -> None:
        self.status = "running"

    async def complete_job(
        self, job_id: str, result: dict | None = None, worker_id: str | None = None
    ) -> None:
        self.status = "completed"
        self.result = result

    async def fail_job(self, job_id: str, error: str, worker_id: str | None = None) -> None:
        self.status = "failed"
        self.error = error

    async def append_event(self, job_id: str, event_type: str, message: str, data=None) -> None:
        if self.event_writes_fail:
            raise RuntimeError("event sink unavailable")


def _job(job_type: str):
    return SimpleNamespace(id="job-1", job_type=job_type, attempts=0, max_attempts=1)


def _registry_with(job_type: str, fn) -> JobHandlerRegistry:
    registry = JobHandlerRegistry()
    registry.register(job_type, fn)
    return registry


async def _run_job_inline(job, queue, registry):
    loop = asyncio.get_running_loop()
    original = loop.run_in_executor

    def inline_executor(executor, fn, *args):
        future = loop.create_future()
        try:
            future.set_result(fn(*args))
        except Exception as exc:
            future.set_exception(exc)
        return future

    loop.run_in_executor = inline_executor
    try:
        await _run_job(job, queue, asyncio.Semaphore(1), registry)
    finally:
        loop.run_in_executor = original


def test_terminal_success_survives_auxiliary_event_write_failure():
    queue = _FakeQueue(event_writes_fail=True)
    job_type = "m7d_success"
    registry = _registry_with(job_type, lambda job: {"ok": True})
    asyncio.run(_run_job_inline(_job(job_type), queue, registry))

    assert queue.status == "completed"
    assert queue.result == {"ok": True}
    assert queue.error is None


def test_terminal_failure_survives_auxiliary_event_write_failure():
    queue = _FakeQueue(event_writes_fail=True)
    job_type = "m7d_failure"

    def handler(job):
        raise RuntimeError("handler failed")

    registry = _registry_with(job_type, handler)
    asyncio.run(_run_job_inline(_job(job_type), queue, registry))

    assert queue.status == "failed"
    assert "handler failed" in (queue.error or "")


def test_worker_marks_running_before_handler_execution():
    queue = _FakeQueue()
    job_type = "m7d_observe_running"
    observed: list[str] = []

    def handler(job):
        observed.append(queue.status)
        return {"seen": observed[-1]}

    registry = _registry_with(job_type, handler)
    asyncio.run(_run_job_inline(_job(job_type), queue, registry))

    assert observed == ["running"]
    assert queue.status == "completed"


def test_memory_consolidation_job_payload_requires_real_user_id():
    with pytest.raises(ValueError, match="missing user_id"):
        run_memory_consolidation_job_payload(
            db=None,
            payload={"space_id": "space-a", "batch_limit": 1},
        )
