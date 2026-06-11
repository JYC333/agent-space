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

The lock is stored in the ``run_execution_locks`` table. Acquisition uses a
short-lived independent session so it is durable while execution is in
progress without committing business work in the caller's session. A PK
collision raises ``IntegrityError`` and indicates that another worker owns
the lock. Release deletes the lock in its own short transaction and does not
commit caller business work.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Generator

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

log = logging.getLogger(__name__)

_UNKNOWN_WORKER = "unknown"


class RunExecutionLockService:
    def __init__(self, db: Session) -> None:
        self._db = db

    def try_acquire(self, run_id: str, *, worker_id: str, job_id: str | None = None) -> bool:
        """Attempt to acquire the execution lock for *run_id*.

        Returns True when the lock was successfully inserted (this caller owns
        it).  Returns False when another worker already holds the lock.

        Uses a short-lived independent session so the durable lock is visible
        to other workers without committing the caller's business transaction.
        """
        from ..models import RunExecutionLock

        LockSession = sessionmaker(bind=self._db.get_bind(), autocommit=False, autoflush=False)
        lock_db = LockSession()
        try:
            lock = RunExecutionLock(
                run_id=run_id,
                locked_at=datetime.now(UTC),
                worker_id=worker_id,
                job_id=job_id,
            )
            lock_db.add(lock)
            lock_db.commit()
            log.debug("Execution lock acquired run=%s worker=%s", run_id, worker_id)
            return True
        except IntegrityError:
            lock_db.rollback()
            log.warning(
                "Execution lock already held for run=%s — duplicate execution prevented",
                run_id,
            )
            return False
        except Exception:
            lock_db.rollback()
            raise
        finally:
            lock_db.close()

    def release(self, run_id: str) -> None:
        """Release the execution lock for *run_id*.

        Safe to call even when no lock exists (idempotent).
        The delete is committed in an independent short-lived transaction;
        pending business changes in the caller's session are untouched.
        """
        from ..models import RunExecutionLock

        LockSession = sessionmaker(bind=self._db.get_bind(), autocommit=False, autoflush=False)
        lock_db = LockSession()
        try:
            row = lock_db.query(RunExecutionLock).filter(RunExecutionLock.run_id == run_id).first()
            if row is not None:
                lock_db.delete(row)
                lock_db.commit()
                log.debug("Execution lock released run=%s", run_id)
        except Exception:
            lock_db.rollback()
            log.warning("Failed to release execution lock for run=%s", run_id, exc_info=True)
        finally:
            lock_db.close()

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
