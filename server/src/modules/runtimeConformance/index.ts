import type { ServerModule } from "../../gateway/routeRegistry";
import { registerRoutes } from "./routes";

export const runtimeConformanceModule: ServerModule = {
  name: "runtimeConformance",
  registerRoutes,
};

export {
  CONFORMANCE_CHECKS,
  CONFORMANCE_SUITE_VERSION,
  RuntimeConformanceService,
  type ConformanceCheck,
  type ConformanceCheckObservation,
  type ConformanceProbeContext,
  type ConformanceProbeRunner,
  type ConformanceResult,
} from "./service";
export {
  LocalCliConformanceProbeRunner,
  type LocalCliConformanceProbeRunnerDeps,
} from "./probeRunner";
