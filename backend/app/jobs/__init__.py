"""Public facade for the durable job queue's handler registry.

Kept lightweight: only the registry API is exported here. The queue
implementation (``app.jobs.queue``), worker (``app.jobs.worker``), and HTTP
router (``app.jobs.api``) remain internal modules imported directly by their
consumers.
"""

from __future__ import annotations

from .registry import (
    DuplicateJobHandlerError,
    JobHandler,
    JobHandlerRegistry,
    UnknownJobTypeError,
)

__all__ = [
    "JobHandler",
    "JobHandlerRegistry",
    "DuplicateJobHandlerError",
    "UnknownJobTypeError",
]
