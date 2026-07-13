import type { ServerModule } from "../../gateway/routeRegistry";
import { registerRoutes } from "./routes";

export const routingModule: ServerModule = { name: "routing", registerRoutes };

export { DeterministicRouteSelector, EMPTY_ROUTE_HINTS, mergeRouteHints } from "./router";
export { PgRouteDecisionRepository, RouteSelectionError, routeHintsForRun } from "./repository";
export type * from "./types";
