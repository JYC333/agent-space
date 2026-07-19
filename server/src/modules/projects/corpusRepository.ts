import { randomUUID } from "node:crypto";
import {
  HttpError,
  countFromRow,
  dateIso,
  numberValue,
  objectValue,
  optionalObject,
  optionalString,
  page,
  type Queryable,
  type SpaceUserIdentity,
} from "../routeUtils/common";
import { contentReadSql } from "../access/contentAccessSql";
import { sourceItemReadableClause } from "../sources/sourceItemAccess";
import { assertProjectReadable, assertProjectWriter } from "./access";

export type ProjectCorpusRole = "candidate" | "reference" | "primary" | "related" | "background";
export type ProjectCorpusStatus = "active" | "archived";
export type ProjectCorpusTriageStatus = "new" | "relevant" | "maybe" | "excluded" | "included";
export type ProjectCorpusReadStatus = "unread" | "skimmed" | "read" | "discussed";
export type ProjectCorpusRelevance = "relevant" | "maybe" | "not_relevant";

interface ProjectCorpusItemRow {
  id: string;
  space_id: string;
  project_id: string;
  object_id: string | null;
  source_item_id: string | null;
  evidence_id: string | null;
  source_connection_id: string | null;
  source_decision_id: string | null;
  role: ProjectCorpusRole;
  status: ProjectCorpusStatus;
  triage_status: ProjectCorpusTriageStatus;
  triage_confirmed_by_user: boolean;
  read_status: ProjectCorpusReadStatus;
  relevance: ProjectCorpusRelevance | null;
  confidence: number | null;
  reason: string | null;
  added_by_user_id: string | null;
  metadata_json: unknown;
  created_at: unknown;
  updated_at: unknown;
  last_reviewed_at: unknown;
  last_read_at: unknown;
  object_type: string | null;
  object_title: string | null;
  object_summary: string | null;
  object_status: string | null;
  source_item_type: string | null;
  source_item_title: string | null;
  source_item_uri: string | null;
  source_item_domain: string | null;
  source_item_excerpt: string | null;
  evidence_type: string | null;
  evidence_title: string | null;
  evidence_excerpt: string | null;
  academic_arxiv_id: string | null;
  academic_doi: string | null;
  academic_publication_date: unknown;
  academic_venue: string | null;
  academic_paper_type: string | null;
  academic_cited_by_count: number | null;
  academic_reference_count: number | null;
  academic_source_uri: string | null;
  academic_authors: unknown;
  academic_categories: unknown;
}

const CORPUS_COLUMNS = `
  pci.id, pci.space_id, pci.project_id, pci.object_id, pci.source_item_id,
  pci.evidence_id, pci.source_connection_id, pci.source_decision_id,
  pci.role, pci.status, pci.triage_status, pci.triage_confirmed_by_user, pci.read_status, pci.relevance,
  pci.confidence, pci.reason, pci.added_by_user_id, pci.metadata_json,
  pci.created_at, pci.updated_at, pci.last_reviewed_at, pci.last_read_at,
  so.object_type, so.title AS object_title, so.summary AS object_summary, so.status AS object_status,
  si.item_type AS source_item_type, si.title AS source_item_title,
  si.source_uri AS source_item_uri, si.source_domain AS source_item_domain, si.excerpt AS source_item_excerpt,
  ev.evidence_type, ev.title AS evidence_title, ev.content_excerpt AS evidence_excerpt,
  ap.arxiv_id AS academic_arxiv_id, ap.doi AS academic_doi, ap.publication_date AS academic_publication_date,
  ap.venue AS academic_venue, ap.paper_type AS academic_paper_type,
  ap.cited_by_count AS academic_cited_by_count, ap.reference_count AS academic_reference_count,
  src.uri AS academic_source_uri, src.metadata_json->'authors' AS academic_authors,
  src.metadata_json->'categories' AS academic_categories
`;

const ROLES = new Set<ProjectCorpusRole>(["candidate", "reference", "primary", "related", "background"]);
const STATUSES = new Set<ProjectCorpusStatus>(["active", "archived"]);
const TRIAGE_STATUSES = new Set<ProjectCorpusTriageStatus>(["new", "relevant", "maybe", "excluded", "included"]);
const READ_STATUSES = new Set<ProjectCorpusReadStatus>(["unread", "skimmed", "read", "discussed"]);
const RELEVANCES = new Set<ProjectCorpusRelevance>(["relevant", "maybe", "not_relevant"]);

export interface ProjectCorpusBackfillResult {
  project_id: string;
  source_items: number;
  source_objects: number;
  evidence_items: number;
  evidence_objects: number;
  source_decisions: number;
  archived_source_items: number;
}

export class ProjectCorpusRepository {
  constructor(private readonly db: Queryable) {}

