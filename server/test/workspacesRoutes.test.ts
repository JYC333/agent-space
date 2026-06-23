import { afterEach, describe, expect, it } from "vitest";
import type { FastifyInstance } from "fastify";
import { buildServer } from "../src/server";
import { loadConfig } from "../src/config";
import {
  __setWorkspaceIdentityForTests,
  __setWorkspaceServicesFactoryForTests,
} from "../src/modules/workspaces";
import type { PgWorkspaceRepository } from "../src/modules/workspaces/repository";

let app: FastifyInstance | undefined;

afterEach(async () => {
  __setWorkspaceIdentityForTests(null);
  __setWorkspaceServicesFactoryForTests(null);
  await app?.close();
  app = undefined;
});

describe("workspace routes", () => {
  it("serves workspace and workspace-console routes from server-owned services", async () => {
    __setWorkspaceIdentityForTests({ spaceId: "space-1", userId: "user-1" });
    __setWorkspaceServicesFactoryForTests(() => ({
      repository: fakeRepository(),
      runtimes: {
        async listStatus() {
          return [{ runtime: "codex_cli", installed: false }] as never;
        },
      },
    }));
    app = buildServer(loadConfig({}), { logger: false });

    await expectJson("GET", "/api/v1/workspaces", {
      items: [{ id: "workspace-1", name: "Workspace" }],
      total: 1,
      limit: 50,
      offset: 0,
    });
    await expectJson("GET", "/api/v1/workspace-console/workspaces", {
      items: [{
        id: "workspace-1",
        name: "Workspace",
        path: "/workspace",
        type: "project",
        description: null,
      }],
    });
    await expectJson("GET", "/api/v1/workspace-console/workspaces/workspace-1/file?path=README.md", {
      path: "README.md",
      content: "hello",
      size: 5,
      line_count: 1,
    });
    await expectJson("GET", "/api/v1/workspace-console/runtimes", {
      runtimes: [{ runtime: "codex_cli", installed: false }],
    });
    const sessions = await app.inject({ method: "POST", url: "/api/v1/workspace-console/sessions" });
    expect(sessions.statusCode).toBe(501);
    expect(sessions.json()).toEqual({ detail: "workspace_console_sessions is not implemented" });
  });
});

async function expectJson(method: "GET", url: string, expected: unknown): Promise<void> {
  if (!app) throw new Error("test app not initialized");
  const response = await app.inject({ method, url });
  expect(response.statusCode).toBe(200);
  expect(response.json()).toEqual(expected);
}

function fakeRepository(): Pick<
  PgWorkspaceRepository,
  | "list"
  | "create"
  | "scan"
  | "get"
  | "update"
  | "archive"
  | "listConsoleWorkspaces"
  | "getTree"
  | "getFile"
  | "getGitStatus"
  | "getGitDiff"
> {
  return {
    async list() {
      return { items: [{ id: "workspace-1", name: "Workspace" }], total: 1, limit: 50, offset: 0 };
    },
    async create() {
      return { id: "workspace-1", name: "Workspace" };
    },
    async scan() {
      return { created: [], marked_stale: [] };
    },
    async get() {
      return { id: "workspace-1", name: "Workspace" };
    },
    async update() {
      return { id: "workspace-1", name: "Workspace" };
    },
    async archive() {
      return true;
    },
    async listConsoleWorkspaces() {
      return {
        items: [{
          id: "workspace-1",
          name: "Workspace",
          path: "/workspace",
          type: "project",
          description: null,
        }],
      };
    },
    async getTree() {
      return { name: "workspace", path: ".", type: "dir", children: [] };
    },
    async getFile(_identity: unknown, _workspaceId: unknown, requestedPath: string) {
      return { path: requestedPath, content: "hello", size: 5, line_count: 1 };
    },
    async getGitStatus() {
      return { is_repo: false, branch: null, files: [] };
    },
    async getGitDiff() {
      return { diff: "", path: null, truncated: false, redacted: false };
    },
  } as unknown as Pick<
    PgWorkspaceRepository,
    | "list"
    | "create"
    | "scan"
    | "get"
    | "update"
    | "archive"
    | "listConsoleWorkspaces"
    | "getTree"
    | "getFile"
    | "getGitStatus"
    | "getGitDiff"
  >;
}
