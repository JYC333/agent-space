from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
LOCAL_COMPOSE = REPO_ROOT / "ops/scripts/lib/local-compose.sh"


def _script() -> str:
    return LOCAL_COMPOSE.read_text(encoding="utf-8")


def test_control_plane_role_grants_stage_5_policy_audit_tables():
    text = _script()

    required_grants = [
        'GRANT SELECT, INSERT, UPDATE ON TABLE public.runs TO "$role";',
        'GRANT SELECT, INSERT, UPDATE ON TABLE public.run_steps TO "$role";',
        'GRANT SELECT, INSERT ON TABLE public.run_events TO "$role";',
        'GRANT SELECT, INSERT ON TABLE public.run_evaluations TO "$role";',
        'GRANT SELECT, INSERT ON TABLE public.run_finalizations TO "$role";',
        'GRANT SELECT, INSERT, UPDATE ON TABLE public.context_snapshots TO "$role";',
        'GRANT SELECT, INSERT ON TABLE public.actors TO "$role";',
        'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.run_execution_locks TO "$role";',
        'GRANT SELECT, INSERT, UPDATE ON TABLE public.jobs TO "$role";',
        'GRANT SELECT, INSERT ON TABLE public.job_events TO "$role";',
        'GRANT SELECT ON TABLE public.execution_planes TO "$role";',
        'GRANT SELECT ON TABLE public.agents TO "$role";',
        'GRANT SELECT ON TABLE public.agent_versions TO "$role";',
        'GRANT SELECT ON TABLE public.workspaces TO "$role";',
        'GRANT SELECT ON TABLE public.projects TO "$role";',
        'GRANT SELECT, INSERT ON TABLE public.artifacts TO "$role";',
        'GRANT SELECT, INSERT ON TABLE public.policy_decision_records TO "$role";',
        'GRANT SELECT, UPDATE ON TABLE public.proposals TO "$role";',
        'GRANT SELECT, INSERT, UPDATE ON TABLE public.proposal_approvals TO "$role";',
    ]
    for grant in required_grants:
        assert grant in text

    forbidden_direct_grants = [
        # memory_entries SELECT and proposals INSERT are fixed TS memory grants;
        # see the memory-read test.
        "GRANT SELECT ON TABLE public.memory_access_logs",
        "GRANT UPDATE ON TABLE public.policy_decision_records",
        "GRANT DELETE ON TABLE public.policy_decision_records",
        "GRANT DELETE ON TABLE public.proposals",
        "GRANT DELETE ON TABLE public.proposal_approvals",
        "GRANT UPDATE ON TABLE public.run_events",
        "GRANT DELETE ON TABLE public.run_events",
    ]
    for grant in forbidden_direct_grants:
        assert grant not in text


def test_control_plane_role_provisioning_contains_permission_smoke_test():
    text = _script()

    assert "has_schema_privilege(role_name, 'public', 'CREATE')" in text
    assert "has_database_privilege(role_name, current_database(), 'TEMP')" in text
    # has_database_privilege() includes PUBLIC-inherited rights and PostgreSQL
    # grants TEMP to PUBLIC on every database by default — provisioning must
    # revoke it from PUBLIC or the smoke check fails on a fresh database.
    assert 'REVOKE TEMPORARY ON DATABASE "$pgdb" FROM PUBLIC;' in text
    assert "('run_events', 'UPDATE')" in text
    assert "('run_evaluations', 'INSERT')" in text
    assert "('run_finalizations', 'INSERT')" in text
    assert "('memory_entries', 'SELECT')" in text
    assert "('policy_decision_records', 'SELECT')" in text
    assert "('policy_decision_records', 'INSERT')" in text
    assert "('policy_decision_records', 'UPDATE')" in text
    assert "('proposals', 'SELECT')" in text
    assert "('proposals', 'UPDATE')" in text
    assert "('proposal_approvals', 'INSERT')" in text
    assert "('proposal_approvals', 'DELETE')" in text
    assert "('context_snapshots', 'SELECT')" in text
    assert "('context_snapshots', 'INSERT')" in text
    assert "('context_snapshots', 'UPDATE')" in text
    assert "('context_snapshot_items', 'SELECT')" in text
    assert "('user_sessions', 'DELETE')" in text
    assert "('users', 'UPDATE')" in text
    assert "('user_sessions', 'INSERT')" in text
    assert "('space_memberships', 'INSERT')" in text
    assert "unexpectedly has %.% privilege" in text


