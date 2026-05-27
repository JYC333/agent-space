"""
Contract: DigestRefreshRequest validation — strict field rules.

Checks:
  - Empty request refreshes all dirty digests.
  - workspace digest requires scope_id.
  - agent digest requires scope_id.
  - Unknown digest_type is rejected with 422.
  - Extra unknown fields are rejected with 422.
  - scope_type without digest_type is rejected.
  - digest_type without scope_type is rejected.
  - Refresh never writes MemoryEntry, Proposal, or Policy.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.memory.context_api import DigestRefreshRequest
from app.models import MemoryEntry, Policy, Proposal


# ---------------------------------------------------------------------------
# Pydantic validation tests (model level — no HTTP required)
# ---------------------------------------------------------------------------


def test_empty_request_is_valid():
    req = DigestRefreshRequest()
    assert req.scope_type is None
    assert req.digest_type is None
    assert req.scope_id is None


def test_specific_policy_bundle_request_is_valid():
    req = DigestRefreshRequest(scope_type="space", digest_type="policy_bundle")
    assert req.scope_type == "space"
    assert req.digest_type == "policy_bundle"
    assert req.scope_id is None


def test_workspace_digest_requires_scope_id():
    with pytest.raises(ValidationError) as exc_info:
        DigestRefreshRequest(scope_type="workspace", digest_type="workspace")
    errors = exc_info.value.errors()
    assert any("scope_id" in str(e) for e in errors), (
        "workspace digest_type must require scope_id"
    )


def test_agent_digest_requires_scope_id():
    with pytest.raises(ValidationError) as exc_info:
        DigestRefreshRequest(scope_type="agent", digest_type="agent")
    errors = exc_info.value.errors()
    assert any("scope_id" in str(e) for e in errors), (
        "agent digest_type must require scope_id"
    )


def test_workspace_digest_with_scope_id_is_valid():
    req = DigestRefreshRequest(
        scope_type="workspace",
        digest_type="workspace",
        scope_id="ws-123",
    )
    assert req.scope_id == "ws-123"


def test_agent_digest_with_scope_id_is_valid():
    req = DigestRefreshRequest(
        scope_type="agent",
        digest_type="agent",
        scope_id="agent-456",
    )
    assert req.scope_id == "agent-456"


def test_unknown_digest_type_is_rejected():
    with pytest.raises(ValidationError) as exc_info:
        DigestRefreshRequest(scope_type="space", digest_type="unknown_type")
    errors = exc_info.value.errors()
    assert any("digest_type" in str(e) or "unknown_type" in str(e) for e in errors), (
        "Unknown digest_type must be rejected"
    )


def test_extra_fields_are_rejected():
    with pytest.raises(ValidationError) as exc_info:
        DigestRefreshRequest(scope_type="space", digest_type="policy_bundle", surprise_field="oops")
    errors = exc_info.value.errors()
    assert any("extra" in str(e).lower() or "surprise_field" in str(e) for e in errors), (
        "Unknown extra fields must be rejected (extra='forbid')"
    )


def test_scope_type_without_digest_type_is_rejected():
    with pytest.raises(ValidationError) as exc_info:
        DigestRefreshRequest(scope_type="workspace")
    errors = exc_info.value.errors()
    assert any("digest_type" in str(e) or "scope_type" in str(e) for e in errors)


def test_digest_type_without_scope_type_is_rejected():
    with pytest.raises(ValidationError) as exc_info:
        DigestRefreshRequest(digest_type="workspace", scope_id="ws-123")
    errors = exc_info.value.errors()
    assert any("scope_type" in str(e) or "digest_type" in str(e) for e in errors)


# ---------------------------------------------------------------------------
# Service-level: refresh never writes MemoryEntry / Proposal / Policy
# ---------------------------------------------------------------------------


def test_refresh_all_dirty_never_writes_memory_entry_or_proposal(db, cross_space_pair_db):
    from app.memory.digest_refresh import ContextDigestRefreshService
    from app.memory.digest_service import ContextDigestService
    from app.models import SessionSummary

    space_id = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    ws = factories.create_test_workspace(db, space_id=space_id, created_by_user_id=ua.id)

    # Seed a workspace memory and generate a digest
    from app.models import MemoryEntry as ME
    mem = ME(
        id=__import__("ulid", fromlist=["ULID"]).ULID().__str__(),
        space_id=space_id,
        scope_type="workspace",
        memory_type="semantic",
        content="workspace knowledge",
        status="active",
        visibility="space_shared",
        workspace_id=ws.id,
    )
    db.add(mem)
    db.flush()

    svc = ContextDigestService(db)
    svc.generate_workspace_digest(space_id, ws.id)
    svc.mark_digest_dirty(space_id, "workspace", ws.id, "workspace", reason="test")
    db.flush()

    before_mem = db.query(MemoryEntry).filter(MemoryEntry.space_id == space_id).count()
    before_prop = db.query(Proposal).filter(Proposal.space_id == space_id).count()
    before_pol = db.query(Policy).filter(Policy.space_id == space_id).count()

    refresh_svc = ContextDigestRefreshService(db)
    refresh_svc.refresh_all_dirty(space_id)

    after_mem = db.query(MemoryEntry).filter(MemoryEntry.space_id == space_id).count()
    after_prop = db.query(Proposal).filter(Proposal.space_id == space_id).count()
    after_pol = db.query(Policy).filter(Policy.space_id == space_id).count()

    assert after_mem == before_mem, "refresh must not create MemoryEntry rows"
    assert after_prop == before_prop, "refresh must not create Proposal rows"
    assert after_pol == before_pol, "refresh must not create Policy rows"


# Import factories after to avoid circular import issues
from tests.support import factories  # noqa: E402
