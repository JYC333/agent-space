from __future__ import annotations
"""
MemoryEvolver — fitness-based memory lifecycle management.

Integration point for the EvoMap evolver mechanism
(https://github.com/EvoMap/evolver). The evolver treats the memory store as a
population and evolves it over time to keep the most useful, accurate, and
relevant memories while retiring stale ones.

Fitness function:
    fitness(m) = importance(m) × confidence(m) × recency_decay(m) × access_factor(m)

    recency_decay(m) = exp(-λ × days_since_last_access)
    access_factor(m) = 0.7 + 0.3 × min(log(1 + access_count) / log(101), 1.0)

Evolution operations:
  - decay     — reduce confidence/importance on low-fitness memories
  - archive   — move memories below threshold to "archived"
  - merge     — consolidate semantically duplicate memories (requires LLM)
  - promote   — raise importance of frequently-accessed memories
  - synthesize — generate higher-level semantic memories from episodic clusters (LLM)

EvoMap integration plan:
  1. Export memories as population to EvoMap format
  2. Run EvoMap fitness evaluation + evolutionary selection
  3. Apply resulting mutations back to MemoryEntry records via MemoryStore
  4. Log each evolution run as a MemoryEvolutionRun record

Current status: STUB — decay/archive work; merge/synthesize pending EvoMap integration.
"""

import math
from datetime import datetime, UTC
from typing import Optional

from sqlalchemy.orm import Session

from ..models import MemoryEntry


# Decay constant per scope — higher λ = faster decay
_DECAY_LAMBDA: dict[str, float] = {
    "system": 0.0,    # system memories never decay
    "agent": 0.2,     # ephemeral per-run state, decays fast
    "user": 0.05,     # default
    "workspace": 0.05,
    "space": 0.02,
    "capability": 0.03,
}

_ARCHIVE_THRESHOLD = 0.05  # fitness below this → archive candidate


def _recency_decay(memory: MemoryEntry, now: Optional[datetime] = None) -> float:
    now = now or datetime.now(UTC)
    reference = memory.last_accessed_at or memory.created_at
    # Normalize both sides to naive UTC — SQLite strips timezone info on round-trip
    now_cmp = now.replace(tzinfo=None) if now.tzinfo else now
    ref_cmp = reference.replace(tzinfo=None) if reference.tzinfo else reference
    days = max(0.0, (now_cmp - ref_cmp).total_seconds() / 86400)
    lam = _DECAY_LAMBDA.get(memory.scope, 0.05)
    return math.exp(-lam * days)


def _fitness(memory: MemoryEntry, now: Optional[datetime] = None) -> float:
    importance = memory.importance or 0.5
    confidence = memory.confidence or 1.0
    recency = _recency_decay(memory, now)
    access_factor = 0.7 + 0.3 * min(
        math.log1p(memory.access_count or 0) / math.log1p(100), 1.0
    )
    return importance * confidence * recency * access_factor


class MemoryEvolver:
    """
    Evolves the memory store for a given space.

    Mutation methods are stubs except for decay/archive which run locally.
    merge and synthesize require EvoMap + LLM and are deferred.
    """

    def __init__(self, db: Session):
        self.db = db

    def compute_fitness_scores(self, space_id: str) -> dict[str, float]:
        """
        Compute and persist fitness scores for all active memories in a space.
        Returns {memory_id: fitness_score}.
        """
        now = datetime.now(UTC)
        memories = (
            self.db.query(MemoryEntry)
            .filter(
                MemoryEntry.space_id == space_id,
                MemoryEntry.status == "active",
                MemoryEntry.deleted_at.is_(None),
            )
            .all()
        )
        scores: dict[str, float] = {}
        for m in memories:
            score = _fitness(m, now)
            scores[m.id] = score
            m.fitness_score = score
        self.db.commit()
        return scores

    def decay_and_archive(self, space_id: str, dry_run: bool = True) -> dict:
        """
        Archive memories below the fitness threshold.
        dry_run=True — report candidates without making changes (safe default).

        System-scope memories are never archived.
        """
        scores = self.compute_fitness_scores(space_id)
        candidates = [mid for mid, score in scores.items() if score < _ARCHIVE_THRESHOLD]

        archived = 0
        if not dry_run and candidates:
            result = (
                self.db.query(MemoryEntry)
                .filter(MemoryEntry.id.in_(candidates), MemoryEntry.scope != "system")
                .update({"status": "archived"}, synchronize_session=False)
            )
            self.db.commit()
            archived = result

        return {
            "space_id": space_id,
            "dry_run": dry_run,
            "evaluated": len(scores),
            "archive_candidates": len(candidates),
            "archived": archived,
        }

    def evolve_space(self, space_id: str) -> dict:
        """
        Full evolution pass for a space. Currently a dry-run stub.

        EvoMap integration steps (TODO):
          1. Export memories as population: [{"id": m.id, "genes": {...}}, ...]
          2. Run EvoMap.evolve(population, fitness_fn=_fitness, generations=N)
          3. Apply mutations (archive/merge/promote/synthesize) via MemoryStore
          4. Write MemoryEvolutionRun record
        """
        result = self.decay_and_archive(space_id, dry_run=True)
        result["merge_candidates"] = 0        # TODO: embedding-based dedup
        result["synthesize_candidates"] = 0   # TODO: episodic cluster → semantic
        result["status"] = "stub — EvoMap integration pending"
        return result
