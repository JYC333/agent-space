import pytest
from app.agents.agent_service import AgentService
from app.schemas import AgentCreate, AgentUpdate, RunRequest
from tests.conftest import SPACE, USER, ensure_space, ensure_user


def _make_agent(db, **kwargs) -> object:
    svc = AgentService(db)
    return svc.create(AgentCreate(
        name=kwargs.get("name", "Test Agent"),
        description=kwargs.get("description", "A test agent"),
        created_by_user_id=kwargs.get("created_by_user_id", USER),
        visibility=kwargs.get("visibility", "private"),
        space_id=kwargs.get("space_id", SPACE),
        role_instruction=kwargs.get("role_instruction", "You are a helpful agent."),
        runtime_policy_json=kwargs.get("runtime_policy_json", {
            "risk_level": "medium",
            "can_delegate": True,
            "max_delegation_depth": 3,
            "max_run_time_seconds": 300,
            "allowed_adapter_types": ["echo"],
        }),
    ), requesting_user_id=kwargs.get("created_by_user_id", USER))


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

def test_create_agent(db):
    agent = _make_agent(db)
    assert agent.id
    assert agent.status == "active"
    assert agent.space_id == SPACE
    assert agent.created_by_user_id == USER
    assert agent.visibility == "private"
    # Agent executable config lives on AgentVersion, not Agent
    assert agent.current_version_id is not None
    from app.agents.version_service import AgentVersionService
    version_svc = AgentVersionService(db)
    version = version_svc.get_or_404(agent.current_version_id)
    assert "model" in version.model_config_json
    assert "readable_scopes" in version.memory_policy_json


def test_get_agent(db):
    agent = _make_agent(db)
    svc = AgentService(db)
    fetched = svc.get(agent.id)
    assert fetched is not None
    assert fetched.id == agent.id


def test_list_agents_by_creator(db):
    ensure_user(db, "user_a")
    ensure_user(db, "user_b")
    _make_agent(db, created_by_user_id="user_a")
    _make_agent(db, created_by_user_id="user_a")
    _make_agent(db, created_by_user_id="user_b")

    svc = AgentService(db)
    a_agents = svc.list(space_id=SPACE, created_by_user_id="user_a")
    b_agents = svc.list(space_id=SPACE, created_by_user_id="user_b")
    assert len(a_agents) == 2
    assert len(b_agents) == 1


def test_list_agents_space_isolation(db):
    ensure_space(db, "space_a")
    ensure_space(db, "space_b")
    _make_agent(db, space_id="space_a")
    _make_agent(db, space_id="space_b")

    svc = AgentService(db)
    assert len(svc.list(space_id="space_a")) == 1
    assert len(svc.list(space_id="space_b")) == 1


def test_update_agent(db):
    agent = _make_agent(db)
    svc = AgentService(db)
    updated = svc.update(agent.id, AgentUpdate(name="Renamed Agent", status="disabled"))
    assert updated.name == "Renamed Agent"
    assert updated.status == "disabled"


def test_delete_agent(db):
    agent = _make_agent(db)
    svc = AgentService(db)
    assert svc.delete(agent.id) is True
    # soft-delete: status → "archived", agent is still queryable
    assert svc.get(agent.id).status == "archived"


def test_agent_visibility(db):
    svc = AgentService(db)
    private_agent = svc.create(AgentCreate(name="Private", visibility="private", space_id=SPACE), requesting_user_id=USER)
    shared_agent = svc.create(AgentCreate(name="Shared", visibility="space_shared", space_id=SPACE), requesting_user_id=USER)

    assert private_agent.visibility == "private"
    assert shared_agent.visibility == "space_shared"

    # Filter by visibility
    private_list = svc.list(space_id=SPACE, visibility="private")
    shared_list = svc.list(space_id=SPACE, visibility="space_shared")
    assert all(a.visibility == "private" for a in private_list)
    assert all(a.visibility == "space_shared" for a in shared_list)


# ---------------------------------------------------------------------------
# Running agents (user → agent)
# ---------------------------------------------------------------------------

def test_user_runs_agent(db):
    agent = _make_agent(db)
    svc = AgentService(db)
    run = svc.run(
        agent_id=agent.id,
        req=RunRequest(prompt="Hello, agent!", adapter_type="echo"),
        space_id=SPACE,
        instructed_by_user_id=USER,
    )
    assert run.id
    assert run.status == "queued"  # Run is queued until the worker executes it
    assert run.agent_id == agent.id
    assert run.instructed_by_user_id == USER
    assert run.delegation_depth == 0
    assert run.parent_run_id is None


def test_run_disabled_agent_fails(db):
    agent = _make_agent(db)
    svc = AgentService(db)
    svc.update(agent.id, AgentUpdate(status="disabled"))

    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        svc.run(
            agent_id=agent.id,
            req=RunRequest(prompt="Hello", adapter_type="echo"),
            space_id=SPACE,
            instructed_by_user_id=USER,
        )
    assert exc_info.value.status_code == 409


def test_run_with_disallowed_adapter_fails(db):
    agent = _make_agent(db, runtime_policy_json={
        "allowed_adapter_types": ["echo"],
        "can_delegate": True,
        "max_delegation_depth": 3,
    })
    svc = AgentService(db)

    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        svc.run(
            agent_id=agent.id,
            req=RunRequest(prompt="Hi", adapter_type="claude_cli"),
            space_id=SPACE,
            instructed_by_user_id=USER,
        )
    assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# Multi-agent delegation (agent → agent)
# ---------------------------------------------------------------------------

