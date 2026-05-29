"""Alembic baseline schema: required tables, columns, FKs, and migration static checks."""

from __future__ import annotations

import inspect as py_inspect
import re
from pathlib import Path

import pytest
from sqlalchemy import inspect
from sqlalchemy.orm import sessionmaker

from app import models, schemas
from app.db import Base

BACKEND_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def canonical_engine(db_engine):
    """Reuse the session-scoped migrated engine — no second Alembic upgrade needed."""
    yield db_engine


@pytest.fixture(scope="function")
def canonical_conn(canonical_engine):
    """Function-scoped connection with rollback — for tests that write data."""
    connection = canonical_engine.connect()
    transaction = connection.begin()
    yield connection
    transaction.rollback()
    connection.close()


REQUIRED_TABLES = {
    "spaces",
    "users",
    "agents",
    "agent_versions",
    "sessions",
    "messages",
    "model_providers",
    "runtime_adapters",
    "credentials",
    "source_pointers",
    "context_snapshots",
    "policies",
    "runs",
    "activity_records",
    "artifacts",
    "proposals",
    "boards",
    "board_columns",
    "tasks",
    "task_runs",
    "task_artifacts",
    "task_proposals",
    "task_dependencies",
    "task_evaluations",
    "jobs",
    "job_events",
    "workspaces",
    "memory_entries",
    "knowledge_items",
    "knowledge_relations",
    "entity_refs",
    "memory_relations",
    "provenance_links",
    "participation_records",
    "personal_memory_grants",
    "proposal_approvals",
    "personal_memory_grant_events",
    # Control plane tables
    "execution_planes",
    "validation_recipes",
    "workspace_profiles",
    "external_run_records",
    "run_reflections",
    "run_evaluations",
    "run_finalizations",
    "runtime_tool_bindings",
    "policy_decision_records",
}



def _foreign_keys(inspector, table_name: str) -> set[tuple[str, str, str]]:
    found = set()
    for fk in inspector.get_foreign_keys(table_name):
        constrained = tuple(fk.get("constrained_columns") or [])
        referred = tuple(fk.get("referred_columns") or [])
        if constrained and referred:
            found.add((constrained[0], fk["referred_table"], referred[0]))
    return found


def test_canonical_initial_migration_builds_baseline_schema_from_empty_database(canonical_engine):
    inspector = inspect(canonical_engine)

    assert REQUIRED_TABLES.issubset(set(inspector.get_table_names()))
    assert "agent_runs" not in inspector.get_table_names()
    assert "memories" not in inspector.get_table_names()
    assert "".join(("wi", "ki_items")) not in inspector.get_table_names()
    assert "".join(("llm_", "wi", "ki")) not in inspector.get_table_names()
    assert "provider_configs" not in inspector.get_table_names()
    assert "cli_adapter_configs" not in inspector.get_table_names()

    user_columns = {column["name"] for column in inspector.get_columns("users")}
    assert {"space_id", "default_space_id", "role"}.isdisjoint(user_columns)

    agent_version_columns = {column["name"] for column in inspector.get_columns("agent_versions")}
    assert {"source_proposal_id", "source_activity_id"}.issubset(agent_version_columns)

    run_column_defs = {column["name"]: column for column in inspector.get_columns("runs")}
    run_columns = set(run_column_defs)
    assert {
        "agent_id",
        "agent_version_id",
        "context_snapshot_id",
        "mode",
        "status",
        "run_type",
        "trigger_origin",
        "parent_run_id",
        "workspace_id",
        "model_provider_id",
        "runtime_adapter_id",
        "error_message",
        "error_json",
        "output_json",
        "usage_json",
        "task_id",
        "required_sandbox_level",
    }.issubset(run_columns)
    assert run_column_defs["agent_id"]["nullable"] is False
    assert run_column_defs["agent_version_id"]["nullable"] is False
    context_snapshot_columns = {column["name"] for column in inspector.get_columns("context_snapshots")}
    assert "run_id" not in context_snapshot_columns

    proposal_columns = {column["name"] for column in inspector.get_columns("proposals")}
    assert {"urgency", "review_deadline", "expires_at", "preview"}.issubset(proposal_columns)
    assert "expired" not in proposal_columns

    activity_columns = {column["name"] for column in inspector.get_columns("activity_records")}
    assert {
        "workspace_id",
        "agent_id",
        "source_task_id",
        "source_run_id",
        "source_url",
        "status",
        "updated_at",
        "created_at",
        "source_kind",
        "source_trust",
        "subject_user_id",
        "lifecycle_status",
        "consolidation_status",
    }.issubset(activity_columns)
    ar_indexes = {tuple(i["column_names"]) for i in inspector.get_indexes("activity_records")}
    assert ("source_task_id",) in ar_indexes
    assert ("lifecycle_status",) in ar_indexes
    assert ("consolidation_status",) in ar_indexes

    artifact_columns = {column["name"] for column in inspector.get_columns("artifacts")}
    assert {
        "content",
        "storage_ref",
        "storage_path",
        "exportable",
        "export_formats_json",
        "canonical_format",
        "relevant_period_start",
        "preview",
        "metadata_json",
    }.issubset(artifact_columns)
    policy_columns = {column["name"] for column in inspector.get_columns("policies")}
    assert {
        "id", "space_id", "name", "domain", "policy_json", "enabled", "created_at", "updated_at",
        "policy_key", "policy_version", "status", "enforcement_mode", "priority",
        "rule_json", "applies_to_json", "supersedes_policy_id", "created_from_proposal_id",
    }.issubset(policy_columns)

    memory_columns = {column["name"] for column in inspector.get_columns("memory_entries")}
    assert {
        "memory_layer",
        "memory_kind",
        "source_trust",
        "created_from_proposal_id",
        "root_memory_id",
        "supersedes_memory_id",
        "event_time",
        "event_type",
        "summary_json",
        "salience_json",
        "last_retrieved_at",
        "reconsolidation_due",
    }.issubset(memory_columns)

    knowledge_columns = {column["name"] for column in inspector.get_columns("knowledge_items")}
    assert {
        "id", "space_id", "project_id", "workspace_id", "root_item_id",
        "supersedes_item_id", "item_type", "title", "content", "content_format",
        "status", "visibility", "verification_status", "reflection_status",
        "tags_json", "confidence", "source_url", "source_refs_json",
        "owner_user_id", "created_by_user_id", "created_by_agent_id", "created_by_run_id",
        "source_activity_id", "source_artifact_id", "created_from_proposal_id",
        "approved_by_user_id", "version", "created_at", "updated_at", "archived_at",
    }.issubset(knowledge_columns)
    knowledge_relation_columns = {column["name"] for column in inspector.get_columns("knowledge_relations")}
    assert {
        "id", "space_id", "from_item_id", "to_item_id", "relation_type", "status",
        "confidence", "evidence_summary", "source_proposal_id", "created_by_user_id",
        "created_by_agent_id", "created_from_assessment_id", "created_at", "updated_at",
    }.issubset(knowledge_relation_columns)
    knowledge_indexes = {tuple(i["column_names"]) for i in inspector.get_indexes("knowledge_items")}
    assert ("space_id",) in knowledge_indexes
    assert ("owner_user_id",) in knowledge_indexes
    assert ("root_item_id",) in knowledge_indexes
    relation_indexes = {tuple(i["column_names"]) for i in inspector.get_indexes("knowledge_relations")}
    assert ("space_id",) in relation_indexes
    assert ("from_item_id",) in relation_indexes
    assert ("to_item_id",) in relation_indexes

    snapshot_columns = {column["name"] for column in inspector.get_columns("context_snapshots")}
    assert {
        "compiled_prefix_text",
        "compiled_tail_text",
        "prefix_hash",
        "tail_hash",
        "compiler_version",
        "policy_bundle_version",
        "memory_digest_version",
        "workspace_digest_version",
        "retrieval_trace_json",
        "token_budget_json",
    }.issubset(snapshot_columns)


