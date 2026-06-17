import type { ServerModule } from "../../gateway/routeRegistry";
import { registerRoutes } from "./routes";

export const sourcePointersModule: ServerModule = {
  name: "source_pointers",
  registerRoutes,
};
