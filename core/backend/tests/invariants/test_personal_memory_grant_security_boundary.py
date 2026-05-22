"""Security invariants: PersonalMemoryGrant boundary enforcement.

Grant API and service tests verify granting_user_id ownership enforcement and
extra=forbid schema behavior.

Runtime context tests verify grant lifecycle, ownership, expiry, run-scoping,
and sensitivity filtering.

Egress guard tests verify grant-derived output cannot be written to shared targets.

Defense-in-depth apply_update guards and code patch risk labels are verified in
test_personal_memory_egress_guard_invariants.py.
"""

from __future__ import annotations

import pytest
from datetime import UTC, datetime, timedelta
from ulid import ULID

from app.memory.retriever import MemoryRetriever
from app.models import (
    MemoryEntry,
    PersonalMemoryGrant,
    PersonalMemoryGrantEvent,
    Proposal,
    SourcePointer,
    SpaceMembership,
)
from app.personal_memory_grants.resolver import (
    find_active_grant_for_run,
    resolve_personal_memory_context_for_run,
    retrieve_eligible_memories,
)
from app.policy.domains import MEMORY_CROSS_SPACE_READ, RUN_USER_PRIVATE_SCOPE
from tests.support import factories


def _new_id() -> str:
    return str(ULID())


def _personal_space(db):
    sid = _new_id()
    factories.create_test_space(db, space_id=sid, name="Personal", space_type="personal")
    user = factories.create_test_user(db, space_id=sid, display_name="Personal User")
    db.commit()
    return sid, user


def _team_space(db):
    sid = _new_id()
    factories.create_test_space(db, space_id=sid, name="Team", space_type="team")
    user = factories.create_test_user(db, space_id=sid, display_name="Team User")
    db.commit()
    return sid, user


def _add_member(db, *, space_id: str, user_id: str) -> None:
    db.add(SpaceMembership(
        id=_new_id(), space_id=space_id, user_id=user_id, role="member", status="active"
    ))


def _private_memory(
    db,
    *,
    space_id: str,
    owner_user_id: str,
    content: str = "private-content",
    sensitivity_level: str = "normal",
) -> MemoryEntry:
    m = MemoryEntry(
        id=_new_id(),
        space_id=space_id,
        scope_type="user",
        memory_type="semantic",
        content=content,
        status="active",
        visibility="private",
        owner_user_id=owner_user_id,
        subject_user_id=owner_user_id,
        sensitivity_level=sensitivity_level,
    )
    db.add(m)
    db.flush()
    return m


def _active_grant(
    db,
    *,
    granting_user_id: str,
    personal_space_id: str,
    target_space_id: str,
    target_run_id: str,
    expires_in_seconds: int = 3600,
    status: str = "active",
) -> PersonalMemoryGrant:
    grant = PersonalMemoryGrant(
        id=_new_id(),
        granting_user_id=granting_user_id,
        personal_space_id=personal_space_id,
        target_space_id=target_space_id,
        target_run_id=target_run_id,
        target_agent_id=None,
        grant_scope="run",
        access_mode="summary_only",
        status=status,
        memory_filter_json=None,
        read_expires_at=datetime.now(UTC) + timedelta(seconds=expires_in_seconds),
    )
    db.add(grant)
    db.flush()
    return grant


def _policy_row(db, *, space_id: str, domain: str, effect: str):
    return factories.create_test_policy(
        db,
        space_id=space_id,
        domain=domain.split(".", 1)[0],
        policy_key=domain,
        enforcement_mode=effect,
        rule_json={"policy_domain": domain, "effect": effect},
        commit=True,
    )


# ---------------------------------------------------------------------------
# Tests that pass with no grant implementation (invariants preserved)
# ---------------------------------------------------------------------------


