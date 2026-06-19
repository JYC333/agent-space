/**
 * Composition root: builds the Fastify instance for the server.
 *
 * No business route logic lives here. Logger hygiene comes from
 * `gateway/logging`, and all route registration is owned by
 * `gateway/routeRegistry`.
 */

import Fastify, {
  type FastifyBaseLogger,
  type FastifyInstance,
  type FastifyServerOptions,
} from "fastify";
import type { ServerConfig } from "./config";
import { registerServerRoutes } from "./gateway/routeRegistry";
import { buildLoggerOptions } from "./gateway/logging";
import { REQUEST_ID_HEADER } from "./gateway/requestContext";
import type { PluginHost } from "./modules/plugins/host";

const SERVER_BODY_LIMIT_BYTES = 32 * 1024 * 1024;

export interface BuildServerOptions {
  /** Override/disable the built-in logger options (tests pass `false`). */
  logger?: FastifyServerOptions["logger"];
  /** Inject a custom logger instance (advanced; bypasses the built-in serializers). */
  loggerInstance?: FastifyBaseLogger;
  /**
   * Redirect the *built-in* logger to a custom destination, keeping the default
   * serializers + redaction. Tests use this to assert secrets never reach logs.
   */
  logStream?: NodeJS.WritableStream;
  /** Optional plugin host — activates built-in plugins after SERVER_MODULES. */
  pluginHost?: PluginHost;
}

export function buildServer(
  config: ServerConfig,
  options: BuildServerOptions = {},
): FastifyInstance {
  const base: FastifyServerOptions = {
    disableRequestLogging: false,
    bodyLimit: SERVER_BODY_LIMIT_BYTES,
    // The server sits behind the frontend proxy / browser; trust forwarded
    // info only for request-id continuity, not for auth decisions.
    requestIdHeader: REQUEST_ID_HEADER,
  };

  if (options.loggerInstance !== undefined) {
    base.loggerInstance = options.loggerInstance;
  } else if (options.logger !== undefined) {
    base.logger = options.logger;
  } else {
    base.logger = buildLoggerOptions(config, options.logStream);
  }

  const app = Fastify(base);

  // Treat every request body as an opaque buffer. Server-owned POST routes parse only
  // the bodies they explicitly own.
  app.removeAllContentTypeParsers();
  app.addContentTypeParser("*", { parseAs: "buffer" }, (_req, body, done) => {
    done(null, body);
  });

  registerServerRoutes(app, config, options.pluginHost);

  return app;
}