  async list(
    identity: SpaceUserIdentity,
    projectId: string,
    filters: {
      status?: string | null;
      triageStatus?: string | null;
      readStatus?: string | null;
      role?: string | null;
      q?: string | null;
      limit: number;
      offset: number;
    },
  ): Promise<Record<string, unknown>> {
    await assertProjectReadable(this.db, identity.spaceId, projectId, identity.userId);
    const params: unknown[] = [identity.spaceId, projectId, identity.userId];
    const clauses = [
      "pci.space_id = $1",
      "pci.project_id = $2",
      `(pci.object_id IS NULL OR (so.id IS NOT NULL AND ${contentReadSql("space_object", "so", "$3")}))`,
      `(pci.source_item_id IS NULL OR (si.id IS NOT NULL AND ${sourceItemReadableClause("si", "$3", false)}))`,
      `(pci.evidence_id IS NULL OR (ev.id IS NOT NULL AND ${contentReadSql("extracted_evidence", "ev", "$3")}))`,
    ];
    if (filters.status) {
      if (!STATUSES.has(filters.status as ProjectCorpusStatus)) {
        throw new HttpError(422, "status must be active or archived");
      }
      params.push(filters.status);
      clauses.push(`pci.status = $${params.length}`);
    } else {
      clauses.push("pci.status = 'active'");
    }
    if (filters.triageStatus) {
      if (!TRIAGE_STATUSES.has(filters.triageStatus as ProjectCorpusTriageStatus)) {
        throw new HttpError(422, "triage_status is invalid");
      }
      params.push(filters.triageStatus);
      clauses.push(`pci.triage_status = $${params.length}`);
    }
    if (filters.readStatus) {
      if (!READ_STATUSES.has(filters.readStatus as ProjectCorpusReadStatus)) {
        throw new HttpError(422, "read_status is invalid");
      }
      params.push(filters.readStatus);
      clauses.push(`pci.read_status = $${params.length}`);
    }
    if (filters.role) {
      if (!ROLES.has(filters.role as ProjectCorpusRole)) throw new HttpError(422, "role is invalid");
      params.push(filters.role);
      clauses.push(`pci.role = $${params.length}`);
    }
    if (filters.q) {
      params.push(`%${escapeLike(filters.q)}%`);
      clauses.push(`(
        so.title ILIKE $${params.length} ESCAPE '\\'
        OR COALESCE(so.summary, '') ILIKE $${params.length} ESCAPE '\\'
        OR si.title ILIKE $${params.length} ESCAPE '\\'
        OR COALESCE(si.excerpt, '') ILIKE $${params.length} ESCAPE '\\'
        OR ev.title ILIKE $${params.length} ESCAPE '\\'
        OR COALESCE(ev.content_excerpt, '') ILIKE $${params.length} ESCAPE '\\'
      )`);
    }
    const where = clauses.join(" AND ");
    const total = await this.db.query<{ total: string | number }>(
      `SELECT count(pci.id)::text AS total
         FROM project_corpus_items pci
         LEFT JOIN space_objects so ON so.id = pci.object_id AND so.space_id = pci.space_id
         LEFT JOIN source_items si ON si.id = pci.source_item_id AND si.space_id = pci.space_id
         LEFT JOIN extracted_evidence ev ON ev.id = pci.evidence_id AND ev.space_id = pci.space_id
        WHERE ${where}`,
      params,
    );
    const rows = await this.db.query<ProjectCorpusItemRow>(
      `SELECT ${CORPUS_COLUMNS}
         FROM project_corpus_items pci
         LEFT JOIN space_objects so ON so.id = pci.object_id AND so.space_id = pci.space_id
         LEFT JOIN source_items si ON si.id = pci.source_item_id AND si.space_id = pci.space_id
         LEFT JOIN extracted_evidence ev ON ev.id = pci.evidence_id AND ev.space_id = pci.space_id
         LEFT JOIN academic_papers ap ON ap.object_id = so.id AND ap.space_id = pci.space_id
         LEFT JOIN sources src ON src.object_id = so.id AND src.space_id = pci.space_id
        WHERE ${where}
        ORDER BY pci.updated_at DESC, pci.created_at DESC, pci.id ASC
        LIMIT $${params.length + 1} OFFSET $${params.length + 2}`,
      [...params, filters.limit, filters.offset],
    );
    return page(rows.rows.map(projectCorpusItemOut), countFromRow(total.rows[0]), filters.limit, filters.offset);
  }