def test_shared_run_without_grant_cannot_read_personal_private_memory(db):
    """Invariant 1: A shared-space run cannot access personal-space private memory without a grant."""
    personal_id, user = _personal_space(db)
    team_id, _team_user = _team_space(db)
    _add_member(db, space_id=team_id, user_id=user.id)
    private = _private_memory(db, space_id=personal_id, owner_user_id=user.id)
    db.commit()

    result = MemoryRetriever(db).retrieve(space_id=team_id, user_id=user.id)
    memory_ids = {m.id for m in result.memories}
    assert private.id not in memory_ids, (
        "Personal-space private memory must not appear in a shared-space run context."
    )


def test_source_pointer_does_not_act_as_personal_memory_grant(db):
    """Invariant 3: SourcePointer to personal memory does not allow shared-space run access."""
    personal_id, user = _personal_space(db)
    team_id, _team_user = _team_space(db)
    _add_member(db, space_id=team_id, user_id=user.id)
    private = _private_memory(db, space_id=personal_id, owner_user_id=user.id)
    db.commit()

    sp = SourcePointer(
        id=_new_id(),
        owner_space_id=team_id,
        source_space_id=personal_id,
        source_object_type="memory",
        source_object_id=private.id,
        access_mode="read",
        granted_by_user_id=user.id,
    )
    db.add(sp)
    db.commit()

    result = MemoryRetriever(db).retrieve(space_id=team_id, user_id=user.id)
    assert private.id not in {m.id for m in result.memories}, (
        "SourcePointer must not act as a PersonalMemoryGrant — personal memory must remain blocked."
    )


def test_cross_space_read_policy_allow_without_grant_does_not_enable_access(db):
    """Invariant: memory.cross_space_read policy allow without a grant does not enable cross-space read."""
    personal_id, user = _personal_space(db)
    team_id, _team_user = _team_space(db)
    _add_member(db, space_id=team_id, user_id=user.id)
    private = _private_memory(db, space_id=personal_id, owner_user_id=user.id)
    _policy_row(db, space_id=team_id, domain=MEMORY_CROSS_SPACE_READ, effect="allow")
    db.commit()

    result = MemoryRetriever(db).retrieve(space_id=team_id, user_id=user.id)
    assert private.id not in {m.id for m in result.memories}, (
        "Policy allow on memory.cross_space_read must not bypass the space_id hard filter."
    )


def test_personal_memory_grant_model_has_required_fields():
    """PersonalMemoryGrant ORM columns exist with correct nullability."""
    from sqlalchemy import inspect as sa_inspect
    mapper = sa_inspect(PersonalMemoryGrant)
    col_names = {col.key for col in mapper.columns}
    required = {
        "id", "granting_user_id", "personal_space_id", "target_space_id",
        "target_run_id", "target_agent_id", "grant_scope", "access_mode",
        "status", "memory_filter_json", "read_expires_at", "created_at", "updated_at",
    }
    assert required.issubset(col_names), f"Missing ORM columns: {required - col_names}"

    target_run_col = mapper.columns["target_run_id"]
    assert not target_run_col.nullable, "target_run_id must be NOT NULL"

    expires_col = mapper.columns["read_expires_at"]
    assert not expires_col.nullable, "read_expires_at must be NOT NULL"


def test_personal_memory_grant_model_has_no_raw_content_fields():
    """PersonalMemoryGrant ORM model must not have raw content fields."""
    from sqlalchemy import inspect as sa_inspect
    mapper = sa_inspect(PersonalMemoryGrant)
    col_names = {col.key for col in mapper.columns}
    forbidden = {
        "content", "body", "raw_content", "payload", "summary",
        "generated_summary", "memory_text", "copied_text", "source_snapshot",
    }
    found = forbidden & col_names
    assert not found, f"PersonalMemoryGrant must have no content fields: {found}"


# ---------------------------------------------------------------------------
# Service-layer grant lifecycle enforcement
# ---------------------------------------------------------------------------


