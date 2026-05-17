"""Unit tests for SourcePointer metadata service."""

from __future__ import annotations

import pytest
from ulid import ULID

from app.models import SourcePointer
from app.source_pointers.validation import (
    InvalidSourcePointerMetadataError,
    MAX_METADATA_DEPTH,
    MAX_METADATA_KEY_LENGTH,
    MAX_METADATA_STRING_LENGTH,
    MAX_METADATA_TOTAL_ITEMS,
)
from app.source_pointers.service import (
    InvalidSourcePointerAccessModeError,
    InvalidSourcePointerExpiresAtError,
    create_source_pointer,
    delete_source_pointer,
    get_source_pointer,
    list_source_pointers_for_owner_space,
    list_source_pointers_for_user,
)
from tests.support import factories


def _new_id() -> str:
    return str(ULID())


def _two_spaces(db):
    owner_id = _new_id()
    source_id = _new_id()
    factories.create_test_space(db, space_id=owner_id, name="Owner", space_type="personal")
    factories.create_test_space(db, space_id=source_id, name="Source", space_type="team")
    user = factories.create_test_user(db, space_id=owner_id, display_name="Owner User")
    db.commit()
    return owner_id, source_id, user


def _deep_metadata() -> dict:
    nested: dict = {}
    cursor = nested
    for _ in range(MAX_METADATA_DEPTH + 2):
        cursor["n"] = {}
        cursor = cursor["n"]
    return nested


def test_create_valid_pointer_succeeds(db):
    owner_id, source_id, user = _two_spaces(db)
    ptr = create_source_pointer(
        db,
        owner_space_id=owner_id,
        source_space_id=source_id,
        source_object_type="memory",
        source_object_id=_new_id(),
        access_mode="read",
        granted_by_user_id=user.id,
        metadata_json={"note": "provenance only"},
    )
    db.commit()
    assert ptr.id
    assert ptr.owner_space_id == owner_id
    assert ptr.access_mode == "read"
    assert ptr.metadata_json == {"note": "provenance only"}


@pytest.mark.parametrize("mode", ["subscribe", "federated"])
def test_create_valid_subscribe_and_federated_modes(db, mode):
    owner_id, source_id, _user = _two_spaces(db)
    ptr = create_source_pointer(
        db,
        owner_space_id=owner_id,
        source_space_id=source_id,
        source_object_type="memory",
        source_object_id=_new_id(),
        access_mode=mode,
    )
    db.commit()
    assert ptr.access_mode == mode


def test_invalid_access_mode_rejected(db):
    owner_id, source_id, _user = _two_spaces(db)
    with pytest.raises(InvalidSourcePointerAccessModeError, match="invalid access_mode"):
        create_source_pointer(
            db,
            owner_space_id=owner_id,
            source_space_id=source_id,
            source_object_type="memory",
            source_object_id=_new_id(),
            access_mode="full_read_grant",
        )


def test_list_by_owner_space_returns_only_owner_pointers(db):
    owner_a, source_a, _ = _two_spaces(db)
    owner_b = _new_id()
    factories.create_test_space(db, space_id=owner_b, name="Other Owner", space_type="personal")
    db.commit()
    mem_id = _new_id()
    create_source_pointer(
        db,
        owner_space_id=owner_a,
        source_space_id=source_a,
        source_object_type="memory",
        source_object_id=mem_id,
        access_mode="read",
    )
    create_source_pointer(
        db,
        owner_space_id=owner_b,
        source_space_id=source_a,
        source_object_type="memory",
        source_object_id=_new_id(),
        access_mode="read",
    )
    db.commit()
    rows = list_source_pointers_for_owner_space(db, owner_space_id=owner_a)
    assert len(rows) == 1
    assert rows[0].source_object_id == mem_id


def test_get_wrong_owner_space_returns_none(db):
    owner_id, source_id, _user = _two_spaces(db)
    ptr = create_source_pointer(
        db,
        owner_space_id=owner_id,
        source_space_id=source_id,
        source_object_type="memory",
        source_object_id=_new_id(),
        access_mode="read",
    )
    db.commit()
    other_owner = _new_id()
    assert get_source_pointer(db, pointer_id=ptr.id, owner_space_id=other_owner) is None
    assert get_source_pointer(db, pointer_id=ptr.id, owner_space_id=owner_id) is not None


def test_unsafe_metadata_json_rejected_at_service(db):
    owner_id, source_id, _user = _two_spaces(db)
    with pytest.raises(InvalidSourcePointerMetadataError, match="content keys"):
        create_source_pointer(
            db,
            owner_space_id=owner_id,
            source_space_id=source_id,
            source_object_type="memory",
            source_object_id=_new_id(),
            access_mode="read",
            metadata_json={"body": "hidden"},
        )


@pytest.mark.parametrize(
    "metadata_json",
    [
        {"safe": {"content": "nested"}},
        {"items": [{"payload": "in list"}]},
        {"outer": {"inner": {"memory_text": "deep"}}},
        {"CONTENT": "case-insensitive key"},
    ],
)
def test_unsafe_metadata_json_rejected_recursively(db, metadata_json):
    owner_id, source_id, _user = _two_spaces(db)
    with pytest.raises(InvalidSourcePointerMetadataError, match="content keys"):
        create_source_pointer(
            db,
            owner_space_id=owner_id,
            source_space_id=source_id,
            source_object_type="memory",
            source_object_id=_new_id(),
            access_mode="read",
            metadata_json=metadata_json,
        )


