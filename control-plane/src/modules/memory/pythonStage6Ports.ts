import { request as undiciRequest } from "undici";
import type { ControlPlaneConfig } from "../../config";
import { INTERNAL_TOKEN_HEADER } from "../../gateway/internalAuth";
import type {
  Stage6PythonPortManifestResponse,
  Stage6PythonPortOperation,
  Stage6PythonPortRequest,
  Stage6PythonPortResponse,
} from "@agent-space/protocol" with { "resolution-mode": "import" };
import type * as Protocol from "@agent-space/protocol" with { "resolution-mode": "import" };

type ProtocolModule = typeof Protocol;

let protocolCache: Promise<ProtocolModule> | null = null;

function loadProtocol(): Promise<ProtocolModule> {
  protocolCache ??= import("@agent-space/protocol");
  return protocolCache;
}

export class Stage6PythonPortError extends Error {
  constructor(
    message: string,
    readonly code: string,
    readonly statusCode?: number,
    readonly responseBody?: unknown,
  ) {
    super(message);
    this.name = "Stage6PythonPortError";
  }
}

export interface Stage6PythonPortHttpResponse {
  statusCode: number;
  body: unknown;
}

export interface Stage6PythonPortTransport {
  getJson(
    url: string,
    headers: Record<string, string>,
    timeoutMs: number,
  ): Promise<Stage6PythonPortHttpResponse>;
  postJson(
    url: string,
    headers: Record<string, string>,
    body: unknown,
    timeoutMs: number,
  ): Promise<Stage6PythonPortHttpResponse>;
}

export class UndiciStage6PythonPortTransport implements Stage6PythonPortTransport {
  async getJson(
    url: string,
    headers: Record<string, string>,
    timeoutMs: number,
  ): Promise<Stage6PythonPortHttpResponse> {
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
  ): Promise<Stage6PythonPortHttpResponse> {
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

export class Stage6PythonPortClient {
  constructor(
    private readonly config: ControlPlaneConfig,
    private readonly transport: Stage6PythonPortTransport =
      new UndiciStage6PythonPortTransport(),
  ) {}

  async getManifest(): Promise<Stage6PythonPortManifestResponse> {
    const protocol = await loadProtocol();
    const response = await this.transport.getJson(
      this.url("/api/v1/internal/stage6-context/ports"),
      this.headers(),
      this.config.requestTimeoutMs,
    );
    if (response.statusCode >= 400) throw responseError(response);
    const parsed = protocol.Stage6PythonPortManifestResponseSchema.safeParse(
      response.body,
    );
    if (!parsed.success) throw invalidResponse("manifest", response.body);
    return parsed.data;
  }

  async call(
    request: Stage6PythonPortRequest,
  ): Promise<Stage6PythonPortResponse> {
    const protocol = await loadProtocol();
    const parsedRequest = protocol.Stage6PythonPortRequestSchema.parse(request);
    const response = await this.transport.postJson(
      this.url("/api/v1/internal/stage6-context/operations"),
      this.headers(),
      parsedRequest,
      this.config.requestTimeoutMs,
    );
    if (response.statusCode >= 400) throw responseError(response);
    const parsed = protocol.Stage6PythonPortResponseSchema.safeParse(response.body);
    if (!parsed.success) throw invalidResponse("operation", response.body);
    return parsed.data;
  }

  async callDeclaredFailClosedPort(
    operation: Exclude<Stage6PythonPortOperation, "session_summary.get_latest">,
    payload: Omit<Stage6PythonPortRequest, "operation">,
  ): Promise<Stage6PythonPortResponse> {
    return this.call({ operation, ...payload });
  }

  private url(path: string): string {
    return `${this.config.pythonApiBaseUrl.replace(/\/$/, "")}${path}`;
  }

  private headers(): Record<string, string> {
    if (!this.config.internalToken) {
      throw new Stage6PythonPortError(
        "CONTROL_PLANE_INTERNAL_TOKEN is required for Python Stage 6 ports",
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
  } catch {
    throw new Stage6PythonPortError(
      "Python Stage 6 port returned invalid JSON",
      "stage6_port_invalid_response",
    );
  }
}

function responseError(response: Stage6PythonPortHttpResponse): Stage6PythonPortError {
  const detail =
    response.body && typeof response.body === "object"
      ? (response.body as { detail?: unknown }).detail
      : undefined;
  const envelope =
    response.body && typeof response.body === "object"
      ? (response.body as { error?: unknown; message?: unknown })
      : null;
  if (typeof envelope?.error === "string") {
    return new Stage6PythonPortError(
      typeof envelope.message === "string" ? envelope.message : envelope.error,
      envelope.error,
      response.statusCode,
      response.body,
    );
  }
  if (detail && typeof detail === "object") {
    const error = (detail as { error?: unknown }).error;
    const message = (detail as { message?: unknown }).message;
    if (typeof error === "string") {
      return new Stage6PythonPortError(
        typeof message === "string" ? message : error,
        error,
        response.statusCode,
        response.body,
      );
    }
  }
  if (typeof detail === "string") {
    return new Stage6PythonPortError(
      detail,
      "python_stage6_port_unavailable",
      response.statusCode,
      response.body,
    );
  }
  return new Stage6PythonPortError(
    `Python Stage 6 port failed with HTTP ${response.statusCode}`,
    "python_stage6_port_unavailable",
    response.statusCode,
    response.body,
  );
}

function invalidResponse(operation: string, responseBody?: unknown): Stage6PythonPortError {
  return new Stage6PythonPortError(
    `Python Stage 6 port ${operation} response had an invalid shape`,
    "stage6_port_invalid_response",
    undefined,
    responseBody,
  );
}
