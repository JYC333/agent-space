import type { ServerModule } from "../../gateway/routeRegistry";
import { registerRoutes } from "./routes";

export const publicationsModule: ServerModule = {
  name: "publications",
  registerRoutes,
};