def test_user_cannot_create_grant_for_another_users_personal_memory(db):
    """Invariant 2: a user cannot create a grant for a run instructed by another user.

    The service layer enforces this via TargetRunOwnershipError:
    create_personal_memory_grant() checks run.instructed_by_user_id == calling user_id.
    The API layer also enforces this at extra=forbid on GrantCreate (no client-supplied
    granting_user_id) and via TargetRunOwnershipError → HTTP 400/403.
    """
    from app.personal_memory_grants.service import (
        TargetRunOwnershipError,
        create_personal_memory_grant,
    )

    # user_a owns a personal space and is a team member
    personal_a_id, user_a = _personal_space(db)
    team_id, _ = _team_space(db)
    _add_member(db, space_id=team_id, user_id=user_a.id)

    # user_b has their own personal space and instructs a run in the team space
    personal_b_id = _new_id()
    factories.create_test_space(db, space_id=personal_b_id, name="PersonalB", space_type="personal")
    user_b = factories.create_test_user(db, space_id=personal_b_id, display_name="User B")
    _add_member(db, space_id=team_id, user_id=user_b.id)
    db.commit()

    run_by_b = factories.create_test_run(db, space_id=team_id, user_id=user_b.id, commit=True)

    # user_a tries to create a grant for a run instructed by user_b — must be rejected
    with pytest.raises(TargetRunOwnershipError):
        create_personal_memory_grant(
            db,
            user_id=user_a.id,
            target_space_id=team_id,
            target_run_id=run_by_b.id,
            access_mode="summary_only",
            read_expires_in_seconds=3600,
        )


# ---------------------------------------------------------------------------
# Grant resolver boundary invariants
# ---------------------------------------------------------------------------


def test_grant_for_run_a_cannot_be_used_by_run_b(db):
    """Invariant 5: A grant for run A cannot be consumed for run B.

    find_active_grant_for_run filters by target_run_id so run B gets no grant.
    """
    personal_id, user = _personal_space(db)
    team_id, _team_user = _team_space(db)
    _add_member(db, space_id=team_id, user_id=user.id)
    _private_memory(db, space_id=personal_id, owner_user_id=user.id)
    db.commit()

    run_a = factories.create_test_run(db, space_id=team_id, user_id=user.id, commit=True)
    run_b = factories.create_test_run(db, space_id=team_id, user_id=user.id, commit=True)

    # Grant is scoped to run_a only
    _active_grant(
        db,
        granting_user_id=user.id,
        personal_space_id=personal_id,
        target_space_id=team_id,
        target_run_id=run_a.id,
    )
    db.commit()

    now = datetime.now(UTC)

    # run_a should find the grant
    found_for_a = find_active_grant_for_run(
        db, run_id=run_a.id, granting_user_id=user.id,
        target_space_id=team_id, now=now,
    )
    assert found_for_a is not None, "Grant should be found for run A"

    # run_b must NOT find the grant
    found_for_b = find_active_grant_for_run(
        db, run_id=run_b.id, granting_user_id=user.id,
        target_space_id=team_id, now=now,
    )
    assert found_for_b is None, "Grant for run A must not be usable by run B"

    # resolver for run_b returns no personal context
    result_b = resolve_personal_memory_context_for_run(db, run=run_b)
    assert not result_b.has_personal_context, (
        "Resolver must return no personal context when run ID does not match grant"
    )


