"""API contract tests: PersonalMemoryGrant endpoints.

Phase 8B implemented. Phase B tests pass.
Phase C/D/E tests pass: context integration, egress guard, and the granting-user
proposal approval gate are implemented.

Endpoint contracts verified:
  POST /api/v1/personal-memory-grants/preview
  POST /api/v1/personal-memory-grants
  GET  /api/v1/personal-memory-grants
  POST /api/v1/personal-memory-grants/{grant_id}/revoke
  GET  /api/v1/personal-memory-grants/{grant_id}/audit
"""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient
from ulid import ULID

from app.auth.session import SESSION_COOKIE, UserSessionService
from app.main import app as _app
from app.models import SpaceMembership
from app.personal_memory_grants.service import MAX_ACTIVE_CONSUMING_GRANTS, MAX_GRANTS_PER_HOUR
from tests.support import factories


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _new_id() -> str:
    return str(ULID())


def _authed_client(db, user_id: str, space_id: str) -> TestClient:
    """Create a TestClient authenticated as user_id with default_space_id = space_id."""
    _, raw = UserSessionService(db).create(user_id)
    return TestClient(_app, cookies={SESSION_COOKIE: raw}, raise_server_exceptions=True)


def _setup_grant_scenario(db):
    """Create a personal user, team space, and a run instructed by that user.

    Returns:
        user: User ORM object
        personal_id: personal space ID (user owns it)
        team_id: team space ID (user is a member)
        run: Run ORM object in team_id, instructed_by_user_id=user.id
    """
    personal_id = _new_id()
    factories.create_test_space(db, space_id=personal_id, name="Personal", space_type="personal")
    user = factories.create_test_user(db, space_id=personal_id, display_name="Grant User")
    # create_test_user already adds SpaceMembership(personal_id, user.id, role="owner")

    # Set default_space_id so get_identity can resolve space without a query param
    user.default_space_id = personal_id
    db.flush()

    team_id = _new_id()
    factories.create_test_space(db, space_id=team_id, name="Team", space_type="team")
    db.add(SpaceMembership(
        id=_new_id(), space_id=team_id, user_id=user.id, role="member", status="active",
    ))
    db.flush()

    run = factories.create_test_run(db, space_id=team_id, user_id=user.id)
    db.commit()

    return {"user": user, "personal_id": personal_id, "team_id": team_id, "run": run}


# ---------------------------------------------------------------------------
# Phase B passing tests
# ---------------------------------------------------------------------------


def test_create_run_scoped_summary_only_grant(db, client):
    """POST /api/v1/personal-memory-grants returns 201 with a valid run-scoped summary_only grant."""
    s = _setup_grant_scenario(db)
    ac = _authed_client(db, s["user"].id, s["personal_id"])

    resp = ac.post("/api/v1/personal-memory-grants", json={
        "target_space_id": s["team_id"],
        "target_run_id": s["run"].id,
        "access_mode": "summary_only",
        "memory_filter": {
            "schema_version": 1,
            "memory_layers": ["semantic"],
            "memory_kinds": ["preference", "reflection"],
            "max_items": 20,
        },
        "read_expires_in_seconds": 3600,
    })
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["grant_scope"] == "run"
    assert data["access_mode"] == "summary_only"
    assert data["status"] == "active"
    assert data["target_run_id"] == s["run"].id
    assert data.get("target_agent_id") is None


def test_create_grant_derives_granting_user_from_auth(db, client):
    """POST /api/v1/personal-memory-grants must derive granting_user_id from authenticated session."""
    s = _setup_grant_scenario(db)
    ac = _authed_client(db, s["user"].id, s["personal_id"])

    resp = ac.post("/api/v1/personal-memory-grants", json={
        "target_space_id": s["team_id"],
        "target_run_id": s["run"].id,
        "access_mode": "summary_only",
        "read_expires_in_seconds": 300,
    })
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert "granting_user_id" in data
    assert data["granting_user_id"] == s["user"].id
    assert data["granting_user_id"] != "client-supplied"


def test_create_grant_rejects_client_supplied_granting_user_id(db, client):
    """POST /api/v1/personal-memory-grants must reject client-supplied granting_user_id.

    GrantCreate schema uses extra='forbid', so the extra field returns 422.
    """
    s = _setup_grant_scenario(db)
    ac = _authed_client(db, s["user"].id, s["personal_id"])

    resp = ac.post("/api/v1/personal-memory-grants", json={
        "granting_user_id": "attacker-trying-to-spoof-user",
        "target_space_id": s["team_id"],
        "target_run_id": s["run"].id,
        "access_mode": "summary_only",
        "read_expires_in_seconds": 300,
    })
    assert resp.status_code in (400, 422), resp.text


