import { request as undiciRequest } from "undici";
import type { ControlPlaneConfig } from "../../config";
import { INTERNAL_TOKEN_HEADER } from "../../gateway/internalAuth";
import type {
  ProposalAcceptDispatchRequest,
  ProposalAcceptOut,
  ProposalApprovalOut,
  ProposalEgressApprovalDispatchRequest,
  ProposalOut,
  ProposalPythonPortManifestResponse,
  ProposalRejectDispatchRequest,
} from "@agent-space/protocol" with { "resolution-mode": "import" };
import type * as Protocol from "@agent-space/protocol" with { "resolution-mode": "import" };

type ProtocolModule = typeof Protocol;

let protocolCache: Promise<ProtocolModule> | null = null;

function loadProtocol(): Promise<ProtocolModule> {
  protocolCache ??= import("@agent-space/protocol");
  return protocolCache;
}

export class ProposalPythonPortError extends Error {
  constructor(
    message: string,
    readonly code: string,
    readonly statusCode?: number,
    readonly responseBody?: unknown,
  ) {
    super(message);
    this.name = "ProposalPythonPortError";
  }
}

export interface ProposalPythonPortHttpResponse {
  statusCode: number;
  body: unknown;
}

export interface ProposalPythonPortTransport {
  getJson(
    url: string,
    headers: Record<string, string>,
    timeoutMs: number,
  ): Promise<ProposalPythonPortHttpResponse>;
  postJson(
    url: string,
    headers: Record<string, string>,
    body: unknown,
    timeoutMs: number,
  ): Promise<ProposalPythonPortHttpResponse>;
}

