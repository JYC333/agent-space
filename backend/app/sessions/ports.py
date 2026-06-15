"""Interface seams for session-owned derived context.

These ports are migration preparation only. The Python sessions module remains
the authority today, but cross-context callers should depend on this narrow
surface instead of importing session internals such as ``sessions.condenser``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from sqlalchemy.orm import Session as DBSession

    from ..models import Message, Session
    from ..schemas import MessageCreate, SessionCreate


@dataclass(frozen=True)
class SessionSummaryForContext:
    """Secret-free session summary DTO used by context assembly."""

    id: str
    session_id: str
    version: int
    summary_text: str
    condenser_version: str


@runtime_checkable
class SessionSummaryPort(Protocol):
    """Read-only session-summary seam consumed by memory/context code."""

    def get_latest_for_context(
        self,
        session_id: str,
        space_id: str,
    ) -> SessionSummaryForContext | None:
        ...


def get_session_summary_port(db: "DBSession") -> SessionSummaryPort:
    """Resolve the active session-summary authority.

    Python remains authoritative unless Stage 6 has moved the sessions-derived
    summary read to the control plane. Keeping the resolver here gives memory
    code one stable seam while the authority flips one slice at a time.
    """

    from .control_plane_client import (
        ControlPlaneSessionSummaryPort,
        session_summary_owned_by_control_plane,
    )
    from .condenser import SessionCondenser

    if session_summary_owned_by_control_plane():
        return ControlPlaneSessionSummaryPort()
    return SessionCondenser(db)


@runtime_checkable
class SessionWritePort(Protocol):
    """Session get-or-create + message-append seam used by cross-context callers.

    Mirrors the subset of :class:`app.sessions.service.SessionService` the chat
    turn (``agents.chat_service``) depends on. Sessions remains the authority
    until Stage 6 flips the sessions slice; depending on this port instead of
    importing ``sessions.service`` directly gives the migration one place to
    route session writes to the TS ``sessions`` module later.
    """

    def get_session(
        self,
        session_id: str,
        *,
        space_id: str | None = None,
        user_id: str | None = None,
    ) -> "Session | None":
        ...

    def create_session(self, data: "SessionCreate") -> "Session":
        ...

    def add_message(
        self,
        session_id: str,
        data: "MessageCreate",
        space_id: str,
        user_id: str,
    ) -> "Message | None":
        ...


def get_session_write_port(db: "DBSession") -> SessionWritePort:
    """Resolve the active session write authority.

    Same rationale as :func:`get_session_summary_port`, for the session
    get-or-create + message-append surface.
    """

    from .service import SessionService

    return SessionService(db)


__all__ = [
    "SessionSummaryForContext",
    "SessionSummaryPort",
    "SessionWritePort",
    "get_session_summary_port",
    "get_session_write_port",
]
