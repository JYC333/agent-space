import { randomUUID } from "node:crypto";
import type {
  ProposalApplyContext,
  ProposalApplyResult,
} from "../proposals/applierRegistry";
import {
  writeProvenanceLinks,
  type Queryable,
} from "../memory/memoryApplyProvenance";

interface ProposalApplierRegistrar {
  register(
    proposalType: string,
    applier: (context: ProposalApplyContext) => Promise<ProposalApplyResult>,
  ): void;
}

interface KnowledgeItemRow {
  id: string;
  space_id: string;
  project_id: string | null;
  workspace_id: string | null;
  root_item_id: string | null;
  supersedes_item_id: string | null;
  redirect_to_item_id: string | null;
  item_type: string;
  slug: string | null;
  aliases_json: unknown;
  title: string;
  content: string;
  content_json: unknown | null;
  content_format: string;
  content_schema_version: string | number;
  plain_text: string | null;
  excerpt: string | null;
  status: string;
  visibility: string;
  verification_status: string;
  reflection_status: string;
  tags_json: unknown;
  confidence: number | null;
  source_url: string | null;
  owner_user_id: string | null;
  created_by_user_id: string | null;
  created_by_agent_id: string | null;
  created_by_run_id: string | null;
  source_activity_id: string | null;
  source_artifact_id: string | null;
  created_from_proposal_id: string | null;
  approved_by_user_id: string | null;
  version: string | number;
  archived_at: string | null;
  deprecated_at: string | null;
  created_at: string | null;
  updated_at: string | null;
}

interface KnowledgeRelationRow {
  id: string;
  space_id: string;
  from_item_id: string;
  to_item_id: string;
  relation_type: string;
  status: string;
  confidence: number | null;
  evidence_summary: string | null;
  source_proposal_id: string | null;
  created_by_user_id: string | null;
  created_by_agent_id: string | null;
  created_at: string | null;
  updated_at: string | null;
}

interface ProvenanceEntry {
  source_type: string;
  source_id: string;
  source_trust?: string;
  evidence_json?: Record<string, unknown>;
}

const VALID_ITEM_TYPES = new Set([
  "concept",
  "claim",
  "lesson",
  "procedure",
  "decision",
  "question",
  "answer",
  "summary",
]);

const VALID_CONTENT_FORMATS = new Set(["markdown", "plain", "prosemirror_json"]);

const VALID_VISIBILITIES = new Set([
  "private",
  "space_shared",
  "workspace_shared",
  "restricted",
]);

const VALID_VERIFICATION_STATUSES = new Set(["unverified", "needs_review", "verified"]);

const VALID_REFLECTION_STATUSES = new Set(["unreviewed", "reviewed", "distilled"]);

const VALID_RELATION_TYPES = new Set([
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
]);

const VALID_RELATION_STATUSES = new Set(["candidate", "active"]);

const VALID_PROVENANCE_TYPES = new Set([
  "activity",
  "proposal",
  "memory",
  "artifact",
  "run_step",
  "external_source",
  "user_confirmation",
  "intake_item",
  "source_snapshot",
  "extracted_evidence",
  "run_event",
]);

const KNOWLEDGE_ITEM_COLUMNS = `
  id, space_id, project_id, workspace_id, root_item_id, supersedes_item_id, redirect_to_item_id,
  item_type, slug, aliases_json, title, content, content_json, content_format,
  content_schema_version, plain_text, excerpt, status, visibility, verification_status,
  reflection_status, tags_json, confidence, source_url, owner_user_id, created_by_user_id,
  created_by_agent_id, created_by_run_id, source_activity_id, source_artifact_id,
  created_from_proposal_id, approved_by_user_id, version, archived_at, deprecated_at,
  created_at, updated_at
`;

const KNOWLEDGE_RELATION_COLUMNS = `
  id, space_id, from_item_id, to_item_id, relation_type, status, confidence,
  evidence_summary, source_proposal_id, created_by_user_id, created_by_agent_id,
  created_at, updated_at
`;

const TARGET_KNOWLEDGE = "knowledge";

