import { INTERNAL_TOKEN_HEADER } from "../../gateway/internalAuth";
import type { ControlPlaneConfig } from "../../config";
import { loadProtocol } from "../providers/protocolRuntime";
import type {
  ChatTurnPrepareRunRequest,
  ChatTurnPrepareRunResult,
} from "@agent-space/protocol" with { "resolution-mode": "import" };

export class ChatTurnPreparationError extends Error {
  constructor(
    message: string,
    readonly statusCode = 502,
    readonly body: unknown = { detail: message },
  ) {
    super(message);
    this.name = "ChatTurnPreparationError";
  }
}

export interface ChatTurnPreparationHttpResponse {
  statusCode: number;
  body: unknown;
}

export interface ChatTurnPreparationTransport {
  postJson(
    url: string,
    headers: Record<string, string>,
    body: unknown,
    timeoutMs: number,
  ): Promise<ChatTurnPreparationHttpResponse>;
}

export class UndiciChatTurnPreparationTransport
  implements ChatTurnPreparationTransport
{
  async postJson(
    url: string,
    headers: Record<string, string>,
    body: unknown,
    timeoutMs: number,
  ): Promise<ChatTurnPreparationHttpResponse> {
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

export class ChatTurnPreparationClient {
  constructor(
    private readonly config: ControlPlaneConfig,
    private readonly transport: ChatTurnPreparationTransport =
      new UndiciChatTurnPreparationTransport(),
  ) {}

  async prepareRun(
    request: ChatTurnPrepareRunRequest,
  ): Promise<ChatTurnPrepareRunResult> {
    const protocol = await loadProtocol();
    const parsedRequest = protocol.ChatTurnPrepareRunRequestSchema.parse(request);
    const response = await this.transport.postJson(
      `${this.config.pythonApiBaseUrl}/api/v1/internal/agents-chat/prepare-run`,
      this.headers(),
      parsedRequest,
      this.config.requestTimeoutMs,
    );
    if (response.statusCode >= 400) throw responseError(response);
    const parsed = protocol.ChatTurnPrepareRunResultSchema.safeParse(response.body);
    if (!parsed.success) {
      throw new ChatTurnPreparationError(
        "Python chat-turn preparation returned an invalid response",
        502,
        response.body,
      );
    }
    return parsed.data;
  }

  private headers(): Record<string, string> {
    if (!this.config.internalToken) {
      throw new ChatTurnPreparationError(
        "CONTROL_PLANE_INTERNAL_TOKEN is required for Python chat-turn preparation",
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
    throw new ChatTurnPreparationError(
      "Python chat-turn preparation returned invalid JSON",
      502,
    );
  }
}

function responseError(response: ChatTurnPreparationHttpResponse): ChatTurnPreparationError {
  const body = response.body;
  const detail =
    body && typeof body === "object" ? (body as { detail?: unknown }).detail : null;
  const message =
    typeof detail === "string"
      ? detail
      : detail && typeof detail === "object"
        ? JSON.stringify(detail)
        : `HTTP ${response.statusCode}`;
  return new ChatTurnPreparationError(message, response.statusCode, body);
}
