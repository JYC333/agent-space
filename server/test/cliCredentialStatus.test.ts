import { mkdtemp, mkdir, rm, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { afterEach, describe, expect, it, vi } from "vitest";
import { loadConfig } from "../src/config";
import { getDbPool } from "../src/db/pool";
import { CliCredentialBroker } from "../src/modules/providers/cliCredentialBroker";

vi.mock("../src/db/pool", () => ({
  getDbPool: vi.fn(),
}));

let tempDir: string | undefined;

afterEach(async () => {
  vi.clearAllMocks();
  if (tempDir) await rm(tempDir, { recursive: true, force: true });
  tempDir = undefined;
});

describe("CLI credential login-state detection", () => {
  it("uses the runtime credential file rather than directory non-emptiness", async () => {
    tempDir = await mkdtemp(join(tmpdir(), "aspace-cli-state-"));
    const cacheOnlyPath = join(tempDir, "codex-cache-only");
    const loggedInPath = join(tempDir, "codex-logged-in");
    await mkdir(join(cacheOnlyPath, "log"), { recursive: true });
    await writeFile(join(cacheOnlyPath, "config.toml"), "model = \"gpt-5\"\n");
    await writeFile(join(cacheOnlyPath, "log", "codex-login.log"), "not a token\n");
    await mkdir(loggedInPath, { recursive: true });
    await writeFile(join(loggedInPath, "auth.json"), "{\"token\":\"present\"}\n");

    const rows = [
      {
        id: "profile-cache-only",
        owner_user_id: "user-1",
        runtime: "codex_cli",
        name: "cache-only",
        source_path: cacheOnlyPath,
        target_path: "/home/agent/.codex",
        readonly: false,
        notes: "",
        grant_id: "grant-cache-only",
        grant_enabled: true,
        is_default: true,
        network_profile_id: null,
        manageable: true,
      },
      {
        id: "profile-logged-in",
        owner_user_id: "user-1",
        runtime: "codex_cli",
        name: "logged-in",
        source_path: loggedInPath,
        target_path: "/home/agent/.codex",
        readonly: false,
        notes: "",
        grant_id: "grant-logged-in",
        grant_enabled: true,
        is_default: false,
        network_profile_id: null,
        manageable: true,
      },
    ];
    const query = vi.fn(async (sql: string, params: readonly unknown[] = []) => {
      if (sql.includes("FROM cli_credential_space_grants") && sql.includes("JOIN cli_credential_profiles")) {
        const profileId = params[2];
        return {
          rows: profileId ? rows.filter(row => row.id === profileId) : rows,
          rowCount: profileId ? rows.filter(row => row.id === profileId).length : rows.length,
        };
      }
      return { rows: [], rowCount: 0 };
    });
    vi.mocked(getDbPool).mockReturnValue({ query } as never);

    const broker = new CliCredentialBroker(
      loadConfig({
        AGENT_SPACE_HOME: tempDir,
        SERVER_DATABASE_URL: "postgresql://server@db:5432/agent_space",
      }),
    );

    const available = await broker.availableProfiles("space-1", "user-1", "codex_cli");
    expect(available.find(row => row.id === "profile-cache-only")).toMatchObject({
      file_count: 2,
      logged_in: false,
    });
    expect(available.find(row => row.id === "profile-logged-in")).toMatchObject({
      logged_in: true,
    });

    const status = await broker.status("space-1", "user-1");
    expect(status.find(row => row.runtime === "codex_cli")).toMatchObject({
      profile_id: "profile-logged-in",
      logged_in: true,
    });

    await expect(
      broker.resolveProfile("codex_cli", "profile-cache-only", true, "space-1", "user-1"),
    ).resolves.toBeNull();
    await expect(
      broker.resolveProfile("codex_cli", "profile-logged-in", true, "space-1", "user-1"),
    ).resolves.toMatchObject({ id: "profile-logged-in" });
  });
});
