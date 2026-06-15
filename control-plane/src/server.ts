/**
 * Composition root: builds the Fastify instance for the control plane.
 *
 * No business route logic lives here. Logger hygiene comes from
 * `gateway/logging`, and all route registration — TS-owned modules first, the
 * temporary Python fallback proxy last — is owned by `gateway/routeRegistry`.
 */

import Fastify, {
  type FastifyBaseLogger,
  type FastifyInstance,
  type FastifyServerOptions,
} from "fastify";
import type { ControlPlaneConfig } from "./config";
import { registerControlPlaneRoutes } from "./gateway/routeRegistry";
import { buildLoggerOptions } from "./gateway/logging";
import { REQUEST_ID_HEADER } from "./gateway/requestContext";

const PYTHON_FALLBACK_PROXY_BODY_LIMIT_BYTES = 32 * 1024 * 1024;

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
}

export function buildServer(
  config: ControlPlaneConfig,
  options: BuildServerOptions = {},
): FastifyInstance {
  const base: FastifyServerOptions = {
    disableRequestLogging: false,
    // The Python activity upload endpoint accepts 25 MiB files. The proxy keeps
    // a small transport margin for multipart framing while Python remains the
    // business authority for accepted file types and exact upload limits.
    bodyLimit: PYTHON_FALLBACK_PROXY_BODY_LIMIT_BYTES,
    // The control plane sits behind the frontend proxy / browser; trust forwarded
    // info only for request-id continuity, not for auth decisions (Python owns
    // those).
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

  // Treat every request body as an opaque buffer so the fallback proxy can forward
  // it verbatim (any content-type). TS-owned POST routes parse only the bodies
  // they explicitly own.
  app.removeAllContentTypeParsers();
  app.addContentTypeParser("*", { parseAs: "buffer" }, (_req, body, done) => {
    done(null, body);
  });

  registerControlPlaneRoutes(app, config);

  return app;
}
