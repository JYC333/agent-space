"""Authority guard for the Stage 6 sessions slice.

When ``CONTROL_PLANE_SESSIONS_AUTHORITY=ts`` the control plane owns the public
session commands — the read model (list/get sessions, list messages) **and**
session create + message append — serving them from its own DB. The Python HTTP
handlers for those commands must then stop being a second authority.

This guard is applied at the HTTP route layer only. Internal in-process callers
(e.g. the chat turn using ``SessionService``/``SessionWritePort`` to create the
session and append messages) are unaffected — they are part of the chat-turn
orchestration (a separate, still-Python-owned slice), not the public session
command surface this slice moved. The ``reflect`` route is likewise not guarded;
it stays Python-owned.
"""

from __future__ import annotations

import os

from fastapi import HTTPException


def sessions_commands_owned_by_ts() -> bool:
    return (
        os.getenv("CONTROL_PLANE_SESSIONS_AUTHORITY", "python").strip().lower() == "ts"
    )


def reject_python_session_command_when_ts_authority(command: str) -> None:
    if not sessions_commands_owned_by_ts():
        return
    raise HTTPException(
        status_code=410,
        detail=(
            f"Python no longer owns sessions.{command}; this command is served by "
            "the TypeScript control plane."
        ),
    )
