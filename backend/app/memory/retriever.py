"""
MemoryRetriever — policy-aware retrieval pipeline for run context injection.

Retrieval order:
  0. Hard Filter   (space_id, scope, visibility, status, deleted_at, agent permission)
  1. Symbol Match  (workspace_id, agent_id, user_id, scope_type, memory_kind)
  2. Relation Graph Expansion  (MemoryRelation, max 2 hops, scope-bounded)
  3. Keyword Fallback  (title/content ilike, existing store.search behaviour)
  4. Embedding Fallback Interface  (stub; delegates to keyword for now)

Hard filter is applied at the SQL query level before any ranking.  It is
re-applied after graph expansion to ensure forbidden memory cannot re-enter
the candidate set through relation traversal.

Rules:
  - Cross-space memory never enters the candidate set.
  - Private memory for another user never enters.
  - archived / superseded / rejected / proposed memory excluded by default.
  - deleted memory (deleted_at IS NOT NULL) always excluded.
  - Hard filter cannot be bypassed by keyword or embedding fallback.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..models import MemoryEntry, MemoryRelation, Policy
from ..policy import can_read_memory_in_run_context

log = logging.getLogger(__name__)

# Statuses eligible for context injection (default). Others are excluded.
_ALLOWED_STATUSES = frozenset({"active"})

# Relation types allowed during graph expansion (directed search only).
_ALLOWED_RELATION_TYPES = frozenset(
    {"derived_from", "related_to", "applies_to", "supports", "caused_by"}
)

# Maximum relation-graph hops.
_MAX_HOPS = 2


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass
class RetrievalResult:
    memories: list[MemoryEntry]
    active_policies: list[Policy]
    source_refs: list[dict]
    retrieval_trace: dict
    token_budget: dict


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _hard_filter_row(
    m: MemoryEntry,
    *,
    space_id: str,
    user_id: str,
    workspace_id: str | None,
    include_system_scope: bool,
    db: Session | None = None,
) -> bool:
    """Return True if the row passes all hard-filter checks."""
    if m.space_id != space_id:
        return False
    if m.deleted_at is not None:
        return False
    if m.status not in _ALLOWED_STATUSES:
        return False
    if db is None:
        from .read_auth import can_read_memory

        return can_read_memory(
            m,
            user_id=user_id,
            space_id=space_id,
            workspace_id=workspace_id,
            include_system_scope=include_system_scope,
        )
    return can_read_memory_in_run_context(
        m,
        user_id=user_id,
        space_id=space_id,
        workspace_id=workspace_id,
        db=db,
        include_system_scope=include_system_scope,
    )


def _hard_filter_list(
    rows: list[MemoryEntry],
    *,
    space_id: str,
    user_id: str,
    workspace_id: str | None,
    include_system_scope: bool,
    db: Session | None = None,
) -> list[MemoryEntry]:
    return [
        m
        for m in rows
        if _hard_filter_row(
            m,
            space_id=space_id,
            user_id=user_id,
            workspace_id=workspace_id,
            include_system_scope=include_system_scope,
            db=db,
        )
    ]


def _base_query(db: Session, space_id: str):
    """Base SQL query: space-bound, non-deleted, status=active."""
    return (
        db.query(MemoryEntry)
        .filter(
            MemoryEntry.space_id == space_id,
            MemoryEntry.deleted_at.is_(None),
            MemoryEntry.status == "active",
        )
    )


def _source_ref(
    m: MemoryEntry,
    *,
    reason: str,
    section: str,
    stage: str,
) -> dict:
    return {
        "source_type": "memory",
        "source_id": m.id,
        "reason": reason,
        "section": section,
        "stage": stage,
        "source_trust": m.source_trust or "internal_system",
        "memory_kind": m.memory_kind,
        "memory_layer": m.memory_layer,
        "scope_type": m.scope_type,
    }


def _policy_source_ref(p: Policy) -> dict:
    return {
        "source_type": "policy",
        "source_id": p.id,
        "reason": "active_policy",
        "section": "stable_prefix",
        "stage": "policy_load",
        "policy_key": p.policy_key,
        "domain": p.domain,
    }


# ---------------------------------------------------------------------------
# MemoryRetriever
# ---------------------------------------------------------------------------


class MemoryRetriever:
    """
    Policy-aware memory retrieval pipeline.

    Parameters
    ----------
    db : SQLAlchemy Session
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def retrieve(
        self,
        *,
        space_id: str,
        user_id: str,
        workspace_id: str | None = None,
        agent_id: str | None = None,
        query: str | None = None,
        agent_memory_policy: dict | None = None,
        max_memories: int = 30,
        include_system_scope: bool = False,
    ) -> RetrievalResult:
        """
        Run the full retrieval pipeline and return a RetrievalResult.

        Hard filter is applied at SQL level and re-applied after graph
        expansion.  Forbidden memory cannot re-enter the candidate set.
        """
        if not space_id:
            raise ValueError("space_id is required for retrieval")

        hard_filter_kwargs: dict[str, Any] = {
            "space_id": space_id,
            "user_id": user_id,
            "workspace_id": workspace_id,
            "include_system_scope": include_system_scope,
        }

        # Determine readable scopes from agent_memory_policy.
        all_scopes = {"system", "space", "user", "workspace", "capability", "agent"}
        readable_scopes: set[str] = set(all_scopes)
        if agent_memory_policy:
            declared = agent_memory_policy.get("readable_scopes")
            if declared is not None:
                readable_scopes = set(declared) & all_scopes

        if not include_system_scope:
            readable_scopes.discard("system")

        trace_hard_filter = {
            "space_id": space_id,
            "user_id": user_id,
            "readable_scopes": sorted(readable_scopes),
            "excluded_statuses": sorted(
                {"archived", "superseded", "rejected", "proposed", "deleted"}
            ),
            "cross_space_blocked": True,
            "private_other_user_blocked": True,
        }

        seen_ids: set[str] = set()
        source_refs: list[dict] = []
        stage_traces: list[dict] = []

        # ── Stage 1: Symbol Match ────────────────────────────────────────
        symbol_rows = self._symbol_match(
            space_id=space_id,
            user_id=user_id,
            workspace_id=workspace_id,
            agent_id=agent_id,
            readable_scopes=readable_scopes,
        )
        symbol_rows = _hard_filter_list(symbol_rows, db=self.db, **hard_filter_kwargs)
        for m in symbol_rows:
            if m.id not in seen_ids:
                seen_ids.add(m.id)
                source_refs.append(
                    _source_ref(
                        m,
                        reason="symbol_match",
                        section=_assign_section(m),
                        stage="symbol_match",
                    )
                )
        stage_traces.append({
            "stage": "symbol_match",
            "found": len([r for r in source_refs if r["stage"] == "symbol_match"]),
            "ids": [r["source_id"] for r in source_refs if r["stage"] == "symbol_match"],
        })

        # ── Stage 2: Relation Graph Expansion ───────────────────────────
        if seen_ids:
            graph_rows, hop_count = self._graph_expand(
                seed_ids=set(seen_ids),
                space_id=space_id,
                readable_scopes=readable_scopes,
                hard_filter_kwargs=hard_filter_kwargs,
            )
            new_graph: list[str] = []
            for m in graph_rows:
                if m.id not in seen_ids:
                    seen_ids.add(m.id)
                    new_graph.append(m.id)
                    source_refs.append(
                        _source_ref(
                            m,
                            reason=f"graph_expansion_hop_{hop_count}",
                            section=_assign_section(m),
                            stage="graph_expansion",
                        )
                    )
            stage_traces.append({
                "stage": "graph_expansion",
                "hops_used": hop_count,
                "found": len(new_graph),
                "ids": new_graph,
            })
        else:
            stage_traces.append({"stage": "graph_expansion", "hops_used": 0, "found": 0, "ids": []})

        # ── Stage 3: Keyword Fallback ────────────────────────────────────
        keyword_rows: list[MemoryEntry] = []
        keyword_new: list[str] = []
        if query:
            keyword_rows = self._keyword_fallback(
                query=query,
                space_id=space_id,
                readable_scopes=readable_scopes,
                hard_filter_kwargs=hard_filter_kwargs,
            )
            for m in keyword_rows:
                if m.id not in seen_ids:
                    seen_ids.add(m.id)
                    keyword_new.append(m.id)
                    source_refs.append(
                        _source_ref(
                            m,
                            reason="keyword_fallback",
                            section=_assign_section(m),
                            stage="keyword_fallback",
                        )
                    )
        stage_traces.append({
            "stage": "keyword_fallback",
            "query": query or "",
            "found": len(keyword_new),
            "ids": keyword_new,
        })

        # ── Stage 4: Embedding Fallback (stub) ──────────────────────────
        # Delegates to keyword for now; no vector DB.
        embedding_new: list[str] = []
        embedding_rows = self._embedding_fallback(
            query=query,
            space_id=space_id,
            existing_ids=set(seen_ids),
            readable_scopes=readable_scopes,
            hard_filter_kwargs=hard_filter_kwargs,
        )
        for m in embedding_rows:
            if m.id not in seen_ids:
                seen_ids.add(m.id)
                embedding_new.append(m.id)
                source_refs.append(
                    _source_ref(
                        m,
                        reason="embedding_fallback",
                        section=_assign_section(m),
                        stage="embedding_fallback",
                    )
                )
        stage_traces.append({
            "stage": "embedding_fallback",
            "backend": "keyword_delegation",
            "found": len(embedding_new),
            "ids": embedding_new,
        })

        # ── Assemble final ranked list ───────────────────────────────────
        # Fetch all collected ids, hard-filter again (belt-and-suspenders).
        final_memories = self._load_and_rank(
            ids=list(seen_ids),
            space_id=space_id,
            hard_filter_kwargs=hard_filter_kwargs,
            max_memories=max_memories,
        )
        # Trim source_refs to only include IDs that survived final ranking.
        final_ids = {m.id for m in final_memories}
        source_refs = [r for r in source_refs if r["source_id"] in final_ids]

        # ── Load active policies ─────────────────────────────────────────
        active_policies, policy_refs = self._load_active_policies(space_id)
        source_refs.extend(policy_refs)

        token_budget = {
            "default_budget_chars": 128_000,
            "source": "default",
            "note": "token_budget populated by ContextSnapshotPopulator",
        }

        retrieval_trace = {
            "retrieved_at": datetime.now(UTC).isoformat(),
            "space_id": space_id,
            "hard_filter": trace_hard_filter,
            "stages": stage_traces,
            "total_selected": len(final_memories),
            "selected_ids": [m.id for m in final_memories],
            "policy_count": len(active_policies),
            "token_budget": token_budget,
        }

        return RetrievalResult(
            memories=final_memories,
            active_policies=active_policies,
            source_refs=source_refs,
            retrieval_trace=retrieval_trace,
            token_budget=token_budget,
        )

    # ------------------------------------------------------------------
    # Stage implementations
    # ------------------------------------------------------------------

    def _symbol_match(
        self,
        *,
        space_id: str,
        user_id: str,
        workspace_id: str | None,
        agent_id: str | None,
        readable_scopes: set[str],
    ) -> list[MemoryEntry]:
        """
        Find memories that match the run context by structural identity:
        workspace_id, agent_id, subject_user_id, or scope_type membership.
        """
        q = _base_query(self.db, space_id)

        scope_filters = []
        for scope in readable_scopes:
            scope_filters.append(MemoryEntry.scope_type == scope)

        if not scope_filters:
            return []

        q = q.filter(or_(*scope_filters))

        # Narrow by structural identity when available.
        identity_filters = [
            MemoryEntry.subject_user_id == user_id,
            MemoryEntry.owner_user_id == user_id,
        ]
        if workspace_id:
            identity_filters.append(MemoryEntry.workspace_id == workspace_id)
        if agent_id:
            identity_filters.append(MemoryEntry.agent_id == agent_id)

        q = q.filter(or_(*identity_filters))
        return q.order_by(
            MemoryEntry.importance.desc(),
            MemoryEntry.updated_at.desc(),
        ).limit(50).all()

    def _graph_expand(
        self,
        *,
        seed_ids: set[str],
        space_id: str,
        readable_scopes: set[str],
        hard_filter_kwargs: dict,
    ) -> tuple[list[MemoryEntry], int]:
        """
        BFS over MemoryRelation edges starting from seed_ids.
        Returns (new_memory_rows, max_hop_reached).
        Scope boundaries are not crossed (target must also pass hard filter).
        """
        frontier = set(seed_ids)
        all_found: list[MemoryEntry] = []
        hops_done = 0

        for hop in range(1, _MAX_HOPS + 1):
            if not frontier:
                break
            # Find relation edges where source is in the frontier.
            edges = (
                self.db.query(MemoryRelation)
                .filter(
                    MemoryRelation.space_id == space_id,
                    MemoryRelation.source_type == "memory",
                    MemoryRelation.target_type == "memory",
                    MemoryRelation.relation_type.in_(_ALLOWED_RELATION_TYPES),
                    MemoryRelation.source_id.in_(list(frontier)),
                )
                .all()
            )
            candidate_ids = {e.target_id for e in edges} - seed_ids
            if not candidate_ids:
                break

            rows = (
                _base_query(self.db, space_id)
                .filter(MemoryEntry.id.in_(list(candidate_ids)))
                .all()
            )
            # Re-apply hard filter after graph traversal.
            rows = _hard_filter_list(rows, db=self.db, **hard_filter_kwargs)
            # Scope boundary: target must be in readable_scopes.
            rows = [m for m in rows if m.scope_type in readable_scopes]

            new_ids = {m.id for m in rows}
            seed_ids |= new_ids
            frontier = new_ids
            all_found.extend(rows)
            hops_done = hop

        return all_found, hops_done

    def _keyword_fallback(
        self,
        *,
        query: str,
        space_id: str,
        readable_scopes: set[str],
        hard_filter_kwargs: dict,
    ) -> list[MemoryEntry]:
        """Simple ILIKE keyword search over title + content."""
        if not query or not query.strip():
            return []
        q = (
            _base_query(self.db, space_id)
            .filter(
                or_(
                    MemoryEntry.title.ilike(f"%{query}%"),
                    MemoryEntry.content.ilike(f"%{query}%"),
                )
            )
            .order_by(
                MemoryEntry.importance.desc(),
                MemoryEntry.confidence.desc(),
            )
            .limit(20)
        )
        rows = q.all()
        rows = _hard_filter_list(rows, db=self.db, **hard_filter_kwargs)
        return [m for m in rows if m.scope_type in readable_scopes]

    def _embedding_fallback(
        self,
        *,
        query: str | None,
        space_id: str,
        existing_ids: set[str],
        readable_scopes: set[str],
        hard_filter_kwargs: dict,
    ) -> list[MemoryEntry]:
        """
        Embedding fallback interface — delegates to keyword search.
        No vector DB; hard filter is still applied.
        """
        if not query:
            return []
        rows = self._keyword_fallback(
            query=query,
            space_id=space_id,
            readable_scopes=readable_scopes,
            hard_filter_kwargs=hard_filter_kwargs,
        )
        return [m for m in rows if m.id not in existing_ids]

    # ------------------------------------------------------------------
    # Policy loading
    # ------------------------------------------------------------------

    def _load_active_policies(
        self, space_id: str
    ) -> tuple[list[Policy], list[dict]]:
        """Load active (non-disabled, non-superseded) policies for the space."""
        policies = (
            self.db.query(Policy)
            .filter(
                Policy.space_id == space_id,
                Policy.enabled.is_(True),
                Policy.status == "active",
            )
            .order_by(Policy.priority.desc())
            .limit(10)
            .all()
        )
        refs = [_policy_source_ref(p) for p in policies]
        return policies, refs

    # ------------------------------------------------------------------
    # Final ranking
    # ------------------------------------------------------------------

    def _load_and_rank(
        self,
        *,
        ids: list[str],
        space_id: str,
        hard_filter_kwargs: dict,
        max_memories: int,
    ) -> list[MemoryEntry]:
        """Load all collected ids, apply hard filter once more, rank and truncate."""
        if not ids:
            return []
        rows = (
            _base_query(self.db, space_id)
            .filter(MemoryEntry.id.in_(ids))
            .all()
        )
        # Belt-and-suspenders: re-apply hard filter on every row.
        rows = _hard_filter_list(rows, db=self.db, **hard_filter_kwargs)
        # Rank: symbol-match ids first (by importance/confidence), then rest.
        rows.sort(
            key=lambda m: (m.importance or 0.0, m.confidence or 0.0),
            reverse=True,
        )
        return rows[:max_memories]


# ---------------------------------------------------------------------------
# Section assignment
# ---------------------------------------------------------------------------


def _assign_section(m: MemoryEntry) -> str:
    """Assign a memory to stable_prefix or dynamic_tail based on its layer/scope."""
    if m.memory_layer == "episodic":
        return "dynamic_tail"
    scope = m.scope_type or ""
    if scope in ("system", "space"):
        return "stable_prefix"
    if scope in ("workspace", "user", "capability", "agent"):
        return "stable_prefix"
    return "dynamic_tail"
