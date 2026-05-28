from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


KnowledgeItemType = Literal[
    "knowledge",
    "experience",
    "lesson",
    "procedure",
    "decision",
    "reflection",
    "source",
    "question",
    "answer",
    "summary",
]
KnowledgeContentFormat = Literal["markdown", "plain"]
KnowledgeItemStatus = Literal["draft", "active", "superseded", "archived"]
KnowledgeVisibility = Literal["private", "space_shared", "workspace_shared", "restricted"]
KnowledgeVerificationStatus = Literal["unverified", "needs_review", "verified"]
KnowledgeReflectionStatus = Literal["unreviewed", "reviewed", "distilled"]
KnowledgeRelationType = Literal[
    "related",
    "derived_from",
    "example_of",
    "supports",
    "contradicts",
    "part_of",
    "prerequisite_of",
    "applies_to",
    "answers",
]
KnowledgeRelationStatus = Literal["candidate", "active", "rejected", "archived"]


class KnowledgeItemOut(BaseModel):
    id: str
    space_id: str
    project_id: str | None
    workspace_id: str | None
    root_item_id: str | None
    supersedes_item_id: str | None
    item_type: KnowledgeItemType
    title: str
    content: str
    content_format: KnowledgeContentFormat
    status: KnowledgeItemStatus
    visibility: KnowledgeVisibility
    verification_status: KnowledgeVerificationStatus
    reflection_status: KnowledgeReflectionStatus
    tags: list[str] = Field(default_factory=list)
    confidence: float | None
    source_url: str | None
    source_refs: list[dict] = Field(default_factory=list)
    owner_user_id: str | None
    created_by_user_id: str | None
    created_by_agent_id: str | None
    created_by_run_id: str | None
    source_activity_id: str | None
    source_artifact_id: str | None
    created_from_proposal_id: str | None
    approved_by_user_id: str | None
    version: int
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None


class KnowledgeItemSummaryOut(BaseModel):
    id: str
    space_id: str
    project_id: str | None
    workspace_id: str | None
    item_type: KnowledgeItemType
    title: str
    content_preview: str
    status: KnowledgeItemStatus
    visibility: KnowledgeVisibility
    verification_status: KnowledgeVerificationStatus
    reflection_status: KnowledgeReflectionStatus
    tags: list[str] = Field(default_factory=list)
    confidence: float | None
    version: int
    updated_at: datetime


class KnowledgeRelationOut(BaseModel):
    id: str
    space_id: str
    from_item_id: str
    to_item_id: str
    relation_type: KnowledgeRelationType
    status: KnowledgeRelationStatus
    confidence: float | None
    evidence_summary: str | None
    source_proposal_id: str | None
    created_by_user_id: str | None
    created_by_agent_id: str | None
    created_from_assessment_id: str | None
    created_at: datetime
    updated_at: datetime


class KnowledgeCreateProposalIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_type: KnowledgeItemType = "knowledge"
    title: str = Field(min_length=1, max_length=512)
    content: str = Field(min_length=1)
    content_format: KnowledgeContentFormat = "markdown"
    visibility: KnowledgeVisibility = "space_shared"
    project_id: str | None = None
    workspace_id: str | None = None
    tags: list[str] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0, le=1)
    source_url: str | None = None
    source_refs: list[dict] = Field(default_factory=list)
    source_activity_id: str | None = None
    source_run_id: str | None = None
    source_artifact_id: str | None = None
    verification_status: KnowledgeVerificationStatus = "unverified"
    reflection_status: KnowledgeReflectionStatus = "unreviewed"
    rationale: str | None = None


class KnowledgeUpdateProposalIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=512)
    content: str = Field(min_length=1)
    content_format: KnowledgeContentFormat = "markdown"
    tags: list[str] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0, le=1)
    source_refs: list[dict] = Field(default_factory=list)
    verification_status: KnowledgeVerificationStatus = "unverified"
    reflection_status: KnowledgeReflectionStatus = "unreviewed"
    rationale: str | None = None


class KnowledgeRelationCreateProposalIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_item_id: str
    to_item_id: str
    relation_type: KnowledgeRelationType
    confidence: float | None = Field(default=None, ge=0, le=1)
    evidence_summary: str | None = None
    status: Literal["candidate", "active"] = "active"
    rationale: str | None = None
