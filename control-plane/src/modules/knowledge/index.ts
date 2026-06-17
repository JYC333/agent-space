import type { ControlPlaneModule } from "../../gateway/routeRegistry";
import { registerRoutes } from "./routes";

export const knowledgeModule: ControlPlaneModule = {
  name: "knowledge",
  registerRoutes,
};