def test_control_plane_role_provisioning_uses_readable_quiet_logs():
    text = _script()

    assert "psql -X -q -v ON_ERROR_STOP=1" in text
    assert (
        "applying least-privilege identity, provider, run, job, runtime metadata, policy audit, "
        "proposal review/apply, sessions, context, memory, artifact, leaf-domain, "
        "and scheduler/automation grants"
    ) in text
    assert "verified required grants and denied unrelated table access" in text
    assert "Control-plane DB role '$role' is ready." in text


def test_control_plane_role_identity_grants_are_native_and_scoped():
    """Native auth/spaces are TS-owned, with scoped DB grants."""
    text = _script()

    required_grants = [
        'GRANT SELECT (id, email, display_name, avatar_url, created_at, last_login_at) ON TABLE public.users TO "$role";',
        'GRANT INSERT (id, email, display_name, avatar_url, status, last_login_at, created_at, updated_at) ON TABLE public.users TO "$role";',
        'GRANT UPDATE (email, display_name, avatar_url, last_login_at, updated_at) ON TABLE public.users TO "$role";',
        'GRANT SELECT (user_id, provider, provider_user_id) ON TABLE public.auth_accounts TO "$role";',
        'GRANT INSERT (id, user_id, provider, provider_user_id, email, created_at) ON TABLE public.auth_accounts TO "$role";',
        'GRANT SELECT (id, user_id, token_hash, expires_at) ON TABLE public.user_sessions TO "$role";',
        'GRANT INSERT (id, user_id, token_hash, created_at, expires_at, last_seen_at) ON TABLE public.user_sessions TO "$role";',
        'GRANT UPDATE (last_seen_at) ON TABLE public.user_sessions TO "$role";',
        'GRANT DELETE ON TABLE public.user_sessions TO "$role";',
        'GRANT SELECT (id, space_id, user_id, role, status, created_at) ON TABLE public.space_memberships TO "$role";',
        'GRANT INSERT (id, space_id, user_id, role, status, created_at, updated_at) ON TABLE public.space_memberships TO "$role";',
        'GRANT SELECT (id, name, type, created_by_user_id, created_at, updated_at) ON TABLE public.spaces TO "$role";',
        'GRANT INSERT (id, name, type, created_by_user_id, created_at, updated_at) ON TABLE public.spaces TO "$role";',
        'GRANT SELECT (id, space_id, invited_email, role, token_hash, status, expires_at, accepted_at) ON TABLE public.space_invitations TO "$role";',
        'GRANT INSERT (id, space_id, invited_email, role, token_hash, status, invited_by_user_id, created_at, expires_at) ON TABLE public.space_invitations TO "$role";',
        'GRANT UPDATE (status, accepted_at) ON TABLE public.space_invitations TO "$role";',
        'GRANT INSERT (id, space_id, name, type, provider, execution_location, runtime_origin, trust_level, observability_level, data_exposure_level, credential_mode, config_json, enabled, created_at, updated_at) ON TABLE public.execution_planes TO "$role";',
        'GRANT SELECT (space_id, namespace, scope_type, deleted_at) ON TABLE public.memory_entries TO "$role";',
        'GRANT INSERT (id, space_id, scope_type, scope_id, memory_type, content, status, created_at, updated_at, subject_user_id, owner_user_id, sensitivity_level, namespace, title, visibility, confidence, importance, created_by, version, access_count) ON TABLE public.memory_entries TO "$role";',
        'GRANT SELECT (id, space_id, system_role) ON TABLE public.note_collections TO "$role";',
        'GRANT INSERT (id, space_id, parent_id, name, system_role, sort_order, is_system, is_hidden, created_at, updated_at) ON TABLE public.note_collections TO "$role";',
    ]
    for grant in required_grants:
        assert grant in text

    required_revokes = [
        'REVOKE SELECT (id, email, display_name, avatar_url, created_at, last_login_at) ON TABLE public.users FROM "$role";',
        'REVOKE INSERT (id, email, display_name, avatar_url, status, last_login_at, created_at, updated_at) ON TABLE public.users FROM "$role";',
        'REVOKE UPDATE (email, display_name, avatar_url, last_login_at, updated_at) ON TABLE public.users FROM "$role";',
        'REVOKE SELECT (user_id, provider, provider_user_id) ON TABLE public.auth_accounts FROM "$role";',
        'REVOKE INSERT (id, user_id, provider, provider_user_id, email, created_at) ON TABLE public.auth_accounts FROM "$role";',
        'REVOKE SELECT (id, user_id, token_hash, expires_at) ON TABLE public.user_sessions FROM "$role";',
        'REVOKE INSERT (id, user_id, token_hash, created_at, expires_at, last_seen_at) ON TABLE public.user_sessions FROM "$role";',
        'REVOKE UPDATE (last_seen_at) ON TABLE public.user_sessions FROM "$role";',
        'REVOKE SELECT (id, space_id, user_id, role, status, created_at) ON TABLE public.space_memberships FROM "$role";',
        'REVOKE INSERT (id, space_id, user_id, role, status, created_at, updated_at) ON TABLE public.space_memberships FROM "$role";',
        'REVOKE SELECT (id, name, type, created_by_user_id, created_at, updated_at) ON TABLE public.spaces FROM "$role";',
        'REVOKE INSERT (id, name, type, created_by_user_id, created_at, updated_at) ON TABLE public.spaces FROM "$role";',
    ]
    for revoke in required_revokes:
        assert revoke in text

    # Logout is the only table-level identity mutation. OAuth, space create,
    # invitations, and space-created seeds use column-scoped inserts/updates.
    assert "('user_sessions', 'DELETE')" in text
    assert "('users', 'UPDATE')" in text
    assert "('users', 'DELETE')" in text
    assert "('user_sessions', 'INSERT')" in text
    assert "('space_memberships', 'INSERT')" in text
    assert "('space_memberships', 'UPDATE')" in text
    assert "('space_memberships', 'DELETE')" in text
    assert "GRANT UPDATE ON TABLE public.users" not in text
    assert "GRANT INSERT ON TABLE public.user_sessions" not in text
    assert "GRANT INSERT ON TABLE public.space_memberships" not in text
    assert "GRANT INSERT ON TABLE public.memory_entries" not in text
    assert "GRANT INSERT ON TABLE public.note_collections" not in text

    column_checks = [
        "has_column_privilege(role_name, 'public.users', 'id', 'SELECT')",
        "has_column_privilege(role_name, 'public.users', 'email', 'INSERT')",
        "has_column_privilege(role_name, 'public.users', 'display_name', 'UPDATE')",
        "has_column_privilege(role_name, 'public.users', 'status', 'UPDATE')",
        "has_column_privilege(role_name, 'public.auth_accounts', 'provider_user_id', 'SELECT')",
        "has_column_privilege(role_name, 'public.auth_accounts', 'provider_user_id', 'INSERT')",
        "has_column_privilege(role_name, 'public.user_sessions', 'token_hash', 'SELECT')",
        "has_column_privilege(role_name, 'public.user_sessions', 'token_hash', 'INSERT')",
        "has_column_privilege(role_name, 'public.user_sessions', 'last_seen_at', 'UPDATE')",
        "has_column_privilege(role_name, 'public.space_memberships', 'space_id', 'SELECT')",
        "has_column_privilege(role_name, 'public.space_memberships', 'role', 'INSERT')",
        "has_column_privilege(role_name, 'public.spaces', 'name', 'SELECT')",
        "has_column_privilege(role_name, 'public.spaces', 'name', 'INSERT')",
        "has_column_privilege(role_name, 'public.space_invitations', 'token_hash', 'SELECT')",
        "has_column_privilege(role_name, 'public.space_invitations', 'token_hash', 'INSERT')",
        "has_column_privilege(role_name, 'public.space_invitations', 'status', 'UPDATE')",
        "has_column_privilege(role_name, 'public.execution_planes', 'name', 'INSERT')",
        "has_column_privilege(role_name, 'public.memory_entries', 'namespace', 'SELECT')",
        "has_column_privilege(role_name, 'public.memory_entries', 'namespace', 'INSERT')",
        "has_column_privilege(role_name, 'public.note_collections', 'system_role', 'SELECT')",
        "has_column_privilege(role_name, 'public.note_collections', 'system_role', 'INSERT')",
    ]
    for check in column_checks:
        assert check in text


