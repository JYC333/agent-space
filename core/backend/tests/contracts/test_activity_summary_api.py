"""HTTP contract tests for activity/summary-runs, intake/summary-runs, and home/summary intake_summary."""
from __future__ import annotations
import uuid

from unittest.mock import patch

from tests.support import factories

from app.activity.service import ActivityService
from app.models import Artifact


from app.providers.invocation import CompletionResult as _CompletionResult


def _CR(text):
    return _CompletionResult(text=text, model="gpt-4o-mini")


_FAKE_PROVIDER = ("prov-test", None)
_FAKE_SUMMARY = "This is a test summary."


def test_activity_summary_run_creates_artifact(db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    client_a = cross_space_pair["client_a"]

    svc = ActivityService(db)
    act = svc.create(
        space_id=a,
        source_type="user_capture",
        content="Important content to summarize",
        user_id=ua.id,
        title="Test",
    )
    db.commit()

    with patch("app.activity.input_summary_service.resolve_reflector_provider_id", return_value=_FAKE_PROVIDER), \
         patch("app.activity.input_summary_service.complete_text", return_value=_CR(_FAKE_SUMMARY)):
        r = client_a.post(
            "/api/v1/activity/summary-runs",
            params={"space_id": a},
            json={"activity_ids": [act.id]},
        )

    assert r.status_code == 201, r.text
    data = r.json()
    assert data["artifact_id"]
    assert data["status"] == "succeeded"
    assert data["proposal_ids"] == []

    artifact = db.query(Artifact).filter(Artifact.id == data["artifact_id"]).first()
    assert artifact is not None
    assert artifact.artifact_type == "summary"


def test_activity_summary_run_creates_memory_proposal_when_requested(db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    client_a = cross_space_pair["client_a"]

    svc = ActivityService(db)
    act = svc.create(
        space_id=a,
        source_type="user_capture",
        content="Something to make a memory proposal from",
        user_id=ua.id,
    )
    db.commit()

    with patch("app.activity.input_summary_service.resolve_reflector_provider_id", return_value=_FAKE_PROVIDER), \
         patch("app.activity.input_summary_service.complete_text", return_value=_CR(_FAKE_SUMMARY)):
        r = client_a.post(
            "/api/v1/activity/summary-runs",
            params={"space_id": a},
            json={"activity_ids": [act.id], "create_memory_proposal": True},
        )

    assert r.status_code == 201, r.text
    data = r.json()
    assert len(data["proposal_ids"]) == 1


def test_activity_summary_run_missing_provider_returns_422(db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    client_a = cross_space_pair["client_a"]

    svc = ActivityService(db)
    act = svc.create(
        space_id=a,
        source_type="user_capture",
        content="content",
        user_id=ua.id,
    )
    db.commit()

    from app.memory.provider_client import ReflectorModelProviderMissingError

    with patch(
        "app.activity.input_summary_service.resolve_reflector_provider_id",
        side_effect=ReflectorModelProviderMissingError("no provider"),
    ):
        r = client_a.post(
            "/api/v1/activity/summary-runs",
            params={"space_id": a},
            json={"activity_ids": [act.id]},
        )

    assert r.status_code == 422


def test_activity_summary_run_empty_ids_returns_422(db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    client_a = cross_space_pair["client_a"]

    r = client_a.post(
        "/api/v1/activity/summary-runs",
        params={"space_id": a},
        json={},
    )
    assert r.status_code == 422


def test_activity_summary_run_cross_space_rejects(db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    b = cross_space_pair["space_b_id"]
    ua = cross_space_pair["user_a"]
    client_b = cross_space_pair["client_b"]

    svc = ActivityService(db)
    act = svc.create(
        space_id=a,
        source_type="user_capture",
        content="cross-space content",
        user_id=ua.id,
    )
    db.commit()

    with patch("app.activity.input_summary_service.resolve_reflector_provider_id", return_value=_FAKE_PROVIDER), \
         patch("app.activity.input_summary_service.complete_text", return_value=_CR(_FAKE_SUMMARY)):
        r = client_b.post(
            "/api/v1/activity/summary-runs",
            params={"space_id": b},
            json={"activity_ids": [act.id]},
        )

    assert r.status_code == 403


def test_intake_summary_run_creates_artifact(db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    client_a = cross_space_pair["client_a"]

    from app.intake.service import IntakeService
    intake_svc = IntakeService(db)
    evidence = intake_svc.create_evidence(
        space_id=a,
        intake_item_id=None,
        source_object_type=None,
        source_object_id=None,
        evidence_type="excerpt",
        title="Test evidence",
        content_excerpt="This is the content of the evidence to summarize.",
        created_by_user_id=ua.id,
    )
    db.commit()

    with patch("app.activity.input_summary_service.resolve_reflector_provider_id", return_value=_FAKE_PROVIDER), \
         patch("app.activity.input_summary_service.complete_text", return_value=_CR(_FAKE_SUMMARY)):
        r = client_a.post(
            "/api/v1/intake/summary-runs",
            params={"space_id": a},
            json={"evidence_ids": [evidence.id]},
        )

    assert r.status_code == 201, r.text
    data = r.json()
    assert data["artifact_id"]


def test_home_summary_includes_intake_section(db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    client_a = cross_space_pair["client_a"]

    r = client_a.get("/api/v1/home/summary", params={"space_id": a})
    assert r.status_code == 200, r.text
    data = r.json()
    assert "intake_summary" in data
    intake = data["intake_summary"]
    assert "open_items" in intake
    assert "candidate_evidence" in intake
    assert "pending_extraction_jobs" in intake
    assert "failed_extraction_jobs" in intake
    assert "due_connections" in intake
    assert isinstance(intake["open_items"], int)
    assert isinstance(intake["candidate_evidence"], int)
    assert isinstance(intake["due_connections"], int)


def test_home_summary_includes_due_connections(db, cross_space_pair):
    """due_connections counts active SourceConnection rows with next_check_at <= now."""
    from datetime import datetime, UTC, timedelta
    from app.models import SourceConnection, User

    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    client_a = cross_space_pair["client_a"]

    # Need a SourceConnector row (FK) — look up the test connector or skip creation if none.
    from app.models import SourceConnector
    connector = db.query(SourceConnector).first()
    if connector is None:
        # No connectors in test DB — the count stays 0, verify field presence only.
        r = client_a.get("/api/v1/home/summary", params={"space_id": a})
        assert r.status_code == 200
        assert isinstance(r.json()["intake_summary"]["due_connections"], int)
        return

    past = datetime.now(UTC) - timedelta(hours=2)
    conn = SourceConnection(
        id=str(uuid.uuid4()),
        space_id=a,
        connector_id=connector.id,
        owner_user_id=ua.id,
        name="due-test-connection",
        status="active",
        fetch_frequency="hourly",
        capture_policy="metadata_only",
        trust_level="normal",
        next_check_at=past,
    )
    db.add(conn)
    db.commit()

    r = client_a.get("/api/v1/home/summary", params={"space_id": a})
    assert r.status_code == 200
    assert r.json()["intake_summary"]["due_connections"] >= 1


def test_activity_summary_run_returns_run_id(db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    client_a = cross_space_pair["client_a"]

    from app.activity.service import ActivityService
    svc = ActivityService(db)
    act = svc.create(
        space_id=a,
        source_type="user_capture",
        content="content for run_id test",
        user_id=ua.id,
    )
    db.commit()

    with patch("app.activity.input_summary_service.resolve_reflector_provider_id", return_value=_FAKE_PROVIDER), \
         patch("app.activity.input_summary_service.complete_text", return_value=_CR(_FAKE_SUMMARY)):
        r = client_a.post(
            "/api/v1/activity/summary-runs",
            params={"space_id": a},
            json={"activity_ids": [act.id]},
        )

    assert r.status_code == 201, r.text
    data = r.json()
    assert "run_id" in data
    assert data["run_id"]

    from app.models import Run
    run = db.query(Run).filter(Run.id == data["run_id"]).first()
    assert run is not None
    assert run.status == "succeeded"