export function registerKnowledgeProposalAppliers(
  registry: ProposalApplierRegistrar,
): void {
  registry.register("knowledge_create", applyKnowledgeCreateProposal);
  registry.register("knowledge_update", applyKnowledgeUpdateProposal);
  registry.register("knowledge_archive", applyKnowledgeArchiveProposal);
  registry.register("knowledge_relation_create", applyKnowledgeRelationCreateProposal);
  registry.register("knowledge_relation_delete", applyKnowledgeRelationDeleteProposal);
}

async function applyKnowledgeCreateProposal(
  context: ProposalApplyContext,
): Promise<ProposalApplyResult> {
  const payload = context.proposal.payload_json ?? {};
  ensureOperation(payload, "create");

  const itemType = expectString(payload.item_type);
  if (!VALID_ITEM_TYPES.has(itemType)) {
    throw new KnowledgeApplyValidationError(`invalid item_type: ${JSON.stringify(itemType)}`);
  }

  const title = expectString(payload.title);
  const content = expectString(payload.content);
  const contentFormat = optionalString(payload.content_format) ?? "markdown";
  if (!VALID_CONTENT_FORMATS.has(contentFormat)) {
    throw new KnowledgeApplyValidationError(`invalid content_format: ${JSON.stringify(contentFormat)}`);
  }

  const visibility = optionalString(payload.visibility) ?? "space_shared";
  if (!VALID_VISIBILITIES.has(visibility)) {
    throw new KnowledgeApplyValidationError(`invalid visibility: ${JSON.stringify(visibility)}`);
  }

  const verificationStatus = optionalString(payload.verification_status) ?? "unverified";
  if (!VALID_VERIFICATION_STATUSES.has(verificationStatus)) {
    throw new KnowledgeApplyValidationError(
      `invalid verification_status: ${JSON.stringify(verificationStatus)}`,
    );
  }

  const reflectionStatus = optionalString(payload.reflection_status) ?? "unreviewed";
  if (!VALID_REFLECTION_STATUSES.has(reflectionStatus)) {
    throw new KnowledgeApplyValidationError(
      `invalid reflection_status: ${JSON.stringify(reflectionStatus)}`,
    );
  }

  const requestedOwnerUserId = optionalString(payload.owner_user_id);
  if (
    requestedOwnerUserId !== null &&
    context.proposal.created_by_user_id !== null &&
    requestedOwnerUserId !== context.proposal.created_by_user_id
  ) {
    throw new KnowledgeApplyValidationError("Knowledge owner must be the proposal creator");
  }
  if (
    (visibility === "private" || visibility === "restricted") &&
    context.proposal.created_by_user_id == null
  ) {
    throw new KnowledgeApplyValidationError("private or restricted Knowledge requires a human owner");
  }

  const projectId = optionalString(payload.project_id);
  const workspaceId = optionalString(payload.workspace_id);
  const contentJson = optionalObject(payload.content_json);
  const aliases = toStringArray(payload.aliases);
  const tags = toStringArray(payload.tags);
  const confidence = parseConfidence(payload.confidence);
  const sourceRefs = provenanceEntriesFromPayload(payload.source_refs);
  const sourceUrl = optionalString(payload.source_url);
  const sourceActivityId = optionalString(payload.source_activity_id);
  const sourceArtifactId = optionalString(payload.source_artifact_id);
  const sourceRunId = optionalString(payload.source_run_id);
  const slug = optionalString(payload.slug);

  const now = new Date().toISOString();
  const plainText = derivePlainText({ title, content, contentJson });
  const excerpt = plainText ? plainText.slice(0, 280) : null;
  const itemId = randomUUID();
  const row = await getKnowledgeRowsOrThrow<{ id: string }>(
    context.db,
    `INSERT INTO knowledge_items (
       id, space_id, project_id, workspace_id, item_type, slug, aliases_json, title,
       content, content_json, content_format, content_schema_version, plain_text, excerpt,
       status, visibility, verification_status, reflection_status, tags_json, confidence,
       source_url, owner_user_id, created_by_user_id, created_by_run_id, source_activity_id,
       source_artifact_id, created_from_proposal_id, approved_by_user_id, version, created_at, updated_at
     )
     VALUES (
       $1, $2, $3, $4, $5, $6, $7::jsonb, $8,
       $9, $10::jsonb, $11, COALESCE($12::int, 1), $13, $14,
       'active', $15, $16, $17, $18::jsonb, $19, $20,
       $21, $22, $23, $24, $25,
       $26, $27, 1, $28, $29
     )
     RETURNING id`,
    [
      itemId,
      context.proposal.space_id,
      projectId,
      workspaceId,
      itemType,
      slug,
      JSON.stringify(aliases),
      title,
      content,
      contentJson ? JSON.stringify(contentJson) : null,
      contentFormat,
      numberValue(payload.content_schema_version),
      plainText,
      excerpt,
      visibility,
      verificationStatus,
      reflectionStatus,
      JSON.stringify(tags),
      confidence,
      sourceUrl,
      context.proposal.created_by_user_id,
      context.proposal.created_by_user_id,
      sourceRunId ?? context.proposal.created_by_run_id,
      sourceActivityId,
      sourceArtifactId,
      context.proposal.id,
      context.userId,
      now,
      now,
    ],
  );

  await context.db.query(`UPDATE knowledge_items SET root_item_id = id WHERE id = $1 AND space_id = $2`, [
    row.id,
    context.proposal.space_id,
  ]);

  await writeSourceRefs({
    db: context.db,
    spaceId: context.proposal.space_id,
    targetId: row.id,
    entries: sourceRefs,
  });

  const created = await getKnowledgeItemById(context.db, context.proposal.space_id, row.id);
  return {
    result_type: "knowledge_item",
    result: { knowledge_item: serializeKnowledgeItem(created) },
  };
}

