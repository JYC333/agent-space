from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.agents.authority import chat_turn_owned_by_ts, reject_python_chat_turn_when_ts_authority


def test_chat_turn_authority_is_fixed_ts(monkeypatch):
    monkeypatch.delenv("CONTROL_PLANE_CHAT_TURN_AUTHORITY", raising=False)

    assert chat_turn_owned_by_ts() is True


def test_chat_turn_authority_ignores_retired_env(monkeypatch):
    monkeypatch.setenv("CONTROL_PLANE_CHAT_TURN_AUTHORITY", "python")

    assert chat_turn_owned_by_ts() is True


def test_python_chat_turn_route_fails_closed():
    with pytest.raises(HTTPException) as exc:
        reject_python_chat_turn_when_ts_authority()

    assert exc.value.status_code == 410
    assert "TypeScript control plane" in str(exc.value.detail)
