"""
ModelService — the central service all API routes call.

Responsibilities:
- resolve provider/model config
- resolve API key (decrypt)
- call selected provider adapter via registry
- normalize response
- log usage
- handle errors consistently

ModelService never calls litellm directly — always goes through a registered adapter.
"""

from __future__ import annotations

import logging
from typing import AsyncIterator

import httpx
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified
from ulid import ULID

from ..crypto import encrypt_to_base64
from ..models import Credential, ModelProvider
from ..secrets.secret_ref import encode_model_provider_api_key_secret_ref
from .models import (
    ChatRequest,
    ChatResponse,
    ConnectionTestResult,
    ModelProviderCreate,
    ModelProviderInternal,
    ModelProviderModelsOut,
    ModelProviderOut,
    ModelProviderUpdate,
    StreamChunk,
    ChatMessage,
)
from .registry import registry
from .validation import ModelProviderValidationError, validate_create_fields, validate_update_base_url
from ..runtimes.credentials import resolve_provider_api_key

log = logging.getLogger(__name__)


def _mp_cfg(row: ModelProvider) -> dict:
    return dict(row.config_json or {})


def _mp_set_cfg(row: ModelProvider, data: dict) -> None:
    row.config_json = data
    flag_modified(row, "config_json")


def _mp_is_default(row: ModelProvider) -> bool:
    return bool(_mp_cfg(row).get("is_default", False))


def _available_models(row: ModelProvider) -> list[str]:
    caps = row.capabilities_json or {}
    if isinstance(caps, dict):
        return list(caps.get("models") or [])
    if isinstance(caps, list):
        return list(caps)
    return []


def _has_api_key(row: ModelProvider) -> bool:
    return bool(row.credential_id)


def _attach_api_key_credential(
    db: Session,
    *,
    space_id: str,
    row: ModelProvider,
    api_key: str,
) -> None:
    """Store provider API key as a Credential row referenced by Credential.secret_ref."""
    encrypted_key, key_nonce = _encrypt(api_key)
    secret_ref = encode_model_provider_api_key_secret_ref(encrypted_key, key_nonce)

    if row.credential_id:
        cred = (
            db.query(Credential)
            .filter(Credential.id == row.credential_id, Credential.space_id == space_id)
            .first()
        )
        if cred is not None:
            cred.secret_ref = secret_ref
            cfg = _mp_cfg(row)
            cfg.pop("encrypted_key", None)
            cfg.pop("key_nonce", None)
            _mp_set_cfg(row, cfg)
            return

    cred = Credential(
        id=str(ULID()),
        space_id=space_id,
        name=f"{row.name} API key",
        credential_type="api_key",
        secret_ref=secret_ref,
        scopes_json=[],
    )
    db.add(cred)
    row.credential_id = cred.id
    cfg = _mp_cfg(row)
    cfg.pop("encrypted_key", None)
    cfg.pop("key_nonce", None)
    _mp_set_cfg(row, cfg)