  async upsert(
    identity: SpaceUserIdentity,
    projectId: string,
    body: Record<string, unknown>,
  ): Promise<Record<string, unknown>> {
    await assertProjectWriter(this.db, identity.spaceId, projectId, identity.userId);
    const target = await this.resolveTarget(identity, projectId, body);
    const now = new Date().toISOString();
    const role = roleValue(body.role) ?? "candidate";
    const status = statusValue(body.status) ?? "active";
    const triageStatus = triageStatusValue(body.triage_status) ?? "new";
    const triageConfirmed = body.triage_status !== undefined;
    const readStatus = readStatusValue(body.read_status) ?? "unread";
    const relevance = relevanceValue(body.relevance);
    const confidence = confidenceValue(body.confidence);
    const metadata = optionalObject(body.metadata_json) ?? {};
    const conflict = conflictClause(target);
    // Every logical usage gets its own parameter number (no $N reuse), even
    // where the JS value repeats (e.g. `now`): this pg version/driver
    // combination raises "inconsistent types deduced for parameter" when a
    // parameter is referenced more than once in a statement.
    const result = await this.db.query<{ id: string }>(
      `INSERT INTO project_corpus_items (
         id, space_id, project_id, object_id, source_item_id, evidence_id,
         source_connection_id, source_decision_id, role, status, triage_status,
         triage_confirmed_by_user, read_status, relevance, confidence, reason, added_by_user_id,
         metadata_json, created_at, updated_at, last_reviewed_at, last_read_at
       ) VALUES (
         $1, $2, $3, $4, $5, $6,
         $7, $8, $9, $10, $11,
         $12, $13, $14, $15, $16, $17,
         $18::jsonb, $19, $20,
         CASE WHEN $21::varchar <> 'new' THEN $22::timestamptz ELSE NULL END,
         CASE WHEN $23::varchar <> 'unread' THEN $24::timestamptz ELSE NULL END
       )
       ${conflict}
       DO UPDATE SET object_id = COALESCE(EXCLUDED.object_id, project_corpus_items.object_id),
                     source_item_id = COALESCE(EXCLUDED.source_item_id, project_corpus_items.source_item_id),
                     evidence_id = COALESCE(EXCLUDED.evidence_id, project_corpus_items.evidence_id),
                     source_connection_id = COALESCE(EXCLUDED.source_connection_id, project_corpus_items.source_connection_id),
                     source_decision_id = COALESCE(EXCLUDED.source_decision_id, project_corpus_items.source_decision_id),
                     role = EXCLUDED.role,
                     status = EXCLUDED.status,
                     triage_status = EXCLUDED.triage_status,
                     triage_confirmed_by_user = CASE
                       WHEN EXCLUDED.triage_confirmed_by_user THEN true
                       ELSE project_corpus_items.triage_confirmed_by_user
                     END,
                     read_status = EXCLUDED.read_status,
                     relevance = EXCLUDED.relevance,
                     confidence = EXCLUDED.confidence,
                     reason = EXCLUDED.reason,
                     metadata_json = EXCLUDED.metadata_json,
                     updated_at = EXCLUDED.updated_at,
                     last_reviewed_at = CASE
                       WHEN EXCLUDED.triage_status <> project_corpus_items.triage_status THEN EXCLUDED.updated_at
                       ELSE project_corpus_items.last_reviewed_at
                     END,
                     last_read_at = CASE
                       WHEN EXCLUDED.read_status <> project_corpus_items.read_status THEN EXCLUDED.updated_at
                       ELSE project_corpus_items.last_read_at
                     END
       RETURNING id`,
      [
        randomUUID(),
        identity.spaceId,
        projectId,
        target.objectId,
        target.sourceItemId,
        target.evidenceId,
        target.sourceConnectionId,
        target.sourceDecisionId,
        role,
        status,
        triageStatus,
        triageConfirmed,
        readStatus,
        relevance,
        confidence,
        optionalString(body.reason),
        identity.userId,
        JSON.stringify(metadata),
        now,
        now,
        triageStatus,
        now,
        readStatus,
        now,
      ],
    );
    const item = await this.getById(identity.spaceId, projectId, result.rows[0]!.id);
    if (!item) throw new HttpError(500, "Failed to upsert project corpus item");
    return projectCorpusItemOut(item);
  }

  async update(
    identity: SpaceUserIdentity,
    projectId: string,
    corpusItemId: string,
    body: Record<string, unknown>,
  ): Promise<Record<string, unknown>> {
    await assertProjectWriter(this.db, identity.spaceId, projectId, identity.userId);
    const current = await this.getById(identity.spaceId, projectId, corpusItemId);
    if (!current) throw new HttpError(404, "Project corpus item not found");
    const nextRole = body.role === undefined ? current.role : roleValue(body.role) ?? current.role;
    const nextStatus = body.status === undefined ? current.status : statusValue(body.status) ?? current.status;
    const nextTriage = body.triage_status === undefined
      ? current.triage_status
      : triageStatusValue(body.triage_status) ?? current.triage_status;
    const triageConfirmed = body.triage_status !== undefined || current.triage_confirmed_by_user;
    const nextRead = body.read_status === undefined ? current.read_status : readStatusValue(body.read_status) ?? current.read_status;
    const nextRelevance = body.relevance === undefined ? current.relevance : relevanceValue(body.relevance);
    const nextConfidence = body.confidence === undefined ? current.confidence : confidenceValue(body.confidence);
    const nextMetadata = body.metadata_json === undefined
      ? objectValue(current.metadata_json)
      : optionalObject(body.metadata_json) ?? {};
    const now = new Date().toISOString();
    // triage_status/read_status are each passed twice (once for the plain
    // SET, once for the CASE comparison) rather than reusing one parameter
    // number: this pg version/driver combination raises "inconsistent types
    // deduced for parameter" when the same parameter is referenced more
    // than once in a statement (reproduced independently of this change).
    await this.db.query(
      `UPDATE project_corpus_items
          SET role = $4,
              status = $5,
              triage_status = $6,
              triage_confirmed_by_user = $15,
              read_status = $7,
              relevance = $8,
              confidence = $9,
              reason = $10,
              metadata_json = $11::jsonb,
              updated_at = $12,
              last_reviewed_at = CASE WHEN triage_status <> $13 THEN $12::timestamptz ELSE last_reviewed_at END,
              last_read_at = CASE WHEN read_status <> $14 THEN $12::timestamptz ELSE last_read_at END
        WHERE space_id = $1 AND project_id = $2 AND id = $3`,
      [
        identity.spaceId,
        projectId,
        corpusItemId,
        nextRole,
        nextStatus,
        nextTriage,
        nextRead,
        nextRelevance,
        nextConfidence,
        body.reason === undefined ? current.reason : optionalString(body.reason),
        JSON.stringify(nextMetadata),
        now,
        nextTriage,
        nextRead,
        triageConfirmed,
      ],
    );
    const updated = await this.getById(identity.spaceId, projectId, corpusItemId);
    if (!updated) throw new HttpError(404, "Project corpus item not found");
    return projectCorpusItemOut(updated);
  }

