"""Job handler registry — dispatch mechanics for the durable job queue.

This module owns *only* the mechanics of mapping a ``job_type`` string to a
handler callable and invoking it. It contains **no business logic** and must
**not** import product modules (``daily_reports``, ``automation``, ``memory``,
``runs``, ``knowledge`` …). Job-owning modules keep their handlers and register
them by calling ``register_job_handlers(registry)`` (see
``app.modules.registry.register_job_handlers``).

Lifecycle (mirrors ``app.jobs.queue.get_queue`` / ``init_queue``): the app
lifespan builds one ``JobHandlerRegistry`` per startup, populates it through the
module-owned registration hooks, publishes it with ``init_registry`` (so the
jobs API can introspect it), and injects it into the background worker.

Handlers
--------
A handler is any callable taking the ``Job`` ORM row and returning an optional
``dict`` (becomes ``job.result_json`` on success):

    def handle(job) -> dict | None: ...          # sync — run in a thread pool
    async def handle(job) -> dict | None: ...     # async — awaited directly

Sync handlers are executed in the default thread-pool executor so blocking DB
work never stalls the event loop; async handlers are awaited on the loop. A
handler that raises propagates the exception unchanged to the worker, which
applies the queue's existing fail/retry semantics.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from typing import Any, Awaitable, Callable, Optional, Union

log = logging.getLogger(__name__)

# Result a handler may return (becomes ``job.result_json`` on success).
JobResult = Optional[dict]

# A job handler receives the ``Job`` ORM row and returns a ``JobResult`` either
# synchronously or as an awaitable. Kept as a structural callable type so the
# registry never needs to import the ORM model.
JobHandler = Callable[[Any], Union[JobResult, Awaitable[JobResult]]]


# ---------------------------------------------------------------------------
# Typed errors
# ---------------------------------------------------------------------------

class JobRegistryError(Exception):
    """Base class for job-registry errors."""


class DuplicateJobHandlerError(JobRegistryError):
    """Raised when a job_type is registered more than once (fail fast)."""

    def __init__(self, job_type: str) -> None:
        self.job_type = job_type
        super().__init__(f"a handler is already registered for job type {job_type!r}")


class UnknownJobTypeError(JobRegistryError):
    """Raised when dispatching a job whose job_type has no registered handler."""

    def __init__(self, job_type: str) -> None:
        self.job_type = job_type
        super().__init__(f"no handler registered for job type {job_type!r}")


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class JobHandlerRegistry:
    """Maps ``job_type`` → handler and dispatches jobs to the right handler.

    The registry owns dispatch mechanics only; it holds no business logic and
    imports no product modules. Registration is explicit (``register``) and the
    instance is cheap to construct, so tests can build an isolated registry.
    """

    def __init__(self) -> None:
        self._handlers: dict[str, JobHandler] = {}

    def register(self, job_type: str, handler: JobHandler) -> None:
        """Register ``handler`` for ``job_type``. Duplicate types fail fast."""
        if not job_type or not isinstance(job_type, str):
            raise ValueError("job_type must be a non-empty string")
        if not callable(handler):
            raise TypeError(f"handler for job type {job_type!r} must be callable")
        if job_type in self._handlers:
            raise DuplicateJobHandlerError(job_type)
        self._handlers[job_type] = handler
        log.debug("registered job handler job_type=%s handler=%s", job_type, getattr(handler, "__name__", handler))

    def get(self, job_type: str) -> JobHandler | None:
        """Return the handler for ``job_type`` or ``None`` if unregistered."""
        return self._handlers.get(job_type)

    def registered_job_types(self) -> list[str]:
        """Return the sorted list of registered job_type names."""
        return sorted(self._handlers)

    async def dispatch(self, job: Any) -> JobResult:
        """Invoke the handler for ``job`` and return its result.

        Sync handlers run in the default thread-pool executor; async handlers
        are awaited. Raises ``UnknownJobTypeError`` when no handler is
        registered for ``job.job_type``. Handler exceptions propagate unchanged.
        """
        job_type = job.job_type
        handler = self._handlers.get(job_type)
        if handler is None:
            raise UnknownJobTypeError(job_type)

        # Fast path: a coroutine function is awaited directly on the loop.
        if inspect.iscoroutinefunction(handler):
            return await handler(job)

        # Otherwise run in the thread-pool executor so a blocking sync handler
        # never stalls the loop. Guard the async shapes that
        # ``iscoroutinefunction`` does not detect (a callable object with an
        # async ``__call__``, a partial/decorator-wrapped coroutine function, or
        # a plain function that returns a coroutine): if the call produced an
        # awaitable, await it rather than reporting a coroutine object as the
        # job result (which would mark the job completed without ever running).
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, handler, job)
        if inspect.isawaitable(result):
            result = await result
        return result


# ---------------------------------------------------------------------------
# Process-wide instance (mirrors app.jobs.queue.get_queue / init_queue)
# ---------------------------------------------------------------------------

_registry: JobHandlerRegistry | None = None


def get_registry() -> JobHandlerRegistry:
    """Return the registry published for this process by ``init_registry``."""
    if _registry is None:
        raise RuntimeError(
            "JobHandlerRegistry not initialised — call init_registry() first"
        )
    return _registry


def init_registry(registry: JobHandlerRegistry) -> None:
    """Publish the active registry so the jobs API and worker can reach it."""
    global _registry
    _registry = registry
