/**
 * Frontend-support read-model facades.
 *
 * Stage 2 makes these aggregation/read surfaces explicit TS-owned edge routes
 * while Python remains the read-model authority behind the port.
 */

import type { ControlPlaneModule } from "../../gateway/routeRegistry";
import { registerRoutes } from "./routes";

export const frontendSupportModule: ControlPlaneModule = {
  name: "frontend_support",
  registerRoutes,
};
