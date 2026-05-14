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

import logging
from typing import AsyncIterator
from ulid import ULID

from sqlalchemy.orm import Session

from ..crypto import decrypt_from_base64
from sqlalchemy.orm.attributes import flag_modified

from ..models import ModelProvider
from .models import (
    ChatRequest, ChatResponse, StreamChunk, ChatMessage,
    ProviderConfigDB, ProviderConfigOut,
    ConnectionTestResult, ProviderConfigCreate, ProviderConfigUpdate,
)
from .registry import registry

log = logging.getLogger(__name__)


def _mp_cfg(row: ModelProvider) -> dict:
    return dict(row.config_json or {})


def _mp_set_cfg(row: ModelProvider, data: dict) -> None:
    row.config_json = data
    flag_modified(row, "config_json")


def _mp_lifecycle(row: ModelProvider) -> str:
    return _mp_cfg(row).get("lifecycle_status", "active")


def _mp_is_default(row: ModelProvider) -> bool:
    return bool(_mp_cfg(row).get("is_default", False))


class ModelService:
    """
    Central service for LLM provider operations.
    All api.py routes call this — never litellm directly.
    """

    # -------------------------------------------------------------------------
    # Config management
    # -------------------------------------------------------------------------

    def list_configs(self, db: Session, space_id: str) -> list[ProviderConfigOut]:
        """List all active provider configs for a space (no raw keys)."""
        rows = db.query(ModelProvider).filter(ModelProvider.space_id == space_id).all()
        return [
            ProviderConfigOut.from_db_row(r)
            for r in rows
            if _mp_lifecycle(r) != "deleted"
        ]

    def get_config(self, db: Session, config_id: str, space_id: str) -> ProviderConfigDB:
        """Load a config by ID and decrypt the API key. Raises if not found or deleted."""
        row = db.query(ModelProvider).filter(
            ModelProvider.id == config_id,
            ModelProvider.space_id == space_id,
        ).first()
        if not row or _mp_lifecycle(row) == "deleted":
            raise ValueError(f"Provider config '{config_id}' not found")

        ek = _mp_cfg(row).get("encrypted_key")
        kn = _mp_cfg(row).get("key_nonce")
        if not ek or not kn:
            raise ValueError(f"Provider config '{config_id}' has no stored credentials")

        return ProviderConfigDB(
            id=row.id,
            space_id=row.space_id,
            name=row.name,
            provider=row.provider,
            api_key=decrypt_from_base64(ek, kn),
            models=row.models if isinstance(row.models, list) else (row.models or {}).get("models", []),
            api_base=row.api_base,
            is_default=_mp_is_default(row),
            status=_mp_lifecycle(row),
        )

    def create_config(
        self, db: Session, space_id: str, data: ProviderConfigCreate
    ) -> ProviderConfigOut:
        """Create a new provider config with encrypted API key."""
        if data.is_default:
            self._clear_default(db, space_id)

        encrypted_key, key_nonce = _encrypt(data.api_key)

        cfg = {
            "encrypted_key": encrypted_key,
            "key_nonce": key_nonce,
            "is_default": data.is_default,
            "lifecycle_status": "active",
        }
        config = ModelProvider(
            id=str(ULID()),
            space_id=space_id,
            name=data.name,
            provider_type=data.provider,
            base_url=data.api_base,
            default_model=data.models[0] if data.models else None,
            enabled=True,
            capabilities_json={"models": data.models},
            config_json=cfg,
        )
        db.add(config)
        db.commit()
        db.refresh(config)
        return ProviderConfigOut.from_db_row(config)

    def update_config(
        self, db: Session, config_id: str, space_id: str, data: ProviderConfigUpdate
    ) -> ProviderConfigOut:
        """Update a provider config (optionally update the API key)."""
        row = db.query(ModelProvider).filter(
            ModelProvider.id == config_id,
            ModelProvider.space_id == space_id,
        ).first()
        if not row:
            raise ValueError(f"Provider config '{config_id}' not found")

        if data.is_default and not _mp_is_default(row):
            self._clear_default(db, space_id)

        if data.name is not None:
            row.name = data.name
        if data.api_key is not None:
            encrypted_key, key_nonce = _encrypt(data.api_key)
            c = _mp_cfg(row)
            c["encrypted_key"] = encrypted_key
            c["key_nonce"] = key_nonce
            _mp_set_cfg(row, c)
        if data.models is not None:
            row.capabilities_json = {"models": data.models}
            flag_modified(row, "capabilities_json")
        if data.api_base is not None:
            row.base_url = data.api_base
        if data.is_default is not None:
            c = _mp_cfg(row)
            c["is_default"] = data.is_default
            _mp_set_cfg(row, c)
        if data.status is not None:
            c = _mp_cfg(row)
            c["lifecycle_status"] = data.status
            _mp_set_cfg(row, c)
            row.enabled = data.status != "deleted"

        db.commit()
        db.refresh(row)
        return ProviderConfigOut.from_db_row(row)

    def delete_config(self, db: Session, config_id: str, space_id: str) -> None:
        """Soft-delete a provider config."""
        row = db.query(ModelProvider).filter(
            ModelProvider.id == config_id,
            ModelProvider.space_id == space_id,
        ).first()
        if not row:
            raise ValueError(f"Provider config '{config_id}' not found")
        c = _mp_cfg(row)
        c["lifecycle_status"] = "deleted"
        _mp_set_cfg(row, c)
        row.enabled = False
        db.commit()

    def resolve_default_config(self, db: Session, space_id: str) -> ProviderConfigDB:
        """Find the default active provider config for a space. Raises if none."""
        row = None
        for r in db.query(ModelProvider).filter(ModelProvider.space_id == space_id).all():
            if _mp_is_default(r) and _mp_lifecycle(r) == "active":
                row = r
                break
        if not row:
            raise ValueError("No default provider configured")
        ek = _mp_cfg(row).get("encrypted_key")
        kn = _mp_cfg(row).get("key_nonce")
        if not ek or not kn:
            raise ValueError("No default provider configured")
        return ProviderConfigDB(
            id=row.id,
            space_id=row.space_id,
            name=row.name,
            provider=row.provider,
            api_key=decrypt_from_base64(ek, kn),
            models=row.models if isinstance(row.models, list) else (row.models or {}).get("models", []),
            api_base=row.api_base,
            is_default=True,
            status=_mp_lifecycle(row),
        )

    # -------------------------------------------------------------------------
    # Chat / Completion
    # -------------------------------------------------------------------------

    async def chat(self, db: Session, request: ChatRequest, space_id: str) -> ChatResponse:
        """
        Send a chat request to a provider.

        Resolves provider from request.provider_id or falls back to default.
        Uses the registered adapter (default: LiteLLMProvider) to make the call.

        ``db`` must be the request-scoped session (e.g. FastAPI ``Depends(get_db)``)
        so TestClient overrides and transaction boundaries stay consistent.
        """
        if request.provider_id:
            config = self.get_config(db, request.provider_id, space_id)
        else:
            config = self.resolve_default_config(db, space_id)

        adapter = registry.get(config.provider)
        if not adapter:
            adapter = registry.get("litellm")

        log.info(
            "chat: provider=%s model=%s space=%s",
            config.provider,
            request.model or config.models[0] if config.models else "unknown",
            space_id,
        )

        response = await adapter.complete(config.api_key, config.api_base, request)

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
        """Streaming version of :meth:`chat` using the same request-scoped ``db``."""
        if request.provider_id:
            config = self.get_config(db, request.provider_id, space_id)
        else:
            config = self.resolve_default_config(db, space_id)

        adapter = registry.get(config.provider) or registry.get("litellm")

        log.info("stream: provider=%s model=%s space=%s", config.provider, request.model, space_id)

        async for chunk in adapter.stream(config.api_key, config.api_base, request):
            yield chunk

    async def test_connection(
        self, db: Session, config_id: str, space_id: str
    ) -> ConnectionTestResult:
        """Test a provider config by making a minimal chat completion."""
        try:
            config = self.get_config(db, config_id, space_id)

            adapter = registry.get(config.provider) or registry.get("litellm")
            model_name = config.models[0] if config.models else None

            if not model_name:
                return ConnectionTestResult(success=False, message="No models configured")

            if "/" not in model_name:
                model_name = f"{config.provider}/{model_name}"

            test_request = ChatRequest(
                model=model_name,
                messages=[ChatMessage(role="user", content="Hi")],
                max_tokens=5,
            )

            response = await adapter.complete(config.api_key, config.api_base, test_request)
            return ConnectionTestResult(
                success=True,
                message="Connection successful",
                model=response.model,
            )
        except Exception as exc:
            return ConnectionTestResult(success=False, message=str(exc))

    # -------------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------------

    def _clear_default(self, db: Session, space_id: str) -> None:
        """Clear is_default on all configs in a space."""
        for row in db.query(ModelProvider).filter(ModelProvider.space_id == space_id).all():
            if not _mp_is_default(row):
                continue
            c = _mp_cfg(row)
            c["is_default"] = False
            _mp_set_cfg(row, c)


def _encrypt(plaintext: str) -> tuple[str, str]:
    """Encrypt a plaintext API key. Returns (base64_ciphertext, base64_nonce)."""
    from ..crypto import encrypt_to_base64
    return encrypt_to_base64(plaintext)


# Import registry and litellm_provider to register adapters on module load
from .registry import registry as _reg  # noqa: E402, F401
from .litellm_provider import LiteLLMProvider as _LP  # noqa: E402, F401