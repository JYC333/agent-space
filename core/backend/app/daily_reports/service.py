from __future__ import annotations
"""
DailyCaptureReportService — generates a Daily Capture Report for one
space/user/date.

Design constraints (mirror InputSummaryService):
- Never writes Memory or Knowledge directly; all outputs are proposals.
- Creates a real Run (run_type="reflection") before the LLM call.
- Creates an Artifact(artifact_type="daily_capture_report") as primary output.
- If the LLM JSON is invalid, marks Run failed and creates no artifact/proposals.
- Memory/experience proposals are always pending; never applied automatically.
- Idempotent: returns the existing report for the same date/user/space unless
  force=True.
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Sequence
from zoneinfo import ZoneInfo

from pydantic import ValidationError
from sqlalchemy.orm import Session
from ulid import ULID

from ..config import settings
from ..memory.provider_client import (
    ReflectorModelProviderMissingError,
    UnsupportedProviderForReflectorError,
    call_reflector_llm,
    resolve_reflector_provider,
)
from ..memory.proposal_payload import SOURCE_TRUST_VALUES, ProvenanceEntry
from ..memory.proposals import build_memory_create_proposal
from ..models import (
    ActivityRecord,
    Agent,
    AgentVersion,
    Artifact,
    DailyCaptureReportSetting,
    Proposal,
    Run,
)
from ..schemas import DEFAULT_MEMORY_POLICY, DEFAULT_MODEL_CONFIG, DEFAULT_RUNTIME_POLICY
from .schemas import (
    DailyCaptureReportSettingOut,
    StructuredDailyReport,
    validate_timezone_or_raise,
    zoneinfo_for_setting,
)

log = logging.getLogger(__name__)

_SERVICE_VERSION = "1"
_MAX_CONTENT_CHARS = 10_000
_TRUNCATE_SUFFIX = "\n[… truncated]"
_VALID_MEMORY_TYPES = frozenset({"semantic", "episodic", "preference", "procedural", "project"})


def _new_id() -> str:
    return str(ULID())


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + _TRUNCATE_SUFFIX


def _local_day_utc_bounds(local_date: date, timezone: str) -> tuple[datetime, datetime]:
    """Return (start_utc, end_utc) for a local calendar day.

    Raises ValueError for invalid timezone — callers must validate first.
    """
    tz = validate_timezone_or_raise(timezone)
    start_local = datetime(local_date.year, local_date.month, local_date.day, 0, 0, 0, tzinfo=tz)
    end_local = start_local + timedelta(days=1)
    return start_local.astimezone(UTC), end_local.astimezone(UTC)


def _render_markdown(report: StructuredDailyReport, local_date: str) -> str:
    lines = [f"# {report.report_title}", f"*{local_date}*", "", report.overview]
    if report.themes:
        lines += ["", "## Themes"]
        for t in report.themes:
            lines += [f"", f"### {t.title}", t.summary]
    if report.ideas:
        lines += ["", "## Ideas"]
        for i in report.ideas:
            lines += [f"", f"### {i.title}", i.content]
    if report.decisions:
        lines += ["", "## Decisions"]
        for d in report.decisions:
            lines += [f"", f"### {d.title}", d.content]
    if report.open_questions:
        lines += ["", "## Open Questions"]
        for q in report.open_questions:
            lines += [f"", f"**{q.question}**", q.context]
    return "\n".join(lines)


def _ensure_system_agent(db: Session, space_id: str) -> tuple[str, str]:
    _NAME = "daily-capture-reporter"
    existing = (
        db.query(Agent)
        .filter(Agent.space_id == space_id, Agent.name == _NAME)
        .first()
    )
    if existing is not None:
        version_id = existing.current_version_id
        if version_id is None:
            v = db.query(AgentVersion).filter(AgentVersion.agent_id == existing.id).first()
            if v is not None:
                version_id = v.id
                existing.current_version_id = version_id
                db.flush()
        if version_id is not None:
            return existing.id, version_id

    agent_id = _new_id()
    version_id = _new_id()
    agent = Agent(
        id=agent_id,
        space_id=space_id,
        name=_NAME,
        description="System agent for daily capture report generation.",
        status="active",
        current_version_id=version_id,
    )
    version = AgentVersion(
        id=version_id,
        agent_id=agent_id,
        space_id=space_id,
        version_label="v1",
        model_config_json=dict(DEFAULT_MODEL_CONFIG),
        memory_policy_json=dict(DEFAULT_MEMORY_POLICY),
        capabilities_json=[],
        tool_permissions_json={},
        runtime_policy_json=dict(DEFAULT_RUNTIME_POLICY),
    )
    db.add(agent)
    db.add(version)
    db.flush()
    return agent_id, version_id


@dataclass
class DailyReportResult:
    run_id: str
    artifact_id: str | None
    proposal_ids: list[str] = field(default_factory=list)
    experience_proposal_ids: list[str] = field(default_factory=list)
    memory_proposal_ids: list[str] = field(default_factory=list)
    capture_count: int = 0
    status: str = "succeeded"
    summary_preview: str = ""
    skipped: bool = False
    existing_artifact_id: str | None = None


class DailyCaptureReportSettingsService:
    """CRUD for per-user/per-space DailyCaptureReportSetting rows."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def get_or_create(self, space_id: str, user_id: str) -> DailyCaptureReportSetting:
        row = self._get(space_id, user_id)
        if row is None:
            row = DailyCaptureReportSetting(
                id=_new_id(),
                space_id=space_id,
                user_id=user_id,
                include_source_types_json=["user_capture"],
            )
            self._db.add(row)
            self._db.commit()
            self._db.refresh(row)
        return row

    def update(self, space_id: str, user_id: str, data: dict) -> DailyCaptureReportSetting:
        row = self.get_or_create(space_id, user_id)
        if "enabled" in data and data["enabled"] is not None:
            row.enabled = data["enabled"]
        if "local_time" in data and data["local_time"] is not None:
            row.local_time = data["local_time"]
        if "timezone" in data and data["timezone"] is not None:
            row.timezone = data["timezone"]
        if "include_source_types" in data and data["include_source_types"] is not None:
            row.include_source_types_json = data["include_source_types"]
        if "create_experience_proposals" in data and data["create_experience_proposals"] is not None:
            row.create_experience_proposals = data["create_experience_proposals"]
        if "create_memory_proposals" in data and data["create_memory_proposals"] is not None:
            row.create_memory_proposals = data["create_memory_proposals"]
        if "experience_confidence_threshold" in data and data["experience_confidence_threshold"] is not None:
            row.experience_confidence_threshold = data["experience_confidence_threshold"]
        if "memory_confidence_threshold" in data and data["memory_confidence_threshold"] is not None:
            row.memory_confidence_threshold = data["memory_confidence_threshold"]
        if "max_experience_proposals_per_day" in data and data["max_experience_proposals_per_day"] is not None:
            row.max_experience_proposals_per_day = data["max_experience_proposals_per_day"]
        if "max_memory_proposals_per_day" in data and data["max_memory_proposals_per_day"] is not None:
            row.max_memory_proposals_per_day = data["max_memory_proposals_per_day"]
        # Recompute next_run_at when schedule params change
        if any(k in data for k in ("enabled", "local_time", "timezone")):
            row.next_run_at = _compute_next_run_at(row)
        self._db.commit()
        self._db.refresh(row)
        return row

    def to_out(self, row: DailyCaptureReportSetting) -> DailyCaptureReportSettingOut:
        return DailyCaptureReportSettingOut(
            id=row.id,
            space_id=row.space_id,
            user_id=row.user_id,
            enabled=row.enabled,
            local_time=row.local_time,
            timezone=row.timezone,
            include_source_types=list(row.include_source_types_json or ["user_capture"]),
            create_experience_proposals=row.create_experience_proposals,
            create_memory_proposals=row.create_memory_proposals,
            experience_confidence_threshold=row.experience_confidence_threshold,
            memory_confidence_threshold=row.memory_confidence_threshold,
            max_experience_proposals_per_day=row.max_experience_proposals_per_day,
            max_memory_proposals_per_day=row.max_memory_proposals_per_day,
            last_report_date=row.last_report_date,
            next_run_at=row.next_run_at,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    def _get(self, space_id: str, user_id: str) -> DailyCaptureReportSetting | None:
        return (
            self._db.query(DailyCaptureReportSetting)
            .filter(
                DailyCaptureReportSetting.space_id == space_id,
                DailyCaptureReportSetting.user_id == user_id,
            )
            .first()
        )


def _compute_next_run_at(row: DailyCaptureReportSetting) -> datetime | None:
    """Compute the next scheduled run datetime in UTC from local_time + timezone.

    Returns None if disabled or if timezone is invalid (rather than silently using UTC).
    """
    if not row.enabled:
        return None
    tz = zoneinfo_for_setting(row.timezone)
    if tz is None:
        return None
    try:
        h, m = int(row.local_time[:2]), int(row.local_time[3:5])
        now_local = datetime.now(tz)
        today_run = now_local.replace(hour=h, minute=m, second=0, microsecond=0)
        if today_run <= now_local:
            today_run += timedelta(days=1)
        return today_run.astimezone(UTC)
    except Exception:
        return None


class DailyCaptureReportService:
    """Generate a Daily Capture Report for one space/user/date."""

    def __init__(self, db: Session) -> None:
        self._db = db

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def generate_for_date(
        self,
        *,
        space_id: str,
        user_id: str,
        setting: DailyCaptureReportSetting,
        local_date: str,
        trigger_origin: str = "manual",
        force: bool = False,
        create_experience_proposals_override: bool | None = None,
        create_memory_proposals_override: bool | None = None,
    ) -> DailyReportResult:
        # Fail early on invalid timezone — do not silently fall back to UTC
        validate_timezone_or_raise(setting.timezone)

        create_exp = (
            create_experience_proposals_override
            if create_experience_proposals_override is not None
            else setting.create_experience_proposals
        )
        create_mem = (
            create_memory_proposals_override
            if create_memory_proposals_override is not None
            else setting.create_memory_proposals
        )

        # Idempotency: check if report already exists for this date
        if not force:
            existing = self._find_existing_artifact(space_id, user_id, local_date)
            if existing is not None:
                return DailyReportResult(
                    run_id=existing.run_id or "",
                    artifact_id=existing.id,
                    status="skipped",
                    summary_preview="Report already exists for this date.",
                    skipped=True,
                    existing_artifact_id=existing.id,
                )

        # Select captures first — if none, skip without needing a provider
        local_dt = date.fromisoformat(local_date)
        captures = self.select_captures_for_date(
            space_id=space_id,
            user_id=user_id,
            local_date=local_dt,
            timezone=setting.timezone,
            source_types=list(setting.include_source_types_json or ["user_capture"]),
        )
        capture_count = len(captures)
        capture_ids = [c.id for c in captures]

        agent_id, agent_version_id = _ensure_system_agent(self._db, space_id)
        now = datetime.now(UTC)
        prompt = (
            f"Generate Daily Capture Report for {local_date} "
            f"from {capture_count} capture(s)."
        )
        run = Run(
            id=_new_id(),
            space_id=space_id,
            agent_id=agent_id,
            agent_version_id=agent_version_id,
            run_type="reflection",
            trigger_origin=trigger_origin,
            source="managed",
            mode="live",
            status="running",
            instructed_by_user_id=user_id,
            prompt=prompt,
            started_at=now,
        )
        self._db.add(run)
        self._db.flush()

        if capture_count == 0:
            run.status = "succeeded"
            run.ended_at = datetime.now(UTC)
            self._db.commit()
            return DailyReportResult(
                run_id=run.id,
                artifact_id=None,
                capture_count=0,
                status="skipped",
                summary_preview="No user_capture records found for this day.",
                skipped=True,
            )

        # Resolve provider — provider failure creates a failed Run for observability
        try:
            provider_type, base_url, model, api_key = resolve_reflector_provider(
                self._db, settings
            )
        except (ReflectorModelProviderMissingError, UnsupportedProviderForReflectorError) as exc:
            log.warning("daily_report: no provider space=%s date=%s: %s", space_id, local_date, exc)
            run.status = "failed"
            run.error_message = f"Provider unavailable: {exc}"[:1000]
            run.ended_at = datetime.now(UTC)
            self._db.commit()
            return DailyReportResult(
                run_id=run.id,
                artifact_id=None,
                capture_count=capture_count,
                status="failed",
                summary_preview=f"Provider unavailable: {exc}",
            )

        # Build bounded prompt content
        content_blocks = []
        for cap in captures:
            text = (cap.content or "").strip()
            if text:
                label = cap.title or f"Capture {cap.id[:8]}"
                content_blocks.append(f"--- {label} ---\n{text}")
        raw_content = "\n\n".join(content_blocks)
        bounded_content = _truncate(raw_content, _MAX_CONTENT_CHARS)

        system_prompt = (
            "You are a reflective journal assistant. Given user capture records from one day, "
            "generate a structured daily report as valid JSON matching this exact schema:\n\n"
            '{"report_title": "string", "overview": "string", '
            '"themes": [{"title":"","summary":"","source_activity_ids":[]}], '
            '"ideas": [{"title":"","content":"","source_activity_ids":[]}], '
            '"decisions": [{"title":"","content":"","source_activity_ids":[]}], '
            '"open_questions": [{"question":"","context":"","source_activity_ids":[]}], '
            '"experience_candidates": [{"title":"","content":"","confidence":0.0,'
            '"source_activity_ids":[]}], '
            '"memory_candidates": [{"title":"","content":"","memory_type":"semantic",'
            '"confidence":0.0,"source_activity_ids":[]}]}\n\n'
            "Rules:\n"
            "- source_activity_ids must only contain IDs from the provided activity list.\n"
            "- confidence is 0.0–1.0.\n"
            "- memory_type must be one of: semantic, episodic, preference, procedural, project.\n"
            "- Return ONLY the JSON object, no markdown fences, no commentary."
        )
        activity_id_list = "\n".join(f"  - {cid}" for cid in capture_ids)
        user_prompt = (
            f"Date: {local_date}\nActivity IDs:\n{activity_id_list}\n\n"
            f"Captures:\n\n{bounded_content}\n\n"
            "Generate the daily capture report JSON:"
        )

        try:
            raw_json = call_reflector_llm(
                provider_type, base_url, model, api_key, system_prompt, user_prompt
            )
        except Exception as exc:
            log.warning("daily_report: LLM call failed run=%s: %s", run.id, exc)
            run.status = "failed"
            run.error_message = str(exc)[:1000]
            run.ended_at = datetime.now(UTC)
            self._db.commit()
            return DailyReportResult(
                run_id=run.id,
                artifact_id=None,
                capture_count=capture_count,
                status="failed",
                summary_preview=f"Provider call failed: {exc}",
            )

        # Validate structured JSON
        try:
            raw_obj = json.loads(raw_json)
            report = StructuredDailyReport.model_validate(raw_obj)
        except (json.JSONDecodeError, ValidationError) as exc:
            log.warning("daily_report: invalid LLM JSON run=%s: %s", run.id, exc)
            run.status = "failed"
            run.error_message = f"Invalid LLM JSON: {exc}"[:1000]
            run.ended_at = datetime.now(UTC)
            self._db.commit()
            return DailyReportResult(
                run_id=run.id,
                artifact_id=None,
                capture_count=capture_count,
                status="failed",
                summary_preview="Invalid structured report from LLM.",
            )

        # Validate source_activity_ids — drop candidates with empty or unknown IDs
        valid_ids = set(capture_ids)
        report.experience_candidates = [
            c for c in report.experience_candidates
            if c.source_activity_ids  # must be non-empty
            and all(aid in valid_ids for aid in c.source_activity_ids)
        ]
        report.memory_candidates = [
            c for c in report.memory_candidates
            if c.source_activity_ids  # must be non-empty
            and all(aid in valid_ids for aid in c.source_activity_ids)
            and c.memory_type in _VALID_MEMORY_TYPES
        ]

        # Build UTC bounds for artifact
        start_utc, end_utc = _local_day_utc_bounds(local_dt, setting.timezone)

        # Render markdown report
        markdown_content = _render_markdown(report, local_date)

        # Create Artifact
        artifact = Artifact(
            id=_new_id(),
            space_id=space_id,
            run_id=run.id,
            artifact_type="daily_capture_report",
            title=f"Daily Capture Report — {local_date}",
            content=markdown_content,
            mime_type="text/markdown",
            exportable=True,
            preview=False,
            owner_user_id=user_id,
            relevant_period_start=start_utc,
            relevant_period_end=end_utc,
            metadata_json={
                "report_type": "daily_capture_report",
                "report_date": local_date,
                "timezone": setting.timezone,
                "source_activity_ids": capture_ids,
                "capture_count": capture_count,
                "structured_report": report.model_dump(mode="json"),
                "provider_type": provider_type,
                "model": model,
                "service_version": _SERVICE_VERSION,
                "setting_id": setting.id,
            },
        )
        self._db.add(artifact)
        self._db.flush()

        # Create experience proposals
        experience_proposal_ids: list[str] = []
        if create_exp:
            experience_proposal_ids = self._create_experience_proposals(
                space_id=space_id,
                user_id=user_id,
                report=report,
                artifact=artifact,
                run=run,
                captures=captures,
                threshold=setting.experience_confidence_threshold,
                max_count=setting.max_experience_proposals_per_day,
                local_date=local_date,
            )

        # Create memory proposals
        memory_proposal_ids: list[str] = []
        if create_mem:
            memory_proposal_ids = self._create_memory_proposals(
                space_id=space_id,
                user_id=user_id,
                report=report,
                artifact=artifact,
                run=run,
                captures=captures,
                threshold=setting.memory_confidence_threshold,
                max_count=setting.max_memory_proposals_per_day,
                local_date=local_date,
            )

        # Update setting.last_report_date
        setting.last_report_date = local_date
        if setting.enabled:
            setting.next_run_at = _compute_next_run_at(setting)

        run.status = "succeeded"
        run.ended_at = datetime.now(UTC)
        self._db.commit()

        preview = markdown_content[:200].strip()
        if len(markdown_content) > 200:
            preview += "…"

        all_proposal_ids = experience_proposal_ids + memory_proposal_ids
        return DailyReportResult(
            run_id=run.id,
            artifact_id=artifact.id,
            proposal_ids=all_proposal_ids,
            experience_proposal_ids=experience_proposal_ids,
            memory_proposal_ids=memory_proposal_ids,
            capture_count=capture_count,
            status="succeeded",
            summary_preview=preview,
        )

    # ------------------------------------------------------------------
    # Capture selection
    # ------------------------------------------------------------------

    def select_captures_for_date(
        self,
        *,
        space_id: str,
        user_id: str,
        local_date: date,
        timezone: str,
        source_types: Sequence[str] | None = None,
    ) -> list[ActivityRecord]:
        start_utc, end_utc = _local_day_utc_bounds(local_date, timezone)
        allowed_types = list(source_types) if source_types else ["user_capture"]
        from sqlalchemy import or_

        q = (
            self._db.query(ActivityRecord)
            .filter(
                ActivityRecord.space_id == space_id,
                ActivityRecord.source_type.in_(allowed_types),
                ActivityRecord.status != "archived",
                ActivityRecord.occurred_at >= start_utc,
                ActivityRecord.occurred_at < end_utc,
                or_(
                    ActivityRecord.user_id == user_id,
                    ActivityRecord.owner_user_id == user_id,
                ),
            )
            .order_by(ActivityRecord.occurred_at.asc())
            .all()
        )
        return q

    # ------------------------------------------------------------------
    # Idempotency check
    # ------------------------------------------------------------------

    def _find_existing_artifact(
        self, space_id: str, user_id: str, local_date: str
    ) -> Artifact | None:
        rows = (
            self._db.query(Artifact)
            .filter(
                Artifact.space_id == space_id,
                Artifact.artifact_type == "daily_capture_report",
                Artifact.owner_user_id == user_id,
            )
            .all()
        )
        for row in rows:
            meta = row.metadata_json or {}
            if meta.get("report_date") == local_date and meta.get("report_type") == "daily_capture_report":
                return row
        return None

    # ------------------------------------------------------------------
    # Experience proposals (Part 7)
    # ------------------------------------------------------------------

    def _create_experience_proposals(
        self,
        *,
        space_id: str,
        user_id: str,
        report: StructuredDailyReport,
        artifact: Artifact,
        run: Run,
        captures: list[ActivityRecord],
        threshold: float,
        max_count: int,
        local_date: str,
    ) -> list[str]:
        capture_map = {c.id: c for c in captures}
        candidates = [
            c for c in report.experience_candidates
            if c.confidence >= threshold
        ][:max_count]

        proposal_ids = []
        for cand in candidates:
            # Build source_refs for the proposal payload
            source_refs = [
                {"type": "activity", "id": aid, "source_trust": "user_confirmed"}
                for aid in cand.source_activity_ids
                if aid in capture_map
            ]
            payload: dict = {
                "operation": "create",
                "item_type": "experience",
                "title": cand.title,
                "content": cand.content,
                "content_format": "markdown",
                "visibility": "space_shared",
                "owner_user_id": user_id,
                "tags": ["daily-capture-report", local_date],
                "confidence": cand.confidence,
                "source_refs": source_refs,
                "source_artifact_id": artifact.id,
                "source_run_id": run.id,
                "verification_status": "unverified",
                "reflection_status": "unreviewed",
            }
            prop = Proposal(
                id=_new_id(),
                space_id=space_id,
                proposal_type="knowledge_create",
                status="pending",
                risk_level="low",
                urgency="normal",
                title=cand.title,
                rationale=f"Experience candidate from Daily Capture Report {local_date}. Confidence: {cand.confidence:.2f}.",
                created_by_user_id=user_id,
                created_by_run_id=run.id,
                payload_json=payload,
            )
            self._db.add(prop)
            self._db.flush()
            proposal_ids.append(prop.id)

        return proposal_ids

    # ------------------------------------------------------------------
    # Memory proposals (Part 8)
    # ------------------------------------------------------------------

    def _create_memory_proposals(
        self,
        *,
        space_id: str,
        user_id: str,
        report: StructuredDailyReport,
        artifact: Artifact,
        run: Run,
        captures: list[ActivityRecord],
        threshold: float,
        max_count: int,
        local_date: str,
    ) -> list[str]:
        capture_map = {c.id: c for c in captures}
        candidates = [
            c for c in report.memory_candidates
            if c.confidence >= threshold
        ][:max_count]

        proposal_ids = []
        for cand in candidates:
            # Provenance from original user_capture rows only (source_trust=user_confirmed)
            extra_prov = []
            for aid in cand.source_activity_ids:
                if aid in capture_map:
                    entry = ProvenanceEntry(
                        source_type="activity",
                        source_id=aid,
                        source_trust="user_confirmed",
                    )
                    extra_prov.append(entry.to_row_dict())

            prop = build_memory_create_proposal(
                _new_id(),
                space_id,
                user_id,
                workspace_id=None,
                proposed_title=cand.title,
                proposed_content=cand.content,
                rationale=f"Memory candidate from Daily Capture Report {local_date}. Confidence: {cand.confidence:.2f}.",
                memory_type=cand.memory_type,
                target_scope="user",
                target_namespace="user.default",
                source_run_id=None,   # do not let run_step/internal_system upgrade trust
                target_visibility="space_shared",
                risk_level="low",
                owner_user_id=user_id,
                created_by_run_id=run.id,
                extra_provenance_entries=extra_prov,
            )
            # Store artifact/run as metadata, not as trust-bearing provenance
            from sqlalchemy.orm.attributes import flag_modified
            payload = dict(prop.payload_json or {})
            payload.setdefault("source_refs_metadata", {})
            payload["source_refs_metadata"]["daily_report_artifact_id"] = artifact.id
            payload["source_refs_metadata"]["daily_report_run_id"] = run.id
            payload["source_refs_metadata"]["report_date"] = local_date
            prop.payload_json = payload
            flag_modified(prop, "payload_json")
            self._db.add(prop)
            self._db.flush()
            proposal_ids.append(prop.id)

        return proposal_ids
