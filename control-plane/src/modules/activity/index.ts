import type { ControlPlaneModule } from "../../gateway/routeRegistry";
import { registerRoutes } from "./routes";

export const activityModule: ControlPlaneModule = {
  name: "activity",
  registerRoutes,
};

