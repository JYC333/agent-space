"""Home API — read-only summary for the Today Command Center."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..auth import get_identity
from ..db import get_db
from .schemas import HomeSummaryOut
from .summary_service import build_home_summary

router = APIRouter(prefix="/home", tags=["home"])


@router.get("/summary", response_model=HomeSummaryOut)
def get_home_summary(
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
    recent_runs_limit: int = Query(10, ge=1, le=20),
    active_runs_limit: int = Query(20, ge=1, le=50),
    pending_preview_limit: int = Query(10, ge=1, le=50),
    recent_artifacts_limit: int = Query(10, ge=1, le=50),
    active_tasks_limit: int = Query(20, ge=1, le=100),
):
    """Aggregate space-scoped dashboard data — bounded reads only, no side effects."""
    space_id, user_id = ids
    return build_home_summary(
        db,
        space_id,
        user_id,
        now=datetime.now(UTC),
        recent_runs_limit=recent_runs_limit,
        active_runs_limit=active_runs_limit,
        pending_preview_limit=pending_preview_limit,
        recent_artifacts_limit=recent_artifacts_limit,
        active_tasks_limit=active_tasks_limit,
    )
