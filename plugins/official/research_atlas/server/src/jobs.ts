import type { PluginHostContext, PluginJobHandler, Queryable } from "@agent-space/protocol" with { "resolution-mode": "import" };
import {
  fetchCitationMetadataByConnector,
  fillCitationEdgesFromMetadata,
} from "./domain/citations";
import { fetchOpenAlexWorkByDoi } from "./domain/openalex";
import { researchAtlasService } from "./domain/service";

export const JOB_TYPE_RESEARCH_ATLAS_ENRICH_ENTITY = "research_atlas_enrich_entity";

export function buildResearchAtlasEnrichEntityHandler(db: Queryable): PluginJobHandler {
  return async (job) => {
    const paperId = typeof job.payload.paper_id === "string" ? job.payload.paper_id : null;
    const spaceId = typeof job.payload.space_id === "string" ? job.payload.space_id : null;
    if (!paperId || !spaceId) {
      return { skipped: true, reason: "missing_paper_or_space" };
    }
    const connector = typeof job.payload.connector === "string" ? job.payload.connector : null;
    const connectorEmail = typeof job.payload.connector_email === "string" ? job.payload.connector_email : null;
    const userId = typeof job.payload.user_id === "string" ? job.payload.user_id : "research_atlas";
    let metadata = job.payload.metadata && typeof job.payload.metadata === "object"
      ? job.payload.metadata as Record<string, unknown>
      : null;
    if (!metadata && connector === "openalex") {
      const paper = await db.query<{ doi: string | null }>(
        "SELECT doi FROM research_atlas_papers WHERE space_id = $1 AND id = $2",
        [spaceId, paperId],
      );
      if (paper.rows[0]?.doi) {
        metadata = await fetchOpenAlexWorkByDoi(paper.rows[0].doi, connectorEmail) as Record<string, unknown> | null;
      }
    }
    if (!metadata && (connector === "s2" || connector === "opencitations")) {
      const paper = await db.query<{ doi: string | null }>(
        "SELECT doi FROM research_atlas_papers WHERE space_id = $1 AND id = $2",
        [spaceId, paperId],
      );
      if (paper.rows[0]?.doi) {
        metadata = await fetchCitationMetadataByConnector(connector, paper.rows[0].doi) as Record<string, unknown> | null;
      }
    }
    const result = await researchAtlasService.refreshPaperFromConnector(db, {
      spaceId,
      paperId,
      connector,
      metadata,
      connectorEmail,
    });
    const citationFill = metadata && (connector === "s2" || connector === "opencitations")
      ? await fillCitationEdgesFromMetadata(db, {
        spaceId,
        userId,
        paperId,
        connector,
        metadata,
      })
      : null;
    return {
      refreshed: result.refreshed,
      paper_id: result.paper.id,
      citation_fill: citationFill,
    };
  };
}

export function registerResearchAtlasJobs(ctx: PluginHostContext): void {
  ctx.jobs.register(JOB_TYPE_RESEARCH_ATLAS_ENRICH_ENTITY, buildResearchAtlasEnrichEntityHandler(ctx.db));
}
