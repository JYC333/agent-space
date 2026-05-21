"""Durable per-run execution lock.

Prevents duplicate concurrent execution of the same run_id across worker
attempts (e.g. when a stuck-job reclaim triggers a second worker to pick up a
job whose original handler is still in adapter.execute()).

Usage inside RunExecutionService::

    from .execution_lock import RunExecutionLockService

    with RunExecutionLockService(db).lock(run_id, worker_id=WORKER_ID) as acquired:
        if not acquired:
            return RuntimeExecutionResult(
                success=False, error="run already executing", error_code="duplicate_execution", ...
            )
        # ... execute run ...

The lock is stored in the ``run_execution_locks`` table.  Acquisition issues
a plain ORM INSERT inside a savepoint; a PK collision raises ``IntegrityError``
which is caught and rolled back to the savepoint so the surrounding session is
unaffected.  Release (DELETE + commit) happens on context exit regardless of
outcome, and is committed durably so the row is gone even when the caller's
session is closed immediately after.

SQLite note: the implementation uses a plain ORM INSERT wrapped in a savepoint.
A PK collision raises ``IntegrityError`` which is caught and rolled back to the
savepoint, leaving the surrounding session intact — equivalent in effect to
``INSERT OR IGNORE`` / ``ON CONFLICT DO NOTHING`` but using portable SQLAlchemy
primitives rather than dialect-specific SQL.  When migrating to PostgreSQL,
``INSERT … ON CONFLICT DO NOTHING`` may be more efficient.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Generator

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

log = logging.getLogger(__name__)

# Sentinel set by the job worker; callers outside the worker pass their own id.
_UNKNOWN_WORKER = "unknown"


class RunExecutionLockService:
    def __init__(self, db: Session) -> None:
        self._db = db

    def try_acquire(self, run_id: str, *, worker_id: str, job_id: str | None = None) -> bool:
        """Attempt to acquire the execution lock for *run_id*.

        Returns True when the lock was successfully inserted (this caller owns
        it).  Returns False when another worker already holds the lock.

        Uses a savepoint so an IntegrityError on the PK collision does not mark
        the surrounding Session as failed.
        """
        from ..models import RunExecutionLock

        try:
            nested = self._db.begin_nested()
            lock = RunExecutionLock(
                run_id=run_id,
                locked_at=datetime.now(UTC),
                worker_id=worker_id,
                job_id=job_id,
            )
            self._db.add(lock)
            self._db.flush()
            nested.commit()
            log.debug("Execution lock acquired run=%s worker=%s", run_id, worker_id)
            return True
        except IntegrityError:
            nested.rollback()
            log.warning(
                "Execution lock already held for run=%s — duplicate execution prevented",
                run_id,
            )
            return False
        except Exception:
            try:
                nested.rollback()
            except Exception:
                pass
            raise

    def release(self, run_id: str) -> None:
        """Release the execution lock for *run_id*.

        Safe to call even when no lock exists (idempotent).
        Commits the deletion durably so the lock row is removed even when the
        caller's session is closed immediately after (e.g. the job handler's
        ``db.close()`` in the ``finally`` block).
        """
        from ..models import RunExecutionLock

        try:
            row = self._db.query(RunExecutionLock).filter(RunExecutionLock.run_id == run_id).first()
            if row is not None:
                self._db.delete(row)
                self._db.flush()
                self._db.commit()
                log.debug("Execution lock released run=%s", run_id)
        except Exception:
            log.warning("Failed to release execution lock for run=%s", run_id, exc_info=True)

    @contextmanager
    def lock(
        self,
        run_id: str,
        *,
        worker_id: str = _UNKNOWN_WORKER,
        job_id: str | None = None,
    ) -> Generator[bool, None, None]:
        """Context manager that acquires and releases the execution lock.

        Yields True when acquired, False when the lock is already held.
        The lock is always released on exit (even when acquired=False, which
        is a no-op release).
        """
        acquired = self.try_acquire(run_id, worker_id=worker_id, job_id=job_id)
        try:
            yield acquired
        finally:
            if acquired:
                self.release(run_id)
