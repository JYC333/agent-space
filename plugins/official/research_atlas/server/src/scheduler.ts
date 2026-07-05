import type { PluginHostContext, PluginScheduledTask, Queryable } from "@agent-space/protocol" with { "resolution-mode": "import" };
import { JOB_TYPE_RESEARCH_ATLAS_ENRICH_ENTITY } from "./jobs";
import { listEnabledAtlasSpaceIds, runResearchAtlasIntakeSync } from "./sync";

export function buildResearchAtlasIntakeSyncTask(db: Queryable): PluginScheduledTask {
  return {
    name: "research_atlas_intake_sync",
    intervalSeconds: 600,
    runOnStart: false,
    async run() {
      const spaces = await listEnabledAtlasSpaceIds(db);
      for (const spaceId of spaces) {
        await runResearchAtlasIntakeSync(db, { spaceId, userId: "system" });
      }
    },
  };
}

export function buildResearchAtlasRefreshSweepTask(ctx: PluginHostContext): PluginScheduledTask {
  return {
    name: "research_atlas_refresh_sweep",
    intervalSeconds: 3600,
    runOnStart: false,
    async run() {
      const spaces = await listEnabledAtlasSpaceIds(ctx.db);
      if (!spaces.length) return;
      const due = await ctx.db.query<{ space_id: string; paper_id: string; connector: string }>(
        `SELECT sr.space_id, es.entity_id AS paper_id, sr.connector
           FROM research_atlas_source_records sr
           JOIN research_atlas_entity_sources es ON es.source_record_id = sr.id
          WHERE sr.space_id = ANY($1::varchar[])
            AND sr.entity_type = 'paper'
            AND sr.refresh_after IS NOT NULL
            AND sr.refresh_after <= now()
          ORDER BY sr.refresh_after ASC
          LIMIT 50`,
        [spaces],
      );
      for (const row of due.rows) {
        await ctx.jobs.enqueue(
          JOB_TYPE_RESEARCH_ATLAS_ENRICH_ENTITY,
          { space_id: row.space_id, paper_id: row.paper_id, connector: row.connector },
          { spaceId: row.space_id, userId: "system" },
        );
      }
    },
  };
}

export function registerResearchAtlasScheduler(ctx: PluginHostContext): void {
  ctx.scheduler.register(buildResearchAtlasIntakeSyncTask(ctx.db));
  ctx.scheduler.register(buildResearchAtlasRefreshSweepTask(ctx));
}
