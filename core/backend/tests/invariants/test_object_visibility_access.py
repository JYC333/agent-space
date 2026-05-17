"""Invariant: visibility filter is enforced for non-memory scoped objects.

Tests verify that the can_read_scoped_object helper and its wiring in
ArtifactReadService, ActivityService, RunService, TaskService, and ProposalService
correctly restrict access based on the visibility column and owner_user_id.

Rules under test:
  - visibility=space_shared: readable by any space member
  - visibility=private:      readable only by owner
  - visibility=restricted:   readable only by owner (no selected-users field yet)
  - unknown visibility:       deny by default (fail closed)
  - Task private: readable by created_by_user_id OR assigned_user_id OR claimed_by_user_id
  - Proposal private: only created_by_user_id; space_shared: any space user
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from ulid import ULID

from app.activity.service import ActivityService
from app.artifacts.service import ArtifactReadService
from app.memory.proposals import ProposalService
from app.models import ActivityRecord, Artifact, Proposal, Run, Space, SpaceMembership, Task
from app.runs.run_service import RunService
from app.tasks.service import TaskService
from app.visibility.auth import can_read_scoped_object
from tests.support import factories


def _new_id() -> str:
    return str(ULID())


# ---------------------------------------------------------------------------
# Unit tests for the can_read_scoped_object helper
# ---------------------------------------------------------------------------


def test_space_shared_readable_by_member():
    assert can_read_scoped_object(
        visibility="space_shared",
        owner_user_id="user-a",
        current_user_id="user-b",
        is_space_member=True,
    ) is True


def test_space_shared_blocked_for_non_member():
    assert can_read_scoped_object(
        visibility="space_shared",
        owner_user_id="user-a",
        current_user_id="user-b",
        is_space_member=False,
    ) is False


def test_private_readable_only_by_owner():
    assert can_read_scoped_object(
        visibility="private",
        owner_user_id="user-a",
        current_user_id="user-a",
        is_space_member=True,
    ) is True


def test_private_blocked_for_non_owner_member():
    assert can_read_scoped_object(
        visibility="private",
        owner_user_id="user-a",
        current_user_id="user-b",
        is_space_member=True,
    ) is False


def test_private_blocked_when_no_owner():
    assert can_read_scoped_object(
        visibility="private",
        owner_user_id=None,
        current_user_id="user-a",
        is_space_member=True,
    ) is False


def test_restricted_readable_only_by_owner():
    assert can_read_scoped_object(
        visibility="restricted",
        owner_user_id="user-a",
        current_user_id="user-a",
        is_space_member=True,
    ) is True


def test_restricted_blocked_for_non_owner():
    assert can_read_scoped_object(
        visibility="restricted",
        owner_user_id="user-a",
        current_user_id="user-b",
        is_space_member=True,
    ) is False


def test_unknown_visibility_fails_closed():
    assert can_read_scoped_object(
        visibility="public",
        owner_user_id=None,
        current_user_id="user-a",
        is_space_member=True,
    ) is False


def test_no_current_user_fails_closed():
    assert can_read_scoped_object(
        visibility="space_shared",
        owner_user_id=None,
        current_user_id=None,
        is_space_member=True,
    ) is False


# ---------------------------------------------------------------------------
# Integration: Artifact visibility via ArtifactReadService
# ---------------------------------------------------------------------------


def _make_space_with_two_users(db):
    space_id = _new_id()
    factories.create_test_space(db, space_id=space_id, name="Two Users", space_type="team", commit=False)
    user_owner = factories.create_test_user(db, space_id=space_id, commit=False)
    user_other = factories.create_test_user(db, space_id=space_id, commit=False)
    db.flush()
    return space_id, user_owner, user_other


def test_private_artifact_visible_only_to_owner(db):
    space_id, owner, other = _make_space_with_two_users(db)
    art = Artifact(
        id=_new_id(), space_id=space_id, artifact_type="report",
        title="Private artifact", content="secret",
        visibility="private", owner_user_id=owner.id,
    )
    db.add(art)
    db.commit()

    svc = ArtifactReadService(db)
    assert svc.get(art.id, space_id, user_id=owner.id) is not None
    assert svc.get(art.id, space_id, user_id=other.id) is None


def test_space_shared_artifact_visible_to_any_member(db):
    space_id, owner, other = _make_space_with_two_users(db)
    art = Artifact(
        id=_new_id(), space_id=space_id, artifact_type="report",
        title="Shared artifact", content="public",
        visibility="space_shared", owner_user_id=owner.id,
    )
    db.add(art)
    db.commit()

    svc = ArtifactReadService(db)
    assert svc.get(art.id, space_id, user_id=owner.id) is not None
    assert svc.get(art.id, space_id, user_id=other.id) is not None


def test_artifact_list_filters_private_for_non_owner(db):
    space_id, owner, other = _make_space_with_two_users(db)
    private_art = Artifact(
        id=_new_id(), space_id=space_id, artifact_type="report",
        title="Private", content="secret",
        visibility="private", owner_user_id=owner.id,
    )
    shared_art = Artifact(
        id=_new_id(), space_id=space_id, artifact_type="report",
        title="Shared", content="visible",
        visibility="space_shared", owner_user_id=owner.id,
    )
    db.add(private_art)
    db.add(shared_art)
    db.commit()

    svc = ArtifactReadService(db)
    _, rows_other = svc.list_artifacts(space_id, user_id=other.id)
    ids_other = {a.id for a in rows_other}
    assert private_art.id not in ids_other
    assert shared_art.id in ids_other

    _, rows_owner = svc.list_artifacts(space_id, user_id=owner.id)
    ids_owner = {a.id for a in rows_owner}
    assert private_art.id in ids_owner
    assert shared_art.id in ids_owner


# ---------------------------------------------------------------------------
# Integration: ActivityRecord visibility via ActivityService
# ---------------------------------------------------------------------------


def test_private_activity_visible_only_to_owner(db):
    space_id, owner, other = _make_space_with_two_users(db)
    rec = ActivityRecord(
        id=_new_id(), space_id=space_id, activity_type="user_capture",
        content="private content", status="raw",
        visibility="private", owner_user_id=owner.id,
    )
    db.add(rec)
    db.commit()

    svc = ActivityService(db)
    assert svc.get(rec.id, space_id, viewer_user_id=owner.id) is not None
    assert svc.get(rec.id, space_id, viewer_user_id=other.id) is None


def test_space_shared_activity_visible_to_members(db):
    space_id, owner, other = _make_space_with_two_users(db)
    rec = ActivityRecord(
        id=_new_id(), space_id=space_id, activity_type="user_capture",
        content="shared content", status="raw",
        visibility="space_shared", owner_user_id=owner.id,
    )
    db.add(rec)
    db.commit()

    svc = ActivityService(db)
    assert svc.get(rec.id, space_id, viewer_user_id=owner.id) is not None
    assert svc.get(rec.id, space_id, viewer_user_id=other.id) is not None


def test_activity_list_filters_private_for_non_owner(db):
    space_id, owner, other = _make_space_with_two_users(db)
    private_rec = ActivityRecord(
        id=_new_id(), space_id=space_id, activity_type="user_capture",
        content="private", status="raw",
        visibility="private", owner_user_id=owner.id,
    )
    shared_rec = ActivityRecord(
        id=_new_id(), space_id=space_id, activity_type="user_capture",
        content="shared", status="raw",
        visibility="space_shared",
    )
    db.add(private_rec)
    db.add(shared_rec)
    db.commit()

    svc = ActivityService(db)
    records_other = svc.list(space_id, viewer_user_id=other.id)
    ids_other = {r.id for r in records_other}
    assert private_rec.id not in ids_other
    assert shared_rec.id in ids_other

    records_owner = svc.list(space_id, viewer_user_id=owner.id)
    ids_owner = {r.id for r in records_owner}
    assert private_rec.id in ids_owner


# ---------------------------------------------------------------------------
# Integration: Run visibility via RunService
# ---------------------------------------------------------------------------


def test_private_run_visible_only_to_instructed_user(db):
    space_id, owner, other = _make_space_with_two_users(db)
    run = factories.create_test_run(db, space_id=space_id, user_id=owner.id, commit=False)
    run.visibility = "private"
    db.flush()
    db.commit()

    svc = RunService(db)
    # Owner can read
    fetched = svc.get_run(run.id, space_id, user_id=owner.id)
    assert fetched.id == run.id

    # Non-owner gets 404
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        svc.get_run(run.id, space_id, user_id=other.id)
    assert exc_info.value.status_code == 404


def test_space_shared_run_visible_to_members(db):
    space_id, owner, other = _make_space_with_two_users(db)
    run = factories.create_test_run(db, space_id=space_id, user_id=owner.id, commit=False)
    run.visibility = "space_shared"
    db.flush()
    db.commit()

    svc = RunService(db)
    assert svc.get_run(run.id, space_id, user_id=owner.id) is not None
    assert svc.get_run(run.id, space_id, user_id=other.id) is not None


def test_run_list_filters_private_for_non_owner(db):
    space_id, owner, other = _make_space_with_two_users(db)
    priv_run = factories.create_test_run(db, space_id=space_id, user_id=owner.id, commit=False)
    priv_run.visibility = "private"
    shared_run = factories.create_test_run(db, space_id=space_id, user_id=owner.id, commit=False)
    shared_run.visibility = "space_shared"
    db.flush()
    db.commit()

    svc = RunService(db)
    runs_other = svc.list_runs(space_id, user_id=other.id)
    ids_other = {r.id for r in runs_other}
    assert priv_run.id not in ids_other
    assert shared_run.id in ids_other

    runs_owner = svc.list_runs(space_id, user_id=owner.id)
    ids_owner = {r.id for r in runs_owner}
    assert priv_run.id in ids_owner
    assert shared_run.id in ids_owner


# ---------------------------------------------------------------------------
# Integration: Task visibility via TaskService
# ---------------------------------------------------------------------------


def test_private_task_visible_to_creator(db):
    space_id, owner, other = _make_space_with_two_users(db)
    task = Task(
        id=_new_id(), space_id=space_id, title="Private task", status="inbox",
        priority="normal", visibility="private", created_by_user_id=owner.id,
    )
    db.add(task)
    db.commit()

    svc = TaskService(db)
    assert svc.get(task.id, space_id, user_id=owner.id) is not None
    with pytest.raises(HTTPException) as exc_info:
        svc.get(task.id, space_id, user_id=other.id)
    assert exc_info.value.status_code == 404


def test_private_task_visible_to_assignee(db):
    space_id, owner, assignee = _make_space_with_two_users(db)
    task = Task(
        id=_new_id(), space_id=space_id, title="Assigned private", status="inbox",
        priority="normal", visibility="private",
        created_by_user_id=owner.id, assigned_user_id=assignee.id,
    )
    db.add(task)
    db.commit()

    svc = TaskService(db)
    assert svc.get(task.id, space_id, user_id=assignee.id) is not None


def test_restricted_task_hidden_from_non_owner(db):
    space_id, owner, other = _make_space_with_two_users(db)
    task = Task(
        id=_new_id(), space_id=space_id, title="Restricted task", status="inbox",
        priority="normal", visibility="restricted", created_by_user_id=owner.id,
    )
    db.add(task)
    db.commit()

    svc = TaskService(db)
    assert svc.get(task.id, space_id, user_id=owner.id) is not None
    with pytest.raises(HTTPException) as exc_info:
        svc.get(task.id, space_id, user_id=other.id)
    assert exc_info.value.status_code == 404


def test_space_shared_task_visible_to_space_member(db):
    space_id, owner, other = _make_space_with_two_users(db)
    task = Task(
        id=_new_id(), space_id=space_id, title="Shared task", status="inbox",
        priority="normal", visibility="space_shared", created_by_user_id=owner.id,
    )
    db.add(task)
    db.commit()

    svc = TaskService(db)
    assert svc.get(task.id, space_id, user_id=owner.id) is not None
    assert svc.get(task.id, space_id, user_id=other.id) is not None


def test_task_list_filters_private_for_non_owner(db):
    space_id, owner, other = _make_space_with_two_users(db)
    priv_task = Task(
        id=_new_id(), space_id=space_id, title="Private", status="inbox",
        priority="normal", visibility="private", created_by_user_id=owner.id,
    )
    shared_task = Task(
        id=_new_id(), space_id=space_id, title="Shared", status="inbox",
        priority="normal", visibility="space_shared", created_by_user_id=owner.id,
    )
    db.add(priv_task)
    db.add(shared_task)
    db.commit()

    svc = TaskService(db)
    _, tasks_other = svc.list_tasks(space_id, user_id=other.id)
    ids_other = {t.id for t in tasks_other}
    assert priv_task.id not in ids_other
    assert shared_task.id in ids_other

    _, tasks_owner = svc.list_tasks(space_id, user_id=owner.id)
    ids_owner = {t.id for t in tasks_owner}
    assert priv_task.id in ids_owner
    assert shared_task.id in ids_owner


# ---------------------------------------------------------------------------
# Integration: Proposal visibility via ProposalService
# ---------------------------------------------------------------------------


def test_private_proposal_visible_to_creator(db):
    space_id, owner, other = _make_space_with_two_users(db)
    prop = factories.create_test_proposal(
        db, space_id=space_id, created_by_user_id=owner.id, status="pending", commit=False,
    )
    prop.visibility = "private"
    db.commit()

    svc = ProposalService(db)
    items = svc.list_proposals(space_id, owner.id)
    assert prop.id in {p.id for p in items}


def test_private_proposal_hidden_from_other_space_member(db):
    space_id, owner, other = _make_space_with_two_users(db)
    prop = factories.create_test_proposal(
        db, space_id=space_id, created_by_user_id=owner.id, status="pending", commit=False,
    )
    prop.visibility = "private"
    db.commit()

    svc = ProposalService(db)
    items_other = svc.list_proposals(space_id, other.id)
    assert prop.id not in {p.id for p in items_other}


def test_space_shared_proposal_visible_to_any_space_member(db):
    space_id, owner, other = _make_space_with_two_users(db)
    prop = factories.create_test_proposal(
        db, space_id=space_id, created_by_user_id=owner.id, status="pending", commit=True,
    )
    assert prop.visibility == "space_shared"

    svc = ProposalService(db)
    # both creator and other space member can see it
    assert prop.id in {p.id for p in svc.list_proposals(space_id, owner.id)}
    assert prop.id in {p.id for p in svc.list_proposals(space_id, other.id)}


def test_restricted_proposal_hidden_from_non_owner(db):
    space_id, owner, other = _make_space_with_two_users(db)
    prop = factories.create_test_proposal(
        db, space_id=space_id, created_by_user_id=owner.id, status="pending", commit=False,
    )
    prop.visibility = "restricted"
    db.commit()

    svc = ProposalService(db)
    items_other = svc.list_proposals(space_id, other.id)
    assert prop.id not in {p.id for p in items_other}

    items_owner = svc.list_proposals(space_id, owner.id)
    assert prop.id in {p.id for p in items_owner}


def test_count_proposals_matches_list_proposals_visibility(db):
    """count_proposals uses the same visibility filter as list_proposals.

    Setup: one space_shared + one private proposal (owner is creator).
    - owner sees count=2, list has both ids
    - other sees count=1 (space_shared only), list excludes private
    """
    space_id, owner, other = _make_space_with_two_users(db)

    shared = factories.create_test_proposal(
        db, space_id=space_id, created_by_user_id=owner.id, status="pending", commit=False,
    )
    assert shared.visibility == "space_shared"

    private = factories.create_test_proposal(
        db, space_id=space_id, created_by_user_id=owner.id, status="pending", commit=False,
    )
    private.visibility = "private"
    db.commit()

    svc = ProposalService(db)

    # owner: count must equal len(list) and include both
    owner_count = svc.count_proposals(space_id, owner.id)
    owner_list = svc.list_proposals(space_id, owner.id)
    assert owner_count == len(owner_list), "count_proposals diverges from list_proposals for owner"
    owner_ids = {p.id for p in owner_list}
    assert shared.id in owner_ids and private.id in owner_ids

    # other: count must equal len(list) and exclude private
    other_count = svc.count_proposals(space_id, other.id)
    other_list = svc.list_proposals(space_id, other.id)
    assert other_count == len(other_list), "count_proposals diverges from list_proposals for non-owner"
    other_ids = {p.id for p in other_list}
    assert shared.id in other_ids
    assert private.id not in other_ids
