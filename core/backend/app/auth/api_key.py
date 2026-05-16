from __future__ import annotations
"""
API key authentication.

Key format:  ask_<32 hex chars>   (agent-space-key)
Storage:     SHA-256 hash of the raw key — raw key is never stored.
Header:      Authorization: Bearer ask_<...>

Behaviour:
  - Token present → validate against api_keys table → return (space_id, user_id)
  - Token absent → validate the session cookie and selected space membership
  - No valid token/session → 401

Usage in route:
    ids: tuple[str, str] = Depends(get_identity)
    space_id, user_id = ids
"""

import hashlib
import secrets
from datetime import datetime, UTC
from typing import Any, Optional

from fastapi import Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from ulid import ULID

from ..db import get_db
from ..feature_gates import API_KEYS_DB_PERSISTED, feature_not_implemented
from ..models import SpaceMembership
from ..param_binding import wire_header


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


def _require_active_membership(db: Session, *, space_id: str, user_id: str) -> None:
    membership = (
        db.query(SpaceMembership)
        .filter(
            SpaceMembership.space_id == space_id,
            SpaceMembership.user_id == user_id,
            SpaceMembership.status == "active",
        )
        .first()
    )
    if membership is None:
        raise HTTPException(status_code=403, detail="Not a member of this space")


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
    ) -> tuple[Any, str]:
        """
        Create a new API key. Returns (record, raw_key).
        The raw key is returned exactly once — it is not recoverable afterward.
        """
        del space_id, owner_user_id, name, scope, expires_at
        if not API_KEYS_DB_PERSISTED:
            feature_not_implemented("api_keys")

    def validate(self, raw_key: str) -> Any:
        """
        Validate a raw key string. Returns the stored key row on success.
        Raises HTTPException 401 on any failure.
        """
        del raw_key
        if not API_KEYS_DB_PERSISTED:
            feature_not_implemented("api_keys")

    def revoke(self, key_id: str, space_id: str) -> bool:
        del key_id, space_id
        if not API_KEYS_DB_PERSISTED:
            feature_not_implemented("api_keys")

    def list(self, space_id: str, owner_user_id: Optional[str] = None) -> list[Any]:
        del space_id, owner_user_id
        if not API_KEYS_DB_PERSISTED:
            feature_not_implemented("api_keys")


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------

def get_identity(
    request: Request,
    authorization: Optional[str] = wire_header(None, wire_name="Authorization"),
    space_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
) -> tuple[str, str]:
    """
    Resolves (space_id, user_id) for a request.

    Priority:
      1. Valid Bearer token  → space_id/user_id from the API key record
      2. Valid session cookie → user_id from session; space_id from query param or user default
      3. No auth          → 401
    """
    if authorization and authorization.startswith("Bearer "):
        raw = authorization[7:].strip()
        key = ApiKeyService(db).validate(raw)
        return (key.space_id, key.owner_user_id)
    session_token = request.cookies.get("session_id")
    if session_token:
        from .session import UserSessionService
        from ..models import User
        session = UserSessionService(db).validate_or_none(session_token)
        if session:
            user = db.query(User).filter(User.id == session.user_id).first()
            if user:
                effective_space = space_id or user.default_space_id
                if not effective_space:
                    raise HTTPException(status_code=403, detail="No active space selected")
                _require_active_membership(db, space_id=effective_space, user_id=user.id)
                return (effective_space, user.id)

    raise HTTPException(status_code=401, detail="Authentication required")
