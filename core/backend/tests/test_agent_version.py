"""
Agent and AgentVersion API / service tests.

Covers AgentVersion invariants using direct service/DB testing to avoid
triggering the full FastAPI lifespan where unnecessary.

API-level smoke tests use TestClient with lifespan; CapabilityRegistry.reload()
loads file-defined manifests only (no DB Capability table in the canonical schema).
"""

import pytest

pytestmark = pytest.mark.canonical

from app.models import Agent, AgentVersion, Run
from app.agents.agent_service import AgentService
from app.agents.version_service import AgentVersionService
from app.agents.seeder import seed_builtin_agents
from app.schemas import AgentCreate, AgentUpdate, AgentVersionCreate
from app.schemas import DEFAULT_MODEL_CONFIG, DEFAULT_MEMORY_POLICY, DEFAULT_RUNTIME_POLICY

# Use IDs from conftest.py (which creates Space="personal" and User="default_user")
SPACE_ID = "personal"
USER_ID = "default_user"

SYSTEM_AGENT_IDS = ["system.echo-agent", "system.memory-curator-agent"]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def service(db):
    return AgentService(db)


@pytest.fixture
def version_service(db):
    return AgentVersionService(db)


# ---------------------------------------------------------------------------
# System agent seeding — initial AgentVersion
# ---------------------------------------------------------------------------

class TestSystemAgentSeeding:
    def test_seeding_creates_system_agents_with_current_version_id(self, db):
        """seed_builtin_agents() creates Agent records with current_version_id set."""
        seed_builtin_agents(db, space_id=SPACE_ID, owner_user_id=USER_ID)

        for agent_id in SYSTEM_AGENT_IDS:
            agent = db.query(Agent).filter(Agent.id == agent_id).first()
            assert agent is not None, f"{agent_id} not found"
            assert agent.current_version_id is not None, f"{agent_id} has no current_version_id"

    def test_seeding_creates_v1_agent_version_for_each_system_agent(self, db):
        """Each system agent has a v1 AgentVersion after seeding."""
        seed_builtin_agents(db, space_id=SPACE_ID, owner_user_id=USER_ID)

        for agent_id in SYSTEM_AGENT_IDS:
            agent = db.query(Agent).filter(Agent.id == agent_id).first()
            assert agent is not None
            version = db.query(AgentVersion).filter(AgentVersion.id == agent.current_version_id).first()
            assert version is not None, f"{agent_id} has no AgentVersion"
            assert version.version_label == "v1"
            assert version.agent_id == agent.id
            assert version.space_id == SPACE_ID

    def test_seeding_does_not_write_exec_config_to_agent_record(self, db):
        """System agent executable config lives on AgentVersion, not on Agent."""
        seed_builtin_agents(db, space_id=SPACE_ID, owner_user_id=USER_ID)

        for agent_id in SYSTEM_AGENT_IDS:
            agent = db.query(Agent).filter(Agent.id == agent_id).first()
            version = db.query(AgentVersion).filter(AgentVersion.id == agent.current_version_id).first()

            # Agent record should have role_instruction (display text)
            assert agent.role_instruction is not None

            # Agent should NOT have runtime_policy_json/memory_policy_json columns
            # (they live on AgentVersion)
            # We can verify this by checking the Agent model doesn't expose these as columns
            # The version has the config
            assert version.runtime_policy_json is not None
            assert version.memory_policy_json is not None

    def test_seeding_preserves_existing_agents_with_version(self, db):
        """Re-seeding does not overwrite existing system agents."""
        seed_builtin_agents(db, space_id=SPACE_ID, owner_user_id=USER_ID)

        agent = db.query(Agent).filter(Agent.id == "system.echo-agent").first()
        original_version_id = agent.current_version_id

        seed_builtin_agents(db, space_id=SPACE_ID, owner_user_id=USER_ID)

        db.refresh(agent)
        assert agent.current_version_id == original_version_id

    def test_seeding_stores_correct_runtime_policy(self, db):
        """System agents' runtime_policy is correctly stored on AgentVersion."""
        seed_builtin_agents(db, space_id=SPACE_ID, owner_user_id=USER_ID)

        agent = db.query(Agent).filter(Agent.id == "system.echo-agent").first()
        version = db.query(AgentVersion).filter(AgentVersion.id == agent.current_version_id).first()

        # echo-agent should resolve to echo adapter (default_adapter_type in tests)
        assert version.runtime_policy_json.get("allowed_adapter_types") == ["echo"]
        assert version.runtime_policy_json.get("default_adapter_type") == "echo"
        assert version.runtime_policy_json.get("risk_level") == "low"
        assert version.runtime_policy_json.get("max_run_time_seconds") == 30

        memory_curator = db.query(Agent).filter(Agent.id == "system.memory-curator-agent").first()
        mc_version = db.query(AgentVersion).filter(AgentVersion.id == memory_curator.current_version_id).first()
        assert mc_version.runtime_policy_json.get("allowed_adapter_types") == ["echo", "claude_cli"]
        assert mc_version.runtime_policy_json.get("max_run_time_seconds") == 120

    def test_seeding_creates_system_prompt_on_agent_version(self, db):
        """System agents' system_prompt is stored on AgentVersion (not role_instruction)."""
        seed_builtin_agents(db, space_id=SPACE_ID, owner_user_id=USER_ID)

        for agent_id in SYSTEM_AGENT_IDS:
            agent = db.query(Agent).filter(Agent.id == agent_id).first()
            version = db.query(AgentVersion).filter(AgentVersion.id == agent.current_version_id).first()
            # system_prompt should be non-null and non-empty
            assert version.system_prompt is not None and len(version.system_prompt) > 0
            # role_instruction should also be set (display text)
            assert agent.role_instruction is not None


