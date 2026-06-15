"""HTTP contract: identity introspection port.

`GET /api/v1/auth/introspect` exposes the `get_identity` resolution for the TS
control plane. It must carry identifiers only — never token, session, or key
material — and must enforce exactly the `get_identity` semantics (401 without
credentials, membership-checked space selection with them).
"""

from __future__ import annotations

INTROSPECT_WIRE_CONTRACT: dict[str, tuple[type, ...]] = {
    "space_id": (str,),
    "user_id": (str,),
}


def test_introspect_unauthenticated_returns_401(api_client):
    r = api_client.get("/api/v1/auth/introspect")
    assert r.status_code == 401


def test_introspect_resolves_identity_with_exact_wire_shape(
    api_client, db, cross_space_pair
):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    db.commit()

    r = cross_space_pair["client_a"].get(
        "/api/v1/auth/introspect", params={"space_id": a}
    )
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == set(INTROSPECT_WIRE_CONTRACT.keys())
    for field, allowed in INTROSPECT_WIRE_CONTRACT.items():
        assert isinstance(body[field], allowed)
    assert body == {"space_id": a, "user_id": ua.id}


def test_introspect_rejects_non_member_space(api_client, db, cross_space_pair):
    b = cross_space_pair["space_b_id"]
    db.commit()

    r = cross_space_pair["client_a"].get(
        "/api/v1/auth/introspect", params={"space_id": b}
    )
    assert r.status_code in (401, 403)
