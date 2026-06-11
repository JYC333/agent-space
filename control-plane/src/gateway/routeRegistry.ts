/**
 * Route registry — the composition pattern for control-plane routes (the
 * permanent "gateway" entry layer).
 *
 * TS-owned backend modules live under `../modules/<module_name>/` and each
 * exposes a {@link ControlPlaneModule}: a name plus a
 * `registerRoutes(app, context)` function. The registry mounts every TS-owned
 * module FIRST, then the temporary legacy Python proxy catch-all LAST. Anything
 * the control plane does not explicitly own falls through to Python — the
 * default stays "proxy to the legacy authority".
 *
 * New TS features must be added as explicit modules in {@link TS_OWNED_MODULES},
 * never by widening the proxy. Python remains the business authority for all
 * existing routes and writes.
 */

import type { FastifyInstance } from "fastify";
import { createConfigSnapshot, type ConfigSnapshot, type ControlPlaneConfig } from "../config";
import { systemModule } from "../modules/system";
import { catalogModule } from "../modules/catalog";
import { registerLegacyPythonProxy } from "../legacy/pythonProxy";
import { registerErrorEnvelopeHandler } from "./errorEnvelope";
import { REQUEST_ID_HEADER, resolveRequestId } from "./requestContext";

/** Dependencies handed to every TS-owned module at registration time. */
export interface ModuleContext {
  config: ControlPlaneConfig;
  /** Immutable, hash-identified view of the same validated config. */
  snapshot: ConfigSnapshot;
}

/** Contract every TS-owned control-plane module implements. */
export interface ControlPlaneModule {
  /** Stable module id (matches its `src/modules/<name>/` directory). */
  name: string;
  registerRoutes(app: FastifyInstance, context: ModuleContext): void;
}

/**
 * All TS-owned modules, in registration order. The legacy Python proxy is NOT a
 * module — it is temporary bridge code registered separately, always last.
 */
export const TS_OWNED_MODULES: readonly ControlPlaneModule[] = [
  systemModule,
  catalogModule,
];

export function registerControlPlaneRoutes(
  app: FastifyInstance,
  config: ControlPlaneConfig,
): void {
  const context: ModuleContext = { config, snapshot: createConfigSnapshot(config) };

  // Cross-cutting gateway conventions: the error envelope for TS-owned route
  // errors, and request-id continuity on every response (the proxy re-stamps
  // the same value on proxied responses).
  registerErrorEnvelopeHandler(app);
  app.addHook("onRequest", async (request, reply) => {
    reply.header(REQUEST_ID_HEADER, resolveRequestId(request));
  });

  // 1. TS-owned control-plane modules (permanent).
  for (const module of TS_OWNED_MODULES) {
    module.registerRoutes(app, context);
  }

  // 2. Temporary legacy Python proxy — catch-all fallback for everything else
  //    under /api/v1/*. Must stay last. This module is conceptually temporary
  //    and may be removed once its endpoints are owned by control-plane modules
  //    or retired.
  registerLegacyPythonProxy(app, config);
}
