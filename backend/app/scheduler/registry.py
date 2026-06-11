"""Shared in-app scheduler registry.

Owns the repeated async sleep/error/cancel loop for periodic backend work.
Registered task callables keep their existing business behavior; this registry
only centralizes when and how they are ticked from the app lifespan.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)

ScheduledCallable = Callable[[], Awaitable[Any]]


@dataclass(frozen=True)
class ScheduledTask:
    name: str
    interval_seconds: int | float
    run: ScheduledCallable
    run_on_start: bool = True
    await_run_on_start: bool = False

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("scheduled task name is required")
        if self.interval_seconds <= 0:
            raise ValueError("scheduled task interval_seconds must be positive")
        if self.await_run_on_start and not self.run_on_start:
            raise ValueError("await_run_on_start requires run_on_start")


class SchedulerRegistry:
    """Registry and lifecycle manager for periodic backend tasks."""

    def __init__(self) -> None:
        self._tasks: dict[str, ScheduledTask] = {}
        self._loops: dict[str, asyncio.Task] = {}
        self._started = False

    def register(self, task: ScheduledTask) -> None:
        if self._started:
            raise RuntimeError("cannot register scheduled tasks after start")
        if task.name in self._tasks:
            raise ValueError(f"scheduled task already registered: {task.name}")
        self._tasks[task.name] = task

    @property
    def task_names(self) -> tuple[str, ...]:
        return tuple(self._tasks)

    async def start(self) -> None:
        if self._started:
            return
        self._started = True

        for task in self._tasks.values():
            if task.run_on_start and task.await_run_on_start:
                await self._run_once(task)
                initial_delay = task.interval_seconds
            else:
                initial_delay = 0 if task.run_on_start else task.interval_seconds

            self._loops[task.name] = asyncio.create_task(
                self._run_loop(task, initial_delay=initial_delay),
                name=f"scheduler:{task.name}",
            )

        if self._tasks:
            log.info("scheduler registry started tasks=%s", ",".join(self._tasks))

    async def stop(self) -> None:
        if not self._started:
            return

        loops = list(self._loops.values())
        for loop in loops:
            loop.cancel()
        for loop in loops:
            try:
                await loop
            except asyncio.CancelledError:
                pass

        self._loops.clear()
        self._started = False
        if self._tasks:
            log.info("scheduler registry stopped")

    async def _run_loop(self, task: ScheduledTask, *, initial_delay: int | float) -> None:
        if initial_delay > 0:
            await asyncio.sleep(initial_delay)

        while True:
            await self._run_once(task)
            await asyncio.sleep(task.interval_seconds)

    async def _run_once(self, task: ScheduledTask) -> None:
        try:
            await task.run()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("%s: scan loop error", task.name)
