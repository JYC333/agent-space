"""Internal client for the control-plane TS runtime host."""

from __future__ import annotations

from typing import Any

import httpx

from ..config import settings


SECRET_RESPONSE_KEYS = {
    "api_key",
    "secret_ref",
    "encrypted_key",
    "credential_secret_ref",
}


class RuntimeHostClientError(Exception):
    """Raised when an internal runtime-host call fails before adapter mapping."""


def _internal_base_url() -> str:
    base_url = (settings.control_plane_internal_url or "").strip().rstrip("/")
    if not base_url:
        raise RuntimeHostClientError(
            "CONTROL_PLANE_INTERNAL_URL is required for the TS runtime host."
        )
    return base_url


def _internal_token() -> str:
    token = (settings.control_plane_internal_token or "").strip()
    if not token:
        raise RuntimeHostClientError(
            "CONTROL_PLANE_INTERNAL_TOKEN is required for the TS runtime host."
        )
    return token


def _reject_secret_response(value: Any) -> None:
    if isinstance(value, dict):
        leaked = SECRET_RESPONSE_KEYS.intersection(value.keys())
        if leaked:
            raise RuntimeHostClientError(
                f"Control-plane runtime host returned secret fields: {sorted(leaked)}"
            )
        for child in value.values():
            _reject_secret_response(child)
    elif isinstance(value, list):
        for child in value:
            _reject_secret_response(child)


def execute_runtime_host_via_control_plane(payload: dict[str, Any]) -> dict[str, Any]:
    url = f"{_internal_base_url()}/internal/runtime-host/execute"
    headers = {
        "content-type": "application/json",
        "x-agent-space-internal-token": _internal_token(),
    }
    try:
        with httpx.Client(
            timeout=settings.control_plane_internal_timeout_seconds
        ) as client:
            response = client.post(url, headers=headers, json=payload)
    except httpx.HTTPError as exc:
        raise RuntimeHostClientError(
            f"Control-plane runtime host call failed: {exc.__class__.__name__}"
        ) from exc

    if response.status_code >= 400:
        try:
            detail = response.json().get("detail")
        except Exception:
            detail = response.text
        raise RuntimeHostClientError(str(detail or f"HTTP {response.status_code}"))

    try:
        value = response.json()
    except ValueError as exc:
        raise RuntimeHostClientError(
            "Control-plane runtime host returned invalid JSON"
        ) from exc
    if not isinstance(value, dict):
        raise RuntimeHostClientError(
            "Control-plane runtime host returned an invalid response shape"
        )
    _reject_secret_response(value)
    return value
