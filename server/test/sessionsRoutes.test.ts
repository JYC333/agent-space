import { afterEach, describe, expect, it } from "vitest";
import type { FastifyInstance } from "fastify";
import { buildServer } from "../src/server";
import { loadConfig } from "../src/config";
import {
  __setSessionIdentityForTests,
  __setSessionServicesFactoryForTests,
} from "../src/modules/sessions";
import type { PgSessionRepository } from "../src/modules/sessions/repository";
import type {
  MessageOut,
  SessionSummaryForContext,
  SessionOut,
  SessionPage,
} from "@agent-space/protocol" with { "resolution-mode": "import" };

let app: FastifyInstance;

afterEach(async () => {
  __setSessionIdentityForTests(null);
  __setSessionServicesFactoryForTests(null);
  await app?.close();
});

function sessionsConfig() {
  return loadConfig({
    SERVER_DATABASE_URL: "postgresql://server@db:5432/agent_space",
    SERVER_INTERNAL_TOKEN: "internal-token",
  });
}

type Repo = Pick<
  PgSessionRepository,
  | "listSessions"
  | "getSession"
  | "listMessages"
  | "createSession"
  | "addMessage"
  | "reflectSession"
  | "getLatestSummaryForContext"
>;

const notCalled = (name: string) => () => {
  throw new Error(`${name} should not run`);
};

/** A repository fake that throws for every method unless overridden. */
function repo(overrides: Partial<Repo>): Repo {
  return {
    listSessions: notCalled("listSessions"),
    getSession: notCalled("getSession"),
    listMessages: notCalled("listMessages"),
    createSession: notCalled("createSession"),
    addMessage: notCalled("addMessage"),
    reflectSession: notCalled("reflectSession"),
    getLatestSummaryForContext: notCalled("getLatestSummaryForContext"),
    ...overrides,
  } as Repo;
}

function withRepo(overrides: Partial<Repo>) {
  __setSessionServicesFactoryForTests(() => ({ repository: repo(overrides) }));
}

function session(overrides: Partial<SessionOut> = {}): SessionOut {
  return {
    id: "session-1",
    space_id: "space-1",
    user_id: "user-1",
    workspace_id: null,
    title: "chat",
    status: "active",
    created_at: "2026-06-14T10:00:00.000Z",
    updated_at: "2026-06-14T10:05:00.000Z",
    ...overrides,
  };
}

function message(overrides: Partial<MessageOut> = {}): MessageOut {
  return {
    id: "message-1",
    session_id: "session-1",
    space_id: "space-1",
    user_id: "user-1",
    role: "user",
    content: "hello",
    metadata_json: null,
    created_at: "2026-06-14T10:01:00.000Z",
    ...overrides,
  };
}

function summary(overrides: Partial<SessionSummaryForContext> = {}): SessionSummaryForContext {
  return {
    id: "summary-1",
    session_id: "session-1",
    version: 2,
    summary_text: "Session with 3 messages. Key topics: stage, migration.",
    condenser_version: "pattern.v1",
    ...overrides,
  };
}

describe("session summary internal route", () => {
  it("serves latest active session summary from the server sessions authority", async () => {
    const calls: Array<Record<string, unknown>> = [];
    withRepo({
      async getLatestSummaryForContext(spaceId, sessionId) {
        calls.push({ spaceId, sessionId });
        return summary({ session_id: sessionId });
      },
    });
    app = buildServer(sessionsConfig(), { logger: false });

    const res = await app.inject({
      method: "POST",
      url: "/internal/sessions/session-summary/get-latest",
      headers: { "x-agent-space-internal-token": "internal-token" },
      payload: { space_id: "space-1", session_id: "session-1" },
    });

    expect(res.statusCode).toBe(200);
    expect(res.json()).toEqual({ summary: summary() });
    expect(calls).toEqual([{ spaceId: "space-1", sessionId: "session-1" }]);
  });

  it("returns null for a missing summary without leaking content", async () => {
    withRepo({
      async getLatestSummaryForContext() {
        return null;
      },
    });
    app = buildServer(sessionsConfig(), { logger: false });

    const res = await app.inject({
      method: "POST",
      url: "/internal/sessions/session-summary/get-latest",
      headers: { "x-agent-space-internal-token": "internal-token" },
      payload: { space_id: "space-1", session_id: "missing-session" },
    });

    expect(res.statusCode).toBe(200);
    expect(res.json()).toEqual({ summary: null });
  });

  it("requires the internal service token", async () => {
    withRepo({});
    app = buildServer(sessionsConfig(), { logger: false });

    const res = await app.inject({
      method: "POST",
      url: "/internal/sessions/session-summary/get-latest",
      payload: { space_id: "space-1", session_id: "session-1" },
    });

    expect(res.statusCode).toBe(401);
  });
});

