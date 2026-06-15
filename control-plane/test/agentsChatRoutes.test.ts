import { afterEach, describe, expect, it } from "vitest";
import type { FastifyInstance } from "fastify";
import { buildServer } from "../src/server";
import { loadConfig } from "../src/config";
import {
  __setAgentChatIdentityForTests,
  __setAgentChatServicesFactoryForTests,
} from "../src/modules/agents";

let app: FastifyInstance;

type AgentChatServicesFactory = NonNullable<
  Parameters<typeof __setAgentChatServicesFactoryForTests>[0]
>;
type AgentChatServices = ReturnType<AgentChatServicesFactory>;

afterEach(async () => {
  __setAgentChatIdentityForTests(null);
  __setAgentChatServicesFactoryForTests(null);
  await app?.close();
});

function tsChatConfig() {
  return loadConfig({
    CONTROL_PLANE_PROVIDERS_AUTHORITY: "ts",
    CONTROL_PLANE_PROVIDERS_CREDENTIALS_AUTHORITY: "ts",
    CONTROL_PLANE_RUNS_AUTHORITY: "ts",
    CONTROL_PLANE_SESSIONS_AUTHORITY: "ts",
    CONTROL_PLANE_CHAT_TURN_AUTHORITY: "ts",
    CONTROL_PLANE_ENABLE_PYTHON_FALLBACK_PROXY: "false",
    CONTROL_PLANE_DATABASE_URL: "postgresql://cp@db:5432/agent_space",
    CONTROL_PLANE_INTERNAL_TOKEN: "internal-token",
  });
}

function tsContextConfig() {
  return loadConfig({
    CONTROL_PLANE_PROVIDERS_AUTHORITY: "ts",
    CONTROL_PLANE_PROVIDERS_CREDENTIALS_AUTHORITY: "ts",
    CONTROL_PLANE_RUNS_AUTHORITY: "ts",
    CONTROL_PLANE_SESSIONS_AUTHORITY: "ts",
    CONTROL_PLANE_CHAT_TURN_AUTHORITY: "ts",
    CONTROL_PLANE_CONTEXT_AUTHORITY: "ts",
    CONTROL_PLANE_ENABLE_PYTHON_FALLBACK_PROXY: "false",
    CONTROL_PLANE_DATABASE_URL: "postgresql://cp@db:5432/agent_space",
    CONTROL_PLANE_INTERNAL_TOKEN: "internal-token",
  });
}

function services(overrides: Partial<AgentChatServices> = {}): AgentChatServices {
  const base: AgentChatServices = {
    agents: {
      async getAgentForChat() {
        return {
          id: "agent-1",
          space_id: "space-1",
          name: "Personal Assistant",
          current_version_id: "agent-version-1",
        };
      },
    },
    sessions: {
      async getSession() {
        throw new Error("getSession should not run");
      },
      async createSession(_spaceId: string, _userId: string, input: { title?: string | null }) {
        return {
          id: "session-1",
          space_id: "space-1",
          user_id: "user-1",
          workspace_id: null,
          title: input.title ?? null,
          status: "active",
          created_at: "2026-06-14T10:00:00.000Z",
          updated_at: "2026-06-14T10:00:00.000Z",
        };
      },
      async addMessage() {
        throw new Error("addMessage should be overridden");
      },
    },
    preparation: {
      async prepareRun() {
        return { session_id: "session-1", run_id: "run-1" };
      },
    },
    orchestration: {
      async executeRun() {
        return { run_id: "run-1", status: "succeeded" };
      },
    },
    runs: {
      async getChatRunResult() {
        return {
          id: "run-1",
          space_id: "space-1",
          status: "succeeded",
          output_json: { output_text: "Hello from TS." },
          error_json: null,
        };
      },
    },
  };
  return { ...base, ...overrides };
}