def test_create_grant_requires_target_space_membership(db, client):
    """POST /api/v1/personal-memory-grants rejects if granting user is not a member of target_space_id."""
    s = _setup_grant_scenario(db)
    ac = _authed_client(db, s["user"].id, s["personal_id"])

    other_space_id = _new_id()
    factories.create_test_space(db, space_id=other_space_id, name="Other", space_type="team")
    db.commit()

    resp = ac.post("/api/v1/personal-memory-grants", json={
        "target_space_id": other_space_id,
        "target_run_id": s["run"].id,
        "access_mode": "summary_only",
        "read_expires_in_seconds": 300,
    })
    assert resp.status_code in (400, 403), resp.text


def test_create_grant_requires_target_run_in_target_space(db, client):
    """POST /api/v1/personal-memory-grants rejects if target_run_id is not in target_space_id."""
    s = _setup_grant_scenario(db)
    ac = _authed_client(db, s["user"].id, s["personal_id"])

    # Create another team space the user is a member of, but pass run from original team_id
    other_team_id = _new_id()
    factories.create_test_space(db, space_id=other_team_id, name="Other Team", space_type="team")
    db.add(SpaceMembership(
        id=_new_id(), space_id=other_team_id, user_id=s["user"].id, role="member", status="active",
    ))
    db.commit()

    resp = ac.post("/api/v1/personal-memory-grants", json={
        "target_space_id": other_team_id,
        "target_run_id": s["run"].id,   # run is in team_id, not other_team_id
        "access_mode": "summary_only",
        "read_expires_in_seconds": 300,
    })
    assert resp.status_code in (400, 403), resp.text


def test_create_grant_requires_target_run_instructed_by_current_user(db, client):
    """POST /api/v1/personal-memory-grants rejects if run.instructed_by_user_id != current user."""
    s = _setup_grant_scenario(db)
    ac = _authed_client(db, s["user"].id, s["personal_id"])

    # Create a second user who instructed a run in the same team space
    other_user_personal_id = _new_id()
    factories.create_test_space(db, space_id=other_user_personal_id, name="Other Personal", space_type="personal")
    other_user = factories.create_test_user(db, space_id=other_user_personal_id, display_name="Other User")
    db.add(SpaceMembership(
        id=_new_id(), space_id=s["team_id"], user_id=other_user.id, role="member", status="active",
    ))
    db.flush()
    other_run = factories.create_test_run(db, space_id=s["team_id"], user_id=other_user.id)
    db.commit()

    # s["user"] tries to grant access for a run instructed by other_user → 400/403
    resp = ac.post("/api/v1/personal-memory-grants", json={
        "target_space_id": s["team_id"],
        "target_run_id": other_run.id,
        "access_mode": "summary_only",
        "read_expires_in_seconds": 300,
    })
    assert resp.status_code in (400, 403), resp.text


def test_create_grant_rejects_target_agent_id(db, client):
    """POST /api/v1/personal-memory-grants rejects target_agent_id (extra='forbid' → 422)."""
    s = _setup_grant_scenario(db)
    ac = _authed_client(db, s["user"].id, s["personal_id"])

    resp = ac.post("/api/v1/personal-memory-grants", json={
        "target_space_id": s["team_id"],
        "target_run_id": s["run"].id,
        "target_agent_id": "some-agent-id",
        "access_mode": "summary_only",
        "read_expires_in_seconds": 300,
    })
    assert resp.status_code in (400, 422), resp.text


def test_create_grant_requires_read_expires_at(db, client):
    """POST /api/v1/personal-memory-grants rejects missing read_expires_in_seconds."""
    s = _setup_grant_scenario(db)
    ac = _authed_client(db, s["user"].id, s["personal_id"])

    resp = ac.post("/api/v1/personal-memory-grants", json={
        "target_space_id": s["team_id"],
        "target_run_id": s["run"].id,
        "access_mode": "summary_only",
        # intentionally omitting read_expires_in_seconds
    })
    assert resp.status_code in (400, 422), resp.text


def test_create_grant_rejects_scope_types_semantic_preference_filters(db, client):
    """POST /api/v1/personal-memory-grants rejects memory_filter with scope_types key."""
    s = _setup_grant_scenario(db)
    ac = _authed_client(db, s["user"].id, s["personal_id"])

    resp = ac.post("/api/v1/personal-memory-grants", json={
        "target_space_id": s["team_id"],
        "target_run_id": s["run"].id,
        "access_mode": "summary_only",
        "read_expires_in_seconds": 300,
        "memory_filter": {
            "schema_version": 1,
            "scope_types": ["semantic", "preference"],  # rejected key
        },
    })
    assert resp.status_code in (400, 422), resp.text


