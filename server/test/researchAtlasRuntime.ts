import { createRequire } from "node:module";

export interface ResearchAtlasRuntime {
  plugin: {
    researchAtlasPlugin: { migrations?: Array<{ id: string; sql: string }> };
  };
  routes: {
    registerResearchAtlasRoutes(app: unknown, db: unknown, ctx: unknown): void;
  };
  service: {
    researchAtlasService: {
      refreshPaperFromConnector(db: unknown, input: Record<string, unknown>): Promise<{ paper: Record<string, unknown>; refreshed: boolean }>;
    };
  };
  jobs: {
    buildResearchAtlasEnrichEntityHandler(db: unknown): (job: {
      job_id: string;
      job_type: string;
      payload: Record<string, unknown>;
      attempt_number: number;
    }) => Promise<Record<string, unknown> | null | undefined>;
  };
  proposalAppliers: {
    PROPOSAL_TYPE_RESEARCH_ATLAS_CURATION: string;
    applyResearchAtlasCuration(ctx: {
      proposal: {
        id: string;
        proposal_type: string;
        space_id: string | null;
        user_id: string | null;
        payload: Record<string, unknown>;
      };
      db: unknown;
      config: unknown;
    }): Promise<void>;
  };
}

export function loadResearchAtlasRuntime(): ResearchAtlasRuntime {
  const requireRuntime = createRequire(__filename);
  return {
    plugin: requireRuntime("../dist/official-plugins/research_atlas/server/index.js") as ResearchAtlasRuntime["plugin"],
    routes: requireRuntime("../dist/official-plugins/research_atlas/server/routes.js") as ResearchAtlasRuntime["routes"],
    service: requireRuntime("../dist/official-plugins/research_atlas/server/domain/service.js") as ResearchAtlasRuntime["service"],
    jobs: requireRuntime("../dist/official-plugins/research_atlas/server/jobs.js") as ResearchAtlasRuntime["jobs"],
    proposalAppliers: requireRuntime("../dist/official-plugins/research_atlas/server/proposalAppliers.js") as ResearchAtlasRuntime["proposalAppliers"],
  };
}
