"""Pydantic models for GET /api/v1/home/summary."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

PriorityLevel = Literal["high", "normal", "low"]


class HomeRunSummaryItem(BaseModel):
    id: str
    status: str
    mode: str
    run_type: str
    agent_id: str
    task_id: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_text: str | None = None


class HomePendingProposalItem(BaseModel):
    id: str
    title: str
    proposal_type: str
    status: str
    risk_level: str
    urgency: str
    review_deadline: datetime | None = None
    expires_at: datetime | None = None
    expired: bool
    preview: bool
    created_by_run_id: str | None = None


class HomePendingProposalsSection(BaseModel):
    count: int
    items: list[HomePendingProposalItem]


class HomeArtifactSummaryItem(BaseModel):
    id: str
    title: str
    artifact_type: str
    preview: bool
    run_id: str | None = None
    created_at: datetime


class HomeTaskSummarySection(BaseModel):
    by_status: dict[str, int] = Field(default_factory=dict)
    total_open: int
    needs_review_count: int
    blocked_count: int
    done_count: int


class HomeActiveTaskItem(BaseModel):
    id: str
    title: str
    status: str
    priority: str
    risk_level: str
    task_type: str
    assigned_user_id: str | None = None
    assigned_agent_id: str | None = None
    due_at: datetime | None = None
    updated_at: datetime


class HomeActivitySummarySection(BaseModel):
    recent_count: int
    raw_count: int
    today_count: int


class HomeRunStatsTodaySection(BaseModel):
    created: int
    queued: int
    running: int
    succeeded: int
    failed: int
    cancelled: int
    dry_run_count: int


class HomeJobQueueStatusSection(BaseModel):
    queued: int
    running: int
    failed: int
    retryable: int
    recent_error_preview: str | None = None


class HomeRuntimeStatusSection(BaseModel):
    real_adapters_configured_count: int
    configured_adapter_types: list[str]
    message: str


class HomeModelProviderStatusSection(BaseModel):
    model_providers_count: int
    enabled_model_providers_count: int
    missing_model_provider_config: bool
    message: str


class HomeSuggestedActionItem(BaseModel):
    id: str
    label: str
    reason: str
    target_path: str
    priority: PriorityLevel


class HomeSummaryOut(BaseModel):
    recent_runs: list[HomeRunSummaryItem]
    active_runs: list[HomeRunSummaryItem]
    pending_proposals: HomePendingProposalsSection
    recent_artifacts: list[HomeArtifactSummaryItem]
    task_summary: HomeTaskSummarySection
    active_tasks: list[HomeActiveTaskItem]
    activity_summary: HomeActivitySummarySection
    run_stats_today: HomeRunStatsTodaySection
    job_queue_status: HomeJobQueueStatusSection
    runtime_status: HomeRuntimeStatusSection
    model_provider_status: HomeModelProviderStatusSection
    suggested_actions: list[HomeSuggestedActionItem]
