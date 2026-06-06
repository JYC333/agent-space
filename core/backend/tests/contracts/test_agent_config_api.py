"""HTTP contract: agent config edit, version restore, and safety enforcement.

Covers the frontend Agent configuration slice:
  - config edit appends a NEW AgentVersion (copy-on-write), repointing current
  - the previous AgentVersion stays immutable
  - Agent.current_version_id only advances after the new version is created
  - hard safety defaults (no direct memory write, proposal-only outputs,
    no tools) cannot be bypassed by frontend overrides
  - restore appends a fresh version copied from an old one (never mutating it)
  - current-version + template-version detail expose enough config for the UI
"""

from __future__ import annotations


def _params(space_id: str) -> dict[str, str]:
    return {"space_id": space_id}


def _reflector_agent(db, client, space_id: str) -> dict:
    """Create an Activity Reflector agent (model-only, proposal-only) from the seeded template."""
    from app.agents.template_seeder import seed_system_templates

    seed_system_templates(db)
    listing = client.get("/api/v1/agent-templates", params=_params(space_id)).json()
    template_id = next(t["id"] for t in listing if t["key"] == "activity_reflector")
    created = client.post(
        f"/api/v1/agent-templates/{template_id}/agents",
        params=_params(space_id),
        json={"name": "Daily Reflector"},
    )
    assert created.status_code == 201, created.text
    return created.json()


