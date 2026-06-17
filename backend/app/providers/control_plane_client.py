"""Internal client for provider and credential operations owned by control-plane."""

from __future__ import annotations

from typing import Any

import httpx

from ..config import settings


class ControlPlaneProviderError(Exception):
    """Raised when an internal provider/credential call to control-plane fails."""


def _internal_base_url() -> str:
    base_url = (settings.control_plane_internal_url or "").strip().rstrip("/")
    if not base_url:
        raise ControlPlaneProviderError(
            "CONTROL_PLANE_INTERNAL_URL is required when provider credentials are owned by control-plane."
        )
    return base_url


def _internal_token() -> str:
    token = (settings.control_plane_internal_token or "").strip()
    if not token:
        raise ControlPlaneProviderError(
            "CONTROL_PLANE_INTERNAL_TOKEN is required when provider credentials are owned by control-plane."
        )
    return token


def _post_internal(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    url = f"{_internal_base_url()}{path}"
    headers = {
        "content-type": "application/json",
        "x-agent-space-internal-token": _internal_token(),
    }
    try:
        with httpx.Client(timeout=settings.control_plane_internal_timeout_seconds) as client:
            response = client.post(url, headers=headers, json=payload)
    except httpx.HTTPError as exc:
        raise ControlPlaneProviderError(
            f"Control-plane provider call failed: {exc.__class__.__name__}"
        ) from exc

    if response.status_code >= 400:
        detail: Any
        try:
            detail = response.json().get("detail")
        except Exception:
            detail = response.text
        message = str(detail or f"HTTP {response.status_code}")
        raise ControlPlaneProviderError(message)

    try:
        value = response.json()
    except ValueError as exc:
        raise ControlPlaneProviderError("Control-plane returned invalid JSON") from exc
    if not isinstance(value, dict):
        raise ControlPlaneProviderError("Control-plane returned an invalid response shape")
    return value


def complete_text_via_control_plane(
    *,
    space_id: str,
    provider_id: str,
    model: str | None,
    system: str,
    user: str,
    max_tokens: int,
    task: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "space_id": space_id,
        "provider_id": provider_id,
        "model": model,
        "system": system,
        "user": user,
        "max_tokens": max_tokens,
        "task": task,
    }
    return _post_internal(
        "/internal/providers-credentials/providers/complete-text",
        payload,
    )


def resolve_model_provider_api_key_via_control_plane(
    *,
    space_id: str,
    provider_id: str,
) -> str:
    value = _post_internal(
        "/internal/providers-credentials/credentials/runtime/resolve",
        {
            "kind": "model_provider_api_key",
            "space_id": space_id,
            "provider_id": provider_id,
        },
    )
    api_key = value.get("api_key")
    if not isinstance(api_key, str) or not api_key:
        raise ControlPlaneProviderError("Control-plane returned no API key")
    return api_key


def resolve_credential_api_key_via_control_plane(
    *,
    space_id: str,
    credential_id: str,
) -> str:
    value = _post_internal(
        "/internal/providers-credentials/credentials/runtime/resolve",
        {
            "kind": "credential_api_key",
            "space_id": space_id,
            "credential_id": credential_id,
        },
    )
    api_key = value.get("api_key")
    if not isinstance(api_key, str) or not api_key:
        raise ControlPlaneProviderError("Control-plane returned no API key")
    return api_key


def resolve_cli_profile_via_control_plane(
    *,
    runtime: str,
    profile_id: str | None,
    require_existing: bool,
) -> dict[str, Any] | None:
    try:
        return _post_internal(
            "/internal/providers-credentials/credentials/runtime/resolve",
            {
                "kind": "cli_profile",
                "runtime": runtime,
                "profile_id": profile_id,
                "require_existing": require_existing,
            },
        )
    except ControlPlaneProviderError as exc:
        if "Credential profile not found" in str(exc):
            return None
        raise


def grant_cli_credential_via_control_plane(
    *,
    run_id: str,
    runtime: str,
    risk_level: str,
    executor_mode: str,
    profile_id: str | None,
) -> dict[str, Any]:
    return _post_internal(
        "/internal/providers-credentials/credentials/cli/grant",
        {
            "run_id": run_id,
            "runtime": runtime,
            "risk_level": risk_level,
            "executor_mode": "docker" if executor_mode == "docker" else "worktree",
            "profile_id": profile_id,
        },
    )


def audit_cli_credential_via_control_plane(payload: dict[str, Any]) -> dict[str, Any]:
    return _post_internal(
        "/internal/providers-credentials/credentials/cli/audit",
        payload,
    )
