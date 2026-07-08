import type { Queryable } from "../routeUtils/common";

/**
 * Auto-link an source item's extracted evidence to every project bound to the
 * item's source connection through an active `workspace_source_bindings` row
 * whose workspace is still linked to that project.
 *
 * Run-context evidence selection reads only `evidence_links`, so without these
 * links scheduled collection never reaches project agent runs. Links are
 * `context_candidate` and idempotent via the partial unique index
 * `uq_evidence_links_active_dedupe`; re-scans and re-extractions are no-ops.
 *
 * Returns the number of links created.
 */
export async function linkEvidenceToBoundProjects(
  db: Queryable,
  input: { spaceId: string; sourceItemId: string },
): Promise<number> {
  const now = new Date().toISOString();
  const result = await db.query(
    `INSERT INTO evidence_links (
       id, space_id, evidence_id, target_type, target_id, link_type,
       status, reason, created_at, updated_at
     )
     SELECT DISTINCT ON (ev.id, wsb.project_id)
            gen_random_uuid()::varchar, ev.space_id, ev.id, 'project', wsb.project_id, 'context_candidate',
            'active', 'workspace_source_binding:' || wsb.id, $3, $3
       FROM extracted_evidence ev
       JOIN source_items ii
         ON ii.space_id = ev.space_id
        AND ii.id = ev.source_item_id
        AND ii.deleted_at IS NULL
       JOIN workspace_source_bindings wsb
         ON wsb.space_id = ii.space_id
        AND (
          wsb.source_connection_id = ii.connection_id
          OR EXISTS (
            SELECT 1
              FROM source_snapshots ss
             WHERE ss.space_id = ii.space_id
               AND ss.source_item_id = ii.id
               AND ss.connection_id = wsb.source_connection_id
          )
        )
        AND wsb.status = 'active'
        AND EXISTS (
         SELECT 1
           FROM project_workspaces pw
          WHERE pw.space_id = wsb.space_id
            AND pw.project_id = wsb.project_id
            AND pw.workspace_id = wsb.workspace_id
       )
      WHERE ev.space_id = $1
        AND ev.source_item_id = $2
        AND ev.deleted_at IS NULL
      ORDER BY ev.id, wsb.project_id, wsb.priority DESC, wsb.id
     ON CONFLICT (space_id, evidence_id, target_type, target_id, link_type)
       WHERE status = 'active'
     DO NOTHING`,
    [input.spaceId, input.sourceItemId, now],
  );
  return result.rowCount ?? 0;
}

/**
 * Backfill project-context evidence links for one existing source binding.
 *
 * This is the historical counterpart to `linkEvidenceToBoundProjects`: creating
 * a binding starts routing future evidence, while this scans already-extracted
 * source evidence for the bound source and materializes the same project
 * `context_candidate` links.
 */
export async function backfillEvidenceForWorkspaceSourceBinding(
  db: Queryable,
  input: { spaceId: string; bindingId: string },
): Promise<number> {
  const now = new Date().toISOString();
  const result = await db.query(
    `INSERT INTO evidence_links (
       id, space_id, evidence_id, target_type, target_id, link_type,
       status, reason, created_at, updated_at
     )
     SELECT DISTINCT ON (ev.id, wsb.project_id)
            gen_random_uuid()::varchar, ev.space_id, ev.id, 'project', wsb.project_id, 'context_candidate',
            'active', 'workspace_source_binding:' || wsb.id, $3, $3
       FROM workspace_source_bindings wsb
       JOIN source_items ii
         ON ii.space_id = wsb.space_id
        AND ii.deleted_at IS NULL
        AND (
          ii.connection_id = wsb.source_connection_id
          OR EXISTS (
            SELECT 1
              FROM source_snapshots ss
             WHERE ss.space_id = ii.space_id
               AND ss.source_item_id = ii.id
               AND ss.connection_id = wsb.source_connection_id
          )
        )
       JOIN extracted_evidence ev
         ON ev.space_id = ii.space_id
        AND ev.source_item_id = ii.id
        AND ev.deleted_at IS NULL
      WHERE wsb.space_id = $1
        AND wsb.id = $2
        AND wsb.status = 'active'
        AND EXISTS (
         SELECT 1
           FROM project_workspaces pw
          WHERE pw.space_id = wsb.space_id
            AND pw.project_id = wsb.project_id
            AND pw.workspace_id = wsb.workspace_id
       )
      ORDER BY ev.id, wsb.project_id, wsb.priority DESC, wsb.id
     ON CONFLICT (space_id, evidence_id, target_type, target_id, link_type)
       WHERE status = 'active'
     DO NOTHING`,
    [input.spaceId, input.bindingId, now],
  );
  return result.rowCount ?? 0;
}
