"""Security invariants: SourcePointer is metadata only and does not grant memory reads."""

from __future__ import annotations
import uuid


from app.memory.retriever import MemoryRetriever
from app.models import MemoryEntry, SourcePointer, SpaceMembership
from app.policy.domains import MEMORY_CROSS_SPACE_READ, RUN_USER_PRIVATE_SCOPE
from app.source_pointers.service import create_source_pointer
from tests.support import factories


def _params(space_id: str, user_id: str) -> dict[str, str]:
    del user_id
    return {"space_id": space_id}


def _add_member(db, *, space_id: str, user_id: str, role: str = "member") -> None:
    db.add(
        SpaceMembership(
            id=str(uuid.uuid4()),
            space_id=space_id,
            user_id=user_id,
            role=role,
            status="active",
        )
    )


def _new_id() -> str:
    return str(uuid.uuid4())


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


def _personal_space(db):
    space_id = _new_id()
    factories.create_test_space(db, space_id=space_id, name="Personal", space_type="personal")
    user = factories.create_test_user(db, space_id=space_id, display_name="Personal User")
    db.commit()
    return space_id, user


def _team_space(db):
    space_id = _new_id()
    factories.create_test_space(db, space_id=space_id, name="Team", space_type="team")
    user = factories.create_test_user(db, space_id=space_id, display_name="Team User")
    db.commit()
    return space_id, user


def _memory(
    db,
    *,
    space_id: str,
    content: str,
    visibility: str = "space_shared",
    owner_user_id: str | None = None,
) -> MemoryEntry:
    m = MemoryEntry(
        id=_new_id(),
        space_id=space_id,
        scope_type="user" if visibility == "private" else "space",
        memory_type="semantic",
        content=content,
        status="active",
        visibility=visibility,
        owner_user_id=owner_user_id,
        subject_user_id=owner_user_id,
    )
    db.add(m)
    db.flush()
    return m


def test_pointer_personal_to_team_does_not_retrieve_team_memory_in_personal_context(db):
    personal_id, user = _personal_space(db)
    team_id, _team_user = _team_space(db)
    team_mem = _memory(db, space_id=team_id, content="team-secret-shared")
    create_source_pointer(
        db,
        owner_space_id=personal_id,
        source_space_id=team_id,
        source_object_type="memory",
        source_object_id=team_mem.id,
        access_mode="read",
        granted_by_user_id=user.id,
    )
    db.commit()

    result = MemoryRetriever(db).retrieve(space_id=personal_id, user_id=user.id)
    assert team_mem.id not in {m.id for m in result.memories}


def test_pointer_team_to_personal_private_does_not_leak_personal_memory(db):
    personal_id, user = _personal_space(db)
    team_id, team_user = _team_space(db)
    personal_private = _memory(
        db,
        space_id=personal_id,
        content="personal-private-secret",
        visibility="private",
        owner_user_id=user.id,
    )
    create_source_pointer(
        db,
        owner_space_id=team_id,
        source_space_id=personal_id,
        source_object_type="memory",
        source_object_id=personal_private.id,
        access_mode="read",
        granted_by_user_id=team_user.id,
    )
    _policy_row(db, space_id=team_id, domain=RUN_USER_PRIVATE_SCOPE, effect="allow")
    db.commit()

    result = MemoryRetriever(db).retrieve(space_id=team_id, user_id=team_user.id)
    assert personal_private.id not in {m.id for m in result.memories}


def test_allow_looking_cross_space_policy_with_pointer_still_denies_retrieval(db):
    personal_id, user = _personal_space(db)
    team_id, _ = _team_space(db)
    team_mem = _memory(db, space_id=team_id, content="team-with-allow-policy")
    create_source_pointer(
        db,
        owner_space_id=personal_id,
        source_space_id=team_id,
        source_object_type="memory",
        source_object_id=team_mem.id,
        access_mode="read",
    )
    _policy_row(db, space_id=personal_id, domain=MEMORY_CROSS_SPACE_READ, effect="allow")
    _policy_row(db, space_id=personal_id, domain=MEMORY_CROSS_SPACE_READ, effect="allow_with_log")
    db.commit()

    result = MemoryRetriever(db).retrieve(space_id=personal_id, user_id=user.id)
    assert team_mem.id not in {m.id for m in result.memories}


