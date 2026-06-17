import type { ServerModule } from "../../gateway/routeRegistry";
import { registerRoutes } from "./routes";

export const projectsModule: ServerModule = { name: "projects", registerRoutes };
