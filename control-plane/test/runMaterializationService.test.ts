import { describe, expect, it } from "vitest";
import { RunMaterializationService } from "../src/modules/runs/materializationService";
import type { RunRecord } from "../src/modules/runs/repository";
import type {
  RunPythonContextPortRequest,
  RunPythonContextPortResponse,
} from "@agent-space/protocol" with { "resolution-mode": "import" };

function run(overrides: Partial<RunRecord> = {}): RunRecord {
  return {
    id: "run-1",
    space_id: "space-1",
    agent_id: "agent-1",
    agent_version_id: "agent-version-1",
    status: "running",
    mode: "live",
    prompt: "Say hello",
    instruction: null,
    workspace_id: "workspace-1",
    session_id: null,
    project_id: null,
    adapter_type: "model_api",
    model_provider_id: "provider-1",
    required_sandbox_level: "none",
    trigger_origin: "manual",
    started_at: null,
    ended_at: null,
    ...overrides,
  };
}

class FakePorts {
  calls: RunPythonContextPortRequest[] = [];
  finalizations: Array<{ runId: string; spaceId: string }> = [];

  async call(request: RunPythonContextPortRequest): Promise<RunPythonContextPortResponse> {
    this.calls.push(request);
    if (request.operation === "artifact.persist") {
      return {
        operation: request.operation,
        owner: "artifacts",
        status: "succeeded",
        result_json: { artifact_id: `artifact-${this.calls.length}` },
      };
    }
    return {
      operation: request.operation,
      owner: "proposals",
      status: "not_implemented",
      error_code: "run_context_port_not_implemented",
      message: "proposal port pending",
      result_json: {},
    };
  }

  async finalizeRun(runId: string, spaceId: string): Promise<RunPythonContextPortResponse> {
    this.finalizations.push({ runId, spaceId });
    return {
      operation: "finalization.finalize",
      owner: "runs_finalization",
      status: "succeeded",
      result_json: {
        run_finalization_id: "finalization-1",
        run_evaluation_id: "evaluation-1",
      },
    };
  }
}

describe("RunMaterializationService", () => {
  it("materializes runtime output, structured artifacts, proposals, and fail-closed activities through ports", async () => {
    const ports = new FakePorts();
    const service = new RunMaterializationService(ports);

    const result = await service.materializeAdapterResult({
      run: run(),
      adapterResult: {
        adapter_type: "model_api",
        adapter_kind: "managed_api",
        success: true,
        output_text: "hello token=secret",
        output_json: {
          artifacts: [{ title: "Report", body: "ok" }],
          proposed_changes: [
            {
              proposal_type: "code_patch",
              workspace_id: "workspace-1",
              patch: { operations: [{ op: "replace_file", path: "a.txt", content: "x" }] },
            },
          ],
          activities: [{ title: "activity" }],
        },
        exit_code: 0,
        error_code: null,
        error_message: null,
        started_at: "2026-06-12T10:00:00.000Z",
        completed_at: "2026-06-12T10:00:01.000Z",
        usage: null,
      },
    });

    expect(ports.calls.map((call) => call.operation)).toEqual([
      "artifact.persist",
      "artifact.persist",
      "proposal.create",
    ]);
    // Port payloads are transport, not evidence: the output text and proposal
    // specs must arrive intact (Python applies artifact redaction on its side).
    expect(ports.calls[0].payload_json).toMatchObject({
      artifact_type: "runtime_output",
      text: "hello token=secret",
      workspace_id: "workspace-1",
    });
    expect(ports.calls[2].payload_json).toMatchObject({
      spec: {
        proposal_type: "code_patch",
        patch: { operations: [{ op: "replace_file", path: "a.txt", content: "x" }] },
      },
    });
    expect(result.items).toMatchObject([
      { kind: "artifact", status: "succeeded", artifact_id: "artifact-1" },
      { kind: "artifact", status: "succeeded", artifact_id: "artifact-2" },
      {
        kind: "proposal",
        status: "skipped",
        error_code: "run_context_port_not_implemented",
      },
      {
        kind: "activity",
        status: "failed",
        error_code: "output_activity_materialization_error",
      },
    ]);
    expect(result.errors).toEqual([
      "proposal:run_context_port_not_implemented:proposal port pending",
      "activity:output_activity_materialization_error:Activity materialization remains Python-owned and has no Stage 4 port.",
    ]);
  });

  it("calls the finalization port and returns trace-safe summary metadata", async () => {
    const ports = new FakePorts();
    const service = new RunMaterializationService(ports);

    const result = await service.finalizeRun(run({ status: "succeeded" }));

    expect(ports.finalizations).toEqual([{ runId: "run-1", spaceId: "space-1" }]);
    expect(result).toMatchObject({
      kind: "activity",
      status: "succeeded",
      activity_id: "finalization-1",
      metadata_json: {
        run_finalization_id: "finalization-1",
        run_evaluation_id: "evaluation-1",
      },
    });
  });
});