describe("session read routes", () => {
  it("serves the session list from the server read model with space/user scope", async () => {
    __setSessionIdentityForTests({ spaceId: "space-1", userId: "user-1" });
    const calls: Array<Record<string, unknown>> = [];
    const page: SessionPage = { items: [session()], total: 1, limit: 25, offset: 10 };
    withRepo({
      async listSessions(spaceId, userId, limit, offset) {
        calls.push({ spaceId, userId, limit, offset });
        return page;
      },
    });
    app = buildServer(sessionsConfig(), { logger: false });

    const res = await app.inject({
      method: "GET",
      url: "/api/v1/sessions?limit=25&offset=10",
    });

    expect(res.statusCode).toBe(200);
    expect(res.json()).toEqual(page);
    expect(calls).toEqual([
      { spaceId: "space-1", userId: "user-1", limit: 25, offset: 10 },
    ]);
  });

  it("serves a visible session detail and 404s an invisible one", async () => {
    __setSessionIdentityForTests({ spaceId: "space-1", userId: "user-1" });
    withRepo({
      async getSession(_spaceId, _userId, sessionId) {
        return sessionId === "session-1" ? session({ id: sessionId }) : null;
      },
    });
    app = buildServer(sessionsConfig(), { logger: false });

    const ok = await app.inject({ method: "GET", url: "/api/v1/sessions/session-1" });
    const missing = await app.inject({ method: "GET", url: "/api/v1/sessions/other" });

    expect(ok.statusCode).toBe(200);
    expect(ok.json()).toMatchObject({ id: "session-1", status: "active" });
    expect(missing.statusCode).toBe(404);
  });

  it("serves messages for a visible session and 404s when not visible", async () => {
    __setSessionIdentityForTests({ spaceId: "space-1", userId: "user-1" });
    const calls: Array<Record<string, unknown>> = [];
    withRepo({
      async listMessages(spaceId, userId, sessionId, limit, offset) {
        calls.push({ spaceId, userId, sessionId, limit, offset });
        return sessionId === "session-1" ? [message()] : null;
      },
    });
    app = buildServer(sessionsConfig(), { logger: false });

    const ok = await app.inject({
      method: "GET",
      url: "/api/v1/sessions/session-1/messages",
    });
    const missing = await app.inject({
      method: "GET",
      url: "/api/v1/sessions/other/messages",
    });

    expect(ok.statusCode).toBe(200);
    expect(ok.json()).toEqual([message()]);
    expect(missing.statusCode).toBe(404);
    expect(calls[0]).toMatchObject({ limit: 100, offset: 0 });
  });

  it("rejects an out-of-range limit with 422", async () => {
    __setSessionIdentityForTests({ spaceId: "space-1", userId: "user-1" });
    withRepo({});
    app = buildServer(sessionsConfig(), { logger: false });

    const res = await app.inject({ method: "GET", url: "/api/v1/sessions?limit=999" });

    expect(res.statusCode).toBe(422);
  });
});

describe("session write routes", () => {
  it("creates a session scoped to the acting identity (201)", async () => {
    __setSessionIdentityForTests({ spaceId: "space-1", userId: "user-1" });
    const calls: Array<Record<string, unknown>> = [];
    withRepo({
      async createSession(spaceId, userId, input) {
        calls.push({ spaceId, userId, input });
        return session({ title: input.title ?? null, workspace_id: input.workspaceId ?? null });
      },
    });
    app = buildServer(sessionsConfig(), { logger: false });

    const res = await app.inject({
      method: "POST",
      url: "/api/v1/sessions",
      payload: { title: "new chat", workspace_id: "ws-1", metadata: { a: 1 } },
    });

    expect(res.statusCode).toBe(201);
    expect(res.json()).toMatchObject({ id: "session-1", status: "active" });
    expect(calls).toEqual([
      {
        spaceId: "space-1",
        userId: "user-1",
        input: { workspaceId: "ws-1", title: "new chat", metadata: { a: 1 } },
      },
    ]);
  });

  it("appends a message to a visible session (201) and 404s an invisible one", async () => {
    __setSessionIdentityForTests({ spaceId: "space-1", userId: "user-1" });
    const calls: Array<Record<string, unknown>> = [];
    withRepo({
      async addMessage(spaceId, userId, sessionId, input) {
        calls.push({ spaceId, userId, sessionId, input });
        return sessionId === "session-1"
          ? message({ role: input.role, content: input.content })
          : null;
      },
    });
    app = buildServer(sessionsConfig(), { logger: false });

    const ok = await app.inject({
      method: "POST",
      url: "/api/v1/sessions/session-1/messages",
      payload: { role: "user", content: "hi" },
    });
    const missing = await app.inject({
      method: "POST",
      url: "/api/v1/sessions/other/messages",
      payload: { role: "user", content: "hi" },
    });

    expect(ok.statusCode).toBe(201);
    expect(ok.json()).toMatchObject({ id: "message-1", role: "user", content: "hi" });
    expect(missing.statusCode).toBe(404);
    expect(calls[0]).toMatchObject({ sessionId: "session-1", input: { role: "user", content: "hi" } });
  });

  it("rejects a message with missing role or empty content (422)", async () => {
    __setSessionIdentityForTests({ spaceId: "space-1", userId: "user-1" });
    withRepo({});
    app = buildServer(sessionsConfig(), { logger: false });

    const noRole = await app.inject({
      method: "POST",
      url: "/api/v1/sessions/session-1/messages",
      payload: { content: "hi" },
    });
    const noContent = await app.inject({
      method: "POST",
      url: "/api/v1/sessions/session-1/messages",
      payload: { role: "user", content: "" },
    });

    expect(noRole.statusCode).toBe(422);
    expect(noContent.statusCode).toBe(422);
  });
});

describe("session route registration", () => {
  it("serves session routes through the registered server route", async () => {
    __setSessionIdentityForTests({ spaceId: "space-1", userId: "user-1" });
    withRepo({
      async listSessions(): Promise<SessionPage> {
        return { items: [], total: 0, limit: 50, offset: 0 };
      },
    });
    app = buildServer(sessionsConfig(), { logger: false });

    const read = await app.inject({ method: "GET", url: "/api/v1/sessions" });

    expect(read.statusCode).toBe(200);
    expect(read.json()).toEqual({ items: [], total: 0, limit: 50, offset: 0 });
  });
});
