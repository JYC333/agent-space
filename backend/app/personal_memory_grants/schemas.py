"""PersonalMemoryGrant API schemas.

Request schemas use extra="forbid" so client-supplied server-derived fields
(granting_user_id, personal_space_id, status, target_agent_id) are rejected as 422.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

MIN_EXPIRES_SECONDS = 60
MAX_EXPIRES_SECONDS = 86400


class GrantCreate(BaseModel):
    """POST /api/v1/personal-memory-grants request body.

    granting_user_id and personal_space_id are server-derived — rejected as extra fields.
    target_agent_id is deferred — rejected as extra field.
    status is server-assigned — rejected as extra field.
    """

    model_config = ConfigDict(extra="forbid")

    target_space_id: str
    target_run_id: str
    access_mode: str = "summary_only"
    memory_filter: Optional[dict] = None
    read_expires_in_seconds: int = Field(..., ge=MIN_EXPIRES_SECONDS, le=MAX_EXPIRES_SECONDS)


class GrantPreviewRequest(BaseModel):
    """POST /api/v1/personal-memory-grants/preview request body."""

    model_config = ConfigDict(extra="forbid")

    target_space_id: str
    target_run_id: str
    access_mode: str = "summary_only"
    memory_filter: Optional[dict] = None
    read_expires_in_seconds: Optional[int] = Field(
        None, ge=MIN_EXPIRES_SECONDS, le=MAX_EXPIRES_SECONDS
    )


class GrantOut(BaseModel):
    """Grant lifecycle response — no raw memory content."""

    id: str
    granting_user_id: str
    personal_space_id: str
    target_space_id: str
    target_run_id: str
    target_agent_id: Optional[str] = None
    grant_scope: str
    access_mode: str
    status: str
    memory_filter_json: Optional[dict] = None
    read_expires_at: datetime
    revoked_at: Optional[datetime] = None
    used_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PreviewOut(BaseModel):
    """Structural-only preview — no raw memory text, no memory IDs."""

    eligible: bool
    target_space_id: str
    target_run_id: str
    access_mode: str
    proposed_read_expires_at: Optional[datetime] = None
    warnings: list[str] = []
    excluded_sensitivity_levels: list[str] = Field(
        default_factory=lambda: ["restricted", "highly_restricted"]
    )
    max_items: Optional[int] = None


class GrantEventOut(BaseModel):
    """Safe audit event — metadata_json must not contain content fields."""

    id: str
    grant_id: str
    event_type: str
    actor_user_id: Optional[str] = None
    run_id: Optional[str] = None
    metadata_json: Optional[dict] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class AuditOut(BaseModel):
    """Audit trail: grant metadata + events. No raw memory content."""

    grant: GrantOut
    events: list[GrantEventOut]