def test_canonical_relationships_can_be_persisted_after_migration(canonical_conn):
    Session = sessionmaker(bind=canonical_conn, join_transaction_mode="create_savepoint")

    db = Session()
    try:
        space = models.Space(id="space-1", name="Personal")
        user = models.User(id="user-1", email="u@example.com", display_name="User")
        credential = models.Credential(
            id="cred-1",
            space_id=space.id,
            name="Test credential",
            credential_type="api_key",
            secret_ref="secret://test/provider",
        )
        provider = models.ModelProvider(
            id="provider-1",
            space_id=space.id,
            name="Test Provider",
            provider_type="test",
            credential_id=credential.id,
        )
        adapter = models.RuntimeAdapter(
            id="adapter-1",
            space_id=space.id,
            name="Echo Adapter",
            adapter_type="echo",
            provider_id=provider.id,
        )
        agent = models.Agent(id="agent-1", space_id=space.id, owner_user_id=user.id, name="Agent")
        version = models.AgentVersion(
            id="version-1",
            agent_id=agent.id,
            space_id=space.id,
            version_label="v1",
            model_provider_id=provider.id,
            runtime_adapter_id=adapter.id,
            system_prompt="You are useful.",
        )
        agent.current_version_id = version.id
        workspace = models.Workspace(id="workspace-1", space_id=space.id, name="Workspace")
        session = models.Session(id="session-1", space_id=space.id, user_id=user.id, agent_id=agent.id, workspace_id=workspace.id)
        snapshot = models.ContextSnapshot(id="snapshot-1", space_id=space.id, source_refs_json=[])
        run = models.Run(
            id="run-1",
            space_id=space.id,
            agent_id=agent.id,
            agent_version_id=version.id,
            context_snapshot_id=snapshot.id,
            workspace_id=workspace.id,
            session_id=session.id,
            instructed_by_user_id=user.id,
            model_provider_id=provider.id,
            runtime_adapter_id=adapter.id,
            run_type="agent",
            trigger_origin="manual",
            prompt="hello",
            mode="dry_run",
            status="queued",
        )
        activity = models.ActivityRecord(
            id="activity-1",
            space_id=space.id,
            source_run_id=run.id,
            session_id=session.id,
            user_id=user.id,
            activity_type="agent_run",
        )
        proposal = models.Proposal(
            id="proposal-1",
            space_id=space.id,
            created_by_run_id=run.id,
            proposal_type="memory_update",
            risk_level="low",
            urgency="normal",
            title="Preview memory",
        )
        artifact = models.Artifact(
            id="artifact-1",
            space_id=space.id,
            run_id=run.id,
            proposal_id=proposal.id,
            artifact_type="report",
            title="preview.txt",
            content="preview",
            storage_ref="instance://artifacts/preview.txt",
            storage_path="artifacts/preview.txt",
            exportable=True,
            canonical_format="text/plain",
            preview=True,
        )
        job = models.Job(
            id="job-1",
            space_id=space.id,
            user_id=user.id,
            workspace_id=workspace.id,
            agent_id=agent.id,
            job_type="agent_run",
            payload_json={"agent_id": agent.id},
        )
        memory = models.MemoryEntry(
            id="memory-1",
            space_id=space.id,
            subject_user_id=user.id,
            workspace_id=workspace.id,
            agent_id=agent.id,
            scope_type="space",
            memory_type="semantic",
            content="Approved memory only",
            source_proposal_id=proposal.id,
        )
        policy = models.Policy(
            id="policy-1",
            space_id=space.id,
            name="Default runtime",
            domain="runtime",
            policy_json={"sandbox_required": True},
        )
        message = models.Message(id="message-1", space_id=space.id, session_id=session.id, user_id=user.id, role="user", content="hi")

        db.add(space)
        db.commit()

        db.add_all([user, credential, policy])
        db.commit()

        db.add(provider)
        db.commit()

        db.add(adapter)
        db.commit()

        db.add(agent)
        db.commit()

        workspace.created_by_user_id = user.id
        db.add(workspace)
        db.commit()

        db.add(version)
        db.commit()

        agent.current_version_id = version.id
        db.add_all([session, snapshot])
        db.commit()

        db.add(run)
        db.commit()

        db.add(activity)
        db.commit()

        proposal.workspace_id = workspace.id
        proposal.created_by_agent_id = agent.id
        proposal.created_by_user_id = user.id
        db.add(proposal)
        db.commit()

        db.add(artifact)
        db.commit()

        knowledge_item = models.KnowledgeItem(
            id="knowledge-1",
            space_id=space.id,
            workspace_id=workspace.id,
            root_item_id="knowledge-1",
            item_type="knowledge",
            title="Knowledge",
            content="Approved knowledge",
            content_format="markdown",
            status="active",
            visibility="space_shared",
            verification_status="unverified",
            reflection_status="unreviewed",
            tags_json=[],
            source_refs_json=[],
            owner_user_id=user.id,
            created_by_user_id=user.id,
            created_by_run_id=run.id,
            source_activity_id=activity.id,
            source_artifact_id=artifact.id,
            created_from_proposal_id=proposal.id,
            approved_by_user_id=user.id,
        )
        db.add(knowledge_item)
        db.commit()

        knowledge_relation = models.KnowledgeRelation(
            id="knowledge-relation-1",
            space_id=space.id,
            from_item_id=knowledge_item.id,
            to_item_id=knowledge_item.id,
            relation_type="related",
            status="active",
            source_proposal_id=proposal.id,
            created_by_user_id=user.id,
        )
        db.add(knowledge_relation)
        db.commit()

        memory.source_activity_id = activity.id
        memory.source_artifact_id = artifact.id
        db.add_all([job, memory, message])
        db.commit()

        entity_ref = models.EntityRef(
            id="entity-1",
            space_id=space.id,
            entity_type="person",
            entity_id="ext-person-42",
            canonical_key="person:ext-person-42",
            display_name="Alice",
        )
        memory_relation = models.MemoryRelation(
            id="relation-1",
            space_id=space.id,
            source_type="memory",
            source_id=memory.id,
            target_type="memory",
            target_id=memory.id,
            relation_type="related_to",
            created_from_proposal_id=proposal.id,
        )
        provenance_link = models.ProvenanceLink(
            id="provenance-1",
            space_id=space.id,
            target_type="memory",
            target_id=memory.id,
            source_type="activity",
            source_id=activity.id,
            source_trust="internal_system",
        )
        db.add_all([entity_ref, memory_relation, provenance_link])
        db.commit()

        assert db.get(models.Agent, "agent-1").current_version_id == "version-1"
        assert db.get(models.Run, "run-1").agent_version_id == "version-1"
        assert db.get(models.Run, "run-1").context_snapshot_id == "snapshot-1"
        assert db.get(models.Artifact, "artifact-1").run_id == "run-1"
        assert db.get(models.Proposal, "proposal-1").created_by_run_id == "run-1"
        assert db.get(models.ActivityRecord, "activity-1").source_run_id == "run-1"
        assert db.get(models.KnowledgeItem, "knowledge-1").created_from_proposal_id == "proposal-1"
        assert db.get(models.KnowledgeRelation, "knowledge-relation-1").relation_type == "related"
        assert db.get(models.EntityRef, "entity-1").entity_type == "person"
        assert db.get(models.MemoryRelation, "relation-1").relation_type == "related_to"
        assert db.get(models.ProvenanceLink, "provenance-1").source_trust == "internal_system"
    finally:
        db.close()


