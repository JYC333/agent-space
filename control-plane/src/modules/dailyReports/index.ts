import type { ControlPlaneModule } from "../../gateway/routeRegistry";
import { registerRoutes } from "./routes";

export const dailyReportsModule: ControlPlaneModule = {
  name: "dailyReports",
  registerRoutes,
};
