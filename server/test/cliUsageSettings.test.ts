import { afterEach, describe, expect, it } from "vitest";
import { mkdtemp, rm } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { loadConfig } from "../src/config";
import { CliCredentialBroker } from "../src/modules/providers/cli/credentialBroker";

let tempDir: string | undefined;

afterEach(async () => {
  if (tempDir) await rm(tempDir, { recursive: true, force: true });
  tempDir = undefined;
});

describe("CLI usage auto-refresh settings", () => {
  it("defaults to enabled and persists frontend changes", async () => {
    tempDir = await mkdtemp(join(tmpdir(), "aspace-usage-settings-"));
    const broker = new CliCredentialBroker(loadConfig({ AGENT_SPACE_HOME: tempDir }));

    expect(await broker.isCliUsageAutoRefreshEnabled()).toBe(true);
    expect((await broker.cliUsageAutoRefreshSettings()).updated_at).toBeNull();

    const saved = await broker.setCliUsageAutoRefresh(false);
    expect(saved.enabled).toBe(false);
    expect(saved.updated_at).toBeTruthy();

    const brokerAfterReload = new CliCredentialBroker(loadConfig({ AGENT_SPACE_HOME: tempDir }));
    expect(await brokerAfterReload.isCliUsageAutoRefreshEnabled()).toBe(false);
  });
});