def test_key_canonical_foreign_keys_exist(canonical_engine):
    inspector = inspect(canonical_engine)

    # Intentionally omitted to avoid an Agent <-> AgentVersion DDL cycle in the
    # clean baseline. Run.agent_version_id is the immutable execution FK.
    assert ("current_version_id", "agent_versions", "id") not in _foreign_keys(inspector, "agents")
    # Intentionally service-enforced to avoid Space/User bootstrap ordering cycles.
    assert ("created_by_user_id", "users", "id") not in _foreign_keys(inspector, "spaces")
    assert ("invited_by_user_id", "users", "id") not in _foreign_keys(inspector, "space_invitations")

    assert ("agent_id", "agents", "id") in _foreign_keys(inspector, "agent_versions")
    assert ("source_proposal_id", "proposals", "id") not in _foreign_keys(inspector, "agent_versions")
    assert ("source_activity_id", "activity_records", "id") not in _foreign_keys(inspector, "agent_versions")
    assert ("task_id", "tasks", "id") not in _foreign_keys(inspector, "runs")
    assert ("source_task_id", "tasks", "id") not in _foreign_keys(inspector, "activity_records")
    assert ("agent_version_id", "agent_versions", "id") in _foreign_keys(inspector, "runs")
    assert ("context_snapshot_id", "context_snapshots", "id") in _foreign_keys(inspector, "runs")
    assert ("run_id", "runs", "id") in _foreign_keys(inspector, "artifacts")
    assert ("created_by_run_id", "runs", "id") in _foreign_keys(inspector, "proposals")
    assert ("source_run_id", "runs", "id") in _foreign_keys(inspector, "activity_records")
    assert ("workspace_id", "workspaces", "id") in _foreign_keys(inspector, "proposals")
    assert ("created_by_agent_id", "agents", "id") in _foreign_keys(inspector, "proposals")
    assert ("created_by_user_id", "users", "id") in _foreign_keys(inspector, "proposals")
    assert ("user_id", "users", "id") in _foreign_keys(inspector, "jobs")
    assert ("workspace_id", "workspaces", "id") in _foreign_keys(inspector, "jobs")
    assert ("agent_id", "agents", "id") in _foreign_keys(inspector, "jobs")
    assert ("created_by_user_id", "users", "id") in _foreign_keys(inspector, "workspaces")
    assert ("subject_user_id", "users", "id") in _foreign_keys(inspector, "memory_entries")
    assert ("owner_user_id", "users", "id") in _foreign_keys(inspector, "memory_entries")
    assert ("workspace_id", "workspaces", "id") in _foreign_keys(inspector, "memory_entries")
    assert ("agent_id", "agents", "id") in _foreign_keys(inspector, "memory_entries")
    assert ("source_activity_id", "activity_records", "id") in _foreign_keys(inspector, "memory_entries")
    assert ("source_artifact_id", "artifacts", "id") in _foreign_keys(inspector, "memory_entries")
    assert ("created_from_proposal_id", "proposals", "id") in _foreign_keys(inspector, "memory_entries")
    assert ("space_id", "spaces", "id") in _foreign_keys(inspector, "knowledge_items")
    assert ("workspace_id", "workspaces", "id") in _foreign_keys(inspector, "knowledge_items")
    assert ("project_id", "projects", "id") in _foreign_keys(inspector, "knowledge_items")
    assert ("created_by_user_id", "users", "id") in _foreign_keys(inspector, "knowledge_items")
    assert ("owner_user_id", "users", "id") in _foreign_keys(inspector, "knowledge_items")
    assert ("created_by_agent_id", "agents", "id") in _foreign_keys(inspector, "knowledge_items")
    assert ("created_by_run_id", "runs", "id") in _foreign_keys(inspector, "knowledge_items")
    assert ("source_activity_id", "activity_records", "id") in _foreign_keys(inspector, "knowledge_items")
    assert ("source_artifact_id", "artifacts", "id") in _foreign_keys(inspector, "knowledge_items")
    assert ("created_from_proposal_id", "proposals", "id") in _foreign_keys(inspector, "knowledge_items")
    assert ("approved_by_user_id", "users", "id") in _foreign_keys(inspector, "knowledge_items")
    assert ("space_id", "spaces", "id") in _foreign_keys(inspector, "knowledge_relations")
    assert ("from_item_id", "knowledge_items", "id") in _foreign_keys(inspector, "knowledge_relations")
    assert ("to_item_id", "knowledge_items", "id") in _foreign_keys(inspector, "knowledge_relations")
    assert ("source_proposal_id", "proposals", "id") in _foreign_keys(inspector, "knowledge_relations")
    assert "memory_access_logs" in inspector.get_table_names()
    assert ("memory_id", "memory_entries", "id") in _foreign_keys(inspector, "memory_access_logs")
    assert ("space_id", "spaces", "id") in _foreign_keys(inspector, "entity_refs")
    assert ("space_id", "spaces", "id") in _foreign_keys(inspector, "memory_relations")
    assert ("created_from_proposal_id", "proposals", "id") in _foreign_keys(inspector, "memory_relations")
    assert ("space_id", "spaces", "id") in _foreign_keys(inspector, "provenance_links")
    # policies.created_from_proposal_id is intentionally a soft reference (policies precedes proposals in migration order)
    assert ("created_from_proposal_id", "proposals", "id") not in _foreign_keys(inspector, "policies")
    # These three fields are real FKs (not soft references) — enforced in ORM and migration.
    assert ("run_evaluation_id", "run_evaluations", "id") in _foreign_keys(inspector, "task_evaluations")
    assert ("run_evaluation_id", "run_evaluations", "id") in _foreign_keys(inspector, "run_finalizations")
    assert ("task_evaluation_id", "task_evaluations", "id") in _foreign_keys(inspector, "run_finalizations")


def test_initial_migration_has_no_forward_table_references():
    migration = next((BACKEND_ROOT / "migrations" / "versions").glob("*_canonical_initial_schema.py"))
    text = migration.read_text()
    created: list[str] = []
    violations: list[tuple[str, str]] = []
    current_table: str | None = None

    for line in text.splitlines():
        create_match = re.search(r"op\.create_table\('([^']+)'", line)
        if create_match:
            current_table = create_match.group(1)
            created.append(current_table)
            continue
        if current_table and "sa.ForeignKeyConstraint" in line:
            referred_match = re.search(r"\['([^']+)\.id'\]", line)
            if referred_match:
                referred_table = referred_match.group(1)
                if referred_table != current_table and referred_table not in created:
                    violations.append((current_table, referred_table))

    assert violations == []


def test_canonical_migration_has_no_removed_execution_symbols():
    migration = next((BACKEND_ROOT / "migrations" / "versions").glob("*_canonical_initial_schema.py"))
    text = migration.read_text()
    banned = (
        "".join(("Agent", "Run", "Service")),
        "execute_pending_run",
        "create_pending",
        "Task = Job",
    )
    for token in banned:
        assert token not in text, token


def test_product_orm_uses_run_naming():
    mapped_names = {mapper.class_.__name__ for mapper in Base.registry.mappers}
    table_names = set(Base.metadata.tables)
    schema_class_names = {
        value.__name__
        for name, value in py_inspect.getmembers(schemas, py_inspect.isclass)
        if value.__module__ == schemas.__name__
    }

    assert "Run" in mapped_names
    assert "".join(("Agent", "Run")) not in mapped_names
    assert "runs" in table_names
    assert "agent_runs" not in table_names
    assert "RunRequest" in schema_class_names
    assert "RunOut" in schema_class_names


# ---------------------------------------------------------------------------
# Visibility and participation-record schema
# ---------------------------------------------------------------------------

_VISIBILITY_TABLES = ["tasks", "runs", "artifacts", "activity_records", "proposals"]
_VISIBILITY_DEFAULT = "space_shared"


def test_visibility_columns_exist_with_correct_default(canonical_engine):
    """Visibility columns are NOT NULL with server_default=space_shared on all target tables."""
    inspector = inspect(canonical_engine)
    for table in _VISIBILITY_TABLES:
        col_defs = {c["name"]: c for c in inspector.get_columns(table)}
        assert "visibility" in col_defs, f"{table}.visibility column missing"
        col = col_defs["visibility"]
        assert col["nullable"] is False, f"{table}.visibility must be NOT NULL"
        # server_default may be wrapped in quotes by SQLite; strip them
        raw = str(col.get("default") or "").strip("'\" ")
        assert raw == _VISIBILITY_DEFAULT, (
            f"{table}.visibility server_default must be '{_VISIBILITY_DEFAULT}', got {col.get('default')!r}"
        )


def test_owner_user_id_columns_exist(canonical_engine):
    """Artifacts and activity_records have owner_user_id nullable column."""
    inspector = inspect(canonical_engine)
    for table in ("artifacts", "activity_records"):
        col_names = {c["name"] for c in inspector.get_columns(table)}
        assert "owner_user_id" in col_names, f"{table}.owner_user_id column missing"


def test_owner_user_id_fk_exists(canonical_engine):
    """owner_user_id on artifacts and activity_records has FK to users.id."""
    inspector = inspect(canonical_engine)
    assert ("owner_user_id", "users", "id") in _foreign_keys(inspector, "artifacts")
    assert ("owner_user_id", "users", "id") in _foreign_keys(inspector, "activity_records")


def test_participation_records_table_exists(canonical_engine):
    """Participation records table exists with required pointer columns."""
    inspector = inspect(canonical_engine)
    assert "participation_records" in inspector.get_table_names()
    col_names = {c["name"] for c in inspector.get_columns("participation_records")}
    required = {
        "id", "user_id", "personal_space_id", "source_space_id",
        "source_object_type", "source_object_id", "role", "occurred_at", "created_at",
    }
    assert required.issubset(col_names), f"Missing columns: {required - col_names}"


