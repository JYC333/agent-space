import type { ControlPlaneModule } from "../../gateway/routeRegistry";
import { registerRoutes } from "./routes";

export const intakeModule: ControlPlaneModule = {
  name: "intake",
  registerRoutes,
};

