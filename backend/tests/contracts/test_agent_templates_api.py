"""HTTP contract: agent template endpoints (factory → copy-on-create)."""

from __future__ import annotations


def _params(space_id: str) -> dict[str, str]:
    return {"space_id": space_id}


def test_template_list_requires_auth(api_client, db):
    from tests.support.ids import PERSONAL_SPACE_ID

    r = api_client.get("/api/v1/agent-templates", params=_params(PERSONAL_SPACE_ID))
    assert r.status_code == 401


def test_system_templates_listed_and_instantiable(db, cross_space_pair):
    from app.agents.template_seeder import seed_system_templates

    seed_system_templates(db)
    a = cross_space_pair["space_a_id"]
    client = cross_space_pair["client_a"]

    listing = client.get("/api/v1/agent-templates", params=_params(a))
    assert listing.status_code == 200, listing.text
    keys = {t["key"] for t in listing.json()}
    # Specialized reusable templates are public; chat's system-managed assistant
    # (personal_assistant) and the never-seeded general_chat are not in the library.
    assert {"activity_reflector", "memory_reflector"} <= keys
    assert "personal_assistant" not in keys
    assert "general_chat" not in keys

    template_id = next(t["id"] for t in listing.json() if t["key"] == "activity_reflector")

    # Copy-on-create from a public specialized template.
    created = client.post(
        f"/api/v1/agent-templates/{template_id}/agents",
        params=_params(a),
        json={"name": "My Reflector"},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["name"] == "My Reflector"
    assert body["source_template_id"] == template_id
    assert body["current_version_id"] is not None
    assert body["agent_kind"] == "standard"


def test_internal_assistant_template_not_listed_or_instantiable(db, cross_space_pair):
    """personal_assistant is system_internal: hidden from the library and not
    user-instantiable via create-from-template (no duplicate Personal Assistants)."""
    from app.agents.template_seeder import seed_system_templates
    from app.models import AgentTemplate

    seed_system_templates(db)
    a = cross_space_pair["space_a_id"]
    client = cross_space_pair["client_a"]

    tpl = (
        db.query(AgentTemplate)
        .filter(AgentTemplate.scope == "system", AgentTemplate.key == "personal_assistant")
        .one()
    )
    assert tpl.visibility == "system_internal"

    # Not present in the public listing.
    listing = client.get("/api/v1/agent-templates", params=_params(a))
    assert all(t["key"] != "personal_assistant" for t in listing.json())

    # Direct create-from-template is rejected.
    rejected = client.post(
        f"/api/v1/agent-templates/{tpl.id}/agents",
        params=_params(a),
        json={"name": "Sneaky Assistant"},
    )
    assert rejected.status_code == 403, rejected.text


def test_create_publish_and_instantiate_user_template(db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    client = cross_space_pair["client_a"]

    created = client.post(
        "/api/v1/agent-templates",
        params=_params(a),
        json={
            "key": "my_tpl",
            "name": "My Template",
            "scope": "user",
            "initial_version": {"system_prompt": "hello from template"},
        },
    )
    assert created.status_code == 201, created.text
    tpl = created.json()
    assert tpl["status"] == "draft"

    versions = client.get(
        f"/api/v1/agent-templates/{tpl['id']}/versions", params=_params(a)
    ).json()
    assert len(versions) == 1
    version_id = versions[0]["id"]

    published = client.post(
        f"/api/v1/agent-templates/{tpl['id']}/versions/{version_id}/publish",
        params=_params(a),
    )
    assert published.status_code == 200, published.text
    assert published.json()["published_at"] is not None

    agent = client.post(
        f"/api/v1/agent-templates/{tpl['id']}/agents",
        params=_params(a),
        json={},
    )
    assert agent.status_code == 201, agent.text
    assert agent.json()["source_template_id"] == tpl["id"]