async function applyKnowledgeUpdateProposal(
  context: ProposalApplyContext,
): Promise<ProposalApplyResult> {
  const payload = context.proposal.payload_json ?? {};
  ensureOperation(payload, "update");

  const targetId = expectString(payload.target_item_id);
  const current = await requireKnowledgeItem(context.db, context.proposal.space_id, targetId, context.proposal);
  const title = expectString(payload.title);
  const content = expectString(payload.content);
  const contentJson = optionalObject(payload.content_json);
  const contentFormat = optionalString(payload.content_format) ?? current.content_format;
  if (!VALID_CONTENT_FORMATS.has(contentFormat)) {
    throw new KnowledgeApplyValidationError(`invalid content_format: ${JSON.stringify(contentFormat)}`);
  }

  const verificationStatus = optionalString(payload.verification_status) ?? current.verification_status;
  if (!VALID_VERIFICATION_STATUSES.has(verificationStatus)) {
    throw new KnowledgeApplyValidationError(
      `invalid verification_status: ${JSON.stringify(verificationStatus)}`,
    );
  }

  const reflectionStatus = optionalString(payload.reflection_status) ?? current.reflection_status;
  if (!VALID_REFLECTION_STATUSES.has(reflectionStatus)) {
    throw new KnowledgeApplyValidationError(
      `invalid reflection_status: ${JSON.stringify(reflectionStatus)}`,
    );
  }

  const confidence = parseConfidence(payload.confidence);
  const aliases = hasPayloadKey(payload, "aliases")
    ? toStringArray(payload.aliases)
    : [];
  const tags = hasPayloadKey(payload, "tags") ? toStringArray(payload.tags) : [];
  const sourceRefs = provenanceEntriesFromPayload(payload.source_refs);
  const sourceUrl = optionalString(payload.source_url) ?? current.source_url;
  const slug = optionalString(payload.slug) ?? current.slug;
  const now = new Date().toISOString();

  const itemId = randomUUID();
  const rootItemId = current.root_item_id ?? current.id;

  const newVersion = toNumber(current.version) + 1;
  const created = await getKnowledgeRowsOrThrow<{ id: string }>(
    context.db,
    `INSERT INTO knowledge_items (
       id, space_id, project_id, workspace_id, root_item_id, supersedes_item_id,
       item_type, slug, aliases_json, title, content, content_json, content_format,
       content_schema_version, plain_text, excerpt, status, visibility, verification_status,
       reflection_status, tags_json, confidence, source_url, owner_user_id, created_by_user_id,
       created_by_run_id, source_activity_id, source_artifact_id, created_from_proposal_id,
       approved_by_user_id, version, created_at, updated_at
     )
     VALUES (
       $1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10,
       $11, $12::jsonb, $13, $14,
       $15, $16, 'active', $17, $18, $19,
       $20::jsonb, $21, $22, $23, $24,
       $25, $26, $27,
       $28, $29, $30,
       $31, $32, $33, $34
     )
     RETURNING id`,
    [
      itemId,
      context.proposal.space_id,
      current.project_id,
      current.workspace_id,
      rootItemId,
      current.id,
      current.item_type,
      slug,
      JSON.stringify(aliases),
      title,
      content,
      contentJson ? JSON.stringify(contentJson) : null,
      contentFormat,
      numberValue(payload.content_schema_version) ?? toNumber(current.content_schema_version),
      derivePlainText({ title, content, contentJson }),
      derivePlainText({ title, content, contentJson }).slice(0, 280),
      current.visibility,
      verificationStatus,
      reflectionStatus,
      JSON.stringify(tags),
      confidence,
      sourceUrl,
      current.owner_user_id,
      context.proposal.created_by_user_id,
      context.proposal.created_by_run_id,
      current.source_activity_id,
      current.source_artifact_id,
      context.proposal.id,
      context.userId,
      newVersion,
      now,
      now,
    ],
  );

  await context.db.query(
    `UPDATE knowledge_items
       SET status = 'superseded', updated_at = $2
     WHERE id = $1 AND space_id = $3`,
    [current.id, now, context.proposal.space_id],
  );

  const updateTargetId = created.id;

  await writeSourceRefs({
    db: context.db,
    spaceId: context.proposal.space_id,
    targetId: updateTargetId,
    entries: sourceRefs,
  });

  const row = await getKnowledgeItemById(context.db, context.proposal.space_id, itemId);
  return {
    result_type: "knowledge_item",
    result: { knowledge_item: serializeKnowledgeItem(row) },
  };
}