class ModelService:
    """Central service for LLM provider operations."""

    def list_configs(self, db: Session, space_id: str) -> list[ModelProviderOut]:
        rows = (
            db.query(ModelProvider)
            .filter(ModelProvider.space_id == space_id)
            .order_by(ModelProvider.created_at.desc())
            .all()
        )
        return [ModelProviderOut.from_db_row(r) for r in rows]

    def get_config_row(self, db: Session, config_id: str, space_id: str) -> ModelProvider:
        row = db.query(ModelProvider).filter(
            ModelProvider.id == config_id,
            ModelProvider.space_id == space_id,
        ).first()
        if not row:
            raise ValueError(f"ModelProvider '{config_id}' not found")
        return row

    def get_config(self, db: Session, config_id: str, space_id: str) -> ModelProviderInternal:
        row = self.get_config_row(db, config_id, space_id)
        if not row.enabled:
            raise ValueError(f"ModelProvider '{config_id}' is disabled")

        api_key = resolve_provider_api_key(db, row.id)

        return ModelProviderInternal(
            id=row.id,
            space_id=row.space_id,
            name=row.name,
            provider_type=row.provider_type,
            api_key=api_key,
            available_models=_available_models(row),
            base_url=row.base_url,
            default_model=row.default_model,
            is_default=_mp_is_default(row),
            enabled=row.enabled,
        )

    def create_config(
        self, db: Session, space_id: str, data: ModelProviderCreate
    ) -> ModelProviderOut:
        validate_create_fields(
            provider_type=data.provider_type,
            base_url=data.base_url,
            api_key=data.api_key,
        )
        if data.is_default:
            self._clear_default(db, space_id)

        cfg: dict = {"is_default": data.is_default}
        if data.api_key:
            pass  # attached via Credential after row is created

        models = list(data.available_models)
        if data.default_model and data.default_model not in models:
            models.insert(0, data.default_model)

        config = ModelProvider(
            id=str(ULID()),
            space_id=space_id,
            name=data.name.strip(),
            provider_type=data.provider_type,
            base_url=data.base_url,
            default_model=data.default_model or (models[0] if models else None),
            enabled=data.enabled,
            capabilities_json={"models": models},
            config_json=cfg,
        )
        db.add(config)
        db.flush()
        if data.api_key:
            _attach_api_key_credential(
                db, space_id=space_id, row=config, api_key=data.api_key
            )
            db.flush()
        db.commit()
        db.refresh(config)
        return ModelProviderOut.from_db_row(config)

    def update_config(
        self, db: Session, config_id: str, space_id: str, data: ModelProviderUpdate
    ) -> ModelProviderOut:
        row = self.get_config_row(db, config_id, space_id)

        if data.is_default and not _mp_is_default(row):
            self._clear_default(db, space_id)

        if data.name is not None:
            row.name = data.name.strip()
        if data.provider_type is not None:
            row.provider_type = data.provider_type
        if data.base_url is not None:
            row.base_url = data.base_url or None
        if data.api_key is not None and data.api_key.strip():
            _attach_api_key_credential(
                db, space_id=space_id, row=row, api_key=data.api_key.strip()
            )
            db.flush()
        if data.available_models is not None:
            row.capabilities_json = {"models": list(data.available_models)}
            flag_modified(row, "capabilities_json")
        if data.default_model is not None:
            row.default_model = data.default_model or None
        if data.enabled is not None:
            row.enabled = data.enabled
        if data.is_default is not None:
            c = _mp_cfg(row)
            c["is_default"] = data.is_default
            _mp_set_cfg(row, c)

        validate_update_base_url(row.provider_type, row.base_url)

        db.commit()
        db.refresh(row)
        return ModelProviderOut.from_db_row(row)

    def delete_config(self, db: Session, config_id: str, space_id: str) -> None:
        row = self.get_config_row(db, config_id, space_id)
        row.enabled = False
        c = _mp_cfg(row)
        c["is_default"] = False
        _mp_set_cfg(row, c)
        db.commit()

    def assert_selectable(self, db: Session, provider_id: str, space_id: str) -> ModelProvider:
        row = self.get_config_row(db, provider_id, space_id)
        if not row.enabled:
            raise ValueError(f"ModelProvider '{provider_id}' is disabled")
        return row

    def resolve_default_config(self, db: Session, space_id: str) -> ModelProviderInternal:
        row = None
        for r in db.query(ModelProvider).filter(ModelProvider.space_id == space_id).all():
            if _mp_is_default(r) and r.enabled:
                row = r
                break
        if not row:
            raise ValueError("No default provider configured")
        return self.get_config(db, row.id, space_id)

    def list_models(
        self, db: Session, config_id: str, space_id: str
    ) -> ModelProviderModelsOut:
        row = self.get_config_row(db, config_id, space_id)
        configured = _available_models(row)
        if configured:
            return ModelProviderModelsOut(models=configured, source="configured")
        if row.default_model:
            return ModelProviderModelsOut(models=[row.default_model], source="configured")

        live = self._try_live_model_list(db, row)
        if live:
            return ModelProviderModelsOut(models=live, source="live")
        return ModelProviderModelsOut(models=[], source="configured")

    def _try_live_model_list(self, db: Session, row: ModelProvider) -> list[str]:
        if row.provider_type == "ollama" and row.base_url:
            return self._fetch_ollama_models(row.base_url)
        if row.provider_type in {"openai", "openrouter", "custom_openai_compatible", "other"}:
            if row.base_url or row.provider_type in {"openai", "openrouter"}:
                return self._fetch_openai_compatible_models(db, row)
        return []

    def _fetch_ollama_models(self, base_url: str) -> list[str]:
        url = base_url.rstrip("/") + "/api/tags"
        try:
            with httpx.Client(timeout=5.0) as client:
                resp = client.get(url)
                resp.raise_for_status()
                data = resp.json()
            return [m.get("name", "") for m in data.get("models", []) if m.get("name")]
        except Exception as exc:
            log.debug("ollama model list failed: %s", exc)
            return []

    def _fetch_openai_compatible_models(self, db: Session, row: ModelProvider) -> list[str]:
        base = row.base_url
        if not base:
            if row.provider_type == "openrouter":
                base = "https://openrouter.ai/api/v1"
            else:
                base = "https://api.openai.com/v1"
        url = base.rstrip("/") + "/models"
        headers: dict[str, str] = {}
        if _has_api_key(row):
            headers["Authorization"] = f"Bearer {resolve_provider_api_key(db, row.id)}"
        try:
            with httpx.Client(timeout=5.0) as client:
                resp = client.get(url, headers=headers)
                resp.raise_for_status()
                data = resp.json()
            return [
                item.get("id", "")
                for item in data.get("data", [])
                if isinstance(item, dict) and item.get("id")
            ]
        except Exception as exc:
            log.debug("openai-compatible model list failed: %s", exc)
            return []

    async def chat(self, db: Session, request: ChatRequest, space_id: str) -> ChatResponse:
        if request.provider_id:
            config = self.get_config(db, request.provider_id, space_id)
        else:
            config = self.resolve_default_config(db, space_id)

        adapter = registry.get(config.provider_type) or registry.get("litellm")
        model = request.model or config.default_model
        if not model and config.available_models:
            model = config.available_models[0]

        log.info(
            "chat: provider=%s model=%s space=%s",
            config.provider_type,
            model or "unknown",
            space_id,
        )

        response = await adapter.complete(config.api_key, config.base_url, request)

        log.info(
            "chat done: provider=%s model=%s usage=%s",
            response.provider,
            response.model,
            response.usage,
        )
        return response

    async def chat_stream(
        self, db: Session, request: ChatRequest, space_id: str
    ) -> AsyncIterator[StreamChunk]:
        if request.provider_id:
            config = self.get_config(db, request.provider_id, space_id)
        else:
            config = self.resolve_default_config(db, space_id)

        adapter = registry.get(config.provider_type) or registry.get("litellm")
        log.info("stream: provider=%s model=%s space=%s", config.provider_type, request.model, space_id)

        async for chunk in adapter.stream(config.api_key, config.base_url, request):
            yield chunk

    async def test_connection(
        self, db: Session, config_id: str, space_id: str
    ) -> ConnectionTestResult:
        try:
            config = self.get_config(db, config_id, space_id)
            adapter = registry.get(config.provider_type) or registry.get("litellm")
            model_name = config.default_model or (config.available_models[0] if config.available_models else None)

            if not model_name:
                return ConnectionTestResult(success=False, message="No models configured")

            if "/" not in model_name:
                model_name = f"{config.provider_type}/{model_name}"

            test_request = ChatRequest(
                model=model_name,
                messages=[ChatMessage(role="user", content="Hi")],
                max_tokens=5,
            )

            response = await adapter.complete(config.api_key, config.base_url, test_request)
            return ConnectionTestResult(
                success=True,
                message="Connection successful",
                model=response.model,
            )
        except Exception as exc:
            return ConnectionTestResult(success=False, message=str(exc))

    def _clear_default(self, db: Session, space_id: str) -> None:
        for row in db.query(ModelProvider).filter(ModelProvider.space_id == space_id).all():
            if not _mp_is_default(row):
                continue
            c = _mp_cfg(row)
            c["is_default"] = False
            _mp_set_cfg(row, c)


def _encrypt(plaintext: str) -> tuple[str, str]:
    from ..crypto import encrypt_to_base64
    return encrypt_to_base64(plaintext)


# Register adapters on module load
from .registry import registry as _reg  # noqa: E402, F401
from .litellm_provider import LiteLLMProvider as _LP  # noqa: E402, F401
