"""PostgreSQL DDL semantics that must not regress toward generic portable DDL.

Checks both layers so ORM and Alembic stay consistent:
  - ORM metadata: every Boolean column's server_default renders as true/false.
  - Live schema: every boolean column default in the migrated DB is true/false.
  - Structured data columns use PostgreSQL JSONB, not generic JSON.
  - Internal reference columns are real foreign keys unless explicitly allowlisted.
"""
from __future__ import annotations

import pytest
from sqlalchemy import Boolean, JSON, inspect as sa_inspect, text
from sqlalchemy.dialects.postgresql import JSONB

from app.db import Base


EXPECTED_INTERNAL_FKS = {
    ("spaces", "created_by_user_id"): ("users", "id"),
    ("space_invitations", "invited_by_user_id"): ("users", "id"),
    ("agents", "current_version_id"): ("agent_versions", "id"),
    ("agent_versions", "source_proposal_id"): ("proposals", "id"),
    ("agent_versions", "source_activity_id"): ("activity_records", "id"),
    ("context_snapshots", "target_runtime_adapter_id"): ("runtime_adapters", "id"),
    ("context_snapshots", "execution_plane_id"): ("execution_planes", "id"),
    ("policies", "supersedes_policy_id"): ("policies", "id"),
    ("policies", "created_from_proposal_id"): ("proposals", "id"),
    ("runs", "project_id"): ("projects", "id"),
    ("runs", "task_id"): ("tasks", "id"),
    ("activity_records", "project_id"): ("projects", "id"),
    ("activity_records", "source_task_id"): ("tasks", "id"),
    ("activity_records", "subject_user_id"): ("users", "id"),
    ("proposals", "project_id"): ("projects", "id"),
    ("artifacts", "project_id"): ("projects", "id"),
    ("run_execution_locks", "job_id"): ("jobs", "id"),
    ("run_steps", "task_id"): ("tasks", "id"),
    ("memory_entries", "project_id"): ("projects", "id"),
    ("memory_entries", "root_memory_id"): ("memory_entries", "id"),
    ("memory_entries", "supersedes_memory_id"): ("memory_entries", "id"),
    ("knowledge_items", "root_item_id"): ("knowledge_items", "id"),
    ("knowledge_items", "supersedes_item_id"): ("knowledge_items", "id"),
    ("session_summaries", "source_first_message_id"): ("messages", "id"),
    ("session_summaries", "source_last_message_id"): ("messages", "id"),
    ("cli_credential_events", "runtime_adapter_id"): ("runtime_adapters", "id"),
    ("intake_items", "raw_artifact_id"): ("artifacts", "id"),
    ("intake_items", "extracted_artifact_id"): ("artifacts", "id"),
    ("intake_items", "summary_artifact_id"): ("artifacts", "id"),
}


