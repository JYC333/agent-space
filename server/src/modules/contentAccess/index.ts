import type { ServerModule } from "../../gateway/routeRegistry";
import { registerRoutes } from "./routes";

export const contentAccessModule: ServerModule = {
  name: "contentAccess",
  registerRoutes,
};
