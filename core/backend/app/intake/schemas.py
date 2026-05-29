"""Pydantic schemas for the Intake and Evidence API."""
from __future__ import annotations

import json
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _validate_json_size(value: dict | None, *, max_bytes: int = 8192, field: str = "json") -> dict | None:
    if value is None:
        return value
    if len(json.dumps(value, default=str)) > max_bytes:
        raise ValueError(f"{field} must not exceed {max_bytes} bytes")
    return value


class SourceConnectorOut(BaseModel):
    id: str
    connector_key: str
    display_name: str
    connector_type: str
    ingestion_mode: str
    status: str
    capabilities_json: dict
    config_schema_json: dict | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SourceConnectionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    connector_key: str = Field(..., min_length=1, max_length=128)
    name: str = Field(..., min_length=1, max_length=512)
    endpoint_url: str | None = Field(None, max_length=2048)
    credential_id: str | None = None
    fetch_frequency: str = Field("manual", pattern="^(manual|hourly|daily|weekly)$")
    capture_policy: str = Field(
        "metadata_only",
        pattern="^(metadata_only|excerpt_only|auto_extract_relevant|auto_extract_all_text|archive_all_snapshots)$",
    )
    trust_level: str = Field("normal", pattern="^(trusted|normal|untrusted)$")
    topic_hints: list[str] | None = None
    consent: dict = Field(default_factory=dict)
    policy: dict = Field(default_factory=dict)
    config: dict = Field(default_factory=dict)

    @field_validator("topic_hints")
    @classmethod
    def validate_topic_hints(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return value
        if len(value) > 50:
            raise ValueError("topic_hints may not exceed 50 items")
        for hint in value:
            if not isinstance(hint, str) or len(hint) > 256:
                raise ValueError("each topic hint must be a string of at most 256 characters")
        return value

    @field_validator("consent", "policy", "config")
    @classmethod
    def validate_small_json(cls, value: dict) -> dict:
        return _validate_json_size(value, field="connection JSON") or {}


class SourceConnectionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(None, min_length=1, max_length=512)
    status: str | None = Field(None, pattern="^(active|paused|archived)$")
    credential_id: str | None = None
    fetch_frequency: str | None = Field(None, pattern="^(manual|hourly|daily|weekly)$")
    capture_policy: str | None = Field(
        None,
        pattern="^(metadata_only|excerpt_only|auto_extract_relevant|auto_extract_all_text|archive_all_snapshots)$",
    )
    trust_level: str | None = Field(None, pattern="^(trusted|normal|untrusted)$")
    topic_hints: list[str] | None = None
    consent: dict | None = None
    policy: dict | None = None
    config: dict | None = None

    @field_validator("topic_hints")
    @classmethod
    def validate_topic_hints(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return value
        if len(value) > 50:
            raise ValueError("topic_hints may not exceed 50 items")
        for hint in value:
            if not isinstance(hint, str) or len(hint) > 256:
                raise ValueError("each topic hint must be a string of at most 256 characters")
        return value

    @field_validator("consent", "policy", "config")
    @classmethod
    def validate_small_json(cls, value: dict | None) -> dict | None:
        return _validate_json_size(value, field="connection JSON")


class SourceConnectionOut(BaseModel):
    id: str
    space_id: str
    connector_id: str
    owner_user_id: str
    credential_id: str | None
    name: str
    endpoint_url: str | None
    status: str
    fetch_frequency: str
    capture_policy: str
    trust_level: str
    topic_hints_json: list[str] | None
    consent_json: dict
    policy_json: dict
    config_json: dict
    last_checked_at: datetime | None
    next_check_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ManualURLCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(..., max_length=2048)
    title: str | None = Field(None, max_length=1024)
    connection_id: str | None = None
    queue_content: bool = False


class IntakeItemActionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: str = Field(
        ...,
        pattern="^(queue_content|archive_snapshot|read_later|mark_selected|mark_ignored|mark_discussed|extract_evidence)$",
    )


class IntakeItemOut(BaseModel):
    id: str
    space_id: str
    connection_id: str | None
    item_type: str
    source_object_type: str | None
    source_object_id: str | None
    title: str
    source_uri: str | None
    canonical_uri: str | None
    source_domain: str | None
    source_external_id: str | None
    author: str | None
    occurred_at: datetime | None
    first_seen_at: datetime
    last_seen_at: datetime
    content_hash: str | None
    excerpt: str | None
    status: str
    read_status: str
    content_state: str
    retention_policy: str
    relevance_score: float | None
    novelty_score: float | None
    raw_artifact_id: str | None
    extracted_artifact_id: str | None
    summary_artifact_id: str | None
    search_index_ref: str | None
    embedding_index_ref: str | None
    metadata_json: dict | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SourceSnapshotOut(BaseModel):
    id: str
    space_id: str
    intake_item_id: str | None
    connection_id: str | None
    snapshot_type: str
    artifact_id: str | None
    content_hash: str | None
    source_uri: str | None
    capture_method: str
    trust_level: str
    metadata_json: dict | None
    captured_at: datetime
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ExtractionJobOut(BaseModel):
    id: str
    space_id: str
    connection_id: str | None
    intake_item_id: str | None
    source_snapshot_id: str | None
    source_object_type: str | None
    source_object_id: str | None
    job_type: str
    status: str
    started_at: datetime | None
    completed_at: datetime | None
    items_seen: int | None
    items_created: int | None
    items_updated: int | None
    error_code: str | None
    error_message: str | None
    metadata_json: dict | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ExtractedEvidenceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intake_item_id: str | None = None
    source_object_type: str | None = Field(None, max_length=64)
    source_object_id: str | None = None
    evidence_type: str = Field("excerpt", pattern="^(document|excerpt|event|log|artifact|claim|summary)$")
    title: str = Field(..., min_length=1, max_length=1024)
    content_excerpt: str | None = Field(None, max_length=4096)
    artifact_id: str | None = None
    source_uri: str | None = Field(None, max_length=2048)
    trust_level: str = Field("normal", pattern="^(trusted|normal|untrusted)$")
    extraction_method: str = Field("manual", max_length=64)
    confidence: float | None = Field(None, ge=0, le=1)
    status: str = Field("candidate", pattern="^(candidate|active|rejected|archived)$")
    metadata: dict | None = None

    @field_validator("metadata")
    @classmethod
    def validate_metadata(cls, value: dict | None) -> dict | None:
        return _validate_json_size(value, field="metadata")


class ExtractedEvidenceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str | None = Field(None, pattern="^(candidate|active|rejected|archived)$")
    confidence: float | None = Field(None, ge=0, le=1)
    metadata: dict | None = None

    @field_validator("metadata")
    @classmethod
    def validate_metadata(cls, value: dict | None) -> dict | None:
        return _validate_json_size(value, field="metadata")


class ExtractedEvidenceOut(BaseModel):
    id: str
    space_id: str
    intake_item_id: str | None
    extraction_job_id: str | None
    source_snapshot_id: str | None
    source_object_type: str | None
    source_object_id: str | None
    evidence_type: str
    title: str
    content_excerpt: str | None
    content_hash: str | None
    artifact_id: str | None
    source_uri: str | None
    source_title: str | None
    source_author: str | None
    occurred_at: datetime | None
    trust_level: str
    extraction_method: str
    confidence: float | None
    status: str
    metadata_json: dict | None
    created_by_user_id: str | None
    created_by_agent_id: str | None
    created_by_run_id: str | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class EvidenceLinkCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str
    target_type: str = Field(
        ...,
        pattern="^(space|workspace|project|user|agent|run|proposal|artifact|knowledge|memory|task)$",
    )
    target_id: str | None = None
    link_type: str = Field(
        "context_candidate",
        pattern="^(supports|contradicts|derived_from|mentions|context_candidate|used_in_context|provenance)$",
    )
    status: str = Field("active", pattern="^(candidate|active|rejected|archived)$")
    confidence: float | None = Field(None, ge=0, le=1)
    reason: str | None = Field(None, max_length=1024)


class EvidenceLinkOut(BaseModel):
    id: str
    space_id: str
    evidence_id: str
    target_type: str
    target_id: str | None
    link_type: str
    status: str
    confidence: float | None
    reason: str | None
    created_by_user_id: str | None
    created_by_agent_id: str | None
    created_by_run_id: str | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class WorkspaceIntakeProfileCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str
    name: str = Field("Default intake profile", min_length=1, max_length=256)
    observation_policy: str = Field("manual", pattern="^(disabled|manual|auto_select|auto_extract)$")
    routing_policy: dict = Field(default_factory=dict)
    filters: dict = Field(default_factory=dict)
    extraction_policy: dict = Field(default_factory=dict)
    context_policy: dict = Field(default_factory=dict)


class WorkspaceIntakeProfileOut(BaseModel):
    id: str
    space_id: str
    workspace_id: str
    name: str
    status: str
    observation_policy: str
    routing_policy_json: dict
    filters_json: dict
    extraction_policy_json: dict
    context_policy_json: dict
    created_by_user_id: str | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class WorkspaceSourceBindingCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str
    source_connection_id: str
    binding_key: str = Field("default", min_length=1, max_length=128)
    project_id: str | None = None
    priority: int = 0
    filters: dict = Field(default_factory=dict)
    routing_policy: dict = Field(default_factory=dict)
    extraction_policy: dict = Field(default_factory=dict)


class WorkspaceSourceBindingOut(BaseModel):
    id: str
    space_id: str
    workspace_id: str
    project_id: str | None
    source_connection_id: str
    binding_key: str
    status: str
    priority: int
    filters_json: dict
    routing_policy_json: dict
    extraction_policy_json: dict
    created_by_user_id: str | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
