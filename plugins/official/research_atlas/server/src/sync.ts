import { randomUUID } from "node:crypto";
import type { Queryable } from "@agent-space/protocol" with { "resolution-mode": "import" };
import { researchAtlasService } from "./domain/service";
import { nonEmptyString, publicationYearFromDate } from "./domain/identifiers";
import { addProjectCandidatesForIntakeItem } from "./projectOverlay";

const INTAKE_CURSOR_KEY = "intake_items";

interface IntakeItemRow {
  id: string;
  space_id: string;
  connection_id: string | null;
  title: string;
  source_external_id: string | null;
  author: string | null;
  excerpt: string | null;
  source_uri: string | null;
  canonical_uri: string | null;
  metadata_json: Record<string, unknown> | null;
  created_at: Date;
  updated_at: Date;
}

interface CursorWatermark {
  created_at?: string;
  id?: string;
}

export async function listEnabledAtlasSpaceIds(db: Queryable): Promise<string[]> {
  const result = await db.query<{ space_id: string }>(
    `SELECT space_id
       FROM official_plugin_enablements
      WHERE plugin_id = 'research_atlas'
        AND enabled
        AND space_id IS NOT NULL`,
  );
  return result.rows.map((row) => row.space_id);
}

export async function runResearchAtlasIntakeSync(
  db: Queryable,
  input: { spaceId: string; userId: string },
): Promise<{ imported: number; scanned: number; last_error: string | null }> {
  const cursor = await getCursor(db, input.spaceId, INTAKE_CURSOR_KEY);
  const items = await listArxivIntakeItems(db, input.spaceId, cursor, 50);
  let imported = 0;
  let lastSeen: IntakeItemRow | null = null;
  try {
    for (const item of items) {
      lastSeen = item;
      const metadata = item.metadata_json ?? {};
      const arxivId = nonEmptyString(metadata.arxiv_id) ?? item.source_external_id;
      if (!arxivId) continue;
      const doi = nonEmptyString(metadata.doi);
      const importedPaper = await researchAtlasService.importPaperMetadata(db, {
        spaceId: input.spaceId,
        userId: input.userId,
        connector: "intake",
        intakeItemId: item.id,
        paper: {
          title: item.title,
          abstract: item.excerpt,
          publication_date: nonEmptyString(metadata.published_at) ?? null,
          publication_year: publicationYearFromDate(nonEmptyString(metadata.published_at)),
          paper_type: "preprint",
          doi,
          arxiv_id: arxivId,
          raw_author_names: Array.isArray(metadata.authors)
            ? metadata.authors.filter((author): author is string => typeof author === "string")
            : splitAuthors(item.author),
          authors: (Array.isArray(metadata.authors)
            ? metadata.authors.filter((author): author is string => typeof author === "string")
            : splitAuthors(item.author)).map((name) => ({ name })),
          best_oa_url: nonEmptyString(metadata.pdf_url) ?? item.canonical_uri ?? item.source_uri,
          metadata_json: {
            intake_item_id: item.id,
            source_uri: item.source_uri,
            canonical_uri: item.canonical_uri,
            arxiv_categories: metadata.categories ?? null,
          },
        },
      });
      await addProjectCandidatesForIntakeItem(db, {
        spaceId: input.spaceId,
        userId: input.userId,
        paperId: importedPaper.paper.id,
        intakeItemId: item.id,
        connectionId: item.connection_id,
      });
      imported += 1;
    }
    await upsertCursor(db, input.spaceId, INTAKE_CURSOR_KEY, lastSeen ? {
      created_at: lastSeen.created_at.toISOString(),
      id: lastSeen.id,
    } : cursor, null);
    return { imported, scanned: items.length, last_error: null };
  } catch (err) {
    const message = err instanceof Error ? err.message : "intake sync failed";
    await upsertCursor(db, input.spaceId, INTAKE_CURSOR_KEY, cursor, message);
    return { imported, scanned: items.length, last_error: message };
  }
}

export async function getResearchAtlasSyncStatus(db: Queryable, spaceId: string) {
  const cursors = await db.query(
    `SELECT cursor_key, watermark_json, last_run_at, last_error, updated_at
       FROM research_atlas_sync_cursors
      WHERE space_id = $1
      ORDER BY cursor_key`,
    [spaceId],
  );
  const dueRefresh = await db.query<{ count: string }>(
    `SELECT count(*)::text AS count
       FROM research_atlas_source_records
      WHERE space_id = $1
        AND refresh_after IS NOT NULL
        AND refresh_after <= now()`,
    [spaceId],
  );
  return {
    cursors: cursors.rows,
    due_refresh_count: Number(dueRefresh.rows[0]?.count ?? 0),
  };
}

async function getCursor(db: Queryable, spaceId: string, cursorKey: string): Promise<CursorWatermark> {
  const result = await db.query<{ watermark_json: Record<string, unknown> }>(
    `SELECT watermark_json
       FROM research_atlas_sync_cursors
      WHERE space_id = $1
        AND cursor_key = $2
      LIMIT 1`,
    [spaceId, cursorKey],
  );
  return result.rows[0]?.watermark_json as CursorWatermark ?? {};
}

async function upsertCursor(
  db: Queryable,
  spaceId: string,
  cursorKey: string,
  watermark: CursorWatermark,
  lastError: string | null,
): Promise<void> {
  await db.query(
    `INSERT INTO research_atlas_sync_cursors (
       id, space_id, cursor_key, watermark_json, last_run_at, last_error, created_at, updated_at
     ) VALUES ($1, $2, $3, $4::jsonb, $5, $6, $5, $5)
     ON CONFLICT (space_id, cursor_key)
     DO UPDATE SET
       watermark_json = EXCLUDED.watermark_json,
       last_run_at = EXCLUDED.last_run_at,
       last_error = EXCLUDED.last_error,
       updated_at = EXCLUDED.updated_at`,
    [randomUUID(), spaceId, cursorKey, JSON.stringify(watermark), new Date(), lastError],
  );
}

async function listArxivIntakeItems(
  db: Queryable,
  spaceId: string,
  cursor: CursorWatermark,
  limit: number,
): Promise<IntakeItemRow[]> {
  const params: unknown[] = [spaceId];
  let cursorSql = "";
  if (cursor.created_at && cursor.id) {
    params.push(cursor.created_at, cursor.id);
    cursorSql = `AND (created_at, id) > ($${params.length - 1}::timestamptz, $${params.length})`;
  }
  params.push(limit);
  const result = await db.query<IntakeItemRow>(
    `SELECT id, space_id, connection_id, title, source_external_id, author, excerpt, source_uri,
            canonical_uri, metadata_json, created_at, updated_at
       FROM intake_items
      WHERE space_id = $1
        AND deleted_at IS NULL
        AND item_type = 'feed_entry'
        AND (
          metadata_json ? 'arxiv_id'
          OR source_external_id ~ '^[0-9]{4}\\.[0-9]{4,5}'
          OR coalesce(source_uri, canonical_uri, '') ILIKE '%arxiv.org%'
        )
        ${cursorSql}
      ORDER BY created_at ASC, id ASC
      LIMIT $${params.length}`,
    params,
  );
  return result.rows;
}

function splitAuthors(value: string | null): string[] {
  if (!value) return [];
  return value.split(/,|;/).map((item) => item.trim()).filter(Boolean);
}
