"""Shared provider invocation — the single provider LLM call primitive.

This is the one place that turns a configured ``ModelProvider`` + a (system, user)
prompt pair into text. Both the memory reflector path and the ``model_api``
runtime adapter call ``complete_text`` so provider calls have one runtime entry
point.

Credential channel isolation: the API key is resolved only by the configured
provider credential owner and is never written to ``os.environ``.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from ..models import ModelProvider
from .control_plane_client import complete_text_via_control_plane

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

    Provider completion is owned by the TypeScript control plane. Python keeps
    this facade for migration-period callers and forwards the request to the
    internal provider completion port.

    ``api_key`` is accepted for migration-period call signature compatibility
    but is not forwarded. The control plane resolves credentials so credential
    release stays single-decider.

    ``task`` names the auxiliary task (e.g. ``"reflector"``). A matching
    ProviderTaskPolicy chain takes precedence in the control plane and
    ``provider_id`` becomes the safety net.

    Raises:
        ProviderUnavailableError: provider row is missing locally
        ControlPlaneProviderError: internal control-plane call failed
    """
    _ = api_key
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


def _provider_space_id(db: Session, provider_id: str) -> str:
    row = db.query(ModelProvider.space_id).filter(ModelProvider.id == provider_id).first()
    if row is None:
        raise ProviderUnavailableError(f"ModelProvider '{provider_id}' not found.")
    return str(row[0])

