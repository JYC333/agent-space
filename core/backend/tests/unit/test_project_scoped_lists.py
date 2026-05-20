"""Unit tests for project_id filter on durable object list APIs."""

from __future__ import annotations

import pytest
from ulid import ULID

from app.activity.service import ActivityService
from app.artifacts.service import ArtifactReadService
from app.memory.proposals import ProposalService
from app.memory.store import MemoryStore
from app.runs.run_service import RunService
from tests.support import factories
from tests.support.ids import DEFAULT_USER_ID, PERSONAL_SPACE_ID


def _space() -> str:
    return str(ULID())


def _user() -> str:
    return str(ULID())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _project(db, space_id):
    return factories.create_test_project(db, space_id=space_id, commit=False)


def _space_with_project(db):
    sid = _space()
    factories.create_test_space(db, space_id=sid, commit=False)
    proj = _project(db, sid)
    return sid, proj


# ---------------------------------------------------------------------------
# Activity
# ---------------------------------------------------------------------------

class TestActivityProjectFilter:
    def test_returns_only_project_activities(self, db):
        sid, proj = _space_with_project(db)
        svc = ActivityService(db)
        r1 = svc.create(sid, "user_capture", "in-project", user_id=DEFAULT_USER_ID)
        r1.project_id = proj.id
        r2 = svc.create(sid, "user_capture", "no-project", user_id=DEFAULT_USER_ID)

        result = svc.list(sid, project_id=proj.id)
        ids = {r.id for r in result}
        assert r1.id in ids
        assert r2.id not in ids

    def test_empty_when_no_matches(self, db):
        sid, proj = _space_with_project(db)
        svc = ActivityService(db)
        svc.create(sid, "user_capture", "no-project", user_id=DEFAULT_USER_ID)

        result = svc.list(sid, project_id=proj.id)
        assert result == []

    def test_cross_space_project_id_raises(self, db):
        sid1 = _space()
        sid2 = _space()
        factories.create_test_space(db, space_id=sid1, commit=False)
        factories.create_test_space(db, space_id=sid2, commit=False)
        proj = _project(db, sid1)

        svc = ActivityService(db)
        with pytest.raises(ValueError, match="not found in space"):
            svc.list(sid2, project_id=proj.id)


# ---------------------------------------------------------------------------
# Artifact
# ---------------------------------------------------------------------------

class TestArtifactProjectFilter:
    def test_returns_only_project_artifacts(self, db):
        sid, proj = _space_with_project(db)
        a1 = factories.create_test_artifact(db, space_id=sid, title="in-project")
        a1.project_id = proj.id
        a2 = factories.create_test_artifact(db, space_id=sid, title="no-project")

        svc = ArtifactReadService(db)
        total, rows = svc.list_artifacts(sid, project_id=proj.id)
        ids = {r.id for r in rows}
        assert a1.id in ids
        assert a2.id not in ids
        assert total == 1

    def test_empty_when_no_matches(self, db):
        sid, proj = _space_with_project(db)
        factories.create_test_artifact(db, space_id=sid, title="no-project")

        svc = ArtifactReadService(db)
        total, rows = svc.list_artifacts(sid, project_id=proj.id)
        assert total == 0
        assert rows == []

    def test_cross_space_project_id_raises(self, db):
        sid1 = _space()
        sid2 = _space()
        factories.create_test_space(db, space_id=sid1, commit=False)
        factories.create_test_space(db, space_id=sid2, commit=False)
        proj = _project(db, sid1)

        svc = ArtifactReadService(db)
        with pytest.raises(ValueError, match="not found in space"):
            svc.list_artifacts(sid2, project_id=proj.id)


# ---------------------------------------------------------------------------
# Proposal
# ---------------------------------------------------------------------------

