"""ModelProvider input validation — pure rules, no I/O."""

from __future__ import annotations

from typing import Literal

ProviderType = Literal[
    "openai",
    "anthropic",
    "openrouter",
    "ollama",
    "custom_openai_compatible",
    "other",
]

PROVIDER_TYPES: frozenset[str] = frozenset({
    "openai",
    "anthropic",
    "openrouter",
    "ollama",
    "custom_openai_compatible",
    "other",
})

CLOUD_PROVIDER_TYPES: frozenset[str] = frozenset({"openai", "anthropic", "openrouter"})

BASE_URL_REQUIRED_TYPES: frozenset[str] = frozenset({"ollama", "custom_openai_compatible"})


class ModelProviderValidationError(ValueError):
    pass


def validate_provider_type(provider_type: str) -> None:
    if provider_type not in PROVIDER_TYPES:
        raise ModelProviderValidationError(
            f"Invalid provider_type '{provider_type}'. "
            f"Must be one of: {', '.join(sorted(PROVIDER_TYPES))}"
        )


def validate_create_fields(
    *,
    provider_type: str,
    base_url: str | None,
    api_key: str | None,
) -> None:
    validate_provider_type(provider_type)
    if provider_type in BASE_URL_REQUIRED_TYPES and not (base_url and base_url.strip()):
        raise ModelProviderValidationError(
            f"base_url is required for provider_type '{provider_type}'"
        )
    if provider_type in CLOUD_PROVIDER_TYPES and not (api_key and api_key.strip()):
        raise ModelProviderValidationError(
            f"api_key is required for provider_type '{provider_type}'"
        )


def validate_update_base_url(provider_type: str, base_url: str | None) -> None:
    if provider_type in BASE_URL_REQUIRED_TYPES and base_url is not None and not base_url.strip():
        raise ModelProviderValidationError(
            f"base_url cannot be empty for provider_type '{provider_type}'"
        )
