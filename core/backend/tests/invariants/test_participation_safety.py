"""Invariant: try_record_participation failure cannot roll back the caller's transaction.

Tests verify that when participation record creation fails, the primary operation
already committed before the participation hook is unaffected, and the failure
is silently logged without raising.
"""

from __future__ import annotations

import logging
from unittest.mock import patch

import pytest
from ulid import ULID

from app.models import Task
from app.participation.service import record_participation, try_record_participation
from tests.support import factories


def _new_id() -> str:
    return str(ULID())


def test_participation_failure_does_not_rollback_committed_primary_op(db):
    """Force participation to fail after primary op; primary op stays committed."""
    space_id = _new_id()
    factories.create_test_space(db, space_id=space_id, name="Safety test", space_type="team", commit=False)
    user = factories.create_test_user(db, space_id=space_id, commit=True)

    task = Task(
        id=_new_id(), space_id=space_id, title="Primary op", status="inbox", priority="normal"
    )
    db.add(task)
    db.commit()  # primary op committed — participation hasn't run yet

    # Force participation to raise inside the savepoint; patch the logger to capture the warning
    with patch(
        "app.participation.service.record_participation",
        side_effect=RuntimeError("forced participation failure"),
    ), patch("app.participation.service.log") as mock_log:
        try_record_participation(
            db,
            user_id=user.id,
            source_space_id=space_id,
            source_object_type="task",
            source_object_id=task.id,
            role="created",
        )

    # Primary op must still exist — not rolled back
    fetched = db.query(Task).filter(Task.id == task.id).first()
    assert fetched is not None, "Primary task was rolled back by participation failure"

    # Warning must have been emitted by the failure handler
    mock_log.warning.assert_called_once()


def test_participation_failure_leaves_session_usable(db):
    """After participation failure, the DB session must still accept new writes."""
    space_id = _new_id()
    factories.create_test_space(db, space_id=space_id, name="Session usable", space_type="team", commit=True)
    user = factories.create_test_user(db, space_id=space_id, commit=True)

    with patch(
        "app.participation.service.record_participation",
        side_effect=RuntimeError("forced"),
    ):
        try_record_participation(
            db,
            user_id=user.id,
            source_space_id=space_id,
            source_object_type="task",
            source_object_id=_new_id(),
            role="created",
        )

    # Session must still be usable for new writes
    task = Task(
        id=_new_id(), space_id=space_id, title="After failure", status="inbox", priority="normal"
    )
    db.add(task)
    db.commit()
    assert db.query(Task).filter(Task.id == task.id).first() is not None


def test_participation_success_does_not_require_manual_commit(db):
    """Successful participation write is committed by try_record_participation itself."""
    personal_id = _new_id()
    team_id = _new_id()
    factories.create_test_space(db, space_id=personal_id, name="Personal", space_type="personal", commit=False)
    factories.create_test_space(db, space_id=team_id, name="Team", space_type="team", commit=False)
    user = factories.create_test_user(db, space_id=personal_id, commit=False)
    from app.models import SpaceMembership
    db.add(SpaceMembership(id=_new_id(), space_id=team_id, user_id=user.id, role="member", status="active"))
    db.commit()

    obj_id = _new_id()
    try_record_participation(
        db,
        user_id=user.id,
        source_space_id=team_id,
        source_object_type="task",
        source_object_id=obj_id,
        role="created",
    )

    from app.models import ParticipationRecord
    rec = (
        db.query(ParticipationRecord)
        .filter(
            ParticipationRecord.user_id == user.id,
            ParticipationRecord.source_object_id == obj_id,
        )
        .first()
    )
    assert rec is not None, "ParticipationRecord was not persisted on success"