def test_control_plane_role_sessions_grant_is_fixed_ts_authority():
    """Public session/message grants are part of the fixed TS foundation."""
    text = _script()

    assert "CONTROL_PLANE_SESSIONS_AUTHORITY" not in text
    # Emitted from a double-quoted bash string, so the source escapes the quotes.
    assert r'GRANT SELECT, INSERT, UPDATE ON TABLE public.sessions TO \"$role\";' in text
    assert r'GRANT SELECT, INSERT ON TABLE public.messages TO \"$role\";' in text
    assert r'GRANT SELECT ON TABLE public.session_summaries TO \"$role\";' in text
    # Append-only / no-archive privileges are never granted.
    assert "DELETE ON TABLE public.sessions" not in text
    assert "UPDATE ON TABLE public.messages" not in text
    assert "DELETE ON TABLE public.messages" not in text
    assert "INSERT ON TABLE public.session_summaries" not in text
    assert "UPDATE ON TABLE public.session_summaries" not in text
    assert "DELETE ON TABLE public.session_summaries" not in text

    # Always-denied (both modes): session delete, message update/delete, summary writes.
    assert "('sessions', 'DELETE')" in text
    assert "('messages', 'UPDATE')" in text
    assert "('messages', 'DELETE')" in text
    assert "('session_summaries', 'INSERT')" in text
    assert "('session_summaries', 'UPDATE')" in text
    assert "('session_summaries', 'DELETE')" in text
    # Required under the fixed TS sessions authority.
    assert "('sessions', 'INSERT')" in text
    assert "('sessions', 'UPDATE')" in text
    assert "('messages', 'INSERT')" in text
    assert "('sessions', 'SELECT')" in text
    assert "('messages', 'SELECT')," in text
    assert "('session_summaries', 'SELECT')," in text


