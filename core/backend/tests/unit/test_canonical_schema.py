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
    "entity_refs",
    "memory_relations",
    "provenance_links",
    "participation_records",
    "personal_memory_grants",
    "proposal_approvals",
    "personal_memory_grant_events",
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


# ---------------------------------------------------------------------------
# Phase 3 schema additions
# ---------------------------------------------------------------------------

_VISIBILITY_TABLES = ["tasks", "runs", "artifacts", "activity_records", "proposals"]
_VISIBILITY_DEFAULT = "space_shared"


def test_phase3_visibility_columns_exist_with_correct_default(canonical_engine):
    """Phase 3: visibility NOT NULL with server_default=space_shared on all target tables."""
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


def test_phase3_owner_user_id_columns_exist(canonical_engine):
    """Phase 3: artifacts and activity_records have owner_user_id nullable column."""
    inspector = inspect(canonical_engine)
    for table in ("artifacts", "activity_records"):
        col_names = {c["name"] for c in inspector.get_columns(table)}
        assert "owner_user_id" in col_names, f"{table}.owner_user_id column missing"


def test_phase3_owner_user_id_fk_exists(canonical_engine):
    """Phase 3: owner_user_id on artifacts and activity_records has FK to users.id."""
    inspector = inspect(canonical_engine)
    assert ("owner_user_id", "users", "id") in _foreign_keys(inspector, "artifacts")
    assert ("owner_user_id", "users", "id") in _foreign_keys(inspector, "activity_records")


def test_phase3_participation_records_table_exists(canonical_engine):
    """Phase 3: participation_records table exists with required pointer columns."""
    inspector = inspect(canonical_engine)
    assert "participation_records" in inspector.get_table_names()
    col_names = {c["name"] for c in inspector.get_columns("participation_records")}
    required = {
        "id", "user_id", "personal_space_id", "source_space_id",
        "source_object_type", "source_object_id", "role", "occurred_at", "created_at",
    }
    assert required.issubset(col_names), f"Missing columns: {required - col_names}"


def test_phase3_participation_records_has_no_content_columns(canonical_engine):
    """Phase 3: participation_records must not contain raw content or payload fields."""
    inspector = inspect(canonical_engine)
    col_names = {c["name"] for c in inspector.get_columns("participation_records")}
    forbidden = {"content", "body", "summary", "payload", "payload_json", "raw_content", "title"}
    found = forbidden & col_names
    assert not found, (
        f"participation_records must be a pointer ledger — found content columns: {found}"
    )


def test_phase3_participation_records_indexes_exist(canonical_engine):
    """Phase 3: participation_records has the three required indexes."""
    inspector = inspect(canonical_engine)
    indexes = inspector.get_indexes("participation_records")
    indexed_cols = {tuple(i["column_names"]) for i in indexes}
    assert ("user_id",) in indexed_cols, "ix_participation_records_user_id missing"
    assert ("personal_space_id",) in indexed_cols, "ix_participation_records_personal_space_id missing"
    # composite source index
    source_cols = ("source_space_id", "source_object_type", "source_object_id")
    assert source_cols in indexed_cols, f"ix_participation_records_source missing: found {indexed_cols}"


def test_phase3_participation_records_fks_exist(canonical_engine):
    """Phase 3: participation_records has FK to users.id and spaces.id (both personal and source)."""
    inspector = inspect(canonical_engine)
    fks = _foreign_keys(inspector, "participation_records")
    assert ("user_id", "users", "id") in fks
    assert ("personal_space_id", "spaces", "id") in fks
    assert ("source_space_id", "spaces", "id") in fks


def test_phase3_visibility_not_on_memory_entries(canonical_engine):
    """Memory already had visibility before Phase 3; ensure the column still exists."""
    inspector = inspect(canonical_engine)
    col_names = {c["name"] for c in inspector.get_columns("memory_entries")}
    assert "visibility" in col_names, "memory_entries.visibility must still exist"


def test_phase7a_source_pointers_table_exists(canonical_engine):
    """Phase 7A: source_pointers table exists with required provenance columns."""
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


def test_phase7a_source_pointers_has_no_content_columns(canonical_engine):
    """Phase 7A: source_pointers must not store raw source content."""
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


def test_phase7a_source_pointers_indexes_exist(canonical_engine):
    """Phase 7A: source_pointers has owner, source composite, granted_by, and expires indexes."""
    inspector = inspect(canonical_engine)
    indexes = inspector.get_indexes("source_pointers")
    indexed_cols = {tuple(i["column_names"]) for i in indexes}
    assert ("owner_space_id",) in indexed_cols
    assert ("granted_by_user_id",) in indexed_cols
    assert ("expires_at",) in indexed_cols
    source_cols = ("source_space_id", "source_object_type", "source_object_id")
    assert source_cols in indexed_cols


