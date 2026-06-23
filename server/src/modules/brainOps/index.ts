import type { ServerModule } from "../../gateway/routeRegistry";
import { registerRoutes } from "./routes";

export const brainOpsModule: ServerModule = {
  name: "brainOps",
  registerRoutes,
};

export { BrainOpsService } from "./service";