def test_revoke_grant_by_owner(db, client):
    """POST /api/v1/personal-memory-grants/{grant_id}/revoke succeeds for grant owner."""
    s = _setup_grant_scenario(db)
    ac = _authed_client(db, s["user"].id, s["personal_id"])

    create_resp = ac.post("/api/v1/personal-memory-grants", json={
        "target_space_id": s["team_id"],
        "target_run_id": s["run"].id,
        "access_mode": "summary_only",
        "read_expires_in_seconds": 300,
    })
    assert create_resp.status_code == 201, create_resp.text
    grant_id = create_resp.json()["id"]

    revoke_resp = ac.post(f"/api/v1/personal-memory-grants/{grant_id}/revoke")
    assert revoke_resp.status_code == 200, revoke_resp.text
    assert revoke_resp.json()["status"] == "revoked"


def test_revoke_grant_by_other_user_rejected(db, client):
    """POST /api/v1/personal-memory-grants/{grant_id}/revoke returns 403 for a non-owner."""
    s = _setup_grant_scenario(db)
    ac_owner = _authed_client(db, s["user"].id, s["personal_id"])

    # User A creates a grant
    create_resp = ac_owner.post("/api/v1/personal-memory-grants", json={
        "target_space_id": s["team_id"],
        "target_run_id": s["run"].id,
        "access_mode": "summary_only",
        "read_expires_in_seconds": 300,
    })
    assert create_resp.status_code == 201, create_resp.text
    grant_id = create_resp.json()["id"]

    # User B has their own personal space (no access to User A's grant)
    b_personal_id = _new_id()
    factories.create_test_space(db, space_id=b_personal_id, name="B Personal", space_type="personal")
    user_b = factories.create_test_user(db, space_id=b_personal_id, display_name="User B")
    user_b.default_space_id = b_personal_id
    db.commit()

    ac_b = _authed_client(db, user_b.id, b_personal_id)
    revoke_resp = ac_b.post(f"/api/v1/personal-memory-grants/{grant_id}/revoke")
    assert revoke_resp.status_code == 403, revoke_resp.text


def test_list_grants_returns_only_current_users_grants(db, client):
    """GET /api/v1/personal-memory-grants returns only the authenticated user's grants."""
    s = _setup_grant_scenario(db)
    ac = _authed_client(db, s["user"].id, s["personal_id"])

    # Create a grant
    ac.post("/api/v1/personal-memory-grants", json={
        "target_space_id": s["team_id"],
        "target_run_id": s["run"].id,
        "access_mode": "summary_only",
        "read_expires_in_seconds": 300,
    })

    # List
    resp = ac.get("/api/v1/personal-memory-grants")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert isinstance(data, list)
    for grant in data:
        assert grant["granting_user_id"] == s["user"].id


# ---------------------------------------------------------------------------
# Additional Phase B tests
# ---------------------------------------------------------------------------


def test_preview_returns_structural_data_and_creates_no_grant(db, client):
    """POST /api/v1/personal-memory-grants/preview returns structural preview without creating a grant."""
    s = _setup_grant_scenario(db)
    ac = _authed_client(db, s["user"].id, s["personal_id"])

    resp = ac.post("/api/v1/personal-memory-grants/preview", json={
        "target_space_id": s["team_id"],
        "target_run_id": s["run"].id,
        "access_mode": "summary_only",
        "read_expires_in_seconds": 300,
    })
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["eligible"] is True
    assert data["target_space_id"] == s["team_id"]
    assert data["target_run_id"] == s["run"].id
    assert data["access_mode"] == "summary_only"
    assert isinstance(data["warnings"], list)

    # No grant created
    list_resp = ac.get("/api/v1/personal-memory-grants")
    assert list_resp.json() == []


def test_preview_does_not_return_memory_text_or_ids(db, client):
    """POST /api/v1/personal-memory-grants/preview must not expose raw memory text or memory IDs."""
    s = _setup_grant_scenario(db)
    ac = _authed_client(db, s["user"].id, s["personal_id"])

    resp = ac.post("/api/v1/personal-memory-grants/preview", json={
        "target_space_id": s["team_id"],
        "target_run_id": s["run"].id,
        "access_mode": "summary_only",
    })
    assert resp.status_code == 200, resp.text
    raw = resp.text
    assert "memory_text" not in raw
    assert "raw_content" not in raw
    assert "generated_summary" not in raw
    assert "personal_memory_text" not in raw


