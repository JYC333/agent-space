from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


KnowledgeItemType = Literal[
    "knowledge",
    "idea",
    "experience",
    "reflection",
    "lesson",
    "procedure",
    "decision",
    "question",
    "summary",
]
KnowledgeContentFormat = Literal["markdown", "plain"]
KnowledgeItemStatus = Literal["draft", "active", "superseded", "archived"]
KnowledgeVisibility = Literal["private", "space_shared", "workspace_shared", "restricted"]
KnowledgeVerificationStatus = Literal["unverified", "needs_review", "verified"]
KnowledgeReflectionStatus = Literal["unreviewed", "reviewed", "distilled"]
KnowledgeItemRelationType = Literal[
    "related_to",
    "derived_from",
    "supports",
    "contradicts",
    "answers",
    "summarizes",
    "depends_on",
    "updates",
]
KnowledgeItemRelationStatus = Literal["candidate", "active", "rejected", "archived"]

SourceType = Literal[
    "activity_record",
    "chat_capture",
    "webpage",
    "article",
    "paper",
    "pdf",
    "file",
    "email",
    "manual_reference",
    "external_note",
]
SourceStatus = Literal["raw", "processing", "processed", "archived", "error"]
KnowledgeItemSourceRelationType = Literal[
    "derived_from",
    "supported_by",
    "cites",
    "summarizes",
    "mentions",
]


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


class KnowledgeItemRelationOut(BaseModel):
    id: str
    space_id: str
    from_item_id: str
    to_item_id: str
    relation_type: KnowledgeItemRelationType
    status: KnowledgeItemRelationStatus
    confidence: float | None
    note: str | None
    source_proposal_id: str | None
    created_by_user_id: str | None
    created_by_agent_id: str | None
    created_from_assessment_id: str | None
    created_at: datetime
    updated_at: datetime


class SourceOut(BaseModel):
    id: str
    space_id: str
    source_type: SourceType
    title: str
    uri: str | None
    content_ref: str | None
    raw_text: str | None
    summary: str | None
    metadata: dict = Field(default_factory=dict)
    status: SourceStatus
    source_activity_id: str | None
    created_by_user_id: str | None
    created_at: datetime
    updated_at: datetime


class SourceSummaryOut(BaseModel):
    id: str
    space_id: str
    source_type: SourceType
    title: str
    uri: str | None
    status: SourceStatus
    source_activity_id: str | None
    created_at: datetime
    updated_at: datetime


class KnowledgeItemSourceOut(BaseModel):
    id: str
    space_id: str
    knowledge_item_id: str
    source_id: str
    relation_type: KnowledgeItemSourceRelationType
    locator: str | None
    quote: str | None
    note: str | None
    confidence: float | None
    created_by_user_id: str | None
    created_at: datetime


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


class KnowledgeItemRelationCreateProposalIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_item_id: str
    to_item_id: str
    relation_type: KnowledgeItemRelationType
    confidence: float | None = Field(default=None, ge=0, le=1)
    note: str | None = None
    status: Literal["candidate", "active"] = "active"
    rationale: str | None = None


class SourceCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_type: SourceType
    title: str = Field(min_length=1, max_length=512)
    uri: str | None = None
    content_ref: str | None = None
    raw_text: str | None = None
    summary: str | None = None
    metadata: dict = Field(default_factory=dict)
    status: SourceStatus = "raw"
    source_activity_id: str | None = None


class SourceUpdateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=512)
    uri: str | None = None
    content_ref: str | None = None
    raw_text: str | None = None
    summary: str | None = None
    metadata: dict | None = None
    status: SourceStatus | None = None


class KnowledgeItemSourceLinkIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str
    relation_type: KnowledgeItemSourceRelationType = "derived_from"
    locator: str | None = None
    quote: str | None = None
    note: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
