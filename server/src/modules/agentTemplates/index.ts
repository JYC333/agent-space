import type { ServerModule } from "../../gateway/routeRegistry";
import { registerRoutes } from "./routes";

export const agentTemplatesModule: ServerModule = { name: "agentTemplates", registerRoutes };