async function applyKnowledgeArchiveProposal(
  context: ProposalApplyContext,
): Promise<ProposalApplyResult> {
  const payload = context.proposal.payload_json ?? {};
  ensureOperation(payload, "archive");

  const targetId = expectString(payload.target_item_id);
  const item = await requireKnowledgeItem(context.db, context.proposal.space_id, targetId, context.proposal);
  if (item.status !== "active" && item.status !== "draft") {
    throw new KnowledgeApplyValidationError("target Knowledge item is not active");
  }

  const now = new Date().toISOString();
  await context.db.query(
    `UPDATE knowledge_items
      SET status = 'archived', archived_at = $2, updated_at = $2
     WHERE id = $1 AND space_id = $3`,
    [targetId, now, context.proposal.space_id],
  );

  const row = await getKnowledgeItemById(context.db, context.proposal.space_id, targetId);
  return {
    result_type: "knowledge_item",
    result: { knowledge_item: serializeKnowledgeItem(row) },
  };
}

async function applyKnowledgeRelationCreateProposal(
  context: ProposalApplyContext,
): Promise<ProposalApplyResult> {
  const payload = context.proposal.payload_json ?? {};
  ensureOperation(payload, "relation_create");

  const fromItemId = expectString(payload.from_item_id);
  const toItemId = expectString(payload.to_item_id);
  const relationType = expectString(payload.relation_type);
  if (!VALID_RELATION_TYPES.has(relationType)) {
    throw new KnowledgeApplyValidationError(`invalid relation_type: ${JSON.stringify(relationType)}`);
  }

  const status = optionalString(payload.status) ?? "active";
  if (!VALID_RELATION_STATUSES.has(status)) {
    throw new KnowledgeApplyValidationError(`invalid relation status: ${JSON.stringify(status)}`);
  }

  const confidence = parseConfidence(payload.confidence);
  const evidenceSummary = optionalString(payload.evidence_summary);
  const fromItem = await requireKnowledgeItem(context.db, context.proposal.space_id, fromItemId, context.proposal);
  const toItem = await requireKnowledgeItem(context.db, context.proposal.space_id, toItemId, context.proposal);
  if (fromItem.space_id !== toItem.space_id || fromItem.space_id !== context.proposal.space_id) {
    throw new KnowledgeApplyValidationError("Knowledge relation endpoints must be in the same space");
  }

  if (status === "active") {
    const existing = await context.db.query<{ id: string }>(
      `SELECT id FROM knowledge_item_relations
         WHERE space_id = $1 AND from_item_id = $2 AND to_item_id = $3 AND relation_type = $4 AND status = 'active'`,
      [context.proposal.space_id, fromItemId, toItemId, relationType],
    );
    if (existing.rows.length > 0) {
      throw new KnowledgeApplyValidationError("active Knowledge relation already exists");
    }
  }

  const relationId = randomUUID();
  await context.db.query(
    `INSERT INTO knowledge_item_relations (
       id, space_id, from_item_id, to_item_id, relation_type, status, confidence,
       evidence_summary, source_proposal_id, created_by_user_id, created_by_agent_id
     ) VALUES (
       $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, NULL
     )`,
    [
      relationId,
      context.proposal.space_id,
      fromItemId,
      toItemId,
      relationType,
      status,
      confidence,
      evidenceSummary,
      context.proposal.id,
      context.proposal.created_by_user_id,
    ],
  );

  const row = await getKnowledgeRelationById(context.db, context.proposal.space_id, relationId);
  return {
    result_type: "knowledge_relation",
    result: { knowledge_relation: serializeKnowledgeRelation(row) },
  };
}