def test_audit_returns_safe_event_metadata(db, client):
    """GET /api/v1/personal-memory-grants/{id}/audit returns events without raw memory content."""
    s = _setup_grant_scenario(db)
    ac = _authed_client(db, s["user"].id, s["personal_id"])

    create_resp = ac.post("/api/v1/personal-memory-grants", json={
        "target_space_id": s["team_id"],
        "target_run_id": s["run"].id,
        "access_mode": "summary_only",
        "read_expires_in_seconds": 300,
    })
    assert create_resp.status_code == 201
    grant_id = create_resp.json()["id"]

    audit_resp = ac.get(f"/api/v1/personal-memory-grants/{grant_id}/audit")
    assert audit_resp.status_code == 200, audit_resp.text
    data = audit_resp.json()
    assert "grant" in data
    assert "events" in data
    assert isinstance(data["events"], list)
    assert len(data["events"]) >= 1
    # No content fields in event metadata
    raw = audit_resp.text
    assert "memory_text" not in raw
    assert "generated_summary" not in raw
    assert "personal_memory_text" not in raw


def test_create_enforces_active_consuming_limit(db, client):
    """POST /api/v1/personal-memory-grants rejects when active/consuming grant limit is reached."""
    personal_id = _new_id()
    factories.create_test_space(db, space_id=personal_id, name="Personal", space_type="personal")
    user = factories.create_test_user(db, space_id=personal_id, display_name="Rate User")
    user.default_space_id = personal_id

    team_id = _new_id()
    factories.create_test_space(db, space_id=team_id, name="Team", space_type="team")
    db.add(SpaceMembership(
        id=_new_id(), space_id=team_id, user_id=user.id, role="member", status="active",
    ))
    db.flush()

    # Create MAX_ACTIVE_CONSUMING_GRANTS separate runs (one grant each; unique index per user+run)
    runs = []
    for _ in range(MAX_ACTIVE_CONSUMING_GRANTS):
        r = factories.create_test_run(db, space_id=team_id, user_id=user.id)
        runs.append(r)
    db.commit()

    ac = _authed_client(db, user.id, personal_id)

    # Create the maximum number of grants
    for r in runs:
        resp = ac.post("/api/v1/personal-memory-grants", json={
            "target_space_id": team_id,
            "target_run_id": r.id,
            "access_mode": "summary_only",
            "read_expires_in_seconds": 300,
        })
        assert resp.status_code == 201, f"Expected 201 for run {r.id}: {resp.text}"

    # One more run; 11th grant must be rejected
    extra_run = factories.create_test_run(db, space_id=team_id, user_id=user.id)
    db.commit()

    resp = ac.post("/api/v1/personal-memory-grants", json={
        "target_space_id": team_id,
        "target_run_id": extra_run.id,
        "access_mode": "summary_only",
        "read_expires_in_seconds": 300,
    })
    assert resp.status_code == 429, f"Expected 429 (rate limited), got {resp.status_code}: {resp.text}"


def test_create_enforces_hourly_limit(db, client):
    """POST /api/v1/personal-memory-grants rejects when hourly grant limit is reached.

    Revoked grants still count toward the hourly limit.
    """
    personal_id = _new_id()
    factories.create_test_space(db, space_id=personal_id, name="Personal H", space_type="personal")
    user = factories.create_test_user(db, space_id=personal_id, display_name="Hourly User")
    user.default_space_id = personal_id

    team_id = _new_id()
    factories.create_test_space(db, space_id=team_id, name="Team H", space_type="team")
    db.add(SpaceMembership(
        id=_new_id(), space_id=team_id, user_id=user.id, role="member", status="active",
    ))
    db.flush()

    # Need MAX_GRANTS_PER_HOUR + 1 runs
    runs = []
    for _ in range(MAX_GRANTS_PER_HOUR + 1):
        r = factories.create_test_run(db, space_id=team_id, user_id=user.id)
        runs.append(r)
    db.commit()

    ac = _authed_client(db, user.id, personal_id)

    # Create MAX_GRANTS_PER_HOUR grants and revoke them (so active limit doesn't trigger)
    for r in runs[:MAX_GRANTS_PER_HOUR]:
        resp = ac.post("/api/v1/personal-memory-grants", json={
            "target_space_id": team_id,
            "target_run_id": r.id,
            "access_mode": "summary_only",
            "read_expires_in_seconds": 300,
        })
        assert resp.status_code == 201, f"Expected 201: {resp.text}"
        grant_id = resp.json()["id"]
        # Revoke so active limit doesn't trigger on the next iteration
        ac.post(f"/api/v1/personal-memory-grants/{grant_id}/revoke")

    # 21st grant (within the same hour) must be rejected by hourly limit
    resp = ac.post("/api/v1/personal-memory-grants", json={
        "target_space_id": team_id,
        "target_run_id": runs[MAX_GRANTS_PER_HOUR].id,
        "access_mode": "summary_only",
        "read_expires_in_seconds": 300,
    })
    assert resp.status_code == 429, f"Expected 429 (hourly limit), got {resp.status_code}: {resp.text}"


