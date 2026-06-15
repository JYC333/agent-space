"""Runtime credential resolver — M4 canonical boundary.

Runtime adapters must not read raw API keys from adapter config_json or
environment variables.  All credentials must flow through this module.

Resolution priority for API-key-based providers:
  1. run_model_provider_id -> ModelProvider.credential_id -> Credential.secret_ref
  2. AgentVersion.model_provider_id -> ModelProvider.credential_id -> Credential.secret_ref
  3. None of the above -> empty dict (adapter must handle) or raises when required

Env-variable fallback (ANTHROPIC_API_KEY, OPENAI_API_KEY, etc.) is NOT
performed here.  If only an env key is available, configure a ModelProvider
row in the space.

``sanitize_runtime_config`` strips known secret field names from an adapter
config dict so the sanitised copy is safe to log or pass to non-credential
code paths.

"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy.orm import Session

from ..models import AgentVersion
from ..providers.credentials import (
    CredentialResolutionError,
    resolve_provider_api_key as _resolve_provider_api_key,
    resolve_provider_credentials,
)

if TYPE_CHECKING:
    pass

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


def resolve_runtime_credentials(
    db: Session,
    *,
    adapter_type: str | None,
    version: Optional[AgentVersion] = None,
    run_model_provider_id: Optional[str] = None,
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

    # 0. Run-level model provider override (highest priority)
    if run_model_provider_id:
        return resolve_provider_credentials(
            db,
            provider_id=run_model_provider_id,
            adapter_type=adapter_type,
            context="run.model_provider_id",
        )

    # 1. AgentVersion.model_provider_id -> ModelProvider encrypted key
    if version is not None and version.model_provider_id:
        return resolve_provider_credentials(
            db,
            provider_id=version.model_provider_id,
            adapter_type=adapter_type,
            context="agent_version.model_provider_id",
        )

    # 2. No provider configured - return empty (adapter must handle)
    return {}


def resolve_effective_model_provider_id(
    *,
    version: Optional[AgentVersion] = None,
    run_model_provider_id: Optional[str] = None,
) -> Optional[str]:
    """Return the effective ModelProvider id for a run.

    Mirrors the *provider-based* steps of :func:`resolve_runtime_credentials`
    so the provider an adapter is told to use (``ctx.model_provider_id``) is the
    same provider whose key was resolved for it:

      1. ``run_model_provider_id``
      2. ``AgentVersion.model_provider_id``
    This keeps the policy subject (``runs.policy_inputs``), the resolved
    credential, and the adapter's provider selection in agreement.
    """
    if run_model_provider_id:
        return run_model_provider_id
    if version is not None and version.model_provider_id:
        return version.model_provider_id
    return None


def resolve_provider_api_key(db: Session, provider_id: str) -> str:
    """Decrypt and return the API key for a ModelProvider row.

    Raises :class:`CredentialResolutionError` if the provider is not found,
    disabled, or has no stored encrypted key.
    """
    return _resolve_provider_api_key(db, provider_id, context="direct")


def sanitize_runtime_config(config: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of ``config`` with known secret field names removed.

    Safe to log, store in RunStep metadata, or pass to non-credential paths.
    Does not recurse into nested dicts (adapter config is expected to be flat).
    """
    if not config:
        return {}
    return {k: v for k, v in config.items() if k.lower() not in _INLINE_SECRET_FIELDS}
