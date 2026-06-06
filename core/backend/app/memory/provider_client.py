"""Reflector provider configuration.

Resolves *which* ModelProvider the LLM reflector should use (a deployment-level
setting). The actual key decryption and litellm call live in the shared
``providers.invocation`` primitive — see ``complete_text``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..config import Settings

log = logging.getLogger(__name__)


class ReflectorModelProviderMissingError(Exception):
    """Raised when reflector_mode=llm but no ModelProvider is configured.

    error_code: reflector_model_provider_missing
    """

    error_code = "reflector_model_provider_missing"


def resolve_reflector_provider_id(settings: "Settings") -> tuple[str, str | None]:
    """Resolve the reflector's provider id and optional model override from settings.

    Returns:
        ``(provider_id, model_override)`` — ``model_override`` may be ``None``.

    Raises:
        ReflectorModelProviderMissingError: REFLECTOR_MODEL_PROVIDER_ID is not set.

    Provider availability (row exists / enabled / supported type) and key decryption
    are validated downstream by ``providers.invocation.complete_text``.
    """
    provider_id = settings.reflector_model_provider_id
    if not provider_id:
        raise ReflectorModelProviderMissingError(
            "reflector_mode=llm but REFLECTOR_MODEL_PROVIDER_ID is not configured. "
            "Create a ModelProvider row and set REFLECTOR_MODEL_PROVIDER_ID to its ID."
        )
    return provider_id, settings.reflector_model
