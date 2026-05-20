"""Unit tests for ProjectService and assert_project_in_space."""

from __future__ import annotations

import pytest
from ulid import ULID

from app.models import Project, ProjectWorkspace
from app.projects.service import ProjectService, assert_project_in_space
from app.schemas import ProjectCreate, ProjectUpdate, ProjectWorkspaceLinkCreate
from tests.support import factories
from tests.support.ids import DEFAULT_USER_ID, PERSONAL_SPACE_ID


def _space() -> str:
    return str(ULID())


def _user_id() -> str:
    return str(ULID())


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------


def test_create_project_returns_active_row(db):
    # PERSONAL_SPACE_ID is already seeded by conftest; use it directly.
    svc = ProjectService(db)
    row = svc.create(
        PERSONAL_SPACE_ID,
        ProjectCreate(name="Alpha"),
        created_by_user_id=DEFAULT_USER_ID,
        commit=False,
    )
    assert row.id
    assert row.space_id == PERSONAL_SPACE_ID
    assert row.name == "Alpha"
    assert row.status == "active"
    assert row.deleted_at is None


def test_create_project_strips_name_whitespace(db):
    svc = ProjectService(db)
    row = svc.create(
        PERSONAL_SPACE_ID,
        ProjectCreate(name="  Beta  "),
        commit=False,
    )
    assert row.name == "Beta"


def test_create_duplicate_active_name_raises(db):
    sid = _space()
    factories.create_test_space(db, space_id=sid, commit=False)
    svc = ProjectService(db)
    svc.create(sid, ProjectCreate(name="Gamma"), commit=False)
    with pytest.raises(ValueError, match="already exists"):
        svc.create(sid, ProjectCreate(name="Gamma"), commit=False)


def test_create_same_name_different_spaces_allowed(db):
    a = _space()
    b = _space()
    factories.create_test_space(db, space_id=a, commit=False)
    factories.create_test_space(db, space_id=b, commit=False)
    svc = ProjectService(db)
    r1 = svc.create(a, ProjectCreate(name="Delta"), commit=False)
    r2 = svc.create(b, ProjectCreate(name="Delta"), commit=False)
    assert r1.id != r2.id


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


def test_list_projects_scoped_by_space(db):
    a = _space()
    b = _space()
    factories.create_test_space(db, space_id=a, commit=False)
    factories.create_test_space(db, space_id=b, commit=False)
    factories.create_test_project(db, space_id=a, name="P1")
    factories.create_test_project(db, space_id=a, name="P2")
    factories.create_test_project(db, space_id=b, name="P3")
    svc = ProjectService(db)
    total, rows = svc.list_projects(a)
    assert total == 2
    names = {r.name for r in rows}
    assert names == {"P1", "P2"}


def test_list_projects_excludes_archived_by_default(db):
    sid = _space()
    factories.create_test_space(db, space_id=sid, commit=False)
    factories.create_test_project(db, space_id=sid, name="Active")
    factories.create_test_project(db, space_id=sid, name="Archived", status="archived")
    svc = ProjectService(db)
    total, rows = svc.list_projects(sid)
    assert total == 1
    assert rows[0].name == "Active"


def test_list_projects_filter_by_status(db):
    sid = _space()
    factories.create_test_space(db, space_id=sid, commit=False)
    factories.create_test_project(db, space_id=sid, name="Active")
    factories.create_test_project(db, space_id=sid, name="Archived", status="archived")
    svc = ProjectService(db)
    total, rows = svc.list_projects(sid, status="archived")
    assert total == 1
    assert rows[0].name == "Archived"


# ---------------------------------------------------------------------------
# get
# ---------------------------------------------------------------------------


def test_get_returns_none_for_wrong_space(db):
    a = _space()
    b = _space()
    factories.create_test_space(db, space_id=a, commit=False)
    factories.create_test_space(db, space_id=b, commit=False)
    proj = factories.create_test_project(db, space_id=a)
    svc = ProjectService(db)
    assert svc.get(proj.id, b) is None


def test_get_returns_none_for_soft_deleted(db):
    sid = _space()
    factories.create_test_space(db, space_id=sid, commit=False)
    proj = factories.create_test_project(db, space_id=sid)
    from datetime import UTC, datetime
    proj.deleted_at = datetime.now(UTC)
    db.flush()
    svc = ProjectService(db)
    assert svc.get(proj.id, sid) is None


# ---------------------------------------------------------------------------
# update
# ---------------------------------------------------------------------------


def test_update_name_and_focus(db):
    sid = _space()
    factories.create_test_space(db, space_id=sid, commit=False)
    proj = factories.create_test_project(db, space_id=sid, name="Old")
    svc = ProjectService(db)
    updated = svc.update(
        proj.id,
        sid,
        ProjectUpdate(name="New", current_focus="ship it"),
        commit=False,
    )
    assert updated.name == "New"
    assert updated.current_focus == "ship it"


