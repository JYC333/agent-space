import { describe, expect, it } from "vitest";
import {
  RunPythonContextPortManifestResponseSchema,
  RunPythonContextPortRequestSchema,
  RunPythonContextPortResponseSchema,
} from "../src/index";

describe("run context port contracts", () => {
  it("describes Python-owned ports with owner, auth, and error taxonomy", () => {
    const manifest = RunPythonContextPortManifestResponseSchema.parse({
      service: "python_runs_context_ports",
      generated_at: "2026-06-12T10:00:00.000Z",
      ports: [
        {
          operation: "policy.enforce",
          owner: "policy",
          implemented: false,
          auth: "internal_service_token",
          error_codes: ["policy_denied", "policy_requires_approval"],
          writes: ["policy_decision_records"],
        },
        {
          operation: "finalization.finalize",
          owner: "runs_finalization",
          implemented: true,
          auth: "internal_service_token",
          error_codes: ["run_not_found", "run_not_terminal", "finalization_failed"],
          writes: ["run_finalizations", "run_evaluations", "run_events"],
        },
      ],
    });

    expect(manifest.ports.map((port) => port.operation)).toEqual([
      "policy.enforce",
      "finalization.finalize",
    ]);
    expect(
      RunPythonContextPortManifestResponseSchema.safeParse({
        ...manifest,
        secret_ref: "model_provider_api_key:v1:secret",
      }).success,
    ).toBe(false);
  });

  it("parses service-to-service operation requests and rejects nested secrets", () => {
    const request = RunPythonContextPortRequestSchema.parse({
      operation: "artifact.persist",
      run_id: "run-1",
      space_id: "space-1",
      payload_json: {
        artifact_type: "runtime_output",
        title: "Output",
      },
    });

    expect(request.payload_json).toEqual({
      artifact_type: "runtime_output",
      title: "Output",
    });
    expect(
      RunPythonContextPortRequestSchema.safeParse({
        operation: "artifact.persist",
        payload_json: { nested: { api_key: "sk-secret" } },
      }).success,
    ).toBe(false);
  });

  it("parses operation responses and enforces trace-safe result payloads", () => {
    const response = RunPythonContextPortResponseSchema.parse({
      operation: "finalization.finalize",
      owner: "runs_finalization",
      status: "succeeded",
      result_json: {
        run_finalization_id: "finalization-1",
        outcome_status: "passed",
      },
    });

    expect(response.status).toBe("succeeded");
    expect(
      RunPythonContextPortResponseSchema.safeParse({
        ...response,
        result_json: { full_patch: "diff --git ..." },
      }).success,
    ).toBe(false);
  });
});
