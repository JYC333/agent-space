"""Minimal provider client for the LLM reflector.

Resolves a configured ModelProvider and makes a single synchronous chat-completion
call (system prompt + user prompt → text).  Only non-Anthropic provider types are
supported; Anthropic is CLI-only per product policy.

Usage::

    from app.memory.provider_client import (
        ReflectorModelProviderMissingError,
        UnsupportedProviderForReflectorError,
        call_reflector_llm,
        resolve_reflector_provider,
    )

    provider_type, base_url, model, api_key = resolve_reflector_provider(db, settings)
    text = call_reflector_llm(provider_type, base_url, model, api_key, system_prompt, user_prompt)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
    from ..config import Settings

log = logging.getLogger(__name__)

# Provider types that route through the OpenAI-compatible chat-completions endpoint
# (via litellm, which is already a project dependency).
_OPENAI_COMPATIBLE_TYPES = frozenset({
    "openai",
    "openrouter",
    "ollama",
    "custom_openai_compatible",
    "other",
})


class ReflectorModelProviderMissingError(Exception):
    """Raised when reflector_mode=llm but no ModelProvider is configured.

    error_code: reflector_model_provider_missing
    """

    error_code = "reflector_model_provider_missing"


class UnsupportedProviderForReflectorError(Exception):
    """Raised when the configured provider_type is not allowed for the reflector.

    Anthropic is CLI-only and must not be called directly from the reflector.
    error_code: unsupported_provider_for_reflector
    """

    error_code = "unsupported_provider_for_reflector"


def resolve_reflector_provider(
    db: "Session",
    settings: "Settings",
) -> tuple[str, str | None, str, str]:
    """Resolve provider config for the LLM reflector.

    Priority:
      1. ``settings.reflector_model_provider_id`` → ModelProvider row → Credential
      2. If no provider ID configured → raise ``ReflectorModelProviderMissingError``

    Returns:
        ``(provider_type, base_url, model, api_key)``

    Raises:
        ReflectorModelProviderMissingError: no provider configured
        UnsupportedProviderForReflectorError: provider_type=anthropic (CLI-only)
        CredentialResolutionError: provider found but credentials cannot be decrypted
    """
    provider_id = settings.reflector_model_provider_id
    if not provider_id:
        raise ReflectorModelProviderMissingError(
            "reflector_mode=llm but REFLECTOR_MODEL_PROVIDER_ID is not configured. "
            "Create a ModelProvider row (OpenAI-compatible) and set "
            "REFLECTOR_MODEL_PROVIDER_ID to its ID."
        )

    from ..models import ModelProvider
    from ..runtimes.credentials import resolve_provider_api_key, CredentialResolutionError

    row: ModelProvider | None = (
        db.query(ModelProvider).filter(ModelProvider.id == provider_id).first()
    )
    if row is None:
        raise ReflectorModelProviderMissingError(
            f"ModelProvider '{provider_id}' (REFLECTOR_MODEL_PROVIDER_ID) not found in database."
        )
    if not row.enabled:
        raise ReflectorModelProviderMissingError(
            f"ModelProvider '{provider_id}' (REFLECTOR_MODEL_PROVIDER_ID) is disabled."
        )

    provider_type: str = row.provider_type
    _guard_provider_type(provider_type)

    api_key: str = resolve_provider_api_key(db, provider_id)

    # Model resolution priority: settings override → provider default_model
    model: str = (
        settings.reflector_model
        or row.default_model
        or _default_model_for_type(provider_type)
    )

    log.debug(
        "reflector provider resolved: type=%s model=%s provider_id=%s",
        provider_type,
        model,
        provider_id,
    )
    return provider_type, row.base_url, model, api_key


def call_reflector_llm(
    provider_type: str,
    base_url: str | None,
    model: str,
    api_key: str,
    system_prompt: str,
    user_prompt: str,
) -> str:
    """Make a single synchronous chat-completion call via litellm.

    Returns the text content of the first choice.

    Raises:
        UnsupportedProviderForReflectorError: if provider_type is anthropic or unknown
        Any litellm exception on network/API failure (caller decides how to handle)
    """
    _guard_provider_type(provider_type)

    import litellm  # already a project dependency (litellm>=1.0.0)

    # LiteLLM model name format: "provider/model" or just "model" for openai.
    # For openai-compatible types we pass api_base when set.
    litellm_model = _build_litellm_model_name(provider_type, model)

    params: dict = {
        "model": litellm_model,
        "api_key": api_key,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": 2048,
    }
    if base_url:
        params["api_base"] = base_url

    log.debug("reflector llm call: model=%s", litellm_model)
    response = litellm.completion(**params)
    return response.choices[0].message.content or ""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _guard_provider_type(provider_type: str) -> None:
    """Raise if provider_type is not allowed for direct reflector calls."""
    if provider_type == "anthropic":
        raise UnsupportedProviderForReflectorError(
            "provider_type='anthropic' is not supported for the reflector. "
            "Anthropic/Claude execution is CLI-only in this deployment. "
            "Configure an OpenAI-compatible provider (openai, openrouter, ollama, "
            "custom_openai_compatible) as REFLECTOR_MODEL_PROVIDER_ID."
        )
    if provider_type not in _OPENAI_COMPATIBLE_TYPES:
        raise UnsupportedProviderForReflectorError(
            f"provider_type='{provider_type}' is not supported for the reflector. "
            f"Supported types: {', '.join(sorted(_OPENAI_COMPATIBLE_TYPES))}."
        )


def _build_litellm_model_name(provider_type: str, model: str) -> str:
    """Build a litellm model string from provider_type and model name.

    litellm uses "provider/model" for non-OpenAI providers.
    For openai and custom_openai_compatible we pass the model name as-is
    (api_base handles routing for custom endpoints).
    """
    if "/" in model:
        # Already qualified (e.g. "openai/gpt-4o")
        return model
    if provider_type == "openai":
        return model
    if provider_type == "openrouter":
        return f"openrouter/{model}"
    if provider_type == "ollama":
        return f"ollama/{model}"
    # custom_openai_compatible, other — pass model name directly;
    # api_base param tells litellm where to send the request
    return model


def _default_model_for_type(provider_type: str) -> str:
    """Minimal fallback model name when no default_model is configured."""
    _DEFAULTS = {
        "openai": "gpt-4o-mini",
        "openrouter": "openai/gpt-4o-mini",
        "ollama": "llama3",
    }
    return _DEFAULTS.get(provider_type, "gpt-4o-mini")
