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
  const features = ["control_plane_health", "catalog_read"];
  if (config.enableLegacyProxy) features.push("legacy_python_proxy");
  if (isProtocolPackageDetected()) features.push("protocol_package_detected");
  return features;
}

export function featuresBody(config: ControlPlaneConfig): FeaturesBody {
  return { service: CONTROL_PLANE_SERVICE_NAME, features: computeFeatures(config) };
}