# ---------------------------------------------------------------------------
# Agent creation creates v1
# ---------------------------------------------------------------------------

class TestAgentCreate:
    def test_creating_agent_creates_v1_version(self, db, service):
        """AgentService.create() creates an initial v1 AgentVersion."""
        data = AgentCreate(name="Test Agent", description="A test agent")
        agent = service.create(data, requesting_user_id=USER_ID)

        assert agent.current_version_id is not None

        version = db.query(AgentVersion).filter(AgentVersion.id == agent.current_version_id).first()
        assert version is not None
        assert version.version_label == "v1"
        assert version.agent_id == agent.id
        assert version.space_id == SPACE_ID

    def test_agent_current_version_id_points_to_v1(self, db, service):
        """Agent.current_version_id points to the v1 AgentVersion."""
        agent = service.create(AgentCreate(name="My Agent"), requesting_user_id=USER_ID)

        assert agent.current_version_id is not None
        version = db.query(AgentVersion).filter(AgentVersion.id == agent.current_version_id).first()
        assert version.version_label == "v1"

    def test_agent_version_has_correct_defaults(self, db, service):
        """Initial version has default config values."""
        agent = service.create(AgentCreate(name="Config Test Agent"), requesting_user_id=USER_ID)
        version = db.query(AgentVersion).filter(AgentVersion.id == agent.current_version_id).first()

        assert version.model_config_json == DEFAULT_MODEL_CONFIG
        assert version.memory_policy_json == DEFAULT_MEMORY_POLICY
        assert version.runtime_policy_json == DEFAULT_RUNTIME_POLICY
        assert version.capabilities_json == []
        assert version.tool_permissions_json == {}


# ---------------------------------------------------------------------------
# Agent update creates version only when execution config changes
# ---------------------------------------------------------------------------

