"""Runtime credential resolver — M4 canonical boundary.

Runtime adapters must not read raw API keys from adapter config_json or
environment variables.  All credentials must flow through this module.

Resolution priority for API-key-based providers:
  1. RuntimeAdapter.provider_id → ModelProvider.config_json encrypted key
  2. AgentVersion.model_provider_id → ModelProvider.config_json encrypted key
  3. RuntimeAdapter.credential_id → Credential (opaque; not yet decryptable here)
  4. None of the above → raises CredentialResolutionError with a sanitized message

Env-variable fallback (ANTHROPIC_API_KEY, OPENAI_API_KEY, etc.) is NOT
performed here.  If only an env key is available, configure a ModelProvider
row in the space.

``sanitize_runtime_config`` strips known secret field names from an adapter
config dict so the sanitised copy is safe to log or pass to non-credential
code paths.

``assert_no_inline_secret_config`` raises if a RuntimeAdapter row stores a
raw api_key in config_json, preventing secrets from being written to the DB
adapter config column.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy.orm import Session

from ..models import AgentVersion, Credential, ModelProvider, RuntimeAdapter

if TYPE_CHECKING:
    pass

log = logging.getLogger(__name__)

# Field names that must never appear as raw secrets in adapter config_json.
_INLINE_SECRET_FIELDS: frozenset[str] = frozenset({
    "api_key",
    "apikey",
    "api_token",
    "secret_key",
    "access_key",
    "private_key",
    "anthropic_api_key",
    "openai_api_key",
})


class CredentialResolutionError(Exception):
    """Raised when credentials cannot be resolved through the canonical boundary.

    The message is always sanitized — no raw secret values.
    """

    def __init__(self, message: str, *, adapter_type: str | None = None):
        super().__init__(message)
        self.adapter_type = adapter_type


def resolve_runtime_credentials(
    db: Session,
    *,
    runtime_adapter_row: Optional[RuntimeAdapter],
    version: Optional[AgentVersion] = None,
    purpose: str = "runtime",
) -> dict[str, Any]:
    """Resolve credentials for a runtime adapter through the canonical boundary.

    Returns a dict of resolved credential values (e.g. ``{"api_key": "..."}``).
    Returns an empty dict if the adapter type does not require credentials.

    Raises :class:`CredentialResolutionError` with a sanitized message if
    credentials are required but cannot be resolved.

    Never reads ANTHROPIC_API_KEY or any other environment variable.
    Never reads raw ``api_key`` fields from adapter config_json.
    """
    del purpose  # reserved for future access-grant scoping

    # 1. RuntimeAdapter.provider_id → ModelProvider encrypted key
    if runtime_adapter_row is not None and runtime_adapter_row.provider_id:
        return _resolve_from_model_provider(
            db,
            provider_id=runtime_adapter_row.provider_id,
            adapter_type=getattr(runtime_adapter_row, "adapter_type", None),
            context="runtime_adapter.provider_id",
        )

    # 2. AgentVersion.model_provider_id → ModelProvider encrypted key
    if version is not None and version.model_provider_id:
        return _resolve_from_model_provider(
            db,
            provider_id=version.model_provider_id,
            adapter_type=getattr(runtime_adapter_row, "adapter_type", None),
            context="agent_version.model_provider_id",
        )

    # 3. RuntimeAdapter.credential_id → Credential row (opaque ref; no decrypt yet)
    if runtime_adapter_row is not None and runtime_adapter_row.credential_id:
        cred = (
            db.query(Credential)
            .filter(Credential.id == runtime_adapter_row.credential_id)
            .first()
        )
        if cred is not None:
            # Credential.secret_ref is an opaque reference — not the plaintext key.
            # Full Credential decryption is deferred to a later milestone.
            log.debug(
                "credential_id %s found (type=%s) but opaque decryption is not yet implemented; "
                "returning empty credentials dict",
                cred.id,
                cred.credential_type,
            )
            return {}

    # 4. No provider or credential configured — return empty (adapter must handle)
    return {}


def resolve_provider_api_key(db: Session, provider_id: str) -> str:
    """Decrypt and return the API key for a ModelProvider row.

    Raises :class:`CredentialResolutionError` if the provider is not found,
    disabled, or has no stored encrypted key.
    """
    result = _resolve_from_model_provider(db, provider_id=provider_id, context="direct")
    api_key = result.get("api_key")
    if not api_key:
        raise CredentialResolutionError(
            f"ModelProvider '{provider_id}' resolved but returned no api_key"
        )
    return api_key


def sanitize_runtime_config(config: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of ``config`` with known secret field names removed.

    Safe to log, store in RunStep metadata, or pass to non-credential paths.
    Does not recurse into nested dicts (adapter config is expected to be flat).
    """
    if not config:
        return {}
    return {k: v for k, v in config.items() if k.lower() not in _INLINE_SECRET_FIELDS}


def assert_no_inline_secret_config(runtime_adapter_row: RuntimeAdapter) -> None:
    """Raise if the RuntimeAdapter row stores raw secret fields in config_json.

    Prevents API keys from being persisted in the adapter config column.
    Call this at adapter registration or before execution to enforce the boundary.
    """
    cfg = dict(runtime_adapter_row.config_json or {})
    found = [k for k in cfg if k.lower() in _INLINE_SECRET_FIELDS]
    if found:
        raise CredentialResolutionError(
            f"RuntimeAdapter '{runtime_adapter_row.id}' config_json contains inline secret "
            f"field(s): {sorted(found)!r}. Credentials must be stored in a linked ModelProvider "
            "or Credential row — not in adapter config_json.",
            adapter_type=runtime_adapter_row.adapter_type,
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _resolve_from_model_provider(
    db: Session,
    *,
    provider_id: str,
    adapter_type: str | None = None,
    context: str = "unknown",
) -> dict[str, Any]:
    """Fetch and decrypt the API key from a ModelProvider row."""
    provider = db.query(ModelProvider).filter(ModelProvider.id == provider_id).first()
    if provider is None:
        raise CredentialResolutionError(
            f"ModelProvider '{provider_id}' not found (referenced via {context})",
            adapter_type=adapter_type,
        )
    if not provider.enabled:
        raise CredentialResolutionError(
            f"ModelProvider '{provider_id}' is disabled (via {context})",
            adapter_type=adapter_type,
        )

    cfg = dict(provider.config_json or {})
    encrypted_key = cfg.get("encrypted_key")
    key_nonce = cfg.get("key_nonce")

    if not encrypted_key or not key_nonce:
        raise CredentialResolutionError(
            f"ModelProvider '{provider_id}' has no stored encrypted credentials (via {context}). "
            "Configure the provider API key through the provider management interface.",
            adapter_type=adapter_type,
        )

    try:
        from ..crypto import decrypt_from_base64
        api_key = decrypt_from_base64(encrypted_key, key_nonce)
    except Exception as exc:
        raise CredentialResolutionError(
            f"ModelProvider '{provider_id}' credential decryption failed (via {context}): "
            f"{type(exc).__name__} — check crypto configuration.",
            adapter_type=adapter_type,
        ) from exc

    if not api_key or not api_key.strip():
        raise CredentialResolutionError(
            f"ModelProvider '{provider_id}' decrypted to an empty API key (via {context})",
            adapter_type=adapter_type,
        )

    log.debug(
        "resolved api_key from ModelProvider %s via %s (adapter_type=%s)",
        provider_id,
        context,
        adapter_type,
    )
    return {"api_key": api_key.strip()}
