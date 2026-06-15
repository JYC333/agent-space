/**
 * Identity introspection contract for TS control-plane modules.
 *
 * Mirrors Python `GET /api/v1/auth/introspect`, which exposes the
 * `get_identity` resolution as a port. Python remains the sole
 * authentication/membership authority; TS consumers call this endpoint with
 * the original caller's credentials forwarded and never validate credentials
 * themselves. The response carries identifiers only — never token, session,
 * or key material.
 */

import { z } from "zod";
import { IdSchema, SecretResponseGuards } from "./common.js";

export const IdentityIntrospectionResponseSchema = z
  .object({
    space_id: IdSchema,
    user_id: IdSchema,
    // Session/token material must never ride along on this port.
    session_id: z.never().optional(),
    token: z.never().optional(),
    ...SecretResponseGuards,
  })
  .passthrough();
export type IdentityIntrospectionResponse = z.infer<
  typeof IdentityIntrospectionResponseSchema
>;
