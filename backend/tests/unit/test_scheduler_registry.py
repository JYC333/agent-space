from __future__ import annotations

import asyncio

import pytest

from app.scheduler import ScheduledTask, SchedulerRegistry


def test_register_rejects_duplicate_names():
    registry = SchedulerRegistry()

    async def run() -> None:
        return None

    registry.register(ScheduledTask(name="daily", interval_seconds=60, run=run))
    with pytest.raises(ValueError, match="already registered"):
        registry.register(ScheduledTask(name="daily", interval_seconds=60, run=run))


def test_run_on_start_task_runs_before_first_sleep():
    calls: list[str] = []
    ran = asyncio.Event()

    async def run() -> None:
        calls.append("ran")
        ran.set()

    async def scenario() -> None:
        registry = SchedulerRegistry()
        registry.register(ScheduledTask(name="immediate", interval_seconds=3600, run=run))
        await registry.start()
        await asyncio.wait_for(ran.wait(), timeout=1)
        await registry.stop()

    asyncio.run(scenario())
    assert calls == ["ran"]


def test_run_on_start_false_waits_for_interval():
    calls: list[str] = []

    async def run() -> None:
        calls.append("ran")

    async def scenario() -> None:
        registry = SchedulerRegistry()
        registry.register(
            ScheduledTask(
                name="delayed",
                interval_seconds=3600,
                run=run,
                run_on_start=False,
            )
        )
        await registry.start()
        await asyncio.sleep(0)
        await registry.stop()

    asyncio.run(scenario())
    assert calls == []


def test_await_run_on_start_completes_before_start_returns():
    calls: list[str] = []

    async def run() -> None:
        calls.append("startup")

    async def scenario() -> None:
        registry = SchedulerRegistry()
        registry.register(
            ScheduledTask(
                name="startup",
                interval_seconds=3600,
                run=run,
                run_on_start=True,
                await_run_on_start=True,
            )
        )
        await registry.start()
        assert calls == ["startup"]
        await registry.stop()

    asyncio.run(scenario())


def test_cannot_register_after_start():
    async def run() -> None:
        return None

    async def scenario() -> None:
        registry = SchedulerRegistry()
        await registry.start()
        with pytest.raises(RuntimeError, match="after start"):
            registry.register(ScheduledTask(name="late", interval_seconds=60, run=run))
        await registry.stop()

    asyncio.run(scenario())


def test_task_validation():
    async def run() -> None:
        return None

    with pytest.raises(ValueError, match="name is required"):
        ScheduledTask(name="", interval_seconds=60, run=run)
    with pytest.raises(ValueError, match="positive"):
        ScheduledTask(name="bad", interval_seconds=0, run=run)
    with pytest.raises(ValueError, match="requires run_on_start"):
        ScheduledTask(
            name="bad",
            interval_seconds=60,
            run=run,
            run_on_start=False,
            await_run_on_start=True,
        )
