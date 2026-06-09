"""ORM metadata and live-schema tests for the Cards persistence layer.

Covers: Card / CardReviewState / CardReview
  - check constraints are registered in ORM metadata
  - relationships exist and point the right direction
  - UniqueConstraint on (card_id, user_id) in card_review_states
  - source_id is nullable (no FK; allowlisted as polymorphic)
  - live migrated schema has the three tables with correct columns and constraints
"""
from __future__ import annotations

import pytest
from sqlalchemy import CheckConstraint, UniqueConstraint, inspect as sa_inspect, text

from app.db import Base
from app.models import Card, CardReview, CardReviewState


# ---------------------------------------------------------------------------
# ORM metadata helpers (no DB required)
# ---------------------------------------------------------------------------

def _constraint_names(table) -> set[str]:
    return {c.name for c in table.constraints if c.name}


def _check_sqls(table) -> set[str]:
    return {str(c.sqltext) for c in table.constraints if isinstance(c, CheckConstraint)}


def _unique_column_sets(table) -> list[frozenset[str]]:
    return [
        frozenset(c.columns.keys())
        for c in table.constraints
        if isinstance(c, UniqueConstraint)
    ]


# ---------------------------------------------------------------------------
# Card ORM metadata
# ---------------------------------------------------------------------------

class TestCardOrmMetadata:
    def test_table_name(self):
        assert Card.__tablename__ == "cards"

    def test_card_type_check_constraint_registered(self):
        sqls = _check_sqls(Card.__table__)
        assert any("'basic'" in s and "'cloze'" in s for s in sqls)

    def test_status_check_constraint_registered(self):
        sqls = _check_sqls(Card.__table__)
        assert any("'draft'" in s and "'suspended'" in s for s in sqls)

    def test_source_type_check_constraint_registered(self):
        sqls = _check_sqls(Card.__table__)
        assert any("'note'" in s and "'knowledge_item'" in s for s in sqls)

    def test_source_id_is_nullable_no_fk(self):
        col = Card.__table__.c["source_id"]
        assert col.nullable is True
        assert not col.foreign_keys

    def test_source_type_is_nullable(self):
        col = Card.__table__.c["source_type"]
        assert col.nullable is True

    def test_metadata_json_is_nullable(self):
        col = Card.__table__.c["metadata_json"]
        assert col.nullable is True

    def test_has_review_states_relationship(self):
        assert hasattr(Card, "review_states")

    def test_has_reviews_relationship(self):
        assert hasattr(Card, "reviews")

    def test_space_id_has_fk_to_spaces(self):
        col = Card.__table__.c["space_id"]
        targets = {fk.column.table.name for fk in col.foreign_keys}
        assert "spaces" in targets


# ---------------------------------------------------------------------------
# CardReviewState ORM metadata
# ---------------------------------------------------------------------------

class TestCardReviewStateOrmMetadata:
    def test_table_name(self):
        assert CardReviewState.__tablename__ == "card_review_states"

    def test_state_check_constraint_registered(self):
        sqls = _check_sqls(CardReviewState.__table__)
        assert any("'new'" in s and "'relearning'" in s for s in sqls)

    def test_unique_constraint_card_user(self):
        sets = _unique_column_sets(CardReviewState.__table__)
        assert frozenset({"card_id", "user_id"}) in sets

    def test_card_id_has_fk_to_cards(self):
        col = CardReviewState.__table__.c["card_id"]
        targets = {fk.column.table.name for fk in col.foreign_keys}
        assert "cards" in targets

    def test_user_id_has_fk_to_users(self):
        col = CardReviewState.__table__.c["user_id"]
        targets = {fk.column.table.name for fk in col.foreign_keys}
        assert "users" in targets

    def test_fsrs_fields_are_nullable(self):
        for field in ("stability", "difficulty", "elapsed_days", "scheduled_days", "state"):
            col = CardReviewState.__table__.c[field]
            assert col.nullable is True, f"{field} must be nullable"

    def test_reps_lapses_default_zero(self):
        for field in ("reps", "lapses"):
            col = CardReviewState.__table__.c[field]
            assert col.default.arg == 0

    def test_has_card_relationship(self):
        assert hasattr(CardReviewState, "card")


