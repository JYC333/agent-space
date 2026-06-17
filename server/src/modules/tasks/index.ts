import type { ServerModule } from "../../gateway/routeRegistry";
import { registerRoutes } from "./routes";

export const tasksModule: ServerModule = {
  name: "tasks",
  registerRoutes,
};

