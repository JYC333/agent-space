"""Helpers for distinguishing real SQLAlchemy mapped classes from stub rows."""

from __future__ import annotations

from sqlalchemy.orm import class_mapper
from sqlalchemy.orm.exc import UnmappedClassError


def is_mapped_class(cls: type) -> bool:
    """Return True if cls is registered with SQLAlchemy's mapper registry."""
    try:
        class_mapper(cls)
        return True
    except UnmappedClassError:
        return False
