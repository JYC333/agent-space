"""
Tests for MemoryEvolver — fitness scoring, decay, and archiving.
"""
import math
from datetime import datetime, timedelta, UTC

import pytest
from app.memory.evolver import MemoryEvolver, _fitness, _recency_decay, _ARCHIVE_THRESHOLD
from app.models import MemoryEntry
from tests.conftest import SPACE, USER, ensure_space


def _utcnow() -> datetime:
    """Naive UTC datetime — matches what SQLite returns after a round-trip."""
    return datetime.now(UTC).replace(tzinfo=None)


def _make_memory(db, **kwargs) -> MemoryEntry:
    from ulid import ULID
    vis = kwargs.get("visibility", "private")
    subj = kwargs.get("subject_user_id", kwargs.get("owner_user_id", USER))
    own = kwargs.get("owner_user_id")
    if own is None and vis == "private":
        own = USER
    m = MemoryEntry(
        id=str(ULID()),
        space_id=kwargs.get("space_id", SPACE),
        subject_user_id=subj,
        owner_user_id=own,
        sensitivity_level=kwargs.get("sensitivity_level", "normal"),
        scope=kwargs.get("scope", "user"),
        namespace=kwargs.get("namespace", "user.default"),
        type=kwargs.get("type", "semantic"),
        title=kwargs.get("title", "Test memory"),
        content=kwargs.get("content", "Some content."),
        status=kwargs.get("status", "active"),
        visibility=kwargs.get("visibility", "private"),
        importance=kwargs.get("importance", 0.5),
        confidence=kwargs.get("confidence", 1.0),
        access_count=kwargs.get("access_count", 0),
        created_by=USER,
        # Use naive datetimes — SQLite strips tz info on round-trip
        created_at=kwargs.get("created_at", _utcnow()),
        last_accessed_at=kwargs.get("last_accessed_at", None),
    )
    db.add(m)
    db.commit()
    return m


# ---------------------------------------------------------------------------
# _recency_decay
# ---------------------------------------------------------------------------

def test_recency_decay_fresh_memory():
    # Use naive datetimes for in-process tests — _recency_decay uses datetime.now(UTC)
    # which is aware; pass an explicit now= to avoid tz comparison issues
    m = MemoryEntry(scope="user", confidence=1.0, importance=0.5, access_count=0,
               created_at=_utcnow(), last_accessed_at=None)
    now = datetime.now(UTC).replace(tzinfo=None)
    decay = _recency_decay(m, now)
    assert decay > 0.99  # just created, nearly no decay


def test_recency_decay_aged_memory():
    aged = _utcnow() - timedelta(days=365)
    m = MemoryEntry(scope="user", confidence=1.0, importance=0.5, access_count=0,
               created_at=aged, last_accessed_at=None)
    decay = _recency_decay(m, _utcnow())
    assert decay < 0.01  # far in the past, nearly zero


def test_recency_decay_system_scope_never_decays():
    aged = _utcnow() - timedelta(days=3650)
    m = MemoryEntry(scope="system", confidence=1.0, importance=0.5, access_count=0,
               created_at=aged, last_accessed_at=None)
    decay = _recency_decay(m, _utcnow())
    assert decay == pytest.approx(1.0)  # lambda=0 → no decay ever


def test_recency_decay_uses_last_accessed_if_set():
    old_created = _utcnow() - timedelta(days=365)
    recent_accessed = _utcnow() - timedelta(hours=1)
    m = MemoryEntry(scope="user", confidence=1.0, importance=0.5, access_count=5,
               created_at=old_created, last_accessed_at=recent_accessed)
    decay = _recency_decay(m, _utcnow())
    assert decay > 0.99  # accessed recently, nearly no decay


# ---------------------------------------------------------------------------
# _fitness
# ---------------------------------------------------------------------------

def test_fitness_fresh_important_memory_is_high():
    m = MemoryEntry(scope="user", importance=1.0, confidence=1.0, access_count=10,
               created_at=_utcnow(), last_accessed_at=None)
    score = _fitness(m, _utcnow())
    assert score > 0.8


