"""SourcePointer API schemas (metadata only — no source content fields)."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class SourcePointerCreate(BaseModel):
    """Create body — ``granted_by_user_id`` is server-assigned from the authenticated user."""

    model_config = ConfigDict(extra="forbid")

    owner_space_id: str
    source_space_id: str
    source_object_type: str = Field(..., min_length=1, max_length=64)
    source_object_id: str
    access_mode: str = Field(..., min_length=1, max_length=32)
    expires_at: Optional[datetime] = None
    metadata_json: Optional[dict] = None


class SourcePointerOut(BaseModel):
    id: str
    owner_space_id: str
    source_space_id: str
    source_object_type: str
    source_object_id: str
    access_mode: str
    granted_by_user_id: Optional[str] = None
    expires_at: Optional[datetime] = None
    metadata_json: Optional[dict] = None
    created_at: datetime

    model_config = {"from_attributes": True}