def test_duplicate_active_grant_for_same_user_run_returns_conflict(db, client):
    """POST /api/v1/personal-memory-grants returns 409 for duplicate active grant on same user+run."""
    s = _setup_grant_scenario(db)
    ac = _authed_client(db, s["user"].id, s["personal_id"])

    payload = {
        "target_space_id": s["team_id"],
        "target_run_id": s["run"].id,
        "access_mode": "summary_only",
        "read_expires_in_seconds": 300,
    }

    r1 = ac.post("/api/v1/personal-memory-grants", json=payload)
    assert r1.status_code == 201, r1.text

    r2 = ac.post("/api/v1/personal-memory-grants", json=payload)
    assert r2.status_code == 409, r2.text


def test_api_rejects_extra_fields_granting_user_id_and_personal_space_id(db, client):
    """POST /api/v1/personal-memory-grants rejects both granting_user_id and personal_space_id."""
    s = _setup_grant_scenario(db)
    ac = _authed_client(db, s["user"].id, s["personal_id"])

    resp = ac.post("/api/v1/personal-memory-grants", json={
        "granting_user_id": "spoofed",
        "personal_space_id": "spoofed",
        "target_space_id": s["team_id"],
        "target_run_id": s["run"].id,
        "access_mode": "summary_only",
        "read_expires_in_seconds": 300,
    })
    assert resp.status_code in (400, 422), resp.text


def test_api_rejects_unsupported_access_mode(db, client):
    """POST /api/v1/personal-memory-grants rejects access_mode other than summary_only."""
    s = _setup_grant_scenario(db)
    ac = _authed_client(db, s["user"].id, s["personal_id"])

    resp = ac.post("/api/v1/personal-memory-grants", json={
        "target_space_id": s["team_id"],
        "target_run_id": s["run"].id,
        "access_mode": "full_read",  # not allowed
        "read_expires_in_seconds": 300,
    })
    assert resp.status_code in (400, 422), resp.text


def test_revoked_grants_do_not_count_toward_active_limit(db, client):
    """Revoked grants are excluded from the active/consuming limit count."""
    s = _setup_grant_scenario(db)
    ac = _authed_client(db, s["user"].id, s["personal_id"])

    # Create and revoke a grant for the same run
    r1 = ac.post("/api/v1/personal-memory-grants", json={
        "target_space_id": s["team_id"],
        "target_run_id": s["run"].id,
        "access_mode": "summary_only",
        "read_expires_in_seconds": 300,
    })
    assert r1.status_code == 201
    grant_id = r1.json()["id"]

    ac.post(f"/api/v1/personal-memory-grants/{grant_id}/revoke")

    # Now recreate for same run (revoked does not hold the unique-index slot)
    r2 = ac.post("/api/v1/personal-memory-grants", json={
        "target_space_id": s["team_id"],
        "target_run_id": s["run"].id,
        "access_mode": "summary_only",
        "read_expires_in_seconds": 300,
    })
    assert r2.status_code == 201, r2.text


# ---------------------------------------------------------------------------
# Phase C — now passing; Phase D — now passing; Phase E — now passing
# ---------------------------------------------------------------------------

def test_shared_run_with_valid_grant_receives_personal_context(db, client):
    """Phase C: resolver returns a personal memory summary when a valid grant exists.

    Verifies the service-level contract: a valid active grant causes
    resolve_personal_memory_context_for_run to return a non-empty
    personal_context_block and transition the grant to 'used'.
    """
    from datetime import UTC, datetime, timedelta
    from app.models import MemoryEntry, PersonalMemoryGrant
    from app.personal_memory_grants.resolver import resolve_personal_memory_context_for_run

    s = _setup_grant_scenario(db)
    user, personal_id, team_id, run = s["user"], s["personal_id"], s["team_id"], s["run"]

    # Add private memory to personal space
    mem = MemoryEntry(
        id=_new_id(),
        space_id=personal_id,
        scope_type="user",
        memory_type="semantic",
        content="personal work context",
        status="active",
        visibility="private",
        owner_user_id=user.id,
        subject_user_id=user.id,
        sensitivity_level="normal",
    )
    db.add(mem)

    grant = PersonalMemoryGrant(
        id=_new_id(),
        granting_user_id=user.id,
        personal_space_id=personal_id,
        target_space_id=team_id,
        target_run_id=run.id,
        target_agent_id=None,
        grant_scope="run",
        access_mode="summary_only",
        status="active",
        memory_filter_json=None,
        read_expires_at=datetime.now(UTC) + timedelta(seconds=3600),
    )
    db.add(grant)
    db.commit()

    result = resolve_personal_memory_context_for_run(db, run=run)
    db.commit()

    assert result.has_personal_context, "Resolver must return non-empty personal context for valid grant"
    assert result.memory_count >= 1

    db.refresh(grant)
    assert grant.status == "used"