def test_control_plane_role_context_grant_is_fixed_ts_authority():
    """Context item/source/digest/grant reads are fixed TS-owned."""
    text = _script()

    assert "CONTROL_PLANE_CONTEXT_AUTHORITY" not in text
    assert 'GRANT SELECT, INSERT, UPDATE ON TABLE public.context_snapshots TO "$role";' in text
    assert (
        r'GRANT SELECT, INSERT, UPDATE ON TABLE public.context_snapshot_items TO \"$role\";'
        in text
    )
    assert r'GRANT SELECT, INSERT, UPDATE ON TABLE public.knowledge_items TO \"$role\";' in text
    assert r'GRANT SELECT, INSERT, UPDATE ON TABLE public.sources TO \"$role\";' in text
    assert r'GRANT SELECT, INSERT, UPDATE ON TABLE public.activity_records TO \"$role\";' in text
    assert r'GRANT SELECT ON TABLE public.policies TO \"$role\";' in text
    assert r'GRANT SELECT ON TABLE public.context_digests TO \"$role\";' in text
    assert r'GRANT SELECT ON TABLE public.memory_relations TO \"$role\";' in text
    assert r'GRANT SELECT, INSERT, UPDATE ON TABLE public.extracted_evidence TO \"$role\";' in text
    assert r'GRANT SELECT ON TABLE public.evidence_links TO \"$role\";' in text
    assert (
        r'GRANT INSERT (id, space_id, evidence_id, target_type, target_id, link_type, status, '
        r'created_by_run_id, created_at, updated_at) ON TABLE public.evidence_links TO \"$role\";'
    ) in text
    assert r'GRANT SELECT ON TABLE public.personal_memory_grants TO \"$role\";' in text
    assert (
        r'GRANT UPDATE (status, consume_started_at, used_at, failed_at, failure_stage, updated_at) '
        r'ON TABLE public.personal_memory_grants TO \"$role\";'
    ) in text
    assert r'GRANT INSERT ON TABLE public.personal_memory_grant_events TO \"$role\";' in text

    assert "('context_snapshots', 'INSERT')" in text
    assert "('context_snapshots', 'UPDATE')" in text
    assert "('context_snapshot_items', 'SELECT')" in text
    assert "('context_snapshot_items', 'INSERT')" in text
    assert "('context_snapshot_items', 'UPDATE')" in text
    assert "('policies', 'SELECT')" in text
    assert "('context_digests', 'SELECT')" in text
    assert "('memory_relations', 'SELECT')" in text
    assert "('extracted_evidence', 'SELECT')" in text
    assert "('evidence_links', 'SELECT')" in text
    assert "('personal_memory_grants', 'SELECT')" in text
    assert "('personal_memory_grant_events', 'INSERT')" in text
    assert "('context_snapshot_items', 'DELETE')" in text
    assert "('activity_records', 'INSERT')" in text
    assert "('activity_records', 'UPDATE')" in text
    assert "('knowledge_items', 'INSERT')" in text
    assert "('knowledge_items', 'UPDATE')" in text
    assert "('sources', 'INSERT')" in text
    assert "('sources', 'UPDATE')" in text
    assert "('extracted_evidence', 'INSERT')" in text
    assert "('extracted_evidence', 'UPDATE')" in text
    assert "('context_digests', 'INSERT')" in text
    assert "('extracted_evidence', 'DELETE')" in text
    assert "('activity_records', 'DELETE')" in text
    assert "('knowledge_items', 'DELETE')" in text
    assert "('sources', 'DELETE')" in text
    assert "('evidence_links', 'INSERT')" in text
    assert "('evidence_links', 'UPDATE')" in text
    assert "('personal_memory_grants', 'UPDATE')" in text
    assert "('personal_memory_grants', 'INSERT')" in text
    assert "('personal_memory_grant_events', 'SELECT')" in text

    column_checks = [
        "has_column_privilege(role_name, 'public.evidence_links', 'id', 'INSERT')",
        "has_column_privilege(role_name, 'public.evidence_links', 'link_type', 'INSERT')",
        "has_column_privilege(role_name, 'public.evidence_links', 'created_by_run_id', 'INSERT')",
        "has_column_privilege(role_name, 'public.evidence_links', 'confidence', 'INSERT')",
        "has_column_privilege(role_name, 'public.evidence_links', 'reason', 'INSERT')",
        "has_column_privilege(role_name, 'public.personal_memory_grants', 'status', 'UPDATE')",
        "has_column_privilege(role_name, 'public.personal_memory_grants', 'updated_at', 'UPDATE')",
        "has_column_privilege(role_name, 'public.personal_memory_grants', 'failure_stage', 'UPDATE')",
        "has_column_privilege(role_name, 'public.personal_memory_grants', 'memory_filter_json', 'UPDATE')",
        "has_column_privilege(role_name, 'public.personal_memory_grants', 'target_run_id', 'UPDATE')",
    ]
    for check in column_checks:
        assert check in text


