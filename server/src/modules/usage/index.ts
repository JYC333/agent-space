import type { ServerModule } from "../../gateway/routeRegistry";
import { registerRoutes } from "./routes";

export const usageModule: ServerModule = {
  name: "usage",
  registerRoutes,
};

export { normalizeUsageObservation } from "./normalizer";
export {
  PgUsageRepository,
  usageRepositoryFromPool,
  type UsageQueryFilters,
} from "./repository";
export {
  UsageService,
  recordAttributedUsageObservation,
  recordUsageObservation,
  resolveUsageObservationAttribution,
  usageServiceFromConfig,
  type UsageIdentity,
  type UsageQueryInput,
} from "./service";
export type {
  NormalizedUsageObservation,
  UsageAttribution,
  UsageObservation,
} from "./types";
