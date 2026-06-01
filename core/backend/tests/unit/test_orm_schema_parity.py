"""Strict ORM ↔ migrated PostgreSQL schema parity.

PostgreSQL is the server database and Alembic owns the schema. These
tests fail if the SQLAlchemy ORM and the *migrated* Postgres schema drift apart:

  - Every mapped ORM column must exist as a physical column in the live schema.
    This catches any column declared in the ORM but absent from the canonical
    migration.
  - Every ORM column declared with ``index=True`` must be backed by a real index
    in the migrated schema (single-column index, matching SQLAlchemy semantics).

Foreign-key semantics are covered by ``test_postgres_ddl_semantics``. These
tests stay focused on physical columns and indexes, and run against the
committed Testcontainers PostgreSQL engine (``db_engine``).
"""
from __future__ import annotations

from sqlalchemy import inspect as sa_inspect

from app.db import Base


def _live_columns(inspector, table_name: str) -> set[str]:
    try:
        return {c["name"] for c in inspector.get_columns(table_name)}
    except Exception:
        return set()


def test_every_orm_column_exists_in_migrated_schema(db_engine):
    """No mapped ORM column may be missing from the migrated PostgreSQL schema."""
    inspector = sa_inspect(db_engine)
    live_tables = set(inspector.get_table_names())

    missing: list[str] = []
    for table in Base.metadata.sorted_tables:
        if table.name not in live_tables:
            missing.append(f"{table.name} (entire table missing from migrated schema)")
            continue
        live_cols = _live_columns(inspector, table.name)
        for col in table.columns:
            if col.name not in live_cols:
                missing.append(f"{table.name}.{col.name}")

    assert not missing, (
        "ORM columns missing from the migrated PostgreSQL schema "
        "(add them to the canonical migration):\n  " + "\n  ".join(sorted(missing))
    )


def test_explicitly_indexed_orm_columns_have_live_indexes(db_engine):
    """Every ORM column with index=True must have a matching index in the schema.

    SQLAlchemy emits a single-column index for ``index=True``. We accept the
    column being covered either by its own single-column index or as the leading
    column of a composite index, which is what an index on that column provides
    in practice.
    """
    inspector = sa_inspect(db_engine)
    live_tables = set(inspector.get_table_names())

    offenders: list[str] = []
    for table in Base.metadata.sorted_tables:
        if table.name not in live_tables:
            continue
        live_indexes = inspector.get_indexes(table.name)
        single_col = {tuple(ix["column_names"]) for ix in live_indexes}
        leading_cols = {
            ix["column_names"][0]
            for ix in live_indexes
            if ix.get("column_names")
        }
        # Unique constraints also create a backing index on their columns.
        for uc in inspector.get_unique_constraints(table.name):
            cols = uc.get("column_names") or []
            if cols:
                leading_cols.add(cols[0])
                single_col.add(tuple(cols))
        # Primary key columns are indexed implicitly.
        pk_cols = set(inspector.get_pk_constraint(table.name).get("constrained_columns") or [])

        for col in table.columns:
            if not col.index:
                continue
            if (col.name,) in single_col or col.name in leading_cols or col.name in pk_cols:
                continue
            offenders.append(f"{table.name}.{col.name}")

    assert not offenders, (
        "ORM columns declared index=True but not indexed in the migrated schema "
        "(add the index to the canonical migration):\n  " + "\n  ".join(sorted(offenders))
    )


def test_activity_records_and_artifacts_project_id_parity(db_engine):
    """Regression guard for the known mismatch: project_id on activity_records/artifacts.

    These soft-reference columns existed in the ORM but were absent from the
    canonical migration. They must be present as physical, indexed columns.
    """
    inspector = sa_inspect(db_engine)
    for table in ("activity_records", "artifacts"):
        cols = _live_columns(inspector, table)
        assert "project_id" in cols, f"{table}.project_id missing from migrated schema"
        indexed = {tuple(ix["column_names"]) for ix in inspector.get_indexes(table)}
        assert ("project_id",) in indexed, f"ix_{table}_project_id missing from migrated schema"