def test_grant_consumed_after_context_build(db, client):
    """Phase C: grant transitions active→consuming→used atomically; reuse is blocked.

    After resolve_personal_memory_context_for_run succeeds, the grant is marked
    'used' and a subsequent call returns no personal context.
    """
    from datetime import UTC, datetime, timedelta
    from app.models import MemoryEntry, PersonalMemoryGrant
    from app.personal_memory_grants.resolver import resolve_personal_memory_context_for_run

    s = _setup_grant_scenario(db)
    user, personal_id, team_id, run = s["user"], s["personal_id"], s["team_id"], s["run"]

    mem = MemoryEntry(
        id=_new_id(),
        space_id=personal_id,
        scope_type="user",
        memory_type="semantic",
        content="ephemeral personal note",
        status="active",
        visibility="private",
        owner_user_id=user.id,
        subject_user_id=user.id,
        sensitivity_level="normal",
    )
    db.add(mem)

    grant = PersonalMemoryGrant(
        id=_new_id(),
        granting_user_id=user.id,
        personal_space_id=personal_id,
        target_space_id=team_id,
        target_run_id=run.id,
        target_agent_id=None,
        grant_scope="run",
        access_mode="summary_only",
        status="active",
        memory_filter_json=None,
        read_expires_at=datetime.now(UTC) + timedelta(seconds=3600),
    )
    db.add(grant)
    db.commit()

    # First resolution — should consume the grant
    r1 = resolve_personal_memory_context_for_run(db, run=run)
    db.commit()
    assert r1.has_personal_context, "First resolution must produce personal context"

    db.refresh(grant)
    assert grant.status == "used"
    assert grant.used_at is not None

    # Second resolution — grant is already used; must return no personal context
    r2 = resolve_personal_memory_context_for_run(db, run=run)
    assert not r2.has_personal_context, "Used grant must not be consumable a second time"


def test_grant_derived_context_does_not_create_team_memory(db, client):
    """Phase D: grant-derived context must not be written into team memory.

    RunOutputMaterializer must refuse to create memory proposals when the source
    run has personal grant context and the target space is non-personal.
    """
    from datetime import UTC, datetime, timedelta
    from app.models import AgentVersion, MemoryEntry, PersonalMemoryGrant, Proposal
    from app.personal_memory_grants.resolver import resolve_personal_memory_context_for_run
    from app.runs.context_snapshot_populator import ContextSnapshotPopulator
    from app.runs.run_output_materialization import RunOutputMaterializer

    s = _setup_grant_scenario(db)
    user, personal_id, team_id, run = s["user"], s["personal_id"], s["team_id"], s["run"]

    # Add private memory in personal space
    mem = MemoryEntry(
        id=_new_id(),
        space_id=personal_id,
        scope_type="user",
        memory_type="semantic",
        content="private pref: prefer short answers",
        status="active",
        visibility="private",
        owner_user_id=user.id,
        subject_user_id=user.id,
        sensitivity_level="normal",
    )
    db.add(mem)

    grant = PersonalMemoryGrant(
        id=_new_id(),
        granting_user_id=user.id,
        personal_space_id=personal_id,
        target_space_id=team_id,
        target_run_id=run.id,
        target_agent_id=None,
        grant_scope="run",
        access_mode="summary_only",
        status="active",
        memory_filter_json=None,
        read_expires_at=datetime.now(UTC) + timedelta(seconds=3600),
    )
    db.add(grant)
    db.commit()

    # Build context snapshot — marks run.has_personal_grant_context = True
    version = db.query(AgentVersion).filter(AgentVersion.id == run.agent_version_id).first()
    assert version is not None
    ContextSnapshotPopulator(db).populate(run, version)
    db.commit()

    db.refresh(run)
    assert run.has_personal_grant_context is True, "Run must be marked grant-derived"

    # Attempt to materialize a team memory proposal — must be blocked by egress guard
    materializer = RunOutputMaterializer(db)
    errors = materializer.materialize(
        run=run,
        adapter_output={
            "proposed_changes": [{
                "proposal_type": "memory_update",
                "summary": "Team memory from personal context",
                "payload": {
                    "proposed_content": "inferred from personal memory",
                    "memory_type": "semantic",
                    "target_scope": "space",
                    "target_namespace": "space.knowledge",
                    "target_visibility": "space_shared",
                },
            }]
        },
        adapter_type="test",
    )

    assert len(errors) > 0, "Egress guard must block grant-derived memory proposal"

    # No memory proposals may exist in team space; only egress_review proposals (Phase F2)
    all_proposals = db.query(Proposal).filter(Proposal.space_id == team_id).all()
    memory_proposals = [p for p in all_proposals if p.proposal_type != "egress_review"]
    assert len(memory_proposals) == 0, "No memory proposals must exist for grant-derived run"

    # Phase F2: sanitized egress_review proposal must have been created
    from tests.support.assertions import assert_egress_review_proposal_is_content_free
    db.commit()
    egress_proposals = [p for p in all_proposals if p.proposal_type == "egress_review"]
    assert len(egress_proposals) >= 1, "egress_review proposal must be created for blocked output"
    assert_egress_review_proposal_is_content_free(egress_proposals[0])


