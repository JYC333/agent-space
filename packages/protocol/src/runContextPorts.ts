/**
 * Python-owned context ports used by TS run orchestration.
 *
 * These contracts describe explicit service-to-service calls from the
 * control-plane runs module to Python-owned contexts that Stage 4 must not
 * own directly. Schemas only; no transport or authority lives here.
 */

import { z } from "zod";
import {
  IdSchema,
  ISODateTimeSchema,
  SecretResponseGuards,
} from "./common.js";
import {
  SecretFreeJsonSchema,
  TraceSafeJsonSchema,
} from "./runOrchestration.js";

export const RunPythonContextPortOperationSchema = z.enum([
  "policy.enforce",
  "context.prepare",
  "artifact.persist",
  "proposal.create",
  "workspace.prepare",
  "workspace.cleanup",
  "finalization.finalize",
]);
export type RunPythonContextPortOperation = z.infer<
  typeof RunPythonContextPortOperationSchema
>;

export const RunPythonContextPortOwnerSchema = z.enum([
  "policy",
  "memory_context",
  "artifacts",
  "proposals",
  "workspace_sandbox",
  "runs_finalization",
]);
export type RunPythonContextPortOwner = z.infer<
  typeof RunPythonContextPortOwnerSchema
>;

export const RunPythonContextPortErrorCodeSchema = z.enum([
  "unauthorized_internal_port",
  "run_context_port_not_implemented",
  "python_context_port_unavailable",
  "python_context_port_invalid_response",
  "policy_denied",
  "policy_requires_approval",
  "policy_audit_persist_failed",
  "runtime_resolution_failed",
  "context_prepare_failed",
  "artifact_persist_failed",
  "proposal_create_failed",
  "workspace_prepare_failed",
  "workspace_cleanup_failed",
  "run_not_found",
  "run_not_terminal",
  "finalization_failed",
]);
export type RunPythonContextPortErrorCode = z.infer<
  typeof RunPythonContextPortErrorCodeSchema
>;

export const RunPythonContextPortDescriptorSchema = z
  .object({
    operation: RunPythonContextPortOperationSchema,
    owner: RunPythonContextPortOwnerSchema,
    implemented: z.boolean(),
    auth: z.literal("internal_service_token"),
    error_codes: z.array(RunPythonContextPortErrorCodeSchema),
    writes: z.array(z.string()).default([]),
    notes: z.string().nullish(),
    ...SecretResponseGuards,
  })
  .passthrough();
export type RunPythonContextPortDescriptor = z.infer<
  typeof RunPythonContextPortDescriptorSchema
>;

export const RunPythonContextPortManifestResponseSchema = z
  .object({
    service: z.literal("python_runs_context_ports"),
    ports: z.array(RunPythonContextPortDescriptorSchema),
    generated_at: ISODateTimeSchema,
    ...SecretResponseGuards,
  })
  .passthrough();
export type RunPythonContextPortManifestResponse = z.infer<
  typeof RunPythonContextPortManifestResponseSchema
>;

export const RunPythonContextPortRequestSchema = z.object({
  operation: RunPythonContextPortOperationSchema,
  run_id: IdSchema.nullish(),
  space_id: IdSchema.nullish(),
  payload_json: SecretFreeJsonSchema.default({}),
});
export type RunPythonContextPortRequest = z.infer<
  typeof RunPythonContextPortRequestSchema
>;

export const RunPythonContextPortResponseSchema = z
  .object({
    operation: RunPythonContextPortOperationSchema,
    owner: RunPythonContextPortOwnerSchema,
    status: z.enum(["succeeded", "failed", "not_implemented"]),
    error_code: RunPythonContextPortErrorCodeSchema.nullish(),
    message: z.string().nullish(),
    result_json: TraceSafeJsonSchema.default({}),
    ...SecretResponseGuards,
  })
  .passthrough();
export type RunPythonContextPortResponse = z.infer<
  typeof RunPythonContextPortResponseSchema
>;
