import type { ServerModule } from "../../gateway/routeRegistry";
import { registerRoutes } from "./routes";

export const personalMemoryGrantsModule: ServerModule = {
  name: "personalMemoryGrants",
  registerRoutes,
};
