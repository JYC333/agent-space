"""
ModelProvider domain models — Pydantic schemas for API request/response and internal use.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

ProviderType = Literal[
    "openai",
    "anthropic",
    "openrouter",
    "ollama",
    "custom_openai_compatible",
    "other",
]


class ModelProviderCreate(BaseModel):
    name: str
    provider_type: ProviderType
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    default_model: Optional[str] = None
    available_models: list[str] = Field(default_factory=list)
    enabled: bool = True
    is_default: bool = False


class ModelProviderUpdate(BaseModel):
    name: Optional[str] = None
    provider_type: Optional[ProviderType] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    default_model: Optional[str] = None
    available_models: Optional[list[str]] = None
    enabled: Optional[bool] = None
    is_default: Optional[bool] = None


class ModelProviderOut(BaseModel):
    """Response body — never exposes raw API key."""

    id: str
    space_id: str
    name: str
    provider_type: str
    base_url: Optional[str]
    default_model: Optional[str]
    available_models: list[str]
    enabled: bool
    is_default: bool
    has_api_key: bool
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_db_row(cls, row) -> "ModelProviderOut":
        caps = row.capabilities_json or {}
        if isinstance(caps, dict):
            models_list = list(caps.get("models") or [])
        elif isinstance(caps, list):
            models_list = list(caps)
        else:
            models_list = []
        cfg = row.config_json or {}
        has_key = bool(row.credential_id)
        return cls(
            id=row.id,
            space_id=row.space_id,
            name=row.name,
            provider_type=row.provider_type,
            base_url=row.base_url,
            default_model=row.default_model,
            available_models=models_list,
            enabled=bool(row.enabled),
            is_default=bool(cfg.get("is_default", False)),
            has_api_key=has_key,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )


class ModelProviderInternal(BaseModel):
    """Internal model with decrypted API key — never expose via HTTP."""

    id: str
    space_id: str
    name: str
    provider_type: str
    api_key: str
    available_models: list[str]
    base_url: Optional[str]
    default_model: Optional[str]
    is_default: bool
    enabled: bool


class ModelProviderModelsOut(BaseModel):
    models: list[str]
    source: Literal["configured", "live"]


class ConnectionTestResult(BaseModel):
    success: bool
    message: str
    model: Optional[str] = None


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    provider_id: Optional[str] = None
    model: Optional[str] = None
    messages: list[ChatMessage]
    system: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None


class ChatResponse(BaseModel):
    content: str
    provider: str
    model: str
    usage: dict


class StreamChunk(BaseModel):
    delta: str
    finish_reason: Optional[str] = None
