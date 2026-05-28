from __future__ import annotations

from sqlalchemy import func

from app.models import KnowledgeItem, KnowledgeRelation, MemoryEntry, Proposal
from tests.support import factories


def _params(space_id: str, user_id: str) -> dict[str, str]:
    del user_id
    return {"space_id": space_id}


def _create_payload(**overrides):
    payload = {
        "item_type": "knowledge",
        "title": "HTTP Knowledge",
        "content": "approved only after proposal accept",
        "content_format": "markdown",
        "visibility": "space_shared",
        "tags": ["alpha"],
    }
    payload.update(overrides)
    return payload


def _knowledge_update_payload(item_id: str, *, title: str = "Updated", content: str = "updated") -> dict:
    return {
        "operation": "update",
        "target_item_id": item_id,
        "title": title,
        "content": content,
        "content_format": "markdown",
        "tags": [],
        "verification_status": "unverified",
        "reflection_status": "unreviewed",
    }


def test_unauthenticated_knowledge_endpoint_returns_401(api_client):
    r = api_client.get("/api/v1/knowledge/items")
    assert r.status_code == 401


def test_legacy_route_is_not_registered(api_client):
    legacy = "".join(("/api/v1/wi", "ki/items"))
    r = api_client.get(legacy)
    assert r.status_code == 404