def test_agent_delegates_to_agent(db):
    agent_a = _make_agent(db, name="Agent A")
    agent_b = _make_agent(db, name="Agent B")
    svc = AgentService(db)

    # User starts agent A
    parent_run = svc.run(
        agent_id=agent_a.id,
        req=RunRequest(prompt="Do the work", adapter_type="echo"),
        space_id=SPACE,
        instructed_by_user_id=USER,
    )
    assert parent_run.delegation_depth == 0

    # Agent A delegates to Agent B
    child_run = svc.delegate(
        target_agent_id=agent_b.id,
        req=RunRequest(prompt="Sub-task", adapter_type="echo"),
        space_id=SPACE,
        parent_run_id=parent_run.id,
        instructed_by_agent_id=agent_a.id,
    )
    assert child_run.agent_id == agent_b.id
    assert child_run.parent_run_id == parent_run.id
    assert child_run.instructed_by_agent_id == agent_a.id
    assert child_run.delegation_depth == 1
    assert child_run.instructed_by_user_id is None


def test_delegation_depth_limit_enforced(db):
    agent_a = _make_agent(db, name="A", runtime_policy_json={
        "can_delegate": True,
        "max_delegation_depth": 1,
        "allowed_adapter_types": ["echo"],
    })
    agent_b = _make_agent(db, name="B")
    agent_c = _make_agent(db, name="C")
    svc = AgentService(db)

    parent_run = svc.run(
        agent_id=agent_a.id,
        req=RunRequest(prompt="Start", adapter_type="echo"),
        space_id=SPACE,
        instructed_by_user_id=USER,
    )
    # depth=0 → depth=1: parent depth 0 < max_depth 1 → allowed
    child_run = svc.delegate(
        target_agent_id=agent_b.id,
        req=RunRequest(prompt="Level 1", adapter_type="echo"),
        space_id=SPACE,
        parent_run_id=parent_run.id,
        instructed_by_agent_id=agent_a.id,
    )
    assert child_run.delegation_depth == 1

    # depth=1 → depth=2: parent depth 1 == max_depth 1 → DENIED
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        svc.delegate(
            target_agent_id=agent_c.id,
            req=RunRequest(prompt="Level 2", adapter_type="echo"),
            space_id=SPACE,
            parent_run_id=child_run.id,
            instructed_by_agent_id=agent_a.id,
        )
    assert exc_info.value.status_code == 403


def test_no_delegation_permission_enforced(db):
    agent_a = _make_agent(db, name="No-delegate agent", runtime_policy_json={
        "can_delegate": False,
        "max_delegation_depth": 3,
        "allowed_adapter_types": ["echo"],
    })
    agent_b = _make_agent(db, name="B")
    svc = AgentService(db)

    parent_run = svc.run(
        agent_id=agent_a.id,
        req=RunRequest(prompt="Start", adapter_type="echo"),
        space_id=SPACE,
        instructed_by_user_id=USER,
    )

    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        svc.delegate(
            target_agent_id=agent_b.id,
            req=RunRequest(prompt="Delegate", adapter_type="echo"),
            space_id=SPACE,
            parent_run_id=parent_run.id,
            instructed_by_agent_id=agent_a.id,
        )
    assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# Delegation chain inspection
# ---------------------------------------------------------------------------

def test_delegation_chain_retrieval(db):
    agent_a = _make_agent(db, name="A")
    agent_b = _make_agent(db, name="B")
    svc = AgentService(db)

    run_a = svc.run(
        agent_id=agent_a.id,
        req=RunRequest(prompt="Root", adapter_type="echo"),
        space_id=SPACE,
        instructed_by_user_id=USER,
    )
    run_b = svc.delegate(
        target_agent_id=agent_b.id,
        req=RunRequest(prompt="Child", adapter_type="echo"),
        space_id=SPACE,
        parent_run_id=run_a.id,
        instructed_by_agent_id=agent_a.id,
    )

    # Delegation chain is stored via parent_run_id on Run records
    assert run_b.parent_run_id == run_a.id
    assert run_b.delegation_depth == 1


# ---------------------------------------------------------------------------
# Agent memory policy enforcement in context
# ---------------------------------------------------------------------------

def test_agent_with_restricted_memory_policy(db):
    from app.memory.store import MemoryStore
    from app.schemas import MemoryCreate
    from app.memory.context_builder import ContextBuilder

    # Seed a user-scope memory
    store = MemoryStore(db)
    store.create(
        MemoryCreate(
            title="User pref",
            content="I prefer Python.",
            type="preference",
            scope="user",
            namespace="user.default.preferences",
            space_id=SPACE,
            subject_user_id=USER,
        ),
        acting_user_id=USER,
    )

    # Agent with memory policy restricted to ["system", "agent"] only — cannot read "user"
    restricted_policy = {
        "readable_scopes": ["system", "agent"],
        "writable_scopes": ["agent"],
        "readable_types": ["semantic"],
    }

    builder = ContextBuilder(db)
    pkg = builder.build(
        space_id=SPACE,
        user_id=USER,
        agent_memory_policy=restricted_policy,
    )
    # user scope excluded by policy
    assert len(pkg.user_memory) == 0


def test_agent_with_full_memory_policy(db):
    from app.memory.store import MemoryStore
    from app.schemas import MemoryCreate
    from app.memory.context_builder import ContextBuilder

    store = MemoryStore(db)
    store.create(
        MemoryCreate(
            title="User pref",
            content="I prefer Rust.",
            type="preference",
            scope="user",
            namespace="user.default.preferences",
            space_id=SPACE,
            subject_user_id=USER,
            importance=0.8,
        ),
        acting_user_id=USER,
    )

    # Default full policy allows all scopes
    from app.schemas import DEFAULT_MEMORY_POLICY
    builder = ContextBuilder(db)
    pkg = builder.build(
        space_id=SPACE,
        user_id=USER,
        agent_memory_policy=DEFAULT_MEMORY_POLICY,
    )
    assert len(pkg.user_memory) >= 1
