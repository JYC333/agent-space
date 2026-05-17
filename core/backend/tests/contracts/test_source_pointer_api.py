"""HTTP contract: SourcePointer API is membership-gated metadata only."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from ulid import ULID

from app.models import MemoryEntry, SourcePointer, SpaceMembership
from app.source_pointers.service import create_source_pointer
from tests.support import factories

_FORBIDDEN_FIELDS = frozenset({
    "content",
    "body",
    "raw_content",
    "payload",
    "summary",
    "copied_text",
    "source_snapshot",
    "memory_text",
    "artifact_payload",
    "public_url",
})


def _new_id() -> str:
    return str(ULID())


def _params(space_id: str, user_id: str) -> dict[str, str]:
    del user_id
    return {"space_id": space_id}


def _add_member(db, *, space_id: str, user_id: str, role: str = "member") -> None:
    db.add(
        SpaceMembership(
            id=_new_id(),
            space_id=space_id,
            user_id=user_id,
            role=role,
            status="active",
        )
    )


def _three_space_setup(db, cross_space_pair):
    """User A in space A (owner); space C exists with no extra members; user B only in B."""
    a = cross_space_pair["space_a_id"]
    b = cross_space_pair["space_b_id"]
    c = _new_id()
    ua = cross_space_pair["user_a"]
    ub = cross_space_pair["user_b"]
    factories.create_test_space(db, space_id=c, name="Space C", space_type="team")
    db.commit()
    return a, b, c, ua, ub


def test_create_pointer_member_of_owner_and_source_succeeds(db, cross_space_pair):
    a, b, _c, ua, _ub = _three_space_setup(db, cross_space_pair)
    _add_member(db, space_id=b, user_id=ua.id)
    db.commit()
    mem_id = _new_id()
    r = cross_space_pair["client_a"].post(
        "/api/v1/source-pointers",
        params=_params(a, ua.id),
        json={
            "owner_space_id": a,
            "source_space_id": b,
            "source_object_type": "memory",
            "source_object_id": mem_id,
            "access_mode": "read",
            "metadata_json": {"note": "provenance"},
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["owner_space_id"] == a
    assert body["source_space_id"] == b
    assert body["source_object_id"] == mem_id
    assert body["access_mode"] == "read"
    assert body["metadata_json"] == {"note": "provenance"}
    assert not (_FORBIDDEN_FIELDS & set(body.keys()))


def test_create_pointer_non_member_of_owner_forbidden(db, cross_space_pair):
    a, b, _c, _ua, ub = _three_space_setup(db, cross_space_pair)
    r = cross_space_pair["client_b"].post(
        "/api/v1/source-pointers",
        params=_params(b, ub.id),
        json={
            "owner_space_id": a,
            "source_space_id": b,
            "source_object_type": "memory",
            "source_object_id": _new_id(),
            "access_mode": "read",
        },
    )
    assert r.status_code == 403


def test_create_pointer_non_member_of_source_forbidden(db, cross_space_pair):
    a, _b, c, ua, _ub = _three_space_setup(db, cross_space_pair)
    r = cross_space_pair["client_a"].post(
        "/api/v1/source-pointers",
        params=_params(a, ua.id),
        json={
            "owner_space_id": a,
            "source_space_id": c,
            "source_object_type": "memory",
            "source_object_id": _new_id(),
            "access_mode": "read",
        },
    )
    assert r.status_code == 403


def test_create_invalid_access_mode_rejected(db, cross_space_pair):
    a, b, _c, ua, _ub = _three_space_setup(db, cross_space_pair)
    _add_member(db, space_id=b, user_id=ua.id)
    db.commit()
    r = cross_space_pair["client_a"].post(
        "/api/v1/source-pointers",
        params=_params(a, ua.id),
        json={
            "owner_space_id": a,
            "source_space_id": b,
            "source_object_type": "memory",
            "source_object_id": _new_id(),
            "access_mode": "full_read_grant",
        },
    )
    assert r.status_code == 400


def test_create_unsafe_metadata_json_rejected(db, cross_space_pair):
    a, b, _c, ua, _ub = _three_space_setup(db, cross_space_pair)
    _add_member(db, space_id=b, user_id=ua.id)
    db.commit()
    r = cross_space_pair["client_a"].post(
        "/api/v1/source-pointers",
        params=_params(a, ua.id),
        json={
            "owner_space_id": a,
            "source_space_id": b,
            "source_object_type": "memory",
            "source_object_id": _new_id(),
            "access_mode": "read",
            "metadata_json": {"content": "must not store"},
        },
    )
    assert r.status_code == 400
    assert "content" in r.text.lower() or "metadata" in r.text.lower()


def test_list_returns_pointers_for_member_owner_spaces(db, cross_space_pair):
    a, b, _c, ua, _ub = _three_space_setup(db, cross_space_pair)
    _add_member(db, space_id=b, user_id=ua.id)
    create_source_pointer(
        db,
        owner_space_id=a,
        source_space_id=b,
        source_object_type="memory",
        source_object_id=_new_id(),
        access_mode="read",
    )
    db.commit()
    r = cross_space_pair["client_a"].get(
        "/api/v1/source-pointers",
        params=_params(a, ua.id),
    )
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) >= 1
    assert all(i["owner_space_id"] == a for i in items)
    for item in items:
        assert not (_FORBIDDEN_FIELDS & set(item.keys()))


def test_list_filter_non_member_owner_space_forbidden(db, cross_space_pair):
    a, _b, _c, _ua, ub = _three_space_setup(db, cross_space_pair)
    r = cross_space_pair["client_b"].get(
        "/api/v1/source-pointers",
        params={**_params(cross_space_pair["space_b_id"], ub.id), "owner_space_id": a},
    )
    assert r.status_code == 403


def test_list_excludes_non_member_owner_spaces(db, cross_space_pair):
    a, b, _c, ua, ub = _three_space_setup(db, cross_space_pair)
    _add_member(db, space_id=b, user_id=ua.id)
    ptr_id = _new_id()
    create_source_pointer(
        db,
        owner_space_id=a,
        source_space_id=b,
        source_object_type="memory",
        source_object_id=ptr_id,
        access_mode="read",
    )
    db.commit()
    r = cross_space_pair["client_b"].get(
        "/api/v1/source-pointers",
        params=_params(b, ub.id),
    )
    assert r.status_code == 200
    ids = {i["id"] for i in r.json()["items"]}
    row = db.query(SourcePointer).filter(SourcePointer.source_object_id == ptr_id).first()
    assert row is not None
    assert row.id not in ids


def test_detail_returns_metadata_only(db, cross_space_pair):
    a, b, _c, ua, _ub = _three_space_setup(db, cross_space_pair)
    _add_member(db, space_id=b, user_id=ua.id)
    ptr = create_source_pointer(
        db,
        owner_space_id=a,
        source_space_id=b,
        source_object_type="memory",
        source_object_id=_new_id(),
        access_mode="subscribe",
        metadata_json={"label": "ref"},
    )
    db.commit()
    r = cross_space_pair["client_a"].get(
        f"/api/v1/source-pointers/{ptr.id}",
        params=_params(a, ua.id),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == ptr.id
    assert body["access_mode"] == "subscribe"
    assert body["metadata_json"] == {"label": "ref"}
    assert not (_FORBIDDEN_FIELDS & set(body.keys()))


def test_detail_non_member_of_owner_returns_404(db, cross_space_pair):
    a, b, _c, ua, ub = _three_space_setup(db, cross_space_pair)
    _add_member(db, space_id=b, user_id=ua.id)
    ptr = create_source_pointer(
        db,
        owner_space_id=a,
        source_space_id=b,
        source_object_type="memory",
        source_object_id=_new_id(),
        access_mode="read",
    )
    db.commit()
    r = cross_space_pair["client_b"].get(
        f"/api/v1/source-pointers/{ptr.id}",
        params=_params(b, ub.id),
    )
    assert r.status_code == 404


def test_delete_requires_admin_of_owner_space(db, cross_space_pair):
    a, b, _c, ua, ub = _three_space_setup(db, cross_space_pair)
    _add_member(db, space_id=b, user_id=ua.id)
    _add_member(db, space_id=a, user_id=ub.id, role="member")
    ptr = create_source_pointer(
        db,
        owner_space_id=a,
        source_space_id=b,
        source_object_type="memory",
        source_object_id=_new_id(),
        access_mode="read",
    )
    db.commit()
    denied = cross_space_pair["client_b"].delete(
        f"/api/v1/source-pointers/{ptr.id}",
        params=_params(a, ub.id),
    )
    assert denied.status_code == 403


def test_delete_admin_removes_pointer_not_source_object(db, cross_space_pair):
    a, b, _c, ua, _ub = _three_space_setup(db, cross_space_pair)
    _add_member(db, space_id=b, user_id=ua.id)
    mem = factories.create_test_memory_entry(
        db,
        space_id=b,
        content="SOURCE_OBJECT_MUST_SURVIVE",
        commit=False,
    )
    mem.visibility = "space_shared"
    ptr = create_source_pointer(
        db,
        owner_space_id=a,
        source_space_id=b,
        source_object_type="memory",
        source_object_id=mem.id,
        access_mode="read",
    )
    db.commit()
    ok = cross_space_pair["client_a"].delete(
        f"/api/v1/source-pointers/{ptr.id}",
        params=_params(a, ua.id),
    )
    assert ok.status_code == 204
    assert db.query(SourcePointer).filter(SourcePointer.id == ptr.id).first() is None
    assert db.query(MemoryEntry).filter(MemoryEntry.id == mem.id).first() is not None


def test_create_expires_at_in_past_rejected(db, cross_space_pair):
    a, b, _c, ua, _ub = _three_space_setup(db, cross_space_pair)
    _add_member(db, space_id=b, user_id=ua.id)
    db.commit()
    past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    r = cross_space_pair["client_a"].post(
        "/api/v1/source-pointers",
        params=_params(a, ua.id),
        json={
            "owner_space_id": a,
            "source_space_id": b,
            "source_object_type": "memory",
            "source_object_id": _new_id(),
            "access_mode": "read",
            "expires_at": past,
        },
    )
    assert r.status_code == 400


def test_create_sets_granted_by_from_authenticated_user(db, cross_space_pair):
    a, b, _c, ua, _ub = _three_space_setup(db, cross_space_pair)
    _add_member(db, space_id=b, user_id=ua.id)
    db.commit()
    r = cross_space_pair["client_a"].post(
        "/api/v1/source-pointers",
        params=_params(a, ua.id),
        json={
            "owner_space_id": a,
            "source_space_id": b,
            "source_object_type": "memory",
            "source_object_id": _new_id(),
            "access_mode": "read",
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["granted_by_user_id"] == ua.id


def test_create_rejects_client_supplied_granted_by_user_id(db, cross_space_pair):
    a, b, _c, ua, ub = _three_space_setup(db, cross_space_pair)
    _add_member(db, space_id=b, user_id=ua.id)
    db.commit()
    r = cross_space_pair["client_a"].post(
        "/api/v1/source-pointers",
        params=_params(a, ua.id),
        json={
            "owner_space_id": a,
            "source_space_id": b,
            "source_object_type": "memory",
            "source_object_id": _new_id(),
            "access_mode": "read",
            "granted_by_user_id": ub.id,
        },
    )
    assert r.status_code == 422
    row = (
        db.query(SourcePointer)
        .filter(SourcePointer.granted_by_user_id == ub.id)
        .first()
    )
    assert row is None


def test_create_rejects_nested_forbidden_metadata_key(db, cross_space_pair):
    a, b, _c, ua, _ub = _three_space_setup(db, cross_space_pair)
    _add_member(db, space_id=b, user_id=ua.id)
    db.commit()
    r = cross_space_pair["client_a"].post(
        "/api/v1/source-pointers",
        params=_params(a, ua.id),
        json={
            "owner_space_id": a,
            "source_space_id": b,
            "source_object_type": "memory",
            "source_object_id": _new_id(),
            "access_mode": "read",
            "metadata_json": {"safe": {"content": "nested secret"}},
        },
    )
    assert r.status_code == 400


def test_create_rejects_forbidden_metadata_key_inside_list(db, cross_space_pair):
    a, b, _c, ua, _ub = _three_space_setup(db, cross_space_pair)
    _add_member(db, space_id=b, user_id=ua.id)
    db.commit()
    r = cross_space_pair["client_a"].post(
        "/api/v1/source-pointers",
        params=_params(a, ua.id),
        json={
            "owner_space_id": a,
            "source_space_id": b,
            "source_object_type": "memory",
            "source_object_id": _new_id(),
            "access_mode": "read",
            "metadata_json": {"items": [{"payload": "hidden"}]},
        },
    )
    assert r.status_code == 400


def test_create_accepts_safe_nested_metadata(db, cross_space_pair):
    a, b, _c, ua, _ub = _three_space_setup(db, cross_space_pair)
    _add_member(db, space_id=b, user_id=ua.id)
    db.commit()
    r = cross_space_pair["client_a"].post(
        "/api/v1/source-pointers",
        params=_params(a, ua.id),
        json={
            "owner_space_id": a,
            "source_space_id": b,
            "source_object_type": "memory",
            "source_object_id": _new_id(),
            "access_mode": "read",
            "metadata_json": {
                "note": "ok",
                "refs": {"run_id": _new_id()},
                "tags": ["a", "b"],
            },
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["metadata_json"]["refs"]


def test_create_rejects_oversized_metadata_json(db, cross_space_pair):
    a, b, _c, ua, _ub = _three_space_setup(db, cross_space_pair)
    _add_member(db, space_id=b, user_id=ua.id)
    db.commit()
    metadata = {f"k{i:04d}": "x" * 100 for i in range(200)}
    r = cross_space_pair["client_a"].post(
        "/api/v1/source-pointers",
        params=_params(a, ua.id),
        json={
            "owner_space_id": a,
            "source_space_id": b,
            "source_object_type": "memory",
            "source_object_id": _new_id(),
            "access_mode": "read",
            "metadata_json": metadata,
        },
    )
    assert r.status_code == 400


def test_create_rejects_deeply_nested_metadata(db, cross_space_pair):
    from app.source_pointers.validation import MAX_METADATA_DEPTH

    a, b, _c, ua, _ub = _three_space_setup(db, cross_space_pair)
    _add_member(db, space_id=b, user_id=ua.id)
    db.commit()
    nested: dict = {}
    cursor = nested
    for _ in range(MAX_METADATA_DEPTH + 2):
        cursor["n"] = {}
        cursor = cursor["n"]
    r = cross_space_pair["client_a"].post(
        "/api/v1/source-pointers",
        params=_params(a, ua.id),
        json={
            "owner_space_id": a,
            "source_space_id": b,
            "source_object_type": "memory",
            "source_object_id": _new_id(),
            "access_mode": "read",
            "metadata_json": nested,
        },
    )
    assert r.status_code == 400


def test_create_rejects_too_many_metadata_items(db, cross_space_pair):
    from app.source_pointers.validation import MAX_METADATA_TOTAL_ITEMS

    a, b, _c, ua, _ub = _three_space_setup(db, cross_space_pair)
    _add_member(db, space_id=b, user_id=ua.id)
    db.commit()
    r = cross_space_pair["client_a"].post(
        "/api/v1/source-pointers",
        params=_params(a, ua.id),
        json={
            "owner_space_id": a,
            "source_space_id": b,
            "source_object_type": "memory",
            "source_object_id": _new_id(),
            "access_mode": "read",
            "metadata_json": {f"k{i}": i for i in range(MAX_METADATA_TOTAL_ITEMS + 1)},
        },
    )
    assert r.status_code == 400


def test_create_rejects_long_metadata_string(db, cross_space_pair):
    from app.source_pointers.validation import MAX_METADATA_STRING_LENGTH

    a, b, _c, ua, _ub = _three_space_setup(db, cross_space_pair)
    _add_member(db, space_id=b, user_id=ua.id)
    db.commit()
    r = cross_space_pair["client_a"].post(
        "/api/v1/source-pointers",
        params=_params(a, ua.id),
        json={
            "owner_space_id": a,
            "source_space_id": b,
            "source_object_type": "memory",
            "source_object_id": _new_id(),
            "access_mode": "read",
            "metadata_json": {"note": "x" * (MAX_METADATA_STRING_LENGTH + 1)},
        },
    )
    assert r.status_code == 400


def test_responses_never_include_source_content_fields(db, cross_space_pair):
    a, b, _c, ua, _ub = _three_space_setup(db, cross_space_pair)
    _add_member(db, space_id=b, user_id=ua.id)
    mem = factories.create_test_memory_entry(
        db,
        space_id=b,
        content="SECRET_MEMORY_BODY",
        commit=False,
    )
    mem.visibility = "space_shared"
    db.commit()
    create_r = cross_space_pair["client_a"].post(
        "/api/v1/source-pointers",
        params=_params(a, ua.id),
        json={
            "owner_space_id": a,
            "source_space_id": b,
            "source_object_type": "memory",
            "source_object_id": mem.id,
            "access_mode": "read",
        },
    )
    assert create_r.status_code == 201
    assert "SECRET_MEMORY_BODY" not in create_r.text
    assert not (_FORBIDDEN_FIELDS & set(create_r.json().keys()))
    ptr_id = create_r.json()["id"]
    detail = cross_space_pair["client_a"].get(
        f"/api/v1/source-pointers/{ptr_id}",
        params=_params(a, ua.id),
    )
    assert detail.status_code == 200
    assert "SECRET_MEMORY_BODY" not in detail.text
    listed = cross_space_pair["client_a"].get(
        "/api/v1/source-pointers",
        params=_params(a, ua.id),
    )
    assert listed.status_code == 200
    assert "SECRET_MEMORY_BODY" not in listed.text
