/**
 * Frontend-support read models.
 *
 * Aggregation/read surfaces used by the web app. Implemented natively in the
 * server against the server-owned Postgres schema.
 */

import type { ServerModule } from "../../gateway/routeRegistry";
import { registerRoutes } from "./routes";

export const frontendSupportModule: ServerModule = {
  name: "frontend_support",
  registerRoutes,
};
