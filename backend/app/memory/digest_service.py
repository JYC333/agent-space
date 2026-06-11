from __future__ import annotations
"""
ContextDigestService — versioned derived cache of approved Memory/Policy context.

Core principle:
  Digest is derived cache. Not Memory. Not Policy. Not a source of truth.
  Digest does not create Proposal. Digest can be deleted and regenerated.
  Digest summarises active approved Memory/Policy content only.

Supported digest_type values: policy_bundle, workspace, agent.

Versioning:
  - Source hash computed from source IDs + updated_at/version fields.
  - If active digest exists with same source_hash: return it unchanged.
  - If source_hash changed: mark old active as superseded, create new version+1.
  - If no digest exists: create version=1, status=active.

Initial generation:
  Digests are not auto-generated on every run. The first digest must be
  produced by an explicit call to one of the generate_*() methods:

    svc = ContextDigestService(db)
    svc.generate_policy_bundle_digest(space_id)
    svc.generate_workspace_digest(space_id, workspace_id)
    svc.generate_agent_digest(space_id, agent_id)

  Until a digest is generated, ContextSnapshotPopulator falls back to direct
  MemoryRetriever behaviour for the missing scope (non-blocking, recorded in
  retrieval_trace_json as fallback_reason="no_digest_available").

  Digests are not regenerated on dirty — mark_digest_dirty() only sets
  status="dirty". Regeneration is explicit and under caller control.

Dirty tracking:
  mark_digest_dirty() is a no-op when no active digest exists for a scope.
  This is intentional: there is nothing to invalidate if no digest was ever
  generated. ProposalApplyService calls mark_digest_dirty() after accepted
  proposals; if no digest exists the call is silently skipped.
"""

import hashlib
import json
import logging
from datetime import UTC, datetime
from typing import Optional

from sqlalchemy.orm import Session

from ..models import ContextDigest, MemoryEntry, Policy

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Hashing helpers
# ---------------------------------------------------------------------------


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def _compact(obj) -> str:
    return json.dumps(obj, separators=(",", ":"), sort_keys=True, default=str)


def _compute_source_hash(
    memory_rows: list[MemoryEntry],
    policy_rows: list[Policy],
    relation_ids: list[str] | None = None,
) -> str:
    """Stable hash of the set of sources (IDs + version signals)."""
    mem_parts = sorted(
        f"{m.id}:{m.version}:{m.updated_at.isoformat() if m.updated_at else ''}"
        for m in memory_rows
    )
    pol_parts = sorted(
        f"{p.id}:{p.policy_version}:{p.updated_at.isoformat() if p.updated_at else ''}"
        for p in policy_rows
    )
    rel_parts = sorted(relation_ids or [])
    payload = _compact({"mem": mem_parts, "pol": pol_parts, "rel": rel_parts})
    return _sha256(payload)


# ---------------------------------------------------------------------------
# Content templates (deterministic markdown)
# ---------------------------------------------------------------------------


def _render_policy_bundle(policies: list[Policy]) -> str:
    if not policies:
        return "No active policies."
    lines = ["## Active Policies\n"]
    for p in policies:
        mode = p.enforcement_mode or "none"
        priority = p.priority or 0
        key = p.policy_key or p.name
        rule_summary = ""
        if p.rule_json:
            try:
                rule_summary = _compact(p.rule_json)[:200]
            except Exception:
                rule_summary = str(p.rule_json)[:200]
        elif p.name:
            rule_summary = p.name
        lines.append(
            f"- **{key}** (domain={p.domain}, mode={mode}, priority={priority}): {rule_summary}"
        )
    return "\n".join(lines)


def _render_workspace(memories: list[MemoryEntry], policies: list[Policy]) -> str:
    parts: list[str] = []
    if memories:
        mem_lines = ["## Workspace Memories\n"]
        for m in memories:
            kind = m.memory_kind or m.memory_type or "semantic"
            title = m.title or "(untitled)"
            content = (m.content or "").strip()[:400]
            mem_lines.append(f"- [{kind}] **{title}**: {content}")
        parts.append("\n".join(mem_lines))
    if policies:
        pol_lines = ["## Workspace Policies\n"]
        for p in policies:
            mode = p.enforcement_mode or "none"
            key = p.policy_key or p.name
            pol_lines.append(f"- **{key}** (mode={mode}, priority={p.priority or 0})")
        parts.append("\n".join(pol_lines))
    return "\n\n".join(parts) if parts else "No workspace context."


