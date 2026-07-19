import { randomUUID } from "node:crypto";
import type { Queryable } from "../routeUtils/common";
import {
  syncProjectCorpusEvidenceForSourceItem,
  syncProjectCorpusForSourceItem,
} from "./corpusRepository";
import { materializeAcademicPaperFromSourceItem } from "../academic/paperMaterializer";

type ProjectSourceBindingFilterRow = {
  id: string;
  space_id: string;
  project_id: string;
  source_channel_id: string;
  priority: number;
  filters_json: unknown;
  collection_notifications_enabled: boolean;
  extraction_policy_json: unknown;
};

function extractionProfileKey(value: unknown): string | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const profileKey = (value as Record<string, unknown>).profile_key;
  return typeof profileKey === "string" && profileKey.trim() ? profileKey.trim() : null;
}

type SourceItemFilterRow = {
  id: string;
  space_id: string;
  connection_id: string | null;
  item_type: string;
  title: string | null;
  excerpt: string | null;
  source_uri: string | null;
  source_domain: string | null;
};

export type ProjectSourceBackfillResult = {
  created_links: number;
  reactivated_links: number;
  archived_links: number;
  evidence_links: number;
};

/**
 * The single producer-to-consumer seam used by Sources. Projects owns all
 * binding, link, evidence-routing, and corpus synchronization writes.
 */
export class ProjectSourceRoutingService {
  constructor(private readonly db: Queryable) {}

  routeMaterializedItem(input: { spaceId: string; sourceItemId: string; bindingId?: string | null; archiveNonMatching?: boolean }) {
    return materializeProjectSourceItemLinks(this.db, input);
  }

  routeEvidence(input: { spaceId: string; sourceItemId: string }, options: { materializeSourceItemLinks?: boolean } = {}) {
    return linkEvidenceToBoundProjects(this.db, input, options);
  }

  recomputeBinding(input: { spaceId: string; bindingId: string }) {
    return recomputeProjectSourceBindingLinks(this.db, input);
  }
}

function stringList(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string" && item.trim().length > 0)
    : [];
}

function filterText(item: SourceItemFilterRow): string {
  return [
    item.title,
    item.excerpt,
    item.source_uri,
    item.source_domain,
    item.item_type,
  ].filter(Boolean).join(" ").toLowerCase();
}

export function sourceItemMatchesProjectFilters(item: SourceItemFilterRow, filters: unknown): boolean {
  if (!filters || typeof filters !== "object" || Array.isArray(filters)) return true;
  const values = filters as Record<string, unknown>;
  const text = filterText(item);
  const keywordsAny = stringList(values.keywords_any).map((value) => value.toLowerCase());
  const keywordsAll = stringList(values.keywords_all).map((value) => value.toLowerCase());
  const excludeKeywords = stringList(values.exclude_keywords).map((value) => value.toLowerCase());
  const itemTypes = stringList(values.item_types);
  const sourceDomains = stringList(values.source_domains).map((value) => value.toLowerCase());

  if (itemTypes.length && !itemTypes.includes(item.item_type)) return false;
  if (sourceDomains.length && (!item.source_domain || !sourceDomains.includes(item.source_domain.toLowerCase()))) return false;
  if (keywordsAny.length && !keywordsAny.some((keyword) => text.includes(keyword))) return false;
  if (keywordsAll.length && !keywordsAll.every((keyword) => text.includes(keyword))) return false;
  if (excludeKeywords.some((keyword) => text.includes(keyword))) return false;
  return true;
}

async function itemRow(db: Queryable, spaceId: string, sourceItemId: string): Promise<SourceItemFilterRow | null> {
  const result = await db.query<SourceItemFilterRow>(
    `SELECT si.id, si.space_id,
            COALESCE(
              si.connection_id,
              (
                SELECT ss.connection_id
                  FROM source_snapshots ss
                 WHERE ss.space_id = si.space_id
                   AND ss.source_item_id = si.id
                   AND ss.connection_id IS NOT NULL
                 ORDER BY ss.captured_at DESC, ss.id DESC
                 LIMIT 1
              )
            ) AS connection_id,
            si.item_type, si.title, si.excerpt, si.source_uri, si.source_domain
       FROM source_items si
      WHERE si.space_id = $1
        AND si.id = $2
        AND si.deleted_at IS NULL
      LIMIT 1`,
    [spaceId, sourceItemId],
  );
  return result.rows[0] ?? null;
}

