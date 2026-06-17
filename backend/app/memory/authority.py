"""Authority guards for memory routes.

The TypeScript control plane owns public memory reads, public memory
proposal-create routes, and accepted ``memory_create``/``memory_update``/
``memory_archive`` proposal apply. Python's moved handlers fail closed so there
is exactly one command authority. Quality/evolution routes remain Python-owned
until their later slices move.
"""

from __future__ import annotations

from fastapi import HTTPException


def memory_read_owned_by_ts() -> bool:
    return True


def memory_proposal_create_owned_by_ts() -> bool:
    return memory_read_owned_by_ts()


def memory_apply_owned_by_ts() -> bool:
    """TS applies accepted memory_create/update/archive proposals."""
    return True


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
