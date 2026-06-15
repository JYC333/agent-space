/**
 * Outbound notification/webhook egress module.
 *
 * New Stage 2 capability built TS-first. It is policy-gated by control-plane
 * config and disabled unless an explicit webhook allowlist is configured.
 */

import type { ControlPlaneModule } from "../../gateway/routeRegistry";
import { registerRoutes } from "./routes";

export const notificationsModule: ControlPlaneModule = {
  name: "notifications",
  registerRoutes,
};

export {
  evaluateWebhookPolicy,
  normalizeNotificationWebhookUrl,
  type NotificationWebhookPolicy,
} from "./service";
