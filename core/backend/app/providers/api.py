"""
Provider config API — routes for CRUD and chat via ModelService.

All heavy lifting delegated to ModelService / LiteLLMProvider / ProviderRegistry.
"""

import litellm

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ..auth import get_identity
from ..db import get_db
from .models import (
    ProviderConfigCreate, ProviderConfigUpdate, ProviderConfigOut,
    ChatRequest as ChatRequestModel, ChatResponse,
    ConnectionTestResult,
)
from .service import ModelService

router = APIRouter(prefix="/providers", tags=["providers"])

service = ModelService()


@router.get("/litellm-providers")
def get_litellm_providers():
    """Return the list of provider IDs supported by litellm."""
    return litellm.LITELLM_CHAT_PROVIDERS


# ---------------------------------------------------------------------------
# Catalog (liteLLM open format — no hardcoded provider list)
# ---------------------------------------------------------------------------

CATALOG_INFO = {
    "id": "litellm",
    "name": "LiteLLM (Open Format)",
    "description": (
        "支持 100+ LLM 供应商。填写任意 litellm 模型名，如 'openai/gpt-4o'、"
        "'anthropic/claude-3-5-sonnet-20241022'、'deepseek/deepseek-chat' 等。"
    ),
    "model_hint": "填写任意 litellm 支持的 model name（格式：provider/model 或纯 model 名）",
    "supported_params": ["model", "temperature", "max_tokens", "system"],
}


@router.get("/catalog")
def get_catalog():
    """Return catalog metadata — describes litellm open format, not a fixed list."""
    return CATALOG_INFO


# ---------------------------------------------------------------------------
# Config CRUD
# ---------------------------------------------------------------------------

@router.get("", response_model=list[ProviderConfigOut])
def list_configs(
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """List all provider configurations for the current space."""
    space_id, _ = ids
    return service.list_configs(db, space_id)


@router.post("", response_model=ProviderConfigOut, status_code=201)
def create_config(
    body: ProviderConfigCreate,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """Add a new provider configuration. No provider catalog validation — any litellm model name works."""
    space_id, _ = ids

    if not body.models:
        raise HTTPException(status_code=400, detail="At least one model is required")

    try:
        return service.create_config(db, space_id, body)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/{config_id}", response_model=ProviderConfigOut)
def get_config(
    config_id: str,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """Get a single provider configuration."""
    space_id, _ = ids
    try:
        cfg = service.get_config(db, config_id, space_id)
        # Return public shape (no api_key)
        return ProviderConfigOut(
            id=cfg.id,
            space_id=cfg.space_id,
            name=cfg.name,
            provider=cfg.provider,
            models=cfg.models,
            api_base=cfg.api_base,
            is_default=cfg.is_default,
            status=cfg.status,
            created_at="",  # not needed for public response
            updated_at="",
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.put("/{config_id}", response_model=ProviderConfigOut)
def update_config(
    config_id: str,
    body: ProviderConfigUpdate,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """Update a provider configuration."""
    space_id, _ = ids
    try:
        return service.update_config(db, config_id, space_id, body)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.delete("/{config_id}", status_code=204)
def delete_config(
    config_id: str,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """Delete (soft) a provider configuration."""
    space_id, _ = ids
    try:
        service.delete_config(db, config_id, space_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/{config_id}/test", response_model=ConnectionTestResult)
async def test_config(
    config_id: str,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """Test a provider configuration."""
    space_id, _ = ids
    try:
        return await service.test_connection(db, config_id, space_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------

@router.post("/chat", response_model=ChatResponse)
async def chat(
    body: ChatRequestModel,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """
    Send a chat message via a configured LLM provider.

    provider_id: if omitted, uses the space's default provider.
    model:        if omitted, uses the provider's first configured model.
    """
    space_id, _ = ids
    try:
        return await service.chat(db, body, space_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))