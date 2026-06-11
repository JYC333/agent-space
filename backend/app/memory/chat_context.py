"""
ChatContextBuilder — dynamic context selection for the Personal Assistant / chat path.

Reads AgentVersion.context_policy_json as the allowed context boundary.  Selects
context from available sources without embeddings, vector DB, or graph traversal.

Selection priority (highest → lowest):
  1. Explicit / manual context
  2. Current workspace and project metadata
  3. Approved memory (via MemoryRetriever)
  4. Knowledge items
  5. Sources
  6. Recent activity records

Token budget and max_items caps are enforced; items are deduplicated by (type, id).
Context types absent from context_policy_json.sources are silently excluded.

AgentVersion is never mutated per-run — all per-run decisions stay inside
ContextBundle and the resulting ContextSnapshot + ContextSnapshotItem rows.
"""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy.orm import Session

from ..models import (
    ActivityRecord,
    AgentVersion,
    ContextSnapshot,
    ContextSnapshotItem,
    KnowledgeItem,
    Project,
    Source,
    Workspace,
)
from ..schemas import ContextBundle, ContextBundleItem, ContextRequest
from .retriever import MemoryRetriever

log = logging.getLogger(__name__)

# All source type tokens recognised by context_policy_json.sources.
_ALL_SOURCES: frozenset[str] = frozenset(
    [
        "memory",
        "knowledge_item",
        "source",
        "activity_record",
        "task",
        "project",
        "workspace",
        "run",
        "proposal",
        "artifact",
        "manual_context",
    ]
)

# Per-item excerpt truncation limit (characters).
_MAX_EXCERPT_CHARS = 800


