/**
 * System module service — the control plane's self-descriptors.
 *
 * Pure functions only: liveness body and the feature advertisement. Implemented
 * entirely in the control plane (no proxy to Python); they report only the
 * control plane's own state and never check or speak for the Python backend.
 */

import { createRequire } from "node:module";
import { join } from "node:path";
import type { ControlPlaneConfig } from "../../config";

export const CONTROL_PLANE_SERVICE_NAME = "control-plane";

const PROTOCOL_PACKAGE = "@agent-space/protocol";

export interface HealthBody {
  status: "ok";
  service: string;
}

export function healthBody(): HealthBody {
  return { status: "ok", service: CONTROL_PLANE_SERVICE_NAME };
}

/**
 * Detect whether the shared protocol package is resolvable, *without executing*
 * it (the package is ESM/TS source; we only resolve its location). Safe in both
 * dev (vitest) and the compiled CJS runtime — the anchor falls back to the
 * working directory when `__filename` is not defined.
 */
export function isProtocolPackageDetected(): boolean {
  try {
    const anchor =
      typeof __filename !== "undefined"
        ? __filename
        : join(process.cwd(), "package.json");
    createRequire(anchor).resolve(PROTOCOL_PACKAGE);
    return true;
  } catch {
    return false;
  }
}

export interface FeaturesBody {
  service: string;
  features: string[];
}

export function computeFeatures(config: ControlPlaneConfig): string[] {
  const features = [
    "control_plane_health",
    "catalog_read",
    "run_event_sse_stream",
    "frontend_support_read_model_facades",
    "runtime_tools_controlled_installer",
    "config_semantic_validation",
    "notification_webhook_egress_policy_gate",
  ];
  features.push(
    config.providersAuthority === "ts"
      ? "providers_read_ts_authority"
      : "providers_readonly_python_facade",
  );
  features.push(
    config.providersCredentialsAuthority === "ts"
      ? "providers_credentials_ts_authority"
      : "providers_credentials_python_authority",
  );
  features.push(
    config.runsAuthority === "ts"
      ? "runs_commands_ts_authority"
      : "runs_commands_python_authority",
  );
  features.push(
    config.policyAuthority === "ts"
      ? "policy_enforcement_ts_authority"
      : "policy_enforcement_python_authority",
  );
  features.push(
    config.proposalsAuthority === "ts"
      ? "proposals_review_ts_authority"
      : "proposals_review_python_authority",
  );
  features.push(
    config.sessionsAuthority === "ts"
      ? "sessions_ts_authority"
      : "sessions_python_authority",
  );
  features.push(
    config.chatTurnAuthority === "ts"
      ? "chat_turn_ts_authority"
      : "chat_turn_python_authority",
  );
  features.push(
    config.contextAuthority === "ts"
      ? "context_assembly_ts_authority"
      : "context_assembly_python_authority",
  );
  features.push(
    config.memoryAuthority === "ts"
      ? "memory_ts_authority"
      : "memory_python_authority",
  );
  if (config.providersCredentialsAuthority === "ts") {
    features.push("ts_agent_runtime_host");
  }
  if (config.providersShadowCompare) features.push("providers_read_shadow_compare");
  if (config.enablePythonFallbackProxy) features.push("python_fallback_proxy");
  if (config.enableNotificationWebhookEgress) {
    features.push("notification_webhook_egress");
  }
  if (isProtocolPackageDetected()) features.push("protocol_package_detected");
  return features;
}

export function featuresBody(config: ControlPlaneConfig): FeaturesBody {
  return { service: CONTROL_PLANE_SERVICE_NAME, features: computeFeatures(config) };
}