export class UndiciProposalPythonPortTransport implements ProposalPythonPortTransport {
  async getJson(
    url: string,
    headers: Record<string, string>,
    timeoutMs: number,
  ): Promise<ProposalPythonPortHttpResponse> {
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
  ): Promise<ProposalPythonPortHttpResponse> {
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

export class ProposalPythonPortClient {
  constructor(
    private readonly config: ControlPlaneConfig,
    private readonly transport: ProposalPythonPortTransport =
      new UndiciProposalPythonPortTransport(),
  ) {}

  async getManifest(): Promise<ProposalPythonPortManifestResponse> {
    const protocol = await loadProtocol();
    const response = await this.transport.getJson(
      this.url("/api/v1/internal/proposals-context/ports"),
      this.headers(),
      this.config.requestTimeoutMs,
    );
    if (response.statusCode >= 400) throw responseError(response);
    const parsed = protocol.ProposalPythonPortManifestResponseSchema.safeParse(response.body);
    if (!parsed.success) throw invalidResponse("manifest");
    return parsed.data;
  }

  async acceptProposal(request: ProposalAcceptDispatchRequest): Promise<ProposalAcceptOut> {
    const protocol = await loadProtocol();
    const parsedRequest = protocol.ProposalAcceptDispatchRequestSchema.parse(request);
    const response = await this.transport.postJson(
      this.url("/api/v1/internal/proposals-context/accept"),
      this.headers(),
      parsedRequest,
      this.config.requestTimeoutMs,
    );
    if (response.statusCode >= 400) throw responseError(response);
    const parsed = protocol.ProposalAcceptOutSchema.safeParse(response.body);
    if (!parsed.success) throw invalidResponse("accept");
    return parsed.data;
  }

  /**
   * Stage 6 slice 7b: gate (validate + run the proposal.apply policy gate, which
   * writes the durable ALLOW audit) an accepted memory proposal and return its
   * raw fields. Does NOT apply or mark accepted — the TS accept path does that.
   * A blocked gate / risk error surfaces as a `ProposalPythonPortError`.
   */
  async gateMemoryApply(request: {
    proposal_id: string;
    space_id: string;
    user_id: string;
  }): Promise<MemoryApplyGateResult> {
    const response = await this.transport.postJson(
      this.url("/api/v1/internal/proposals-context/memory-apply-gate"),
      this.headers(),
      request,
      this.config.requestTimeoutMs,
    );
    if (response.statusCode >= 400) throw responseError(response);
    const parsed = parseMemoryApplyGate(response.body);
    if (!parsed) throw invalidResponse("memory-apply-gate");
    return parsed;
  }

  async rejectProposal(request: ProposalRejectDispatchRequest): Promise<ProposalOut> {
    const protocol = await loadProtocol();
    const parsedRequest = protocol.ProposalRejectDispatchRequestSchema.parse(request);
    const response = await this.transport.postJson(
      this.url("/api/v1/internal/proposals-context/reject"),
      this.headers(),
      parsedRequest,
      this.config.requestTimeoutMs,
    );
    if (response.statusCode >= 400) throw responseError(response);
    const parsed = protocol.ProposalOutSchema.safeParse(response.body);
    if (!parsed.success) throw invalidResponse("reject");
    return parsed.data;
  }

  async approveEgressGrantingUser(
    request: ProposalEgressApprovalDispatchRequest,
  ): Promise<ProposalApprovalOut> {
    const protocol = await loadProtocol();
    const parsedRequest = protocol.ProposalEgressApprovalDispatchRequestSchema.parse(request);
    const response = await this.transport.postJson(
      this.url("/api/v1/internal/proposals-context/approvals/egress-granting-user"),
      this.headers(),
      parsedRequest,
      this.config.requestTimeoutMs,
    );
    if (response.statusCode >= 400) throw responseError(response);
    const parsed = protocol.ProposalApprovalOutSchema.safeParse(response.body);
    if (!parsed.success) throw invalidResponse("egress approval");
    return parsed.data;
  }

  private url(path: string): string {
    return `${this.config.pythonApiBaseUrl.replace(/\/$/, "")}${path}`;
  }

  private headers(): Record<string, string> {
    if (!this.config.internalToken) {
      throw new ProposalPythonPortError(
        "CONTROL_PLANE_INTERNAL_TOKEN is required for Python proposal ports",
        "unauthorized_internal_port",
      );
    }
    return {
      "content-type": "application/json",
      [INTERNAL_TOKEN_HEADER]: this.config.internalToken,
    };
  }
}

export interface MemoryApplyGateResult {
  id: string;
  space_id: string;
  proposal_type: string;
  payload_json: Record<string, unknown> | null;
  workspace_id: string | null;
  created_by_user_id: string | null;
  created_by_run_id: string | null;
  title: string | null;
}

function parseMemoryApplyGate(body: unknown): MemoryApplyGateResult | null {
  if (!body || typeof body !== "object") return null;
  const b = body as Record<string, unknown>;
  if (typeof b.id !== "string" || typeof b.space_id !== "string" || typeof b.proposal_type !== "string") {
    return null;
  }
  const payload =
    b.payload_json && typeof b.payload_json === "object" && !Array.isArray(b.payload_json)
      ? (b.payload_json as Record<string, unknown>)
      : null;
  const asStr = (v: unknown): string | null => (typeof v === "string" ? v : null);
  return {
    id: b.id,
    space_id: b.space_id,
    proposal_type: b.proposal_type,
    payload_json: payload,
    workspace_id: asStr(b.workspace_id),
    created_by_user_id: asStr(b.created_by_user_id),
    created_by_run_id: asStr(b.created_by_run_id),
    title: asStr(b.title),
  };
}

async function readJson(body: { text(): Promise<string> }): Promise<unknown> {
  const text = await body.text();
  if (!text) return null;
  try {
    return JSON.parse(text) as unknown;
  } catch {
    throw new ProposalPythonPortError(
      "Python proposal port returned invalid JSON",
      "python_proposal_port_invalid_response",
    );
  }
}

function responseError(response: ProposalPythonPortHttpResponse): ProposalPythonPortError {
  const detail =
    response.body && typeof response.body === "object"
      ? (response.body as { detail?: unknown }).detail
      : undefined;
  const envelope =
    response.body && typeof response.body === "object"
      ? (response.body as { error?: unknown; message?: unknown })
      : null;
  if (typeof envelope?.error === "string") {
    return new ProposalPythonPortError(
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
      return new ProposalPythonPortError(
        typeof message === "string" ? message : error,
        error,
        response.statusCode,
        response.body,
      );
    }
  }
  if (typeof detail === "string") {
    return new ProposalPythonPortError(
      detail,
      "python_proposal_port_unavailable",
      response.statusCode,
      response.body,
    );
  }
  return new ProposalPythonPortError(
    `Python proposal port failed with HTTP ${response.statusCode}`,
    "python_proposal_port_unavailable",
    response.statusCode,
    response.body,
  );
}

function invalidResponse(operation: string): ProposalPythonPortError {
  return new ProposalPythonPortError(
    `Python proposal port ${operation} response had an invalid shape`,
    "python_proposal_port_invalid_response",
  );
}