  async backfillFromSources(identity: SpaceUserIdentity, projectId: string): Promise<ProjectCorpusBackfillResult> {
    await assertProjectWriter(this.db, identity.spaceId, projectId, identity.userId);
    const sourceItems = await upsertProjectCorpusSourceItemsFromLinks(this.db, {
      spaceId: identity.spaceId,
      projectId,
    });
    const sourceObjects = await upsertProjectCorpusObjectsFromSourceItems(this.db, {
      spaceId: identity.spaceId,
      projectId,
    });
    const evidenceItems = await upsertProjectCorpusEvidenceFromLinks(this.db, {
      spaceId: identity.spaceId,
      projectId,
    });
    const evidenceObjects = await upsertProjectCorpusObjectsFromEvidence(this.db, {
      spaceId: identity.spaceId,
      projectId,
    });
    const sourceDecisions = await syncProjectCorpusSourceDecisions(this.db, {
      spaceId: identity.spaceId,
      projectId,
    });
    const archivedSourceItems = await archiveCorpusSourceItemsWithoutActiveLinks(this.db, {
      spaceId: identity.spaceId,
      projectId,
    });
    return {
      project_id: projectId,
      source_items: sourceItems,
      source_objects: sourceObjects,
      evidence_items: evidenceItems,
      evidence_objects: evidenceObjects,
      source_decisions: sourceDecisions,
      archived_source_items: archivedSourceItems,
    };
  }

  private async resolveTarget(
    identity: SpaceUserIdentity,
    projectId: string,
    body: Record<string, unknown>,
  ): Promise<{
    objectId: string | null;
    sourceItemId: string | null;
    evidenceId: string | null;
    sourceConnectionId: string | null;
    sourceDecisionId: string | null;
  }> {
    const objectId = optionalString(body.object_id);
    const sourceItemId = optionalString(body.source_item_id);
    const evidenceId = optionalString(body.evidence_id);
    const sourceDecisionId = optionalString(body.source_decision_id);
    if (!objectId && !sourceItemId && !evidenceId) {
      throw new HttpError(422, "object_id, source_item_id, or evidence_id is required");
    }
    let sourceConnectionId = optionalString(body.source_connection_id);
    if (objectId) {
      const object = await this.db.query<{ id: string }>(
        `SELECT so.id
           FROM space_objects so
          WHERE so.space_id = $1
            AND so.id = $2
            AND so.deleted_at IS NULL
            AND ${contentReadSql("space_object", "so", "$3")}
          LIMIT 1`,
        [identity.spaceId, objectId, identity.userId],
      );
      if (!object.rows[0]) throw new HttpError(422, "object_id is not readable by this user");
    }
    if (sourceItemId) {
      const item = await this.db.query<{ connection_id: string | null }>(
        `SELECT si.connection_id
           FROM source_items si
          WHERE si.space_id = $1
            AND si.id = $2
            AND si.deleted_at IS NULL
            AND ${sourceItemReadableClause("si", "$3", false)}
          LIMIT 1`,
        [identity.spaceId, sourceItemId, identity.userId],
      );
      if (!item.rows[0]) throw new HttpError(422, "source_item_id is not readable by this user");
      sourceConnectionId ??= item.rows[0].connection_id;
    }
    if (evidenceId) {
      const evidence = await this.db.query<{ source_item_connection_id: string | null }>(
        `SELECT si.connection_id AS source_item_connection_id
           FROM extracted_evidence ev
           LEFT JOIN source_items si ON si.id = ev.source_item_id AND si.space_id = ev.space_id
           LEFT JOIN space_objects so ON so.id = ev.source_object_id AND so.space_id = ev.space_id
          WHERE ev.space_id = $1
            AND ev.id = $2
            AND ev.deleted_at IS NULL
            AND ${contentReadSql("extracted_evidence", "ev", "$3")}
            AND (
              (
                ev.source_item_id IS NOT NULL
                AND si.deleted_at IS NULL
                AND ${sourceItemReadableClause("si", "$3", false)}
              )
              OR (
                ev.source_item_id IS NULL
                AND ev.source_object_id IS NOT NULL
                AND so.deleted_at IS NULL
                AND ${contentReadSql("space_object", "so", "$3")}
              )
              OR (
                ev.source_item_id IS NULL
                AND ev.source_object_id IS NULL
              )
            )
          LIMIT 1`,
        [identity.spaceId, evidenceId, identity.userId],
      );
      if (!evidence.rows[0]) throw new HttpError(422, "evidence_id is not readable by this user");
      sourceConnectionId ??= evidence.rows[0].source_item_connection_id;
    }
    if (sourceDecisionId) {
      const decision = await this.db.query<{ source_connection_id: string | null; source_item_id: string }>(
        `SELECT sc.id AS source_connection_id, d.source_item_id
           FROM source_post_processing_item_decisions d
           LEFT JOIN source_channels ch ON ch.id = d.source_channel_id AND ch.space_id = d.space_id
           LEFT JOIN source_connections sc ON sc.id = ch.source_connection_id
         WHERE d.space_id = $1 AND d.project_id = $2 AND d.id = $3
          LIMIT 1`,
        [identity.spaceId, projectId, sourceDecisionId],
      );
      const row = decision.rows[0];
      if (!row) throw new HttpError(422, "source_decision_id does not reference this project");
      if (sourceItemId && row.source_item_id !== sourceItemId) {
        throw new HttpError(422, "source_decision_id must match source_item_id");
      }
      sourceConnectionId ??= row.source_connection_id;
    }
    return { objectId, sourceItemId, evidenceId, sourceConnectionId, sourceDecisionId };
  }

