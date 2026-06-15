/**
 * Runtime host module.
 *
 * Internal route only: Python-owned `runs` invokes this module through the
 * runtime-adapter seam. The module executes a provider-backed TS host turn and
 * returns a normalized adapter result; it does not own run lifecycle state.
 */

import type { ControlPlaneModule } from "../../gateway/routeRegistry";
import { registerRoutes } from "./routes";

export const runtimeHostModule: ControlPlaneModule = {
  name: "runtime_host",
  registerRoutes,
};

export { executeRuntimeHost } from "./service";
