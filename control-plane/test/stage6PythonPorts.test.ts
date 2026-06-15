import { describe, expect, it } from "vitest";
import { loadConfig } from "../src/config";
import { INTERNAL_TOKEN_HEADER } from "../src/gateway/internalAuth";
import {
  Stage6PythonPortClient,
  Stage6PythonPortError,
  type Stage6PythonPortHttpResponse,
  type Stage6PythonPortTransport,
} from "../src/modules/memory/pythonStage6Ports";

interface CapturedCall {
  method: "GET" | "POST";
  url: string;
  headers: Record<string, string>;
  body?: unknown;
}

class FakeTransport implements Stage6PythonPortTransport {
  calls: CapturedCall[] = [];
  nextPost: Stage6PythonPortHttpResponse = {
    statusCode: 200,
    body: {
      operation: "session_summary.get_latest",
      owner: "sessions",
      status: "succeeded",
      result_json: {
        summary: {
          id: "summary-1",
          session_id: "session-1",
          version: 1,
          summary_text: "Session summary.",
          condenser_version: "pattern.v1",
        },
      },
    },
  };

  async getJson(
    url: string,
    headers: Record<string, string>,
  ): Promise<Stage6PythonPortHttpResponse> {
    this.calls.push({ method: "GET", url, headers });
    return {
      statusCode: 200,
      body: {
        service: "python_stage6_context_ports",
        generated_at: "2026-06-14T10:00:00.000Z",
        ports: [
          {
            operation: "session_summary.get_latest",
            owner: "sessions",
            implemented: true,
            auth: "internal_service_token",
            error_codes: ["session_summary_not_found", "stage6_port_invalid_request"],
            writes: [],
          },
          {
            operation: "context.build",
            owner: "memory_context",
            implemented: false,
            auth: "internal_service_token",
            error_codes: ["stage6_port_not_implemented", "context_build_failed"],
            writes: ["context_snapshots", "memory_access_logs"],
          },
          {
            operation: "memory.read",
            owner: "memory",
            implemented: false,
            auth: "internal_service_token",
            error_codes: ["stage6_port_not_implemented", "memory_read_failed"],
            writes: [],
          },
          {
            operation: "memory.proposal_create",
            owner: "memory",
            implemented: false,
            auth: "internal_service_token",
            error_codes: [
              "stage6_port_not_implemented",
              "memory_proposal_create_failed",
            ],
            writes: ["proposals"],
          },
        ],
      },
    };
  }

  async postJson(
    url: string,
    headers: Record<string, string>,
    body: unknown,
  ): Promise<Stage6PythonPortHttpResponse> {
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

describe("Stage 6 Python context port client", () => {
  it("fetches the manifest and sends the internal service token", async () => {
    const transport = new FakeTransport();
    const client = new Stage6PythonPortClient(config(), transport);

    const manifest = await client.getManifest();

    expect(manifest.ports.map((port) => port.operation)).toEqual([
      "session_summary.get_latest",
      "context.build",
      "memory.read",
      "memory.proposal_create",
    ]);
    expect(transport.calls[0]).toMatchObject({
      method: "GET",
      url: "http://python.test/api/v1/internal/stage6-context/ports",
    });
    expect(transport.calls[0].headers[INTERNAL_TOKEN_HEADER]).toBe("internal-token");
  });

  it("calls implemented Stage 6 operations with a typed envelope", async () => {
    const transport = new FakeTransport();
    const client = new Stage6PythonPortClient(config(), transport);

    const result = await client.call({
      operation: "session_summary.get_latest",
      space_id: "space-1",
      user_id: "user-1",
      payload_json: { session_id: "session-1" },
    });

    expect(result.result_json).toMatchObject({
      summary: { id: "summary-1", session_id: "session-1" },
    });
    expect(transport.calls[0]).toMatchObject({
      method: "POST",
      url: "http://python.test/api/v1/internal/stage6-context/operations",
      body: {
        operation: "session_summary.get_latest",
        space_id: "space-1",
        user_id: "user-1",
        payload_json: { session_id: "session-1" },
      },
    });
  });

  it("preserves declared fail-closed operation responses", async () => {
    const transport = new FakeTransport();
    transport.nextPost = {
      statusCode: 200,
      body: {
        operation: "context.build",
        owner: "memory_context",
        status: "not_implemented",
        error_code: "stage6_port_not_implemented",
        message: "declared but not implemented",
        result_json: {},
      },
    };
    const client = new Stage6PythonPortClient(config(), transport);

    const result = await client.callDeclaredFailClosedPort("context.build", {
      space_id: "space-1",
      user_id: "user-1",
      payload_json: {},
    });

    expect(result).toMatchObject({
      status: "not_implemented",
      error_code: "stage6_port_not_implemented",
    });
  });

  it("maps HTTP errors to stable codes from Python error envelopes", async () => {
    const transport = new FakeTransport();
    transport.nextPost = {
      statusCode: 401,
      body: {
        detail: {
          error: "unauthorized_internal_port",
          message: "Unauthorized",
        },
      },
    };
    const client = new Stage6PythonPortClient(config(), transport);

    await expect(
      client.call({
        operation: "session_summary.get_latest",
        space_id: "space-1",
        payload_json: { session_id: "session-1" },
      }),
    ).rejects.toMatchObject({
      code: "unauthorized_internal_port",
      statusCode: 401,
    });
  });

  it("rejects invalid or secret-bearing responses from Python", async () => {
    const transport = new FakeTransport();
    transport.nextPost = {
      statusCode: 200,
      body: {
        operation: "session_summary.get_latest",
        owner: "sessions",
        status: "succeeded",
        result_json: { api_key: "sk-secret" },
      },
    };
    const client = new Stage6PythonPortClient(config(), transport);

    await expect(
      client.call({
        operation: "session_summary.get_latest",
        space_id: "space-1",
        payload_json: { session_id: "session-1" },
      }),
    ).rejects.toMatchObject({
      code: "stage6_port_invalid_response",
    });
  });

  it("requires an internal token before calling Python", async () => {
    const client = new Stage6PythonPortClient(config(""));

    await expect(client.getManifest()).rejects.toBeInstanceOf(Stage6PythonPortError);
    await expect(client.getManifest()).rejects.toMatchObject({
      code: "unauthorized_internal_port",
    });
  });
});
