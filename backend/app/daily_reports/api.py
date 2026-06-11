from __future__ import annotations
"""
Daily Capture Report API

Routes:
  GET  /daily-capture-report/settings          — get settings for current user/space
  PUT  /daily-capture-report/settings          — upsert settings for current user/space
  POST /daily-capture-report/run               — trigger manual run
  GET  /daily-capture-report/reports           — list recent report artifacts
"""

from datetime import UTC, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..auth import get_identity
from ..db import get_db
from .schemas import (
    DailyCaptureReportSettingOut,
    DailyCaptureReportSettingUpdate,
    DailyReportArtifactItemOut,
    DailyReportRunRequest,
    DailyReportRunResponse,
)
from .service import DailyCaptureReportService, DailyCaptureReportSettingsService

router = APIRouter(prefix="/daily-capture-report", tags=["daily-capture-report"])


@router.get("/settings", response_model=DailyCaptureReportSettingOut)
def get_settings(
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
) -> DailyCaptureReportSettingOut:
    space_id, user_id = ids
    svc = DailyCaptureReportSettingsService(db)
    row = svc.get_or_create(space_id, user_id)
    return svc.to_out(row)


@router.put("/settings", response_model=DailyCaptureReportSettingOut)
@router.patch("/settings", response_model=DailyCaptureReportSettingOut)
def update_settings(
    body: DailyCaptureReportSettingUpdate,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
) -> DailyCaptureReportSettingOut:
    space_id, user_id = ids
    svc = DailyCaptureReportSettingsService(db)
    try:
        row = svc.update(space_id, user_id, body.model_dump(exclude_none=True))
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return svc.to_out(row)


@router.post("/run", response_model=DailyReportRunResponse, status_code=201)
def trigger_manual_run(
    body: DailyReportRunRequest,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
) -> DailyReportRunResponse:
    space_id, user_id = ids
    settings_svc = DailyCaptureReportSettingsService(db)
    setting = settings_svc.get_or_create(space_id, user_id)

    # Resolve local_date
    if body.local_date:
        local_date = body.local_date
    else:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
        try:
            tz = ZoneInfo(setting.timezone)
        except (ZoneInfoNotFoundError, Exception):
            tz = ZoneInfo("UTC")
        local_date = datetime.now(tz).strftime("%Y-%m-%d")

    svc = DailyCaptureReportService(db)
    result = svc.generate_for_date(
        space_id=space_id,
        user_id=user_id,
        setting=setting,
        local_date=local_date,
        trigger_origin="manual",
        force=body.force,
        create_experience_proposals_override=body.create_experience_proposals,
        create_memory_proposals_override=body.create_memory_proposals,
    )

    return DailyReportRunResponse(
        run_id=result.run_id,
        artifact_id=result.artifact_id or result.existing_artifact_id,
        proposal_ids=result.proposal_ids,
        experience_proposal_ids=result.experience_proposal_ids,
        memory_proposal_ids=result.memory_proposal_ids,
        capture_count=result.capture_count,
        status=result.status,
        summary_preview=result.summary_preview,
    )


@router.get("/reports", response_model=list[DailyReportArtifactItemOut])
def list_reports(
    limit: int = Query(default=10, le=50),
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
) -> list[DailyReportArtifactItemOut]:
    """List recent daily_capture_report artifacts for the current user."""
    from ..models import Artifact

    space_id, user_id = ids
    rows = (
        db.query(Artifact)
        .filter(
            Artifact.space_id == space_id,
            Artifact.artifact_type == "daily_capture_report",
            Artifact.owner_user_id == user_id,
        )
        .order_by(Artifact.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        DailyReportArtifactItemOut(
            id=r.id,
            title=r.title,
            artifact_type=r.artifact_type,
            run_id=r.run_id,
            created_at=r.created_at.isoformat(),
            report_date=(r.metadata_json or {}).get("report_date"),
            capture_count=(r.metadata_json or {}).get("capture_count", 0),
        )
        for r in rows
    ]