def test_expired_grant_cannot_be_used(db):
    """Invariant 6: An expired grant (read_expires_at < now) cannot be consumed."""
    personal_id, user = _personal_space(db)
    team_id, _team_user = _team_space(db)
    _add_member(db, space_id=team_id, user_id=user.id)
    _private_memory(db, space_id=personal_id, owner_user_id=user.id)
    db.commit()

    run = factories.create_test_run(db, space_id=team_id, user_id=user.id, commit=True)

    # Create grant that already expired
    expired_grant = PersonalMemoryGrant(
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
        read_expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    db.add(expired_grant)
    db.commit()

    now = datetime.now(UTC)
    found = find_active_grant_for_run(
        db, run_id=run.id, granting_user_id=user.id,
        target_space_id=team_id, now=now,
    )
    assert found is None, "Expired grant must not be returned by find_active_grant_for_run"

    result = resolve_personal_memory_context_for_run(db, run=run)
    assert not result.has_personal_context, "Expired grant must produce no personal context"


def test_revoked_grant_cannot_be_used(db):
    """Invariant 6: A revoked grant (status=revoked) cannot be consumed."""
    personal_id, user = _personal_space(db)
    team_id, _team_user = _team_space(db)
    _add_member(db, space_id=team_id, user_id=user.id)
    _private_memory(db, space_id=personal_id, owner_user_id=user.id)
    db.commit()

    run = factories.create_test_run(db, space_id=team_id, user_id=user.id, commit=True)

    revoked_grant = _active_grant(
        db,
        granting_user_id=user.id,
        personal_space_id=personal_id,
        target_space_id=team_id,
        target_run_id=run.id,
        status="revoked",
    )
    db.commit()

    now = datetime.now(UTC)
    found = find_active_grant_for_run(
        db, run_id=run.id, granting_user_id=user.id,
        target_space_id=team_id, now=now,
    )
    assert found is None, "Revoked grant must not be returned by find_active_grant_for_run"

    result = resolve_personal_memory_context_for_run(db, run=run)
    assert not result.has_personal_context, "Revoked grant must produce no personal context"


def test_used_one_time_grant_cannot_be_reused(db):
    """Invariant 6: A used grant (status=used) cannot be consumed again."""
    personal_id, user = _personal_space(db)
    team_id, _team_user = _team_space(db)
    _add_member(db, space_id=team_id, user_id=user.id)
    _private_memory(db, space_id=personal_id, owner_user_id=user.id)
    db.commit()

    run = factories.create_test_run(db, space_id=team_id, user_id=user.id, commit=True)
    grant = _active_grant(
        db,
        granting_user_id=user.id,
        personal_space_id=personal_id,
        target_space_id=team_id,
        target_run_id=run.id,
    )
    db.commit()

    # First consumption
    result1 = resolve_personal_memory_context_for_run(db, run=run)
    db.commit()
    assert result1.has_personal_context, "First resolution should succeed"

    db.refresh(grant)
    assert grant.status == "used"

    # Second attempt must fail
    result2 = resolve_personal_memory_context_for_run(db, run=run)
    assert not result2.has_personal_context, (
        "Used one-time grant must not be consumable a second time"
    )


def test_highly_restricted_memory_excluded_even_with_grant(db):
    """Invariant 4: sensitivity_level=highly_restricted memory must never be grant-readable.

    retrieve_eligible_memories filters by sensitivity_level in ('normal', 'sensitive').
    Both 'restricted' and 'highly_restricted' memories must be excluded.
    """
    personal_id, user = _personal_space(db)

    normal_mem = _private_memory(
        db, space_id=personal_id, owner_user_id=user.id,
        content="normal content", sensitivity_level="normal",
    )
    sensitive_mem = _private_memory(
        db, space_id=personal_id, owner_user_id=user.id,
        content="sensitive content", sensitivity_level="sensitive",
    )
    restricted_mem = _private_memory(
        db, space_id=personal_id, owner_user_id=user.id,
        content="restricted content", sensitivity_level="restricted",
    )
    highly_restricted_mem = _private_memory(
        db, space_id=personal_id, owner_user_id=user.id,
        content="highly restricted content", sensitivity_level="highly_restricted",
    )
    db.commit()

    memories = retrieve_eligible_memories(
        db,
        personal_space_id=personal_id,
        granting_user_id=user.id,
        memory_filter=None,
    )
    mem_ids = {m.id for m in memories}

    assert normal_mem.id in mem_ids, "normal sensitivity memory should be included"
    assert sensitive_mem.id in mem_ids, "sensitive sensitivity memory should be included"
    assert restricted_mem.id not in mem_ids, (
        "restricted sensitivity memory must be excluded even with a grant"
    )
    assert highly_restricted_mem.id not in mem_ids, (
        "highly_restricted sensitivity memory must be excluded even with a grant"
    )


# ---------------------------------------------------------------------------
# Egress guard
# ---------------------------------------------------------------------------


def test_grant_does_not_enable_team_memory_write_of_private_content(db):
    """Invariant 7: grant-derived context must not be silently written into team memory.

    The egress guard intercepts and blocks direct persistence of grant-derived
    output into non-personal spaces via RunOutputMaterializer.
    """
    personal_id, user = _personal_space(db)
    team_id, _team_user = _team_space(db)
    _add_member(db, space_id=team_id, user_id=user.id)
    _private_memory(db, space_id=personal_id, owner_user_id=user.id, content="private-preference-X")
    db.commit()

    run = factories.create_test_run(db, space_id=team_id, user_id=user.id, commit=True)
    _active_grant(
        db,
        granting_user_id=user.id,
        personal_space_id=personal_id,
        target_space_id=team_id,
        target_run_id=run.id,
    )
    db.commit()

    # Build context snapshot to mark run as grant-derived
    from app.models import AgentVersion
    from app.runs.context_snapshot_populator import ContextSnapshotPopulator
    version = db.query(AgentVersion).filter(AgentVersion.id == run.agent_version_id).first()
    assert version is not None
    ContextSnapshotPopulator(db).populate(run, version)
    db.commit()

    db.refresh(run)
    assert run.has_personal_grant_context is True

    # Attempt team memory creation via RunOutputMaterializer — must be blocked
    from app.runs.run_output_materialization import RunOutputMaterializer
    materializer = RunOutputMaterializer(db)
    errors = materializer.materialize(
        run=run,
        adapter_output={
            "proposed_changes": [{
                "proposal_type": "memory_update",
                "summary": "Team knowledge from personal context",
                "payload": {
                    "proposed_content": "derived content from private memory",
                    "memory_type": "semantic",
                    "target_scope": "space",
                    "target_namespace": "space.default",
                    "target_visibility": "space_shared",
                },
            }]
        },
        adapter_type="test",
    )

    assert len(errors) > 0, "Egress guard must block grant-derived memory proposal creation"

    # Invariant: no team memory proposal must exist; egress_review proposals are allowed.
    proposals = db.query(Proposal).filter(Proposal.space_id == team_id).all()
    memory_proposals = [p for p in proposals if p.proposal_type != "egress_review"]
    assert len(memory_proposals) == 0, (
        f"Invariant 7 violated: grant-derived context must not create team memory proposals; "
        f"got: {[p.proposal_type for p in memory_proposals]}"
    )


# ---------------------------------------------------------------------------
# Final Consistency Patch: multi-user grant deferral
# ---------------------------------------------------------------------------


def test_multi_user_grant_rejected(db):
    """Multi-user grants are deferred: user_A cannot create a grant for a run instructed by user_B.

    The granting user (caller) must be the same user who instructed the target run.
    The Run model has a single instructed_by_user_id. Granting access to another user's run
    is rejected at the service layer via TargetRunOwnershipError.

    Multi-user grants require a safe per-user isolation model and are deferred.
    """
    from app.personal_memory_grants.service import (
        TargetRunOwnershipError,
        create_personal_memory_grant,
    )

    # user_a: granting user who will attempt to create the grant
    personal_a_id, user_a = _personal_space(db)
    team_id, _ = _team_space(db)
    _add_member(db, space_id=team_id, user_id=user_a.id)

    # user_b: instructed the target run — different from user_a
    personal_b_id = _new_id()
    factories.create_test_space(db, space_id=personal_b_id, name="PersonalB", space_type="personal")
    user_b = factories.create_test_user(db, space_id=personal_b_id, display_name="User B")
    _add_member(db, space_id=team_id, user_id=user_b.id)
    db.commit()

    run_by_b = factories.create_test_run(db, space_id=team_id, user_id=user_b.id, commit=True)

    # user_a cannot create a grant for a run instructed by user_b
    with pytest.raises(TargetRunOwnershipError):
        create_personal_memory_grant(
            db,
            user_id=user_a.id,
            target_space_id=team_id,
            target_run_id=run_by_b.id,
            access_mode="summary_only",
            read_expires_in_seconds=3600,
        )
