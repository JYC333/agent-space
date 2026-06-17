import { randomUUID } from "node:crypto";
import {
  HttpError,
  canReadByVisibility,
  countFromRow,
  dateIso,
  numberValue,
  objectValue,
  optionalObject,
  optionalString,
  page,
  requiredString,
  stringArray,
  type SpaceUserIdentity,
  type Queryable,
} from "../routeUtils/common";
import { proposalToOut, type ProposalRow } from "../proposals/repository";
import type { ProposalOut } from "@agent-space/protocol" with { "resolution-mode": "import" };

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
  content_json: unknown;
  content_format: string;
  content_schema_version: unknown;
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
  version: unknown;
  created_at: unknown;
  updated_at: unknown;
  archived_at: unknown;
  deprecated_at: unknown;
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
  created_from_assessment_id: string | null;
  created_at: unknown;
  updated_at: unknown;
}

interface SourceRow {
  id: string;
  space_id: string;
  source_type: string;
  title: string;
  uri: string | null;
  content_ref: string | null;
  raw_text: string | null;
  summary: string | null;
  metadata_json: unknown;
  status: string;
  source_activity_id: string | null;
  created_by_user_id: string | null;
  created_at: unknown;
  updated_at: unknown;
}

interface NoteRow {
  id: string;
  space_id: string;
  title: string;
  content_json: unknown;
  content_format: string;
  content_schema_version: unknown;
  plain_text: string | null;
  excerpt: string | null;
  status: string;
  primary_project_id: string | null;
  collection_id: string | null;
  created_from_activity_id: string | null;
  created_by_user_id: string | null;
  created_at: unknown;
  updated_at: unknown;
  archived_at: unknown;
  deleted_at: unknown;
}

interface NoteCollectionRow {
  id: string;
  space_id: string;
  parent_id: string | null;
  name: string;
  system_role: string;
  sort_order: number | string;
  is_system: boolean;
  is_hidden: boolean;
  created_at: unknown;
  updated_at: unknown;
}

interface EntityLinkRow {
  id: string;
  space_id: string;
  source_type: string;
  source_id: string;
  target_type: string;
  target_id: string;
  link_type: string;
  confidence: number | null;
  status: string;
  created_by_user_id: string | null;
  created_at: unknown;
}

interface ProvenanceLinkRow {
  source_type: string;
  source_id: string;
  source_trust: string | null;
  evidence_json: unknown;
  created_at: unknown;
}

const KNOWLEDGE_ITEM_COLUMNS = `
  id, space_id, project_id, workspace_id, root_item_id, supersedes_item_id,
  redirect_to_item_id, item_type, slug, aliases_json, title, content, content_json,
  content_format, content_schema_version, plain_text, excerpt, status, visibility,
  verification_status, reflection_status, tags_json, confidence, source_url,
  owner_user_id, created_by_user_id, created_by_agent_id, created_by_run_id,
  source_activity_id, source_artifact_id, created_from_proposal_id,
  approved_by_user_id, version, created_at, updated_at, archived_at, deprecated_at
`;

const KNOWLEDGE_RELATION_COLUMNS = `
  id, space_id, from_item_id, to_item_id, relation_type, status, confidence,
  evidence_summary, source_proposal_id, created_by_user_id, created_by_agent_id,
  created_from_assessment_id, created_at, updated_at
`;

const SOURCE_COLUMNS = `
  id, space_id, source_type, title, uri, content_ref, raw_text, summary,
  metadata_json, status, source_activity_id, created_by_user_id, created_at, updated_at
`;

const NOTE_COLUMNS = `
  n.id, n.space_id, n.title, n.content_json, n.content_format,
  n.content_schema_version, n.plain_text, n.excerpt, n.status,
  n.primary_project_id, n.created_from_activity_id, n.created_by_user_id,
  n.created_at, n.updated_at, n.archived_at, n.deleted_at,
  first_collection.collection_id
`;

const NOTE_COLLECTION_COLUMNS = `
  id, space_id, parent_id, name, system_role, sort_order, is_system,
  is_hidden, created_at, updated_at
`;

const ENTITY_LINK_COLUMNS = `
  id, space_id, source_type, source_id, target_type, target_id, link_type,
  confidence, status, created_by_user_id, created_at
`;