describe("agents chat-turn route", () => {
  it("orchestrates a successful chat turn and persists user then assistant messages", async () => {
    __setAgentChatIdentityForTests({ spaceId: "space-1", userId: "user-1" });
    const calls: string[] = [];
    const messages: Array<Record<string, unknown>> = [];
    __setAgentChatServicesFactoryForTests(() =>
      services({
        sessions: {
          async getSession() {
            throw new Error("getSession should not run");
          },
          async createSession(_spaceId, _userId, input) {
            calls.push(`createSession:${input.title}`);
            return {
              id: "session-1",
              space_id: "space-1",
              user_id: "user-1",
              workspace_id: null,
              title: input.title ?? null,
              status: "active",
              created_at: "2026-06-14T10:00:00.000Z",
              updated_at: "2026-06-14T10:00:00.000Z",
            };
          },
          async addMessage(_spaceId, _userId, sessionId, input) {
            calls.push(`addMessage:${input.role}:${input.content}`);
            messages.push({ sessionId, ...input });
            return {
              id: `message-${messages.length}`,
              session_id: sessionId,
              space_id: "space-1",
              user_id: "user-1",
              role: input.role,
              content: input.content,
              metadata_json: input.metadata ?? null,
              created_at: "2026-06-14T10:00:00.000Z",
            };
          },
        },
        preparation: {
          async prepareRun(input) {
            calls.push(`prepare:${input.session_id}:${input.message}`);
            return { session_id: input.session_id, run_id: "run-1" };
          },
        },
        orchestration: {
          async executeRun(input) {
            calls.push(`execute:${input.run_id}:${input.space_id}:${input.command_source}`);
            return { run_id: input.run_id, status: "succeeded" };
          },
        },
      }),
    );
    app = buildServer(tsChatConfig(), { logger: false });

    const res = await app.inject({
      method: "POST",
      url: "/api/v1/agents/agent-1/chat",
      payload: { message: "  Hi there  " },
    });

    expect(res.statusCode).toBe(200);
    expect(res.json()).toEqual({
      session_id: "session-1",
      run_id: "run-1",
      ok: true,
      reply: "Hello from TS.",
    });
    expect(calls).toEqual([
      "createSession:Personal Assistant chat",
      "addMessage:user:Hi there",
      "prepare:session-1:Hi there",
      "execute:run-1:space-1:http",
      "addMessage:assistant:Hello from TS.",
    ]);
    expect(messages[1].metadata).toEqual({ run_id: "run-1" });
  });

  it("returns ok=false on run failure and does not persist an assistant message", async () => {
    __setAgentChatIdentityForTests({ spaceId: "space-1", userId: "user-1" });
    const roles: string[] = [];
    __setAgentChatServicesFactoryForTests(() =>
      services({
        sessions: {
          async getSession() {
            throw new Error("getSession should not run");
          },
          async createSession() {
            return {
              id: "session-1",
              space_id: "space-1",
              user_id: "user-1",
              workspace_id: null,
              title: "Personal Assistant chat",
              status: "active",
              created_at: "2026-06-14T10:00:00.000Z",
              updated_at: "2026-06-14T10:00:00.000Z",
            };
          },
          async addMessage(_spaceId, _userId, sessionId, input) {
            roles.push(input.role);
            return {
              id: `message-${roles.length}`,
              session_id: sessionId,
              space_id: "space-1",
              user_id: "user-1",
              role: input.role,
              content: input.content,
              metadata_json: input.metadata ?? null,
              created_at: "2026-06-14T10:00:00.000Z",
            };
          },
        },
        orchestration: {
          async executeRun(input) {
            return { run_id: input.run_id, status: "failed", error_code: "model_provider_required" };
          },
        },
        runs: {
          async getChatRunResult() {
            return {
              id: "run-1",
              space_id: "space-1",
              status: "failed",
              output_json: null,
              error_json: {
                error_code: "model_provider_required",
                error_text: "No model provider is configured.",
              },
            };
          },
        },
      }),
    );
    app = buildServer(tsChatConfig(), { logger: false });

    const res = await app.inject({
      method: "POST",
      url: "/api/v1/agents/agent-1/chat",
      payload: { message: "Hello?" },
    });

    expect(res.statusCode).toBe(200);
    expect(res.json()).toEqual({
      session_id: "session-1",
      run_id: "run-1",
      ok: false,
      error: "No model provider is configured.",
      error_code: "model_provider_required",
    });
    expect(roles).toEqual(["user"]);
  });

  it("fails closed when execution returns but the run row is not readable", async () => {
    __setAgentChatIdentityForTests({ spaceId: "space-1", userId: "user-1" });
    const roles: string[] = [];
    __setAgentChatServicesFactoryForTests(() =>
      services({
        sessions: {
          async getSession() {
            throw new Error("getSession should not run");
          },
          async createSession() {
            return {
              id: "session-1",
              space_id: "space-1",
              user_id: "user-1",
              workspace_id: null,
              title: "Personal Assistant chat",
              status: "active",
              created_at: "2026-06-14T10:00:00.000Z",
              updated_at: "2026-06-14T10:00:00.000Z",
            };
          },
          async addMessage(_spaceId, _userId, sessionId, input) {
            roles.push(input.role);
            return {
              id: `message-${roles.length}`,
              session_id: sessionId,
              space_id: "space-1",
              user_id: "user-1",
              role: input.role,
              content: input.content,
              metadata_json: input.metadata ?? null,
              created_at: "2026-06-14T10:00:00.000Z",
            };
          },
        },
        runs: {
          async getChatRunResult() {
            return null;
          },
        },
      }),
    );
    app = buildServer(tsChatConfig(), { logger: false });

    const res = await app.inject({
      method: "POST",
      url: "/api/v1/agents/agent-1/chat",
      payload: { message: "Hello?" },
    });

    expect(res.statusCode).toBe(200);
    expect(res.json()).toEqual({
      session_id: "session-1",
      run_id: "run-1",
      ok: false,
      error: "Run not found after TS execution",
      error_code: "run_not_found",
    });
    expect(roles).toEqual(["user"]);
  });

  it("404s an invisible existing session before writing a user message", async () => {
    __setAgentChatIdentityForTests({ spaceId: "space-1", userId: "user-1" });
    let wrote = false;
    __setAgentChatServicesFactoryForTests(() =>
      services({
        sessions: {
          async getSession() {
            return null;
          },
          async createSession() {
            throw new Error("createSession should not run");
          },
          async addMessage() {
            wrote = true;
            throw new Error("addMessage should not run");
          },
        },
      }),
    );
    app = buildServer(tsChatConfig(), { logger: false });

    const res = await app.inject({
      method: "POST",
      url: "/api/v1/agents/agent-1/chat",
      payload: { message: "Hello?", session_id: "missing-session" },
    });

    expect(res.statusCode).toBe(404);
    expect(res.json()).toEqual({ detail: "session not found in this space" });
    expect(wrote).toBe(false);
  });

  it("rejects empty messages with the Python-compatible 422", async () => {
    __setAgentChatIdentityForTests({ spaceId: "space-1", userId: "user-1" });
    __setAgentChatServicesFactoryForTests(() => services());
    app = buildServer(tsChatConfig(), { logger: false });

    const res = await app.inject({
      method: "POST",
      url: "/api/v1/agents/agent-1/chat",
      payload: { message: "   " },
    });

    expect(res.statusCode).toBe(422);
    expect(res.json()).toEqual({ detail: "message must not be empty" });
  });

  it("assembles context in TS and persists the snapshot when context authority is ts", async () => {
    __setAgentChatIdentityForTests({ spaceId: "space-1", userId: "user-1" });
    const calls: string[] = [];
    let persisted: Record<string, unknown> | null = null;
    __setAgentChatServicesFactoryForTests(() =>
      services({
        sessions: {
          async getSession() {
            throw new Error("getSession should not run");
          },
          async createSession() {
            return {
              id: "session-1",
              space_id: "space-1",
              user_id: "user-1",
              workspace_id: null,
              title: "Personal Assistant chat",
              status: "active",
              created_at: "2026-06-14T10:00:00.000Z",
              updated_at: "2026-06-14T10:00:00.000Z",
            };
          },
          async addMessage(_spaceId, _userId, sessionId, input) {
            calls.push(`addMessage:${input.role}`);
            return {
              id: `message-${calls.length}`,
              session_id: sessionId,
              space_id: "space-1",
              user_id: "user-1",
              role: input.role,
              content: input.content,
              metadata_json: input.metadata ?? null,
              created_at: "2026-06-14T10:00:00.000Z",
            };
          },
        },
        preparation: {
          async prepareRun() {
            throw new Error("prepareRun must not run under context=ts");
          },
        },
        context: {
          async fetchCandidates(input) {
            calls.push(`candidates:${input.message}`);
            return {
              allowed_sources: ["memory"],
              max_tokens: 4000,
              max_items: 20,
              context_policy_applied: true,
              items: [
                {
                  item_type: "memory",
                  item_id: "memory-1",
                  title: "A memory",
                  excerpt: "remember this",
                  score: 0.8,
                  reason: "approved_memory",
                  token_count: 3,
                  metadata: {},
                },
              ],
            };
          },
          async createRun(input) {
            calls.push(`createRun:${input.prompt.includes("remember this") ? "with-context" : "bare"}`);
            return { run_id: "run-1", context_snapshot_id: "snapshot-1" };
          },
        },
        snapshots: {
          async persistChatSnapshot(input) {
            persisted = input as unknown as Record<string, unknown>;
            calls.push(`persist:${input.contextSnapshotId}:${input.items.length}`);
          },
        },
        orchestration: {
          async executeRun(input) {
            calls.push(`execute:${input.run_id}`);
            return { run_id: input.run_id, status: "succeeded" };
          },
        },
      }),
    );
    app = buildServer(tsContextConfig(), { logger: false });

    const res = await app.inject({
      method: "POST",
      url: "/api/v1/agents/agent-1/chat",
      payload: { message: "Hi" },
    });

    expect(res.statusCode).toBe(200);
    expect(res.json()).toEqual({
      session_id: "session-1",
      run_id: "run-1",
      ok: true,
      reply: "Hello from TS.",
    });
    // TS owns context build (candidates → snapshot persist) and never calls the
    // combined Python prepare-run port.
    expect(calls).toEqual([
      "addMessage:user",
      "candidates:Hi",
      "createRun:with-context",
      "persist:snapshot-1:1",
      "execute:run-1",
      "addMessage:assistant",
    ]);
    expect(persisted).toMatchObject({
      contextSnapshotId: "snapshot-1",
      spaceId: "space-1",
      tokenEstimate: 3,
    });
  });

  it("leaves the chat route unowned by TS when chat authority is python", async () => {
    app = buildServer(
      loadConfig({ CONTROL_PLANE_ENABLE_PYTHON_FALLBACK_PROXY: "false" }),
      { logger: false },
    );

    const res = await app.inject({
      method: "POST",
      url: "/api/v1/agents/agent-1/chat",
      payload: { message: "Hello" },
    });

    expect(res.statusCode).toBe(503);
    expect(res.payload).toContain("python_fallback_proxy_disabled");
  });
});
