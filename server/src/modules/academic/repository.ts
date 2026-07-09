import { randomUUID } from "node:crypto";
import type { PoolClient } from "../../db/pool";
import { HttpError, type Queryable } from "../routeUtils/common";

export interface AcademicPaperRow {
  object_id: string;
  space_id: string;
  title: string;
  summary: string | null;
  status: string;
  doi: string | null;
  arxiv_id: string | null;
  pmid: string | null;
  openalex_id: string | null;
  publication_date: unknown;
  venue: string | null;
  paper_type: string;
  cited_by_count: number | null;
  reference_count: number | null;
  created_at: unknown;
  updated_at: unknown;
}

export interface AcademicAuthorRow {
  person_object_id: string;
  title: string;
  author_position: number | null;
  is_corresponding: boolean;
  object_relation_id: string;
}

export interface AcademicCitationRow {
  paper_object_id: string;
  title: string;
  doi: string | null;
  arxiv_id: string | null;
}

const PAPER_COLUMNS = `
  so.id AS object_id, so.space_id, so.title, so.summary, so.status,
  ap.doi, ap.arxiv_id, ap.pmid, ap.openalex_id, ap.publication_date, ap.venue,
  ap.paper_type, ap.cited_by_count, ap.reference_count, ap.created_at, ap.updated_at
`;

export class AcademicRepository {
  constructor(private readonly db: Queryable) {}

  async createPaper(
    client: PoolClient,
    input: {
      spaceId: string;
      title: string;
      summary: string | null;
      doi: string | null;
      arxivId: string | null;
      pmid: string | null;
      openalexId: string | null;
      publicationDate: string | null;
      venue: string | null;
      paperType: string;
      sourceUri: string | null;
      createdByUserId: string | null;
    },
  ): Promise<AcademicPaperRow> {
    const objectId = randomUUID();
    const now = new Date().toISOString();
    await client.query(
      `INSERT INTO space_objects (
         id, space_id, object_type, title, summary, status, visibility,
         created_by_user_id, created_at, updated_at
       ) VALUES ($1, $2, 'source', $3, $4, 'raw', 'space_shared', $5, $6, $6)`,
      [objectId, input.spaceId, input.title, input.summary, input.createdByUserId, now],
    );
    await client.query(
      `INSERT INTO sources (object_id, space_id, source_type, uri, metadata_json)
       VALUES ($1, $2, 'paper', $3, '{}'::jsonb)`,
      [objectId, input.spaceId, input.sourceUri],
    );
    await client.query(
      `INSERT INTO academic_papers (
         object_id, space_id, doi, arxiv_id, pmid, openalex_id, publication_date,
         venue, paper_type, created_at, updated_at
       ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $10)`,
      [
        objectId,
        input.spaceId,
        input.doi,
        input.arxivId,
        input.pmid,
        input.openalexId,
        input.publicationDate,
        input.venue,
        input.paperType,
        now,
      ],
    );
    const created = await this.getPaper(client, input.spaceId, objectId);
    if (!created) throw new HttpError(500, "Failed to create academic paper");
    return created;
  }

  async getPaper(db: Queryable, spaceId: string, objectId: string): Promise<AcademicPaperRow | null> {
    const result = await db.query<AcademicPaperRow>(
      `SELECT ${PAPER_COLUMNS}
         FROM space_objects so
         JOIN academic_papers ap ON ap.object_id = so.id AND ap.space_id = so.space_id
        WHERE so.id = $1 AND so.space_id = $2 AND so.status <> 'deleted'
        LIMIT 1`,
      [objectId, spaceId],
    );
    return result.rows[0] ?? null;
  }

  async findByExternalId(
    spaceId: string,
    input: { doi: string | null; arxivId: string | null },
  ): Promise<AcademicPaperRow | null> {
    if (!input.doi && !input.arxivId) return null;
    const params: unknown[] = [spaceId];
    const clauses: string[] = [];
    if (input.doi) {
      params.push(input.doi);
      clauses.push(`ap.doi = $${params.length}`);
    }
    if (input.arxivId) {
      params.push(input.arxivId);
      clauses.push(`ap.arxiv_id = $${params.length}`);
    }
    const result = await this.db.query<AcademicPaperRow>(
      `SELECT ${PAPER_COLUMNS}
         FROM space_objects so
         JOIN academic_papers ap ON ap.object_id = so.id AND ap.space_id = so.space_id
        WHERE so.space_id = $1 AND so.status <> 'deleted' AND (${clauses.join(" OR ")})
        LIMIT 1`,
      params,
    );
    return result.rows[0] ?? null;
  }