  private async getById(spaceId: string, projectId: string, corpusItemId: string): Promise<ProjectCorpusItemRow | null> {
    const result = await this.db.query<ProjectCorpusItemRow>(
      `SELECT ${CORPUS_COLUMNS}
         FROM project_corpus_items pci
         LEFT JOIN space_objects so ON so.id = pci.object_id AND so.space_id = pci.space_id
         LEFT JOIN source_items si ON si.id = pci.source_item_id AND si.space_id = pci.space_id
         LEFT JOIN extracted_evidence ev ON ev.id = pci.evidence_id AND ev.space_id = pci.space_id
         LEFT JOIN academic_papers ap ON ap.object_id = so.id AND ap.space_id = pci.space_id
         LEFT JOIN sources src ON src.object_id = so.id AND src.space_id = pci.space_id
        WHERE pci.space_id = $1 AND pci.project_id = $2 AND pci.id = $3
        LIMIT 1`,
      [spaceId, projectId, corpusItemId],
    );
    return result.rows[0] ?? null;
  }
}

export async function syncProjectCorpusForSourceItem(
  db: Queryable,
  input: { spaceId: string; sourceItemId: string; projectId?: string | null },
): Promise<{ source_items: number; source_objects: number; archived_source_items: number }> {
  const sourceItems = await upsertProjectCorpusSourceItemsFromLinks(db, input);
  const sourceObjects = await upsertProjectCorpusObjectsFromSourceItems(db, input);
  const archivedSourceItems = await archiveCorpusSourceItemsWithoutActiveLinks(db, input);
  return { source_items: sourceItems, source_objects: sourceObjects, archived_source_items: archivedSourceItems };
}

export async function syncProjectCorpusEvidenceForSourceItem(
  db: Queryable,
  input: { spaceId: string; sourceItemId: string; projectId?: string | null },
): Promise<{ evidence_items: number; evidence_objects: number }> {
  const evidenceItems = await upsertProjectCorpusEvidenceFromLinks(db, input);
  const evidenceObjects = await upsertProjectCorpusObjectsFromEvidence(db, input);
  return { evidence_items: evidenceItems, evidence_objects: evidenceObjects };
}

/**
 * Applies the latest source-post-processing decision to the project corpus.
 * User-confirmed triage is intentionally preserved by the SQL upsert below.
 */
export async function syncProjectCorpusDecisionForSourceItem(
  db: Queryable,
  input: { spaceId: string; sourceItemId: string; projectId?: string | null },
): Promise<number> {
  return syncProjectCorpusSourceDecisions(db, input);
}

async function upsertProjectCorpusSourceItemsFromLinks(
  db: Queryable,
  input: { spaceId: string; sourceItemId?: string | null; projectId?: string | null },
): Promise<number> {
  const now = new Date().toISOString();
  const result = await db.query(
    `INSERT INTO project_corpus_items (
       id, space_id, project_id, source_item_id, source_connection_id,
       role, status, triage_status, read_status, reason, metadata_json, created_at, updated_at
     )
     SELECT DISTINCT ON (psil.project_id, psil.source_item_id)
            gen_random_uuid()::varchar, psil.space_id, psil.project_id, psil.source_item_id,
            COALESCE(psil.source_connection_id, si.connection_id),
            'candidate', 'active', 'new', 'unread',
            psil.match_reason, '{}'::jsonb, $4, $4
       FROM project_source_item_links psil
       JOIN source_items si ON si.id = psil.source_item_id AND si.space_id = psil.space_id
      WHERE psil.space_id = $1
        AND psil.status = 'active'
        AND si.deleted_at IS NULL
        AND ($2::varchar IS NULL OR psil.source_item_id = $2)
        AND ($3::varchar IS NULL OR psil.project_id = $3)
      ORDER BY psil.project_id, psil.source_item_id, psil.matched_at DESC, psil.id ASC
     ON CONFLICT (space_id, project_id, source_item_id)
       WHERE source_item_id IS NOT NULL AND object_id IS NULL AND evidence_id IS NULL
     DO UPDATE SET status = 'active',
                   source_connection_id = COALESCE(project_corpus_items.source_connection_id, EXCLUDED.source_connection_id),
                   reason = COALESCE(project_corpus_items.reason, EXCLUDED.reason),
                   updated_at = EXCLUDED.updated_at`,
    [input.spaceId, input.sourceItemId ?? null, input.projectId ?? null, now],
  );
  return result.rowCount ?? 0;
}

