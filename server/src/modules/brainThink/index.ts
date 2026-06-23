import type { ServerModule } from "../../gateway/routeRegistry";
import { registerRoutes } from "./routes";

export const brainThinkModule: ServerModule = {
  name: "brainThink",
  registerRoutes,
};

export { BrainThinkService } from "./service";
