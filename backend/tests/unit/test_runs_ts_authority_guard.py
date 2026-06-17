from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.runs.authority import (
    reject_python_run_command_when_ts_authority,
    runs_commands_owned_by_ts,
)


def test_runs_authority_is_fixed_to_ts(monkeypatch):
    monkeypatch.delenv("CONTROL_PLANE_RUNS_AUTHORITY", raising=False)

    assert runs_commands_owned_by_ts() is True
    with pytest.raises(HTTPException) as exc:
        reject_python_run_command_when_ts_authority("execute")
    assert exc.value.status_code == 410


def test_runs_authority_rejects_python_execute_when_ts_owned(monkeypatch):
    monkeypatch.setenv("CONTROL_PLANE_RUNS_AUTHORITY", "python")

    with pytest.raises(HTTPException) as exc:
        reject_python_run_command_when_ts_authority("execute")

    assert exc.value.status_code == 410
    assert "TypeScript control plane" in str(exc.value.detail)


class _FakeRunQuery:
    def __init__(self, run):
        self._run = run

    def filter(self, *args):
        return self

    def first(self):
        return self._run


class _FakeDb:
    def __init__(self, run):
        self._run = run
        self.expired = False

    def expire_all(self):
        self.expired = True

    def query(self, model):
        return _FakeRunQuery(self._run)


def test_chat_run_execution_routes_through_ts_authority(monkeypatch):
    from app.agents import chat_service

    calls: list[dict] = []

    def fake_execute(**kwargs):
        calls.append(kwargs)
        return {"run_id": kwargs["run_id"], "status": "succeeded"}

    monkeypatch.setattr(chat_service, "execute_run_via_control_plane", fake_execute)
    run = SimpleNamespace(
        id="run-1",
        space_id="space-1",
        status="succeeded",
        output_json={"output_text": "hello there"},
        error_json=None,
    )
    db = _FakeDb(run)

    ok, reply, error, error_code = chat_service._execute_chat_run_via_ts(
        db, run_id="run-1", space_id="space-1"
    )

    assert calls and calls[0]["run_id"] == "run-1"
    assert db.expired is True
    assert (ok, reply, error, error_code) == (True, "hello there", None, None)


def test_chat_run_execution_surfaces_ts_failure(monkeypatch):
    from app.agents import chat_service
    from app.runs.ts_execution_client import TsRunExecutionError

    def fake_execute(**kwargs):
        raise TsRunExecutionError("control plane unavailable")

    monkeypatch.setattr(chat_service, "execute_run_via_control_plane", fake_execute)
    db = _FakeDb(None)

    ok, reply, error, error_code = chat_service._execute_chat_run_via_ts(
        db, run_id="run-1", space_id="space-1"
    )

    assert ok is False
    assert reply is None
    assert error_code == "ts_run_execution_unavailable"
    assert "unavailable" in (error or "")


def test_chat_run_execution_maps_failed_run_error(monkeypatch):
    from app.agents import chat_service

    monkeypatch.setattr(
        chat_service,
        "execute_run_via_control_plane",
        lambda **kwargs: {"run_id": kwargs["run_id"], "status": "failed"},
    )
    run = SimpleNamespace(
        id="run-1",
        space_id="space-1",
        status="failed",
        output_json={},
        error_json={"error_code": "policy_denied", "error_text": "denied by policy"},
    )
    db = _FakeDb(run)

    ok, reply, error, error_code = chat_service._execute_chat_run_via_ts(
        db, run_id="run-1", space_id="space-1"
    )

    assert ok is False
    assert error_code == "policy_denied"
    assert error == "denied by policy"