def _render_agent(memories: list[MemoryEntry], policies: list[Policy]) -> str:
    parts: list[str] = []
    if memories:
        mem_lines = ["## Agent Memories\n"]
        for m in memories:
            kind = m.memory_kind or m.memory_type or "semantic"
            title = m.title or "(untitled)"
            content = (m.content or "").strip()[:400]
            mem_lines.append(f"- [{kind}] **{title}**: {content}")
        parts.append("\n".join(mem_lines))
    if policies:
        pol_lines = ["## Agent Policies\n"]
        for p in policies:
            mode = p.enforcement_mode or "none"
            key = p.policy_key or p.name
            pol_lines.append(f"- **{key}** (mode={mode}, priority={p.priority or 0})")
        parts.append("\n".join(pol_lines))
    return "\n\n".join(parts) if parts else "No agent context."


# ---------------------------------------------------------------------------
# ContextDigestService
# ---------------------------------------------------------------------------


class ContextDigestService:
    """
    Generates and caches versioned digests of approved Memory/Policy content.

    All generation reads only active MemoryEntry and active/enabled Policy rows.
    Never writes MemoryEntry, never creates Proposal, never calls ProposalApplyService.
    """

    def __init__(self, db: Session) -> None:
        self._db = db

    # ------------------------------------------------------------------
    # Public: generation
    # ------------------------------------------------------------------

    def generate_policy_bundle_digest(
        self,
        space_id: str,
        scope_type: Optional[str] = None,
        scope_id: Optional[str] = None,
    ) -> ContextDigest:
        """Generate (or reuse) the policy_bundle digest for a space."""
        policies = self._active_policies(space_id, scope_type=scope_type, scope_id=scope_id)
        source_hash = _compute_source_hash([], policies)
        content = _render_policy_bundle(policies)
        return self._upsert_digest(
            space_id=space_id,
            scope_type=scope_type or "space",
            scope_id=scope_id,
            digest_type="policy_bundle",
            memories=[],
            policies=policies,
            relation_ids=None,
            source_hash=source_hash,
            content=content,
        )

    def generate_workspace_digest(self, space_id: str, workspace_id: str) -> ContextDigest:
        """Generate (or reuse) the workspace digest for a workspace."""
        memories = self._active_memories(
            space_id, scope_type="workspace", scope_id=workspace_id
        )
        policies = self._active_policies(
            space_id, scope_type="workspace", scope_id=workspace_id
        )
        source_hash = _compute_source_hash(memories, policies)
        content = _render_workspace(memories, policies)
        return self._upsert_digest(
            space_id=space_id,
            scope_type="workspace",
            scope_id=workspace_id,
            digest_type="workspace",
            memories=memories,
            policies=policies,
            relation_ids=None,
            source_hash=source_hash,
            content=content,
        )

    def generate_agent_digest(self, space_id: str, agent_id: str) -> ContextDigest:
        """Generate (or reuse) the agent digest for an agent."""
        memories = self._active_memories(space_id, scope_type="agent", scope_id=agent_id)
        policies = self._active_policies(space_id, scope_type="agent", scope_id=agent_id)
        source_hash = _compute_source_hash(memories, policies)
        content = _render_agent(memories, policies)
        return self._upsert_digest(
            space_id=space_id,
            scope_type="agent",
            scope_id=agent_id,
            digest_type="agent",
            memories=memories,
            policies=policies,
            relation_ids=None,
            source_hash=source_hash,
            content=content,
        )

    # ------------------------------------------------------------------
    # Public: retrieval
    # ------------------------------------------------------------------

    def get_active_digest(
        self,
        space_id: str,
        scope_type: str,
        scope_id: Optional[str],
        digest_type: str,
    ) -> Optional[ContextDigest]:
        """Return the active (or dirty-but-active) digest for the given scope, or None."""
        q = (
            self._db.query(ContextDigest)
            .filter(
                ContextDigest.space_id == space_id,
                ContextDigest.scope_type == scope_type,
                ContextDigest.digest_type == digest_type,
                ContextDigest.status.in_(["active", "dirty"]),
            )
        )
        if scope_id is not None:
            q = q.filter(ContextDigest.scope_id == scope_id)
        else:
            q = q.filter(ContextDigest.scope_id == None)  # noqa: E711
        return q.order_by(ContextDigest.version.desc()).first()

    # ------------------------------------------------------------------
    # Public: dirty tracking
    # ------------------------------------------------------------------

    def mark_digest_dirty(
        self,
        space_id: str,
        scope_type: str,
        scope_id: Optional[str],
        digest_type: str,
        reason: str,
    ) -> None:
        """Mark an active digest as dirty. No-op if no active digest exists."""
        digest = self.get_active_digest(space_id, scope_type, scope_id, digest_type)
        if digest is None:
            return
        if digest.status == "active":
            digest.status = "dirty"
            digest.dirty_since = datetime.now(UTC)
        # Always update dirty metadata
        existing_reason = digest.dirty_reason_json or {}
        existing_reason["latest"] = reason
        reasons: list = existing_reason.get("reasons", [])
        reasons.append({"reason": reason, "at": datetime.now(UTC).isoformat()})
        existing_reason["reasons"] = reasons[-10:]  # cap at last 10
        digest.dirty_reason_json = existing_reason
        digest.dirty_count = (digest.dirty_count or 0) + 1
        self._db.add(digest)
        self._db.flush()

    # ------------------------------------------------------------------
    # Internal: source queries (active/approved content only)
    # ------------------------------------------------------------------

    def _active_memories(
        self,
        space_id: str,
        scope_type: str,
        scope_id: Optional[str],
    ) -> list[MemoryEntry]:
        """Active MemoryEntry rows for the given scope. Never returns proposed/archived/superseded."""
        q = (
            self._db.query(MemoryEntry)
            .filter(
                MemoryEntry.space_id == space_id,
                MemoryEntry.scope_type == scope_type,
                MemoryEntry.status == "active",
                MemoryEntry.deleted_at == None,  # noqa: E711
            )
        )
        if scope_id is not None:
            if scope_type == "workspace":
                q = q.filter(MemoryEntry.workspace_id == scope_id)
            elif scope_type == "agent":
                q = q.filter(MemoryEntry.agent_id == scope_id)
        return q.all()

    def _active_policies(
        self,
        space_id: str,
        scope_type: Optional[str] = None,
        scope_id: Optional[str] = None,
    ) -> list[Policy]:
        """Active, enabled Policy rows. Never returns disabled/superseded/draft."""
        q = (
            self._db.query(Policy)
            .filter(
                Policy.space_id == space_id,
                Policy.status == "active",
                Policy.enabled == True,  # noqa: E712
            )
        )
        # If scope_type indicates workspace/agent, filter by applies_to_json if present.
        # For simple policy_bundle (space-level), return all active policies.
        if scope_type in ("workspace", "agent") and scope_id:
            # Return policies that either apply to this scope or have no specific scope filter.
            # We use Python-level filtering since applies_to_json is a JSON column.
            rows = q.all()
            return [
                p for p in rows
                if _policy_applies_to(p, scope_type=scope_type, scope_id=scope_id)
            ]
        return q.all()

    # ------------------------------------------------------------------
    # Internal: upsert / versioning
    # ------------------------------------------------------------------

    def _upsert_digest(
        self,
        *,
        space_id: str,
        scope_type: str,
        scope_id: Optional[str],
        digest_type: str,
        memories: list[MemoryEntry],
        policies: list[Policy],
        relation_ids: Optional[list[str]],
        source_hash: str,
        content: str,
    ) -> ContextDigest:
        """Create or version a digest. Returns the active digest row."""
        existing = self.get_active_digest(space_id, scope_type, scope_id, digest_type)

        if existing is not None and existing.source_hash == source_hash:
            # Sources unchanged — reuse existing digest, ensure status is active.
            if existing.status == "dirty":
                existing.status = "active"
                existing.dirty_since = None
                existing.dirty_reason_json = None
                self._db.add(existing)
                self._db.flush()
            return existing

        content_hash = _sha256(content)
        now = datetime.now(UTC)

        if existing is not None:
            # Mark old active digest superseded.
            existing.status = "superseded"
            self._db.add(existing)
            new_version = existing.version + 1
        else:
            new_version = 1

        new_digest = ContextDigest(
            space_id=space_id,
            scope_type=scope_type,
            scope_id=scope_id,
            digest_type=digest_type,
            version=new_version,
            status="active",
            content=content,
            source_memory_ids_json=[m.id for m in memories],
            source_policy_ids_json=[p.id for p in policies],
            source_relation_ids_json=relation_ids or [],
            source_hash=source_hash,
            content_hash=content_hash,
            dirty_since=None,
            dirty_reason_json=None,
            dirty_count=0,
            generated_at=now,
        )
        self._db.add(new_digest)
        self._db.flush()
        return new_digest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _policy_applies_to(
    policy: Policy,
    scope_type: str,
    scope_id: str,
) -> bool:
    """Return True if the policy applies to the given scope (or has no scope filter)."""
    applies = policy.applies_to_json
    if not applies:
        return True  # no scope filter → applies to all
    # Check if the policy explicitly targets this scope_type/scope_id.
    targets = applies.get("scope_types") or applies.get("scopes") or []
    if isinstance(targets, list):
        if targets and scope_type not in targets:
            return False
    scope_ids = applies.get("scope_ids") or []
    if isinstance(scope_ids, list) and scope_ids:
        return scope_id in scope_ids
    return True