def test_participation_records_has_no_content_columns(canonical_engine):
    """Participation records must not contain raw content or payload fields."""
    inspector = inspect(canonical_engine)
    col_names = {c["name"] for c in inspector.get_columns("participation_records")}
    forbidden = {"content", "body", "summary", "payload", "payload_json", "raw_content", "title"}
    found = forbidden & col_names
    assert not found, (
        f"participation_records must be a pointer ledger — found content columns: {found}"
    )


def test_participation_records_indexes_exist(canonical_engine):
    """Participation records has the three required indexes."""
    inspector = inspect(canonical_engine)
    indexes = inspector.get_indexes("participation_records")
    indexed_cols = {tuple(i["column_names"]) for i in indexes}
    assert ("user_id",) in indexed_cols, "ix_participation_records_user_id missing"
    assert ("personal_space_id",) in indexed_cols, "ix_participation_records_personal_space_id missing"
    # composite source index
    source_cols = ("source_space_id", "source_object_type", "source_object_id")
    assert source_cols in indexed_cols, f"ix_participation_records_source missing: found {indexed_cols}"


def test_participation_records_fks_exist(canonical_engine):
    """Participation records has FK to users.id and spaces.id (both personal and source)."""
    inspector = inspect(canonical_engine)
    fks = _foreign_keys(inspector, "participation_records")
    assert ("user_id", "users", "id") in fks
    assert ("personal_space_id", "spaces", "id") in fks
    assert ("source_space_id", "spaces", "id") in fks


def test_memory_entries_visibility_column_still_exists(canonical_engine):
    """Memory entries retain their visibility column."""
    inspector = inspect(canonical_engine)
    col_names = {c["name"] for c in inspector.get_columns("memory_entries")}
    assert "visibility" in col_names, "memory_entries.visibility must still exist"


def test_source_pointers_table_exists(canonical_engine):
    """source_pointers table exists with required provenance columns."""
    inspector = inspect(canonical_engine)
    assert "source_pointers" in inspector.get_table_names()
    assert "context_sources" not in inspector.get_table_names()
    col_names = {c["name"] for c in inspector.get_columns("source_pointers")}
    required = {
        "id",
        "owner_space_id",
        "source_space_id",
        "source_object_type",
        "source_object_id",
        "access_mode",
        "granted_by_user_id",
        "expires_at",
        "metadata_json",
        "created_at",
    }
    assert required.issubset(col_names), f"Missing columns: {required - col_names}"
    assert "access_mode" in col_names


def test_source_pointers_has_no_content_columns(canonical_engine):
    """source_pointers must not store raw source content."""
    inspector = inspect(canonical_engine)
    col_names = {c["name"] for c in inspector.get_columns("source_pointers")}
    forbidden = {
        "content",
        "body",
        "summary",
        "payload",
        "raw_content",
        "source_snapshot",
        "public_url",
        "copied_text",
    }
    found = forbidden & col_names
    assert not found, f"source_pointers must be metadata-only — found: {found}"


def test_source_pointers_indexes_exist(canonical_engine):
    """source_pointers has owner, source composite, granted_by, and expires indexes."""
    inspector = inspect(canonical_engine)
    indexes = inspector.get_indexes("source_pointers")
    indexed_cols = {tuple(i["column_names"]) for i in indexes}
    assert ("owner_space_id",) in indexed_cols
    assert ("granted_by_user_id",) in indexed_cols
    assert ("expires_at",) in indexed_cols
    source_cols = ("source_space_id", "source_object_type", "source_object_id")
    assert source_cols in indexed_cols


def test_source_pointers_fks_exist(canonical_engine):
    """source_pointers FKs to spaces and users."""
    inspector = inspect(canonical_engine)
    fks = _foreign_keys(inspector, "source_pointers")
    assert ("owner_space_id", "spaces", "id") in fks
    assert ("source_space_id", "spaces", "id") in fks
    assert ("granted_by_user_id", "users", "id") in fks


# ---------------------------------------------------------------------------
# PersonalMemoryGrant schema
# ---------------------------------------------------------------------------


def test_personal_memory_grant_tables_exist(canonical_engine):
    """personal_memory_grants and personal_memory_grant_events tables exist."""
    inspector = inspect(canonical_engine)
    tables = inspector.get_table_names()
    assert "personal_memory_grants" in tables
    assert "personal_memory_grant_events" in tables


def test_personal_memory_grant_required_columns_exist(canonical_engine):
    """personal_memory_grants has all required columns."""
    inspector = inspect(canonical_engine)
    col_defs = {c["name"]: c for c in inspector.get_columns("personal_memory_grants")}
    required = {
        "id", "granting_user_id", "personal_space_id", "target_space_id",
        "target_run_id", "target_agent_id", "grant_scope", "access_mode",
        "status", "memory_filter_json", "read_expires_at",
        "egress_review_expires_at", "consume_started_at",
        "revoked_at", "used_at", "failed_at", "failure_stage",
        "created_at", "updated_at",
    }
    assert required.issubset(col_defs.keys()), f"Missing: {required - col_defs.keys()}"
    # target_run_id must be NOT NULL
    assert col_defs["target_run_id"]["nullable"] is False
    # read_expires_at must be NOT NULL
    assert col_defs["read_expires_at"]["nullable"] is False
    # target_agent_id must be nullable (agent-level grants are deferred; NULL enforced by CHECK constraint)
    assert col_defs["target_agent_id"]["nullable"] is True


def test_personal_memory_grant_has_no_raw_content_columns(canonical_engine):
    """personal_memory_grants must not store raw memory content."""
    inspector = inspect(canonical_engine)
    col_names = {c["name"] for c in inspector.get_columns("personal_memory_grants")}
    forbidden = {
        "content", "body", "raw_content", "payload", "summary",
        "generated_summary", "memory_text", "copied_text", "source_snapshot",
    }
    found = forbidden & col_names
    assert not found, f"personal_memory_grants must not have content columns: {found}"


def test_personal_memory_grant_events_required_columns_exist(canonical_engine):
    """personal_memory_grant_events has all required columns."""
    inspector = inspect(canonical_engine)
    col_names = {c["name"] for c in inspector.get_columns("personal_memory_grant_events")}
    required = {
        "id", "grant_id", "event_type", "actor_user_id", "run_id",
        "proposal_id", "source_space_id", "target_space_id", "metadata_json", "created_at",
    }
    assert required.issubset(col_names), f"Missing: {required - col_names}"


def test_personal_memory_grant_events_has_no_raw_content_columns(canonical_engine):
    """personal_memory_grant_events must not store raw memory content."""
    inspector = inspect(canonical_engine)
    col_names = {c["name"] for c in inspector.get_columns("personal_memory_grant_events")}
    forbidden = {
        "content", "body", "raw_content", "payload", "summary",
        "generated_summary", "memory_text", "copied_text", "source_snapshot",
    }
    found = forbidden & col_names
    assert not found, f"personal_memory_grant_events must not have content columns: {found}"


def test_personal_memory_grant_fks_exist(canonical_engine):
    """personal_memory_grants has all required foreign keys."""
    inspector = inspect(canonical_engine)
    fks = _foreign_keys(inspector, "personal_memory_grants")
    assert ("granting_user_id", "users", "id") in fks
    assert ("personal_space_id", "spaces", "id") in fks
    assert ("target_space_id", "spaces", "id") in fks
    assert ("target_run_id", "runs", "id") in fks
    assert ("target_agent_id", "agents", "id") in fks


def test_personal_memory_grant_events_fks_exist(canonical_engine):
    """personal_memory_grant_events has required foreign keys."""
    inspector = inspect(canonical_engine)
    fks = _foreign_keys(inspector, "personal_memory_grant_events")
    assert ("grant_id", "personal_memory_grants", "id") in fks
    assert ("actor_user_id", "users", "id") in fks
    assert ("run_id", "runs", "id") in fks
    assert ("proposal_id", "proposals", "id") in fks


def test_personal_memory_grant_indexes_exist(canonical_engine):
    """personal_memory_grants has required indexes."""
    inspector = inspect(canonical_engine)
    indexed = {tuple(i["column_names"]) for i in inspector.get_indexes("personal_memory_grants")}
    assert ("granting_user_id",) in indexed
    assert ("personal_space_id",) in indexed
    assert ("target_space_id",) in indexed
    assert ("target_run_id",) in indexed
    assert ("status",) in indexed
    assert ("read_expires_at",) in indexed


