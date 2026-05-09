from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel


class JobOut(BaseModel):
    id: str
    space_id: str
    user_id: str
    workspace_id: str | None
    agent_id: str | None
    job_type: str
    status: str
    priority: int
    payload: dict | None
    result: dict | None
    error: str | None
    attempts: int
    max_attempts: int
    claimed_by: str | None
    claimed_at: datetime | None
    scheduled_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class JobEventOut(BaseModel):
    id: str
    job_id: str
    event_type: str
    message: str
    data: dict | None
    created_at: datetime

    model_config = {"from_attributes": True}