def test_api_created_pointer_does_not_grant_memory_read(db, cross_space_pair):
    owner_id = cross_space_pair["space_a_id"]
    source_id = cross_space_pair["space_b_id"]
    user = cross_space_pair["user_a"]
    team_mem = factories.create_test_memory_entry(
        db,
        space_id=source_id,
        content="api-pointer-no-read",
        commit=False,
    )
    team_mem.visibility = "space_shared"
    _add_member(db, space_id=source_id, user_id=user.id)
    db.commit()
    r = cross_space_pair["client_a"].post(
        "/api/v1/source-pointers",
        params=_params(owner_id, user.id),
        json={
            "owner_space_id": owner_id,
            "source_space_id": source_id,
            "source_object_type": "memory",
            "source_object_id": team_mem.id,
            "access_mode": "read",
        },
    )
    assert r.status_code == 201
    assert "api-pointer-no-read" not in r.text
    db.commit()
    result = MemoryRetriever(db).retrieve(space_id=owner_id, user_id=user.id)
    assert team_mem.id not in {m.id for m in result.memories}


def test_api_pointer_create_requires_source_space_membership(db, cross_space_pair):
    owner_id = cross_space_pair["space_a_id"]
    source_id = cross_space_pair["space_b_id"]
    user = cross_space_pair["user_a"]
    team_mem = factories.create_test_memory_entry(
        db,
        space_id=source_id,
        content="hidden-from-nonmember",
        commit=True,
    )
    team_mem.visibility = "space_shared"
    db.commit()
    r = cross_space_pair["client_a"].post(
        "/api/v1/source-pointers",
        params=_params(owner_id, user.id),
        json={
            "owner_space_id": owner_id,
            "source_space_id": source_id,
            "source_object_type": "memory",
            "source_object_id": team_mem.id,
            "access_mode": "read",
        },
    )
    assert r.status_code == 403


def test_api_unsafe_metadata_json_rejected(db, cross_space_pair):
    owner_id = cross_space_pair["space_a_id"]
    source_id = cross_space_pair["space_b_id"]
    user = cross_space_pair["user_a"]
    _add_member(db, space_id=source_id, user_id=user.id)
    db.commit()
    r = cross_space_pair["client_a"].post(
        "/api/v1/source-pointers",
        params=_params(owner_id, user.id),
        json={
            "owner_space_id": owner_id,
            "source_space_id": source_id,
            "source_object_type": "memory",
            "source_object_id": _new_id(),
            "access_mode": "read",
            "metadata_json": {"memory_text": "must not store"},
        },
    )
    assert r.status_code == 400


def test_metadata_json_large_blob_under_innocent_key_rejected(db, cross_space_pair):
    owner_id = cross_space_pair["space_a_id"]
    source_id = cross_space_pair["space_b_id"]
    user = cross_space_pair["user_a"]
    _add_member(db, space_id=source_id, user_id=user.id)
    db.commit()
    object_id = _new_id()
    metadata = {f"label_{i:04d}": "x" * 100 for i in range(200)}
    r = cross_space_pair["client_a"].post(
        "/api/v1/source-pointers",
        params=_params(owner_id, user.id),
        json={
            "owner_space_id": owner_id,
            "source_space_id": source_id,
            "source_object_type": "memory",
            "source_object_id": object_id,
            "access_mode": "read",
            "metadata_json": metadata,
        },
    )
    assert r.status_code == 400
    assert (
        db.query(SourcePointer)
        .filter(SourcePointer.source_object_id == object_id)
        .first()
        is None
    )


def test_api_nested_metadata_cannot_hide_raw_content(db, cross_space_pair):
    owner_id = cross_space_pair["space_a_id"]
    source_id = cross_space_pair["space_b_id"]
    user = cross_space_pair["user_a"]
    _add_member(db, space_id=source_id, user_id=user.id)
    db.commit()
    object_id = _new_id()
    r = cross_space_pair["client_a"].post(
        "/api/v1/source-pointers",
        params=_params(owner_id, user.id),
        json={
            "owner_space_id": owner_id,
            "source_space_id": source_id,
            "source_object_type": "memory",
            "source_object_id": object_id,
            "access_mode": "read",
            "metadata_json": {"wrapper": [{"body": "hidden copy"}]},
        },
    )
    assert r.status_code == 400
    assert (
        db.query(SourcePointer)
        .filter(SourcePointer.source_object_id == object_id)
        .first()
        is None
    )
