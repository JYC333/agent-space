/**
 * Provider routes.
 *
 * - GET /api/v1/providers
 * - GET /api/v1/providers/catalog
 * - GET /api/v1/providers/litellm-providers
 * - GET /api/v1/providers/:configId
 *
 * Provider reads and commands are TS-owned. List/detail read from the provider
 * DB port behind native TS identity; catalog routes come from the protocol
 * package or built-in TS constants.
 *
 * The two static sub-routes must be claimed explicitly: once this module owns
 * `GET /api/v1/providers/:configId`, the parametric route would otherwise
   * swallow `/catalog` and `/litellm-providers` (parametric beats the fallback
 * proxy wildcard) and mis-validate their non-DTO payloads as provider configs.
 *
 * Provider commands and credential-channel routes are registered by
 * `providerCommandRoutes`.
 */

import type { FastifyInstance } from "fastify";
import type { ModuleContext } from "../../gateway/routeRegistry";
import {
  getProviderCatalogInfo,
  getProviderConfig,
  listLitellmProviders,
  listProviderConfigs,
} from "./service";
import { registerProviderCommandRoutes } from "./providerCommandRoutes";

export function registerRoutes(app: FastifyInstance, context: ModuleContext): void {
  registerProviderCommandRoutes(app, context.config);
  app.get("/api/v1/providers", async (request, reply) =>
    listProviderConfigs(context.config, request, reply),
  );
  app.get("/api/v1/providers/catalog", async (request, reply) =>
    getProviderCatalogInfo(context.config, request, reply),
  );
  app.get("/api/v1/providers/litellm-providers", async (request, reply) =>
    listLitellmProviders(context.config, request, reply),
  );
  app.get("/api/v1/providers/:configId", async (request, reply) =>
    getProviderConfig(context.config, request, reply),
  );
}
