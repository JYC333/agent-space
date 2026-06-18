import type { FastifyInstance } from "fastify";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { loadConfig } from "../src/config";
import { getDbPool } from "../src/db/pool";
import { buildServer } from "../src/server";
import { __setAgentChatIdentityForTests } from "../src/modules/agents";

vi.mock("../src/db/pool", () => ({
  getDbPool: vi.fn(),
}));

let app: FastifyInstance | undefined;

beforeEach(() => {
  vi.clearAllMocks();
  __setAgentChatIdentityForTests({ spaceId: "space-1", userId: "user-1" });
});

afterEach(async () => {
  __setAgentChatIdentityForTests(null);
  await app?.close();
  app = undefined;
});

function config() {
  return loadConfig({
    SERVER_DATABASE_URL: "postgresql://server@db:5432/agent_space",
    SERVER_INTERNAL_TOKEN: "internal-token",
  });
}

describe("agents CRUD routes", () => {
  it("lists agents with the public response shape", async () => {
    const query = vi.fn(async () => ({ rows: [], rowCount: 0 }));
    vi.mocked(getDbPool).mockReturnValue({ query } as never);
    app = buildServer(config(), { logger: false });

    const res = await app.inject({
      method: "GET",
      url: "/api/v1/agents?status=active,disabled,inactive",
    });

    expect(res.statusCode).toBe(200);
    expect(res.json()).toEqual([]);
  });

  it("creates an agent and returns its initial immutable version", async () => {
    let agentId = "";
    let versionId = "";
    const client = {
      query: vi.fn(async (sql: string, params: readonly unknown[] = []) => {
        if (sql.startsWith("INSERT INTO agents")) {
          agentId = String(params[0]);
          return { rows: [], rowCount: 1 };
        }
        if (sql.startsWith("INSERT INTO agent_versions")) {
          versionId = String(params[0]);
          return { rows: [{ id: versionId }], rowCount: 1 };
        }
        if (sql.includes("FROM agents a")) {
          return {
            rows: [
              {
                id: agentId,
                space_id: "space-1",
                owner_user_id: "user-1",
                name: "API Agent",
                description: "Uses Model API",
                role_instruction: null,
                status: "active",
                agent_kind: "standard",
                source_template_id: null,
                source_template_version_id: null,
                current_version_id: versionId,
                visibility: "private",
                created_at: "2026-06-17T00:00:00.000Z",
                updated_at: "2026-06-17T00:00:00.000Z",
                model_provider_id: null,
                provider_name: null,
                provider_type: null,
                model_name: null,
                system_prompt: "Act carefully.",
                runtime_policy_json: { default_adapter_type: "capability" },
              },
            ],
            rowCount: 1,
          };
        }
        return { rows: [], rowCount: 0 };
      }),
      release: vi.fn(),
    };
    const pool = {
      connect: vi.fn(async () => client),
      query: vi.fn(),
    };
    vi.mocked(getDbPool).mockReturnValue(pool as never);
    app = buildServer(config(), { logger: false });

    const res = await app.inject({
      method: "POST",
      url: "/api/v1/agents",
      payload: {
        name: "API Agent",
        description: "Uses Model API",
        system_prompt: "Act carefully.",
        adapter_type: "capability",
        default_model_provider_id: null,
        default_model: null,
      },
    });

    expect(res.statusCode).toBe(201);
    expect(res.json()).toMatchObject({
      id: agentId,
      space_id: "space-1",
      created_by_user_id: "user-1",
      name: "API Agent",
      adapter_type: "capability",
      current_version_id: versionId,
    });
  });
});
