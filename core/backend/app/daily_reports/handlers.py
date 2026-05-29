from __future__ import annotations
"""
Job handler for daily_capture_report jobs.

Payload schema:
  {
    "space_id": "...",
    "user_id": "...",
    "setting_id": "...",
    "local_date": "YYYY-MM-DD",
    "timezone": "...",
    "trigger_origin": "automation|manual",
    "force": false
  }
"""

import logging

from ..jobs.handlers import register_handler

log = logging.getLogger(__name__)


@register_handler("daily_capture_report")
def handle_daily_capture_report(job) -> dict | None:
    """Handle a scheduled or manual daily_capture_report job.

    Retry policy (max_attempts=1, set at enqueue time by the scheduler):
    Product-level failures — provider missing, invalid LLM JSON, etc. — are
    recorded on the Run row and the handler returns normally. The queue marks
    the job completed, not failed/retryable. Queue retry is unnecessary: if the
    enqueue itself failed, next_run_at was not advanced, so the scheduler
    naturally retries the slot on the next scan.
    """
    from ..db import SessionLocal
    from ..models import DailyCaptureReportSetting
    from .service import DailyCaptureReportService

    payload = job.payload or {}
    space_id = payload.get("space_id") or job.space_id
    user_id = payload.get("user_id") or job.user_id
    setting_id = payload.get("setting_id")
    local_date = payload.get("local_date")
    timezone = payload.get("timezone", "UTC")
    trigger_origin = payload.get("trigger_origin", "automation")
    force = bool(payload.get("force", False))

    if not space_id:
        raise ValueError("daily_capture_report handler: missing space_id")
    if not user_id:
        raise ValueError("daily_capture_report handler: missing user_id")
    if not local_date:
        raise ValueError("daily_capture_report handler: missing local_date")

    db = SessionLocal()
    try:
        setting = None
        if setting_id:
            setting = (
                db.query(DailyCaptureReportSetting)
                .filter(
                    DailyCaptureReportSetting.id == setting_id,
                    DailyCaptureReportSetting.space_id == space_id,
                )
                .first()
            )
        if setting is None:
            from .service import DailyCaptureReportSettingsService
            setting = DailyCaptureReportSettingsService(db).get_or_create(space_id, user_id)

        svc = DailyCaptureReportService(db)
        result = svc.generate_for_date(
            space_id=space_id,
            user_id=user_id,
            setting=setting,
            local_date=local_date,
            trigger_origin=trigger_origin,
            force=force,
        )
        log.info(
            "daily_capture_report: done space=%s user=%s date=%s status=%s captures=%d",
            space_id, user_id, local_date, result.status, result.capture_count,
        )
        return {
            "run_id": result.run_id,
            "artifact_id": result.artifact_id,
            "proposal_ids": result.proposal_ids,
            "experience_proposal_ids": result.experience_proposal_ids,
            "memory_proposal_ids": result.memory_proposal_ids,
            "capture_count": result.capture_count,
            "status": result.status,
        }
    finally:
        db.close()