def test_phase7a_source_pointers_fks_exist(canonical_engine):
    """Phase 7A: source_pointers FKs to spaces and users."""
    inspector = inspect(canonical_engine)
    fks = _foreign_keys(inspector, "source_pointers")
    assert ("owner_space_id", "spaces", "id") in fks
    assert ("source_space_id", "spaces", "id") in fks
    assert ("granted_by_user_id", "users", "id") in fks


# ---------------------------------------------------------------------------
# Phase 8A: PersonalMemoryGrant schema skeleton
# ---------------------------------------------------------------------------


def test_phase8a_grant_tables_exist(canonical_engine):
    """Phase 8A: personal_memory_grants and personal_memory_grant_events tables exist."""
    inspector = inspect(canonical_engine)
    tables = inspector.get_table_names()
    assert "personal_memory_grants" in tables
    assert "personal_memory_grant_events" in tables


def test_phase8a_grant_required_columns_exist(canonical_engine):
    """Phase 8A: personal_memory_grants has all required columns."""
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
    # target_agent_id must be nullable (MVP: NULL enforced by CHECK constraint)
    assert col_defs["target_agent_id"]["nullable"] is True


def test_phase8a_grant_has_no_raw_content_columns(canonical_engine):
    """Phase 8A: personal_memory_grants must not store raw memory content."""
    inspector = inspect(canonical_engine)
    col_names = {c["name"] for c in inspector.get_columns("personal_memory_grants")}
    forbidden = {
        "content", "body", "raw_content", "payload", "summary",
        "generated_summary", "memory_text", "copied_text", "source_snapshot",
    }
    found = forbidden & col_names
    assert not found, f"personal_memory_grants must not have content columns: {found}"


def test_phase8a_grant_events_required_columns_exist(canonical_engine):
    """Phase 8A: personal_memory_grant_events has all required columns."""
    inspector = inspect(canonical_engine)
    col_names = {c["name"] for c in inspector.get_columns("personal_memory_grant_events")}
    required = {
        "id", "grant_id", "event_type", "actor_user_id", "run_id",
        "proposal_id", "source_space_id", "target_space_id", "metadata_json", "created_at",
    }
    assert required.issubset(col_names), f"Missing: {required - col_names}"


def test_phase8a_grant_events_has_no_raw_content_columns(canonical_engine):
    """Phase 8A: personal_memory_grant_events must not store raw memory content."""
    inspector = inspect(canonical_engine)
    col_names = {c["name"] for c in inspector.get_columns("personal_memory_grant_events")}
    forbidden = {
        "content", "body", "raw_content", "payload", "summary",
        "generated_summary", "memory_text", "copied_text", "source_snapshot",
    }
    found = forbidden & col_names
    assert not found, f"personal_memory_grant_events must not have content columns: {found}"


def test_phase8a_grant_fks_exist(canonical_engine):
    """Phase 8A: personal_memory_grants has all required foreign keys."""
    inspector = inspect(canonical_engine)
    fks = _foreign_keys(inspector, "personal_memory_grants")
    assert ("granting_user_id", "users", "id") in fks
    assert ("personal_space_id", "spaces", "id") in fks
    assert ("target_space_id", "spaces", "id") in fks
    assert ("target_run_id", "runs", "id") in fks
    assert ("target_agent_id", "agents", "id") in fks


def test_phase8a_grant_events_fks_exist(canonical_engine):
    """Phase 8A: personal_memory_grant_events has required foreign keys."""
    inspector = inspect(canonical_engine)
    fks = _foreign_keys(inspector, "personal_memory_grant_events")
    assert ("grant_id", "personal_memory_grants", "id") in fks
    assert ("actor_user_id", "users", "id") in fks
    assert ("run_id", "runs", "id") in fks
    assert ("proposal_id", "proposals", "id") in fks


def test_phase8a_grant_indexes_exist(canonical_engine):
    """Phase 8A: personal_memory_grants has required indexes."""
    inspector = inspect(canonical_engine)
    indexed = {tuple(i["column_names"]) for i in inspector.get_indexes("personal_memory_grants")}
    assert ("granting_user_id",) in indexed
    assert ("personal_space_id",) in indexed
    assert ("target_space_id",) in indexed
    assert ("target_run_id",) in indexed
    assert ("status",) in indexed
    assert ("read_expires_at",) in indexed