async function matchingBindingRows(
  db: Queryable,
  item: SourceItemFilterRow,
  bindingId: string | null,
): Promise<ProjectSourceBindingFilterRow[]> {
  const result = await db.query<ProjectSourceBindingFilterRow>(
    `SELECT psb.id, psb.space_id, psb.project_id, psb.source_channel_id,
            psb.priority, psb.filters_json, psb.collection_notifications_enabled,
            psb.extraction_policy_json
       FROM project_source_bindings psb
      WHERE psb.space_id = $1
        AND psb.status = 'active'
        AND ($3::varchar IS NULL OR psb.id = $3)
        AND (
          EXISTS (
            SELECT 1 FROM source_channel_item_links sci
             WHERE sci.space_id = psb.space_id
               AND sci.source_channel_id = psb.source_channel_id
               AND sci.source_item_id = $4
               AND sci.status = 'active'
          )
          OR EXISTS (
            SELECT 1 FROM source_channels ch
             WHERE ch.space_id = psb.space_id
               AND ch.id = psb.source_channel_id
               AND ch.source_connection_id = $2
          )
        )
      ORDER BY psb.priority DESC, psb.id ASC`,
    [item.space_id, item.connection_id, bindingId, item.id],
  );
  return result.rows;
}

async function upsertProjectSourceCollectionActivity(
  db: Queryable,
  input: { spaceId: string; projectId: string; sourceConnectionId: string; localDate: string; now: string },
): Promise<void> {
  const aggregateKey = `project_source_collection:${input.projectId}:${input.localDate}`;
  const payload = {
    pointer_type: "project_source_collection",
    project_id: input.projectId,
    source_connection_id: input.sourceConnectionId,
    local_date: input.localDate,
  };
  await db.query(
    `INSERT INTO activity_records (
       id, space_id, project_id, activity_type, title, content, payload_json,
       occurred_at, created_at, status, updated_at, source_kind, source_trust,
       visibility, aggregate_key
     ) VALUES (
       $1, $2, $3, 'project_source_collection', 'New project source items',
       'New source items were collected for this project.', $4::jsonb,
       $5::timestamptz, $5::timestamptz, 'raw', $5::timestamptz, 'source', 'internal_system',
       'space_shared', $6
     )
     ON CONFLICT (space_id, aggregate_key) WHERE aggregate_key IS NOT NULL
     DO UPDATE SET payload_json = activity_records.payload_json || EXCLUDED.payload_json,
                   occurred_at = GREATEST(activity_records.occurred_at, EXCLUDED.occurred_at),
                   updated_at = EXCLUDED.updated_at,
                   status = 'raw',
                   processed_at = NULL,
                   discarded_at = NULL`,
    [randomUUID(), input.spaceId, input.projectId, JSON.stringify(payload), input.now, aggregateKey],
  );
}

export async function materializeProjectSourceItemLinks(
  db: Queryable,
  input: { spaceId: string; sourceItemId: string; bindingId?: string | null; archiveNonMatching?: boolean },
): Promise<{ created: number; reactivated: number; archived: number }> {
  const item = await itemRow(db, input.spaceId, input.sourceItemId);
  if (!item) return { created: 0, reactivated: 0, archived: 0 };
  const bindings = await matchingBindingRows(db, item, input.bindingId ?? null);
  if (bindings.some((binding) => extractionProfileKey(binding.extraction_policy_json) === "academic_paper_v1")) {
    // Best-effort: a materialization failure (e.g. a dedupe race between
    // concurrent connection scans hitting the same arxiv_id) must not fail
    // the whole scan/extraction job over one item, mirroring the retrieval
    // reindex helpers in extractionWorker.ts.
    await materializeAcademicPaperFromSourceItem(db, { spaceId: input.spaceId, sourceItemId: input.sourceItemId }).catch((error) => {
      process.stderr.write(
        `[academic.paper_materializer] materialization failed (${input.sourceItemId}): ${String((error as Error)?.message ?? error)}\n`,
      );
    });
  }
  const now = new Date().toISOString();
  const localDate = now.slice(0, 10);
  let created = 0;
  let reactivated = 0;
  let archived = 0;

  for (const binding of bindings) {
    if (!sourceItemMatchesProjectFilters(item, binding.filters_json)) {
      if (input.archiveNonMatching) {
        const result = await db.query(
          `UPDATE project_source_item_links
              SET status = 'archived',
                  updated_at = $4
            WHERE space_id = $1
              AND project_source_binding_id = $2
              AND source_item_id = $3
              AND status = 'active'`,
          [input.spaceId, binding.id, input.sourceItemId, now],
        );
        archived += result.rowCount ?? 0;
      }
      continue;
    }
    const result = await db.query<{ was_created: boolean; was_reactivated: boolean }>(
      `INSERT INTO project_source_item_links (
         id, space_id, project_id, project_source_binding_id, source_channel_id, source_connection_id,
         source_item_id, status, matched_at, match_reason, created_at, updated_at
       ) VALUES (
         $1, $2, $3, $4::varchar, $5, $6,
         $7, 'active', $8, 'project_source_binding:' || $9::text, $10, $11
       )
       ON CONFLICT (space_id, project_id, project_source_binding_id, source_item_id)
       DO UPDATE SET status = 'active',
                     source_channel_id = EXCLUDED.source_channel_id,
                     source_connection_id = EXCLUDED.source_connection_id,
                     match_reason = EXCLUDED.match_reason,
                     updated_at = EXCLUDED.updated_at
       RETURNING (xmax = 0) AS was_created,
                 (xmax <> 0 AND project_source_item_links.status = 'active') AS was_reactivated`,
      [
        randomUUID(),
        input.spaceId,
        binding.project_id,
        binding.id,
        binding.source_channel_id,
        item.connection_id,
        input.sourceItemId,
        now,
        binding.id,
        now,
        now,
      ],
    );
    if (result.rows[0]?.was_created) created++;
    else reactivated++;
    if (binding.collection_notifications_enabled) {
      await upsertProjectSourceCollectionActivity(db, {
        spaceId: input.spaceId,
        projectId: binding.project_id,
        sourceConnectionId: item.connection_id ?? "",
        localDate,
        now,
      });
    }
  }

  await syncProjectCorpusForSourceItem(db, {
    spaceId: input.spaceId,
    sourceItemId: input.sourceItemId,
  });

  return { created, reactivated, archived };
}