async function upsertProjectCorpusObjectsFromSourceItems(
  db: Queryable,
  input: { spaceId: string; sourceItemId?: string | null; projectId?: string | null },
): Promise<number> {
  const now = new Date().toISOString();
  const result = await db.query(
    `INSERT INTO project_corpus_items (
       id, space_id, project_id, object_id, source_item_id, source_connection_id,
       role, status, triage_status, read_status, reason, metadata_json, created_at, updated_at
     )
     SELECT DISTINCT ON (psil.project_id, si.source_object_id)
            gen_random_uuid()::varchar, psil.space_id, psil.project_id, si.source_object_id,
            psil.source_item_id, COALESCE(psil.source_connection_id, si.connection_id),
            'candidate', 'active', 'new', 'unread',
            psil.match_reason, '{}'::jsonb, $4, $4
       FROM project_source_item_links psil
       JOIN source_items si ON si.id = psil.source_item_id AND si.space_id = psil.space_id
       JOIN space_objects so ON so.id = si.source_object_id AND so.space_id = si.space_id
      WHERE psil.space_id = $1
        AND psil.status = 'active'
        AND si.deleted_at IS NULL
        AND si.source_object_id IS NOT NULL
        AND so.deleted_at IS NULL
        AND ($2::varchar IS NULL OR psil.source_item_id = $2)
        AND ($3::varchar IS NULL OR psil.project_id = $3)
      ORDER BY psil.project_id, si.source_object_id, psil.matched_at DESC, psil.id ASC
     ON CONFLICT (space_id, project_id, object_id)
       WHERE object_id IS NOT NULL
     DO UPDATE SET status = 'active',
                   source_item_id = COALESCE(project_corpus_items.source_item_id, EXCLUDED.source_item_id),
                   source_connection_id = COALESCE(project_corpus_items.source_connection_id, EXCLUDED.source_connection_id),
                   reason = COALESCE(project_corpus_items.reason, EXCLUDED.reason),
                   updated_at = EXCLUDED.updated_at`,
    [input.spaceId, input.sourceItemId ?? null, input.projectId ?? null, now],
  );
  return result.rowCount ?? 0;
}

async function upsertProjectCorpusEvidenceFromLinks(
  db: Queryable,
  input: { spaceId: string; sourceItemId?: string | null; projectId?: string | null },
): Promise<number> {
  const now = new Date().toISOString();
  const result = await db.query(
    `INSERT INTO project_corpus_items (
       id, space_id, project_id, evidence_id, source_item_id, source_connection_id,
       role, status, triage_status, read_status, confidence, reason, metadata_json, created_at, updated_at
     )
     SELECT DISTINCT ON (el.target_id, ev.id)
            gen_random_uuid()::varchar, ev.space_id, el.target_id, ev.id, ev.source_item_id,
            si.connection_id, 'candidate', 'active', 'new', 'unread',
            ev.confidence, el.reason, '{}'::jsonb, $4, $4
       FROM evidence_links el
       JOIN extracted_evidence ev ON ev.id = el.evidence_id AND ev.space_id = el.space_id
       LEFT JOIN source_items si ON si.id = ev.source_item_id AND si.space_id = ev.space_id
      WHERE el.space_id = $1
        AND el.target_type = 'project'
        AND el.status = 'active'
        AND ev.deleted_at IS NULL
        AND ($2::varchar IS NULL OR ev.source_item_id = $2)
        AND ($3::varchar IS NULL OR el.target_id = $3)
      ORDER BY el.target_id, ev.id, el.updated_at DESC, el.id ASC
     ON CONFLICT (space_id, project_id, evidence_id)
       WHERE evidence_id IS NOT NULL AND object_id IS NULL
     DO UPDATE SET status = 'active',
                   source_item_id = COALESCE(project_corpus_items.source_item_id, EXCLUDED.source_item_id),
                   source_connection_id = COALESCE(project_corpus_items.source_connection_id, EXCLUDED.source_connection_id),
                   confidence = COALESCE(project_corpus_items.confidence, EXCLUDED.confidence),
                   reason = COALESCE(project_corpus_items.reason, EXCLUDED.reason),
                   updated_at = EXCLUDED.updated_at`,
    [input.spaceId, input.sourceItemId ?? null, input.projectId ?? null, now],
  );
  return result.rowCount ?? 0;
}

async function upsertProjectCorpusObjectsFromEvidence(
  db: Queryable,
  input: { spaceId: string; sourceItemId?: string | null; projectId?: string | null },
): Promise<number> {
  const now = new Date().toISOString();
  const result = await db.query(
    `INSERT INTO project_corpus_items (
       id, space_id, project_id, object_id, evidence_id, source_item_id, source_connection_id,
       role, status, triage_status, read_status, confidence, reason, metadata_json, created_at, updated_at
     )
     SELECT DISTINCT ON (el.target_id, ev.source_object_id)
            gen_random_uuid()::varchar, ev.space_id, el.target_id, ev.source_object_id,
            ev.id, ev.source_item_id, si.connection_id,
            'candidate', 'active', 'new', 'unread',
            ev.confidence, el.reason, '{}'::jsonb, $4, $4
       FROM evidence_links el
       JOIN extracted_evidence ev ON ev.id = el.evidence_id AND ev.space_id = el.space_id
       JOIN space_objects so ON so.id = ev.source_object_id AND so.space_id = ev.space_id
       LEFT JOIN source_items si ON si.id = ev.source_item_id AND si.space_id = ev.space_id
      WHERE el.space_id = $1
        AND el.target_type = 'project'
        AND el.status = 'active'
        AND ev.deleted_at IS NULL
        AND ev.source_object_id IS NOT NULL
        AND so.deleted_at IS NULL
        AND ($2::varchar IS NULL OR ev.source_item_id = $2)
        AND ($3::varchar IS NULL OR el.target_id = $3)
      ORDER BY el.target_id, ev.source_object_id, el.updated_at DESC, el.id ASC
     ON CONFLICT (space_id, project_id, object_id)
       WHERE object_id IS NOT NULL
     DO UPDATE SET status = 'active',
                   evidence_id = COALESCE(project_corpus_items.evidence_id, EXCLUDED.evidence_id),
                   source_item_id = COALESCE(project_corpus_items.source_item_id, EXCLUDED.source_item_id),
                   source_connection_id = COALESCE(project_corpus_items.source_connection_id, EXCLUDED.source_connection_id),
                   confidence = COALESCE(project_corpus_items.confidence, EXCLUDED.confidence),
                   reason = COALESCE(project_corpus_items.reason, EXCLUDED.reason),
                   updated_at = EXCLUDED.updated_at`,
    [input.spaceId, input.sourceItemId ?? null, input.projectId ?? null, now],
  );
  return result.rowCount ?? 0;
}