def _excerpt(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    return text[:_MAX_EXCERPT_CHARS]


def _tokens(text: Optional[str]) -> int:
    return len(text or "") // 4


class ChatContextBuilder:
    """
    Dynamic context selector for the Personal Assistant / chat path.

    Uses AgentVersion.context_policy_json as the allowed boundary for each request.
    Never mutates AgentVersion — all selection decisions are local to build() and
    persisted in ContextSnapshot / ContextSnapshotItem rows by persist_snapshot().
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    # ── Policy helpers ───────────────────────────────────────────────────────

    def _load_policy(
        self, agent_version_id: Optional[str]
    ) -> tuple[frozenset[str], dict]:
        """Return (allowed_sources, raw_policy_dict) from AgentVersion.

        Falls back to (all_sources, {}) when agent_version_id is absent or the
        version cannot be found — conservative permissive default.
        """
        if not agent_version_id:
            return _ALL_SOURCES, {}
        version = (
            self.db.query(AgentVersion)
            .filter(AgentVersion.id == agent_version_id)
            .first()
        )
        if version is None:
            return _ALL_SOURCES, {}
        policy = version.context_policy_json or {}
        sources = policy.get("sources")
        if not sources:
            # Empty or absent sources list → all sources allowed.
            return _ALL_SOURCES, policy
        return frozenset(sources) & _ALL_SOURCES, policy

    # ── Source selectors ─────────────────────────────────────────────────────

    def _select_manual(self, request: ContextRequest) -> list[ContextBundleItem]:
        items: list[ContextBundleItem] = []
        for mc in request.manual_context:
            text = mc.get("content") or mc.get("excerpt") or ""
            items.append(
                ContextBundleItem(
                    item_type="manual_context",
                    item_id=mc.get("id"),
                    title=mc.get("title"),
                    excerpt=_excerpt(text),
                    score=1.0,
                    reason="explicit_selection",
                    token_count=_tokens(text),
                    metadata=mc,
                )
            )
        return items

    def _select_workspace(self, request: ContextRequest) -> list[ContextBundleItem]:
        if not request.workspace_id:
            return []
        ws = (
            self.db.query(Workspace)
            .filter(
                Workspace.id == request.workspace_id,
                Workspace.space_id == request.space_id,
            )
            .first()
        )
        if ws is None:
            return []
        text = ws.description or ws.name or ""
        return [
            ContextBundleItem(
                item_type="workspace",
                item_id=ws.id,
                title=ws.name,
                excerpt=_excerpt(text),
                score=0.9,
                reason="current_workspace",
                token_count=_tokens(text),
            )
        ]

    def _select_project(self, request: ContextRequest) -> list[ContextBundleItem]:
        if not request.project_id:
            return []
        proj = (
            self.db.query(Project)
            .filter(
                Project.id == request.project_id,
                Project.space_id == request.space_id,
            )
            .first()
        )
        if proj is None:
            return []
        text = proj.description or proj.name or ""
        return [
            ContextBundleItem(
                item_type="project",
                item_id=proj.id,
                title=proj.name,
                excerpt=_excerpt(text),
                score=0.9,
                reason="current_project",
                token_count=_tokens(text),
            )
        ]

    def _select_memory(
        self, request: ContextRequest, limit: int
    ) -> list[ContextBundleItem]:
        retriever = MemoryRetriever(self.db)
        result = retriever.retrieve(
            space_id=request.space_id,
            user_id=request.user_id,
            workspace_id=request.workspace_id,
            agent_id=None,
            query=request.user_message,
            agent_memory_policy=None,
            max_memories=min(limit, 10),
            include_system_scope=False,
        )
        items: list[ContextBundleItem] = []
        for m in result.memories:
            text = m.content or ""
            items.append(
                ContextBundleItem(
                    item_type="memory",
                    item_id=m.id,
                    title=m.title,
                    excerpt=_excerpt(text),
                    score=0.8,
                    reason="approved_memory",
                    token_count=_tokens(text),
                )
            )
        return items

    def _select_knowledge_items(
        self,
        request: ContextRequest,
        allowed: frozenset[str],
        limit: int,
    ) -> list[ContextBundleItem]:
        # Build the knowledge_item.item_type filter based on allowed sources.
        type_filter: list[str] = []
        if "knowledge_item" in allowed:
            type_filter += [
                "concept",
                "claim",
                "lesson",
                "procedure",
                "decision",
                "question",
                "answer",
                "summary",
            ]
        if not type_filter:
            return []

        q = self.db.query(KnowledgeItem).filter(
            KnowledgeItem.space_id == request.space_id,
            KnowledgeItem.status == "active",
            KnowledgeItem.item_type.in_(type_filter),
        )
        if request.workspace_id:
            q = q.filter(KnowledgeItem.workspace_id == request.workspace_id)
        # Recent-first for knowledge items (simple keyword/recency retrieval).
        if request.user_message:
            keyword = f"%{request.user_message[:40]}%"
            from sqlalchemy import or_

            q = q.filter(
                or_(
                    KnowledgeItem.title.ilike(keyword),
                    KnowledgeItem.content.ilike(keyword),
                )
            )
        q = q.order_by(KnowledgeItem.updated_at.desc()).limit(limit)

        items: list[ContextBundleItem] = []
        for ki in q:
            text = ki.content or ""
            items.append(
                ContextBundleItem(
                    item_type="knowledge_item",
                    item_id=ki.id,
                    title=ki.title,
                    excerpt=_excerpt(text),
                    score=0.7,
                    reason="knowledge_item",
                    token_count=_tokens(text),
                )
            )
        return items

    def _select_sources(
        self, request: ContextRequest, limit: int
    ) -> list[ContextBundleItem]:
        q = (
            self.db.query(Source)
            .filter(
                Source.space_id == request.space_id,
                Source.status == "processed",
            )
            .order_by(Source.created_at.desc())
            .limit(limit)
        )
        items: list[ContextBundleItem] = []
        for src in q:
            text = src.summary or src.raw_text or ""
            items.append(
                ContextBundleItem(
                    item_type="source",
                    item_id=src.id,
                    title=src.title,
                    excerpt=_excerpt(text),
                    score=0.6,
                    reason="source",
                    token_count=_tokens(text),
                )
            )
        return items

    def _select_activity_records(
        self, request: ContextRequest, limit: int
    ) -> list[ContextBundleItem]:
        q = self.db.query(ActivityRecord).filter(
            ActivityRecord.space_id == request.space_id
        )
        if request.workspace_id:
            q = q.filter(ActivityRecord.workspace_id == request.workspace_id)
        # Recent-first for activity records.
        q = q.order_by(ActivityRecord.occurred_at.desc()).limit(limit)

        items: list[ContextBundleItem] = []
        for ar in q:
            text = ar.content or ""
            items.append(
                ContextBundleItem(
                    item_type="activity_record",
                    item_id=ar.id,
                    title=ar.title,
                    excerpt=_excerpt(text),
                    score=0.5,
                    reason="recent_activity",
                    token_count=_tokens(text),
                )
            )
        return items

    # ── Main entry points ────────────────────────────────────────────────────

    def build(self, request: ContextRequest) -> ContextBundle:
        """
        Select context for a Personal Assistant / chat model call.

        Reads AgentVersion.context_policy_json for the allowed boundary.
        Items are collected in priority order and truncated at max_tokens /
        max_items. Duplicate (item_type, item_id) pairs are silently dropped.

        Does not persist any rows — call persist_snapshot() after building.
        """
        if not request.space_id:
            raise ValueError("space_id is required")
        if not request.user_id:
            raise ValueError("user_id is required")

        allowed, context_policy = self._load_policy(request.agent_version_id)
        max_tokens: int = context_policy.get("max_tokens", request.max_tokens)
        max_items: int = context_policy.get("max_items", request.max_items)

        items: list[ContextBundleItem] = []
        seen: set[tuple[str, str]] = set()
        total_tokens = 0

        def _add(candidates: list[ContextBundleItem]) -> None:
            nonlocal total_tokens
            for item in candidates:
                if total_tokens >= max_tokens or len(items) >= max_items:
                    return
                key = (item.item_type, str(item.item_id or id(item)))
                if key in seen:
                    continue
                seen.add(key)
                items.append(item)
                total_tokens += item.token_count or 0

        # 1. Explicit / manual context (highest priority — always first).
        if "manual_context" in allowed:
            _add(self._select_manual(request))

        # 2. Current workspace metadata.
        if "workspace" in allowed:
            _add(self._select_workspace(request))

        # 3. Current project metadata.
        if "project" in allowed:
            _add(self._select_project(request))

        # 4. Approved memory.
        if "memory" in allowed:
            remaining = max_items - len(items)
            if remaining > 0:
                _add(self._select_memory(request, limit=remaining))

        # 5. Knowledge items.
        if "knowledge_item" in allowed:
            remaining = max_items - len(items)
            if remaining > 0:
                _add(self._select_knowledge_items(request, allowed, limit=remaining))

        # 6. Sources.
        if "source" in allowed:
            remaining = max_items - len(items)
            if remaining > 0:
                _add(self._select_sources(request, limit=remaining))

        # 7. Recent activity records.
        if "activity_record" in allowed:
            remaining = max_items - len(items)
            if remaining > 0:
                _add(self._select_activity_records(request, limit=remaining))

        truncated = total_tokens >= max_tokens or len(items) >= max_items

        return ContextBundle(
            items=items,
            token_count=total_tokens,
            truncated=truncated,
            retrieval_trace={
                "allowed_sources": sorted(allowed),
                "context_policy_applied": bool(request.agent_version_id),
                "item_count": len(items),
                "total_tokens": total_tokens,
                "truncated": truncated,
                "max_tokens": max_tokens,
                "max_items": max_items,
            },
        )

    def persist_snapshot(
        self,
        bundle: ContextBundle,
        request: ContextRequest,
        context_snapshot_id: Optional[str] = None,
    ) -> ContextSnapshot:
        """
        Persist ContextSnapshot and ContextSnapshotItem rows for audit.

        If context_snapshot_id is provided, updates that row in-place.
        Otherwise creates a new ContextSnapshot.  Flushes but does not commit —
        the caller owns the transaction boundary.

        Sets bundle.snapshot_id to the persisted snapshot's id.
        """
        snap: Optional[ContextSnapshot] = None
        if context_snapshot_id:
            snap = (
                self.db.query(ContextSnapshot)
                .filter(ContextSnapshot.id == context_snapshot_id)
                .first()
            )

        if snap is None:
            snap = ContextSnapshot(
                space_id=request.space_id,
                source_refs_json=[],
                token_estimate=bundle.token_count,
                request_json=request.model_dump(mode="json"),
                session_id=request.session_id,
                run_id=request.run_id,
            )
            # Derive agent_id from the AgentVersion if available.
            if request.agent_version_id:
                version = (
                    self.db.query(AgentVersion)
                    .filter(AgentVersion.id == request.agent_version_id)
                    .first()
                )
                if version is not None:
                    snap.agent_id = version.agent_id
            self.db.add(snap)
            self.db.flush()
        else:
            snap.token_estimate = bundle.token_count
            snap.request_json = request.model_dump(mode="json")
            self.db.flush()

        # Persist per-item audit rows.
        for item in bundle.items:
            sni = ContextSnapshotItem(
                context_snapshot_id=snap.id,
                item_type=item.item_type,
                item_id=item.item_id,
                title=item.title,
                excerpt=item.excerpt,
                score=item.score,
                reason=item.reason,
                token_count=item.token_count,
                metadata_json=item.metadata or {},
            )
            self.db.add(sni)
        self.db.flush()

        bundle.snapshot_id = snap.id
        return snap

    def list_snapshot_items(
        self, context_snapshot_id: str
    ) -> list[ContextSnapshotItem]:
        """Return all items for a given snapshot, ordered by creation time."""
        return (
            self.db.query(ContextSnapshotItem)
            .filter(ContextSnapshotItem.context_snapshot_id == context_snapshot_id)
            .order_by(ContextSnapshotItem.created_at)
            .all()
        )