class TestProposalProjectFilter:
    def test_returns_only_project_proposals(self, db):
        sid, proj = _space_with_project(db)
        p1 = factories.create_test_proposal(db, space_id=sid, created_by_user_id=DEFAULT_USER_ID)
        p1.project_id = proj.id
        p2 = factories.create_test_proposal(db, space_id=sid, created_by_user_id=DEFAULT_USER_ID)

        svc = ProposalService(db)
        items = svc.list_proposals(sid, DEFAULT_USER_ID, status="pending", project_id=proj.id)
        ids = {p.id for p in items}
        assert p1.id in ids
        assert p2.id not in ids

    def test_count_with_project_filter(self, db):
        sid, proj = _space_with_project(db)
        p1 = factories.create_test_proposal(db, space_id=sid, created_by_user_id=DEFAULT_USER_ID)
        p1.project_id = proj.id
        factories.create_test_proposal(db, space_id=sid, created_by_user_id=DEFAULT_USER_ID)

        svc = ProposalService(db)
        n = svc.count_proposals(sid, DEFAULT_USER_ID, status="pending", project_id=proj.id)
        assert n == 1

    def test_cross_space_project_id_raises_in_list(self, db):
        sid1 = _space()
        sid2 = _space()
        factories.create_test_space(db, space_id=sid1, commit=False)
        factories.create_test_space(db, space_id=sid2, commit=False)
        proj = _project(db, sid1)

        svc = ProposalService(db)
        with pytest.raises(ValueError, match="not found in space"):
            svc.list_proposals(sid2, DEFAULT_USER_ID, project_id=proj.id)

    def test_cross_space_project_id_raises_in_count(self, db):
        sid1 = _space()
        sid2 = _space()
        factories.create_test_space(db, space_id=sid1, commit=False)
        factories.create_test_space(db, space_id=sid2, commit=False)
        proj = _project(db, sid1)

        svc = ProposalService(db)
        with pytest.raises(ValueError, match="not found in space"):
            svc.count_proposals(sid2, DEFAULT_USER_ID, project_id=proj.id)


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

class TestRunProjectFilter:
    def test_returns_only_project_runs(self, db):
        sid, proj = _space_with_project(db)
        r1 = factories.create_test_run(db, space_id=sid, user_id=DEFAULT_USER_ID)
        r1.project_id = proj.id
        r2 = factories.create_test_run(db, space_id=sid, user_id=DEFAULT_USER_ID)

        svc = RunService(db)
        runs = svc.list_runs(sid, project_id=proj.id)
        ids = {r.id for r in runs}
        assert r1.id in ids
        assert r2.id not in ids

    def test_empty_when_no_matches(self, db):
        sid, proj = _space_with_project(db)
        factories.create_test_run(db, space_id=sid, user_id=DEFAULT_USER_ID)

        svc = RunService(db)
        runs = svc.list_runs(sid, project_id=proj.id)
        assert runs == []

    def test_cross_space_project_id_raises(self, db):
        sid1 = _space()
        sid2 = _space()
        factories.create_test_space(db, space_id=sid1, commit=False)
        factories.create_test_space(db, space_id=sid2, commit=False)
        proj = _project(db, sid1)

        svc = RunService(db)
        with pytest.raises(ValueError, match="not found in space"):
            svc.list_runs(sid2, project_id=proj.id)


# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------

class TestMemoryProjectFilter:
    def test_returns_only_project_memories(self, db):
        sid, proj = _space_with_project(db)
        m1 = factories.create_test_memory_entry(db, space_id=sid, owner_user_id=DEFAULT_USER_ID)
        m1.project_id = proj.id
        m2 = factories.create_test_memory_entry(db, space_id=sid, owner_user_id=DEFAULT_USER_ID)

        store = MemoryStore(db)
        items = store.list(sid, DEFAULT_USER_ID, project_id=proj.id)
        ids = {m.id for m in items}
        assert m1.id in ids
        assert m2.id not in ids

    def test_count_with_project_filter(self, db):
        sid, proj = _space_with_project(db)
        m1 = factories.create_test_memory_entry(db, space_id=sid, owner_user_id=DEFAULT_USER_ID)
        m1.project_id = proj.id
        factories.create_test_memory_entry(db, space_id=sid, owner_user_id=DEFAULT_USER_ID)

        store = MemoryStore(db)
        n = store.count(sid, DEFAULT_USER_ID, project_id=proj.id)
        assert n == 1

    def test_cross_space_project_id_raises_in_list(self, db):
        sid1 = _space()
        sid2 = _space()
        factories.create_test_space(db, space_id=sid1, commit=False)
        factories.create_test_space(db, space_id=sid2, commit=False)
        proj = _project(db, sid1)

        store = MemoryStore(db)
        with pytest.raises(ValueError, match="not found in space"):
            store.list(sid2, DEFAULT_USER_ID, project_id=proj.id)

    def test_cross_space_project_id_raises_in_count(self, db):
        sid1 = _space()
        sid2 = _space()
        factories.create_test_space(db, space_id=sid1, commit=False)
        factories.create_test_space(db, space_id=sid2, commit=False)
        proj = _project(db, sid1)

        store = MemoryStore(db)
        with pytest.raises(ValueError, match="not found in space"):
            store.count(sid2, DEFAULT_USER_ID, project_id=proj.id)