def test_list_is_space_scoped_and_cross_space_item_read_returns_404(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    b = cross_space_pair["space_b_id"]
    ua = cross_space_pair["user_a"]
    ub = cross_space_pair["user_b"]
    item_a = factories.create_test_knowledge_item(db, space_id=a, title="A item", commit=True)
    factories.create_test_knowledge_item(db, space_id=b, title="B item", commit=True)

    list_a = cross_space_pair["client_a"].get("/api/v1/knowledge/items", params=_params(a, ua.id))
    assert list_a.status_code == 200
    titles = [row["title"] for row in list_a.json()["items"]]
    assert titles == ["A item"]

    read_cross = cross_space_pair["client_b"].get(
        f"/api/v1/knowledge/items/{item_a.id}",
        params=_params(b, ub.id),
    )
    assert read_cross.status_code == 404


def test_create_proposal_creates_proposal_only_until_accept(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    before_items = db.query(func.count(KnowledgeItem.id)).filter(KnowledgeItem.space_id == a).scalar()
    r = cross_space_pair["client_a"].post(
        "/api/v1/knowledge/items/proposals",
        params=_params(a, ua.id),
        json=_create_payload(),
    )
    assert r.status_code == 202
    body = r.json()
    assert body["proposal_type"] == "knowledge_create"
    db.expire_all()
    prop = db.get(Proposal, body["id"])
    assert prop is not None and prop.status == "pending"
    assert prop.payload_json["owner_user_id"] == ua.id
    after_items = db.query(func.count(KnowledgeItem.id)).filter(KnowledgeItem.space_id == a).scalar()
    assert after_items == before_items


def test_accept_knowledge_create_creates_active_item(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    r = cross_space_pair["client_a"].post(
        "/api/v1/knowledge/items/proposals",
        params=_params(a, ua.id),
        json=_create_payload(title="Created Knowledge", content="v1"),
    )
    proposal_id = r.json()["id"]

    accepted = cross_space_pair["client_a"].post(f"/api/v1/proposals/{proposal_id}/accept", params=_params(a, ua.id))
    assert accepted.status_code == 200
    accepted_body = accepted.json()
    assert accepted_body["result_type"] == "knowledge_item"
    item_id = accepted_body["result"]["knowledge_item"]["id"]

    db.expire_all()
    item = db.get(KnowledgeItem, item_id)
    assert item is not None
    assert item.status == "active"
    assert item.title == "Created Knowledge"
    assert item.owner_user_id == ua.id
    assert item.created_from_proposal_id == proposal_id
    assert item.root_item_id == item.id


def test_private_knowledge_is_owner_visible_and_hidden_from_same_space_user(db, same_space_pair):
    space = same_space_pair["space_id"]
    ua = same_space_pair["user_a"]
    ub = same_space_pair["user_b"]
    r = same_space_pair["client_a"].post(
        "/api/v1/knowledge/items/proposals",
        params=_params(space, ua.id),
        json=_create_payload(title="Private Knowledge", content="private body", visibility="private"),
    )
    assert r.status_code == 202
    db.expire_all()
    assert db.query(func.count(KnowledgeItem.id)).filter(KnowledgeItem.space_id == space).scalar() == 0

    accepted = same_space_pair["client_a"].post(f"/api/v1/proposals/{r.json()['id']}/accept", params=_params(space, ua.id))
    assert accepted.status_code == 200
    item_id = accepted.json()["result"]["knowledge_item"]["id"]
    db.expire_all()
    item = db.get(KnowledgeItem, item_id)
    assert item is not None
    assert item.visibility == "private"
    assert item.owner_user_id == ua.id

    owner_get = same_space_pair["client_a"].get(f"/api/v1/knowledge/items/{item_id}", params=_params(space, ua.id))
    assert owner_get.status_code == 200
    assert owner_get.json()["content"] == "private body"

    other_list = same_space_pair["client_b"].get("/api/v1/knowledge/items", params=_params(space, ub.id))
    assert other_list.status_code == 200
    assert [row["id"] for row in other_list.json()["items"]] == []

    other_get = same_space_pair["client_b"].get(f"/api/v1/knowledge/items/{item_id}", params=_params(space, ub.id))
    assert other_get.status_code == 404


def test_knowledge_create_rejects_payload_owner_different_from_creator(db, same_space_pair):
    space = same_space_pair["space_id"]
    ua = same_space_pair["user_a"]
    ub = same_space_pair["user_b"]
    prop = factories.create_test_proposal(
        db,
        space_id=space,
        proposal_type="knowledge_create",
        created_by_user_id=ua.id,
        payload_json={
            "operation": "create",
            "item_type": "knowledge",
            "title": "Bad owner",
            "content": "body",
            "content_format": "markdown",
            "visibility": "private",
            "owner_user_id": ub.id,
            "verification_status": "unverified",
            "reflection_status": "unreviewed",
        },
        commit=True,
    )

    accepted = same_space_pair["client_a"].post(f"/api/v1/proposals/{prop.id}/accept", params=_params(space, ua.id))
    assert accepted.status_code == 422
    assert db.query(func.count(KnowledgeItem.id)).filter(KnowledgeItem.space_id == space).scalar() == 0


def test_private_knowledge_cannot_be_updated_or_archived_by_same_space_non_owner(db, same_space_pair):
    space = same_space_pair["space_id"]
    ua = same_space_pair["user_a"]
    ub = same_space_pair["user_b"]
    item = factories.create_test_knowledge_item(
        db,
        space_id=space,
        title="Owner only",
        visibility="restricted",
        owner_user_id=ua.id,
        created_by_user_id=ua.id,
        commit=True,
    )

    update = same_space_pair["client_b"].patch(
        f"/api/v1/knowledge/items/{item.id}/proposals",
        params=_params(space, ub.id),
        json={"title": "Blocked", "content": "blocked", "content_format": "markdown"},
    )
    assert update.status_code == 404

    archive = same_space_pair["client_b"].delete(f"/api/v1/knowledge/items/{item.id}", params=_params(space, ub.id))
    assert archive.status_code == 404


def test_same_space_user_can_propose_update_for_shared_item(db, same_space_pair):
    space = same_space_pair["space_id"]
    ua = same_space_pair["user_a"]
    ub = same_space_pair["user_b"]
    item = factories.create_test_knowledge_item(
        db,
        space_id=space,
        title="Shared",
        visibility="space_shared",
        owner_user_id=ua.id,
        created_by_user_id=ua.id,
        commit=True,
    )

    update = same_space_pair["client_b"].patch(
        f"/api/v1/knowledge/items/{item.id}/proposals",
        params=_params(space, ub.id),
        json={"title": "Shared updated", "content": "new", "content_format": "markdown"},
    )
    assert update.status_code == 202
    assert update.json()["proposal_type"] == "knowledge_update"


def test_list_returns_summary_payload_and_detail_returns_full_content(db, same_space_pair):
    space = same_space_pair["space_id"]
    ua = same_space_pair["user_a"]
    long_content = "x" * 400
    item = factories.create_test_knowledge_item(
        db,
        space_id=space,
        title="Long item",
        content=long_content,
        owner_user_id=ua.id,
        created_by_user_id=ua.id,
        commit=True,
    )

    listed = same_space_pair["client_a"].get("/api/v1/knowledge/items", params=_params(space, ua.id))
    assert listed.status_code == 200
    row = listed.json()["items"][0]
    assert "content" not in row
    assert row["content_preview"] != long_content
    assert len(row["content_preview"]) <= 240

    detail = same_space_pair["client_a"].get(f"/api/v1/knowledge/items/{item.id}", params=_params(space, ua.id))
    assert detail.status_code == 200
    assert detail.json()["content"] == long_content


def test_accept_knowledge_update_versions_without_overwriting_old_item(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    item = factories.create_test_knowledge_item(db, space_id=a, title="Original", content="old", commit=True)

    r = cross_space_pair["client_a"].patch(
        f"/api/v1/knowledge/items/{item.id}/proposals",
        params=_params(a, ua.id),
        json={
            "title": "Original updated",
            "content": "new",
            "content_format": "markdown",
            "tags": ["updated"],
        },
    )
    assert r.status_code == 202
    accepted = cross_space_pair["client_a"].post(f"/api/v1/proposals/{r.json()['id']}/accept", params=_params(a, ua.id))
    assert accepted.status_code == 200
    new_item_id = accepted.json()["result"]["knowledge_item"]["id"]

    db.expire_all()
    old = db.get(KnowledgeItem, item.id)
    new = db.get(KnowledgeItem, new_item_id)
    assert old is not None and old.status == "superseded"
    assert old.content == "old"
    assert new is not None
    assert new.content == "new"
    assert new.version == old.version + 1
    assert new.root_item_id == old.root_item_id
    assert new.supersedes_item_id == old.id


def test_knowledge_update_preserves_root_lineage_over_multiple_versions(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    item = factories.create_test_knowledge_item(db, space_id=a, title="Original", content="v1", commit=True)

    first = cross_space_pair["client_a"].patch(
        f"/api/v1/knowledge/items/{item.id}/proposals",
        params=_params(a, ua.id),
        json={"title": "V2", "content": "v2", "content_format": "markdown"},
    )
    assert first.status_code == 202
    first_accept = cross_space_pair["client_a"].post(
        f"/api/v1/proposals/{first.json()['id']}/accept",
        params=_params(a, ua.id),
    )
    assert first_accept.status_code == 200
    v2_id = first_accept.json()["result"]["knowledge_item"]["id"]

    second = cross_space_pair["client_a"].patch(
        f"/api/v1/knowledge/items/{v2_id}/proposals",
        params=_params(a, ua.id),
        json={"title": "V3", "content": "v3", "content_format": "markdown"},
    )
    assert second.status_code == 202
    second_accept = cross_space_pair["client_a"].post(
        f"/api/v1/proposals/{second.json()['id']}/accept",
        params=_params(a, ua.id),
    )
    assert second_accept.status_code == 200
    v3_id = second_accept.json()["result"]["knowledge_item"]["id"]

    db.expire_all()
    v1 = db.get(KnowledgeItem, item.id)
    v2 = db.get(KnowledgeItem, v2_id)
    v3 = db.get(KnowledgeItem, v3_id)
    assert v1 is not None and v2 is not None and v3 is not None
    assert v1.root_item_id == item.id
    assert v2.root_item_id == item.id
    assert v3.root_item_id == item.id
    assert v2.status == "superseded"
    assert v3.version == 3


def test_update_and_archive_reject_superseded_or_archived_targets(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    superseded = factories.create_test_knowledge_item(db, space_id=a, status="superseded", commit=True)
    archived = factories.create_test_knowledge_item(db, space_id=a, status="archived", commit=True)

    update_superseded = cross_space_pair["client_a"].patch(
        f"/api/v1/knowledge/items/{superseded.id}/proposals",
        params=_params(a, ua.id),
        json={"title": "No", "content": "no", "content_format": "markdown"},
    )
    assert update_superseded.status_code == 422

    archive_superseded = cross_space_pair["client_a"].delete(
        f"/api/v1/knowledge/items/{superseded.id}",
        params=_params(a, ua.id),
    )
    assert archive_superseded.status_code == 422

    update_archived = cross_space_pair["client_a"].patch(
        f"/api/v1/knowledge/items/{archived.id}/proposals",
        params=_params(a, ua.id),
        json={"title": "No", "content": "no", "content_format": "markdown"},
    )
    assert update_archived.status_code == 422


def test_apply_update_rejects_malformed_private_target_proposal_from_non_owner(db, same_space_pair):
    space = same_space_pair["space_id"]
    ua = same_space_pair["user_a"]
    ub = same_space_pair["user_b"]
    item = factories.create_test_knowledge_item(
        db,
        space_id=space,
        title="Private v1",
        content="private original",
        visibility="private",
        owner_user_id=ua.id,
        created_by_user_id=ua.id,
        commit=False,
    )
    prop = factories.create_test_proposal(
        db,
        space_id=space,
        proposal_type="knowledge_update",
        created_by_user_id=ub.id,
        payload_json=_knowledge_update_payload(item.id, title="Bad update", content="leak"),
        commit=True,
    )

    accepted = same_space_pair["client_b"].post(f"/api/v1/proposals/{prop.id}/accept", params=_params(space, ub.id))
    assert accepted.status_code == 422

    db.expire_all()
    unchanged = db.get(KnowledgeItem, item.id)
    assert unchanged is not None
    assert unchanged.status == "active"
    assert unchanged.content == "private original"
    assert db.query(func.count(KnowledgeItem.id)).filter(KnowledgeItem.space_id == space).scalar() == 1


def test_apply_update_allows_owner_private_target_and_same_space_shared_collaboration(db, same_space_pair):
    space = same_space_pair["space_id"]
    ua = same_space_pair["user_a"]
    ub = same_space_pair["user_b"]
    private = factories.create_test_knowledge_item(
        db,
        space_id=space,
        title="Private v1",
        content="private original",
        visibility="restricted",
        owner_user_id=ua.id,
        created_by_user_id=ua.id,
        commit=False,
    )
    shared = factories.create_test_knowledge_item(
        db,
        space_id=space,
        title="Shared v1",
        content="shared original",
        visibility="space_shared",
        owner_user_id=ua.id,
        created_by_user_id=ua.id,
        commit=False,
    )
    owner_prop = factories.create_test_proposal(
        db,
        space_id=space,
        proposal_type="knowledge_update",
        created_by_user_id=ua.id,
        payload_json=_knowledge_update_payload(private.id, title="Private v2", content="private updated"),
        commit=False,
    )
    shared_prop = factories.create_test_proposal(
        db,
        space_id=space,
        proposal_type="knowledge_update",
        created_by_user_id=ub.id,
        payload_json=_knowledge_update_payload(shared.id, title="Shared v2", content="shared updated"),
        commit=True,
    )

    owner_accept = same_space_pair["client_a"].post(
        f"/api/v1/proposals/{owner_prop.id}/accept",
        params=_params(space, ua.id),
    )
    assert owner_accept.status_code == 200
    shared_accept = same_space_pair["client_b"].post(
        f"/api/v1/proposals/{shared_prop.id}/accept",
        params=_params(space, ub.id),
    )
    assert shared_accept.status_code == 200

    db.expire_all()
    assert db.get(KnowledgeItem, private.id).status == "superseded"  # type: ignore[union-attr]
    assert db.get(KnowledgeItem, shared.id).status == "superseded"  # type: ignore[union-attr]
    assert owner_accept.json()["result"]["knowledge_item"]["content"] == "private updated"
    assert shared_accept.json()["result"]["knowledge_item"]["content"] == "shared updated"


def test_accept_knowledge_archive_archives_item(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    item = factories.create_test_knowledge_item(db, space_id=a, commit=True)

    r = cross_space_pair["client_a"].delete(f"/api/v1/knowledge/items/{item.id}", params=_params(a, ua.id))
    assert r.status_code == 202
    accepted = cross_space_pair["client_a"].post(f"/api/v1/proposals/{r.json()['id']}/accept", params=_params(a, ua.id))
    assert accepted.status_code == 200

    db.expire_all()
    archived = db.get(KnowledgeItem, item.id)
    assert archived is not None and archived.status == "archived"
    assert archived.archived_at is not None


def test_apply_archive_rejects_malformed_private_target_proposal_from_non_owner(db, same_space_pair):
    space = same_space_pair["space_id"]
    ua = same_space_pair["user_a"]
    ub = same_space_pair["user_b"]
    item = factories.create_test_knowledge_item(
        db,
        space_id=space,
        title="Private archive target",
        visibility="private",
        owner_user_id=ua.id,
        created_by_user_id=ua.id,
        commit=False,
    )
    prop = factories.create_test_proposal(
        db,
        space_id=space,
        proposal_type="knowledge_archive",
        created_by_user_id=ub.id,
        payload_json={"operation": "archive", "target_item_id": item.id},
        commit=True,
    )

    accepted = same_space_pair["client_b"].post(f"/api/v1/proposals/{prop.id}/accept", params=_params(space, ub.id))
    assert accepted.status_code == 422

    db.expire_all()
    unchanged = db.get(KnowledgeItem, item.id)
    assert unchanged is not None
    assert unchanged.status == "active"
    assert unchanged.archived_at is None


def test_apply_archive_allows_owner_private_target(db, same_space_pair):
    space = same_space_pair["space_id"]
    ua = same_space_pair["user_a"]
    item = factories.create_test_knowledge_item(
        db,
        space_id=space,
        title="Owner archive target",
        visibility="restricted",
        owner_user_id=ua.id,
        created_by_user_id=ua.id,
        commit=False,
    )
    prop = factories.create_test_proposal(
        db,
        space_id=space,
        proposal_type="knowledge_archive",
        created_by_user_id=ua.id,
        payload_json={"operation": "archive", "target_item_id": item.id},
        commit=True,
    )

    accepted = same_space_pair["client_a"].post(f"/api/v1/proposals/{prop.id}/accept", params=_params(space, ua.id))
    assert accepted.status_code == 200

    db.expire_all()
    archived = db.get(KnowledgeItem, item.id)
    assert archived is not None
    assert archived.status == "archived"
    assert archived.archived_at is not None


def test_relation_create_and_delete_are_proposal_applied(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    left = factories.create_test_knowledge_item(db, space_id=a, title="Left", commit=False)
    right = factories.create_test_knowledge_item(db, space_id=a, title="Right", commit=True)

    r = cross_space_pair["client_a"].post(
        "/api/v1/knowledge/relations/proposals",
        params=_params(a, ua.id),
        json={
            "from_item_id": left.id,
            "to_item_id": right.id,
            "relation_type": "supports",
            "status": "active",
        },
    )
    assert r.status_code == 202
    accepted = cross_space_pair["client_a"].post(f"/api/v1/proposals/{r.json()['id']}/accept", params=_params(a, ua.id))
    assert accepted.status_code == 200
    assert accepted.json()["result_type"] == "knowledge_relation"
    relation_id = accepted.json()["result"]["knowledge_relation"]["id"]

    db.expire_all()
    relation = db.get(KnowledgeRelation, relation_id)
    assert relation is not None and relation.status == "active"

    delete_prop = cross_space_pair["client_a"].delete(
        f"/api/v1/knowledge/relations/{relation_id}",
        params=_params(a, ua.id),
    )
    assert delete_prop.status_code == 202
    deleted = cross_space_pair["client_a"].post(
        f"/api/v1/proposals/{delete_prop.json()['id']}/accept",
        params=_params(a, ua.id),
    )
    assert deleted.status_code == 200
    db.expire_all()
    relation = db.get(KnowledgeRelation, relation_id)
    assert relation is not None and relation.status == "archived"


def test_relation_reads_do_not_leak_unreadable_private_endpoint(db, same_space_pair):
    space = same_space_pair["space_id"]
    ua = same_space_pair["user_a"]
    ub = same_space_pair["user_b"]
    shared = factories.create_test_knowledge_item(
        db,
        space_id=space,
        title="Shared",
        owner_user_id=ua.id,
        created_by_user_id=ua.id,
        commit=False,
    )
    private = factories.create_test_knowledge_item(
        db,
        space_id=space,
        title="Private",
        visibility="private",
        owner_user_id=ua.id,
        created_by_user_id=ua.id,
        commit=False,
    )
    relation = factories.create_test_knowledge_relation(
        db,
        space_id=space,
        from_item_id=shared.id,
        to_item_id=private.id,
        relation_type="supports",
        commit=True,
    )

    owner_relations = same_space_pair["client_a"].get(
        f"/api/v1/knowledge/items/{shared.id}/relations",
        params=_params(space, ua.id),
    )
    assert owner_relations.status_code == 200
    assert [row["id"] for row in owner_relations.json()] == [relation.id]

    other_private_relations = same_space_pair["client_b"].get(
        f"/api/v1/knowledge/items/{private.id}/relations",
        params=_params(space, ub.id),
    )
    assert other_private_relations.status_code == 404

    other_shared_relations = same_space_pair["client_b"].get(
        f"/api/v1/knowledge/items/{shared.id}/relations",
        params=_params(space, ub.id),
    )
    assert other_shared_relations.status_code == 200
    assert other_shared_relations.json() == []


def test_relation_proposal_requires_readable_endpoints(db, same_space_pair):
    space = same_space_pair["space_id"]
    ua = same_space_pair["user_a"]
    ub = same_space_pair["user_b"]
    shared_a = factories.create_test_knowledge_item(db, space_id=space, title="Shared A", commit=False)
    shared_b = factories.create_test_knowledge_item(db, space_id=space, title="Shared B", commit=False)
    private = factories.create_test_knowledge_item(
        db,
        space_id=space,
        title="Private",
        visibility="private",
        owner_user_id=ua.id,
        created_by_user_id=ua.id,
        commit=True,
    )

    blocked = same_space_pair["client_b"].post(
        "/api/v1/knowledge/relations/proposals",
        params=_params(space, ub.id),
        json={"from_item_id": shared_a.id, "to_item_id": private.id, "relation_type": "related"},
    )
    assert blocked.status_code == 404

    allowed = same_space_pair["client_b"].post(
        "/api/v1/knowledge/relations/proposals",
        params=_params(space, ub.id),
        json={"from_item_id": shared_a.id, "to_item_id": shared_b.id, "relation_type": "related"},
    )
    assert allowed.status_code == 202


def test_apply_relation_create_rejects_malformed_private_endpoint_proposal_from_non_owner(db, same_space_pair):
    space = same_space_pair["space_id"]
    ua = same_space_pair["user_a"]
    ub = same_space_pair["user_b"]
    shared = factories.create_test_knowledge_item(db, space_id=space, title="Shared", commit=False)
    private = factories.create_test_knowledge_item(
        db,
        space_id=space,
        title="Private",
        visibility="private",
        owner_user_id=ua.id,
        created_by_user_id=ua.id,
        commit=False,
    )
    prop = factories.create_test_proposal(
        db,
        space_id=space,
        proposal_type="knowledge_relation_create",
        created_by_user_id=ub.id,
        payload_json={
            "operation": "relation_create",
            "from_item_id": shared.id,
            "to_item_id": private.id,
            "relation_type": "related",
            "status": "active",
        },
        commit=True,
    )

    accepted = same_space_pair["client_b"].post(f"/api/v1/proposals/{prop.id}/accept", params=_params(space, ub.id))
    assert accepted.status_code == 422
    db.expire_all()
    assert db.query(func.count(KnowledgeRelation.id)).filter(KnowledgeRelation.space_id == space).scalar() == 0


def test_apply_relation_create_allows_owner_private_endpoint_and_shared_pair_for_same_space_user(db, same_space_pair):
    space = same_space_pair["space_id"]
    ua = same_space_pair["user_a"]
    ub = same_space_pair["user_b"]
    private = factories.create_test_knowledge_item(
        db,
        space_id=space,
        title="Private",
        visibility="restricted",
        owner_user_id=ua.id,
        created_by_user_id=ua.id,
        commit=False,
    )
    shared_a = factories.create_test_knowledge_item(db, space_id=space, title="Shared A", commit=False)
    shared_b = factories.create_test_knowledge_item(db, space_id=space, title="Shared B", commit=False)
    owner_prop = factories.create_test_proposal(
        db,
        space_id=space,
        proposal_type="knowledge_relation_create",
        created_by_user_id=ua.id,
        payload_json={
            "operation": "relation_create",
            "from_item_id": private.id,
            "to_item_id": shared_a.id,
            "relation_type": "supports",
            "status": "active",
        },
        commit=False,
    )
    shared_prop = factories.create_test_proposal(
        db,
        space_id=space,
        proposal_type="knowledge_relation_create",
        created_by_user_id=ub.id,
        payload_json={
            "operation": "relation_create",
            "from_item_id": shared_a.id,
            "to_item_id": shared_b.id,
            "relation_type": "related",
            "status": "active",
        },
        commit=True,
    )

    owner_accept = same_space_pair["client_a"].post(
        f"/api/v1/proposals/{owner_prop.id}/accept",
        params=_params(space, ua.id),
    )
    assert owner_accept.status_code == 200
    shared_accept = same_space_pair["client_b"].post(
        f"/api/v1/proposals/{shared_prop.id}/accept",
        params=_params(space, ub.id),
    )
    assert shared_accept.status_code == 200

    db.expire_all()
    assert db.query(func.count(KnowledgeRelation.id)).filter(KnowledgeRelation.space_id == space).scalar() == 2


def test_apply_relation_delete_rejects_malformed_private_endpoint_proposal_from_non_owner(db, same_space_pair):
    space = same_space_pair["space_id"]
    ua = same_space_pair["user_a"]
    ub = same_space_pair["user_b"]
    shared = factories.create_test_knowledge_item(db, space_id=space, title="Shared", commit=False)
    private = factories.create_test_knowledge_item(
        db,
        space_id=space,
        title="Private",
        visibility="private",
        owner_user_id=ua.id,
        created_by_user_id=ua.id,
        commit=False,
    )
    relation = factories.create_test_knowledge_relation(
        db,
        space_id=space,
        from_item_id=shared.id,
        to_item_id=private.id,
        commit=False,
    )
    prop = factories.create_test_proposal(
        db,
        space_id=space,
        proposal_type="knowledge_relation_delete",
        created_by_user_id=ub.id,
        payload_json={"operation": "relation_delete", "relation_id": relation.id},
        commit=True,
    )

    accepted = same_space_pair["client_b"].post(f"/api/v1/proposals/{prop.id}/accept", params=_params(space, ub.id))
    assert accepted.status_code == 422
    db.expire_all()
    unchanged = db.get(KnowledgeRelation, relation.id)
    assert unchanged is not None
    assert unchanged.status == "active"


def test_apply_relation_delete_allows_owner_private_relation_and_shared_relation(db, same_space_pair):
    space = same_space_pair["space_id"]
    ua = same_space_pair["user_a"]
    ub = same_space_pair["user_b"]
    private = factories.create_test_knowledge_item(
        db,
        space_id=space,
        title="Private",
        visibility="restricted",
        owner_user_id=ua.id,
        created_by_user_id=ua.id,
        commit=False,
    )
    shared_a = factories.create_test_knowledge_item(db, space_id=space, title="Shared A", commit=False)
    shared_b = factories.create_test_knowledge_item(db, space_id=space, title="Shared B", commit=False)
    private_relation = factories.create_test_knowledge_relation(
        db,
        space_id=space,
        from_item_id=private.id,
        to_item_id=shared_a.id,
        relation_type="supports",
        commit=False,
    )
    shared_relation = factories.create_test_knowledge_relation(
        db,
        space_id=space,
        from_item_id=shared_a.id,
        to_item_id=shared_b.id,
        relation_type="related",
        commit=False,
    )
    owner_prop = factories.create_test_proposal(
        db,
        space_id=space,
        proposal_type="knowledge_relation_delete",
        created_by_user_id=ua.id,
        payload_json={"operation": "relation_delete", "relation_id": private_relation.id},
        commit=False,
    )
    shared_prop = factories.create_test_proposal(
        db,
        space_id=space,
        proposal_type="knowledge_relation_delete",
        created_by_user_id=ub.id,
        payload_json={"operation": "relation_delete", "relation_id": shared_relation.id},
        commit=True,
    )

    owner_accept = same_space_pair["client_a"].post(
        f"/api/v1/proposals/{owner_prop.id}/accept",
        params=_params(space, ua.id),
    )
    assert owner_accept.status_code == 200
    shared_accept = same_space_pair["client_b"].post(
        f"/api/v1/proposals/{shared_prop.id}/accept",
        params=_params(space, ub.id),
    )
    assert shared_accept.status_code == 200

    db.expire_all()
    assert db.get(KnowledgeRelation, private_relation.id).status == "archived"  # type: ignore[union-attr]
    assert db.get(KnowledgeRelation, shared_relation.id).status == "archived"  # type: ignore[union-attr]


def test_relation_create_cross_space_fails_on_accept(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    b = cross_space_pair["space_b_id"]
    ua = cross_space_pair["user_a"]
    left = factories.create_test_knowledge_item(db, space_id=a, title="Left", commit=False)
    right = factories.create_test_knowledge_item(db, space_id=b, title="Right", commit=False)
    prop = factories.create_test_proposal(
        db,
        space_id=a,
        proposal_type="knowledge_relation_create",
        created_by_user_id=ua.id,
        payload_json={
            "operation": "relation_create",
            "from_item_id": left.id,
            "to_item_id": right.id,
            "relation_type": "related",
            "status": "active",
        },
        commit=True,
    )

    accepted = cross_space_pair["client_a"].post(f"/api/v1/proposals/{prop.id}/accept", params=_params(a, ua.id))
    assert accepted.status_code == 422
    db.expire_all()
    relation_count = db.query(func.count(KnowledgeRelation.id)).filter(KnowledgeRelation.space_id == a).scalar()
    assert relation_count == 0


def test_knowledge_item_does_not_create_memory_or_context_entry(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    before_memory = db.query(func.count(MemoryEntry.id)).filter(MemoryEntry.space_id == a).scalar()
    r = cross_space_pair["client_a"].post(
        "/api/v1/knowledge/items/proposals",
        params=_params(a, ua.id),
        json=_create_payload(title="Not memory"),
    )
    accepted = cross_space_pair["client_a"].post(f"/api/v1/proposals/{r.json()['id']}/accept", params=_params(a, ua.id))
    assert accepted.status_code == 200
    db.expire_all()
    after_memory = db.query(func.count(MemoryEntry.id)).filter(MemoryEntry.space_id == a).scalar()
    assert after_memory == before_memory
