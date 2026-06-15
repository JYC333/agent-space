from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.agents.authority import (
    chat_turn_owned_by_ts,
    reject_python_chat_turn_when_ts_authority,
)


def test_chat_turn_authority_defaults_to_python(monkeypatch):
    monkeypatch.delenv("CONTROL_PLANE_CHAT_TURN_AUTHORITY", raising=False)

    assert chat_turn_owned_by_ts() is False
    reject_python_chat_turn_when_ts_authority()


def test_chat_turn_authority_is_case_insensitive(monkeypatch):
    monkeypatch.setenv("CONTROL_PLANE_CHAT_TURN_AUTHORITY", "TS")

    assert chat_turn_owned_by_ts() is True


def test_python_chat_turn_route_fails_closed_when_ts_owned(monkeypatch):
    monkeypatch.setenv("CONTROL_PLANE_CHAT_TURN_AUTHORITY", "ts")

    with pytest.raises(HTTPException) as exc:
        reject_python_chat_turn_when_ts_authority()

    assert exc.value.status_code == 410
    assert "TypeScript control plane" in str(exc.value.detail)
