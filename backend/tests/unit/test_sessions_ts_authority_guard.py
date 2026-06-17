"""Python public session command routes are retired behind the TS authority."""

import pytest
from fastapi import HTTPException

from app.sessions.authority import (
    reject_python_session_command_when_ts_authority,
    sessions_commands_owned_by_ts,
)

ALL_COMMANDS = ["list", "get", "messages", "create", "add_message"]


def test_sessions_authority_is_fixed_to_ts():
    assert sessions_commands_owned_by_ts() is True


@pytest.mark.parametrize("command", ALL_COMMANDS)
def test_python_session_command_fails_closed(command):
    with pytest.raises(HTTPException) as exc:
        reject_python_session_command_when_ts_authority(command)

    assert exc.value.status_code == 410
    assert "TypeScript control plane" in str(exc.value.detail)
    assert command in str(exc.value.detail)
