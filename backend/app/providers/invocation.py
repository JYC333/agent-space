"""Shared provider invocation — the single provider LLM call primitive.

This is the one place that turns a configured ``ModelProvider`` + a (system, user)
prompt pair into text. Both the memory reflector path and the ``model_api``
runtime adapter call ``complete_text`` so provider calls have one runtime entry
point.

Credential channel isolation: the API key is resolved only by the configured
provider credential owner and is never written to ``os.environ``.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from ..models import ModelProvider
from .control_plane_client import (
    complete_text_via_control_plane,
    provider_credentials_owned_by_control_plane,
)
from .credentials import resolve_provider_api_key

log = logging.getLogger(__name__)

# Provider types callable through this in-process litellm channel. Mirrors the
# ProviderType literal in providers/models.py.
SUPPORTED_PROVIDER_TYPES = frozenset({
    "openai",
    "anthropic",
    "openrouter",
    "ollama",
    "custom_openai_compatible",
    "other",
})


class ProviderUnavailableError(Exception):
    """Raised when the ModelProvider row is missing or disabled.

    error_code: provider_unavailable
    """

    error_code = "provider_unavailable"


class UnsupportedProviderError(Exception):
    """Raised when provider_type is not callable through this channel.

    error_code: unsupported_provider
    """

    error_code = "unsupported_provider"


@dataclass
class CompletionResult:
    text: str
    model: str
    usage: dict | None = None


def build_litellm_model_name(provider_type: str, model: str) -> str:
    """Build a litellm model string from provider_type + model name.

    litellm uses ``provider/model`` for non-OpenAI providers. An already-qualified
    name (containing ``/``) is returned unchanged. OpenAI and custom OpenAI-compatible
    endpoints pass the bare model name (api_base handles routing).
    """
    if "/" in model:
        return model
    if provider_type == "anthropic":
        return f"anthropic/{model}"
    if provider_type == "openrouter":
        return f"openrouter/{model}"
    if provider_type == "ollama":
        return f"ollama/{model}"
    # openai, custom_openai_compatible, other → OpenAI-compatible client. litellm needs
    # the "openai/" prefix to select the OpenAI handler; api_base (when set) overrides the
    # endpoint. A bare name makes litellm fail with "LLM Provider NOT provided".
    return f"openai/{model}"


def resolve_usable_provider(db: Session, provider_id: str) -> ModelProvider:
    """Load and validate a ModelProvider for in-process invocation.

    Raises:
        ProviderUnavailableError: row missing or disabled
        UnsupportedProviderError: provider_type not callable through this channel
    """
    row: ModelProvider | None = (
        db.query(ModelProvider).filter(ModelProvider.id == provider_id).first()
    )
    if row is None:
        raise ProviderUnavailableError(f"ModelProvider '{provider_id}' not found.")
    if not row.enabled:
        raise ProviderUnavailableError(f"ModelProvider '{provider_id}' is disabled.")
    if row.provider_type not in SUPPORTED_PROVIDER_TYPES:
        raise UnsupportedProviderError(
            f"provider_type='{row.provider_type}' is not supported for in-process invocation. "
            f"Supported types: {', '.join(sorted(SUPPORTED_PROVIDER_TYPES))}."
        )
    return row


def complete_text(
    db: Session,
    *,
    provider_id: str,
    model: str | None,
    system: str,
    user: str,
    max_tokens: int = 2048,
    api_key: str | None = None,
    task: str | None = None,
) -> CompletionResult:
    """Single synchronous (system, user) -> text completion.

    In the default Python-owned mode this resolves the provider locally, builds
    the litellm model name, and makes one ``litellm.completion`` call. When
    provider credentials are owned by control-plane, it forwards the same
    request to the internal provider completion port.

    ``api_key`` may be supplied pre-resolved (e.g. a runtime adapter passing
    ``ctx.resolved_credentials["api_key"]`` that the execution service already
    resolved through the canonical boundary). When omitted, it is resolved here via
    ``resolve_provider_api_key``. Under control-plane authority the key is
    always resolved by the credential owner (a pre-resolved ``api_key`` is not
    forwarded), so credential release stays single-decider.

    ``task`` names the auxiliary task (e.g. ``"reflector"``). Under
    control-plane authority a matching ProviderTaskPolicy chain takes
    precedence and ``provider_id`` becomes the safety net; the Python-owned
    path has no chain support and ignores it.

    Raises:
        ProviderUnavailableError / UnsupportedProviderError: from resolve_usable_provider
        CredentialResolutionError: provider has no decryptable key
        Any litellm exception on network/API failure (caller decides how to handle)
    """
    if provider_credentials_owned_by_control_plane():
        space_id = _provider_space_id(db, provider_id)
        response = complete_text_via_control_plane(
            space_id=space_id,
            provider_id=provider_id,
            model=model,
            system=system,
            user=user,
            max_tokens=max_tokens,
            task=task,
        )
        usage = response.get("usage")
        return CompletionResult(
            text=str(response.get("text") or ""),
            model=str(response.get("model") or model or ""),
            usage=usage if isinstance(usage, dict) else None,
        )

    row = resolve_usable_provider(db, provider_id)
    provider_type = row.provider_type
    if api_key is None:
        api_key = resolve_provider_api_key(db, provider_id)

    resolved_model = model or row.default_model or _default_model_for_type(provider_type)
    litellm_model = build_litellm_model_name(provider_type, resolved_model)

    import litellm  # already a project dependency (litellm>=1.0.0)

    params: dict = {
        "model": litellm_model,
        "api_key": api_key,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_tokens": max_tokens,
    }
    if row.base_url:
        params["api_base"] = row.base_url

    log.debug("complete_text: provider=%s model=%s", provider_type, litellm_model)
    response = litellm.completion(**params)
    text = response.choices[0].message.content or ""
    usage = getattr(response, "usage", None)
    usage_dict = usage.model_dump() if hasattr(usage, "model_dump") else (dict(usage) if usage else None)
    return CompletionResult(text=text, model=resolved_model, usage=usage_dict)


def _provider_space_id(db: Session, provider_id: str) -> str:
    row = db.query(ModelProvider.space_id).filter(ModelProvider.id == provider_id).first()
    if row is None:
        raise ProviderUnavailableError(f"ModelProvider '{provider_id}' not found.")
    return str(row[0])


def _default_model_for_type(provider_type: str) -> str:
    """Minimal fallback model name when no default_model is configured."""
    _DEFAULTS = {
        "openai": "gpt-4o-mini",
        "anthropic": "claude-3-5-sonnet-latest",
        "openrouter": "openai/gpt-4o-mini",
        "ollama": "llama3",
    }
    return _DEFAULTS.get(provider_type, "gpt-4o-mini")