def test_fitness_stale_unaccessed_memory_is_low():
    aged = _utcnow() - timedelta(days=500)
    m = MemoryEntry(scope="user", importance=0.5, confidence=0.5, access_count=0,
               created_at=aged, last_accessed_at=None)
    score = _fitness(m, _utcnow())
    assert score < _ARCHIVE_THRESHOLD


def test_fitness_zero_importance_treated_as_default():
    # The formula uses `importance or 0.5` — Python treats 0.0 as falsy,
    # so zero importance falls back to 0.5. This is intentional: a memory
    # with no explicit importance is given a neutral score, not silenced.
    m = MemoryEntry(scope="user", importance=0.0, confidence=1.0, access_count=0,
               created_at=_utcnow(), last_accessed_at=None)
    score = _fitness(m, _utcnow())
    assert score > 0.3  # 0.5 * 1.0 * ~1.0 * 0.7 ≈ 0.35


# ---------------------------------------------------------------------------
# MemoryEvolver.compute_fitness_scores
# ---------------------------------------------------------------------------

def test_compute_fitness_scores_returns_all_active(db):
    _make_memory(db, title="A", importance=0.9)
    _make_memory(db, title="B", importance=0.1)
    _make_memory(db, title="C", status="archived")  # should be excluded

    evolver = MemoryEvolver(db)
    scores = evolver.compute_fitness_scores(SPACE)
    assert len(scores) == 2  # only active
    for score in scores.values():
        assert 0.0 <= score <= 1.0


def test_compute_fitness_scores_persists_to_db(db):
    m = _make_memory(db, title="Persist test")
    evolver = MemoryEvolver(db)
    evolver.compute_fitness_scores(SPACE)
    db.refresh(m)
    assert m.fitness_score is not None


def test_compute_fitness_scores_space_isolation(db):
    ensure_space(db, "space_a")
    ensure_space(db, "space_b")
    _make_memory(db, space_id="space_a", title="A")
    _make_memory(db, space_id="space_b", title="B")

    evolver = MemoryEvolver(db)
    scores_a = evolver.compute_fitness_scores("space_a")
    assert len(scores_a) == 1


# ---------------------------------------------------------------------------
# MemoryEvolver.decay_and_archive
# ---------------------------------------------------------------------------

def test_decay_and_archive_dry_run_does_not_change_status(db):
    aged = _utcnow() - timedelta(days=500)
    m = _make_memory(db, title="Aged memory", importance=0.01, confidence=0.1, created_at=aged)

    evolver = MemoryEvolver(db)
    result = evolver.decay_and_archive(SPACE, dry_run=True)

    db.refresh(m)
    assert m.status == "active"  # not changed in dry_run
    assert result["dry_run"] is True
    assert result["archived"] == 0
    assert result["archive_candidates"] >= 1


def test_decay_and_archive_live_run_archives_low_fitness(db):
    aged = _utcnow() - timedelta(days=500)
    m = _make_memory(db, title="Stale", importance=0.01, confidence=0.05, created_at=aged)

    evolver = MemoryEvolver(db)
    result = evolver.decay_and_archive(SPACE, dry_run=False)

    db.refresh(m)
    assert m.status == "archived"
    assert result["archived"] >= 1
    assert result["dry_run"] is False


def test_decay_and_archive_keeps_high_fitness_memories(db):
    m = _make_memory(db, title="Important", importance=1.0, confidence=1.0)

    evolver = MemoryEvolver(db)
    evolver.decay_and_archive(SPACE, dry_run=False)

    db.refresh(m)
    assert m.status == "active"


def test_decay_and_archive_never_archives_system_scope(db):
    aged = _utcnow() - timedelta(days=500)
    m = _make_memory(db, scope="system", subject_user_id=None, title="System rule", importance=0.01,
                     confidence=0.01, created_at=aged)

    evolver = MemoryEvolver(db)
    evolver.decay_and_archive(SPACE, dry_run=False)

    db.refresh(m)
    assert m.status == "active"


# ---------------------------------------------------------------------------
# MemoryEvolver.evolve_space
# ---------------------------------------------------------------------------

def test_evolve_space_returns_stub_status(db):
    result = MemoryEvolver(db).evolve_space(SPACE)
    assert "status" in result
    assert "stub" in result["status"].lower()
    assert result["dry_run"] is True
    assert "merge_candidates" in result
    assert "synthesize_candidates" in result