async function applyKnowledgeRelationDeleteProposal(
  context: ProposalApplyContext,
): Promise<ProposalApplyResult> {
  const payload = context.proposal.payload_json ?? {};
  ensureOperation(payload, "relation_delete");

  const relationId = expectString(payload.relation_id);
  const relation = await context.db.query<KnowledgeRelationRow>(
    `SELECT ${KNOWLEDGE_RELATION_COLUMNS}
       FROM knowledge_item_relations
      WHERE id = $1 AND space_id = $2`,
    [relationId, context.proposal.space_id],
  );
  if (relation.rows.length === 0) {
    throw new KnowledgeApplyValidationError("Knowledge relation not found");
  }
  const existing = relation.rows[0]!;

  await requireKnowledgeItemForMutation(context.db, context.proposal.space_id, existing.from_item_id, context.proposal);
  await requireKnowledgeItemForMutation(context.db, context.proposal.space_id, existing.to_item_id, context.proposal);

  await context.db.query(
    `UPDATE knowledge_item_relations
       SET status = 'archived', updated_at = $3
     WHERE id = $1 AND space_id = $2`,
    [relationId, context.proposal.space_id, new Date().toISOString()],
  );

  const row = await getKnowledgeRelationById(context.db, context.proposal.space_id, relationId);
  return {
    result_type: "knowledge_relation",
    result: { knowledge_relation: serializeKnowledgeRelation(row) },
  };
}

async function requireKnowledgeItem(
  db: Queryable,
  spaceId: string,
  itemId: string,
  proposal: ProposalApplyContext["proposal"],
): Promise<KnowledgeItemRow> {
  const row = await getKnowledgeItemById(db, spaceId, itemId);
  if (row.status !== "active" && row.status !== "draft") {
    throw new KnowledgeApplyValidationError("target Knowledge item is not active");
  }
  if (!canApplyKnowledgeMutation(row, proposal)) {
    throw new KnowledgeApplyValidationError("Knowledge item not found or not editable");
  }
  return row;
}

async function requireKnowledgeItemForMutation(
  db: Queryable,
  spaceId: string,
  itemId: string,
  proposal: ProposalApplyContext["proposal"],
): Promise<KnowledgeItemRow> {
  const row = await getKnowledgeItemById(db, spaceId, itemId);
  if (!canApplyKnowledgeMutation(row, proposal)) {
    throw new KnowledgeApplyValidationError("Knowledge relation not found");
  }
  return row;
}

async function getKnowledgeItemById(db: Queryable, spaceId: string, itemId: string): Promise<KnowledgeItemRow> {
  const result = await db.query<KnowledgeItemRow>(
    `SELECT ${KNOWLEDGE_ITEM_COLUMNS}
       FROM knowledge_items
      WHERE id = $1 AND space_id = $2`,
    [itemId, spaceId],
  );
  const row = result.rows[0];
  if (!row) throw new KnowledgeApplyValidationError("Knowledge item not found");
  return row;
}

