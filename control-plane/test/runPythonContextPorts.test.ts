import { describe, expect, it } from "vitest";
import { loadConfig } from "../src/config";
import {
  RunPythonContextPortClient,
  RunPythonContextPortError,
  type RunPythonContextPortHttpResponse,
  type RunPythonContextPortTransport,
} from "../src/modules/runs/pythonContextPorts";
import { INTERNAL_TOKEN_HEADER } from "../src/gateway/internalAuth";

interface CapturedCall {
  method: "GET" | "POST";
  url: string;
  headers: Record<string, string>;
  body?: unknown;
}

class FakeTransport implements RunPythonContextPortTransport {
  calls: CapturedCall[] = [];
  nextPost: RunPythonContextPortHttpResponse = {
    statusCode: 200,
    body: {
      operation: "finalization.finalize",
      owner: "runs_finalization",
      status: "succeeded",
      result_json: { run_finalization_id: "finalization-1" },
    },
  };

  async getJson(
    url: string,
    headers: Record<string, string>,
  ): Promise<RunPythonContextPortHttpResponse> {
    this.calls.push({ method: "GET", url, headers });
    return {
      statusCode: 200,
      body: {
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
            operation: "context.prepare",
            owner: "memory_context",
            implemented: false,
            auth: "internal_service_token",
            error_codes: ["run_context_port_not_implemented"],
            writes: [],
          },
          {
            operation: "artifact.persist",
            owner: "artifacts",
            implemented: false,
            auth: "internal_service_token",
            error_codes: ["artifact_persist_failed"],
            writes: ["artifacts"],
          },
          {
            operation: "proposal.create",
            owner: "proposals",
            implemented: false,
            auth: "internal_service_token",
            error_codes: ["proposal_create_failed"],
            writes: ["proposals"],
          },
          {
            operation: "workspace.prepare",
            owner: "workspace_sandbox",
            implemented: true,
            auth: "internal_service_token",
            error_codes: ["workspace_prepare_failed"],
            writes: ["runs.sandbox_path"],
          },
          {
            operation: "workspace.cleanup",
            owner: "workspace_sandbox",
            implemented: true,
            auth: "internal_service_token",
            error_codes: ["workspace_cleanup_failed"],
            writes: ["runs.sandbox_path"],
          },
          {
            operation: "finalization.finalize",
            owner: "runs_finalization",
            implemented: true,
            auth: "internal_service_token",
            error_codes: ["run_not_found", "run_not_terminal", "finalization_failed"],
            writes: ["run_evaluations", "run_finalizations", "run_events"],
          },
        ],
      },
    };
  }

  async postJson(
    url: string,
    headers: Record<string, string>,
    body: unknown,
  ): Promise<RunPythonContextPortHttpResponse> {
    this.calls.push({ method: "POST", url, headers, body });
    return this.nextPost;
  }
}

function config(token = "internal-token") {
  return loadConfig({
    CONTROL_PLANE_PYTHON_API_BASE_URL: "http://python.test",
    CONTROL_PLANE_INTERNAL_TOKEN: token,
  });
}

describe("run Python context port client", () => {
  it("fetches the manifest and sends the internal service token", async () => {
    const transport = new FakeTransport();
    const client = new RunPythonContextPortClient(config(), transport);

    const manifest = await client.getManifest();

    expect(manifest.ports.map((port) => port.operation)).toEqual([
      "policy.enforce",
      "context.prepare",
      "artifact.persist",
      "proposal.create",
      "workspace.prepare",
      "workspace.cleanup",
      "finalization.finalize",
    ]);
    expect(transport.calls[0]).toMatchObject({
      method: "GET",
      url: "http://python.test/api/v1/internal/runs-context/ports",
    });
    expect(transport.calls[0].headers[INTERNAL_TOKEN_HEADER]).toBe("internal-token");
  });

  it("calls the finalization port with a typed request", async () => {
    const transport = new FakeTransport();
    const client = new RunPythonContextPortClient(config(), transport);

    const result = await client.finalizeRun("run-1", "space-1");

    expect(result.result_json).toEqual({ run_finalization_id: "finalization-1" });
    expect(transport.calls[0]).toMatchObject({
      method: "POST",
      url: "http://python.test/api/v1/internal/runs-context/operations",
      body: {
        operation: "finalization.finalize",
        run_id: "run-1",
        space_id: "space-1",
        payload_json: {},
      },
    });
  });

  it("maps declared fail-closed ports to stable error codes", async () => {
    const transport = new FakeTransport();
    transport.nextPost = {
      statusCode: 501,
      body: {
        detail: {
          error: "run_context_port_not_implemented",
          operation: "policy.enforce",
          owner: "policy",
          message: "not wired",
        },
      },
    };
    const client = new RunPythonContextPortClient(config(), transport);

    await expect(
      client.callDeclaredFailClosedPort("policy.enforce", {
        run_id: "run-1",
        space_id: "space-1",
        payload_json: { action: "runtime.execute" },
      }),
    ).rejects.toMatchObject({
      code: "run_context_port_not_implemented",
      statusCode: 501,
    });
  });

  it("rejects invalid or secret-bearing responses from Python", async () => {
    const transport = new FakeTransport();
    transport.nextPost = {
      statusCode: 200,
      body: {
        operation: "finalization.finalize",
        owner: "runs_finalization",
        status: "succeeded",
        result_json: { api_key: "sk-secret" },
      },
    };
    const client = new RunPythonContextPortClient(config(), transport);

    await expect(client.finalizeRun("run-1", "space-1")).rejects.toMatchObject({
      code: "python_context_port_invalid_response",
    });
  });

  it("requires an internal token before calling Python", async () => {
    const client = new RunPythonContextPortClient(config(""));

    await expect(client.getManifest()).rejects.toBeInstanceOf(
      RunPythonContextPortError,
    );
    await expect(client.getManifest()).rejects.toMatchObject({
      code: "unauthorized_internal_port",
    });
  });
});
