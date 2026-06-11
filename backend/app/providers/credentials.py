"""Provider-owned API-key credential resolution.

Providers own model API credentials. Runtime adapters may receive already
resolved credentials from run execution, but provider invocation and provider
services must not import the runtime credential module to decrypt provider keys.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from ..models import Credential, ModelProvider

log = logging.getLogger(__name__)


class CredentialResolutionError(Exception):
    """Raised when provider API credentials cannot be resolved.

    The message is always sanitized and must never include raw secret values.
    ``adapter_type`` is kept for callers that surface runtime-scoped errors.
    """

    def __init__(self, message: str, *, adapter_type: str | None = None):
        super().__init__(message)
        self.adapter_type = adapter_type


def resolve_provider_credentials(
    db: Session,
    *,
    provider_id: str,
    adapter_type: str | None = None,
    context: str = "direct",
) -> dict[str, Any]:
    """Fetch and decrypt API-key material for a ``ModelProvider`` row."""

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
    if not provider.credential_id:
        raise CredentialResolutionError(
            f"ModelProvider '{provider_id}' has no credential configured (via {context}). "
            "Configure the provider API key through the provider management interface.",
            adapter_type=adapter_type,
        )

    api_key = resolve_credential_api_key(
        db,
        credential_id=provider.credential_id,
        adapter_type=adapter_type,
        context=f"{context} -> model_provider.credential_id",
    )
    return {"api_key": api_key}


def resolve_provider_api_key(
    db: Session,
    provider_id: str,
    *,
    adapter_type: str | None = None,
    context: str = "direct",
) -> str:
    """Decrypt and return the API key for a ``ModelProvider`` row."""

    result = resolve_provider_credentials(
        db,
        provider_id=provider_id,
        adapter_type=adapter_type,
        context=context,
    )
    api_key = result.get("api_key")
    if not api_key:
        raise CredentialResolutionError(
            f"ModelProvider '{provider_id}' resolved but returned no api_key",
            adapter_type=adapter_type,
        )
    return api_key


def resolve_credential_api_key(
    db: Session,
    *,
    credential_id: str,
    adapter_type: str | None = None,
    context: str = "unknown",
) -> str:
    """Resolve API-key material from ``Credential.secret_ref``."""

    cred = db.query(Credential).filter(Credential.id == credential_id).first()
    if cred is None:
        raise CredentialResolutionError(
            f"Credential '{credential_id}' not found (referenced via {context})",
            adapter_type=adapter_type,
        )

    from ..secrets.secret_ref import (
        SecretRefResolutionError,
        resolve_api_key_from_secret_ref,
    )

    try:
        api_key = resolve_api_key_from_secret_ref(cred.secret_ref)
    except SecretRefResolutionError as exc:
        raise CredentialResolutionError(
            f"Credential '{credential_id}' could not be resolved (via {context}): {exc}",
            adapter_type=adapter_type,
        ) from exc

    if not api_key:
        raise CredentialResolutionError(
            f"Credential '{credential_id}' resolved to an empty API key (via {context})",
            adapter_type=adapter_type,
        )

    log.debug(
        "resolved api_key from Credential %s via %s (adapter_type=%s)",
        credential_id,
        context,
        adapter_type,
    )
    return api_key


__all__ = [
    "CredentialResolutionError",
    "resolve_credential_api_key",
    "resolve_provider_api_key",
    "resolve_provider_credentials",
]
