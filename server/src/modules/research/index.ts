import type { ServerModule } from "../../gateway/routeRegistry";
import { registerRoutes } from "./routes";
export const researchModule: ServerModule = { name: "research", registerRoutes };
export { ResearchEngineService } from "./engine/service";
