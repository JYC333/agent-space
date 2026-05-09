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
from ..models import ProviderConfig
from .models import (
    ChatRequest, ChatResponse, StreamChunk, ChatMessage,
    ProviderConfigDB, ProviderConfigOut,
    ConnectionTestResult, ProviderConfigCreate, ProviderConfigUpdate,
)
from .registry import registry

log = logging.getLogger(__name__)


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
        rows = db.query(ProviderConfig).filter(
            ProviderConfig.space_id == space_id,
            ProviderConfig.status != "deleted",
        ).all()
        return [ProviderConfigOut.from_db_row(r) for r in rows]

    def get_config(self, db: Session, config_id: str, space_id: str) -> ProviderConfigDB:
        """Load a config by ID and decrypt the API key. Raises if not found or deleted."""
        row = db.query(ProviderConfig).filter(
            ProviderConfig.id == config_id,
            ProviderConfig.space_id == space_id,
            ProviderConfig.status != "deleted",
        ).first()
        if not row:
            raise ValueError(f"Provider config '{config_id}' not found")

        return ProviderConfigDB(
            id=row.id,
            space_id=row.space_id,
            name=row.name,
            provider=row.provider,
            api_key=decrypt_from_base64(row.encrypted_key, row.key_nonce),
            models=row.models,
            api_base=row.api_base,
            is_default=row.is_default,
            status=row.status,
        )

    def create_config(
        self, db: Session, space_id: str, data: ProviderConfigCreate
    ) -> ProviderConfigOut:
        """Create a new provider config with encrypted API key."""
        if data.is_default:
            self._clear_default(db, space_id)

        encrypted_key, key_nonce = _encrypt(data.api_key)

        config = ProviderConfig(
            id=str(ULID()),
            space_id=space_id,
            name=data.name,
            provider=data.provider,
            encrypted_key=encrypted_key,
            key_nonce=key_nonce,
            models=data.models,
            api_base=data.api_base,
            is_default=data.is_default,
            status="active",
        )
        db.add(config)
        db.commit()
        db.refresh(config)
        return ProviderConfigOut.from_db_row(config)

    def update_config(
        self, db: Session, config_id: str, space_id: str, data: ProviderConfigUpdate
    ) -> ProviderConfigOut:
        """Update a provider config (optionally update the API key)."""
        row = db.query(ProviderConfig).filter(
            ProviderConfig.id == config_id,
            ProviderConfig.space_id == space_id,
        ).first()
        if not row:
            raise ValueError(f"Provider config '{config_id}' not found")

        if data.is_default and not row.is_default:
            self._clear_default(db, space_id)

        if data.name is not None:
            row.name = data.name
        if data.api_key is not None:
            encrypted_key, key_nonce = _encrypt(data.api_key)
            row.encrypted_key = encrypted_key
            row.key_nonce = key_nonce
        if data.models is not None:
            row.models = data.models
        if data.api_base is not None:
            row.api_base = data.api_base
        if data.is_default is not None:
            row.is_default = data.is_default
        if data.status is not None:
            row.status = data.status

        db.commit()
        db.refresh(row)
        return ProviderConfigOut.from_db_row(row)

    def delete_config(self, db: Session, config_id: str, space_id: str) -> None:
        """Soft-delete a provider config."""
        row = db.query(ProviderConfig).filter(
            ProviderConfig.id == config_id,
            ProviderConfig.space_id == space_id,
        ).first()
        if not row:
            raise ValueError(f"Provider config '{config_id}' not found")
        row.status = "deleted"
        db.commit()

    def resolve_default_config(self, db: Session, space_id: str) -> ProviderConfigDB:
        """Find the default active provider config for a space. Raises if none."""
        row = db.query(ProviderConfig).filter(
            ProviderConfig.space_id == space_id,
            ProviderConfig.is_default == True,
            ProviderConfig.status == "active",
        ).first()
        if not row:
            raise ValueError("No default provider configured")
        return ProviderConfigDB(
            id=row.id,
            space_id=row.space_id,
            name=row.name,
            provider=row.provider,
            api_key=decrypt_from_base64(row.encrypted_key, row.key_nonce),
            models=row.models,
            api_base=row.api_base,
            is_default=row.is_default,
            status=row.status,
        )

    # -------------------------------------------------------------------------
    # Chat / Completion
    # -------------------------------------------------------------------------

    async def chat(self, request: ChatRequest, space_id: str) -> ChatResponse:
        """
        Send a chat request to a provider.

        Resolves provider from request.provider_id or falls back to default.
        Uses the registered adapter (default: LiteLLMProvider) to make the call.
        """
        from ..db import get_db

        # Get DB session for this request
        db_gen = get_db()
        db = next(db_gen)
        try:
            if request.provider_id:
                config = self.get_config(db, request.provider_id, space_id)
            else:
                config = self.resolve_default_config(db, space_id)

            adapter = registry.get(config.provider)
            if not adapter:
                # Fall back to litellm for unknown providers
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

        finally:
            try:
                next(db_gen, None)
            except StopIteration:
                pass

    async def chat_stream(
        self, request: ChatRequest, space_id: str
    ) -> AsyncIterator[StreamChunk]:
        """Streaming version of chat()."""
        from ..db import get_db

        db_gen = get_db()
        db = next(db_gen)
        try:
            if request.provider_id:
                config = self.get_config(db, request.provider_id, space_id)
            else:
                config = self.resolve_default_config(db, space_id)

            adapter = registry.get(config.provider) or registry.get("litellm")

            log.info("stream: provider=%s model=%s space=%s", config.provider, request.model, space_id)

            async for chunk in adapter.stream(config.api_key, config.api_base, request):
                yield chunk

        finally:
            try:
                next(db_gen, None)
            except StopIteration:
                pass

    async def test_connection(
        self, config_id: str, space_id: str
    ) -> ConnectionTestResult:
        """Test a provider config by making a minimal chat completion."""
        from ..db import get_db

        db_gen = get_db()
        db = next(db_gen)
        try:
            config = self.get_config(db, config_id, space_id)

            adapter = registry.get(config.provider) or registry.get("litellm")
            model_name = config.models[0] if config.models else None

            if not model_name:
                return ConnectionTestResult(success=False, message="No models configured")

            # Prepend provider prefix if model doesn't already have one
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
        finally:
            try:
                next(db_gen, None)
            except StopIteration:
                pass

    # -------------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------------

    def _clear_default(self, db: Session, space_id: str) -> None:
        """Clear is_default on all configs in a space."""
        for row in db.query(ProviderConfig).filter(
            ProviderConfig.space_id == space_id,
            ProviderConfig.is_default == True,
        ):
            row.is_default = False


def _encrypt(plaintext: str) -> tuple[str, str]:
    """Encrypt a plaintext API key. Returns (base64_ciphertext, base64_nonce)."""
    from ..crypto import encrypt_to_base64
    return encrypt_to_base64(plaintext)


# Import registry and litellm_provider to register adapters on module load
from .registry import registry as _reg  # noqa: E402, F401
from .litellm_provider import LiteLLMProvider as _LP  # noqa: E402, F401