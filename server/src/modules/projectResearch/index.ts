import type { ServerModule } from "../../gateway/routeRegistry";
import { registerRoutes } from "./routes";

export const projectResearchModule: ServerModule = {
  name: "project_research",
  registerRoutes,
};

export { __setProjectResearchRepositoryFactoryForTests, __setProjectExperimentRepositoryFactoryForTests } from "./routes";
export { ProjectResearchRepository, ARTIFACT_TYPES } from "./repository";
export { ProjectExperimentRepository } from "./experimentRepository";
