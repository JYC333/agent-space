import { createHash } from "node:crypto";
import {
  HttpError,
  dateIso,
} from "../routeUtils/common";
import type {
  EvidenceLinkRow,
  EvidenceRow,
  ExtractionJobRow,
  IntakeItemRow,
  SourceConnectionRow,
  SourceConnectorRow,
  WorkspaceBindingRow,
  WorkspaceProfileRow,
} from "./intakeRepositoryRows";
import { normalizeSourceConnectionReadGovernance } from "./sourceConsent";

export function connectorOut(row: SourceConnectorRow) {
  return {
    id: row.id,
    connector_key: row.connector_key,
    display_name: row.display_name,
    connector_type: row.connector_type,
    ingestion_mode: row.ingestion_mode,
    status: row.status,
    capabilities_json: row.capabilities_json ?? {},
    config_schema_json: row.config_schema_json ?? null,
    created_at: dateIso(row.created_at),
    updated_at: dateIso(row.updated_at),
  };
}

export function connectionOut(row: SourceConnectionRow) {
  const governance = normalizeSourceConnectionReadGovernance(row);
  return {
    id: row.id,
    space_id: row.space_id,
    connector_id: row.connector_id,
    owner_user_id: row.owner_user_id,
    credential_id: row.credential_id,
    name: row.name,
    endpoint_url: row.endpoint_url,
    status: row.status,
    fetch_frequency: row.fetch_frequency,
    capture_policy: row.capture_policy,
    trust_level: row.trust_level,
    topic_hints_json: row.topic_hints_json ?? null,
    consent_json: governance.consent,
    policy_json: governance.policy,
    config_json: row.config_json ?? {},
    last_checked_at: dateIso(row.last_checked_at),
    next_check_at: dateIso(row.next_check_at),
    created_at: dateIso(row.created_at),
    updated_at: dateIso(row.updated_at),
  };
}

export function itemOut(row: IntakeItemRow) {
  return {
    id: row.id,
    space_id: row.space_id,
    connection_id: row.connection_id,
    item_type: row.item_type,
    source_object_type: row.source_object_type,
    source_object_id: row.source_object_id,
    title: row.title,
    source_uri: row.source_uri,
    canonical_uri: row.canonical_uri,
    source_domain: row.source_domain,
    source_external_id: row.source_external_id,
    author: row.author,
    occurred_at: dateIso(row.occurred_at),
    first_seen_at: dateIso(row.first_seen_at),
    last_seen_at: dateIso(row.last_seen_at),
    content_hash: row.content_hash,
    excerpt: row.excerpt,
    status: row.status,
    read_status: row.read_status,
    content_state: row.content_state,
    retention_policy: row.retention_policy,
    relevance_score: row.relevance_score,
    novelty_score: row.novelty_score,
    raw_artifact_id: row.raw_artifact_id,
    extracted_artifact_id: row.extracted_artifact_id,
    summary_artifact_id: row.summary_artifact_id,
    search_index_ref: row.search_index_ref,
    embedding_index_ref: row.embedding_index_ref,
    metadata_json: row.metadata_json ?? null,
    created_at: dateIso(row.created_at),
    updated_at: dateIso(row.updated_at),
  };
}

export function jobOut(row: ExtractionJobRow) {
  return {
    id: row.id,
    space_id: row.space_id,
    connection_id: row.connection_id,
    intake_item_id: row.intake_item_id,
    source_snapshot_id: row.source_snapshot_id,
    source_object_type: row.source_object_type,
    source_object_id: row.source_object_id,
    job_type: row.job_type,
    status: row.status,
    started_at: dateIso(row.started_at),
    completed_at: dateIso(row.completed_at),
    items_seen: row.items_seen,
    items_created: row.items_created,
    items_updated: row.items_updated,
    error_code: row.error_code,
    error_message: row.error_message,
    metadata_json: row.metadata_json ?? null,
    created_at: dateIso(row.created_at),
  };
}