def test_update_raises_on_duplicate_name(db):
    sid = _space()
    factories.create_test_space(db, space_id=sid, commit=False)
    factories.create_test_project(db, space_id=sid, name="Existing")
    proj = factories.create_test_project(db, space_id=sid, name="Target")
    svc = ProjectService(db)
    with pytest.raises(ValueError, match="already exists"):
        svc.update(proj.id, sid, ProjectUpdate(name="Existing"), commit=False)


def test_update_returns_none_for_missing(db):
    sid = _space()
    factories.create_test_space(db, space_id=sid, commit=False)
    svc = ProjectService(db)
    assert svc.update("nonexistent", sid, ProjectUpdate(name="x"), commit=False) is None


# ---------------------------------------------------------------------------
# archive
# ---------------------------------------------------------------------------


def test_archive_sets_status_and_timestamp(db):
    sid = _space()
    factories.create_test_space(db, space_id=sid, commit=False)
    proj = factories.create_test_project(db, space_id=sid)
    svc = ProjectService(db)
    archived = svc.archive(proj.id, sid, commit=False)
    assert archived.status == "archived"
    assert archived.archived_at is not None


def test_archive_returns_none_for_wrong_space(db):
    a = _space()
    b = _space()
    factories.create_test_space(db, space_id=a, commit=False)
    factories.create_test_space(db, space_id=b, commit=False)
    proj = factories.create_test_project(db, space_id=a)
    svc = ProjectService(db)
    assert svc.archive(proj.id, b, commit=False) is None


# ---------------------------------------------------------------------------
# workspace linking
# ---------------------------------------------------------------------------


def test_link_workspace_creates_association(db):
    sid = _space()
    uid = _user_id()
    factories.create_test_space(db, space_id=sid, commit=False)
    factories.create_test_user(db, space_id=sid, user_id=uid, commit=False)
    proj = factories.create_test_project(db, space_id=sid)
    ws = factories.create_test_workspace(db, space_id=sid, created_by_user_id=uid)
    svc = ProjectService(db)
    link = svc.link_workspace(
        proj.id, sid, ProjectWorkspaceLinkCreate(workspace_id=ws.id, role="docs"), commit=False
    )
    assert link.project_id == proj.id
    assert link.workspace_id == ws.id
    assert link.role == "docs"


def test_link_workspace_prevents_duplicate_role(db):
    sid = _space()
    uid = _user_id()
    factories.create_test_space(db, space_id=sid, commit=False)
    factories.create_test_user(db, space_id=sid, user_id=uid, commit=False)
    proj = factories.create_test_project(db, space_id=sid)
    ws = factories.create_test_workspace(db, space_id=sid, created_by_user_id=uid)
    svc = ProjectService(db)
    svc.link_workspace(
        proj.id, sid, ProjectWorkspaceLinkCreate(workspace_id=ws.id, role="docs"), commit=False
    )
    with pytest.raises(ValueError, match="already linked"):
        svc.link_workspace(
            proj.id, sid, ProjectWorkspaceLinkCreate(workspace_id=ws.id, role="docs"), commit=False
        )


def test_link_workspace_prevents_cross_space(db):
    a = _space()
    b = _space()
    ua = _user_id()
    factories.create_test_space(db, space_id=a, commit=False)
    factories.create_test_space(db, space_id=b, commit=False)
    factories.create_test_user(db, space_id=a, user_id=ua, commit=False)
    proj = factories.create_test_project(db, space_id=a)
    ws_b = factories.create_test_workspace(db, space_id=b, created_by_user_id=ua)
    svc = ProjectService(db)
    with pytest.raises(ValueError, match="not found in this space"):
        svc.link_workspace(
            proj.id, a, ProjectWorkspaceLinkCreate(workspace_id=ws_b.id), commit=False
        )


def test_unlink_workspace_removes_link(db):
    sid = _space()
    uid = _user_id()
    factories.create_test_space(db, space_id=sid, commit=False)
    factories.create_test_user(db, space_id=sid, user_id=uid, commit=False)
    proj = factories.create_test_project(db, space_id=sid)
    ws = factories.create_test_workspace(db, space_id=sid, created_by_user_id=uid)
    svc = ProjectService(db)
    svc.link_workspace(
        proj.id, sid, ProjectWorkspaceLinkCreate(workspace_id=ws.id), commit=False
    )
    removed = svc.unlink_workspace(proj.id, ws.id, sid, commit=False)
    assert removed is True
    remaining = svc.list_workspaces(proj.id, sid)
    assert remaining == []


