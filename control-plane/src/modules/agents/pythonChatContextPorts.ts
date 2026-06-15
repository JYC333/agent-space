/**
 * TS clients for the Stage 6 slice-4 Python chat-context ports.
 *
 * Two narrow service-authenticated ports back the TS-owned chat context
 * assembly while the underlying reads / run creation stay Python-owned:
 *   - `context-candidates` — read-only per-source candidates (memory, knowledge,
 *     source, activity, workspace, project) for the TS budget/dedup loop;
 *   - `create-run` — creates the queued chat run + its empty ContextSnapshot.
 *
 * Modeled on `pythonChatTurnPrep.ts`: undici transport, internal-token header,
 * zod-validated responses, preserved Python error envelopes.
 */

import { INTERNAL_TOKEN_HEADER } from "../../gateway/internalAuth";
import type { ControlPlaneConfig } from "../../config";
import { loadProtocol } from "../providers/protocolRuntime";
import type {
  ChatContextCandidatesRequest,
  ChatContextCandidatesResult,
  ChatRunCreateRequest,
  ChatRunCreateResult,
} from "@agent-space/protocol" with { "resolution-mode": "import" };

export class ChatContextPortError extends Error {
  constructor(
    message: string,
    readonly statusCode = 502,
    readonly body: unknown = { detail: message },
  ) {
    super(message);
    this.name = "ChatContextPortError";
  }
}

export interface ChatContextPortHttpResponse {
  statusCode: number;
  body: unknown;
}

export interface ChatContextPortTransport {
  postJson(
    url: string,
    headers: Record<string, string>,
    body: unknown,
    timeoutMs: number,
  ): Promise<ChatContextPortHttpResponse>;
}

export class UndiciChatContextPortTransport implements ChatContextPortTransport {
  async postJson(
    url: string,
    headers: Record<string, string>,
    body: unknown,
    timeoutMs: number,
  ): Promise<ChatContextPortHttpResponse> {
    const { request } = await import("undici");
    const response = await request(url, {
      method: "POST",
      headers,
      body: JSON.stringify(body),
      bodyTimeout: timeoutMs,
      headersTimeout: timeoutMs,
    });
    return { statusCode: response.statusCode, body: await readJson(response.body) };
  }
}

export class ChatContextPortClient {
  constructor(
    private readonly config: ControlPlaneConfig,
    private readonly transport: ChatContextPortTransport =
      new UndiciChatContextPortTransport(),
  ) {}

  async fetchCandidates(
    request: ChatContextCandidatesRequest,
  ): Promise<ChatContextCandidatesResult> {
    const protocol = await loadProtocol();
    const parsedRequest =
      protocol.ChatContextCandidatesRequestSchema.parse(request);
    const response = await this.transport.postJson(
      `${this.config.pythonApiBaseUrl}/api/v1/internal/agents-chat/context-candidates`,
      this.headers(),
      parsedRequest,
      this.config.requestTimeoutMs,
    );
    if (response.statusCode >= 400) throw responseError(response);
    const parsed = protocol.ChatContextCandidatesResultSchema.safeParse(
      response.body,
    );
    if (!parsed.success) {
      throw new ChatContextPortError(
        "Python chat context-candidates port returned an invalid response",
        502,
        response.body,
      );
    }
    return parsed.data;
  }

  async createRun(
    request: ChatRunCreateRequest,
  ): Promise<ChatRunCreateResult> {
    const protocol = await loadProtocol();
    const parsedRequest = protocol.ChatRunCreateRequestSchema.parse(request);
    const response = await this.transport.postJson(
      `${this.config.pythonApiBaseUrl}/api/v1/internal/agents-chat/create-run`,
      this.headers(),
      parsedRequest,
      this.config.requestTimeoutMs,
    );
    if (response.statusCode >= 400) throw responseError(response);
    const parsed = protocol.ChatRunCreateResultSchema.safeParse(response.body);
    if (!parsed.success) {
      throw new ChatContextPortError(
        "Python chat create-run port returned an invalid response",
        502,
        response.body,
      );
    }
    return parsed.data;
  }

  private headers(): Record<string, string> {
    if (!this.config.internalToken) {
      throw new ChatContextPortError(
        "CONTROL_PLANE_INTERNAL_TOKEN is required for Python chat-context ports",
        401,
        { detail: "Unauthorized" },
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
    throw new ChatContextPortError(
      "Python chat-context port returned invalid JSON",
      502,
    );
  }
}

function responseError(response: ChatContextPortHttpResponse): ChatContextPortError {
  const body = response.body;
  const detail =
    body && typeof body === "object" ? (body as { detail?: unknown }).detail : null;
  const message =
    typeof detail === "string"
      ? detail
      : detail && typeof detail === "object"
        ? JSON.stringify(detail)
        : `HTTP ${response.statusCode}`;
  return new ChatContextPortError(message, response.statusCode, body);
}
