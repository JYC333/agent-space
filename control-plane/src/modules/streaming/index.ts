/**
 * Streaming edge module.
 *
 * The control plane owns the SSE transport. Python remains the authority for
 * run-event records and access control.
 */

import type { ControlPlaneModule } from "../../gateway/routeRegistry";
import { registerRoutes } from "./routes";

export const streamingModule: ControlPlaneModule = {
  name: "streaming",
  registerRoutes,
};

export { RUN_EVENT_APPENDED_TYPE } from "./service";
