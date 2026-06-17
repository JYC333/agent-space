import type { ServerModule } from "../../gateway/routeRegistry";
import { registerRoutes } from "./routes";

export const workspaceProfilesModule: ServerModule = {
  name: "workspace_profiles",
  registerRoutes,
};
