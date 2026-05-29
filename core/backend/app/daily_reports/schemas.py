from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator

_VALID_SOURCE_TYPES = frozenset({"user_capture"})


def _validate_local_time(v: str | None) -> str | None:
    if v is None:
        return v
    import re
    if not re.fullmatch(r"\d{2}:\d{2}", v):
        raise ValueError("local_time must be HH:MM (e.g. 08:30)")
    h, m = int(v[:2]), int(v[3:5])
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError("local_time hour must be 00–23 and minute must be 00–59")
    return v


def _validate_timezone(v: str | None) -> str | None:
    if v is None:
        return v
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    try:
        ZoneInfo(v)
    except (ZoneInfoNotFoundError, Exception):
        raise ValueError(f"timezone {v!r} is not a valid IANA timezone")
    return v


def zoneinfo_for_setting(timezone: str) -> "ZoneInfo | None":
    """Return ZoneInfo for timezone, or None if invalid. Use in scheduler to skip bad settings."""
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    try:
        return ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, Exception):
        return None


def validate_timezone_or_raise(timezone: str) -> "ZoneInfo":
    """Return ZoneInfo or raise ValueError for invalid timezone. Use in service for strict checks."""
    tz = zoneinfo_for_setting(timezone)
    if tz is None:
        raise ValueError(f"Invalid timezone: {timezone!r}")
    return tz


def _validate_source_types(v: list[str] | None) -> list[str] | None:
    if v is None:
        return v
    invalid = [t for t in v if t not in _VALID_SOURCE_TYPES]
    if invalid:
        raise ValueError(
            f"include_source_types contains unsupported values: {invalid}. "
            f"Allowed: {sorted(_VALID_SOURCE_TYPES)}"
        )
    return v


# ---------------------------------------------------------------------------
# Settings schemas
# ---------------------------------------------------------------------------

class DailyCaptureReportSettingOut(BaseModel):
    id: str
    space_id: str
    user_id: str
    enabled: bool
    local_time: str
    timezone: str
    include_source_types: list[str]
    create_experience_proposals: bool
    create_memory_proposals: bool
    experience_confidence_threshold: float
    memory_confidence_threshold: float
    max_experience_proposals_per_day: int
    max_memory_proposals_per_day: int
    last_report_date: Optional[str]
    next_run_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DailyCaptureReportSettingUpdate(BaseModel):
    enabled: Optional[bool] = None
    local_time: Optional[str] = None
    timezone: Optional[str] = None
    include_source_types: Optional[list[str]] = None
    create_experience_proposals: Optional[bool] = None
    create_memory_proposals: Optional[bool] = None
    experience_confidence_threshold: Optional[float] = None
    memory_confidence_threshold: Optional[float] = None
    max_experience_proposals_per_day: Optional[int] = None
    max_memory_proposals_per_day: Optional[int] = None

    @field_validator("local_time")
    @classmethod
    def validate_local_time(cls, v: Optional[str]) -> Optional[str]:
        return _validate_local_time(v)

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, v: Optional[str]) -> Optional[str]:
        return _validate_timezone(v)

    @field_validator("include_source_types")
    @classmethod
    def validate_source_types(cls, v: Optional[list[str]]) -> Optional[list[str]]:
        return _validate_source_types(v)

    @field_validator("experience_confidence_threshold", "memory_confidence_threshold")
    @classmethod
    def validate_threshold(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and not (0.0 <= v <= 1.0):
            raise ValueError("threshold must be between 0.0 and 1.0")
        return v

    @field_validator("max_experience_proposals_per_day")
    @classmethod
    def validate_max_experience(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and not (0 <= v <= 20):
            raise ValueError("max_experience_proposals_per_day must be 0–20")
        return v

    @field_validator("max_memory_proposals_per_day")
    @classmethod
    def validate_max_memory(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and not (0 <= v <= 10):
            raise ValueError("max_memory_proposals_per_day must be 0–10")
        return v


# ---------------------------------------------------------------------------
# Manual run request / response schemas
# ---------------------------------------------------------------------------

class DailyReportRunRequest(BaseModel):
    local_date: Optional[str] = Field(
        default=None,
        pattern=r"^\d{4}-\d{2}-\d{2}$",
        description="YYYY-MM-DD in the setting's timezone. Defaults to today.",
    )
    force: bool = False
    create_experience_proposals: Optional[bool] = None
    create_memory_proposals: Optional[bool] = None


class DailyReportRunResponse(BaseModel):
    run_id: str
    artifact_id: Optional[str]
    proposal_ids: list[str]
    experience_proposal_ids: list[str]
    memory_proposal_ids: list[str]
    capture_count: int
    status: str
    summary_preview: str


class DailyReportArtifactItemOut(BaseModel):
    id: str
    title: str
    artifact_type: str
    run_id: Optional[str]
    created_at: str
    report_date: Optional[str]
    capture_count: int

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Structured LLM output (internal validation)
# ---------------------------------------------------------------------------

class ReportTheme(BaseModel):
    title: str
    summary: str
    source_activity_ids: list[str] = Field(default_factory=list)


class ReportIdea(BaseModel):
    title: str
    content: str
    source_activity_ids: list[str] = Field(default_factory=list)


class ReportDecision(BaseModel):
    title: str
    content: str
    source_activity_ids: list[str] = Field(default_factory=list)


class ReportOpenQuestion(BaseModel):
    question: str
    context: str
    source_activity_ids: list[str] = Field(default_factory=list)


class ExperienceCandidate(BaseModel):
    title: str
    content: str
    confidence: float
    source_activity_ids: list[str] = Field(default_factory=list)


class MemoryCandidate(BaseModel):
    title: str
    content: str
    memory_type: str
    confidence: float
    source_activity_ids: list[str] = Field(default_factory=list)


class StructuredDailyReport(BaseModel):
    report_title: str
    overview: str
    themes: list[ReportTheme] = Field(default_factory=list)
    ideas: list[ReportIdea] = Field(default_factory=list)
    decisions: list[ReportDecision] = Field(default_factory=list)
    open_questions: list[ReportOpenQuestion] = Field(default_factory=list)
    experience_candidates: list[ExperienceCandidate] = Field(default_factory=list)
    memory_candidates: list[MemoryCandidate] = Field(default_factory=list)