@pytest.mark.parametrize(
    "metadata_json,match",
    [
        ({f"k{i:04d}": "x" * 100 for i in range(200)}, "bytes"),
        (_deep_metadata(), "depth"),
        ({f"k{i}": i for i in range(MAX_METADATA_TOTAL_ITEMS + 1)}, "total items"),
        ({"k" * (MAX_METADATA_KEY_LENGTH + 1): "ok"}, "key exceeds"),
        ({"note": "v" * (MAX_METADATA_STRING_LENGTH + 1)}, "string exceeds"),
    ],
)
def test_metadata_json_bounds_rejected(db, metadata_json, match):
    owner_id, source_id, _user = _two_spaces(db)
    with pytest.raises(InvalidSourcePointerMetadataError, match=match):
        create_source_pointer(
            db,
            owner_space_id=owner_id,
            source_space_id=source_id,
            source_object_type="memory",
            source_object_id=_new_id(),
            access_mode="read",
            metadata_json=metadata_json,
        )


@pytest.mark.parametrize(
    "metadata_json,match",
    [
        ({"items": (1, 2)}, "tuple"),
        ({"items": {1, 2}}, "set"),
        ({"raw": b"abc"}, "bytes"),
        ({"obj": object()}, "unsupported type"),
        ({1: "non-string key"}, "keys must be strings"),
    ],
)
def test_metadata_json_rejects_non_json_types_at_service(db, metadata_json, match):
    owner_id, source_id, _user = _two_spaces(db)
    with pytest.raises(InvalidSourcePointerMetadataError, match=match):
        create_source_pointer(
            db,
            owner_space_id=owner_id,
            source_space_id=source_id,
            source_object_type="memory",
            source_object_id=_new_id(),
            access_mode="read",
            metadata_json=metadata_json,
        )


def test_metadata_json_top_level_list_rejected(db):
    owner_id, source_id, _user = _two_spaces(db)
    with pytest.raises(InvalidSourcePointerMetadataError, match="JSON object"):
        create_source_pointer(
            db,
            owner_space_id=owner_id,
            source_space_id=source_id,
            source_object_type="memory",
            source_object_id=_new_id(),
            access_mode="read",
            metadata_json=["not", "a", "dict"],  # type: ignore[arg-type]
        )


def test_metadata_json_exceeds_total_items_via_nested_structure_rejected(db):
    owner_id, source_id, _user = _two_spaces(db)
    # 130 outer keys × 2 inner keys = 260 items > 256 cap.
    metadata = {f"k{i}": {"a": 1, "b": 2} for i in range(130)}
    with pytest.raises(InvalidSourcePointerMetadataError, match="total items"):
        create_source_pointer(
            db,
            owner_space_id=owner_id,
            source_space_id=source_id,
            source_object_type="memory",
            source_object_id=_new_id(),
            access_mode="read",
            metadata_json=metadata,
        )


def test_safe_nested_metadata_json_accepted(db):
    owner_id, source_id, user = _two_spaces(db)
    ptr = create_source_pointer(
        db,
        owner_space_id=owner_id,
        source_space_id=source_id,
        source_object_type="memory",
        source_object_id=_new_id(),
        access_mode="read",
        metadata_json={
            "note": "provenance",
            "tags": ["alpha", "beta"],
            "refs": {"run_id": _new_id(), "label": "ok"},
            "hint": "content is only a word in a value",
        },
        granted_by_user_id=user.id,
    )
    db.commit()
    assert ptr.metadata_json["refs"]["label"] == "ok"


def test_expires_at_in_past_rejected(db):
    from datetime import UTC, datetime, timedelta

    owner_id, source_id, _user = _two_spaces(db)
    with pytest.raises(InvalidSourcePointerExpiresAtError):
        create_source_pointer(
            db,
            owner_space_id=owner_id,
            source_space_id=source_id,
            source_object_type="memory",
            source_object_id=_new_id(),
            access_mode="read",
            expires_at=datetime.now(UTC) - timedelta(hours=1),
        )


def test_list_for_user_scopes_to_member_owner_spaces(db):
    owner_a, source_a, user_a = _two_spaces(db)
    owner_b = _new_id()
    factories.create_test_space(db, space_id=owner_b, name="Other Owner", space_type="personal")
    mem_id = _new_id()
    create_source_pointer(
        db,
        owner_space_id=owner_a,
        source_space_id=source_a,
        source_object_type="memory",
        source_object_id=mem_id,
        access_mode="read",
    )
    create_source_pointer(
        db,
        owner_space_id=owner_b,
        source_space_id=source_a,
        source_object_type="memory",
        source_object_id=_new_id(),
        access_mode="read",
    )
    db.commit()
    rows = list_source_pointers_for_user(db, user_id=user_a.id)
    assert len(rows) == 1
    assert rows[0].source_object_id == mem_id


def test_delete_removes_pointer_only(db):
    owner_id, source_id, _user = _two_spaces(db)
    ptr = create_source_pointer(
        db,
        owner_space_id=owner_id,
        source_space_id=source_id,
        source_object_type="memory",
        source_object_id=_new_id(),
        access_mode="read",
    )
    db.commit()
    assert delete_source_pointer(db, pointer_id=ptr.id) is True
    db.commit()
    assert get_source_pointer(db, pointer_id=ptr.id, owner_space_id=owner_id) is None


def test_pointer_model_has_no_raw_content_columns():
    forbidden = {
        "content",
        "body",
        "summary",
        "payload",
        "raw_content",
        "source_snapshot",
        "public_url",
        "copied_text",
    }
    col_names = {c.key for c in SourcePointer.__table__.columns}
    assert not (forbidden & col_names), f"SourcePointer must not store content: {forbidden & col_names}"