  async listPapers(
    spaceId: string,
    filters: { q: string | null; limit: number; offset: number },
  ): Promise<{ rows: AcademicPaperRow[]; total: number }> {
    const params: unknown[] = [spaceId];
    const clauses = ["so.space_id = $1", "so.status <> 'deleted'"];
    if (filters.q) {
      params.push(`%${filters.q}%`);
      clauses.push(`so.title ILIKE $${params.length}`);
    }
    const where = clauses.join(" AND ");
    const limitParamIndex = params.length + 1;
    const offsetParamIndex = params.length + 2;
    const [rows, total] = await Promise.all([
      this.db.query<AcademicPaperRow>(
        `SELECT ${PAPER_COLUMNS}
           FROM space_objects so
           JOIN academic_papers ap ON ap.object_id = so.id AND ap.space_id = so.space_id
          WHERE ${where}
          ORDER BY ap.publication_date DESC NULLS LAST, so.title ASC
          LIMIT $${limitParamIndex} OFFSET $${offsetParamIndex}`,
        [...params, filters.limit, filters.offset],
      ),
      this.db.query<{ total: string }>(
        `SELECT COUNT(*)::text AS total
           FROM space_objects so
           JOIN academic_papers ap ON ap.object_id = so.id AND ap.space_id = so.space_id
          WHERE ${where}`,
        params,
      ),
    ]);
    return { rows: rows.rows, total: Number(total.rows[0]?.total ?? 0) };
  }

  async updatePaper(
    spaceId: string,
    objectId: string,
    patch: { title?: string; summary?: string | null; venue?: string | null; citedByCount?: number | null; referenceCount?: number | null },
  ): Promise<AcademicPaperRow | null> {
    const now = new Date().toISOString();
    if (patch.title !== undefined || patch.summary !== undefined) {
      await this.db.query(
        `UPDATE space_objects
            SET title = COALESCE($3, title), summary = CASE WHEN $4 THEN $5 ELSE summary END, updated_at = $6
          WHERE id = $1 AND space_id = $2`,
        [objectId, spaceId, patch.title ?? null, patch.summary !== undefined, patch.summary ?? null, now],
      );
    }
    if (patch.venue !== undefined || patch.citedByCount !== undefined || patch.referenceCount !== undefined) {
      await this.db.query(
        `UPDATE academic_papers
            SET venue = CASE WHEN $3 THEN $4 ELSE venue END,
                cited_by_count = CASE WHEN $5 THEN $6 ELSE cited_by_count END,
                reference_count = CASE WHEN $7 THEN $8 ELSE reference_count END,
                updated_at = $9
          WHERE object_id = $1 AND space_id = $2`,
        [
          objectId,
          spaceId,
          patch.venue !== undefined,
          patch.venue ?? null,
          patch.citedByCount !== undefined,
          patch.citedByCount ?? null,
          patch.referenceCount !== undefined,
          patch.referenceCount ?? null,
          now,
        ],
      );
    }
    return this.getPaper(this.db, spaceId, objectId);
  }

  async personExists(spaceId: string, objectId: string): Promise<boolean> {
    const result = await this.db.query(
      `SELECT 1 FROM space_objects WHERE id = $1 AND space_id = $2 AND object_type = 'person' AND status <> 'deleted' LIMIT 1`,
      [objectId, spaceId],
    );
    return result.rows.length > 0;
  }

