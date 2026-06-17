import type { ControlPlaneModule } from "../../gateway/routeRegistry";
import { registerRoutes } from "./routes";

export const tasksModule: ControlPlaneModule = {
  name: "tasks",
  registerRoutes,
};

