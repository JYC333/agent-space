"""Query normalization for space proposal list (GET /proposals)."""

from __future__ import annotations

from fastapi import HTTPException

# Explicit "all" avoids ambiguous omission vs default=pending product semantics.
_PROPOSAL_LIST_STATUSES = frozenset({"pending", "accepted", "rejected"})


def resolve_proposal_list_status(raw: str | None) -> str | None:
    """Return DB status filter: ``None`` means no status filter; default is ``pending``."""
    if raw is None:
        return "pending"
    if raw == "all":
        return None
    if raw not in _PROPOSAL_LIST_STATUSES:
        raise HTTPException(status_code=422, detail=f"Invalid status {raw!r}")
    return raw
