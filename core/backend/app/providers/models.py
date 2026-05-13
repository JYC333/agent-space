"""
Provider domain models — Pydantic schemas for API request/response and internal use.
"""

from pydantic import BaseModel
from typing import Optional


class ProviderConfigCreate(BaseModel):
    """Request body for creating a new provider config."""
    name: str
    provider: str  # litellm provider id, e.g. "openai", "anthropic", "azure/openai"
    api_key: str
    models: list[str]
    api_base: Optional[str] = None
    is_default: bool = False


class ProviderConfigUpdate(BaseModel):
    """Request body for updating a provider config."""
    name: Optional[str] = None
    api_key: Optional[str] = None
    models: Optional[list[str]] = None
    api_base: Optional[str] = None
    is_default: Optional[bool] = None
    status: Optional[str] = None


class ProviderConfigOut(BaseModel):
    """Response body — never exposes raw API key."""
    id: str
    space_id: str
    name: str
    provider: str
    models: list[str]
    api_base: Optional[str]
    is_default: bool
    status: str
    created_at: str
    updated_at: str

    @classmethod
    def from_db_row(cls, row) -> "ProviderConfigOut":
        caps = getattr(row, "capabilities_json", None)
        if caps is None:
            caps = getattr(row, "models", None)
        if isinstance(caps, dict):
            models_list = caps.get("models", [])
        elif isinstance(caps, list):
            models_list = caps
        else:
            models_list = []
        cfg = getattr(row, "config_json", None) or {}
        lifecycle = cfg.get("lifecycle_status", "active")
        is_default = bool(cfg.get("is_default", False))
        prov = getattr(row, "provider", None) or getattr(row, "provider_type", "")
        api_base = getattr(row, "api_base", None)
        if api_base is None:
            api_base = getattr(row, "base_url", None)
        return cls(
            id=row.id,
            space_id=row.space_id,
            name=row.name,
            provider=prov,
            models=models_list,
            api_base=api_base,
            is_default=is_default,
            status=lifecycle,
            created_at=row.created_at.isoformat(),
            updated_at=row.updated_at.isoformat(),
        )


class ProviderConfigDB(BaseModel):
    """
    Internal model passed to adapters — holds decrypted API key.
    Never expose this outside the service layer.
    """
    id: str
    space_id: str
    name: str
    provider: str
    api_key: str  # decrypted
    models: list[str]
    api_base: Optional[str]
    is_default: bool
    status: str


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