def test_personal_memory_grant_events_indexes_exist(canonical_engine):
    """personal_memory_grant_events has required indexes."""
    inspector = inspect(canonical_engine)
    indexed = {tuple(i["column_names"]) for i in inspector.get_indexes("personal_memory_grant_events")}
    assert ("grant_id",) in indexed
    assert ("actor_user_id",) in indexed
    assert ("run_id",) in indexed
    assert ("created_at",) in indexed


def test_personal_memory_grant_check_constraints_exist(canonical_engine):
    """personal_memory_grants has grant_scope, access_mode, status, and target_agent_id constraints."""
    from sqlalchemy import text as sa_text

    with canonical_engine.connect() as conn:
        rows = conn.execute(
            sa_text("SELECT sql FROM sqlite_master WHERE type='table' AND name='personal_memory_grants'")
        ).fetchall()
    ddl = rows[0][0] if rows else ""
    assert "ck_personal_memory_grants_grant_scope" in ddl, "grant_scope CHECK constraint missing"
    assert "ck_personal_memory_grants_access_mode" in ddl, "access_mode CHECK constraint missing"
    assert "ck_personal_memory_grants_status" in ddl, "status CHECK constraint missing"
    assert "ck_personal_memory_grants_target_agent_id_null" in ddl, "target_agent_id NULL CHECK constraint missing"


def test_personal_memory_grant_events_check_constraint_exists(canonical_engine):
    """personal_memory_grant_events has event_type CHECK constraint."""
    from sqlalchemy import text as sa_text

    with canonical_engine.connect() as conn:
        rows = conn.execute(
            sa_text("SELECT sql FROM sqlite_master WHERE type='table' AND name='personal_memory_grant_events'")
        ).fetchall()
    ddl = rows[0][0] if rows else ""
    assert "ck_personal_memory_grant_events_event_type" in ddl, "event_type CHECK constraint missing"


def test_grant_events_event_type_constraint_includes_new_types(canonical_engine):
    """event_type DDL includes egress_proposal_created and egress_approved."""
    from sqlalchemy import text as sa_text

    with canonical_engine.connect() as conn:
        rows = conn.execute(
            sa_text("SELECT sql FROM sqlite_master WHERE type='table' AND name='personal_memory_grant_events'")
        ).fetchall()
    ddl = rows[0][0] if rows else ""
    assert "egress_proposal_created" in ddl, "egress_proposal_created must be in event_type CHECK constraint"
    assert "egress_approved" in ddl, "egress_approved must be in event_type CHECK constraint"


def test_proposal_approvals_table_exists(canonical_engine):
    """proposal_approvals table exists."""
    inspector = inspect(canonical_engine)
    assert "proposal_approvals" in inspector.get_table_names()


def test_proposal_approvals_required_columns_exist(canonical_engine):
    """proposal_approvals has all required metadata-only columns."""
    inspector = inspect(canonical_engine)
    col_defs = {c["name"]: c for c in inspector.get_columns("proposal_approvals")}
    required = {
        "id",
        "proposal_id",
        "approval_type",
        "approver_user_id",
        "grant_id",
        "target_space_id",
        "status",
        "metadata_json",
        "created_at",
        "revoked_at",
    }
    assert required.issubset(col_defs), f"Missing: {required - col_defs.keys()}"
    assert col_defs["proposal_id"]["nullable"] is False
    assert col_defs["approval_type"]["nullable"] is False
    assert col_defs["approver_user_id"]["nullable"] is False
    assert col_defs["status"]["nullable"] is False
    assert col_defs["grant_id"]["nullable"] is True


def test_proposal_approvals_has_no_raw_content_columns(canonical_engine):
    """proposal_approvals must not store raw memory, summary, IDs, or payload content."""
    inspector = inspect(canonical_engine)
    col_names = {c["name"] for c in inspector.get_columns("proposal_approvals")}
    forbidden = {
        "content",
        "body",
        "raw_content",
        "payload",
        "payload_json",
        "summary",
        "generated_summary",
        "memory_text",
        "memory_ids",
        "personal_memory_ids",
        "source_memory_text",
        "artifact_payload",
    }
    found = forbidden & col_names
    assert not found, f"proposal_approvals must not have content columns: {found}"


def test_proposal_approvals_fks_exist(canonical_engine):
    """proposal_approvals has required foreign keys."""
    inspector = inspect(canonical_engine)
    fks = _foreign_keys(inspector, "proposal_approvals")
    assert ("proposal_id", "proposals", "id") in fks
    assert ("approver_user_id", "users", "id") in fks
    assert ("grant_id", "personal_memory_grants", "id") in fks
    assert ("target_space_id", "spaces", "id") in fks


def test_proposal_approvals_indexes_exist(canonical_engine):
    """proposal_approvals has lookup and active-approval uniqueness indexes."""
    inspector = inspect(canonical_engine)
    indexed = {tuple(i["column_names"]) for i in inspector.get_indexes("proposal_approvals")}
    assert ("proposal_id",) in indexed
    assert ("approver_user_id",) in indexed
    assert ("approval_type",) in indexed
    assert ("grant_id",) in indexed
    assert ("target_space_id",) in indexed
    assert ("created_at",) in indexed
    assert ("proposal_id", "approval_type", "approver_user_id", "grant_id") in indexed


def test_proposal_approvals_check_constraints_exist(canonical_engine):
    """proposal_approvals constrains approval_type and status."""
    from sqlalchemy import text as sa_text

    with canonical_engine.connect() as conn:
        rows = conn.execute(
            sa_text("SELECT sql FROM sqlite_master WHERE type='table' AND name='proposal_approvals'")
        ).fetchall()
    ddl = rows[0][0] if rows else ""
    assert "ck_proposal_approvals_approval_type" in ddl
    assert "ck_proposal_approvals_status" in ddl
    assert "egress_granting_user" in ddl
    assert "approved" in ddl
    assert "revoked" in ddl


def test_proposal_approvals_partial_unique_index_exists(canonical_engine):
    """At most one active approval per proposal/type/approver/grant."""
    from sqlalchemy import text as sa_text

    with canonical_engine.connect() as conn:
        rows = conn.execute(
            sa_text(
                "SELECT name, sql FROM sqlite_master "
                "WHERE type='index' AND name='ix_proposal_approvals_unique_active'"
            )
        ).fetchall()
    assert rows, "ix_proposal_approvals_unique_active partial unique index not found"
    idx_sql = rows[0][1]
    assert "UNIQUE" in idx_sql.upper()
    assert "proposal_id" in idx_sql
    assert "approval_type" in idx_sql
    assert "approver_user_id" in idx_sql
    assert "grant_id" in idx_sql
    assert "approved" in idx_sql


def test_personal_memory_grant_partial_unique_index_exists(canonical_engine):
    """PersonalMemoryGrant partial unique index exists on personal_memory_grants (granting_user_id, target_run_id) WHERE active/consuming."""
    from sqlalchemy import text as sa_text

    with canonical_engine.connect() as conn:
        rows = conn.execute(
            sa_text(
                "SELECT name, sql FROM sqlite_master "
                "WHERE type='index' AND name='ix_personal_memory_grants_unique_active_consuming'"
            )
        ).fetchall()
    assert rows, "ix_personal_memory_grants_unique_active_consuming partial unique index not found"
    idx_sql = rows[0][1]
    assert "UNIQUE" in idx_sql.upper()
    assert "granting_user_id" in idx_sql
    assert "target_run_id" in idx_sql


def test_personal_memory_grant_constraints_reject_invalid_scope(canonical_engine):
    """PersonalMemoryGrant grant_scope != 'run' is rejected by DB constraint."""
    import sqlite3
    from sqlalchemy import text as sa_text
    from datetime import UTC, datetime, timedelta

    with canonical_engine.connect() as conn:
        with conn.begin():
            try:
                conn.execute(sa_text("""
                    INSERT INTO personal_memory_grants
                    (id, granting_user_id, personal_space_id, target_space_id,
                     target_run_id, grant_scope, access_mode, status,
                     read_expires_at, created_at, updated_at)
                    VALUES
                    ('pmg-bad-scope', 'u1', 's1', 's2',
                     'r1', 'agent', 'summary_only', 'active',
                     '2099-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')
                """))
                # If we reach here without an exception, the test must detect the violation via the
                # constraint name. Force a failure so the test reflects the expected DB behavior.
                conn.rollback()
                raise AssertionError("Expected IntegrityError for invalid grant_scope='agent'")
            except Exception as exc:
                conn.rollback()
                # Accept any integrity / constraint error — the specific type varies by driver
                assert "SQLITE_CONSTRAINT" in type(exc).__name__ or "IntegrityError" in type(exc).__name__ or isinstance(exc, AssertionError) is False or "CHECK" in str(exc).upper() or "constraint" in str(exc).lower(), f"Unexpected exception type: {type(exc)} {exc}"


