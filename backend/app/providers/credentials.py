"""Provider-owned API-key credential resolution through the TS control plane."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from ..models import Credential, ModelProvider
from .control_plane_client import (
    ControlPlaneProviderError,
    resolve_credential_api_key_via_control_plane,
    resolve_model_provider_api_key_via_control_plane,
)


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
    """Resolve API-key material for a ``ModelProvider`` through control-plane."""

    provider = db.query(ModelProvider.space_id).filter(ModelProvider.id == provider_id).first()
    if provider is None:
        raise CredentialResolutionError(
            f"ModelProvider '{provider_id}' not found (referenced via {context})",
            adapter_type=adapter_type,
        )
    try:
        return {
            "api_key": resolve_model_provider_api_key_via_control_plane(
                space_id=str(provider[0]),
                provider_id=provider_id,
            )
        }
    except ControlPlaneProviderError as exc:
        raise CredentialResolutionError(str(exc), adapter_type=adapter_type) from exc


def resolve_provider_api_key(
    db: Session,
    provider_id: str,
    *,
    adapter_type: str | None = None,
    context: str = "direct",
) -> str:
    """Resolve and return the API key for a ``ModelProvider`` row."""

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
    """Resolve API-key material from the control-plane credential store."""

    cred_ref = db.query(Credential.space_id).filter(Credential.id == credential_id).first()
    if cred_ref is None:
        raise CredentialResolutionError(
            f"Credential '{credential_id}' not found (referenced via {context})",
            adapter_type=adapter_type,
        )
    try:
        return resolve_credential_api_key_via_control_plane(
            space_id=str(cred_ref[0]),
            credential_id=credential_id,
        )
    except ControlPlaneProviderError as exc:
        raise CredentialResolutionError(str(exc), adapter_type=adapter_type) from exc


__all__ = [
    "CredentialResolutionError",
    "resolve_credential_api_key",
    "resolve_provider_api_key",
    "resolve_provider_credentials",
]
