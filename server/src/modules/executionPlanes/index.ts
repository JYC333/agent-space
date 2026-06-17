import type { ServerModule } from "../../gateway/routeRegistry";
import { registerRoutes } from "./routes";

export const executionPlanesModule: ServerModule = {
  name: "execution_planes",
  registerRoutes,
};
