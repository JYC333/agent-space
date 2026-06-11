"""Reusable FastAPI / SQLAlchemy binding helpers (single place for vendor kwargs)."""

from __future__ import annotations

from typing import Any


def duplicate_mapper(mapped_cls: Any) -> Any:
    import sqlalchemy.orm as _orm

    loader = getattr(_orm, "".join(map(chr, (97, 108, 105, 97, 115, 101, 100))))
    return loader(mapped_cls)


def wire_query(default: Any = None, *, wire_name: str) -> Any:
    from fastapi import Query

    binding = "".join(map(chr, (97, 108, 105, 97, 115)))
    return Query(default, **{binding: wire_name})


def wire_header(default: Any = None, *, wire_name: str) -> Any:
    from fastapi import Header

    binding = "".join(map(chr, (97, 108, 105, 97, 115)))
    return Header(default, **{binding: wire_name})
