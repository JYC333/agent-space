"""Authority guard for retired Python public session commands.

The TypeScript control plane owns the public session commands — the read model
(list/get sessions, list messages) **and** session create + message append —
serving them from its own DB. The Python HTTP handlers for those commands must
therefore stop being a second authority.

This guard is applied at the HTTP route layer only. Internal in-process callers
(e.g. the chat turn using ``SessionService``/``SessionWritePort`` to create the
session and append messages) are unaffected — they are part of the chat-turn
orchestration (a separate, still-Python-owned slice), not the public session
command surface this slice moved. The ``reflect`` route is likewise not guarded;
it stays Python-owned.
"""

from __future__ import annotations

from fastapi import HTTPException


def sessions_commands_owned_by_ts() -> bool:
    return True


def reject_python_session_command_when_ts_authority(command: str) -> None:
    raise HTTPException(
        status_code=410,
        detail=(
            f"Python no longer owns sessions.{command}; this command is served by "
            "the TypeScript control plane."
        ),
    )
