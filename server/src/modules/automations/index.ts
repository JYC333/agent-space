import type { ServerModule } from "../../gateway/routeRegistry";
import { registerRoutes } from "./routes";

export const automationsModule: ServerModule = {
  name: "automations",
  registerRoutes,
};