async function syncProjectCorpusSourceDecisions(
  db: Queryable,
  input: { spaceId: string; sourceItemId?: string | null; projectId?: string | null },
): Promise<number> {
  const now = new Date().toISOString();
  const result = await db.query(
    `WITH latest_decisions AS (
       SELECT DISTINCT ON (d.project_id, d.source_item_id)
              d.id, d.space_id, d.project_id, sc.id AS source_connection_id, d.source_item_id,
              d.relevance, d.confidence, d.reason
         FROM source_post_processing_item_decisions d
         JOIN source_items si ON si.id = d.source_item_id AND si.space_id = d.space_id
         LEFT JOIN source_channels ch ON ch.id = d.source_channel_id AND ch.space_id = d.space_id
         LEFT JOIN source_connections sc ON sc.id = ch.source_connection_id
        WHERE d.space_id = $1
          AND si.deleted_at IS NULL
          AND d.project_id IS NOT NULL
          AND ($2::varchar IS NULL OR d.source_item_id = $2)
          AND ($3::varchar IS NULL OR d.project_id = $3)
        ORDER BY d.project_id, d.source_item_id, d.research_question_version DESC, d.updated_at DESC, d.id ASC
     )
     INSERT INTO project_corpus_items (
       id, space_id, project_id, source_item_id, source_connection_id, source_decision_id,
       role, status, triage_status, read_status, relevance, confidence, reason,
       metadata_json, created_at, updated_at, last_reviewed_at
     )
     SELECT gen_random_uuid()::varchar, d.space_id, d.project_id, d.source_item_id,
            d.source_connection_id, d.id,
            'candidate', 'active',
            CASE d.relevance
              WHEN 'relevant' THEN 'relevant'
              WHEN 'maybe' THEN 'maybe'
              ELSE 'excluded'
            END,
            'unread', d.relevance, d.confidence, d.reason, '{}'::jsonb, $4, $4, $4
       FROM latest_decisions d
     ON CONFLICT (space_id, project_id, source_item_id)
       WHERE source_item_id IS NOT NULL AND object_id IS NULL AND evidence_id IS NULL
     DO UPDATE SET status = 'active',
                   source_connection_id = COALESCE(project_corpus_items.source_connection_id, EXCLUDED.source_connection_id),
                   source_decision_id = EXCLUDED.source_decision_id,
                   relevance = EXCLUDED.relevance,
                   confidence = EXCLUDED.confidence,
                   triage_status = CASE
                     WHEN project_corpus_items.triage_confirmed_by_user THEN project_corpus_items.triage_status
                     WHEN project_corpus_items.triage_status IN ('new', 'relevant', 'maybe', 'excluded')
                       THEN EXCLUDED.triage_status
                     ELSE project_corpus_items.triage_status
                   END,
                   reason = COALESCE(EXCLUDED.reason, project_corpus_items.reason),
                   updated_at = EXCLUDED.updated_at,
                   last_reviewed_at = CASE
                     WHEN project_corpus_items.triage_confirmed_by_user THEN project_corpus_items.last_reviewed_at
                     WHEN project_corpus_items.triage_status IN ('new', 'relevant', 'maybe', 'excluded')
                       THEN EXCLUDED.updated_at
                     ELSE project_corpus_items.last_reviewed_at
                   END`,
    [input.spaceId, input.sourceItemId ?? null, input.projectId ?? null, now],
  );
  return result.rowCount ?? 0;
}

async function archiveCorpusSourceItemsWithoutActiveLinks(
  db: Queryable,
  input: { spaceId: string; sourceItemId?: string | null; projectId?: string | null },
): Promise<number> {
  const now = new Date().toISOString();
  const result = await db.query(
    `UPDATE project_corpus_items pci
        SET status = 'archived',
            updated_at = $4
      WHERE pci.space_id = $1
        AND pci.object_id IS NULL
        AND pci.evidence_id IS NULL
        AND pci.source_item_id IS NOT NULL
        AND pci.status = 'active'
        AND ($2::varchar IS NULL OR pci.source_item_id = $2)
        AND ($3::varchar IS NULL OR pci.project_id = $3)
        AND NOT EXISTS (
          SELECT 1
            FROM project_source_item_links psil
           WHERE psil.space_id = pci.space_id
             AND psil.project_id = pci.project_id
             AND psil.source_item_id = pci.source_item_id
             AND psil.status = 'active'
        )`,
    [input.spaceId, input.sourceItemId ?? null, input.projectId ?? null, now],
  );
  return result.rowCount ?? 0;
}

