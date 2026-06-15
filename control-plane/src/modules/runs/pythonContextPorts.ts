import { request as undiciRequest } from "undici";
import type { ControlPlaneConfig } from "../../config";
import { INTERNAL_TOKEN_HEADER } from "../../gateway/internalAuth";
import type {
  RunPythonContextPortManifestResponse,
  RunPythonContextPortOperation,
  RunPythonContextPortRequest,
  RunPythonContextPortResponse,
} from "@agent-space/protocol" with { "resolution-mode": "import" };
import type * as Protocol from "@agent-space/protocol" with { "resolution-mode": "import" };

type ProtocolModule = typeof Protocol;

let protocolCache: Promise<ProtocolModule> | null = null;

function loadProtocol(): Promise<ProtocolModule> {
  protocolCache ??= import("@agent-space/protocol");
  return protocolCache;
}

export class RunPythonContextPortError extends Error {
  constructor(
    message: string,
    readonly code: string,
    readonly statusCode?: number,
  ) {
    super(message);
    this.name = "RunPythonContextPortError";
  }
}

export interface RunPythonContextPortHttpResponse {
  statusCode: number;
  body: unknown;
}

export interface RunPythonContextPortTransport {
  getJson(
    url: string,
    headers: Record<string, string>,
    timeoutMs: number,
  ): Promise<RunPythonContextPortHttpResponse>;
  postJson(
    url: string,
    headers: Record<string, string>,
    body: unknown,
    timeoutMs: number,
  ): Promise<RunPythonContextPortHttpResponse>;
}

export class UndiciRunPythonContextPortTransport
  implements RunPythonContextPortTransport
{
  async getJson(
    url: string,
    headers: Record<string, string>,
    timeoutMs: number,
  ): Promise<RunPythonContextPortHttpResponse> {
    const response = await undiciRequest(url, {
      method: "GET",
      headers,
      maxRedirections: 0,
      signal: AbortSignal.timeout(timeoutMs),
    });
    return { statusCode: response.statusCode, body: await readJson(response.body) };
  }

  async postJson(
    url: string,
    headers: Record<string, string>,
    body: unknown,
    timeoutMs: number,
  ): Promise<RunPythonContextPortHttpResponse> {
    const response = await undiciRequest(url, {
      method: "POST",
      headers,
      body: JSON.stringify(body),
      maxRedirections: 0,
      signal: AbortSignal.timeout(timeoutMs),
    });
    return { statusCode: response.statusCode, body: await readJson(response.body) };
  }
}

export class RunPythonContextPortClient {
  constructor(
    private readonly config: ControlPlaneConfig,
    private readonly transport: RunPythonContextPortTransport =
      new UndiciRunPythonContextPortTransport(),
  ) {}

  async getManifest(): Promise<RunPythonContextPortManifestResponse> {
    const protocol = await loadProtocol();
    const response = await this.transport.getJson(
      this.url("/api/v1/internal/runs-context/ports"),
      this.headers(),
      this.config.requestTimeoutMs,
    );
    if (response.statusCode >= 400) throw responseError(response);
    return parseManifest(response.body, protocol);
  }

  async call(
    request: RunPythonContextPortRequest,
  ): Promise<RunPythonContextPortResponse> {
    const protocol = await loadProtocol();
    const parsedRequest = protocol.RunPythonContextPortRequestSchema.parse(request);
    const response = await this.transport.postJson(
      this.url("/api/v1/internal/runs-context/operations"),
      this.headers(),
      parsedRequest,
      this.config.requestTimeoutMs,
    );
    if (response.statusCode >= 400) throw responseError(response);
    return parseOperationResponse(response.body, protocol);
  }

  async finalizeRun(runId: string, spaceId: string): Promise<RunPythonContextPortResponse> {
    return this.call({
      operation: "finalization.finalize",
      run_id: runId,
      space_id: spaceId,
      payload_json: {},
    });
  }

  async callDeclaredFailClosedPort(
    operation: Exclude<RunPythonContextPortOperation, "finalization.finalize">,
    payload: Omit<RunPythonContextPortRequest, "operation">,
  ): Promise<RunPythonContextPortResponse> {
    return this.call({ operation, ...payload });
  }

  private url(path: string): string {
    return `${this.config.pythonApiBaseUrl.replace(/\/$/, "")}${path}`;
  }

  private headers(): Record<string, string> {
    if (!this.config.internalToken) {
      throw new RunPythonContextPortError(
        "CONTROL_PLANE_INTERNAL_TOKEN is required for Python run context ports",
        "unauthorized_internal_port",
      );
    }
    return {
      "content-type": "application/json",
      [INTERNAL_TOKEN_HEADER]: this.config.internalToken,
    };
  }
}

async function readJson(body: { text(): Promise<string> }): Promise<unknown> {
  const text = await body.text();
  if (!text) return null;
  try {
    return JSON.parse(text) as unknown;
  } catch (error) {
    throw new RunPythonContextPortError(
      "Python run context port returned invalid JSON",
      "python_context_port_invalid_response",
    );
  }
}

function parseManifest(
  value: unknown,
  protocol: ProtocolModule,
): RunPythonContextPortManifestResponse {
  const parsed = protocol.RunPythonContextPortManifestResponseSchema.safeParse(value);
  if (!parsed.success) {
    throw new RunPythonContextPortError(
      "Python run context port manifest had an invalid response shape",
      "python_context_port_invalid_response",
    );
  }
  return parsed.data;
}

function parseOperationResponse(
  value: unknown,
  protocol: ProtocolModule,
): RunPythonContextPortResponse {
  const parsed = protocol.RunPythonContextPortResponseSchema.safeParse(value);
  if (!parsed.success) {
    throw new RunPythonContextPortError(
      "Python run context port operation had an invalid response shape",
      "python_context_port_invalid_response",
    );
  }
  return parsed.data;
}

function responseError(response: RunPythonContextPortHttpResponse): RunPythonContextPortError {
  const detail =
    response.body && typeof response.body === "object"
      ? (response.body as { detail?: unknown }).detail
      : undefined;
  if (detail && typeof detail === "object") {
    const error = (detail as { error?: unknown }).error;
    const message = (detail as { message?: unknown }).message;
    if (typeof error === "string") {
      return new RunPythonContextPortError(
        typeof message === "string" ? message : error,
        error,
        response.statusCode,
      );
    }
  }
  if (typeof detail === "string") {
    return new RunPythonContextPortError(
      detail,
      "python_context_port_unavailable",
      response.statusCode,
    );
  }
  return new RunPythonContextPortError(
    `Python run context port failed with HTTP ${response.statusCode}`,
    "python_context_port_unavailable",
    response.statusCode,
  );
}
