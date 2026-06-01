from __future__ import annotations
import uuid
import hashlib
import secrets
from datetime import datetime, UTC, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import User, UserSession

SESSION_COOKIE = "session_id"
OAUTH_STATE_COOKIE = "oauth_state"


def _new_id() -> str:
    return str(uuid.uuid4())


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


class UserSessionService:
    def __init__(self, db: Session):
        self.db = db

    def create(self, user_id: str) -> tuple[UserSession, str]:
        """Create a new session. Returns (session, raw_token). Raw token goes in the cookie."""
        raw = secrets.token_hex(32)
        session = UserSession(
            id=_new_id(),
            user_id=user_id,
            token_hash=_hash_token(raw),
            expires_at=datetime.now(UTC) + timedelta(days=settings.session_expire_days),
        )
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)
        return session, raw

    def validate(self, raw_token: str) -> UserSession:
        h = _hash_token(raw_token)
        session = self.db.query(UserSession).filter(UserSession.token_hash == h).first()
        if not session:
            raise HTTPException(status_code=401, detail="Invalid session")
        expires = session.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=UTC)
        if expires < datetime.now(UTC):
            raise HTTPException(status_code=401, detail="Session expired")
        session.last_seen_at = datetime.now(UTC)
        self.db.commit()
        return session

    def validate_or_none(self, raw_token: str) -> Optional[UserSession]:
        try:
            return self.validate(raw_token)
        except HTTPException:
            return None

    def delete(self, raw_token: str) -> None:
        h = _hash_token(raw_token)
        session = self.db.query(UserSession).filter(UserSession.token_hash == h).first()
        if session:
            self.db.delete(session)
            self.db.commit()


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated. Sign in with Google.")
    session = UserSessionService(db).validate(token)
    user = db.query(User).filter(User.id == session.user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


def get_optional_user(
    request: Request,
    db: Session = Depends(get_db),
) -> Optional[User]:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    try:
        session = UserSessionService(db).validate(token)
        return db.query(User).filter(User.id == session.user_id).first()
    except HTTPException:
        return None
