"""Internal client for TS-owned session summary context reads."""

from __future__ import annotations

from typing import Any

import httpx

from ..config import settings
from .authority import sessions_commands_owned_by_ts
from .ports import SessionSummaryForContext


class ControlPlaneSessionSummaryError(Exception):
    """Raised when the TS session-summary authority is unavailable or invalid."""


def session_summary_owned_by_control_plane() -> bool:
    return sessions_commands_owned_by_ts()


def _internal_base_url() -> str:
    base_url = (settings.control_plane_internal_url or "").strip().rstrip("/")
    if not base_url:
        raise ControlPlaneSessionSummaryError(
            "CONTROL_PLANE_INTERNAL_URL is required when session summary is owned by control-plane."
        )
    return base_url


def _internal_token() -> str:
    token = (settings.control_plane_internal_token or "").strip()
    if not token:
        raise ControlPlaneSessionSummaryError(
            "CONTROL_PLANE_INTERNAL_TOKEN is required when session summary is owned by control-plane."
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
        raise ControlPlaneSessionSummaryError(
            f"Control-plane session summary call failed: {exc.__class__.__name__}"
        ) from exc

    if response.status_code >= 400:
        try:
            detail = response.json().get("detail")
        except Exception:
            detail = response.text
        raise ControlPlaneSessionSummaryError(str(detail or f"HTTP {response.status_code}"))

    try:
        value = response.json()
    except ValueError as exc:
        raise ControlPlaneSessionSummaryError(
            "Control-plane session summary returned invalid JSON"
        ) from exc
    if not isinstance(value, dict):
        raise ControlPlaneSessionSummaryError(
            "Control-plane session summary returned an invalid response"
        )
    return value


class ControlPlaneSessionSummaryPort:
    """SessionSummaryPort backed by the TS control-plane sessions module."""

    def get_latest_for_context(
        self,
        session_id: str,
        space_id: str,
    ) -> SessionSummaryForContext | None:
        value = _post_internal(
            "/internal/sessions/session-summary/get-latest",
            {"session_id": session_id, "space_id": space_id},
        )
        summary = value.get("summary")
        if summary is None:
            return None
        if not isinstance(summary, dict):
            raise ControlPlaneSessionSummaryError(
                "Control-plane session summary response is missing summary"
            )
        summary_id = summary.get("id")
        summary_session_id = summary.get("session_id")
        version = summary.get("version")
        summary_text = summary.get("summary_text")
        condenser_version = summary.get("condenser_version")
        if (
            not isinstance(summary_id, str)
            or not isinstance(summary_session_id, str)
            or not isinstance(version, int)
            or isinstance(version, bool)
            or not isinstance(summary_text, str)
            or not isinstance(condenser_version, str)
        ):
            raise ControlPlaneSessionSummaryError(
                "Control-plane session summary response contains an invalid summary"
            )
        return SessionSummaryForContext(
            id=summary_id,
            session_id=summary_session_id,
            version=version,
            summary_text=summary_text,
            condenser_version=condenser_version,
        )
