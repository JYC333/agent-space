"""HTTP contract: Intake API maps service-layer validation to 4xx responses."""

from __future__ import annotations

from ulid import ULID

from app.intake.service import IntakeService
from tests.support import factories


def _params(space_id: str) -> dict[str, str]:
    return {"space_id": space_id}


def test_create_evidence_missing_reference_returns_404(db, cross_space_pair):
    space_id = cross_space_pair["space_a_id"]
    client = cross_space_pair["client_a"]
    db.commit()

    response = client.post(
        "/api/v1/intake/evidence",
        params=_params(space_id),
        json={
            "title": "Missing intake reference",
            "intake_item_id": str(ULID()),
            "evidence_type": "claim",
        },
    )

    assert response.status_code == 404


def test_create_connection_missing_credential_returns_404(db, cross_space_pair):
    space_id = cross_space_pair["space_a_id"]
    client = cross_space_pair["client_a"]
    db.commit()

    response = client.post(
        "/api/v1/intake/connections",
        params=_params(space_id),
        json={
            "connector_key": "manual_url",
            "name": "Missing credential",
            "credential_id": str(ULID()),
        },
    )

    assert response.status_code == 404


def test_create_evidence_internal_source_uri_returns_422(db, cross_space_pair):
    space_id = cross_space_pair["space_a_id"]
    user_id = cross_space_pair["user_a"].id
    client = cross_space_pair["client_a"]
    activity = factories.create_test_activity(
        db,
        space_id=space_id,
        actor_user_id=user_id,
        title="Internal source",
        commit=True,
    )

    response = client.post(
        "/api/v1/intake/evidence",
        params=_params(space_id),
        json={
            "title": "Bad internal source",
            "source_object_type": "activity_record",
            "source_object_id": activity.id,
            "source_uri": "https://example.com/not-internal",
            "evidence_type": "event",
        },
    )

    assert response.status_code == 422


def test_create_evidence_link_missing_target_id_returns_422(db, cross_space_pair):
    space_id = cross_space_pair["space_a_id"]
    user_id = cross_space_pair["user_a"].id
    client = cross_space_pair["client_a"]
    evidence = IntakeService(db).create_evidence(
        space_id=space_id,
        evidence_type="claim",
        title="Link target validation",
        status="active",
        created_by_user_id=user_id,
    )
    db.commit()

    response = client.post(
        "/api/v1/intake/evidence-links",
        params=_params(space_id),
        json={
            "evidence_id": evidence.id,
            "target_type": "workspace",
        },
    )

    assert response.status_code == 422


def test_create_workspace_binding_unlinked_project_returns_422(db, cross_space_pair):
    space_id = cross_space_pair["space_a_id"]
    user_id = cross_space_pair["user_a"].id
    client = cross_space_pair["client_a"]
    workspace = factories.create_test_workspace(db, space_id=space_id, created_by_user_id=user_id)
    project = factories.create_test_project(db, space_id=space_id, owner_user_id=user_id)
    connection = IntakeService(db).create_connection(
        space_id=space_id,
        owner_user_id=user_id,
        connector_key="manual_url",
        name="Manual",
    )
    db.commit()

    response = client.post(
        "/api/v1/intake/workspace-source-bindings",
        params=_params(space_id),
        json={
            "workspace_id": workspace.id,
            "source_connection_id": connection.id,
            "project_id": project.id,
            "binding_key": "unlinked",
        },
    )

    assert response.status_code == 422