# ---------------------------------------------------------------------------
# CardReview ORM metadata
# ---------------------------------------------------------------------------

class TestCardReviewOrmMetadata:
    def test_table_name(self):
        assert CardReview.__tablename__ == "card_reviews"

    def test_rating_check_constraint_registered(self):
        sqls = _check_sqls(CardReview.__table__)
        assert any("'again'" in s and "'easy'" in s for s in sqls)

    def test_card_id_has_fk_to_cards(self):
        col = CardReview.__table__.c["card_id"]
        targets = {fk.column.table.name for fk in col.foreign_keys}
        assert "cards" in targets

    def test_user_id_has_fk_to_users(self):
        col = CardReview.__table__.c["user_id"]
        targets = {fk.column.table.name for fk in col.foreign_keys}
        assert "users" in targets

    def test_review_state_snapshot_nullable_jsonb(self):
        col = CardReview.__table__.c["review_state_snapshot_json"]
        assert col.nullable is True

    def test_duration_ms_is_nullable(self):
        col = CardReview.__table__.c["duration_ms"]
        assert col.nullable is True

    def test_has_card_relationship(self):
        assert hasattr(CardReview, "card")

    def test_no_updated_at_column(self):
        """CardReview is append-only — no updated_at."""
        assert "updated_at" not in CardReview.__table__.c


# ---------------------------------------------------------------------------
# Live migrated schema checks (require PostgreSQL testcontainer)
# ---------------------------------------------------------------------------

def test_cards_tables_present_in_migrated_schema(db_engine):
    inspector = sa_inspect(db_engine)
    tables = set(inspector.get_table_names())
    assert {"cards", "card_review_states", "card_reviews"}.issubset(tables)


def test_cards_check_constraints_in_live_schema(db_engine):
    with db_engine.connect() as conn:
        for table, expected_fragment in [
            ("cards", "basic"),
            ("cards", "suspended"),
            ("card_review_states", "relearning"),
            ("card_reviews", "again"),
        ]:
            rows = conn.execute(text("""
                SELECT pg_get_constraintdef(oid)
                FROM pg_constraint
                WHERE conrelid = CAST(:t AS regclass) AND contype = 'c'
            """), {"t": table}).fetchall()
            defs = " ".join(r[0] for r in rows)
            assert expected_fragment in defs, (
                f"Expected '{expected_fragment}' in {table} check constraints, got: {defs}"
            )


def test_card_review_states_unique_constraint_in_live_schema(db_engine):
    with db_engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT pg_get_constraintdef(oid)
            FROM pg_constraint
            WHERE conrelid = CAST('card_review_states' AS regclass)
              AND contype = 'u'
        """)).fetchall()
    defs = " ".join(r[0] for r in rows)
    assert "card_id" in defs and "user_id" in defs, (
        f"Expected unique(card_id, user_id) in card_review_states, got: {defs}"
    )


def test_cards_composite_source_index_exists(db_engine):
    with db_engine.connect() as conn:
        row = conn.execute(text("""
            SELECT indexdef FROM pg_indexes
            WHERE schemaname = 'public' AND indexname = 'ix_cards_source'
        """)).fetchone()
    assert row is not None, "Expected composite index ix_cards_source on cards"
    assert "source_type" in row[0] and "source_id" in row[0]


def test_card_review_states_user_due_index_exists(db_engine):
    with db_engine.connect() as conn:
        row = conn.execute(text("""
            SELECT indexdef FROM pg_indexes
            WHERE schemaname = 'public' AND indexname = 'ix_card_review_states_user_due'
        """)).fetchone()
    assert row is not None, "Expected composite index ix_card_review_states_user_due"
    assert "user_id" in row[0] and "due_at" in row[0]


def test_card_reviews_user_reviewed_at_index_exists(db_engine):
    with db_engine.connect() as conn:
        row = conn.execute(text("""
            SELECT indexdef FROM pg_indexes
            WHERE schemaname = 'public' AND indexname = 'ix_card_reviews_user_reviewed_at'
        """)).fetchone()
    assert row is not None, "Expected composite index ix_card_reviews_user_reviewed_at"
    assert "user_id" in row[0] and "reviewed_at" in row[0]
