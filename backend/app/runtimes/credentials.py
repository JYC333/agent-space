"""Runtime credential resolver — M4 canonical boundary.

Runtime adapters must not read raw API keys from adapter config_json or
environment variables.  All credentials must flow through this module.

Resolution priority for API-key-based providers:
  1. run_model_provider_id → ModelProvider.credential_id → Credential.secret_ref
  2. RuntimeAdapter.provider_id → ModelProvider.credential_id → Credential.secret_ref
  3. AgentVersion.model_provider_id → ModelProvider.credential_id → Credential.secret_ref
  4. RuntimeAdapter.credential_id → Credential.secret_ref
  5. None of the above → empty dict (adapter must handle) or raises when required

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

from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy.orm import Session

from ..models import AgentVersion, RuntimeAdapter
from ..providers.credentials import (
    CredentialResolutionError,
    resolve_credential_api_key,
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
    runtime_adapter_row: Optional[RuntimeAdapter],
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
            adapter_type=getattr(runtime_adapter_row, "adapter_type", None),
            context="run.model_provider_id",
        )

    # 1. RuntimeAdapter.provider_id → ModelProvider encrypted key
    if runtime_adapter_row is not None and runtime_adapter_row.provider_id:
        return resolve_provider_credentials(
            db,
            provider_id=runtime_adapter_row.provider_id,
            adapter_type=getattr(runtime_adapter_row, "adapter_type", None),
            context="runtime_adapter.provider_id",
        )

    # 2. AgentVersion.model_provider_id → ModelProvider encrypted key
    if version is not None and version.model_provider_id:
        return resolve_provider_credentials(
            db,
            provider_id=version.model_provider_id,
            adapter_type=getattr(runtime_adapter_row, "adapter_type", None),
            context="agent_version.model_provider_id",
        )

    # 3. RuntimeAdapter.credential_id → Credential.secret_ref
    if runtime_adapter_row is not None and runtime_adapter_row.credential_id:
        api_key = resolve_credential_api_key(
            db,
            credential_id=runtime_adapter_row.credential_id,
            adapter_type=getattr(runtime_adapter_row, "adapter_type", None),
            context="runtime_adapter.credential_id",
        )
        return {"api_key": api_key}

    # 4. No provider or credential configured — return empty (adapter must handle)
    return {}


def resolve_effective_model_provider_id(
    *,
    runtime_adapter_row: Optional[RuntimeAdapter],
    version: Optional[AgentVersion] = None,
    run_model_provider_id: Optional[str] = None,
) -> Optional[str]:
    """Return the effective ModelProvider id for a run.

    Mirrors the *provider-based* steps of :func:`resolve_runtime_credentials`
    so the provider an adapter is told to use (``ctx.model_provider_id``) is the
    same provider whose key was resolved for it:

      1. ``run_model_provider_id``
      2. ``RuntimeAdapter.provider_id``
      3. ``AgentVersion.model_provider_id``

    Step 4 of credential resolution (``RuntimeAdapter.credential_id``) yields a
    bare ``Credential`` with no associated ``ModelProvider``, so it maps to
    ``None`` here. Adapters that require a provider (e.g. ``model_api``) must
    fail when this returns ``None`` even though a key may still be resolvable —
    a raw credential carries no vendor/endpoint, so the provider is genuinely
    unknown. This keeps the policy subject (``runs.policy_inputs``), the
    resolved credential, and the adapter's provider selection in agreement.
    """
    if run_model_provider_id:
        return run_model_provider_id
    if runtime_adapter_row is not None and runtime_adapter_row.provider_id:
        return runtime_adapter_row.provider_id
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
