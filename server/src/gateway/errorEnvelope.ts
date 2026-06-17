/**
 * Error envelope convention for server-owned routes.
 *
 * Every error a server-owned route returns uses one JSON shape:
 *
 *     { "error": "<machine_code>", "message": "<human text>", "request_id": "..." }
 *
 * Errors returned to clients must never leak upstream internals, stack traces,
 * headers, tokens, cookies, or request/response bodies. Server errors (5xx) get
 * a fixed generic message; client errors (4xx) keep their intentional,
 * client-safe message.
 *
 * Unknown API routes are handled separately by the gateway catch-all.
 */

import type { FastifyInstance, FastifyReply, FastifyRequest } from "fastify";
import { resolveRequestId } from "./requestContext";

export interface ErrorEnvelope {
  error: string;
  message: string;
  request_id?: string;
}

/** Build the standard envelope for a server-owned route error. */
export function errorEnvelope(
  error: string,
  message: string,
  requestId?: string,
): ErrorEnvelope {
  const body: ErrorEnvelope = { error, message };
  if (requestId !== undefined) body.request_id = requestId;
  return body;
}

/** Send an envelope from a server-owned route handler. */
export function sendErrorEnvelope(
  reply: FastifyReply,
  statusCode: number,
  body: ErrorEnvelope,
): FastifyReply {
  return reply.code(statusCode).send(body);
}

const INTERNAL_ERROR: Pick<ErrorEnvelope, "error" | "message"> = {
  error: "internal_error",
  message: "Internal server error",
};

/**
 * Install the app-wide error handler that converts uncaught server-owned route
 * errors into the envelope.
 */
export function registerErrorEnvelopeHandler(app: FastifyInstance): void {
  app.setErrorHandler((err, request: FastifyRequest, reply: FastifyReply) => {
    const known = err as { statusCode?: unknown; name?: unknown; message?: unknown };
    const statusCode =
      typeof known.statusCode === "number" &&
      known.statusCode >= 400 &&
      known.statusCode < 600
        ? known.statusCode
        : 500;
    // Never echo internal error text (or anything a handler embedded in it) for
    // server errors; 4xx messages are intentional, client-safe text.
    const safe =
      statusCode >= 500
        ? INTERNAL_ERROR
        : {
            error: "request_error",
            message: typeof known.message === "string" ? known.message : "Bad request",
          };
    // Log only a secret-free classification — no headers, no bodies, no stack
    // in the response (the stack stays server-side at debug level).
    request.log.error(
      {
        reason: typeof known.name === "string" ? known.name : "Error",
        statusCode,
      },
      "server-owned route error",
    );
    request.log.debug({ err }, "server-owned route error detail");
    return sendErrorEnvelope(
      reply,
      statusCode,
      errorEnvelope(safe.error, safe.message, resolveRequestId(request)),
    );
  });
}