def test_control_plane_role_memory_grant_is_fixed_ts_authority():
    """Memory read/proposal-create/apply grants are fixed TS-owned."""
    text = _script()

    assert "CONTROL_PLANE_MEMORY_AUTHORITY" not in text
    assert "CONTROL_PLANE_MEMORY_APPLY_AUTHORITY" not in text
    assert r'GRANT SELECT, INSERT, UPDATE ON TABLE public.memory_entries TO \"$role\";' in text
    assert r'GRANT SELECT ON TABLE public.projects TO \"$role\";' in text
    assert r'GRANT INSERT ON TABLE public.proposals TO \"$role\";' in text
    assert r'GRANT INSERT ON TABLE public.memory_access_logs TO \"$role\";' in text
    assert r'GRANT SELECT, INSERT ON TABLE public.provenance_links TO \"$role\";' in text
    assert r'GRANT INSERT ON TABLE public.memory_relations TO \"$role\";' in text
    assert "DELETE ON TABLE public.memory_entries" not in text
    assert "GRANT SELECT ON TABLE public.memory_access_logs" not in text
    assert "('memory_entries', 'SELECT')" in text
    assert "('projects', 'SELECT')" in text
    assert "('proposals', 'INSERT')" in text
    assert "('memory_access_logs', 'INSERT')" in text
    assert "('memory_entries', 'INSERT')" in text
    assert "('memory_entries', 'UPDATE')" in text
    assert "('memory_entries', 'DELETE')" in text
    assert "('provenance_links', 'SELECT')" in text
    assert "('provenance_links', 'INSERT')" in text
    assert "('memory_relations', 'INSERT')" in text
    # memory_access_logs SELECT is denied in both modes (read model never reads logs).
    assert "('memory_access_logs', 'SELECT')" in text


