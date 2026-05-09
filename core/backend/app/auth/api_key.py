from __future__ import annotations
"""
API key authentication.

Key format:  ask_<32 hex chars>   (agent-space-key)
Storage:     SHA-256 hash of the raw key — raw key is never stored.
Header:      Authorization: Bearer ask_<...>

Behaviour:
  - Token present → validate against api_keys table → return (space_id, user_id)
  - Token absent → fall back to query params or configured defaults

Usage in route:
    ids: tuple[str, str] = Depends(get_identity)
    space_id, user_id = ids
"""

import hashlib
import secrets
from datetime import datetime, UTC
from typing import Optional

from fastapi import Depends, Header, HTTPException, Query, Request
from sqlalchemy.orm import Session
from ulid import ULID

from ..config import settings
from ..db import get_db
from ..models import ApiKey


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _new_id() -> str:
    return str(ULID())


def generate_key() -> str:
    """Generate a new raw API key. Call once; the raw value is shown only here."""
    return "ask_" + secrets.token_hex(32)


def hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class ApiKeyService:
    def __init__(self, db: Session):
        self.db = db

    def create(
        self,
        space_id: str,
        owner_user_id: str,
        name: str,
        scope: str = "full",
        expires_at: Optional[datetime] = None,
    ) -> tuple[ApiKey, str]:
        """
        Create a new API key. Returns (ApiKey record, raw_key).
        The raw key is returned exactly once — it is not recoverable afterward.
        """
        raw = generate_key()
        key = ApiKey(
            id=_new_id(),
            space_id=space_id,
            owner_user_id=owner_user_id,
            name=name,
            key_hash=hash_key(raw),
            scope=scope,
            status="active",
            expires_at=expires_at,
        )
        self.db.add(key)
        self.db.commit()
        self.db.refresh(key)
        return key, raw

    def validate(self, raw_key: str) -> ApiKey:
        """
        Validate a raw key string. Returns the ApiKey on success.
        Raises HTTPException 401 on any failure.
        """
        h = hash_key(raw_key)
        key = self.db.query(ApiKey).filter(ApiKey.key_hash == h).first()

        if not key:
            raise HTTPException(status_code=401, detail="Invalid API key")
        if key.status != "active":
            raise HTTPException(status_code=401, detail="API key revoked")
        if key.expires_at and key.expires_at < datetime.now(UTC):
            raise HTTPException(status_code=401, detail="API key expired")

        key.last_used_at = datetime.now(UTC)
        self.db.commit()
        return key

    def revoke(self, key_id: str, space_id: str) -> bool:
        key = (
            self.db.query(ApiKey)
            .filter(ApiKey.id == key_id, ApiKey.space_id == space_id)
            .first()
        )
        if not key:
            return False
        key.status = "revoked"
        key.updated_at = datetime.now(UTC)
        self.db.commit()
        return True

    def list(self, space_id: str, owner_user_id: Optional[str] = None) -> list[ApiKey]:
        q = self.db.query(ApiKey).filter(
            ApiKey.space_id == space_id,
            ApiKey.status == "active",
        )
        if owner_user_id:
            q = q.filter(ApiKey.owner_user_id == owner_user_id)
        return q.order_by(ApiKey.created_at.desc()).all()


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------

def get_identity(
    request: Request,
    authorization: Optional[str] = Header(None, alias="Authorization"),
    space_id: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
) -> tuple[str, str]:
    """
    Resolves (space_id, user_id) for a request.

    Priority:
      1. Valid Bearer token  → space_id/user_id from the ApiKey record
      2. Valid session cookie → user_id from session; space_id from query param or user default
      3. No auth, dev mode   → query params or configured defaults
          """
    if authorization and authorization.startswith("Bearer "):
        raw = authorization[7:].strip()
        key = ApiKeyService(db).validate(raw)
        return (key.space_id, key.owner_user_id)

    # Session cookie
    session_token = request.cookies.get("session_id")
    if session_token:
        from .session import UserSessionService
        from ..models import User
        session = UserSessionService(db).validate_or_none(session_token)
        if session:
            user = db.query(User).filter(User.id == session.user_id).first()
            if user:
                effective_space = space_id or user.default_space_id or settings.default_space_id
                return (effective_space, user.id)

    return (
        space_id or settings.default_space_id,
        user_id or settings.default_user_id,
    )
