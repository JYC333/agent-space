import type { ServerModule } from "../../gateway/routeRegistry";
import { registerRoutes } from "./routes";

export const sourcesModule: ServerModule = {
  name: "sources",
  registerRoutes,
};
