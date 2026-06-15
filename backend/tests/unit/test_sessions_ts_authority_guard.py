"""Stage 6 S7: the Python session command routes fail closed once TS owns them.

The flip moves the whole public session command surface — reads (list/get
sessions, list messages) and writes (create session, add message). Session
``reflect`` and in-process service callers (the chat turn) are not guarded.
These tests assert the guard helper's behavior in both authority modes.
"""

import pytest
from fastapi import HTTPException

from app.sessions.authority import (
    reject_python_session_command_when_ts_authority,
    sessions_commands_owned_by_ts,
)

ALL_COMMANDS = ["list", "get", "messages", "create", "add_message"]


def test_sessions_authority_defaults_to_python(monkeypatch):
    monkeypatch.delenv("CONTROL_PLANE_SESSIONS_AUTHORITY", raising=False)

    assert sessions_commands_owned_by_ts() is False
    # No-op when Python still owns the commands.
    for command in ALL_COMMANDS:
        reject_python_session_command_when_ts_authority(command)


def test_sessions_authority_is_case_insensitive(monkeypatch):
    monkeypatch.setenv("CONTROL_PLANE_SESSIONS_AUTHORITY", "TS")
    assert sessions_commands_owned_by_ts() is True


@pytest.mark.parametrize("command", ALL_COMMANDS)
def test_python_session_command_fails_closed_when_ts_owned(monkeypatch, command):
    monkeypatch.setenv("CONTROL_PLANE_SESSIONS_AUTHORITY", "ts")

    with pytest.raises(HTTPException) as exc:
        reject_python_session_command_when_ts_authority(command)

    assert exc.value.status_code == 410
    assert "TypeScript control plane" in str(exc.value.detail)
    assert command in str(exc.value.detail)
