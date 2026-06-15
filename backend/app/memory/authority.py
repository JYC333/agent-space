"""Authority guard for Stage 6 memory slices.

When ``CONTROL_PLANE_MEMORY_AUTHORITY=ts`` the TypeScript control plane owns the
public memory read routes (slice 5) and public memory proposal-create routes
(slice 6). Python's moved handlers fail closed so there is exactly one command
authority. When ``CONTROL_PLANE_MEMORY_APPLY_AUTHORITY=ts`` the TypeScript
control plane also owns accepted ``memory_create``/``memory_update``/
``memory_archive`` proposal apply. Quality/evolution routes remain Python-owned
until their later slices move.
"""

from __future__ import annotations

import os

from fastapi import HTTPException


def memory_read_owned_by_ts() -> bool:
    return (
        os.getenv("CONTROL_PLANE_MEMORY_AUTHORITY", "python").strip().lower() == "ts"
    )


def memory_proposal_create_owned_by_ts() -> bool:
    return memory_read_owned_by_ts()


def memory_apply_owned_by_ts() -> bool:
    """Stage 6 slice 7b: TS applies accepted memory_create/update/archive proposals."""
    return (
        os.getenv("CONTROL_PLANE_MEMORY_APPLY_AUTHORITY", "python").strip().lower()
        == "ts"
    )


_TS_APPLIED_MEMORY_TYPES = frozenset(
    {"memory_create", "memory_update", "memory_archive"}
)


def memory_proposal_apply_owned_by_ts(proposal_type: str) -> bool:
    return memory_apply_owned_by_ts() and proposal_type in _TS_APPLIED_MEMORY_TYPES


def reject_python_memory_read_when_ts_authority() -> None:
    if not memory_read_owned_by_ts():
        return
    raise HTTPException(
        status_code=410,
        detail=(
            "Python no longer owns memory reads; the TypeScript control plane "
            "serves /memory list/get/search."
        ),
    )


def reject_python_memory_proposal_create_when_ts_authority() -> None:
    if not memory_proposal_create_owned_by_ts():
        return
    raise HTTPException(
        status_code=410,
        detail=(
            "Python no longer owns public memory proposal creation; the "
            "TypeScript control plane serves POST/PATCH/DELETE /memory."
        ),
    )
