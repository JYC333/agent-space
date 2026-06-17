import type { ServerModule } from "../../gateway/routeRegistry";
import { registerRoutes } from "./routes";

export const knowledgeModule: ServerModule = {
  name: "knowledge",
  registerRoutes,
};

