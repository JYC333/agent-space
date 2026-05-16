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
    "context_sources",
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
    "entity_refs",
    "memory_relations",
    "provenance_links",
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
    assert "provider_configs" not in inspector.get_table_names()
    assert "cli_adapter_configs" not in inspector.get_table_names()

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
        user = models.User(id="user-1", space_id=space.id, email="u@example.com", display_name="User")
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
        source = models.ContextSource(
            id="source-1",
            space_id=space.id,
            name="Activity",
            source_type="activity",
            scope_json={"space_id": space.id},
        )
        message = models.Message(id="message-1", space_id=space.id, session_id=session.id, user_id=user.id, role="user", content="hi")

        db.add(space)
        db.commit()

        db.add_all([user, credential, source, policy])
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
    assert ("default_space_id", "spaces", "id") not in _foreign_keys(inspector, "users")
    assert ("invited_by_user_id", "users", "id") not in _foreign_keys(inspector, "space_invitations")

    assert ("agent_id", "agents", "id") in _foreign_keys(inspector, "agent_versions")
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
    assert "memory_access_logs" in inspector.get_table_names()
    assert ("memory_id", "memory_entries", "id") in _foreign_keys(inspector, "memory_access_logs")
    assert ("space_id", "spaces", "id") in _foreign_keys(inspector, "entity_refs")
    assert ("space_id", "spaces", "id") in _foreign_keys(inspector, "memory_relations")
    assert ("created_from_proposal_id", "proposals", "id") in _foreign_keys(inspector, "memory_relations")
    assert ("space_id", "spaces", "id") in _foreign_keys(inspector, "provenance_links")
    # policies.created_from_proposal_id is intentionally a soft reference (policies precedes proposals in migration order)
    assert ("created_from_proposal_id", "proposals", "id") not in _foreign_keys(inspector, "policies")


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
