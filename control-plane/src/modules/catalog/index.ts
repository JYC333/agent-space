/**
 * Catalog module — read-only surface over the built-in `catalog/` definitions,
 * packaged in the standard TS-owned module shape (`ControlPlaneModule`).
 *
 * First TS-owned read surface beyond the system descriptors (migration roadmap
 * Stage 1). Python remains the business authority for the DB-backed capability
 * registry and Template Library.
 */

import type { ControlPlaneModule } from "../../gateway/routeRegistry";
import { registerRoutes } from "./routes";

export const catalogModule: ControlPlaneModule = {
  name: "catalog",
  registerRoutes,
};

export {
  catalogSummary,
  listAgentTemplates,
  listCapabilities,
  type CatalogAgentTemplateSummary,
  type CatalogCapabilitySummary,
  type CatalogListBody,
  type CatalogSummaryBody,
} from "./service";