export async function linkEvidenceToBoundProjects(
  db: Queryable,
  input: { spaceId: string; sourceItemId: string },
  options: { materializeSourceItemLinks?: boolean } = {},
): Promise<number> {
  if (options.materializeSourceItemLinks !== false) {
    await materializeProjectSourceItemLinks(db, input);
  }
  const now = new Date().toISOString();
  const result = await db.query(
    `INSERT INTO evidence_links (
       id, space_id, evidence_id, target_type, target_id, link_type,
       status, reason, created_at, updated_at
     )
     SELECT DISTINCT ON (ev.id, psil.project_id)
            gen_random_uuid()::varchar, ev.space_id, ev.id, 'project', psil.project_id, 'context_candidate',
            'active', 'project_source_binding:' || psil.project_source_binding_id, $3, $3
       FROM extracted_evidence ev
       JOIN project_source_item_links psil
         ON psil.space_id = ev.space_id
        AND psil.source_item_id = ev.source_item_id
        AND psil.status = 'active'
       JOIN project_source_bindings psb
         ON psb.id = psil.project_source_binding_id
        AND psb.space_id = psil.space_id
        AND psb.status = 'active'
      WHERE ev.space_id = $1
        AND ev.source_item_id = $2
        AND ev.deleted_at IS NULL
      ORDER BY ev.id, psil.project_id, psb.priority DESC, psil.project_source_binding_id
     ON CONFLICT (space_id, evidence_id, target_type, target_id, link_type)
       WHERE status = 'active'
     DO NOTHING`,
    [input.spaceId, input.sourceItemId, now],
  );
  await syncProjectCorpusEvidenceForSourceItem(db, {
    spaceId: input.spaceId,
    sourceItemId: input.sourceItemId,
  });
  return result.rowCount ?? 0;
}

export async function recomputeProjectSourceBindingLinks(
  db: Queryable,
  input: { spaceId: string; bindingId: string },
): Promise<ProjectSourceBackfillResult> {
  const items = await db.query<{ id: string }>(
    `SELECT DISTINCT si.id
       FROM project_source_bindings psb
       JOIN source_items si
         ON si.space_id = psb.space_id
        AND si.deleted_at IS NULL
        AND (
          EXISTS (
            SELECT 1 FROM source_channel_item_links sci
             WHERE sci.space_id = psb.space_id
               AND sci.source_channel_id = psb.source_channel_id
               AND sci.source_item_id = si.id
               AND sci.status = 'active'
          )
          OR EXISTS (
            SELECT 1 FROM source_channels ch
             WHERE ch.space_id = psb.space_id
               AND ch.id = psb.source_channel_id
               AND ch.source_connection_id = si.connection_id
          )
        )
      WHERE psb.space_id = $1
        AND psb.id = $2`,
    [input.spaceId, input.bindingId],
  );
  const totals: ProjectSourceBackfillResult = {
    created_links: 0,
    reactivated_links: 0,
    archived_links: 0,
    evidence_links: 0,
  };
  for (const item of items.rows) {
    const linkCounts = await materializeProjectSourceItemLinks(db, {
      spaceId: input.spaceId,
      sourceItemId: item.id,
      bindingId: input.bindingId,
      archiveNonMatching: true,
    });
    totals.created_links += linkCounts.created;
    totals.reactivated_links += linkCounts.reactivated;
    totals.archived_links += linkCounts.archived;
    totals.evidence_links += await linkEvidenceToBoundProjects(db, {
      spaceId: input.spaceId,
      sourceItemId: item.id,
    });
  }
  return totals;
}
