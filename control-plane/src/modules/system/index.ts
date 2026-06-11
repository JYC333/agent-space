/**
 * System module — the control plane's own health/features descriptors,
 * packaged in the standard TS-owned module shape (`ControlPlaneModule`).
 */

import type { ControlPlaneModule } from "../../gateway/routeRegistry";
import { registerRoutes } from "./routes";

export const systemModule: ControlPlaneModule = {
  name: "system",
  registerRoutes,
};

export {
  CONTROL_PLANE_SERVICE_NAME,
  computeFeatures,
  isProtocolPackageDetected,
  type FeaturesBody,
  type HealthBody,
} from "./service";