def test_run_output_requires_proposal_before_persisting_personal_context(db, client):
    """Phase E: persisting grant-derived output requires proposal + granting-user approval."""
    from datetime import UTC, datetime, timedelta
    from app.memory.apply_service import ProposalApplyError, ProposalApplyService
    from app.models import AgentVersion, MemoryEntry, PersonalMemoryGrant, Proposal
    from app.proposals.approvals import record_egress_granting_user_approval
    from app.runs.context_snapshot_populator import ContextSnapshotPopulator

    s = _setup_grant_scenario(db)
    user, personal_id, team_id, run = s["user"], s["personal_id"], s["team_id"], s["run"]

    db.add(MemoryEntry(
        id=_new_id(),
        space_id=personal_id,
        scope_type="user",
        memory_type="semantic",
        content="PRIVATE_CONTRACT_PHASE_E",
        status="active",
        visibility="private",
        owner_user_id=user.id,
        subject_user_id=user.id,
        sensitivity_level="normal",
    ))
    grant = PersonalMemoryGrant(
        id=_new_id(),
        granting_user_id=user.id,
        personal_space_id=personal_id,
        target_space_id=team_id,
        target_run_id=run.id,
        target_agent_id=None,
        grant_scope="run",
        access_mode="summary_only",
        status="active",
        memory_filter_json=None,
        read_expires_at=datetime.now(UTC) + timedelta(seconds=3600),
        egress_review_expires_at=datetime.now(UTC) + timedelta(hours=2),
    )
    db.add(grant)
    db.commit()

    version = db.query(AgentVersion).filter(AgentVersion.id == run.agent_version_id).first()
    assert version is not None
    ContextSnapshotPopulator(db).populate(run, version)
    db.commit()
    db.refresh(run)
    db.refresh(grant)
    assert run.has_personal_grant_context is True
    assert grant.status == "used"

    proposal = Proposal(
        id=_new_id(),
        space_id=team_id,
        created_by_run_id=run.id,
        proposal_type="memory_create",
        status="pending",
        risk_level="high",
        urgency="normal",
        title="Approved sanitized memory",
        payload_json={
            "operation": "create",
            "proposed_content": "approved sanitized output",
            "memory_type": "semantic",
            "target_scope": "space",
            "target_namespace": "space.knowledge",
            "target_visibility": "space_shared",
            "sensitivity_level": "normal",
            "source_run_id": run.id,
            "grant_id": grant.id,
            "personal_context_derived": True,
            "egress_guard_required": True,
            "raw_private_memory_included": False,
            "personal_summary_persisted": False,
            "approved_by_granting_user": True,
        },
        created_by_user_id=user.id,
        review_deadline=datetime.now(UTC) + timedelta(hours=1),
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )
    db.add(proposal)
    db.flush()

    with pytest.raises(ProposalApplyError, match="GrantingUserApprovalRequired"):
        ProposalApplyService(db).apply(proposal, user_id=user.id, accept_context="explicit_user_accept")

    record_egress_granting_user_approval(
        db,
        proposal_id=proposal.id,
        grant_id=grant.id,
        approver_user_id=user.id,
    )
    result = ProposalApplyService(db).apply(proposal, user_id=user.id, accept_context="explicit_user_accept")
    assert result.memory is not None
    assert result.memory.content == "approved sanitized output"