function projectCorpusItemOut(row: ProjectCorpusItemRow): Record<string, unknown> {
  return {
    id: row.id,
    space_id: row.space_id,
    project_id: row.project_id,
    object_id: row.object_id,
    source_item_id: row.source_item_id,
    evidence_id: row.evidence_id,
    source_connection_id: row.source_connection_id,
    source_decision_id: row.source_decision_id,
    role: row.role,
    status: row.status,
    triage_status: row.triage_status,
    triage_confirmed_by_user: row.triage_confirmed_by_user,
    read_status: row.read_status,
    relevance: row.relevance,
    confidence: row.confidence,
    reason: row.reason,
    added_by_user_id: row.added_by_user_id,
    metadata_json: objectValue(row.metadata_json),
    created_at: dateIso(row.created_at) ?? new Date(0).toISOString(),
    updated_at: dateIso(row.updated_at) ?? new Date(0).toISOString(),
    last_reviewed_at: dateIso(row.last_reviewed_at),
    last_read_at: dateIso(row.last_read_at),
    object: row.object_id
      ? {
          id: row.object_id,
          object_type: row.object_type,
          title: row.object_title,
          summary: row.object_summary,
          status: row.object_status,
          // academic_papers.paper_type is NOT NULL (defaults to 'article'),
          // so it's a reliable "the LEFT JOIN matched" signal — arxiv_id/doi
          // are both nullable and a manually-created paper can have neither.
          academic: row.academic_paper_type !== null
            ? {
                arxiv_id: row.academic_arxiv_id,
                doi: row.academic_doi,
                publication_date: dateIso(row.academic_publication_date),
                venue: row.academic_venue,
                paper_type: row.academic_paper_type,
                cited_by_count: row.academic_cited_by_count,
                reference_count: row.academic_reference_count,
                source_uri: row.academic_source_uri,
                authors: Array.isArray(row.academic_authors) ? row.academic_authors : [],
                categories: Array.isArray(row.academic_categories) ? row.academic_categories : [],
              }
            : null,
        }
      : null,
    source_item: row.source_item_id
      ? {
          id: row.source_item_id,
          item_type: row.source_item_type,
          title: row.source_item_title,
          source_uri: row.source_item_uri,
          source_domain: row.source_item_domain,
          excerpt: row.source_item_excerpt,
        }
      : null,
    evidence: row.evidence_id
      ? {
          id: row.evidence_id,
          evidence_type: row.evidence_type,
          title: row.evidence_title,
          content_excerpt: row.evidence_excerpt,
        }
      : null,
  };
}

function conflictClause(target: { objectId: string | null; evidenceId: string | null; sourceItemId: string | null }): string {
  if (target.objectId) {
    return `ON CONFLICT (space_id, project_id, object_id) WHERE object_id IS NOT NULL`;
  }
  if (target.evidenceId) {
    return `ON CONFLICT (space_id, project_id, evidence_id) WHERE evidence_id IS NOT NULL AND object_id IS NULL`;
  }
  return `ON CONFLICT (space_id, project_id, source_item_id) WHERE source_item_id IS NOT NULL AND object_id IS NULL AND evidence_id IS NULL`;
}

function roleValue(value: unknown): ProjectCorpusRole | null {
  const text = optionalString(value);
  if (!text) return null;
  if (!ROLES.has(text as ProjectCorpusRole)) throw new HttpError(422, "role is invalid");
  return text as ProjectCorpusRole;
}

function statusValue(value: unknown): ProjectCorpusStatus | null {
  const text = optionalString(value);
  if (!text) return null;
  if (!STATUSES.has(text as ProjectCorpusStatus)) throw new HttpError(422, "status must be active or archived");
  return text as ProjectCorpusStatus;
}

function triageStatusValue(value: unknown): ProjectCorpusTriageStatus | null {
  const text = optionalString(value);
  if (!text) return null;
  if (!TRIAGE_STATUSES.has(text as ProjectCorpusTriageStatus)) throw new HttpError(422, "triage_status is invalid");
  return text as ProjectCorpusTriageStatus;
}

function readStatusValue(value: unknown): ProjectCorpusReadStatus | null {
  const text = optionalString(value);
  if (!text) return null;
  if (!READ_STATUSES.has(text as ProjectCorpusReadStatus)) throw new HttpError(422, "read_status is invalid");
  return text as ProjectCorpusReadStatus;
}

function relevanceValue(value: unknown): ProjectCorpusRelevance | null {
  const text = optionalString(value);
  if (!text) return null;
  if (!RELEVANCES.has(text as ProjectCorpusRelevance)) throw new HttpError(422, "relevance is invalid");
  return text as ProjectCorpusRelevance;
}

function confidenceValue(value: unknown): number | null {
  if (value === undefined || value === null) return null;
  const confidence = numberValue(value);
  if (confidence === null) return null;
  if (confidence < 0 || confidence > 1) throw new HttpError(422, "confidence must be between 0 and 1");
  return confidence;
}

function escapeLike(value: string): string {
  return value.replace(/[\\%_]/g, (match) => `\\${match}`);
}
