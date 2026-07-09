import { randomUUID } from "node:crypto";
import type { Queryable } from "../routeUtils/common";

interface SourceItemForMaterialization {
  id: string;
  space_id: string;
  title: string;
  metadata_json: unknown;
  source_object_id: string | null;
  created_by_user_id: string | null;
}

interface ArxivItemMetadata {
  arxivId: string;
  doi: string | null;
  authors: string[];
  categories: string[];
  primaryCategory: string | null;
  publishedAt: string | null;
  updatedAt: string | null;
  absUrl: string | null;
  htmlUrl: string | null;
  pdfUrl: string | null;
  journalRef: string | null;
  comment: string | null;
}

export interface MaterializeAcademicPaperResult {
  objectId: string;
  created: boolean;
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

function stringOrNull(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function stringArray(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string" && item.trim().length > 0)
    : [];
}

/**
 * arXiv metadata is only present when the item was scanned via the arXiv
 * connector (`SourceExtractionWorker.scanArxiv`), which stores these exact
 * keys on `source_items.metadata_json`. Items without `arxiv_id` are not
 * arXiv papers and are left untouched (not every source item run through
 * this path is academic literature).
 */
function arxivMetadataFromItem(item: SourceItemForMaterialization): ArxivItemMetadata | null {
  const meta = record(item.metadata_json);
  const arxivId = stringOrNull(meta.arxiv_id);
  if (!arxivId) return null;
  return {
    arxivId,
    doi: stringOrNull(meta.doi),
    authors: stringArray(meta.authors),
    categories: stringArray(meta.categories),
    primaryCategory: stringOrNull(meta.primary_category),
    publishedAt: stringOrNull(meta.published_at),
    updatedAt: stringOrNull(meta.updated_at),
    absUrl: stringOrNull(meta.abs_url),
    htmlUrl: stringOrNull(meta.html_url),
    pdfUrl: stringOrNull(meta.pdf_url),
    journalRef: stringOrNull(meta.journal_ref),
    comment: stringOrNull(meta.comment),
  };
}

/**
 * Materializes an arXiv-derived `source_item` into an `academic_paper_v1`
 * object: `space_objects` (object_type='source') + `sources`
 * (source_type='paper') + `academic_papers`, deduped per space by
 * arxiv_id/doi (matches the partial unique indexes on `academic_papers`).
 * Idempotent — a source_item whose `source_object_id` is already set is
 * treated as already materialized, and re-running against an existing
 * arxiv_id/doi links the item to that paper instead of creating a duplicate.
 *
 * Author/category strings stay on the paper's `sources.metadata_json` only.
 * Canonical `person` objects are not auto-created from author strings
 * without a disambiguation/review path.
 *
 * Returns null when the item does not exist or is not an arXiv item.
 */
export async function materializeAcademicPaperFromSourceItem(
  db: Queryable,
  input: { spaceId: string; sourceItemId: string },
): Promise<MaterializeAcademicPaperResult | null> {
  const itemResult = await db.query<SourceItemForMaterialization>(
    `SELECT id, space_id, title, metadata_json, source_object_id, created_by_user_id
       FROM source_items
      WHERE space_id = $1 AND id = $2 AND deleted_at IS NULL
      LIMIT 1`,
    [input.spaceId, input.sourceItemId],
  );
  const item = itemResult.rows[0];
  if (!item) return null;
  if (item.source_object_id) return { objectId: item.source_object_id, created: false };

  const arxiv = arxivMetadataFromItem(item);
  if (!arxiv) return null;

  const existing = await db.query<{ object_id: string }>(
    `SELECT ap.object_id
       FROM academic_papers ap
       JOIN space_objects so ON so.id = ap.object_id AND so.space_id = ap.space_id
      WHERE ap.space_id = $1
        AND so.deleted_at IS NULL
        AND (ap.arxiv_id = $2 OR ($3::varchar IS NOT NULL AND ap.doi = $3))
      LIMIT 1`,
    [input.spaceId, arxiv.arxivId, arxiv.doi],
  );
  const now = new Date().toISOString();
  const existingObjectId = existing.rows[0]?.object_id;
  if (existingObjectId) {
    await db.query(
      `UPDATE source_items
          SET source_object_id = $3, source_object_type = 'source', updated_at = $4
        WHERE space_id = $1 AND id = $2 AND source_object_id IS NULL`,
      [input.spaceId, input.sourceItemId, existingObjectId, now],
    );
    return { objectId: existingObjectId, created: false };
  }

  const objectId = randomUUID();
  const title = (item.title?.trim() || arxiv.arxivId).slice(0, 1024);
  await db.query(
    `INSERT INTO space_objects (
       id, space_id, object_type, title, summary, status, visibility,
       created_by_user_id, created_at, updated_at
     ) VALUES ($1, $2, 'source', $3, NULL, 'processed', 'space_shared', $4, $5, $5)`,
    [objectId, input.spaceId, title, item.created_by_user_id, now],
  );
  await db.query(
    `INSERT INTO sources (object_id, space_id, source_type, uri, metadata_json)
     VALUES ($1, $2, 'paper', $3, $4::jsonb)`,
    [
      objectId,
      input.spaceId,
      arxiv.absUrl,
      JSON.stringify({
        authors: arxiv.authors,
        categories: arxiv.categories,
        primary_category: arxiv.primaryCategory,
        abs_url: arxiv.absUrl,
        html_url: arxiv.htmlUrl,
        pdf_url: arxiv.pdfUrl,
        journal_ref: arxiv.journalRef,
        comment: arxiv.comment,
      }),
    ],
  );
  await db.query(
    `INSERT INTO academic_papers (
       object_id, space_id, doi, arxiv_id, pmid, openalex_id, publication_date,
       venue, paper_type, created_at, updated_at
     ) VALUES ($1, $2, $3, $4, NULL, NULL, $5::timestamptz, NULL, 'preprint', $6, $6)`,
    [objectId, input.spaceId, arxiv.doi, arxiv.arxivId, arxiv.publishedAt ?? arxiv.updatedAt, now],
  );
  await db.query(
    `UPDATE source_items
        SET source_object_id = $3, source_object_type = 'source', updated_at = $4
      WHERE space_id = $1 AND id = $2`,
    [input.spaceId, input.sourceItemId, objectId, now],
  );
  return { objectId, created: true };
}
