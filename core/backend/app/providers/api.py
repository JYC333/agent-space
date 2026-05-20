"""
Provider config API — routes for CRUD and chat via ModelService.
"""

import litellm

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import get_identity
from ..db import get_db
from .models import (
    ChatRequest as ChatRequestModel,
    ChatResponse,
    ConnectionTestResult,
    ModelProviderCreate,
    ModelProviderModelsOut,
    ModelProviderOut,
    ModelProviderUpdate,
)
from .service import ModelService
from .validation import ModelProviderValidationError

router = APIRouter(prefix="/providers", tags=["providers"])

service = ModelService()


@router.get("/litellm-providers")
def get_litellm_providers(_: tuple[str, str] = Depends(get_identity)):
    """Return the list of provider IDs supported by litellm."""
    return litellm.LITELLM_CHAT_PROVIDERS


CATALOG_INFO = {
    "id": "litellm",
    "name": "LiteLLM (Open Format)",
    "description": (
        "Configure OpenAI, Anthropic, OpenRouter, Ollama, or custom OpenAI-compatible endpoints."
    ),
    "model_hint": "Set default_model and/or available_models on the provider",
    "supported_params": ["model", "temperature", "max_tokens", "system"],
}


@router.get("/catalog")
def get_catalog(_: tuple[str, str] = Depends(get_identity)):
    return CATALOG_INFO


@router.get("", response_model=list[ModelProviderOut])
def list_configs(
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, _ = ids
    return service.list_configs(db, space_id)


@router.post("", response_model=ModelProviderOut, status_code=201)
def create_config(
    body: ModelProviderCreate,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, _ = ids
    try:
        return service.create_config(db, space_id, body)
    except ModelProviderValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{config_id}", response_model=ModelProviderOut)
def get_config(
    config_id: str,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, _ = ids
    try:
        row = service.get_config_row(db, config_id, space_id)
        return ModelProviderOut.from_db_row(row)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/{config_id}", response_model=ModelProviderOut)
def update_config(
    config_id: str,
    body: ModelProviderUpdate,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, _ = ids
    try:
        return service.update_config(db, config_id, space_id, body)
    except ModelProviderValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/{config_id}", status_code=204)
def delete_config(
    config_id: str,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, _ = ids
    try:
        service.delete_config(db, config_id, space_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{config_id}/models", response_model=ModelProviderModelsOut)
def list_provider_models(
    config_id: str,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, _ = ids
    try:
        return service.list_models(db, config_id, space_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{config_id}/test", response_model=ConnectionTestResult)
async def test_config(
    config_id: str,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, _ = ids
    try:
        return await service.test_connection(db, config_id, space_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/chat", response_model=ChatResponse)
async def chat(
    body: ChatRequestModel,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, _ = ids
    try:
        return await service.chat(db, body, space_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
