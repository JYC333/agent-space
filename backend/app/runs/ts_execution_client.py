"""Internal client for the fixed TS-owned run execution authority.

Python code that still creates queued runs must not call the retired
``RunExecutionService`` path. It asks the TypeScript control plane to execute
the queued run through the service-authenticated internal port instead, so
exactly one implementation owns ``runs.execute``.
"""

from __future__ import annotations

from typing import Any

import httpx

from ..config import settings


class TsRunExecutionError(Exception):
    """Raised when the internal TS run execution call fails before a result."""


def _internal_base_url() -> str:
    base_url = (settings.control_plane_internal_url or "").strip().rstrip("/")
    if not base_url:
        raise TsRunExecutionError(
            "CONTROL_PLANE_INTERNAL_URL is required to execute runs through the "
            "TS control plane."
        )
    return base_url


def _internal_token() -> str:
    token = (settings.control_plane_internal_token or "").strip()
    if not token:
        raise TsRunExecutionError(
            "CONTROL_PLANE_INTERNAL_TOKEN is required to execute runs through "
            "the TS control plane."
        )
    return token


def execute_run_via_control_plane(
    *,
    run_id: str,
    space_id: str,
    worker_id: str = "python-internal",
) -> dict[str, Any]:
    """Execute a queued run via the TS runs authority; returns its job result.

    The response is the TS ``RunJobResult`` shape: ``run_id``, ``status``, and
    optional ``error_code`` / ``error`` / ``skip_reason`` fields. Terminal run
    state, events, and output live on the Run row — re-read it after this call.
    """
    url = f"{_internal_base_url()}/internal/runs/execute"
    headers = {
        "content-type": "application/json",
        "x-agent-space-internal-token": _internal_token(),
    }
    payload = {"run_id": run_id, "space_id": space_id, "worker_id": worker_id}
    try:
        with httpx.Client(
            timeout=settings.control_plane_internal_timeout_seconds
        ) as client:
            response = client.post(url, headers=headers, json=payload)
    except httpx.HTTPError as exc:
        raise TsRunExecutionError(
            f"Control-plane run execution call failed: {exc.__class__.__name__}"
        ) from exc

    if response.status_code >= 400:
        try:
            detail = response.json().get("detail")
        except Exception:
            detail = response.text
        raise TsRunExecutionError(str(detail or f"HTTP {response.status_code}"))

    try:
        value = response.json()
    except ValueError as exc:
        raise TsRunExecutionError(
            "Control-plane run execution returned invalid JSON"
        ) from exc
    if not isinstance(value, dict):
        raise TsRunExecutionError(
            "Control-plane run execution returned a non-object response"
        )
    return value
