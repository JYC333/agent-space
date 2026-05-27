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

SQLite note: the implementation uses a plain ORM INSERT in its own short
transaction. A PK collision raises ``IntegrityError`` which is caught and
rolled back — equivalent in effect to
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
from sqlalchemy.orm import Session, sessionmaker

log = logging.getLogger(__name__)

# Sentinel set by the job worker; callers outside the worker pass their own id.
_UNKNOWN_WORKER = "unknown"


class RunExecutionLockService:
    def __init__(self, db: Session) -> None:
        self._db = db

    def _is_sqlite(self) -> bool:
        bind = self._db.get_bind()
        try:
            return (bind.dialect.name or "").lower() == "sqlite"
        except Exception:
            return False

    def _sqlite_use_caller_nested_lock(self) -> bool:
        """Use savepoint-based lock when caller already has an open SQLite transaction.

        ``flush()`` can leave ``dirty/new/deleted`` empty while the write
        transaction remains open — an independent lock session would then block
        until ``busy_timeout``.
        """
        if not self._is_sqlite():
            return False
        try:
            return bool(self._db.in_transaction())
        except Exception:
            return False

    def try_acquire(self, run_id: str, *, worker_id: str, job_id: str | None = None) -> bool:
        """Attempt to acquire the execution lock for *run_id*.

        Returns True when the lock was successfully inserted (this caller owns
        it).  Returns False when another worker already holds the lock.

        Uses a short-lived independent session so the durable lock is visible
        to other workers without committing the caller's business transaction.
        """
        from ..models import RunExecutionLock

        # SQLite cannot reliably support an "independent short commit" lock when the
        # caller already holds a write transaction (common in tests). In that case,
        # a second connection will block until busy_timeout and appear "slow".
        #
        # When the caller session has no pending business writes, use the same
        # independent-session path as PostgreSQL so the lock is durable and release()
        # can delete it without committing caller mutations.
        #
        # When the caller already has pending ORM writes, fall back to a nested
        # transaction on the caller session to avoid writer lock contention.
        if self._sqlite_use_caller_nested_lock():
            lock = RunExecutionLock(
                run_id=run_id,
                locked_at=datetime.now(UTC),
                worker_id=worker_id,
                job_id=job_id,
            )
            try:
                with self._db.begin_nested():
                    self._db.add(lock)
                    self._db.flush()
                log.debug("Execution lock acquired (sqlite) run=%s worker=%s", run_id, worker_id)
                return True
            except IntegrityError:
                log.warning(
                    "Execution lock already held for run=%s — duplicate execution prevented",
                    run_id,
                )
                return False

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

    def _sqlite_release_read_transaction_if_idle(self) -> None:
        """End a read-only caller transaction so an independent DELETE can proceed."""
        if not self._is_sqlite():
            return
        try:
            if not self._db.in_transaction():
                return
            if self._db.new or self._db.dirty or self._db.deleted:
                return
            trans = self._db.get_transaction()
            if trans is not None:
                trans.commit()
        except Exception:
            log.debug(
                "Could not release idle SQLite read transaction before lock delete",
                exc_info=True,
            )

    def release(self, run_id: str) -> None:
        """Release the execution lock for *run_id*.

        Safe to call even when no lock exists (idempotent).
        The delete is committed in an independent short-lived transaction;
        pending business changes in the caller's session are untouched.
        """
        from ..models import RunExecutionLock

        self._sqlite_release_read_transaction_if_idle()

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
