import type { ServerModule } from "../../gateway/routeRegistry";
import { registerRoutes } from "./routes";

export const graphModule: ServerModule = { name: "graph", registerRoutes };
