from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, model_validator
from sqlalchemy.orm import Session

from ..db import get_db
from ..schemas import ContextBuildRequest, ContextPackage
from ..auth.api_key import get_identity
from .context_builder import ContextBuilder
from .digest_refresh import ContextDigestRefreshService

router = APIRouter(prefix="/context", tags=["context"])


# Memory follow-up: optionally extend ContextBuildRequest + this handler to pass
# run_id and context_reason into ContextBuilder.build when product needs them.


@router.post("/build", response_model=ContextPackage)
def build_context(
    req: ContextBuildRequest,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, user_id = ids
    builder = ContextBuilder(db)
    return builder.build(
        space_id=space_id,
        user_id=user_id,
        workspace_id=req.workspace_id,
        task_type=req.task_type,
        capability_id=req.capability_id,
        session_id=req.session_id,
        query=req.query,
    )


# ---------------------------------------------------------------------------
# Digest refresh
# ---------------------------------------------------------------------------

_KNOWN_DIGEST_TYPES = frozenset({"policy_bundle", "workspace", "agent"})


class DigestRefreshRequest(BaseModel):
    """
    Refresh a specific dirty digest, or all dirty digests for the space.

    Valid forms:
    - Empty object ``{}`` — refresh all dirty digests in the caller's space.
    - Specific refresh: ``scope_type`` + ``digest_type`` required.
      - ``digest_type="workspace"`` or ``"agent"`` → ``scope_id`` required.
      - ``digest_type="policy_bundle"`` + ``scope_type="space"`` → ``scope_id`` may be null.

    Extra fields are rejected (returns 422).
    """

    model_config = ConfigDict(extra="forbid")

    scope_type: Optional[str] = None
    scope_id: Optional[str] = None
    digest_type: Optional[str] = None

    @model_validator(mode="after")
    def _validate_specific_refresh(self) -> "DigestRefreshRequest":
        has_type = self.digest_type is not None
        has_scope = self.scope_type is not None

        # If either is provided, both must be provided together.
        if has_type != has_scope:
            raise ValueError(
                "Both scope_type and digest_type must be provided together, "
                "or both must be omitted (to refresh all dirty digests)."
            )

        if has_type:
            if self.digest_type not in _KNOWN_DIGEST_TYPES:
                raise ValueError(
                    f"Unknown digest_type {self.digest_type!r}. "
                    f"Must be one of: {sorted(_KNOWN_DIGEST_TYPES)}"
                )
            # workspace and agent digests require a scope_id.
            if self.digest_type in ("workspace", "agent") and not self.scope_id:
                raise ValueError(
                    f"scope_id is required when digest_type={self.digest_type!r}."
                )
            # policy_bundle at space scope may omit scope_id.
            # No additional check needed here.

        return self


class DigestRefreshResponse(BaseModel):
    refreshed_ids: list[str]
    dirty_remaining: int


@router.post("/digests/refresh", response_model=DigestRefreshResponse)
def refresh_digests(
    req: DigestRefreshRequest = DigestRefreshRequest(),
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """
    Explicitly refresh dirty ContextDigest rows.

    Digests are never auto-regenerated when marked dirty. This endpoint is the
    explicit call site for regeneration — call it after approving proposals that
    affect workspace or policy content.

    Never writes MemoryEntry, Proposal, or Policy.
    """
    space_id, _user_id = ids
    svc = ContextDigestRefreshService(db)

    if req.scope_type and req.digest_type:
        # Refresh one specific digest
        try:
            digest = svc.refresh(space_id, req.scope_type, req.scope_id, req.digest_type)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        db.commit()
        remaining = svc.get_dirty_count(space_id)
        return DigestRefreshResponse(refreshed_ids=[digest.id], dirty_remaining=remaining)
    else:
        # Refresh all dirty digests
        digests = svc.refresh_all_dirty(space_id)
        db.commit()
        remaining = svc.get_dirty_count(space_id)
        return DigestRefreshResponse(
            refreshed_ids=[d.id for d in digests],
            dirty_remaining=remaining,
        )