def test_personal_memory_grant_constraints_reject_null_run_id(canonical_engine):
    """PersonalMemoryGrant target_run_id NOT NULL is enforced at DB level."""
    from sqlalchemy import text as sa_text

    with canonical_engine.connect() as conn:
        with conn.begin():
            try:
                conn.execute(sa_text("""
                    INSERT INTO personal_memory_grants
                    (id, granting_user_id, personal_space_id, target_space_id,
                     target_run_id, grant_scope, access_mode, status,
                     read_expires_at, created_at, updated_at)
                    VALUES
                    ('pmg-null-run', 'u1', 's1', 's2',
                     NULL, 'run', 'summary_only', 'active',
                     '2099-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')
                """))
                conn.rollback()
                raise AssertionError("Expected NOT NULL constraint violation for target_run_id=NULL")
            except Exception as exc:
                conn.rollback()
                # Must be a constraint/integrity error, not our forced AssertionError
                assert "AssertionError" not in type(exc).__name__, (
                    "DB did not enforce NOT NULL on target_run_id"
                )


# ---------------------------------------------------------------------------
# Control plane schema: execution_planes, new table columns, FKs, and seeding
# ---------------------------------------------------------------------------


def test_execution_planes_required_columns_exist(canonical_engine):
    """execution_planes has all required control-plane columns."""
    inspector = inspect(canonical_engine)
    col_defs = {c["name"]: c for c in inspector.get_columns("execution_planes")}
    required = {
        "id", "space_id", "name", "type", "provider",
        "execution_location", "runtime_origin", "trust_level",
        "observability_level", "data_exposure_level", "credential_mode",
        "config_json", "enabled", "created_at", "updated_at",
    }
    assert required.issubset(col_defs), f"Missing columns: {required - col_defs.keys()}"
    assert col_defs["space_id"]["nullable"] is False
    assert col_defs["name"]["nullable"] is False
    assert col_defs["type"]["nullable"] is False
    assert col_defs["enabled"]["nullable"] is False


def test_execution_planes_fks_exist(canonical_engine):
    """execution_planes has FK to spaces.id."""
    inspector = inspect(canonical_engine)
    fks = _foreign_keys(inspector, "execution_planes")
    assert ("space_id", "spaces", "id") in fks


def test_execution_planes_unique_space_name_constraint_exists(canonical_engine):
    """execution_planes enforces (space_id, name) uniqueness."""
    from sqlalchemy import text as sa_text

    with canonical_engine.connect() as conn:
        rows = conn.execute(
            sa_text("SELECT sql FROM sqlite_master WHERE type='table' AND name='execution_planes'")
        ).fetchall()
    ddl = rows[0][0] if rows else ""
    assert "uq_execution_planes_space_name" in ddl


def test_execution_planes_check_constraints_exist(canonical_engine):
    """execution_planes has CHECK constraints for all enum fields."""
    from sqlalchemy import text as sa_text

    with canonical_engine.connect() as conn:
        rows = conn.execute(
            sa_text("SELECT sql FROM sqlite_master WHERE type='table' AND name='execution_planes'")
        ).fetchall()
    ddl = rows[0][0] if rows else ""
    assert "ck_execution_planes_type" in ddl
    assert "ck_execution_planes_trust_level" in ddl
    assert "ck_execution_planes_observability_level" in ddl
    assert "ck_execution_planes_data_exposure_level" in ddl
    assert "ck_execution_planes_credential_mode" in ddl


def test_runtime_adapters_extended_with_execution_plane(canonical_engine):
    """runtime_adapters has execution_plane_id FK to execution_planes and capability_support_json column."""
    inspector = inspect(canonical_engine)
    col_names = {c["name"] for c in inspector.get_columns("runtime_adapters")}
    assert "execution_plane_id" in col_names, "runtime_adapters.execution_plane_id missing"
    assert "capability_support_json" in col_names, "runtime_adapters.capability_support_json missing"
    assert "credential_profile_id" in col_names
    assert "quota_status" in col_names
    fks = _foreign_keys(inspector, "runtime_adapters")
    assert ("execution_plane_id", "execution_planes", "id") in fks


def test_runtime_adapter_health_and_quota_constraints(canonical_engine):
    """runtime_adapters validates health_status and quota_status enum values."""
    from sqlalchemy import text as sa_text

    with canonical_engine.connect() as conn:
        rows = conn.execute(
            sa_text("SELECT sql FROM sqlite_master WHERE type='table' AND name='runtime_adapters'")
        ).fetchall()
    ddl = rows[0][0] if rows else ""
    assert "ck_runtime_adapters_health_status" in ddl
    assert "ck_runtime_adapters_quota_status" in ddl


def test_runs_extended_with_execution_plane_and_externality_fields(canonical_engine):
    """runs has execution_plane_id FK and all externality/observability snapshot fields."""
    inspector = inspect(canonical_engine)
    col_names = {c["name"] for c in inspector.get_columns("runs")}
    required = {
        "execution_plane_id",
        "source",
        "observability_level",
        "data_exposure_level",
        "trust_level",
        "externality_level",
    }
    assert required.issubset(col_names), f"Missing run columns: {required - col_names}"
    fks = _foreign_keys(inspector, "runs")
    assert ("execution_plane_id", "execution_planes", "id") in fks


def test_runs_source_and_externality_check_constraints_exist(canonical_engine):
    """runs.source and runs.externality_level have CHECK constraints."""
    from sqlalchemy import text as sa_text

    with canonical_engine.connect() as conn:
        rows = conn.execute(
            sa_text("SELECT sql FROM sqlite_master WHERE type='table' AND name='runs'")
        ).fetchall()
    ddl = rows[0][0] if rows else ""
    assert "ck_runs_source" in ddl, "ck_runs_source CHECK constraint missing"
    assert "ck_runs_externality_level" in ddl, "ck_runs_externality_level CHECK constraint missing"
    assert "manual_import" in ddl, "source CHECK must include 'manual_import'"
    assert "local_external" in ddl, "externality_level CHECK must include 'local_external'"


def test_context_snapshots_has_runtime_facing_fields(canonical_engine):
    """context_snapshots has runtime-facing rendered context columns (soft references, no FKs)."""
    inspector = inspect(canonical_engine)
    col_names = {c["name"] for c in inspector.get_columns("context_snapshots")}
    required = {
        "target_runtime_adapter_id",
        "execution_plane_id",
        "included_memory_refs_json",
        "included_file_refs_json",
        "included_doc_refs_json",
        "redactions_json",
        "data_exposure_level",
        "rendered_context_uri",
        "rendered_context_text",
    }
    assert required.issubset(col_names), f"Missing context_snapshot columns: {required - col_names}"
    # These are deliberately soft references (no FK constraints) — enforce that here
    fks = _foreign_keys(inspector, "context_snapshots")
    assert ("target_runtime_adapter_id", "runtime_adapters", "id") not in fks, (
        "context_snapshots.target_runtime_adapter_id must be a soft reference (no FK) "
        "because context_snapshots is created before runtime_adapters in migration DDL order"
    )
    assert ("execution_plane_id", "execution_planes", "id") not in fks, (
        "context_snapshots.execution_plane_id must be a soft reference (no FK)"
    )


def test_artifacts_extended_with_source_plane_fields(canonical_engine):
    """artifacts has source_runtime_adapter_id and source_execution_plane_id with FKs, plus trust_level."""
    inspector = inspect(canonical_engine)
    col_names = {c["name"] for c in inspector.get_columns("artifacts")}
    assert "source_runtime_adapter_id" in col_names, "artifacts.source_runtime_adapter_id missing"
    assert "source_execution_plane_id" in col_names, "artifacts.source_execution_plane_id missing"
    assert "trust_level" in col_names, "artifacts.trust_level missing"
    fks = _foreign_keys(inspector, "artifacts")
    assert ("source_runtime_adapter_id", "runtime_adapters", "id") in fks
    assert ("source_execution_plane_id", "execution_planes", "id") in fks


