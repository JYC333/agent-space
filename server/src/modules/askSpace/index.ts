import type { ServerModule } from "../../gateway/routeRegistry";
import { registerRoutes } from "./routes";

export const askSpaceModule: ServerModule = {
  name: "askSpace",
  registerRoutes,
};

export { AskSpaceService } from "./service";
