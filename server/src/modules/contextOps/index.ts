import type { ServerModule } from "../../gateway/routeRegistry";
import { registerRoutes } from "./routes";

export const contextOpsModule: ServerModule = {
  name: "contextOps",
  registerRoutes,
};

export { ContextOpsService } from "./service";
