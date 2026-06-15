import { describe, expect, it } from "vitest";
import { loadConfig } from "../src/config";
import {
  ChatContextPortClient,
  ChatContextPortError,
  type ChatContextPortHttpResponse,
  type ChatContextPortTransport,
} from "../src/modules/agents/pythonChatContextPorts";

function config() {
  return loadConfig({
    CONTROL_PLANE_PROVIDERS_AUTHORITY: "ts",
    CONTROL_PLANE_PROVIDERS_CREDENTIALS_AUTHORITY: "ts",
    CONTROL_PLANE_RUNS_AUTHORITY: "ts",
    CONTROL_PLANE_SESSIONS_AUTHORITY: "ts",
    CONTROL_PLANE_CHAT_TURN_AUTHORITY: "ts",
    CONTROL_PLANE_CONTEXT_AUTHORITY: "ts",
    CONTROL_PLANE_DATABASE_URL: "postgresql://cp@db:5432/agent_space",
    CONTROL_PLANE_INTERNAL_TOKEN: "internal-token",
  });
}

class FakeTransport implements ChatContextPortTransport {
  lastUrl = "";
  lastHeaders: Record<string, string> = {};
  constructor(private readonly response: ChatContextPortHttpResponse) {}
  async postJson(
    url: string,
    headers: Record<string, string>,
  ): Promise<ChatContextPortHttpResponse> {
    this.lastUrl = url;
    this.lastHeaders = headers;
    return this.response;
  }
}

const candidateRequest = {
  agent_id: "agent-1",
  space_id: "space-1",
  user_id: "user-1",
  session_id: "session-1",
  message: "hi",
};

describe("ChatContextPortClient", () => {
  it("fetches candidates with the internal token and validates the response", async () => {
    const transport = new FakeTransport({
      statusCode: 200,
      body: {
        allowed_sources: ["memory"],
        max_tokens: 4000,
        max_items: 20,
        context_policy_applied: true,
        items: [],
      },
    });
    const client = new ChatContextPortClient(config(), transport);
    const result = await client.fetchCandidates(candidateRequest);
    expect(result.max_items).toBe(20);
    expect(transport.lastUrl).toContain("/internal/agents-chat/context-candidates");
    expect(transport.lastHeaders["x-agent-space-internal-token"]).toBe("internal-token");
  });

  it("surfaces the Python error envelope on a 4xx", async () => {
    const transport = new FakeTransport({
      statusCode: 410,
      body: { detail: "Python no longer owns chat context assembly" },
    });
    const client = new ChatContextPortClient(config(), transport);
    await expect(client.createRun({ ...candidateRequest, prompt: "p" })).rejects.toMatchObject(
      { statusCode: 410 },
    );
  });

  it("fails closed on an invalid create-run response", async () => {
    const transport = new FakeTransport({ statusCode: 200, body: { nope: true } });
    const client = new ChatContextPortClient(config(), transport);
    await expect(
      client.createRun({ ...candidateRequest, prompt: "p" }),
    ).rejects.toBeInstanceOf(ChatContextPortError);
  });
});
