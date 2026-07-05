import type { ServerModule } from "../../gateway/routeRegistry";
import { registerRoutes } from "./routes";

export const agentGroupsModule: ServerModule = {
  name: "agentGroups",
  registerRoutes,
};

export { __setAgentGroupsServiceFactoryForTests } from "./routes";
export { AgentGroupRunService, authorityWidening } from "./service";
export { PgAgentGroupRepository } from "./repository";
export { AgentGroupRuntimeDelegationMaterializer } from "./runtimeDelegationMaterializer";
export { AgentGroupRunLifecycleProjector } from "./lifecycleProjector";