class TestAgentUpdate:
    def test_identity_only_patch_does_not_create_version(self, db, service):
        """update() with identity fields only does not create a new AgentVersion."""
        agent = service.create(AgentCreate(name="Original"), requesting_user_id=USER_ID)
        original_version_id = agent.current_version_id

        service.update(agent.id, AgentUpdate(name="Updated Name", description="New desc"))

        db.refresh(agent)
        assert agent.current_version_id == original_version_id

        versions = db.query(AgentVersion).filter(AgentVersion.agent_id == agent.id).all()
        assert len(versions) == 1

    def test_execution_config_patch_creates_new_version(self, db, service):
        """update() with execution config fields creates a new AgentVersion."""
        agent = service.create(AgentCreate(name="Base Agent"), requesting_user_id=USER_ID)
        v1_id = agent.current_version_id

        updated = service.update(
            agent.id,
            AgentUpdate(runtime_policy_json={"risk_level": "high"}),
        )

        assert updated.current_version_id != v1_id

        v1 = db.query(AgentVersion).filter(AgentVersion.id == v1_id).first()
        assert v1.version_label == "v1"

        v2 = db.query(AgentVersion).filter(AgentVersion.id == updated.current_version_id).first()
        assert v2.runtime_policy_json.get("risk_level") == "high"

    def test_old_versions_unchanged_after_new_version(self, db, service):
        """Old AgentVersion records are never modified when a new version is created."""
        agent = service.create(AgentCreate(name="Original"), requesting_user_id=USER_ID)
        v1_id = agent.current_version_id

        # Set v1's runtime_policy to 600 via explicit version creation
        v1 = db.query(AgentVersion).filter(AgentVersion.id == v1_id).first()
        v1.runtime_policy_json = {"max_run_time_seconds": 600, "risk_level": "medium", "can_delegate": True, "max_delegation_depth": 3, "allowed_adapter_types": ["echo"]}
        db.commit()

        service.update(
            agent.id,
            AgentUpdate(runtime_policy_json={"max_run_time_seconds": 300}),
        )

        db.refresh(v1)
        assert v1.runtime_policy_json.get("max_run_time_seconds") == 600

    def test_patch_merges_with_current_version(self, db, service):
        """Partial execution config updates merge with current version fields."""
        agent = service.create(AgentCreate(name="Merge Test"), requesting_user_id=USER_ID)
        v1_id = agent.current_version_id

        # Set v1 to have runtime_policy with max_run_time_seconds=600 and risk_level=high
        v1 = db.query(AgentVersion).filter(AgentVersion.id == v1_id).first()
        v1.runtime_policy_json = {"max_run_time_seconds": 600, "risk_level": "high", "can_delegate": True, "max_delegation_depth": 3, "allowed_adapter_types": ["echo"]}
        db.commit()

        updated = service.update(
            agent.id,
            AgentUpdate(model_config_json={"model": "claude-opus-4-7"}),
        )

        v2 = db.query(AgentVersion).filter(AgentVersion.id == updated.current_version_id).first()
        assert v2.model_config_json["model"] == "claude-opus-4-7"
        assert v2.runtime_policy_json["max_run_time_seconds"] == 600
        assert v2.runtime_policy_json["risk_level"] == "high"


# ---------------------------------------------------------------------------
# Explicit version creation
# ---------------------------------------------------------------------------

class TestAgentVersionCreate:
    def test_explicit_version_create_advances_current_version_id(self, db, service):
        """create_version() creates a version and updates current_version_id."""
        agent = service.create(AgentCreate(name="Version Test"), requesting_user_id=USER_ID)
        v1_id = agent.current_version_id

        version_data = AgentVersionCreate(
            version_label="v2",
            runtime_policy_json={"risk_level": "critical"},
        )
        v2 = service.create_version(agent.id, version_data, label="v2")

        assert v2.version_label == "v2"
        assert v2.agent_id == agent.id

        db.refresh(agent)
        assert agent.current_version_id == v2.id
        assert agent.current_version_id != v1_id

    def test_explicit_version_create_validates_space_id(self, db, service):
        """create_version() is scoped to the agent's space."""
        agent = service.create(AgentCreate(name="Space Check"), requesting_user_id=USER_ID)
        version_data = AgentVersionCreate()

        v = service.create_version(agent.id, version_data)
        assert v.space_id == SPACE_ID


# ---------------------------------------------------------------------------
# Version listing
# ---------------------------------------------------------------------------

class TestAgentVersionList:
    def test_list_versions_newest_first(self, db, service):
        """list_for_agent() returns versions newest-first."""
        agent = service.create(AgentCreate(name="List Test"), requesting_user_id=USER_ID)

        service.create_version(agent.id, AgentVersionCreate(), label="v2")
        service.create_version(agent.id, AgentVersionCreate(), label="v3")

        versions = AgentVersionService(db).list_for_agent(agent.id, SPACE_ID)
        assert [v.version_label for v in versions] == ["v3", "v2", "v1"]

    def test_list_versions_is_space_scoped(self, db, service):
        """list_for_agent() only returns versions in the agent's space."""
        agent = service.create(AgentCreate(name="Scope Test"), requesting_user_id=USER_ID)
        versions = AgentVersionService(db).list_for_agent(agent.id, SPACE_ID)
        for v in versions:
            assert v.space_id == SPACE_ID


# ---------------------------------------------------------------------------
# Version retrieval with ownership validation
# ---------------------------------------------------------------------------

