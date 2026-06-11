from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy.orm import Session


class SessionFailedError(RuntimeError):
    """Raised when SQLAlchemy has marked a Session unusable until rollback."""


class UnitOfWork:
    """Small transaction helper around an existing SQLAlchemy Session.

    This is deliberately not a repository or generic database facade. Domain
    services and stores still own their queries; this helper only owns
    transaction control.
    """

    def __init__(self, db: Session) -> None:
        self.db = db
        self._completed = False

    def __enter__(self) -> "UnitOfWork":
        ensure_session_usable(self.db)
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc_type is not None:
            self.rollback()
            return False
        if not self._completed:
            self.commit()
        return False

    def commit(self) -> None:
        try:
            self.db.commit()
            self._completed = True
        except Exception:
            self.db.rollback()
            self._completed = True
            raise

    def rollback(self) -> None:
        self.db.rollback()
        self._completed = True

    def flush(self) -> None:
        ensure_session_usable(self.db)
        self.db.flush()
        ensure_session_usable(self.db)

    @contextmanager
    def savepoint(self) -> Iterator["UnitOfWork"]:
        """Run a best-effort block in a nested transaction/savepoint.

        A failure rolls back only nested state when the backend supports
        savepoints. If SQLAlchemy still marks the whole Session failed, callers
        get an explicit SessionFailedError instead of silently continuing with a
        contaminated Session.
        """

        ensure_session_usable(self.db)
        nested = self.db.begin_nested()
        try:
            yield self
            nested.commit()
        except Exception:
            nested.rollback()
            ensure_session_usable(self.db)
            raise
        ensure_session_usable(self.db)


def ensure_session_usable(db: Session) -> None:
    if not db.is_active:
        raise SessionFailedError(
            "SQLAlchemy Session is in failed state; rollback is required before reuse"
        )


def rollback_if_failed(db: Session) -> None:
    if not db.is_active:
        db.rollback()