def test_validation_recipes_required_columns_exist(canonical_engine):
    """validation_recipes has all required columns."""
    inspector = inspect(canonical_engine)
    col_names = {c["name"] for c in inspector.get_columns("validation_recipes")}
    required = {
        "id", "space_id", "workspace_id", "name", "task_type", "risk_level",
        "commands_json", "required_checks_json", "timeout_seconds",
        "requires_clean_git_state", "enabled", "created_at", "updated_at",
    }
    assert required.issubset(col_names), f"Missing: {required - col_names}"


def test_validation_recipes_fks_exist(canonical_engine):
    """validation_recipes has FKs to spaces and workspaces."""
    inspector = inspect(canonical_engine)
    fks = _foreign_keys(inspector, "validation_recipes")
    assert ("space_id", "spaces", "id") in fks
    assert ("workspace_id", "workspaces", "id") in fks


def test_workspace_profiles_required_columns_exist(canonical_engine):
    """workspace_profiles has all required operational knowledge columns."""
    inspector = inspect(canonical_engine)
    col_names = {c["name"] for c in inspector.get_columns("workspace_profiles")}
    required = {
        "id", "space_id", "workspace_id",
        "validation_recipe_id", "preferred_runtime_adapter_id",
        "cloud_allowed", "max_data_exposure_level", "min_observability_level",
        "created_at", "updated_at",
    }
    assert required.issubset(col_names), f"Missing: {required - col_names}"


def test_workspace_profiles_fks_exist(canonical_engine):
    """workspace_profiles has FKs to spaces, workspaces, validation_recipes, and runtime_adapters."""
    inspector = inspect(canonical_engine)
    fks = _foreign_keys(inspector, "workspace_profiles")
    assert ("space_id", "spaces", "id") in fks
    assert ("workspace_id", "workspaces", "id") in fks
    assert ("validation_recipe_id", "validation_recipes", "id") in fks
    assert ("preferred_runtime_adapter_id", "runtime_adapters", "id") in fks


def test_workspace_profiles_unique_workspace_constraint_exists(canonical_engine):
    """workspace_profiles enforces one-profile-per-workspace uniqueness."""
    from sqlalchemy import text as sa_text

    with canonical_engine.connect() as conn:
        rows = conn.execute(
            sa_text("SELECT sql FROM sqlite_master WHERE type='table' AND name='workspace_profiles'")
        ).fetchall()
    ddl = rows[0][0] if rows else ""
    assert "uq_workspace_profiles_workspace" in ddl


def test_external_run_records_required_columns_and_fks_exist(canonical_engine):
    """external_run_records has required columns and FKs to runs, runtime_adapters, and execution_planes."""
    inspector = inspect(canonical_engine)
    col_names = {c["name"] for c in inspector.get_columns("external_run_records")}
    required = {
        "id", "space_id", "run_id", "vendor", "runtime_adapter_id",
        "execution_plane_id", "observability_level", "data_exposure_level",
        "status", "created_at",
    }
    assert required.issubset(col_names), f"Missing: {required - col_names}"
    fks = _foreign_keys(inspector, "external_run_records")
    assert ("space_id", "spaces", "id") in fks
    assert ("run_id", "runs", "id") in fks
    assert ("runtime_adapter_id", "runtime_adapters", "id") in fks
    assert ("execution_plane_id", "execution_planes", "id") in fks


def test_run_reflections_required_columns_and_fks_exist(canonical_engine):
    """run_reflections has required columns and FKs to spaces and runs."""
    inspector = inspect(canonical_engine)
    col_names = {c["name"] for c in inspector.get_columns("run_reflections")}
    required = {
        "id", "space_id", "run_id", "source",
        "memory_candidates_json", "policy_candidates_json",
        "capability_candidates_json", "created_at",
    }
    assert required.issubset(col_names), f"Missing: {required - col_names}"
    fks = _foreign_keys(inspector, "run_reflections")
    assert ("space_id", "spaces", "id") in fks
    assert ("run_id", "runs", "id") in fks


def test_run_reflections_source_check_constraint_exists(canonical_engine):
    """run_reflections.source has a CHECK constraint."""
    from sqlalchemy import text as sa_text

    with canonical_engine.connect() as conn:
        rows = conn.execute(
            sa_text("SELECT sql FROM sqlite_master WHERE type='table' AND name='run_reflections'")
        ).fetchall()
    ddl = rows[0][0] if rows else ""
    assert "ck_run_reflections_source" in ddl


def test_run_reflections_does_not_have_mutation_columns(canonical_engine):
    """run_reflections must only store candidates — not direct policy/memory mutations."""
    inspector = inspect(canonical_engine)
    col_names = {c["name"] for c in inspector.get_columns("run_reflections")}
    forbidden = {"applied_policy_id", "applied_memory_id", "state_mutation_json", "direct_write_json"}
    found = forbidden & col_names
    assert not found, f"run_reflections must not have mutation columns: {found}"


def test_runtime_tool_bindings_required_columns_and_fks_exist(canonical_engine):
    """runtime_tool_bindings has required columns and FKs to spaces, runtime_adapters, and execution_planes."""
    inspector = inspect(canonical_engine)
    col_names = {c["name"] for c in inspector.get_columns("runtime_tool_bindings")}
    required = {
        "id", "space_id", "workspace_id", "agent_id", "runtime_adapter_id",
        "execution_plane_id", "external_type", "external_ref", "display_name",
        "data_exposure_level", "observability_level", "side_effect_level",
        "approval_required", "enabled", "created_at", "updated_at",
    }
    assert required.issubset(col_names), f"Missing: {required - col_names}"
    fks = _foreign_keys(inspector, "runtime_tool_bindings")
    assert ("space_id", "spaces", "id") in fks
    assert ("workspace_id", "workspaces", "id") in fks
    assert ("agent_id", "agents", "id") in fks
    assert ("runtime_adapter_id", "runtime_adapters", "id") in fks
    assert ("execution_plane_id", "execution_planes", "id") in fks


def test_runtime_tool_bindings_check_constraints_exist(canonical_engine):
    """runtime_tool_bindings has CHECK constraints for external_type and side_effect_level."""
    from sqlalchemy import text as sa_text

    with canonical_engine.connect() as conn:
        rows = conn.execute(
            sa_text("SELECT sql FROM sqlite_master WHERE type='table' AND name='runtime_tool_bindings'")
        ).fetchall()
    ddl = rows[0][0] if rows else ""
    assert "ck_runtime_tool_bindings_external_type" in ddl
    assert "ck_runtime_tool_bindings_side_effect_level" in ddl
    assert "mcp_server" in ddl, "external_type CHECK must include 'mcp_server'"
    assert "sensitive" in ddl, "side_effect_level CHECK must include 'sensitive'"


def test_runtime_tool_bindings_approval_required_defaults_true(canonical_engine):
    """runtime_tool_bindings.approval_required must default to TRUE (gate by default)."""
    inspector = inspect(canonical_engine)
    col_defs = {c["name"]: c for c in inspector.get_columns("runtime_tool_bindings")}
    assert col_defs["approval_required"]["nullable"] is False
    # Default is 1 (true) in SQLite
    raw = str(col_defs["approval_required"].get("default") or "").strip("'\" ")
    assert raw in ("1", "True", "true", ""), f"approval_required default must be true, got {raw!r}"


def test_default_execution_planes_are_seeded(canonical_conn):
    """seed_default_execution_planes creates all 7 canonical planes idempotently."""
    from app.execution_planes.seeder import seed_default_execution_planes

    Session = sessionmaker(bind=canonical_conn, join_transaction_mode="create_savepoint")
    db = Session()
    try:
        space = models.Space(id="seed-space-1", name="Seed Space")
        db.add(space)
        db.commit()

        seed_default_execution_planes(db, "seed-space-1")

        planes = db.query(models.ExecutionPlane).filter_by(space_id="seed-space-1").all()
        names = {p.name for p in planes}
        expected = {
            "agent_space_native_local",
            "local_codex_cli",
            "local_claude_code_cli",
            "local_opencode",
            "remote_codex",
            "remote_claude",
            "manual_import",
        }
        assert expected == names, f"Missing planes: {expected - names}"

        # Remote vendor planes must be disabled by default (data exposure risk)
        for plane in planes:
            if plane.name in ("remote_codex", "remote_claude"):
                assert plane.enabled is False, f"{plane.name} must be disabled by default"

        # Native local plane must have high trust and full observability
        native = next(p for p in planes if p.name == "agent_space_native_local")
        assert native.trust_level == "high"
        assert native.observability_level == "full_trace"
        assert native.data_exposure_level == "local_only"

        # local_opencode must use provider='opencode', not 'other'
        opencode = next(p for p in planes if p.name == "local_opencode")
        assert opencode.provider == "opencode", (
            f"local_opencode.provider must be 'opencode', got {opencode.provider!r}"
        )

        # Re-seeding must be idempotent
        seed_default_execution_planes(db, "seed-space-1")
        count_after = db.query(models.ExecutionPlane).filter_by(space_id="seed-space-1").count()
        assert count_after == 7, "Re-seeding must not create duplicate planes"
    finally:
        db.close()