  async linkAuthor(
    spaceId: string,
    paperObjectId: string,
    personObjectId: string,
    input: { authorPosition: number | null; isCorresponding: boolean; createdByUserId: string | null },
  ): Promise<string> {
    const id = randomUUID();
    const now = new Date().toISOString();
    const result = await this.db.query<{ id: string }>(
      `INSERT INTO object_relations (
         id, space_id, from_object_id, to_object_id, relation_type, status,
         metadata_json, created_by_user_id, created_at, updated_at
       ) VALUES ($1, $2, $3, $4, 'authored_by', 'active', $5::jsonb, $6, $7, $7)
       ON CONFLICT (space_id, from_object_id, to_object_id, relation_type)
       WHERE ((status)::text = 'active'::text)
       DO UPDATE SET
         metadata_json = EXCLUDED.metadata_json,
         updated_at = EXCLUDED.updated_at
       RETURNING id`,
      [
        id,
        spaceId,
        paperObjectId,
        personObjectId,
        JSON.stringify({ author_position: input.authorPosition, is_corresponding: input.isCorresponding }),
        input.createdByUserId,
        now,
      ],
    );
    return result.rows[0]!.id;
  }

  async listAuthors(spaceId: string, paperObjectId: string): Promise<AcademicAuthorRow[]> {
    const result = await this.db.query<AcademicAuthorRow>(
      `SELECT
         so.id AS person_object_id,
         so.title,
         (orl.metadata_json->>'author_position')::int AS author_position,
         COALESCE((orl.metadata_json->>'is_corresponding')::boolean, false) AS is_corresponding,
         orl.id AS object_relation_id
       FROM object_relations orl
       JOIN space_objects so ON so.id = orl.to_object_id AND so.space_id = orl.space_id
      WHERE orl.space_id = $1
        AND orl.from_object_id = $2
        AND orl.relation_type = 'authored_by'
        AND orl.status = 'active'
      ORDER BY author_position NULLS LAST, so.title ASC`,
      [spaceId, paperObjectId],
    );
    return result.rows;
  }

  async linkCitation(spaceId: string, citingPaperObjectId: string, citedPaperObjectId: string, createdByUserId: string | null): Promise<string> {
    const id = randomUUID();
    const now = new Date().toISOString();
    const result = await this.db.query<{ id: string }>(
      `INSERT INTO object_relations (
         id, space_id, from_object_id, to_object_id, relation_type, status,
         metadata_json, created_by_user_id, created_at, updated_at
       ) VALUES ($1, $2, $3, $4, 'cites', 'active', '{}'::jsonb, $5, $6, $6)
       ON CONFLICT (space_id, from_object_id, to_object_id, relation_type)
       WHERE ((status)::text = 'active'::text)
       DO UPDATE SET updated_at = EXCLUDED.updated_at
       RETURNING id`,
      [id, spaceId, citingPaperObjectId, citedPaperObjectId, createdByUserId, now],
    );
    return result.rows[0]!.id;
  }

  async listCitations(spaceId: string, paperObjectId: string): Promise<AcademicCitationRow[]> {
    const result = await this.db.query<AcademicCitationRow>(
      `SELECT so.id AS paper_object_id, so.title, ap.doi, ap.arxiv_id
         FROM object_relations orl
         JOIN space_objects so ON so.id = orl.to_object_id AND so.space_id = orl.space_id
         JOIN academic_papers ap ON ap.object_id = so.id AND ap.space_id = so.space_id
        WHERE orl.space_id = $1 AND orl.from_object_id = $2 AND orl.relation_type = 'cites' AND orl.status = 'active'
        ORDER BY so.title ASC`,
      [spaceId, paperObjectId],
    );
    return result.rows;
  }

  async listCitedBy(spaceId: string, paperObjectId: string): Promise<AcademicCitationRow[]> {
    const result = await this.db.query<AcademicCitationRow>(
      `SELECT so.id AS paper_object_id, so.title, ap.doi, ap.arxiv_id
         FROM object_relations orl
         JOIN space_objects so ON so.id = orl.from_object_id AND so.space_id = orl.space_id
         JOIN academic_papers ap ON ap.object_id = so.id AND ap.space_id = so.space_id
        WHERE orl.space_id = $1 AND orl.to_object_id = $2 AND orl.relation_type = 'cites' AND orl.status = 'active'
        ORDER BY so.title ASC`,
      [spaceId, paperObjectId],
    );
    return result.rows;
  }
}