async function getKnowledgeRelationById(
  db: Queryable,
  spaceId: string,
  relationId: string,
): Promise<KnowledgeRelationRow> {
  const result = await db.query<KnowledgeRelationRow>(
    `SELECT ${KNOWLEDGE_RELATION_COLUMNS}
       FROM knowledge_item_relations
      WHERE id = $1 AND space_id = $2`,
    [relationId, spaceId],
  );
  const row = result.rows[0];
  if (!row) {
    throw new KnowledgeApplyValidationError("Knowledge relation not found");
  }
  return row;
}

async function getKnowledgeRowsOrThrow<Row extends { id: string }>(
  db: Queryable,
  sql: string,
  params: readonly unknown[],
): Promise<Row> {
  const result = await db.query<Row>(sql, params);
  const row = result.rows[0];
  if (!row) throw new KnowledgeApplyValidationError("Knowledge apply failed");
  return row;
}

async function writeSourceRefs(input: {
  db: Queryable;
  spaceId: string;
  targetId: string;
  entries: ProvenanceEntry[];
}): Promise<void> {
  if (!input.entries.length) return;
  await writeProvenanceLinks(input.db, {
    spaceId: input.spaceId,
    targetType: TARGET_KNOWLEDGE,
    targetId: input.targetId,
    entries: input.entries,
  });
}

function provenanceEntriesFromPayload(sourceRefs: unknown): ProvenanceEntry[] {
  if (!Array.isArray(sourceRefs)) return [];

  const entries: ProvenanceEntry[] = [];
  const seen = new Set<string>();
  for (const raw of sourceRefs) {
    if (raw === null || raw === undefined || typeof raw !== "object" || Array.isArray(raw)) continue;
    const obj = raw as Record<string, unknown>;
    const rawType = obj.source_type ?? obj.type;
    const rawId = obj.source_id ?? obj.id;
    if (typeof rawType !== "string" || typeof rawId !== "string") continue;
    const sourceType = rawType.trim();
    const sourceId = rawId.trim();
    if (!sourceType || !sourceId) continue;
    if (!VALID_PROVENANCE_TYPES.has(sourceType)) continue;

    const entry: ProvenanceEntry = {
      source_type: sourceType,
      source_id: sourceId,
    };
    const trust = optionalString(obj.source_trust);
    if (trust) {
      entry.source_trust = trust;
    }

    const evidence = optionalObject(obj.evidence_json);
    if (evidence) {
      entry.evidence_json = evidence;
    }

    const key = `${entry.source_type}:::${entry.source_id}:::${entry.source_trust ?? ""}`;
    if (seen.has(key)) continue;
    seen.add(key);
    entries.push(entry);
  }

  return entries;
}

function serializeKnowledgeItem(row: KnowledgeItemRow): Record<string, unknown> {
  return {
    id: row.id,
    space_id: row.space_id,
    project_id: row.project_id,
    workspace_id: row.workspace_id,
    root_item_id: row.root_item_id,
    supersedes_item_id: row.supersedes_item_id,
    redirect_to_item_id: row.redirect_to_item_id,
    item_type: row.item_type,
    slug: row.slug,
    aliases: parseJsonArray(row.aliases_json),
    title: row.title,
    content: row.content,
    content_json: row.content_json,
    content_format: row.content_format,
    content_schema_version: toNumber(row.content_schema_version),
    plain_text: row.plain_text,
    excerpt: row.excerpt,
    status: row.status,
    visibility: row.visibility,
    verification_status: row.verification_status,
    reflection_status: row.reflection_status,
    tags: parseJsonArray(row.tags_json),
    confidence: row.confidence,
    source_url: row.source_url,
    owner_user_id: row.owner_user_id,
    created_by_user_id: row.created_by_user_id,
    created_by_agent_id: row.created_by_agent_id,
    created_by_run_id: row.created_by_run_id,
    source_activity_id: row.source_activity_id,
    source_artifact_id: row.source_artifact_id,
    created_from_proposal_id: row.created_from_proposal_id,
    approved_by_user_id: row.approved_by_user_id,
    version: toNumber(row.version),
    created_at: normalizeDate(row.created_at),
    updated_at: normalizeDate(row.updated_at),
    archived_at: normalizeDate(row.archived_at),
    deprecated_at: normalizeDate(row.deprecated_at),
  };
}

