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
        'GRANT SELECT, INSERT ON TABLE public.actors TO "$role";',
        'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.run_execution_locks TO "$role";',
        'GRANT SELECT, UPDATE ON TABLE public.jobs TO "$role";',
        'GRANT SELECT, INSERT ON TABLE public.job_events TO "$role";',
        'GRANT SELECT ON TABLE public.execution_planes TO "$role";',
        'GRANT SELECT ON TABLE public.agents TO "$role";',
        'GRANT SELECT ON TABLE public.agent_versions TO "$role";',
        'GRANT SELECT, INSERT ON TABLE public.policy_decision_records TO "$role";',
        'GRANT SELECT, UPDATE ON TABLE public.proposals TO "$role";',
        'GRANT SELECT, INSERT, UPDATE ON TABLE public.proposal_approvals TO "$role";',
    ]
    for grant in required_grants:
        assert grant in text

    forbidden_direct_grants = [
        # memory_entries SELECT is now a conditional grant (memory-read slice),
        # so it is no longer unconditionally forbidden — see the memory-read test.
        "GRANT SELECT ON TABLE public.memory_access_logs",
        "GRANT SELECT ON TABLE public.activity_records",
        "GRANT UPDATE ON TABLE public.policy_decision_records",
        "GRANT DELETE ON TABLE public.policy_decision_records",
        # proposals INSERT is now a conditional grant (memory proposal-create
        # slice), so it is no longer unconditionally forbidden.
        "GRANT DELETE ON TABLE public.proposals",
        "GRANT DELETE ON TABLE public.proposal_approvals",
        "GRANT SELECT ON TABLE public.artifacts",
        "GRANT INSERT ON TABLE public.jobs",
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
    assert "('memory_entries', 'SELECT')" in text
    assert "('policy_decision_records', 'SELECT')" in text
    assert "('policy_decision_records', 'INSERT')" in text
    assert "('policy_decision_records', 'UPDATE')" in text
    assert "('proposals', 'SELECT')" in text
    assert "('proposals', 'UPDATE')" in text
    assert "('proposal_approvals', 'INSERT')" in text
    assert "('proposal_approvals', 'DELETE')" in text
    assert "('context_snapshots', 'SELECT')" in text
    assert "('context_snapshot_items', 'SELECT')" in text
    assert "unexpectedly has %.% privilege" in text


def test_control_plane_role_provisioning_uses_readable_quiet_logs():
    text = _script()

    assert "psql -X -q -v ON_ERROR_STOP=1" in text
    assert (
        "applying least-privilege provider, run, job, runtime metadata, policy audit, "
        "proposal review, and (when flipped) sessions, context-snapshot, and memory grants"
    ) in text
    assert "verified required grants and denied unrelated context-table access" in text
    assert "Control-plane DB role '$role' is ready." in text


def test_control_plane_role_sessions_grant_is_per_slice_and_dormant_by_default():
    """Stage 6 S7: session/message grants are gated on the sessions switch.

    By default (`python`) the cp role gets no session access — the smoke test's
    denied list asserts it. When `CONTROL_PLANE_SESSIONS_AUTHORITY=ts` the role
    gains the read model plus create/append: SELECT/INSERT/UPDATE on sessions,
    SELECT/INSERT on messages, and SELECT on session_summaries for latest-summary
    context reads. Sessions are never DELETEd, messages are append-only, and
    summary writes remain Python-owned, so those privileges stay denied in both
    modes.
    """
    text = _script()

    # The switch drives a conditional grant block (dormant unless flipped).
    assert (
        'sessions_authority="$(local_compose_setting_or_default '
        'CONTROL_PLANE_SESSIONS_AUTHORITY python)"'
    ) in text
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
    # The conditional rows (required when ts / denied when python) are present.
    assert "('sessions', 'INSERT')" in text
    assert "('sessions', 'UPDATE')" in text
    assert "('messages', 'INSERT')" in text
    assert "('sessions', 'SELECT')" in text
    assert "('messages', 'SELECT')," in text
    assert "('session_summaries', 'SELECT')," in text


def test_control_plane_role_context_grant_is_per_slice_and_dormant_by_default():
    """Stage 6 slice 4: context-snapshot grants are gated on the context switch.

    By default (`python`) the cp role gets no context-snapshot access — the smoke
    test's denied list asserts it. When `CONTROL_PLANE_CONTEXT_AUTHORITY=ts` the
    TS chat turn owns the ChatContextBuilder selection loop and snapshot
    persistence, so the role gains SELECT/INSERT/UPDATE on context_snapshots and
    context_snapshot_items. memory_access_logs is never granted (the chat path
    does not write access logs).
    """
    text = _script()

    assert (
        'context_authority="$(local_compose_setting_or_default '
        'CONTROL_PLANE_CONTEXT_AUTHORITY python)"'
    ) in text
    assert (
        r'GRANT SELECT, INSERT, UPDATE ON TABLE public.context_snapshots TO \"$role\";'
        in text
    )
    assert (
        r'GRANT SELECT, INSERT, UPDATE ON TABLE public.context_snapshot_items TO \"$role\";'
        in text
    )
    # The chat path does not write access logs, so they stay denied.
    assert "GRANT SELECT ON TABLE public.memory_access_logs" not in text
    assert "('memory_access_logs', 'SELECT')" in text
    # The conditional rows (required when ts / denied when python) are present.
    assert "('context_snapshots', 'INSERT')" in text
    assert "('context_snapshots', 'UPDATE')" in text
    assert "('context_snapshot_items', 'INSERT')" in text
    assert "('context_snapshot_items', 'UPDATE')" in text


def test_control_plane_role_memory_grant_is_per_slice_and_dormant_by_default():
    """Stage 6 slices 5-6 + 7a: memory grants are gated on the memory switch.

    By default (`python`) the cp role gets no memory/project access — the smoke
    test's denied list asserts it. When `CONTROL_PLANE_MEMORY_AUTHORITY=ts` the TS
    read model gains SELECT on memory_entries (and projects, for the project_id
    filter), memory proposal routes gain INSERT on proposals for pending proposal
    rows, and slice 7a read-access logging gains INSERT on memory_access_logs plus
    a COLUMN-SCOPED UPDATE on memory_entries(access_count, last_accessed_at).
    Table-wide active memory writes stay denied until the separate apply switch
    is flipped.
    """
    text = _script()

    assert (
        'memory_authority="$(local_compose_setting_or_default '
        'CONTROL_PLANE_MEMORY_AUTHORITY python)"'
    ) in text
    assert r'GRANT SELECT ON TABLE public.memory_entries TO \"$role\";' in text
    assert r'GRANT SELECT ON TABLE public.projects TO \"$role\";' in text
    assert r'GRANT INSERT ON TABLE public.proposals TO \"$role\";' in text
    # Slice 7a: read-access logging grants — log INSERT and a column-scoped
    # counter UPDATE only (never table-wide memory_entries write).
    assert r'GRANT INSERT ON TABLE public.memory_access_logs TO \"$role\";' in text
    assert (
        r'GRANT UPDATE (access_count, last_accessed_at) ON TABLE '
        r'public.memory_entries TO \"$role\";'
    ) in text
    assert "DELETE ON TABLE public.memory_entries" not in text
    assert "GRANT SELECT ON TABLE public.memory_access_logs" not in text
    # Conditional rows present (required when ts / denied when python).
    assert "('memory_entries', 'SELECT')" in text
    assert "('projects', 'SELECT')" in text
    assert "('proposals', 'INSERT')" in text
    assert "('memory_access_logs', 'INSERT')" in text
    # Table-level write-denial rows: memory_entries UPDATE stays denied at the
    # table level (the slice-7a grant is column-scoped, so has_table_privilege
    # still reports UPDATE as denied), and INSERT/DELETE are fully denied.
    assert "('memory_entries', 'INSERT')" in text
    assert "('memory_entries', 'UPDATE')" in text
    assert "('memory_entries', 'DELETE')" in text
    assert "('provenance_links', 'INSERT')" in text
    assert "('memory_relations', 'INSERT')" in text
    assert "('spaces', 'SELECT')" in text
    # Column-privilege checks enforce the exact 7a scope.
    assert (
        "has_column_privilege(role_name, 'public.memory_entries', "
        "'access_count', 'UPDATE')"
    ) in text
    assert (
        "has_column_privilege(role_name, 'public.memory_entries', "
        "'content', 'UPDATE')"
    ) in text
    # memory_access_logs SELECT is denied in both modes (read model never reads logs).
    assert "('memory_access_logs', 'SELECT')" in text


def test_control_plane_role_memory_apply_grant_adds_apply_tier_only_when_flipped():
    """Stage 6 slice 7b: active-memory apply grants are separately gated.

    `CONTROL_PLANE_MEMORY_AUTHORITY=ts` alone is still the 7a tier: read model,
    proposal creation, access-log insert, and column-scoped counter bumps only.
    With `CONTROL_PLANE_MEMORY_APPLY_AUTHORITY=ts`, TS gets the table-wide write
    grants it needs to apply accepted memory proposals.
    """
    text = _script()

    assert (
        'memory_apply_authority="$(local_compose_setting_or_default '
        'CONTROL_PLANE_MEMORY_APPLY_AUTHORITY python)"'
    ) in text
    assert (
        '[[ "${memory_authority,,}" == "ts" && '
        '"${memory_apply_authority,,}" == "ts" ]]'
    ) in text

    assert (
        r'GRANT SELECT, INSERT, UPDATE ON TABLE public.memory_entries TO \"$role\";'
        in text
    )
    assert r'GRANT INSERT ON TABLE public.provenance_links TO \"$role\";' in text
    assert r'GRANT INSERT ON TABLE public.memory_relations TO \"$role\";' in text
    assert r'GRANT SELECT (id, type) ON TABLE public.spaces TO \"$role\";' in text
    assert "GRANT DELETE ON TABLE public.memory_entries" not in text
    assert "GRANT SELECT ON TABLE public.spaces" not in text

    # The non-apply branch must continue to deny apply table writes and enforce
    # the exact 7a column scope.
    assert "INSERT/DELETE + apply tables stay fully denied" in text
    assert (
        "has_column_privilege(role_name, 'public.memory_entries', "
        "'content', 'UPDATE')"
    ) in text
    assert (
        "has_column_privilege(role_name, 'public.memory_entries', "
        "'visibility', 'UPDATE')"
    ) in text
    assert (
        "has_column_privilege(role_name, 'public.spaces', "
        "'id', 'SELECT')"
    ) in text
    assert (
        "has_column_privilege(role_name, 'public.spaces', "
        "'type', 'SELECT')"
    ) in text
    assert (
        "has_column_privilege(role_name, 'public.spaces', "
        "'name', 'SELECT')"
    ) in text
    assert (
        "REVOKE UPDATE (access_count, last_accessed_at) ON TABLE "
        'public.memory_entries FROM "$role";'
    ) in text
    assert 'REVOKE SELECT (id, type) ON TABLE public.spaces FROM "$role";' in text


def test_runs_ts_authority_triggers_control_plane_role_provisioning():
    text = _script()

    assert "CONTROL_PLANE_RUNS_AUTHORITY" in text
    assert "CONTROL_PLANE_POLICY_AUTHORITY" in text
    assert "CONTROL_PLANE_PROPOSALS_AUTHORITY" in text
    assert "CONTROL_PLANE_CHAT_TURN_AUTHORITY" in text
    assert "CONTROL_PLANE_CONTEXT_AUTHORITY" in text
    assert "CONTROL_PLANE_MEMORY_AUTHORITY" in text
    assert "CONTROL_PLANE_MEMORY_APPLY_AUTHORITY" in text
    assert "runs_authority=\"$(local_compose_setting_or_default CONTROL_PLANE_RUNS_AUTHORITY python)\"" in text
    assert "policy_authority=\"$(local_compose_setting_or_default CONTROL_PLANE_POLICY_AUTHORITY python)\"" in text
    assert "proposals_authority=\"$(local_compose_setting_or_default CONTROL_PLANE_PROPOSALS_AUTHORITY python)\"" in text
    assert "chat_turn_authority=\"$(local_compose_setting_or_default CONTROL_PLANE_CHAT_TURN_AUTHORITY python)\"" in text
    assert "context_authority=\"$(local_compose_setting_or_default CONTROL_PLANE_CONTEXT_AUTHORITY python)\"" in text
    assert "memory_apply_authority=\"$(local_compose_setting_or_default CONTROL_PLANE_MEMORY_APPLY_AUTHORITY python)\"" in text
    assert '[[ "${credentials_authority,,}" == "ts" || "${runs_authority,,}" == "ts" || "${policy_authority,,}" == "ts" || "${proposals_authority,,}" == "ts" || "${sessions_authority,,}" == "ts" || "${chat_turn_authority,,}" == "ts" || "${context_authority,,}" == "ts" || "${memory_authority,,}" == "ts" || "${memory_apply_authority,,}" == "ts" ]]' in text
    assert "CONTROL_PLANE_PROVIDERS_CREDENTIALS_AUTHORITY ts" in text
    assert "CONTROL_PLANE_POLICY_AUTHORITY ts" in text
    assert "CONTROL_PLANE_PROPOSALS_AUTHORITY ts" in text
    assert "CONTROL_PLANE_SESSIONS_AUTHORITY ts" in text
    assert "CONTROL_PLANE_CHAT_TURN_AUTHORITY ts" in text
    assert "CONTROL_PLANE_CONTEXT_AUTHORITY ts" in text
    assert "CONTROL_PLANE_MEMORY_AUTHORITY ts" in text
    assert "CONTROL_PLANE_MEMORY_APPLY_AUTHORITY ts" in text
