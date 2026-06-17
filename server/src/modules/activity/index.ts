import type { ServerModule } from "../../gateway/routeRegistry";
import { registerRoutes } from "./routes";

export const activityModule: ServerModule = {
  name: "activity",
  registerRoutes,
};

