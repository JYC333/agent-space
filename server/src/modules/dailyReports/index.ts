import type { ServerModule } from "../../gateway/routeRegistry";
import { registerRoutes } from "./routes";

export const dailyReportsModule: ServerModule = {
  name: "dailyReports",
  registerRoutes,
};