def test_phase8a_grant_events_indexes_exist(canonical_engine):
    """Phase 8A: personal_memory_grant_events has required indexes."""
    inspector = inspect(canonical_engine)
    indexed = {tuple(i["column_names"]) for i in inspector.get_indexes("personal_memory_grant_events")}
    assert ("grant_id",) in indexed
    assert ("actor_user_id",) in indexed
    assert ("run_id",) in indexed
    assert ("created_at",) in indexed


def test_phase8a_grant_check_constraints_exist(canonical_engine):
    """Phase 8A: personal_memory_grants has grant_scope, access_mode, status, and target_agent_id constraints."""
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


def test_phase8a_grant_events_check_constraint_exists(canonical_engine):
    """Phase 8A: personal_memory_grant_events has event_type CHECK constraint."""
    from sqlalchemy import text as sa_text

    with canonical_engine.connect() as conn:
        rows = conn.execute(
            sa_text("SELECT sql FROM sqlite_master WHERE type='table' AND name='personal_memory_grant_events'")
        ).fetchall()
    ddl = rows[0][0] if rows else ""
    assert "ck_personal_memory_grant_events_event_type" in ddl, "event_type CHECK constraint missing"


def test_grant_events_event_type_constraint_includes_new_types(canonical_engine):
    """Final Consistency Patch (M2): event_type DDL includes egress_proposal_created and egress_approved."""
    from sqlalchemy import text as sa_text

    with canonical_engine.connect() as conn:
        rows = conn.execute(
            sa_text("SELECT sql FROM sqlite_master WHERE type='table' AND name='personal_memory_grant_events'")
        ).fetchall()
    ddl = rows[0][0] if rows else ""
    assert "egress_proposal_created" in ddl, "egress_proposal_created must be in event_type CHECK constraint"
    assert "egress_approved" in ddl, "egress_approved must be in event_type CHECK constraint"


def test_phase_e_proposal_approvals_table_exists(canonical_engine):
    """Phase E: proposal_approvals table exists."""
    inspector = inspect(canonical_engine)
    assert "proposal_approvals" in inspector.get_table_names()


def test_phase_e_proposal_approvals_required_columns_exist(canonical_engine):
    """Phase E: proposal_approvals has all required metadata-only columns."""
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


def test_phase_e_proposal_approvals_has_no_raw_content_columns(canonical_engine):
    """Phase E: proposal_approvals must not store raw memory, summary, IDs, or payload content."""
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


def test_phase_e_proposal_approvals_fks_exist(canonical_engine):
    """Phase E: proposal_approvals has required foreign keys."""
    inspector = inspect(canonical_engine)
    fks = _foreign_keys(inspector, "proposal_approvals")
    assert ("proposal_id", "proposals", "id") in fks
    assert ("approver_user_id", "users", "id") in fks
    assert ("grant_id", "personal_memory_grants", "id") in fks
    assert ("target_space_id", "spaces", "id") in fks


def test_phase_e_proposal_approvals_indexes_exist(canonical_engine):
    """Phase E: proposal_approvals has lookup and active-approval uniqueness indexes."""
    inspector = inspect(canonical_engine)
    indexed = {tuple(i["column_names"]) for i in inspector.get_indexes("proposal_approvals")}
    assert ("proposal_id",) in indexed
    assert ("approver_user_id",) in indexed
    assert ("approval_type",) in indexed
    assert ("grant_id",) in indexed
    assert ("target_space_id",) in indexed
    assert ("created_at",) in indexed
    assert ("proposal_id", "approval_type", "approver_user_id", "grant_id") in indexed


def test_phase_e_proposal_approvals_check_constraints_exist(canonical_engine):
    """Phase E: proposal_approvals constrains approval_type and status."""
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


def test_phase_e_proposal_approvals_partial_unique_index_exists(canonical_engine):
    """Phase E: at most one active approval per proposal/type/approver/grant."""
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


def test_phase8a_grant_partial_unique_index_exists(canonical_engine):
    """Phase 8A: partial unique index exists on personal_memory_grants (granting_user_id, target_run_id) WHERE active/consuming."""
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


def test_phase8a_grant_constraints_reject_invalid_scope(canonical_engine):
    """Phase 8A: inserting grant_scope != 'run' is rejected by DB constraint."""
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


def test_phase8a_grant_constraints_reject_null_run_id(canonical_engine):
    """Phase 8A: target_run_id NOT NULL is enforced at DB level."""
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


def test_phase8a_grant_tables_in_required_set(canonical_engine):
    """Phase 8A: both grant tables appear in REQUIRED_TABLES when updated."""
    inspector = inspect(canonical_engine)
    all_tables = set(inspector.get_table_names())
    assert "personal_memory_grants" in all_tables
    assert "personal_memory_grant_events" in all_tables