def test_template_version_detail_exposes_config(db, cross_space_pair):
    from app.agents.template_seeder import seed_system_templates

    seed_system_templates(db)
    a = cross_space_pair["space_a_id"]
    client = cross_space_pair["client_a"]

    listing = client.get("/api/v1/agent-templates", params=_params(a)).json()
    tpl = next(t for t in listing if t["key"] == "activity_reflector")
    r = client.get(
        f"/api/v1/agent-templates/{tpl['id']}/versions/{tpl['current_version_id']}",
        params=_params(a),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["output_policy_json"]["proposal_only"] is True
    assert body["memory_policy_json"]["writable_scopes"] == []
    assert body["context_policy_json"]


def test_current_version_endpoint_returns_config(db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    client = cross_space_pair["client_a"]
    agent = _reflector_agent(db, client, a)

    r = client.get(f"/api/v1/agents/{agent['id']}/current-version", params=_params(a))
    assert r.status_code == 200, r.text
    v = r.json()
    assert v["id"] == agent["current_version_id"]
    # Copied verbatim from the template version on create.
    assert v["output_policy_json"]["proposal_only"] is True
    assert v["tool_policy_json"]["shell"] is False
    assert v["memory_policy_json"]["writable_scopes"] == []


def test_config_edit_appends_immutable_version(db, cross_space_pair):
    from app.models import Agent, AgentVersion

    a = cross_space_pair["space_a_id"]
    client = cross_space_pair["client_a"]
    agent = _reflector_agent(db, client, a)
    v1_id = agent["current_version_id"]
    before = db.query(AgentVersion).filter(AgentVersion.agent_id == agent["id"]).count()

    r = client.post(
        f"/api/v1/agents/{agent['id']}/config",
        params=_params(a),
        json={
            "description": "edited",
            "system_prompt": "reflect more carefully",
            "model_config_json": {"max_tokens": 4096},
            "schedule_config_json": {"enabled": True, "cron": "0 9 * * *"},
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    new_version_id = body["current_version_id"]
    assert new_version_id != v1_id
    assert body["description"] == "edited"

    db.expire_all()
    assert db.query(AgentVersion).filter(AgentVersion.agent_id == agent["id"]).count() == before + 1
    new_v = db.query(AgentVersion).filter(AgentVersion.id == new_version_id).one()
    assert new_v.system_prompt == "reflect more carefully"
    assert new_v.model_config_json["max_tokens"] == 4096
    assert new_v.schedule_config_json["enabled"] is True
    # Old version unchanged.
    old_v = db.query(AgentVersion).filter(AgentVersion.id == v1_id).one()
    assert old_v.system_prompt != "reflect more carefully"
    assert old_v.model_config_json.get("max_tokens") != 4096
    # Current pointer advanced only after the new version exists.
    assert db.query(Agent).filter(Agent.id == agent["id"]).one().current_version_id == new_version_id


def test_config_edit_cannot_bypass_hard_safety(db, cross_space_pair):
    """A frontend override must not grant direct memory write, disable proposal-only
    outputs, or unlock tools."""
    from app.models import AgentVersion

    a = cross_space_pair["space_a_id"]
    client = cross_space_pair["client_a"]
    agent = _reflector_agent(db, client, a)

    r = client.post(
        f"/api/v1/agents/{agent['id']}/config",
        params=_params(a),
        json={
            "memory_policy_json": {
                "writable_scopes": ["space", "user"],
                "requires_proposal": False,
                "readable_scopes": ["space"],
            },
            "output_policy_json": {"proposal_only": False, "auto_save": True},
        },
    )
    assert r.status_code == 200, r.text
    new_version_id = r.json()["current_version_id"]

    db.expire_all()
    v = db.query(AgentVersion).filter(AgentVersion.id == new_version_id).one()
    # Write access and proposal requirement are re-stamped from the source.
    assert v.memory_policy_json["writable_scopes"] == []
    assert v.memory_policy_json["requires_proposal"] is True
    # Editable part still applied.
    assert v.memory_policy_json["readable_scopes"] == ["space"]
    # Proposal-only outputs cannot be turned off.
    assert v.output_policy_json["proposal_only"] is True
    # Tools remain locked (copied verbatim, never editable here).
    assert v.tool_policy_json["shell"] is False
    assert v.tool_policy_json["file_write"] is False
    assert v.tool_policy_json["credential_access"] is False


def test_restore_version_appends_new_version(db, cross_space_pair):
    from app.models import Agent, AgentVersion

    a = cross_space_pair["space_a_id"]
    client = cross_space_pair["client_a"]
    agent = _reflector_agent(db, client, a)
    v1_id = agent["current_version_id"]

    # Edit once so there's a distinct current version to restore away from.
    edited = client.post(
        f"/api/v1/agents/{agent['id']}/config",
        params=_params(a),
        json={"system_prompt": "version two"},
    ).json()
    v2_id = edited["current_version_id"]
    assert v2_id != v1_id

    restored = client.post(
        f"/api/v1/agents/{agent['id']}/versions/{v1_id}/restore",
        params=_params(a),
    )
    assert restored.status_code == 200, restored.text
    v3_id = restored.json()["current_version_id"]
    assert v3_id not in (v1_id, v2_id)

    db.expire_all()
    # A brand-new version was appended; v1 and v2 are untouched.
    assert db.query(AgentVersion).filter(AgentVersion.agent_id == agent["id"]).count() == 3
    v1 = db.query(AgentVersion).filter(AgentVersion.id == v1_id).one()
    v3 = db.query(AgentVersion).filter(AgentVersion.id == v3_id).one()
    assert v3.system_prompt == v1.system_prompt  # config copied from the restored version
    assert v1.system_prompt != "version two"
    assert db.query(Agent).filter(Agent.id == agent["id"]).one().current_version_id == v3_id


def test_create_from_template_applies_overrides_with_safety_restamp(db, cross_space_pair):
    """Create-from-template overrides are configurable but cannot bypass hard safety:
    context/output/batch apply; memory write + proposal-only stay locked."""
    from app.agents.template_seeder import seed_system_templates
    from app.models import AgentVersion
    from tests.support import factories

    a = cross_space_pair["space_a_id"]
    client = cross_space_pair["client_a"]
    seed_system_templates(db)
    factories.create_test_model_provider(
        db, space_id=a, is_default=True, default_model="claude-sonnet-4-6", commit=True
    )
    template_id = next(
        t["id"] for t in client.get("/api/v1/agent-templates", params=_params(a)).json()
        if t["key"] == "activity_reflector"
    )

    created = client.post(
        f"/api/v1/agent-templates/{template_id}/agents",
        params=_params(a),
        json={
            "name": "Tweaked Reflector",
            "context_policy_json": {"batch_size": 5},
            "output_policy_json": {"proposal_only": False, "allowed_output_types": ["task_create_proposal"]},
            "memory_policy_json": {"writable_scopes": ["space"], "requires_proposal": False},
        },
    )
    assert created.status_code == 201, created.text
    v = db.query(AgentVersion).filter(AgentVersion.id == created.json()["current_version_id"]).one()

    # Configurable overrides applied.
    assert v.context_policy_json["batch_size"] == 5
    # Override narrowed the allowed outputs (a subset of the template's ceiling).
    assert v.output_policy_json["allowed_output_types"] == ["task_create_proposal"]
    # Concrete system-default model stamped.
    assert v.model_name == "claude-sonnet-4-6"
    # HARD SAFETY re-stamped from the template version — overrides cannot loosen these.
    assert v.output_policy_json["proposal_only"] is True
    assert v.memory_policy_json["writable_scopes"] == []
    assert v.memory_policy_json["requires_proposal"] is True
    assert v.tool_policy_json["shell"] is False
    assert v.tool_policy_json["file_write"] is False


def test_config_edit_requires_auth(api_client, db, cross_space_pair_db):
    from tests.support import factories

    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=True)
    r = api_client.post(
        f"/api/v1/agents/{agent.id}/config",
        params=_params(a),
        json={"system_prompt": "x"},
    )
    assert r.status_code == 401


def test_config_edit_cross_space_returns_404(db, cross_space_pair):
    from tests.support import factories

    a = cross_space_pair["space_a_id"]
    b = cross_space_pair["space_b_id"]
    ua = cross_space_pair["user_a"]
    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=True)
    r = cross_space_pair["client_b"].post(
        f"/api/v1/agents/{agent.id}/config",
        params=_params(b),
        json={"system_prompt": "x"},
    )
    assert r.status_code == 404