def test_control_plane_role_memory_apply_grant_is_not_switch_gated():
    text = _script()

    assert "memory_apply_authority" not in text
    assert "CONTROL_PLANE_MEMORY_APPLY_AUTHORITY" not in text

    assert (
        r'GRANT SELECT, INSERT, UPDATE ON TABLE public.memory_entries TO \"$role\";'
        in text
    )
    assert r'GRANT SELECT, INSERT ON TABLE public.provenance_links TO \"$role\";' in text
    assert r'GRANT INSERT ON TABLE public.memory_relations TO \"$role\";' in text
    assert "GRANT DELETE ON TABLE public.memory_entries" not in text
    assert "Spaces read access belongs" in text


def test_control_plane_role_leaf_domain_grants_are_fixed_ts_authority():
    """Activity/intake/knowledge/tasks leaf domains are TS-owned."""
    text = _script()

    required_grants = [
        r'GRANT SELECT, INSERT, UPDATE ON TABLE public.activity_records TO \"$role\";',
        'GRANT SELECT, INSERT ON TABLE public.artifacts TO "$role";',
        r'GRANT SELECT ON TABLE public.source_connectors TO \"$role\";',
        r'GRANT SELECT, INSERT, UPDATE ON TABLE public.source_connections TO \"$role\";',
        r'GRANT SELECT, INSERT, UPDATE ON TABLE public.intake_items TO \"$role\";',
        r'GRANT SELECT, INSERT, UPDATE ON TABLE public.extraction_jobs TO \"$role\";',
        r'GRANT SELECT, INSERT, UPDATE ON TABLE public.workspace_intake_profiles TO \"$role\";',
        r'GRANT SELECT, INSERT ON TABLE public.workspace_source_bindings TO \"$role\";',
        r'GRANT SELECT, INSERT, UPDATE ON TABLE public.boards TO \"$role\";',
        r'GRANT SELECT, INSERT ON TABLE public.board_columns TO \"$role\";',
        r'GRANT SELECT, INSERT, UPDATE ON TABLE public.tasks TO \"$role\";',
        r'GRANT SELECT, INSERT ON TABLE public.task_runs TO \"$role\";',
        r'GRANT SELECT, INSERT ON TABLE public.task_evaluations TO \"$role\";',
        r'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.notes TO \"$role\";',
        r'GRANT SELECT, INSERT, UPDATE ON TABLE public.knowledge_item_relations TO \"$role\";',
    ]
    for grant in required_grants:
        assert grant in text

    assert "('artifacts', 'INSERT')" in text
    assert "('intake_items', 'INSERT')" in text
    assert "('tasks', 'UPDATE')" in text
    assert "('notes', 'DELETE')" in text
    assert "('task_artifacts', 'INSERT')" in text
    assert "('artifacts', 'UPDATE')" in text


