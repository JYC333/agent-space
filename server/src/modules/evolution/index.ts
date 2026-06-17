import type { ServerModule } from "../../gateway/routeRegistry";
import { registerRoutes } from "./routes";

export const evolutionModule: ServerModule = { name: "evolution", registerRoutes };
