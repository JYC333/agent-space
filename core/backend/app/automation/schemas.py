"""Pydantic schemas for the Automation API."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


_FORBIDDEN_CONFIG_KEYS = frozenset({
    "api_key",
    "token",
    "secret",
    "password",
    "credential",
    "personal_context_block",
    "approved_by_user",
    "approved_by_granting_user",
    "approval_status",
    "is_approved",
    "auto_approved",
    "pre_approved",
})
_MAX_CONFIG_JSON_BYTES = 8192
_MAX_CONFIG_DEPTH = 8
_MAX_CONFIG_STRING_LENGTH = 2048


def _validate_config_json(value: dict | None) -> dict | None:
    if value is None:
        return None
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise ValueError("config_json must be JSON serializable") from exc
    if len(encoded.encode("utf-8")) > _MAX_CONFIG_JSON_BYTES:
        raise ValueError(
            f"config_json exceeds maximum serialized size of {_MAX_CONFIG_JSON_BYTES} bytes"
        )

    def walk(node: Any, *, depth: int) -> None:
        if depth > _MAX_CONFIG_DEPTH:
            raise ValueError(f"config_json exceeds maximum depth of {_MAX_CONFIG_DEPTH}")
        if isinstance(node, dict):
            for key, child in node.items():
                if str(key).lower() in _FORBIDDEN_CONFIG_KEYS:
                    raise ValueError(f"config_json contains forbidden key {key!r}")
                walk(child, depth=depth + 1)
        elif isinstance(node, list):
            for child in node:
                walk(child, depth=depth + 1)
        elif isinstance(node, str) and len(node) > _MAX_CONFIG_STRING_LENGTH:
            raise ValueError(
                f"config_json string exceeds maximum length of {_MAX_CONFIG_STRING_LENGTH}"
            )

    walk(value, depth=1)
    return value


class AutomationCreate(BaseModel):
    """Input for POST /api/v1/spaces/{space_id}/automations."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=256)
    agent_id: str
    workspace_id: Optional[str] = None
    description: Optional[str] = None
    trigger_type: str = Field(default="manual")
    config_json: Optional[dict] = None

    @field_validator("config_json")
    @classmethod
    def validate_config_json(cls, value: dict | None) -> dict | None:
        return _validate_config_json(value)


class AutomationUpdate(BaseModel):
    """Input for PATCH /api/v1/spaces/{space_id}/automations/{id}."""

    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(default=None, min_length=1, max_length=256)
    description: Optional[str] = None
    status: Optional[str] = None
    config_json: Optional[dict] = None

    @field_validator("config_json")
    @classmethod
    def validate_config_json(cls, value: dict | None) -> dict | None:
        return _validate_config_json(value)


class AutomationFireRequest(BaseModel):
    """Input for POST /api/v1/spaces/{space_id}/automations/{id}/fire."""

    model_config = ConfigDict(extra="forbid")

    prompt: Optional[str] = None
    instruction: Optional[str] = None


class AutomationOut(BaseModel):
    """Serialized Automation for API responses."""

    id: str
    space_id: str
    owner_user_id: str
    agent_id: str
    workspace_id: Optional[str]
    name: str
    description: Optional[str]
    trigger_type: str
    status: str
    preflight_snapshot_json: Optional[dict]
    config_json: Optional[dict]
    created_at: datetime
    updated_at: datetime


class AutomationFireResult(BaseModel):
    """Result of a manual automation fire."""

    run_id: str
    automation_run_id: str
    trigger_origin: str
    preflight_executable: bool
