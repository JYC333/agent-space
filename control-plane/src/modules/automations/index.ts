import type { ControlPlaneModule } from "../../gateway/routeRegistry";
import { registerRoutes } from "./routes";

export const automationsModule: ControlPlaneModule = {
  name: "automations",
  registerRoutes,
};
