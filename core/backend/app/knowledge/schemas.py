from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


KnowledgeItemType = Literal[
    "concept",
    "claim",
    "lesson",
    "procedure",
    "decision",
    "question",
    "answer",
    "summary",
]
KnowledgeContentFormat = Literal["markdown", "plain", "prosemirror_json"]
KnowledgeItemStatus = Literal["draft", "active", "superseded", "archived"]
KnowledgeVisibility = Literal["private", "space_shared", "workspace_shared", "restricted"]
KnowledgeVerificationStatus = Literal["unverified", "needs_review", "verified"]
KnowledgeReflectionStatus = Literal["unreviewed", "reviewed", "distilled"]
KnowledgeItemRelationType = Literal[
    "related_to",
    "explains",
    "depends_on",
    "prerequisite_of",
    "part_of",
    "example_of",
    "applies_to",
    "supports",
    "contradicts",
    "derived_from",
    "summarizes",
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
    redirect_to_item_id: str | None
    item_type: KnowledgeItemType
    slug: str | None
    aliases: list[str] = Field(default_factory=list)
    title: str
    content: str
    content_json: dict | None
    content_format: KnowledgeContentFormat
    content_schema_version: int
    plain_text: str | None
    excerpt: str | None
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
    deprecated_at: datetime | None


class KnowledgeItemSummaryOut(BaseModel):
    id: str
    space_id: str
    project_id: str | None
    workspace_id: str | None
    item_type: KnowledgeItemType
    slug: str | None
    title: str
    content_preview: str
    excerpt: str | None
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
    evidence_summary: str | None
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

    item_type: KnowledgeItemType = "concept"
    title: str = Field(min_length=1, max_length=512)
    slug: str | None = Field(default=None, max_length=512)
    aliases: list[str] = Field(default_factory=list)
    content: str = Field(min_length=1)
    content_json: dict | None = None
    content_format: KnowledgeContentFormat = "markdown"
    content_schema_version: int = Field(default=1, ge=1)
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
    slug: str | None = Field(default=None, max_length=512)
    aliases: list[str] = Field(default_factory=list)
    content: str = Field(min_length=1)
    content_json: dict | None = None
    content_format: KnowledgeContentFormat = "markdown"
    content_schema_version: int = Field(default=1, ge=1)
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
    evidence_summary: str | None = None
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


# ---------------------------------------------------------------------------
# Notes (working knowledge; direct CRUD)
# ---------------------------------------------------------------------------

NoteStatus = Literal["active", "archived", "deleted"]
NoteContentFormat = Literal["markdown", "plain", "prosemirror_json"]
NoteCollectionSystemRole = Literal["normal", "inbox", "archive"]


class NoteCollectionOut(BaseModel):
    id: str
    space_id: str
    parent_id: str | None
    name: str
    system_role: NoteCollectionSystemRole
    sort_order: int
    is_system: bool
    is_hidden: bool
    created_at: datetime
    updated_at: datetime


class NoteCollectionCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=256)
    parent_id: str | None = None
    sort_order: int | None = None


class NoteCollectionUpdateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=256)
    parent_id: str | None = None
    sort_order: int | None = None
    is_hidden: bool | None = None


class NoteOut(BaseModel):
    id: str
    space_id: str
    title: str
    content_json: dict | None
    content_format: NoteContentFormat
    content_schema_version: int
    plain_text: str | None
    excerpt: str | None
    status: NoteStatus
    primary_project_id: str | None
    collection_id: str | None
    created_from_activity_id: str | None
    created_by_user_id: str | None
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None
    deleted_at: datetime | None


class NoteSummaryOut(BaseModel):
    id: str
    space_id: str
    title: str
    excerpt: str | None
    status: NoteStatus
    content_format: NoteContentFormat
    primary_project_id: str | None
    collection_id: str | None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None


class NoteCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=512)
    content_json: dict | None = None
    content_format: NoteContentFormat = "markdown"
    content_schema_version: int = Field(default=1, ge=1)
    plain_text: str | None = None
    excerpt: str | None = Field(default=None, max_length=512)
    status: Literal["active"] = "active"
    primary_project_id: str | None = None
    created_from_activity_id: str | None = None
    collection_id: str | None = None


class NoteUpdateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=512)
    content_json: dict | None = None
    content_format: NoteContentFormat | None = None
    content_schema_version: int | None = Field(default=None, ge=1)
    plain_text: str | None = None
    excerpt: str | None = Field(default=None, max_length=512)
    status: NoteStatus | None = None
    primary_project_id: str | None = None


# ---------------------------------------------------------------------------
# Entity links (generic cross-object relation layer)
# ---------------------------------------------------------------------------

EntityType = Literal[
    "note", "knowledge_item", "source", "project", "workspace", "activity", "run", "proposal"
]
EntityLinkType = Literal[
    "references", "related_to", "belongs_to", "captured_from", "source_for", "derived_from"
]
EntityLinkStatus = Literal["suggested", "accepted", "rejected"]


class EntityLinkOut(BaseModel):
    id: str
    space_id: str
    source_type: EntityType
    source_id: str
    target_type: EntityType
    target_id: str
    link_type: EntityLinkType
    confidence: float | None
    status: EntityLinkStatus
    created_by_user_id: str | None
    created_at: datetime


class NoteLinkCreateIn(BaseModel):
    """Create a link between a note (the URL's note) and another entity.

    ``direction='outgoing'`` makes the note the source (note -> target);
    ``'incoming'`` makes it the target (target -> note).
    """

    model_config = ConfigDict(extra="forbid")

    target_type: EntityType
    target_id: str
    link_type: EntityLinkType = "related_to"
    confidence: float | None = Field(default=None, ge=0, le=1)
    direction: Literal["outgoing", "incoming"] = "outgoing"


# ---------------------------------------------------------------------------
# Knowledge overview summary
# ---------------------------------------------------------------------------


class KnowledgeNoteCounts(BaseModel):
    active: int
    archived: int
    deleted: int
    total: int


class KnowledgeWikiCounts(BaseModel):
    active: int


class KnowledgeSourceCounts(BaseModel):
    total: int


class KnowledgeSummaryOut(BaseModel):
    notes: KnowledgeNoteCounts
    wiki: KnowledgeWikiCounts
    sources: KnowledgeSourceCounts


# ---------------------------------------------------------------------------
# Cards (knowledge review / spaced-repetition foundation)
# ---------------------------------------------------------------------------

CardType = Literal["basic", "cloze"]
CardStatus = Literal["draft", "active", "suspended", "archived"]
CardSourceType = Literal["note", "knowledge_item", "source", "activity", "run", "proposal"]
CardReviewRating = Literal["again", "hard", "good", "easy"]
CardReviewStateValue = Literal["new", "learning", "review", "relearning"]


class CardOut(BaseModel):
    id: str
    space_id: str
    card_type: CardType
    front: str
    back: str
    source_type: CardSourceType | None
    source_id: str | None
    status: CardStatus
    created_by_user_id: str | None
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None
    metadata: dict = Field(default_factory=dict)


class CardSummaryOut(BaseModel):
    id: str
    space_id: str
    card_type: CardType
    front: str
    status: CardStatus
    source_type: CardSourceType | None
    source_id: str | None
    updated_at: datetime


class CardReviewStateOut(BaseModel):
    id: str
    card_id: str
    user_id: str
    due_at: datetime | None
    stability: float | None
    difficulty: float | None
    elapsed_days: float | None
    scheduled_days: float | None
    reps: int
    lapses: int
    state: CardReviewStateValue | None
    last_reviewed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class CardReviewOut(BaseModel):
    id: str
    card_id: str
    user_id: str
    rating: CardReviewRating
    reviewed_at: datetime
    review_state_snapshot: dict | None
    duration_ms: int | None
    created_at: datetime