export function evidenceOut(row: EvidenceRow) {
  return {
    id: row.id,
    space_id: row.space_id,
    intake_item_id: row.intake_item_id,
    extraction_job_id: row.extraction_job_id,
    source_snapshot_id: row.source_snapshot_id,
    source_object_type: row.source_object_type,
    source_object_id: row.source_object_id,
    evidence_type: row.evidence_type,
    title: row.title,
    content_excerpt: row.content_excerpt,
    content_hash: row.content_hash,
    artifact_id: row.artifact_id,
    source_uri: row.source_uri,
    source_title: row.source_title,
    source_author: row.source_author,
    occurred_at: dateIso(row.occurred_at),
    trust_level: row.trust_level,
    extraction_method: row.extraction_method,
    confidence: row.confidence,
    status: row.status,
    metadata_json: row.metadata_json ?? null,
    created_by_user_id: row.created_by_user_id,
    created_by_agent_id: row.created_by_agent_id,
    created_by_run_id: row.created_by_run_id,
    created_at: dateIso(row.created_at),
    updated_at: dateIso(row.updated_at),
  };
}

export function evidenceLinkOut(row: EvidenceLinkRow) {
  return {
    id: row.id,
    space_id: row.space_id,
    evidence_id: row.evidence_id,
    target_type: row.target_type,
    target_id: row.target_id,
    link_type: row.link_type,
    status: row.status,
    confidence: row.confidence,
    reason: row.reason,
    created_by_user_id: row.created_by_user_id,
    created_by_agent_id: row.created_by_agent_id,
    created_by_run_id: row.created_by_run_id,
    created_at: dateIso(row.created_at),
    updated_at: dateIso(row.updated_at),
  };
}

export function profileOut(row: WorkspaceProfileRow) {
  return {
    id: row.id,
    space_id: row.space_id,
    workspace_id: row.workspace_id,
    name: row.name,
    status: row.status,
    observation_policy: row.observation_policy,
    routing_policy_json: row.routing_policy_json ?? {},
    filters_json: row.filters_json ?? {},
    extraction_policy_json: row.extraction_policy_json ?? {},
    context_policy_json: row.context_policy_json ?? {},
    created_by_user_id: row.created_by_user_id,
    created_at: dateIso(row.created_at),
    updated_at: dateIso(row.updated_at),
  };
}

export function bindingOut(row: WorkspaceBindingRow) {
  return {
    id: row.id,
    space_id: row.space_id,
    workspace_id: row.workspace_id,
    project_id: row.project_id,
    source_connection_id: row.source_connection_id,
    binding_key: row.binding_key,
    status: row.status,
    priority: row.priority,
    filters_json: row.filters_json ?? {},
    routing_policy_json: row.routing_policy_json ?? {},
    extraction_policy_json: row.extraction_policy_json ?? {},
    created_by_user_id: row.created_by_user_id,
    created_at: dateIso(row.created_at),
    updated_at: dateIso(row.updated_at),
  };
}

export function normalizeUrl(value: string): string {
  try {
    const url = new URL(value);
    url.hash = "";
    return url.toString();
  } catch {
    throw new HttpError(422, "url must be a valid URL");
  }
}

export function sourceDomain(value: string): string | null {
  try {
    return new URL(value).hostname || null;
  } catch {
    return null;
  }
}

export function sha256(value: string): string {
  return createHash("sha256").update(value).digest("hex");
}

export function stringList(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string" && item.trim().length > 0) : [];
}

export function buildSummary(evidence: EvidenceRow[], items: IntakeItemRow[], goal: string | null): string {
  const lines = [goal ? `# ${goal}` : "# Intake evidence summary", ""];
  for (const row of evidence) {
    lines.push(`- Evidence: ${row.title}${row.content_excerpt ? ` — ${row.content_excerpt.slice(0, 240)}` : ""}`);
  }
  for (const row of items) {
    lines.push(`- Intake item: ${row.title}${row.excerpt ? ` — ${row.excerpt.slice(0, 240)}` : ""}`);
  }
  return lines.join("\n");
}