def test_proposal_read_model_exposes_safe_egress_approval_state(db, client):
    """Phase F1 UI contract: ProposalOut exposes safe egress metadata and real approval state."""
    from datetime import UTC, datetime, timedelta
    from app.models import PersonalMemoryGrant, Proposal
    from app.proposals.approvals import record_egress_granting_user_approval

    s = _setup_grant_scenario(db)
    user, personal_id, team_id, run = s["user"], s["personal_id"], s["team_id"], s["run"]
    ac = _authed_client(db, user.id, personal_id)

    grant = PersonalMemoryGrant(
        id=_new_id(),
        granting_user_id=user.id,
        personal_space_id=personal_id,
        target_space_id=team_id,
        target_run_id=run.id,
        target_agent_id=None,
        grant_scope="run",
        access_mode="summary_only",
        status="used",
        memory_filter_json={"max_items": 5},
        read_expires_at=datetime.now(UTC) + timedelta(seconds=3600),
        egress_review_expires_at=datetime.now(UTC) + timedelta(hours=2),
    )
    proposal = Proposal(
        id=_new_id(),
        space_id=team_id,
        created_by_run_id=run.id,
        proposal_type="egress_review",
        status="pending",
        risk_level="high",
        urgency="normal",
        title="Grant-derived egress review",
        payload_json={
            "target_space_id": team_id,
            "source_run_id": run.id,
            "grant_id": grant.id,
            "required_approver_user_id": user.id,
            "requires_approval_type": "egress_granting_user",
            "personal_context_derived": True,
            "approved_by_granting_user": True,
            "raw_private_memory_included": False,
            "personal_summary_persisted": False,
        },
        rationale="Grant-derived output requires granting-user approval before apply.",
        created_by_user_id=user.id,
        review_deadline=datetime.now(UTC) + timedelta(hours=1),
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )
    db.add_all([grant, proposal])
    db.commit()

    resp = ac.get(f"/api/v1/proposals/{proposal.id}", params={"space_id": team_id})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["grant_id"] == grant.id
    assert data["required_approver_user_id"] == user.id
    assert data["requires_approval_type"] == "egress_granting_user"
    assert data["egress_approval_status"] is None
    assert data["egress_approval_id"] is None

    record_egress_granting_user_approval(
        db,
        proposal_id=proposal.id,
        grant_id=grant.id,
        approver_user_id=user.id,
    )
    db.commit()

    resp = ac.get(f"/api/v1/proposals/{proposal.id}", params={"space_id": team_id})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["egress_approval_status"] == "approved"
    assert data["egress_approval_id"]
    assert "personal_context_block" not in data


# ---------------------------------------------------------------------------
# M1 — schema_version enforcement in memory_filter (Final Consistency Patch)
# ---------------------------------------------------------------------------


def test_create_grant_rejects_memory_filter_missing_schema_version(db, client):
    """POST rejects memory_filter that omits schema_version."""
    s = _setup_grant_scenario(db)
    ac = _authed_client(db, s["user"].id, s["personal_id"])

    resp = ac.post("/api/v1/personal-memory-grants", json={
        "target_space_id": s["team_id"],
        "target_run_id": s["run"].id,
        "access_mode": "summary_only",
        "read_expires_in_seconds": 300,
        "memory_filter": {"max_items": 5},  # missing schema_version
    })
    assert resp.status_code in (400, 422), resp.text


def test_create_grant_rejects_memory_filter_unknown_schema_version(db, client):
    """POST rejects memory_filter with schema_version outside supported set."""
    s = _setup_grant_scenario(db)
    ac = _authed_client(db, s["user"].id, s["personal_id"])

    resp = ac.post("/api/v1/personal-memory-grants", json={
        "target_space_id": s["team_id"],
        "target_run_id": s["run"].id,
        "access_mode": "summary_only",
        "read_expires_in_seconds": 300,
        "memory_filter": {"schema_version": 99, "max_items": 5},
    })
    assert resp.status_code in (400, 422), resp.text


def test_create_grant_accepts_memory_filter_with_schema_version_1(db, client):
    """POST accepts memory_filter that includes schema_version=1."""
    s = _setup_grant_scenario(db)
    ac = _authed_client(db, s["user"].id, s["personal_id"])

    resp = ac.post("/api/v1/personal-memory-grants", json={
        "target_space_id": s["team_id"],
        "target_run_id": s["run"].id,
        "access_mode": "summary_only",
        "read_expires_in_seconds": 300,
        "memory_filter": {"schema_version": 1, "max_items": 5},
    })
    assert resp.status_code == 201, resp.text


def test_create_grant_accepts_null_memory_filter(db, client):
    """POST accepts memory_filter=null (no filter); schema_version not required when filter is null."""
    s = _setup_grant_scenario(db)
    ac = _authed_client(db, s["user"].id, s["personal_id"])

    resp = ac.post("/api/v1/personal-memory-grants", json={
        "target_space_id": s["team_id"],
        "target_run_id": s["run"].id,
        "access_mode": "summary_only",
        "read_expires_in_seconds": 300,
        "memory_filter": None,
    })
    assert resp.status_code == 201, resp.text
