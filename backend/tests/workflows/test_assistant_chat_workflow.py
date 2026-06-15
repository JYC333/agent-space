"""End-to-end: a synchronous Personal Assistant chat turn via POST /agents/{id}/chat.

Drives the real chat path — a Session message + ChatContextBuilder + a queued Run
executed in-process through RunExecutionService and the no-tools ``model_api`` adapter —
with only ``litellm.completion`` (the network call) mocked. Proves the endpoint returns
the model reply, persists both turns (raw user message, then assistant reply), and links
the run to the session. Also covers the clean provider-missing failure: ``ok=False`` with
an error code and no fabricated assistant turn.
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

from app.auth.session import SESSION_COOKIE, UserSessionService
from app.config import settings
from app.main import app
from app.models import AgentVersion, Message, Run
from starlette.testclient import TestClient
from tests.support import factories


def _new_id() -> str:
    return str(uuid.uuid4())


def _fake_litellm_response(text: str):
    choice = MagicMock()
    choice.message.content = text
    resp = MagicMock()
    resp.choices = [choice]
    resp.usage = None
    return resp


def _authed_client(db, user_id: str) -> TestClient:
    _, raw = UserSessionService(db).create(user_id)
    db.commit()
    return TestClient(app, cookies={SESSION_COOKIE: raw}, raise_server_exceptions=True)


def _model_api_agent(db, *, space_id: str, owner_user_id: str):
    """A test agent whose current version resolves to the no-tools model_api adapter."""
    agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=owner_user_id, commit=False)
    version = db.query(AgentVersion).filter(AgentVersion.id == agent.current_version_id).one()
    policy = dict(version.runtime_policy_json or {})
    policy["default_adapter_type"] = "model_api"
    version.runtime_policy_json = policy
    db.flush()
    return agent


def _isolate_storage(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "artifact_storage_root", str(tmp_path / "artifacts"))
    monkeypatch.setattr(settings, "workspace_root", str(tmp_path / "workspaces"))
    monkeypatch.setattr(settings, "sandbox_root", str(tmp_path / "sandboxes"))


def test_chat_endpoint_returns_reply_and_persists_turns(
    db, workflow_app_db_override, tmp_path, monkeypatch
):
    _isolate_storage(monkeypatch, tmp_path)
    space_id = _new_id()
    factories.create_test_space(db, space_id=space_id, name="Personal", space_type="personal", commit=False)
    user = factories.create_test_user(db, space_id=space_id, commit=False)
    factories.create_test_model_provider(
        db, space_id=space_id, provider_type="openai", with_api_key=True,
        is_default=True, enabled=True, default_model="gpt-test", commit=False,
    )
    agent = _model_api_agent(db, space_id=space_id, owner_user_id=user.id)
    db.commit()

    c = _authed_client(db, user.id)
    with patch("litellm.completion", return_value=_fake_litellm_response("Hello from the assistant.")):
        r = c.post(
            f"/api/v1/agents/{agent.id}/chat",
            params={"space_id": space_id},
            json={"message": "Hi there"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["reply"] == "Hello from the assistant."
    assert body["session_id"]
    assert body["run_id"]

    db.expire_all()
    msgs = (
        db.query(Message)
        .filter(Message.session_id == body["session_id"])
        .order_by(Message.created_at)
        .all()
    )
    assert [m.role for m in msgs] == ["user", "assistant"]
    # The raw user message is stored (not the context-composed model prompt).
    assert msgs[0].content == "Hi there"
    assert msgs[1].content == "Hello from the assistant."
    assert (msgs[1].metadata_json or {}).get("run_id") == body["run_id"]

    run = db.query(Run).filter(Run.id == body["run_id"]).one()
    assert run.status == "succeeded"
    assert run.session_id == body["session_id"]


def test_chat_endpoint_fails_cleanly_without_provider(
    db, workflow_app_db_override, tmp_path, monkeypatch
):
    _isolate_storage(monkeypatch, tmp_path)
    space_id = _new_id()
    factories.create_test_space(db, space_id=space_id, name="Personal", space_type="personal", commit=False)
    user = factories.create_test_user(db, space_id=space_id, commit=False)
    agent = _model_api_agent(db, space_id=space_id, owner_user_id=user.id)  # no provider configured
    db.commit()

    c = _authed_client(db, user.id)
    r = c.post(
        f"/api/v1/agents/{agent.id}/chat",
        params={"space_id": space_id},
        json={"message": "Hello?"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is False
    assert not body["reply"]
    assert body["error_code"]  # e.g. model_provider_required

    # Only the user turn is persisted — no fabricated assistant reply.
    db.expire_all()
    msgs = db.query(Message).filter(Message.session_id == body["session_id"]).all()
    assert [m.role for m in msgs] == ["user"]


def test_chat_adapter_policy_failure_happens_during_execution(
    db, workflow_app_db_override, tmp_path, monkeypatch
):
    _isolate_storage(monkeypatch, tmp_path)
    space_id = _new_id()
    factories.create_test_space(db, space_id=space_id, name="Personal", space_type="personal", commit=False)
    user = factories.create_test_user(db, space_id=space_id, commit=False)
    factories.create_test_model_provider(
        db,
        space_id=space_id,
        provider_type="openai",
        with_api_key=True,
        is_default=True,
        enabled=True,
        default_model="gpt-test",
        commit=False,
    )
    agent = _model_api_agent(db, space_id=space_id, owner_user_id=user.id)
    version = db.query(AgentVersion).filter(AgentVersion.id == agent.current_version_id).one()
    version.runtime_policy_json = {
        **(version.runtime_policy_json or {}),
        "allowed_adapter_types": ["capability"],
    }
    db.commit()

    c = _authed_client(db, user.id)
    r = c.post(
        f"/api/v1/agents/{agent.id}/chat",
        params={"space_id": space_id},
        json={"message": "Hello?"},
    )

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is False
    assert body["error_code"] == "adapter_type_disallowed"

    db.expire_all()
    msgs = db.query(Message).filter(Message.session_id == body["session_id"]).all()
    assert [m.role for m in msgs] == ["user"]


def test_chat_endpoint_rejects_empty_message(db, workflow_app_db_override):
    space_id = _new_id()
    factories.create_test_space(db, space_id=space_id, name="Personal", space_type="personal", commit=False)
    user = factories.create_test_user(db, space_id=space_id, commit=False)
    agent = _model_api_agent(db, space_id=space_id, owner_user_id=user.id)
    db.commit()

    c = _authed_client(db, user.id)
    r = c.post(
        f"/api/v1/agents/{agent.id}/chat",
        params={"space_id": space_id},
        json={"message": "   "},
    )
    assert r.status_code == 422