SOFT_REFERENCE_ALLOWLIST = {
    ("auth_accounts", "provider_user_id"): "External identity-provider subject, not an internal row.",
    ("capability_overlays", "scope_id"): "Polymorphic capability overlay scope keyed by scope_type.",
    ("capability_versions", "scope_id"): "Polymorphic capability version scope keyed by scope_type.",
    ("cli_credential_events", "credential_profile_id"): "Credential profile IDs are external CLI profile names.",
    ("context_digests", "scope_id"): "Polymorphic digest scope keyed by digest_type.",
    ("context_snapshot_items", "item_id"): "Polymorphic context item keyed by item_type; references memory, knowledge_item, source, etc.",
    ("context_digests", "created_from_run_id"): "Optional provenance retained even if the run is pruned.",
    ("cards", "source_id"): "Polymorphic card origin keyed by source_type; covers note/knowledge_item/source/activity/run/proposal.",
    ("entity_links", "source_id"): "Polymorphic cross-object link source keyed by source_type.",
    ("entity_links", "target_id"): "Polymorphic cross-object link target keyed by target_type.",
    ("evidence_links", "target_id"): "Polymorphic evidence target keyed by target_type.",
    ("evolution_signals", "source_id"): "Polymorphic evolution signal source keyed by source_type.",
    ("evolution_targets", "target_ref_id"): "Polymorphic evolution target reference keyed by target_ref_type.",
    ("external_run_records", "vendor_run_id"): "External vendor/platform run identifier.",
    ("extracted_evidence", "source_object_id"): "Polymorphic source keyed by source_object_type.",
    ("extraction_jobs", "source_object_id"): "Polymorphic extraction source keyed by source_object_type.",
    ("intake_items", "source_object_id"): "Polymorphic source keyed by source_object_type.",
    ("intake_items", "source_external_id"): "External upstream source identifier.",
    ("knowledge_item_relations", "created_from_assessment_id"): "Reserved for a future assessment table.",
    ("memory_entries", "scope_id"): "Polymorphic memory scope keyed by scope_type.",
    ("memory_entries", "capability_id"): "Capability IDs come from capability.yaml, not a DB table.",
    ("memory_entries", "source_id"): "Legacy typed provenance; source_type lives outside this column.",
    ("memory_relations", "source_id"): "Polymorphic memory-system relation keyed by source_type.",
    ("memory_relations", "target_id"): "Polymorphic memory-system relation keyed by target_type.",
    ("participation_records", "source_object_id"): "Polymorphic participation source keyed by source_object_type.",
    ("policy_decision_records", "space_id"): "Append-only policy audit may outlive the referenced scope.",
    ("policy_decision_records", "actor_id"): "Append-only policy audit preserves actor_ref_json for deleted/external actors.",
    ("policy_decision_records", "resource_id"): "Polymorphic audited resource keyed by resource_type.",
    ("policy_decision_records", "policy_rule_id"): "Rule IDs are stable policy-engine identifiers.",
    ("policy_decision_records", "policy_id"): "Append-only audit may reference deleted or external policy sources.",
    ("policy_decision_records", "run_id"): "Append-only audit must survive run pruning.",
    ("policy_decision_records", "proposal_id"): "Append-only audit must survive proposal pruning.",
    ("provenance_links", "target_id"): "Polymorphic provenance target keyed by target_type.",
    ("provenance_links", "source_id"): "Polymorphic provenance source keyed by source_type.",
    ("run_execution_locks", "worker_id"): "Ephemeral worker process identifier, not a DB row.",
    ("runs", "capability_id"): "Capability IDs come from capability.yaml, not a DB table.",
    ("runtime_adapters", "credential_profile_id"): "External CLI credential profile name.",
    ("space_assistant_settings", "default_project_id"): "Optional soft default; a deleted project simply leaves a dangling preference the UI resolves leniently.",
    ("runtime_tool_bindings", "capability_id"): "Capability IDs come from capability.yaml, not a DB table.",
    ("source_pointers", "source_object_id"): "Cross-space polymorphic source keyed by source_object_type.",
}


def _server_default_text(col) -> str | None:
    sd = col.server_default
    if sd is None:
        return None
    arg = getattr(sd, "arg", sd)
    txt = getattr(arg, "text", None)
    if txt is None:
        txt = str(arg)
    return txt.strip().strip("'\"").lower()


def test_orm_boolean_server_defaults_are_native():
    offenders = []
    for table in Base.metadata.tables.values():
        for col in table.columns:
            if not isinstance(col.type, Boolean):
                continue
            val = _server_default_text(col)
            if val is None:
                continue
            if val not in ("true", "false"):
                offenders.append(f"{table.name}.{col.name} -> {val!r}")
    assert not offenders, (
        "Boolean columns must use true/false server defaults, not 1/0:\n"
        + "\n".join(offenders)
    )


def test_no_integer_one_zero_default_on_boolean_columns():
    """Boolean server defaults must be PostgreSQL-native true/false, never 1/0."""
    offenders = []
    for table in Base.metadata.tables.values():
        for col in table.columns:
            if isinstance(col.type, Boolean):
                val = _server_default_text(col)
                if val in ("1", "0"):
                    offenders.append(f"{table.name}.{col.name}")
    assert not offenders, f"Boolean columns using 1/0 default: {offenders}"


def test_live_schema_boolean_defaults_are_native(db_engine):
    """The migrated PostgreSQL schema has no boolean column defaulting to 1/0."""
    with db_engine.connect() as conn:
        rows = conn.execute(text(
            """
            SELECT table_name, column_name, column_default
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND data_type = 'boolean'
              AND column_default IS NOT NULL
            """
        )).fetchall()

    assert rows, "expected at least one boolean column with a default in the schema"
    offenders = []
    for table_name, column_name, default in rows:
        norm = str(default).strip().strip("'\"").lower()
        # PostgreSQL renders boolean defaults as true/false; a 1/0 default would
        # indicate a non-native boolean default leaked into the migration.
        if norm not in ("true", "false"):
            offenders.append(f"{table_name}.{column_name} -> {default!r}")
    assert not offenders, (
        "Live boolean column defaults must be true/false:\n" + "\n".join(offenders)
    )


