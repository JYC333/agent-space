import type { ServerModule } from "../../gateway/routeRegistry";
import { registerRoutes } from "./routes";

export const workspacesModule: ServerModule = {
  name: "workspaces",
  registerRoutes,
};

export {
  __setWorkspaceIdentityForTests,
  __setWorkspaceServicesFactoryForTests,
} from "./routes";
export { PgWorkspaceManager } from "./sandbox";
export type { RunWorkspaceManagerPort, PreparedWorkspaceRuntime } from "./sandbox";
export { PgCodePatchCollector, registerWorkspaceProposalAppliers } from "./codePatch";