def test_control_plane_role_scheduler_grants_cover_automations_daily_reports_and_retention():
    """Jobs/schedulers/automations/daily reports are TS-owned."""
    text = _script()

    required_grants = [
        r'GRANT SELECT, INSERT, UPDATE ON TABLE public.automations TO \"$role\";',
        r'GRANT SELECT, INSERT ON TABLE public.automation_runs TO \"$role\";',
        r'GRANT SELECT, INSERT, UPDATE ON TABLE public.automation_credential_grants TO \"$role\";',
        r'GRANT SELECT, INSERT, UPDATE ON TABLE public.daily_capture_report_settings TO \"$role\";',
        r'GRANT INSERT (id, space_id, owner_user_id, name, description, role_instruction, status, agent_kind, visibility, created_at, updated_at) ON TABLE public.agents TO \"$role\";',
        r'GRANT UPDATE (name, description, role_instruction, status, visibility, current_version_id, updated_at) ON TABLE public.agents TO \"$role\";',
        r'GRANT INSERT (id, agent_id, space_id, version_label, model_provider_id, model_name, system_prompt, model_config_json, runtime_config_json, context_policy_json, memory_policy_json, capabilities_json, tool_permissions_json, runtime_policy_json, tool_policy_json, output_policy_json, schedule_config_json, output_schema_json, created_at) ON TABLE public.agent_versions TO \"$role\";',
        r'GRANT SELECT, INSERT, UPDATE ON TABLE public.space_assistant_settings TO \"$role\";',
        r'GRANT SELECT (accessed_at) ON TABLE public.memory_access_logs TO \"$role\";',
        r'GRANT DELETE ON TABLE public.memory_access_logs TO \"$role\";',
    ]
    for grant in required_grants:
        assert grant in text

    column_checks = [
        "has_column_privilege(role_name, 'public.agents', 'id', 'INSERT')",
        "has_column_privilege(role_name, 'public.agents', 'owner_user_id', 'INSERT')",
        "has_column_privilege(role_name, 'public.agents', 'name', 'UPDATE')",
        "has_column_privilege(role_name, 'public.agents', 'current_version_id', 'UPDATE')",
        "has_column_privilege(role_name, 'public.agent_versions', 'model_provider_id', 'INSERT')",
        "has_column_privilege(role_name, 'public.agent_versions', 'runtime_config_json', 'INSERT')",
        "has_column_privilege(role_name, 'public.agent_versions', 'tool_policy_json', 'INSERT')",
        "has_table_privilege(role_name, 'public.space_assistant_settings', 'INSERT')",
        "has_column_privilege(role_name, 'public.memory_access_logs', 'accessed_at', 'SELECT')",
    ]
    for check in column_checks:
        assert check in text


def test_control_plane_role_provisioning_is_fixed_and_cascades_remaining_switches():
    text = _script()

    assert "local_compose_control_plane_ts_authority_enabled() {\n  return 0\n}" in text
    assert "CONTROL_PLANE_RUNS_AUTHORITY" not in text
    assert "CONTROL_PLANE_PROPOSALS_AUTHORITY" not in text
    assert "CONTROL_PLANE_CHAT_TURN_AUTHORITY" not in text
    assert "CONTROL_PLANE_CONTEXT_AUTHORITY" not in text
    assert "CONTROL_PLANE_MEMORY_AUTHORITY" not in text
    assert "CONTROL_PLANE_MEMORY_APPLY_AUTHORITY" not in text
    assert "CONTROL_PLANE_PROVIDERS_CREDENTIALS_AUTHORITY" not in text
    assert "CONTROL_PLANE_POLICY_AUTHORITY" not in text
    assert "CONTROL_PLANE_SESSIONS_AUTHORITY" not in text