function serializeKnowledgeRelation(row: KnowledgeRelationRow): Record<string, unknown> {
  return {
    id: row.id,
    space_id: row.space_id,
    from_item_id: row.from_item_id,
    to_item_id: row.to_item_id,
    relation_type: row.relation_type,
    status: row.status,
    confidence: row.confidence,
    evidence_summary: row.evidence_summary,
    source_proposal_id: row.source_proposal_id,
    created_by_user_id: row.created_by_user_id,
    created_by_agent_id: row.created_by_agent_id,
    created_at: normalizeDate(row.created_at),
    updated_at: normalizeDate(row.updated_at),
  };
}

function canApplyKnowledgeMutation(
  item: KnowledgeItemRow,
  proposal: ProposalApplyContext["proposal"],
): boolean {
  if (item.space_id !== proposal.space_id) return false;
  if (item.visibility === "space_shared" || item.visibility === "workspace_shared") {
    return true;
  }
  if (item.visibility === "private" || item.visibility === "restricted") {
    const ownerId = item.owner_user_id ?? item.created_by_user_id;
    return ownerId !== null && proposal.created_by_user_id === ownerId;
  }
  return false;
}

function ensureOperation(payload: Record<string, unknown>, operation: string): void {
  const value = optionalString(payload.operation);
  if (value !== operation) {
    throw new KnowledgeApplyValidationError(`expected operation=${JSON.stringify(operation)}`);
  }
}

function expectString(value: unknown): string {
  if (typeof value !== "string" || !value.trim()) {
    throw new KnowledgeApplyValidationError("missing required string value");
  }
  return value.trim();
}

function optionalString(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const normalized = value.trim();
  return normalized ? normalized : null;
}

function optionalObject(value: unknown): Record<string, unknown> | null {
  if (value === null || value === undefined) return null;
  if (typeof value === "object" && !Array.isArray(value)) return value as Record<string, unknown>;
  return null;
}

function hasPayloadKey(payload: Record<string, unknown>, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(payload, key);
}

function toStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((entry): entry is string => typeof entry === "string");
}

function parseJsonArray(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((entry): entry is string => typeof entry === "string")
    : [];
}

function parseConfidence(value: unknown): number | null {
  if (value == null) return null;
  if (typeof value === "number" && Number.isFinite(value)) {
    if (value < 0 || value > 1) {
      throw new KnowledgeApplyValidationError("confidence must be between 0 and 1");
    }
    return value;
  }
  if (typeof value === "string" && value.trim() !== "") {
    const parsed = Number(value);
    if (Number.isFinite(parsed) && parsed >= 0 && parsed <= 1) {
      return parsed;
    }
  }
  throw new KnowledgeApplyValidationError("confidence must be a number between 0 and 1");
}

function numberValue(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() !== "") {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return null;
}

function toNumber(value: unknown): number {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() !== "") {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return 1;
}

function derivePlainText(input: {
  title: string;
  content: string;
  contentJson?: Record<string, unknown> | null;
}): string {
  const chunks = [input.title, contentFromJson(input.contentJson), input.content];
  return chunks
    .map((entry) => typeof entry === "string" ? entry.trim() : "")
    .filter(Boolean)
    .join(" ");
}

function contentFromJson(node: Record<string, unknown> | null | undefined): string {
  if (!node) return "";
  const out: string[] = [];
  const walk = (value: unknown): void => {
    if (!value) return;
    if (typeof value === "string") {
      const valueText = value.trim();
      if (valueText) out.push(valueText);
      return;
    }
    if (Array.isArray(value)) {
      for (const child of value) walk(child);
      return;
    }
    if (typeof value === "object") {
      const objectValue = value as Record<string, unknown>;
      if (typeof objectValue.text === "string" && objectValue.text.trim()) {
        out.push(objectValue.text.trim());
      }
      const nested = objectValue.content;
      if (nested !== undefined) walk(nested);
      return;
    }
  };
  walk(node);
  return out.join(" ");
}

function normalizeDate(value: unknown): string | null {
  if (value == null) return null;
  if (typeof value === "string") return value;
  if (value instanceof Date) return value.toISOString();
  return new Date(value as string | number | Date).toISOString();
}

class KnowledgeApplyValidationError extends Error {
  readonly statusCode = 422;
}