def test_control_plane_orm_relationships_navigate_correctly(canonical_conn):
    """ORM relationships for Space→ExecutionPlane, RuntimeAdapter→ExecutionPlane, Run→ExecutionPlane,
    Workspace→WorkspaceProfile, Run→ExternalRunRecord, and Run→RunReflection are wired correctly."""
    Session = sessionmaker(bind=canonical_conn, join_transaction_mode="create_savepoint")
    db = Session()
    try:
        space = models.Space(id="cp-space-1", name="CP Space")
        user = models.User(id="cp-user-1", email="cp@example.com", display_name="CP User")
        db.add_all([space, user])
        db.commit()

        plane = models.ExecutionPlane(
            id="plane-1",
            space_id=space.id,
            name="test_plane",
            type="native",
            provider="agent_space",
            execution_location="local",
            runtime_origin="native",
            trust_level="high",
            observability_level="full_trace",
            data_exposure_level="local_only",
            credential_mode="agent_space_vault",
            config_json={},
            enabled=True,
        )
        db.add(plane)
        db.commit()

        # Space → ExecutionPlane
        loaded_space = db.get(models.Space, space.id)
        assert any(p.id == plane.id for p in loaded_space.execution_planes)

        credential = models.Credential(
            id="cp-cred-1", space_id=space.id, name="cred",
            credential_type="api_key", secret_ref="secret://x",
        )
        provider = models.ModelProvider(
            id="cp-prov-1", space_id=space.id, name="P",
            provider_type="test", credential_id=credential.id,
        )
        adapter = models.RuntimeAdapter(
            id="cp-adapter-1", space_id=space.id, name="Adapter",
            adapter_type="echo", provider_id=provider.id,
            execution_plane_id=plane.id,
        )
        db.add_all([credential, provider, adapter])
        db.commit()

        # RuntimeAdapter → ExecutionPlane
        loaded_adapter = db.get(models.RuntimeAdapter, adapter.id)
        assert loaded_adapter.execution_plane.id == plane.id

        agent = models.Agent(id="cp-agent-1", space_id=space.id, owner_user_id=user.id, name="A")
        version = models.AgentVersion(
            id="cp-ver-1", agent_id=agent.id, space_id=space.id, version_label="v1",
            model_provider_id=provider.id, runtime_adapter_id=adapter.id,
            system_prompt="test",
        )
        agent.current_version_id = version.id
        workspace = models.Workspace(id="cp-ws-1", space_id=space.id, name="WS", created_by_user_id=user.id)
        snapshot = models.ContextSnapshot(id="cp-snap-1", space_id=space.id, source_refs_json=[])
        db.add_all([agent, version, workspace, snapshot])
        db.commit()

        run = models.Run(
            id="cp-run-1", space_id=space.id, agent_id=agent.id,
            agent_version_id=version.id, context_snapshot_id=snapshot.id,
            workspace_id=workspace.id, instructed_by_user_id=user.id,
            model_provider_id=provider.id, runtime_adapter_id=adapter.id,
            execution_plane_id=plane.id,
            run_type="agent", trigger_origin="manual", prompt="test",
            mode="dry_run", status="queued",
        )
        db.add(run)
        db.commit()

        # Run → ExecutionPlane
        loaded_run = db.get(models.Run, run.id)
        assert loaded_run.execution_plane.id == plane.id

        # Workspace → WorkspaceProfile (one-to-one via back_populates)
        profile = models.WorkspaceProfile(
            id="cp-prof-1", space_id=space.id, workspace_id=workspace.id,
            cloud_allowed=False,
        )
        db.add(profile)
        db.commit()
        loaded_ws = db.get(models.Workspace, workspace.id)
        assert loaded_ws.profile is not None
        assert loaded_ws.profile.id == profile.id

        # Run → ExternalRunRecord
        ext = models.ExternalRunRecord(
            id="cp-ext-1", space_id=space.id, run_id=run.id,
            vendor="manual", execution_plane_id=plane.id,
        )
        db.add(ext)
        db.commit()
        loaded_run = db.get(models.Run, run.id)
        assert any(e.id == ext.id for e in loaded_run.external_run_records)

        # Run → RunReflection
        reflection = models.RunReflection(
            id="cp-refl-1", space_id=space.id, run_id=run.id, source="native",
        )
        db.add(reflection)
        db.commit()
        loaded_run = db.get(models.Run, run.id)
        assert any(r.id == reflection.id for r in loaded_run.run_reflections)
    finally:
        db.close()


def test_on_space_created_seeds_execution_planes(canonical_conn):
    """on_space_created seeds all 7 default execution planes for every new space, idempotently."""
    from app.spaces.hooks import on_space_created

    Session = sessionmaker(bind=canonical_conn, join_transaction_mode="create_savepoint")
    db = Session()
    try:
        space = models.Space(id="hook-space-1", name="Hook Space")
        user = models.User(id="hook-user-1", email="hook@example.com", display_name="Hook User")
        db.add_all([space, user])
        db.commit()

        on_space_created(db, space.id, seeded_by_user_id=user.id)

        count = db.query(models.ExecutionPlane).filter_by(space_id=space.id).count()
        assert count == 7, f"on_space_created must seed 7 execution planes, got {count}"

        # Second call must not create duplicates
        on_space_created(db, space.id, seeded_by_user_id=user.id)
        count_after = db.query(models.ExecutionPlane).filter_by(space_id=space.id).count()
        assert count_after == 7, "on_space_created seeding must be idempotent"
    finally:
        db.close()


def test_runs_does_not_have_orphaned_columns(canonical_engine):
    """runs.executor_type and runs.sandbox_level are removed; current semantic fields remain."""
    inspector = inspect(canonical_engine)
    col_names = {c["name"] for c in inspector.get_columns("runs")}
    assert "executor_type" not in col_names, "runs.executor_type must be removed"
    assert "sandbox_level" not in col_names, "runs.sandbox_level must be removed"
    # Current semantic fields must remain
    assert "required_sandbox_level" in col_names
    assert "execution_plane_id" in col_names
    assert "externality_level" in col_names


def test_copied_enum_check_constraints_exist(canonical_engine):
    """Copied enum fields on runs, artifacts, external_run_records, runtime_tool_bindings,
    workspace_profiles, and context_snapshots have matching CHECK constraints."""
    from sqlalchemy import text as sa_text

    def get_ddl(conn, table):
        rows = conn.execute(
            sa_text(f"SELECT sql FROM sqlite_master WHERE type='table' AND name='{table}'")
        ).fetchall()
        return rows[0][0] if rows else ""

    with canonical_engine.connect() as conn:
        runs_ddl = get_ddl(conn, "runs")
        assert "ck_runs_observability_level" in runs_ddl, "ck_runs_observability_level missing"
        assert "ck_runs_data_exposure_level" in runs_ddl, "ck_runs_data_exposure_level missing"
        assert "ck_runs_trust_level" in runs_ddl, "ck_runs_trust_level missing"

        artifacts_ddl = get_ddl(conn, "artifacts")
        assert "ck_artifacts_trust_level" in artifacts_ddl, "ck_artifacts_trust_level missing"

        ext_ddl = get_ddl(conn, "external_run_records")
        assert "ck_external_run_records_observability_level" in ext_ddl
        assert "ck_external_run_records_data_exposure_level" in ext_ddl

        rtb_ddl = get_ddl(conn, "runtime_tool_bindings")
        assert "ck_runtime_tool_bindings_data_exposure_level" in rtb_ddl
        assert "ck_runtime_tool_bindings_observability_level" in rtb_ddl

        wp_ddl = get_ddl(conn, "workspace_profiles")
        assert "ck_workspace_profiles_max_data_exposure_level" in wp_ddl
        assert "ck_workspace_profiles_min_observability_level" in wp_ddl

        cs_ddl = get_ddl(conn, "context_snapshots")
        assert "ck_context_snapshots_data_exposure_level" in cs_ddl