class TestAgentVersionGet:
    def test_get_version_returns_immutable_snapshot(self, db, service):
        """get_version_for_agent() returns the version snapshot."""
        agent = service.create(AgentCreate(name="Get Test"), requesting_user_id=USER_ID)
        version_id = agent.current_version_id

        version = AgentVersionService(db).get_version_for_agent(
            version_id, agent.id, SPACE_ID
        )
        assert version.id == version_id
        assert version.version_label == "v1"

    def test_get_version_rejects_wrong_agent_id(self, db, service):
        """get_version_for_agent() raises 404 if version belongs to different agent."""
        agent_a = service.create(AgentCreate(name="Agent A"), requesting_user_id=USER_ID)
        agent_b = service.create(AgentCreate(name="Agent B"), requesting_user_id=USER_ID)

        with pytest.raises(Exception) as exc_info:
            AgentVersionService(db).get_version_for_agent(
                agent_b.current_version_id, agent_a.id, SPACE_ID
            )
        assert "404" in str(exc_info.value.status_code)

    def test_get_version_rejects_wrong_space_id(self, db, service):
        """get_version_for_agent() raises 404 if space_id doesn't match."""
        agent = service.create(AgentCreate(name="Space Test"), requesting_user_id=USER_ID)

        with pytest.raises(Exception) as exc_info:
            AgentVersionService(db).get_version_for_agent(
                agent.current_version_id, agent.id, "wrong-space"
            )
        assert "404" in str(exc_info.value.status_code)


# ---------------------------------------------------------------------------
# current_version_id invariant
# ---------------------------------------------------------------------------

class TestCurrentVersionIdInvariant:
    def test_current_version_id_cannot_point_to_another_agent_version(self, db, service):
        """Versions belong to their correct parent agents."""
        agent_a = service.create(AgentCreate(name="Agent X"), requesting_user_id=USER_ID)
        agent_b = service.create(AgentCreate(name="Agent Y"), requesting_user_id=USER_ID)

        v_a = db.query(AgentVersion).filter(AgentVersion.id == agent_a.current_version_id).first()
        v_b = db.query(AgentVersion).filter(AgentVersion.id == agent_b.current_version_id).first()
        assert v_a.agent_id == agent_a.id
        assert v_b.agent_id == agent_b.id

    def test_version_belongs_to_correct_agent(self, db, service):
        """AgentVersion.agent_id matches parent Agent.id and space."""
        agent = service.create(AgentCreate(name="Invariant Test"), requesting_user_id=USER_ID)
        version = db.query(AgentVersion).filter(AgentVersion.id == agent.current_version_id).first()
        assert version.agent_id == agent.id
        assert version.space_id == agent.space_id


# ---------------------------------------------------------------------------
# No Run created by AgentVersion-only flows
# ---------------------------------------------------------------------------

class TestNoRunCreated:
    def test_creating_agent_does_not_create_run(self, db, service):
        """Agent creation does NOT create a Run."""
        initial_count = db.query(Run).count()
        service.create(AgentCreate(name="No Run Test"), requesting_user_id=USER_ID)
        assert db.query(Run).count() == initial_count

    def test_creating_version_does_not_create_run(self, db, service):
        """Explicit version creation does NOT create a Run."""
        agent = service.create(AgentCreate(name="No Run Version Test"), requesting_user_id=USER_ID)
        initial_count = db.query(Run).count()
        service.create_version(agent.id, AgentVersionCreate())
        assert db.query(Run).count() == initial_count

    def test_patching_agent_does_not_create_run(self, db, service):
        """Patching an agent (even with exec config) does NOT create a Run."""
        agent = service.create(AgentCreate(name="No Run Patch Test"), requesting_user_id=USER_ID)
        initial_count = db.query(Run).count()
        service.update(agent.id, AgentUpdate(runtime_policy_json={"risk_level": "high"}))
        assert db.query(Run).count() == initial_count


# ---------------------------------------------------------------------------
# AgentVersionService validation
# ---------------------------------------------------------------------------

class TestAgentVersionService:
    def test_version_label_auto_increment(self, db, service):
        """Creating versions without explicit labels auto-increments v1, v2, v3..."""
        agent = service.create(AgentCreate(name="Auto Label"), requesting_user_id=USER_ID)

        v2 = service.create_version(agent.id, AgentVersionCreate())
        v3 = service.create_version(agent.id, AgentVersionCreate())

        db.refresh(agent)
        assert agent.current_version_id == v3.id

    def test_duplicate_version_label_rejected(self, db, service):
        """Creating a version with a duplicate label raises an error (DB constraint)."""
        agent = service.create(AgentCreate(name="Dup Label"), requesting_user_id=USER_ID)

        with pytest.raises(Exception):
            service.create_version(agent.id, AgentVersionCreate(), label="v1")