def test_unlink_workspace_returns_false_for_missing_link(db):
    sid = _space()
    uid = _user_id()
    factories.create_test_space(db, space_id=sid, commit=False)
    factories.create_test_user(db, space_id=sid, user_id=uid, commit=False)
    proj = factories.create_test_project(db, space_id=sid)
    ws = factories.create_test_workspace(db, space_id=sid, created_by_user_id=uid)
    svc = ProjectService(db)
    assert svc.unlink_workspace(proj.id, ws.id, sid, commit=False) is False


# ---------------------------------------------------------------------------
# summary
# ---------------------------------------------------------------------------


def test_summary_returns_zero_counts_for_empty_project(db):
    sid = _space()
    factories.create_test_space(db, space_id=sid, commit=False)
    proj = factories.create_test_project(db, space_id=sid)
    svc = ProjectService(db)
    summary = svc.get_summary(proj.id, sid)
    assert summary is not None
    assert summary.project_id == proj.id
    assert summary.activity_count == 0
    assert summary.artifact_count == 0
    assert summary.pending_proposal_count == 0
    assert summary.workspace_count == 0
    assert summary.active_run_count == 0
    assert summary.memory_entry_count == 0


def test_summary_returns_none_for_missing_project(db):
    sid = _space()
    factories.create_test_space(db, space_id=sid, commit=False)
    svc = ProjectService(db)
    assert svc.get_summary("nonexistent", sid) is None


def test_summary_counts_linked_workspace(db):
    sid = _space()
    uid = _user_id()
    factories.create_test_space(db, space_id=sid, commit=False)
    factories.create_test_user(db, space_id=sid, user_id=uid, commit=False)
    proj = factories.create_test_project(db, space_id=sid)
    ws = factories.create_test_workspace(db, space_id=sid, created_by_user_id=uid)
    factories.create_test_project_workspace_link(db, project=proj, workspace=ws)
    svc = ProjectService(db)
    summary = svc.get_summary(proj.id, sid)
    assert summary.workspace_count == 1


# ---------------------------------------------------------------------------
# project_id nullable does not break existing ActivityRecord / MemoryEntry
# ---------------------------------------------------------------------------


def test_activity_record_without_project_id_is_valid(db):
    """Existing ActivityRecord rows with project_id=None remain valid."""
    sid = _space()
    factories.create_test_space(db, space_id=sid, commit=False)
    activity = factories.create_test_activity(db, space_id=sid)
    db.flush()
    assert activity.project_id is None


def test_memory_entry_without_project_id_is_valid(db):
    """Existing MemoryEntry rows with project_id=None remain valid."""
    sid = _space()
    uid = _user_id()
    factories.create_test_space(db, space_id=sid, commit=False)
    factories.create_test_user(db, space_id=sid, user_id=uid, commit=False)
    mem = factories.create_test_memory_entry(db, space_id=sid, content="x", owner_user_id=uid)
    db.flush()
    assert mem.project_id is None


# ---------------------------------------------------------------------------
# assert_project_in_space — soft-FK enforcement utility
# ---------------------------------------------------------------------------


def test_assert_project_in_space_passes_for_none(db):
    """None is always valid — nullable column."""
    sid = _space()
    factories.create_test_space(db, space_id=sid, commit=False)
    assert_project_in_space(db, None, sid)  # must not raise


def test_assert_project_in_space_passes_for_valid_project(db):
    sid = _space()
    factories.create_test_space(db, space_id=sid, commit=False)
    proj = factories.create_test_project(db, space_id=sid)
    assert_project_in_space(db, proj.id, sid)  # must not raise


def test_assert_project_in_space_raises_for_wrong_space(db):
    a = _space()
    b = _space()
    factories.create_test_space(db, space_id=a, commit=False)
    factories.create_test_space(db, space_id=b, commit=False)
    proj = factories.create_test_project(db, space_id=a)
    with pytest.raises(ValueError, match="not found in space"):
        assert_project_in_space(db, proj.id, b)


def test_assert_project_in_space_raises_for_nonexistent(db):
    sid = _space()
    factories.create_test_space(db, space_id=sid, commit=False)
    with pytest.raises(ValueError, match="not found in space"):
        assert_project_in_space(db, "no-such-id", sid)


def test_assert_project_in_space_raises_for_soft_deleted(db):
    from datetime import UTC, datetime
    sid = _space()
    factories.create_test_space(db, space_id=sid, commit=False)
    proj = factories.create_test_project(db, space_id=sid)
    proj.deleted_at = datetime.now(UTC)
    db.flush()
    with pytest.raises(ValueError, match="not found in space"):
        assert_project_in_space(db, proj.id, sid)
