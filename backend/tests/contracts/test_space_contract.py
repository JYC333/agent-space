"""HTTP contract: space type vocabulary, auth, and two-person membership boundaries."""

from __future__ import annotations
import uuid


from app.auth.session import SESSION_COOKIE, UserSessionService
from app.main import app as _app
from app.models import Space, SpaceMembership
from starlette.testclient import TestClient
from tests.support import factories


def _authed_client(db, user_id: str) -> TestClient:
    _, raw = UserSessionService(db).create(user_id)
    return TestClient(_app, cookies={SESSION_COOKIE: raw}, raise_server_exceptions=True)


def _params(space_id: str) -> dict[str, str]:
    return {"space_id": space_id}


def _membership(space_id: str, user_id: str, role: str = "member") -> SpaceMembership:
    return SpaceMembership(id=str(uuid.uuid4()), space_id=space_id, user_id=user_id, role=role, status="active")


def test_create_space_uses_household_as_canonical_type(api_client, db, cross_space_pair_db):
    ua = cross_space_pair_db["user_a"]

    r = _authed_client(db, ua.id).post(
        "/api/v1/spaces",
        json={"name": "Household", "type": "household"},
    )

    assert r.status_code == 201, r.text
    body = r.json()
    assert body["type"] == "household"

    db.expire_all()
    row = db.query(Space).filter(Space.id == body["id"]).one()
    assert row.type == "household"


def test_create_space_rejects_family_type_string(api_client, db, cross_space_pair_db):
    ua = cross_space_pair_db["user_a"]

    r = _authed_client(db, ua.id).post(
        "/api/v1/spaces",
        json={"name": "Family label", "type": "family"},
    )

    assert r.status_code == 422


def test_create_team_space_returns_team(api_client, db, cross_space_pair_db):
    ua = cross_space_pair_db["user_a"]

    r = _authed_client(db, ua.id).post(
        "/api/v1/spaces",
        json={"name": "Team", "type": "team"},
    )

    assert r.status_code == 201, r.text
    assert r.json()["type"] == "team"


def test_personal_space_is_private_to_member(api_client, db):
    personal_id = str(uuid.uuid4())
    other_space_id = str(uuid.uuid4())
    factories.create_test_space(db, space_id=personal_id, name="A personal", space_type="personal")
    factories.create_test_space(db, space_id=other_space_id, name="B personal", space_type="personal")
    ua = factories.create_test_user(db, space_id=personal_id, display_name="Owner A")
    ub = factories.create_test_user(db, space_id=other_space_id, display_name="Owner B")
    db.commit()

    ok = _authed_client(db, ua.id).get(
        f"/api/v1/spaces/{personal_id}",
        params=_params(personal_id),
    )
    denied = _authed_client(db, ub.id).get(
        f"/api/v1/spaces/{personal_id}",
        params=_params(personal_id),
    )

    assert ok.status_code == 200, ok.text
    assert ok.json()["type"] == "personal"
    assert denied.status_code == 403


def test_household_space_access_requires_membership(api_client, db):
    household_id = str(uuid.uuid4())
    outside_space_id = str(uuid.uuid4())
    member_home_id = str(uuid.uuid4())
    factories.create_test_space(db, space_id=household_id, name="Shared home", space_type="household")
    factories.create_test_space(db, space_id=outside_space_id, name="Outside", space_type="team")
    factories.create_test_space(db, space_id=member_home_id, name="Member home", space_type="personal")
    owner = factories.create_test_user(db, space_id=household_id, display_name="Owner")
    member = factories.create_test_user(db, space_id=member_home_id, display_name="Member")
    outsider = factories.create_test_user(db, space_id=outside_space_id, display_name="Outsider")
    db.add(_membership(household_id, member.id, "member"))
    db.commit()

    owner_read = _authed_client(db, owner.id).get(
        f"/api/v1/spaces/{household_id}",
        params=_params(household_id),
    )
    member_read = _authed_client(db, member.id).get(
        f"/api/v1/spaces/{household_id}",
        params=_params(household_id),
    )
    outsider_read = _authed_client(db, outsider.id).get(
        f"/api/v1/spaces/{household_id}",
        params=_params(household_id),
    )

    assert owner_read.status_code == 200, owner_read.text
    assert member_read.status_code == 200, member_read.text
    assert owner_read.json()["type"] == "household"
    assert member_read.json()["type"] == "household"
    assert outsider_read.status_code == 403


def test_unauthenticated_request_returns_401(api_client):
    r = api_client.get(
        "/api/v1/memory",
        params={"space_id": "personal"},
    )

    assert r.status_code == 401


def test_query_user_id_and_space_id_do_not_authenticate(api_client, db, cross_space_pair_db):
    """Query params never substitute for session/API-key auth."""
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]

    r = api_client.get(
        "/api/v1/memory",
        params={"space_id": a, "user_id": ua.id},
    )
    assert r.status_code == 401


def test_authenticated_memory_list_with_space_query_succeeds(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]

    r = cross_space_pair["client_a"].get(
        "/api/v1/memory",
        params={"space_id": a},
    )
    assert r.status_code == 200, r.text