def test_orm_json_columns_are_postgresql_jsonb():
    offenders = []
    seen = []
    for table in Base.metadata.tables.values():
        for col in table.columns:
            if isinstance(col.type, JSON):
                seen.append(f"{table.name}.{col.name}")
                if not isinstance(col.type, JSONB):
                    offenders.append(f"{table.name}.{col.name} -> {col.type!r}")

    assert seen, "expected structured JSON columns in ORM metadata"
    assert not offenders, (
        "Structured ORM JSON columns must use PostgreSQL JSONB:\n"
        + "\n".join(offenders)
    )


def test_live_json_columns_are_postgresql_jsonb(db_engine):
    with db_engine.connect() as conn:
        rows = conn.execute(text(
            """
            SELECT table_name, column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND data_type IN ('json', 'jsonb')
            """
        )).fetchall()

    assert rows, "expected structured JSON columns in the migrated schema"
    offenders = [
        f"{table}.{column} -> {data_type}"
        for table, column, data_type in rows
        if data_type != "jsonb"
    ]
    assert not offenders, (
        "Migrated PostgreSQL JSON columns must be jsonb, not json:\n"
        + "\n".join(offenders)
    )


def test_expected_internal_references_have_orm_foreign_keys():
    missing = []
    wrong = []

    for (table_name, column_name), expected in EXPECTED_INTERNAL_FKS.items():
        table = Base.metadata.tables[table_name]
        col = table.columns[column_name]
        if not col.foreign_keys:
            missing.append(f"{table_name}.{column_name}")
            continue
        targets = {(fk.column.table.name, fk.column.name) for fk in col.foreign_keys}
        if expected not in targets:
            wrong.append(f"{table_name}.{column_name} -> {sorted(targets)} expected {expected}")

    assert not missing, "ORM internal references missing FKs:\n" + "\n".join(missing)
    assert not wrong, "ORM internal references point at the wrong table:\n" + "\n".join(wrong)


def test_expected_internal_references_have_live_foreign_keys(db_engine):
    inspector = sa_inspect(db_engine)
    missing = []

    for (table_name, column_name), (target_table, target_col) in EXPECTED_INTERNAL_FKS.items():
        fks = inspector.get_foreign_keys(table_name)
        if not any(
            fk.get("constrained_columns") == [column_name]
            and fk.get("referred_table") == target_table
            and fk.get("referred_columns") == [target_col]
            for fk in fks
        ):
            missing.append(f"{table_name}.{column_name} -> {target_table}.{target_col}")

    assert not missing, (
        "Migrated schema is missing expected internal FK constraints:\n"
        + "\n".join(missing)
    )


def test_unconstrained_id_columns_are_explicitly_allowlisted():
    offenders = []
    for table in Base.metadata.tables.values():
        for col in table.columns:
            if col.primary_key or col.foreign_keys or not col.name.endswith("_id"):
                continue
            key = (table.name, col.name)
            if key not in SOFT_REFERENCE_ALLOWLIST:
                offenders.append(f"{table.name}.{col.name}")

    missing_columns = [key for key in SOFT_REFERENCE_ALLOWLIST if key[0] not in Base.metadata.tables]
    missing_columns += [
        key
        for key in SOFT_REFERENCE_ALLOWLIST
        if key[0] in Base.metadata.tables and key[1] not in Base.metadata.tables[key[0]].columns
    ]
    empty_reasons = [f"{table}.{col}" for (table, col), reason in SOFT_REFERENCE_ALLOWLIST.items() if not reason]

    assert not offenders, (
        "Unconstrained *_id columns must either get a real FK or be explicitly allowlisted:\n"
        + "\n".join(sorted(offenders))
    )
    assert not missing_columns, f"Soft-reference allowlist contains stale columns: {missing_columns}"
    assert not empty_reasons, f"Soft-reference allowlist entries need reasons: {empty_reasons}"