const ITEM_TYPES = new Set(["concept", "claim", "lesson", "procedure", "decision", "question", "answer", "summary"]);
const CONTENT_FORMATS = new Set(["markdown", "plain", "prosemirror_json"]);
const KNOWLEDGE_VISIBILITIES = new Set(["private", "space_shared", "workspace_shared", "restricted"]);
const RELATION_TYPES = new Set([
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
const SOURCE_TYPES = new Set(["activity_record", "chat_capture", "webpage", "article", "paper", "pdf", "file", "email", "manual_reference", "external_note"]);
const SOURCE_STATUSES = new Set(["raw", "processing", "processed", "archived", "error"]);

export class PgKnowledgeRepository {
  constructor(private readonly db: Queryable) {}

  async summary(identity: SpaceUserIdentity): Promise<Record<string, unknown>> {
    const [notes, wiki, sources] = await Promise.all([
      this.db.query<{ status: string; total: string }>(
        `SELECT status, count(*)::text AS total FROM notes WHERE space_id = $1 GROUP BY status`,
        [identity.spaceId],
      ),
      this.db.query<{ total: string }>(
        `SELECT count(*)::text AS total
           FROM knowledge_items
          WHERE space_id = $1 AND status = 'active'`,
        [identity.spaceId],
      ),
      this.db.query<{ total: string }>(
        `SELECT count(*)::text AS total FROM sources WHERE space_id = $1`,
        [identity.spaceId],
      ),
    ]);
    const noteCounts = { active: 0, archived: 0, deleted: 0, total: 0 };
    for (const row of notes.rows) {
      const total = Number(row.total);
      if (row.status === "active") noteCounts.active = total;
      if (row.status === "archived") noteCounts.archived = total;
      if (row.status === "deleted") noteCounts.deleted = total;
      noteCounts.total += total;
    }
    return {
      notes: noteCounts,
      wiki: { active: countFromRow(wiki.rows[0]) },
      sources: { total: countFromRow(sources.rows[0]) },
    };
  }

  async listItems(identity: SpaceUserIdentity, filters: {
    itemType: string | null;
    status: string | null;
    visibility: string | null;
    projectId: string | null;
    workspaceId: string | null;
    q: string | null;
    limit: number;
    offset: number;
  }): Promise<Record<string, unknown>> {
    const built = this.buildItemWhere(identity, filters);
    const total = await this.db.query<{ total: string }>(
      `SELECT count(*)::text AS total FROM knowledge_items ${built.where}`,
      built.params,
    );
    const rows = await this.db.query<KnowledgeItemRow>(
      `SELECT ${KNOWLEDGE_ITEM_COLUMNS}
         FROM knowledge_items
        ${built.where}
        ORDER BY updated_at DESC, id DESC
        LIMIT $${built.params.length + 1} OFFSET $${built.params.length + 2}`,
      [...built.params, filters.limit, filters.offset],
    );
    return page(rows.rows.map(knowledgeSummaryOut), countFromRow(total.rows[0]), filters.limit, filters.offset);
  }

  async getItem(identity: SpaceUserIdentity, itemId: string): Promise<Record<string, unknown> | null> {
    const row = await this.getVisibleItemRow(identity, itemId);
    if (!row) return null;
    return knowledgeItemOut(row, await this.listKnowledgeSourceRefs(identity, row.id));
  }

  async itemRelations(identity: SpaceUserIdentity, itemId: string): Promise<Record<string, unknown>[]> {
    const item = await this.getVisibleItemRow(identity, itemId);
    if (!item) throw new HttpError(404, "Knowledge item not found");
    const rows = await this.db.query<KnowledgeRelationRow>(
      `SELECT ${KNOWLEDGE_RELATION_COLUMNS}
         FROM knowledge_item_relations
        WHERE space_id = $1 AND (from_item_id = $2 OR to_item_id = $2)
          AND status <> 'archived'
        ORDER BY updated_at DESC, id DESC`,
      [identity.spaceId, itemId],
    );
    return rows.rows.map(relationOut);
  }

  async entityLinks(identity: SpaceUserIdentity, filters: Record<string, string | undefined>): Promise<Record<string, unknown>[]> {
    const params: unknown[] = [identity.spaceId];
    const clauses = ["space_id = $1"];
    const add = (value: unknown): string => {
      params.push(value);
      return `$${params.length}`;
    };
    for (const key of ["source_type", "source_id", "target_type", "target_id", "status"]) {
      const value = optionalString(filters[key]);
      if (value) clauses.push(`${key} = ${add(value)}`);
    }
    const rows = await this.db.query<EntityLinkRow>(
      `SELECT ${ENTITY_LINK_COLUMNS}
         FROM entity_links
        WHERE ${clauses.join(" AND ")}
        ORDER BY created_at DESC, id DESC`,
      params,
    );
    return rows.rows.map(entityLinkOut);
  }

  async proposeCreate(identity: SpaceUserIdentity, body: Record<string, unknown>): Promise<ProposalOut> {
    const itemType = requiredString(body.item_type ?? "concept", "item_type");
    if (!ITEM_TYPES.has(itemType)) throw new HttpError(422, "invalid item_type");
    const contentFormat = requiredString(body.content_format ?? "markdown", "content_format");
    if (!CONTENT_FORMATS.has(contentFormat)) throw new HttpError(422, "invalid content_format");
    const visibility = requiredString(body.visibility ?? "space_shared", "visibility");
    if (!KNOWLEDGE_VISIBILITIES.has(visibility)) throw new HttpError(422, "invalid visibility");
    const payload = {
      ...body,
      operation: "create",
      item_type: itemType,
      title: requiredString(body.title, "title"),
      content: requiredString(body.content, "content"),
      content_format: contentFormat,
      visibility,
      tags: stringArray(body.tags),
      source_refs: Array.isArray(body.source_refs) ? body.source_refs : [],
    };
    return this.insertKnowledgeProposal(identity, {
      proposalType: "knowledge_create",
      title: payload.title,
      payload,
      rationale: optionalString(body.rationale) ?? "Knowledge creation requested.",
      workspaceId: optionalString(body.workspace_id),
      projectId: optionalString(body.project_id),
    });
  }

  async proposeUpdate(identity: SpaceUserIdentity, itemId: string, body: Record<string, unknown>): Promise<ProposalOut> {
    const item = await this.getVisibleItemRow(identity, itemId);
    if (!item) throw new HttpError(404, "Knowledge item not found");
    if (!canMutateKnowledge(item, identity.userId)) throw new HttpError(404, "Knowledge item not found");
    const contentFormat = requiredString(body.content_format ?? item.content_format, "content_format");
    if (!CONTENT_FORMATS.has(contentFormat)) throw new HttpError(422, "invalid content_format");
    const payload = {
      ...body,
      operation: "update",
      target_item_id: itemId,
      title: requiredString(body.title, "title"),
      content: requiredString(body.content, "content"),
      content_format: contentFormat,
      tags: stringArray(body.tags),
      source_refs: Array.isArray(body.source_refs) ? body.source_refs : [],
    };
    return this.insertKnowledgeProposal(identity, {
      proposalType: "knowledge_update",
      title: `Update: ${payload.title}`,
      payload,
      rationale: optionalString(body.rationale) ?? "Knowledge update requested.",
      workspaceId: item.workspace_id,
      projectId: item.project_id,
    });
  }

  async proposeArchive(identity: SpaceUserIdentity, itemId: string): Promise<ProposalOut> {
    const item = await this.getVisibleItemRow(identity, itemId);
    if (!item || !canMutateKnowledge(item, identity.userId)) {
      throw new HttpError(404, "Knowledge item not found");
    }
    return this.insertKnowledgeProposal(identity, {
      proposalType: "knowledge_archive",
      title: `Archive: ${item.title}`,
      payload: {
        operation: "archive",
        target_item_id: itemId,
        proposed_content: item.content,
      },
      rationale: "Knowledge archive requested.",
      workspaceId: item.workspace_id,
      projectId: item.project_id,
    });
  }

  async proposeRelation(identity: SpaceUserIdentity, body: Record<string, unknown>): Promise<ProposalOut> {
    const fromItemId = requiredString(body.from_item_id, "from_item_id");
    const toItemId = requiredString(body.to_item_id, "to_item_id");
    const relationType = requiredString(body.relation_type, "relation_type");
    if (!RELATION_TYPES.has(relationType)) throw new HttpError(422, "invalid relation_type");
    const fromItem = await this.getVisibleItemRow(identity, fromItemId);
    const toItem = await this.getVisibleItemRow(identity, toItemId);
    if (!fromItem || !toItem) throw new HttpError(404, "Knowledge relation endpoint not found");
    if (!canMutateKnowledge(fromItem, identity.userId) || !canMutateKnowledge(toItem, identity.userId)) {
      throw new HttpError(404, "Knowledge relation endpoint not found");
    }
    return this.insertKnowledgeProposal(identity, {
      proposalType: "knowledge_relation_create",
      title: `Relate: ${fromItem.title} -> ${toItem.title}`,
      payload: {
        operation: "relation_create",
        from_item_id: fromItemId,
        to_item_id: toItemId,
        relation_type: relationType,
        status: optionalString(body.status) ?? "active",
        confidence: confidence(body.confidence),
        evidence_summary: optionalString(body.evidence_summary),
      },
      rationale: optionalString(body.rationale) ?? "Knowledge relation requested.",
      workspaceId: fromItem.workspace_id,
      projectId: fromItem.project_id,
    });
  }

  async proposeRelationArchive(identity: SpaceUserIdentity, relationId: string): Promise<ProposalOut> {
    const relation = await this.getRelationRow(identity, relationId);
    if (!relation) throw new HttpError(404, "Knowledge relation not found");
    const fromItem = await this.getVisibleItemRow(identity, relation.from_item_id);
    const toItem = await this.getVisibleItemRow(identity, relation.to_item_id);
    if (!fromItem || !toItem || !canMutateKnowledge(fromItem, identity.userId) || !canMutateKnowledge(toItem, identity.userId)) {
      throw new HttpError(404, "Knowledge relation not found");
    }
    return this.insertKnowledgeProposal(identity, {
      proposalType: "knowledge_relation_delete",
      title: "Archive knowledge relation",
      payload: {
        operation: "relation_delete",
        relation_id: relationId,
      },
      rationale: "Knowledge relation archive requested.",
      workspaceId: fromItem.workspace_id,
      projectId: fromItem.project_id,
    });
  }

  async listSources(identity: SpaceUserIdentity, filters: {
    sourceType: string | null;
    status: string | null;
    q: string | null;
    limit: number;
    offset: number;
  }): Promise<Record<string, unknown>> {
    const params: unknown[] = [identity.spaceId];
    const clauses = ["space_id = $1"];
    const add = (value: unknown): string => {
      params.push(value);
      return `$${params.length}`;
    };
    if (filters.sourceType) clauses.push(`source_type = ${add(filters.sourceType)}`);
    if (filters.status) clauses.push(`status = ${add(filters.status)}`);
    if (filters.q) clauses.push(`(title ILIKE ${add(`%${filters.q}%`)} OR uri ILIKE $${params.length})`);
    const where = `WHERE ${clauses.join(" AND ")}`;
    const total = await this.db.query<{ total: string }>(
      `SELECT count(*)::text AS total FROM sources ${where}`,
      params,
    );
    const rows = await this.db.query<SourceRow>(
      `SELECT ${SOURCE_COLUMNS}
         FROM sources
        ${where}
        ORDER BY updated_at DESC, id DESC
        LIMIT $${params.length + 1} OFFSET $${params.length + 2}`,
      [...params, filters.limit, filters.offset],
    );
    return page(rows.rows.map(sourceSummaryOut), countFromRow(total.rows[0]), filters.limit, filters.offset);
  }

  async getSource(identity: SpaceUserIdentity, sourceId: string): Promise<Record<string, unknown> | null> {
    const row = await this.getSourceRow(identity, sourceId);
    return row ? sourceOut(row) : null;
  }

  async createSource(identity: SpaceUserIdentity, body: Record<string, unknown>): Promise<Record<string, unknown>> {
    const now = new Date().toISOString();
    const sourceType = requiredString(body.source_type, "source_type");
    if (!SOURCE_TYPES.has(sourceType)) throw new HttpError(422, "invalid source_type");
    const status = optionalString(body.status) ?? "raw";
    if (!SOURCE_STATUSES.has(status)) throw new HttpError(422, "invalid source status");
    const result = await this.db.query<SourceRow>(
      `INSERT INTO sources (
         id, space_id, source_type, title, uri, content_ref, raw_text, summary,
         metadata_json, status, source_activity_id, created_by_user_id,
         created_at, updated_at
       ) VALUES (
         $1, $2, $3, $4, $5, $6, $7, $8,
         $9::jsonb, $10, $11, $12,
         $13, $13
       )
       RETURNING ${SOURCE_COLUMNS}`,
      [
        randomUUID(),
        identity.spaceId,
        sourceType,
        requiredString(body.title, "title"),
        optionalString(body.uri),
        optionalString(body.content_ref),
        optionalString(body.raw_text),
        optionalString(body.summary),
        JSON.stringify(optionalObject(body.metadata) ?? {}),
        status,
        optionalString(body.source_activity_id),
        identity.userId,
        now,
      ],
    );
    return sourceOut(result.rows[0]!);
  }

  async updateSource(identity: SpaceUserIdentity, sourceId: string, body: Record<string, unknown>): Promise<Record<string, unknown>> {
    const existing = await this.getSourceRow(identity, sourceId);
    if (!existing) throw new HttpError(404, "Source not found");
    const now = new Date().toISOString();
    const status = optionalString(body.status);
    if (status && !SOURCE_STATUSES.has(status)) throw new HttpError(422, "invalid source status");
    const result = await this.db.query<SourceRow>(
      `UPDATE sources SET
         title = COALESCE($3, title),
         uri = CASE WHEN $4::boolean THEN $5 ELSE uri END,
         content_ref = CASE WHEN $6::boolean THEN $7 ELSE content_ref END,
         raw_text = CASE WHEN $8::boolean THEN $9 ELSE raw_text END,
         summary = CASE WHEN $10::boolean THEN $11 ELSE summary END,
         metadata_json = CASE WHEN $12::boolean THEN $13::jsonb ELSE metadata_json END,
         status = COALESCE($14, status),
         updated_at = $15
       WHERE id = $1 AND space_id = $2
       RETURNING ${SOURCE_COLUMNS}`,
      [
        sourceId,
        identity.spaceId,
        optionalString(body.title),
        Object.hasOwn(body, "uri"),
        optionalString(body.uri),
        Object.hasOwn(body, "content_ref"),
        optionalString(body.content_ref),
        Object.hasOwn(body, "raw_text"),
        optionalString(body.raw_text),
        Object.hasOwn(body, "summary"),
        optionalString(body.summary),
        Object.hasOwn(body, "metadata"),
        JSON.stringify(optionalObject(body.metadata) ?? {}),
        status,
        now,
      ],
    );
    return sourceOut(result.rows[0]!);
  }

  async archiveSource(identity: SpaceUserIdentity, sourceId: string): Promise<Record<string, unknown>> {
    const row = await this.updateSource(identity, sourceId, { status: "archived" });
    return row;
  }

  async listItemSources(identity: SpaceUserIdentity, itemId: string): Promise<Record<string, unknown>[]> {
    const item = await this.getVisibleItemRow(identity, itemId);
    if (!item) throw new HttpError(404, "Knowledge item not found");
    return this.listKnowledgeItemSourceLinks("knowledge_item_id", itemId, identity.spaceId);
  }

  async listSourceItems(identity: SpaceUserIdentity, sourceId: string): Promise<Record<string, unknown>[]> {
    const source = await this.getSourceRow(identity, sourceId);
    if (!source) throw new HttpError(404, "Source not found");
    return this.listKnowledgeItemSourceLinks("source_id", sourceId, identity.spaceId);
  }

  async createItemSource(identity: SpaceUserIdentity, itemId: string, body: Record<string, unknown>): Promise<Record<string, unknown>> {
    const item = await this.getVisibleItemRow(identity, itemId);
    if (!item || !canMutateKnowledge(item, identity.userId)) throw new HttpError(404, "Knowledge item not found");
    const sourceId = requiredString(body.source_id, "source_id");
    if (!(await this.getSourceRow(identity, sourceId))) throw new HttpError(404, "Source not found");
    const now = new Date().toISOString();
    const result = await this.db.query<Record<string, unknown>>(
      `INSERT INTO knowledge_item_sources (
         id, space_id, knowledge_item_id, source_id, relation_type, locator,
         quote, note, confidence, created_by_user_id, created_at
       ) VALUES (
         $1, $2, $3, $4, $5, $6,
         $7, $8, $9, $10, $11
       )
       RETURNING id, space_id, knowledge_item_id, source_id, relation_type,
                 locator, quote, note, confidence, created_by_user_id, created_at`,
      [
        randomUUID(),
        identity.spaceId,
        itemId,
        sourceId,
        optionalString(body.relation_type) ?? "derived_from",
        optionalString(body.locator),
        optionalString(body.quote),
        optionalString(body.note),
        confidence(body.confidence),
        identity.userId,
        now,
      ],
    );
    return normalizeDates(result.rows[0]!);
  }

  async deleteItemSource(identity: SpaceUserIdentity, itemId: string, linkId: string): Promise<void> {
    const item = await this.getVisibleItemRow(identity, itemId);
    if (!item || !canMutateKnowledge(item, identity.userId)) throw new HttpError(404, "Knowledge item not found");
    await this.db.query(
      `DELETE FROM knowledge_item_sources
        WHERE id = $1 AND knowledge_item_id = $2 AND space_id = $3`,
      [linkId, itemId, identity.spaceId],
    );
  }

  async listNotes(identity: SpaceUserIdentity, filters: {
    status: string | null;
    projectId: string | null;
    collectionId: string | null;
    q: string | null;
    limit: number;
    offset: number;
  }): Promise<Record<string, unknown>> {
    const built = buildNoteWhere(identity, filters);
    const total = await this.db.query<{ total: string }>(
      `SELECT count(DISTINCT n.id)::text AS total
         FROM notes n
         LEFT JOIN note_collection_items nci ON nci.note_id = n.id
        ${built.where}`,
      built.params,
    );
    const rows = await this.db.query<NoteRow>(
      `SELECT ${NOTE_COLUMNS}
         FROM notes n
         LEFT JOIN LATERAL (
           SELECT nci.collection_id
             FROM note_collection_items nci
            WHERE nci.note_id = n.id
            ORDER BY nci.created_at ASC
            LIMIT 1
         ) first_collection ON true
         LEFT JOIN note_collection_items nci_filter ON nci_filter.note_id = n.id
        ${built.where}
        ORDER BY n.updated_at DESC, n.id DESC
        LIMIT $${built.params.length + 1} OFFSET $${built.params.length + 2}`,
      [...built.params, filters.limit, filters.offset],
    );
    return page(rows.rows.map(noteSummaryOut), countFromRow(total.rows[0]), filters.limit, filters.offset);
  }

  async listNoteCollections(identity: SpaceUserIdentity): Promise<Record<string, unknown>[]> {
    const rows = await this.db.query<NoteCollectionRow>(
      `SELECT ${NOTE_COLLECTION_COLUMNS}
         FROM note_collections
        WHERE space_id = $1
        ORDER BY sort_order ASC, created_at ASC, id ASC`,
      [identity.spaceId],
    );
    return rows.rows.map(noteCollectionOut);
  }

  async createNoteCollection(
    identity: SpaceUserIdentity,
    body: Record<string, unknown>,
  ): Promise<Record<string, unknown>> {
    const parentId = optionalString(body.parent_id);
    if (parentId) await this.requireNoteCollection(identity, parentId);
    const now = new Date().toISOString();
    const result = await this.db.query<NoteCollectionRow>(
      `INSERT INTO note_collections (
         id, space_id, parent_id, name, system_role, sort_order,
         is_system, is_hidden, created_at, updated_at
       ) VALUES (
         $1, $2, $3, $4, 'normal', $5,
         false, false, $6, $6
       )
       RETURNING ${NOTE_COLLECTION_COLUMNS}`,
      [
        randomUUID(),
        identity.spaceId,
        parentId,
        requiredString(body.name, "name"),
        numberValue(body.sort_order) ?? 0,
        now,
      ],
    );
    return noteCollectionOut(result.rows[0]!);
  }

  async updateNoteCollection(
    identity: SpaceUserIdentity,
    collectionId: string,
    body: Record<string, unknown>,
  ): Promise<Record<string, unknown>> {
    const current = await this.getNoteCollectionRow(identity, collectionId);
    if (!current) throw new HttpError(404, "Note collection not found");
    if (current.is_system && Object.hasOwn(body, "system_role")) {
      throw new HttpError(422, "system_role cannot be changed");
    }
    const parentId = Object.hasOwn(body, "parent_id")
      ? optionalString(body.parent_id)
      : current.parent_id;
    if (parentId === collectionId) throw new HttpError(422, "parent_id cannot reference the same collection");
    if (parentId) await this.requireNoteCollection(identity, parentId);
    const now = new Date().toISOString();
    const result = await this.db.query<NoteCollectionRow>(
      `UPDATE note_collections
          SET parent_id = $3,
              name = COALESCE($4, name),
              sort_order = COALESCE($5::int, sort_order),
              is_hidden = COALESCE($6::boolean, is_hidden),
              updated_at = $7
        WHERE id = $1 AND space_id = $2
        RETURNING ${NOTE_COLLECTION_COLUMNS}`,
      [
        collectionId,
        identity.spaceId,
        parentId,
        optionalString(body.name),
        numberValue(body.sort_order),
        typeof body.is_hidden === "boolean" ? body.is_hidden : null,
        now,
      ],
    );
    return noteCollectionOut(result.rows[0]!);
  }

  async deleteNoteCollection(identity: SpaceUserIdentity, collectionId: string): Promise<void> {
    const current = await this.getNoteCollectionRow(identity, collectionId);
    if (!current) throw new HttpError(404, "Note collection not found");
    if (current.is_system) throw new HttpError(422, "System note collections cannot be deleted");
    await this.db.query(
      `DELETE FROM note_collections WHERE id = $1 AND space_id = $2`,
      [collectionId, identity.spaceId],
    );
  }

  async getNote(identity: SpaceUserIdentity, noteId: string): Promise<Record<string, unknown> | null> {
    const row = await this.getNoteRow(identity, noteId);
    return row ? noteOut(row) : null;
  }

  async createNote(identity: SpaceUserIdentity, body: Record<string, unknown>): Promise<Record<string, unknown>> {
    const now = new Date().toISOString();
    const plainText = optionalString(body.plain_text);
    const result = await this.db.query<{ id: string }>(
      `INSERT INTO notes (
         id, space_id, title, content_json, content_format, content_schema_version,
         plain_text, excerpt, status, primary_project_id, created_from_activity_id,
         created_by_user_id, created_at, updated_at
       ) VALUES (
         $1, $2, $3, $4::jsonb, $5, COALESCE($6::int, 1),
         $7, $8, 'active', $9, $10,
         $11, $12, $12
       )
       RETURNING id`,
      [
        randomUUID(),
        identity.spaceId,
        requiredString(body.title, "title"),
        JSON.stringify(optionalObject(body.content_json)),
        optionalString(body.content_format) ?? "markdown",
        numberValue(body.content_schema_version),
        plainText,
        optionalString(body.excerpt) ?? (plainText ? plainText.slice(0, 280) : null),
        optionalString(body.primary_project_id),
        optionalString(body.created_from_activity_id),
        identity.userId,
        now,
      ],
    );
    const note = result.rows[0]!;
    const collectionId = optionalString(body.collection_id);
    if (collectionId) await this.addNoteToCollection(identity, note.id, collectionId);
    return (await this.getNote(identity, note.id))!;
  }

  async updateNote(identity: SpaceUserIdentity, noteId: string, body: Record<string, unknown>): Promise<Record<string, unknown>> {
    if (!(await this.getNoteRow(identity, noteId))) throw new HttpError(404, "Note not found");
    const now = new Date().toISOString();
    const plainText = Object.hasOwn(body, "plain_text") ? optionalString(body.plain_text) : undefined;
    await this.db.query(
      `UPDATE notes SET
         title = COALESCE($3, title),
         content_json = CASE WHEN $4::boolean THEN $5::jsonb ELSE content_json END,
         content_format = COALESCE($6, content_format),
         content_schema_version = COALESCE($7::int, content_schema_version),
         plain_text = CASE WHEN $8::boolean THEN $9 ELSE plain_text END,
         excerpt = CASE WHEN $10::boolean THEN $11 ELSE excerpt END,
         status = COALESCE($12, status),
         primary_project_id = CASE WHEN $13::boolean THEN $14 ELSE primary_project_id END,
         archived_at = CASE WHEN $12 = 'archived' THEN $15::timestamptz ELSE archived_at END,
         deleted_at = CASE WHEN $12 = 'deleted' THEN $15::timestamptz ELSE deleted_at END,
         updated_at = $15
       WHERE id = $1 AND space_id = $2`,
      [
        noteId,
        identity.spaceId,
        optionalString(body.title),
        Object.hasOwn(body, "content_json"),
        JSON.stringify(optionalObject(body.content_json)),
        optionalString(body.content_format),
        numberValue(body.content_schema_version),
        plainText !== undefined,
        plainText ?? null,
        Object.hasOwn(body, "excerpt"),
        optionalString(body.excerpt),
        optionalString(body.status),
        Object.hasOwn(body, "primary_project_id"),
        optionalString(body.primary_project_id),
        now,
      ],
    );
    const collectionId = optionalString(body.collection_id);
    if (collectionId) await this.addNoteToCollection(identity, noteId, collectionId);
    return (await this.getNote(identity, noteId))!;
  }

  async deleteNote(identity: SpaceUserIdentity, noteId: string): Promise<Record<string, unknown>> {
    return this.updateNote(identity, noteId, { status: "deleted" });
  }

  async purgeDeletedNotes(identity: SpaceUserIdentity): Promise<Record<string, unknown>> {
    const result = await this.db.query<{ deleted: string }>(
      `DELETE FROM notes WHERE space_id = $1 AND status = 'deleted' RETURNING id`,
      [identity.spaceId],
    );
    return { deleted: result.rowCount ?? result.rows.length, retention_days: 30 };
  }

  async noteLinks(identity: SpaceUserIdentity, noteId: string, backlinks = false): Promise<Record<string, unknown>[]> {
    if (!(await this.getNoteRow(identity, noteId))) throw new HttpError(404, "Note not found");
    const rows = await this.db.query<EntityLinkRow>(
      `SELECT ${ENTITY_LINK_COLUMNS}
         FROM entity_links
        WHERE space_id = $1
          AND ${backlinks ? "target_type = 'note' AND target_id = $2" : "source_type = 'note' AND source_id = $2"}
        ORDER BY created_at DESC, id DESC`,
      [identity.spaceId, noteId],
    );
    return rows.rows.map(entityLinkOut);
  }

  async createNoteLink(identity: SpaceUserIdentity, noteId: string, body: Record<string, unknown>): Promise<Record<string, unknown>> {
    if (!(await this.getNoteRow(identity, noteId))) throw new HttpError(404, "Note not found");
    const direction = optionalString(body.direction) ?? "outgoing";
    const targetType = requiredString(body.target_type, "target_type");
    const targetId = requiredString(body.target_id, "target_id");
    const sourceType = direction === "incoming" ? targetType : "note";
    const sourceId = direction === "incoming" ? targetId : noteId;
    const finalTargetType = direction === "incoming" ? "note" : targetType;
    const finalTargetId = direction === "incoming" ? noteId : targetId;
    const now = new Date().toISOString();
    const result = await this.db.query<EntityLinkRow>(
      `INSERT INTO entity_links (
         id, space_id, source_type, source_id, target_type, target_id,
         link_type, confidence, status, created_by_user_id, created_at
       ) VALUES (
         $1, $2, $3, $4, $5, $6,
         $7, $8, 'accepted', $9, $10
       )
       RETURNING ${ENTITY_LINK_COLUMNS}`,
      [
        randomUUID(),
        identity.spaceId,
        sourceType,
        sourceId,
        finalTargetType,
        finalTargetId,
        optionalString(body.link_type) ?? "related_to",
        confidence(body.confidence),
        identity.userId,
        now,
      ],
    );
    return entityLinkOut(result.rows[0]!);
  }

  async deleteNoteLink(identity: SpaceUserIdentity, noteId: string, linkId: string): Promise<void> {
    if (!(await this.getNoteRow(identity, noteId))) throw new HttpError(404, "Note not found");
    await this.db.query(
      `DELETE FROM entity_links
        WHERE id = $1 AND space_id = $2
          AND ((source_type = 'note' AND source_id = $3) OR (target_type = 'note' AND target_id = $3))`,
      [linkId, identity.spaceId, noteId],
    );
  }

  private buildItemWhere(
    identity: SpaceUserIdentity,
    filters: {
      itemType: string | null;
      status: string | null;
      visibility: string | null;
      projectId: string | null;
      workspaceId: string | null;
      q: string | null;
    },
  ): { where: string; params: unknown[] } {
    const params: unknown[] = [identity.spaceId, identity.userId];
    const clauses = [
      "space_id = $1",
      "(visibility IN ('space_shared', 'workspace_shared') OR owner_user_id = $2 OR created_by_user_id = $2)",
    ];
    const add = (value: unknown): string => {
      params.push(value);
      return `$${params.length}`;
    };
    if (filters.itemType) clauses.push(`item_type = ${add(filters.itemType)}`);
    if (filters.status) clauses.push(`status = ${add(filters.status)}`);
    if (filters.visibility) clauses.push(`visibility = ${add(filters.visibility)}`);
    if (filters.projectId) clauses.push(`project_id = ${add(filters.projectId)}`);
    if (filters.workspaceId) clauses.push(`workspace_id = ${add(filters.workspaceId)}`);
    if (filters.q) clauses.push(`(title ILIKE ${add(`%${filters.q}%`)} OR content ILIKE $${params.length})`);
    return { where: `WHERE ${clauses.join(" AND ")}`, params };
  }

  private async getVisibleItemRow(identity: SpaceUserIdentity, itemId: string): Promise<KnowledgeItemRow | null> {
    const result = await this.db.query<KnowledgeItemRow>(
      `SELECT ${KNOWLEDGE_ITEM_COLUMNS}
         FROM knowledge_items
        WHERE id = $1 AND space_id = $2`,
      [itemId, identity.spaceId],
    );
    const row = result.rows[0];
    return row && canReadKnowledge(row, identity.userId) ? row : null;
  }

  private async getRelationRow(identity: SpaceUserIdentity, relationId: string): Promise<KnowledgeRelationRow | null> {
    const result = await this.db.query<KnowledgeRelationRow>(
      `SELECT ${KNOWLEDGE_RELATION_COLUMNS}
         FROM knowledge_item_relations
        WHERE id = $1 AND space_id = $2`,
      [relationId, identity.spaceId],
    );
    return result.rows[0] ?? null;
  }

  private async getSourceRow(identity: SpaceUserIdentity, sourceId: string): Promise<SourceRow | null> {
    const result = await this.db.query<SourceRow>(
      `SELECT ${SOURCE_COLUMNS} FROM sources WHERE id = $1 AND space_id = $2`,
      [sourceId, identity.spaceId],
    );
    return result.rows[0] ?? null;
  }

  private async listKnowledgeSourceRefs(identity: SpaceUserIdentity, itemId: string): Promise<Record<string, unknown>[]> {
    const rows = await this.db.query<ProvenanceLinkRow>(
      `SELECT source_type, source_id, source_trust, evidence_json, created_at
         FROM provenance_links
        WHERE space_id = $1 AND target_type = 'knowledge' AND target_id = $2
        ORDER BY created_at ASC, source_type ASC, source_id ASC`,
      [identity.spaceId, itemId],
    );
    return rows.rows.map((row) => ({
      source_type: row.source_type,
      source_id: row.source_id,
      source_trust: row.source_trust,
      evidence_json: optionalObject(row.evidence_json),
      created_at: dateIso(row.created_at),
    }));
  }

  private async listKnowledgeItemSourceLinks(
    column: "knowledge_item_id" | "source_id",
    value: string,
    spaceId: string,
  ): Promise<Record<string, unknown>[]> {
    const rows = await this.db.query<Record<string, unknown>>(
      `SELECT id, space_id, knowledge_item_id, source_id, relation_type,
              locator, quote, note, confidence, created_by_user_id, created_at
         FROM knowledge_item_sources
        WHERE ${column} = $1 AND space_id = $2
        ORDER BY created_at DESC, id DESC`,
      [value, spaceId],
    );
    return rows.rows.map(normalizeDates);
  }

  private async getNoteRow(identity: SpaceUserIdentity, noteId: string): Promise<NoteRow | null> {
    const result = await this.db.query<NoteRow>(
      `SELECT ${NOTE_COLUMNS}
         FROM notes n
         LEFT JOIN LATERAL (
           SELECT nci.collection_id
             FROM note_collection_items nci
            WHERE nci.note_id = n.id
            ORDER BY nci.created_at ASC
            LIMIT 1
         ) first_collection ON true
        WHERE n.id = $1 AND n.space_id = $2`,
      [noteId, identity.spaceId],
    );
    return result.rows[0] ?? null;
  }

  private async getNoteCollectionRow(
    identity: SpaceUserIdentity,
    collectionId: string,
  ): Promise<NoteCollectionRow | null> {
    const result = await this.db.query<NoteCollectionRow>(
      `SELECT ${NOTE_COLLECTION_COLUMNS}
         FROM note_collections
        WHERE id = $1 AND space_id = $2
        LIMIT 1`,
      [collectionId, identity.spaceId],
    );
    return result.rows[0] ?? null;
  }

  private async requireNoteCollection(identity: SpaceUserIdentity, collectionId: string): Promise<void> {
    if (!(await this.getNoteCollectionRow(identity, collectionId))) {
      throw new HttpError(404, "Note collection not found");
    }
  }

  private async addNoteToCollection(identity: SpaceUserIdentity, noteId: string, collectionId: string): Promise<void> {
    const exists = await this.db.query<{ id: string }>(
      `SELECT id FROM note_collections WHERE id = $1 AND space_id = $2`,
      [collectionId, identity.spaceId],
    );
    if (!exists.rows[0]) throw new HttpError(404, "Note collection not found");
    await this.db.query(`DELETE FROM note_collection_items WHERE note_id = $1`, [noteId]);
    await this.db.query(
      `INSERT INTO note_collection_items (id, collection_id, note_id, sort_order, created_at)
       VALUES ($1, $2, $3, 0, $4)`,
      [randomUUID(), collectionId, noteId, new Date().toISOString()],
    );
  }

  private async insertKnowledgeProposal(inputIdentity: SpaceUserIdentity, input: {
    proposalType: string;
    title: string;
    payload: Record<string, unknown>;
    rationale: string;
    workspaceId: string | null;
    projectId: string | null;
  }): Promise<ProposalOut> {
    const now = new Date();
    const nowIso = now.toISOString();
    const result = await this.db.query<ProposalRow>(
      `INSERT INTO proposals (
         id, space_id, proposal_type, status, risk_level, urgency, preview,
         title, summary, payload_json, review_deadline, expires_at, created_at,
         updated_at, reviewed_at, reviewed_by, workspace_id, rationale,
         created_by_agent_id, created_by_user_id, required_approver_role,
         visibility, project_id
       ) VALUES (
         $1, $2, $3, 'pending', 'low', 'normal', false,
         $4, NULL, $5::jsonb, NULL, NULL, $6,
         $6, NULL, NULL, $7, $8,
         NULL, $9, NULL,
         'space_shared', $10
       )
       RETURNING id, space_id, created_by_user_id, workspace_id,
                 created_by_run_id, proposal_type, status, risk_level, urgency,
                 preview, title, payload_json, rationale, visibility,
                 review_deadline, expires_at, created_at, reviewed_at,
                 project_id,
                 NULL::varchar AS egress_approval_id,
                 NULL::varchar AS egress_approval_status`,
      [
        randomUUID(),
        inputIdentity.spaceId,
        input.proposalType,
        input.title,
        JSON.stringify(input.payload),
        nowIso,
        input.workspaceId,
        input.rationale,
        inputIdentity.userId,
        input.projectId,
      ],
    );
    return proposalToOut(result.rows[0]!, now);
  }
}

function buildNoteWhere(
  identity: SpaceUserIdentity,
  filters: {
    status: string | null;
    projectId: string | null;
    collectionId: string | null;
    q: string | null;
  },
): { where: string; params: unknown[] } {
  const params: unknown[] = [identity.spaceId];
  const clauses = ["n.space_id = $1"];
  const add = (value: unknown): string => {
    params.push(value);
    return `$${params.length}`;
  };
  clauses.push(filters.status ? `n.status = ${add(filters.status)}` : "n.status <> 'deleted'");
  if (filters.projectId) clauses.push(`n.primary_project_id = ${add(filters.projectId)}`);
  if (filters.collectionId) clauses.push(`nci_filter.collection_id = ${add(filters.collectionId)}`);
  if (filters.q) clauses.push(`(n.title ILIKE ${add(`%${filters.q}%`)} OR n.plain_text ILIKE $${params.length})`);
  return { where: `WHERE ${clauses.join(" AND ")}`, params };
}

function knowledgeSummaryOut(row: KnowledgeItemRow): Record<string, unknown> {
  return {
    id: row.id,
    space_id: row.space_id,
    project_id: row.project_id,
    workspace_id: row.workspace_id,
    item_type: row.item_type,
    slug: row.slug,
    title: row.title,
    content_preview: row.excerpt ?? (row.plain_text ?? row.content).slice(0, 280),
    excerpt: row.excerpt,
    status: row.status,
    visibility: row.visibility,
    verification_status: row.verification_status,
    reflection_status: row.reflection_status,
    tags: stringArray(row.tags_json),
    confidence: row.confidence,
    version: numberValue(row.version) ?? 1,
    updated_at: dateIso(row.updated_at) ?? new Date(0).toISOString(),
  };
}

function knowledgeItemOut(row: KnowledgeItemRow, sourceRefs: Record<string, unknown>[]): Record<string, unknown> {
  return {
    ...knowledgeSummaryOut(row),
    root_item_id: row.root_item_id,
    supersedes_item_id: row.supersedes_item_id,
    redirect_to_item_id: row.redirect_to_item_id,
    aliases: stringArray(row.aliases_json),
    content: row.content,
    content_json: optionalObject(row.content_json),
    content_format: row.content_format,
    content_schema_version: numberValue(row.content_schema_version) ?? 1,
    plain_text: row.plain_text,
    source_url: row.source_url,
    source_refs: sourceRefs,
    owner_user_id: row.owner_user_id,
    created_by_user_id: row.created_by_user_id,
    created_by_agent_id: row.created_by_agent_id,
    created_by_run_id: row.created_by_run_id,
    source_activity_id: row.source_activity_id,
    source_artifact_id: row.source_artifact_id,
    created_from_proposal_id: row.created_from_proposal_id,
    approved_by_user_id: row.approved_by_user_id,
    created_at: dateIso(row.created_at),
    archived_at: dateIso(row.archived_at),
    deprecated_at: dateIso(row.deprecated_at),
  };
}

function relationOut(row: KnowledgeRelationRow): Record<string, unknown> {
  return normalizeDates({ ...row });
}

function sourceSummaryOut(row: SourceRow): Record<string, unknown> {
  return {
    id: row.id,
    space_id: row.space_id,
    source_type: row.source_type,
    title: row.title,
    uri: row.uri,
    status: row.status,
    source_activity_id: row.source_activity_id,
    created_at: dateIso(row.created_at),
    updated_at: dateIso(row.updated_at),
  };
}

function sourceOut(row: SourceRow): Record<string, unknown> {
  return {
    ...sourceSummaryOut(row),
    content_ref: row.content_ref,
    raw_text: row.raw_text,
    summary: row.summary,
    metadata: objectValue(row.metadata_json),
    created_by_user_id: row.created_by_user_id,
  };
}

function noteSummaryOut(row: NoteRow): Record<string, unknown> {
  return {
    id: row.id,
    space_id: row.space_id,
    title: row.title,
    excerpt: row.excerpt,
    status: row.status,
    content_format: row.content_format,
    primary_project_id: row.primary_project_id,
    collection_id: row.collection_id,
    created_at: dateIso(row.created_at),
    updated_at: dateIso(row.updated_at),
    deleted_at: dateIso(row.deleted_at),
  };
}

function noteOut(row: NoteRow): Record<string, unknown> {
  return {
    ...noteSummaryOut(row),
    content_json: optionalObject(row.content_json),
    content_schema_version: numberValue(row.content_schema_version) ?? 1,
    plain_text: row.plain_text,
    created_from_activity_id: row.created_from_activity_id,
    created_by_user_id: row.created_by_user_id,
    archived_at: dateIso(row.archived_at),
  };
}

function noteCollectionOut(row: NoteCollectionRow): Record<string, unknown> {
  return {
    id: row.id,
    space_id: row.space_id,
    parent_id: row.parent_id,
    name: row.name,
    system_role: row.system_role,
    sort_order: numberValue(row.sort_order) ?? 0,
    is_system: row.is_system,
    is_hidden: row.is_hidden,
    created_at: dateIso(row.created_at),
    updated_at: dateIso(row.updated_at),
  };
}

function entityLinkOut(row: EntityLinkRow): Record<string, unknown> {
  return normalizeDates({ ...row });
}

function normalizeDates(row: Record<string, unknown>): Record<string, unknown> {
  for (const key of Object.keys(row)) {
    if (key.endsWith("_at")) row[key] = dateIso(row[key]);
  }
  return row;
}

function canReadKnowledge(row: KnowledgeItemRow, userId: string): boolean {
  return canReadByVisibility(row.visibility, userId, [row.owner_user_id, row.created_by_user_id]);
}

function canMutateKnowledge(row: KnowledgeItemRow, userId: string): boolean {
  if (row.visibility === "space_shared" || row.visibility === "workspace_shared") return true;
  return row.owner_user_id === userId || row.created_by_user_id === userId;
}

function confidence(value: unknown): number | null {
  const parsed = numberValue(value);
  if (parsed === null) return null;
  if (parsed < 0 || parsed > 1) throw new HttpError(422, "confidence must be between 0 and 1");
  return parsed;
}
