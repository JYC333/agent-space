import { chmod, mkdir, mkdtemp, rm, symlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { loadConfig } from "../src/config";
import {
  RuntimeToolError,
  RuntimeToolRegistry,
  type RuntimeToolInstallRunner,
} from "../src/modules/runtimeTools";

const tmpPaths: string[] = [];

afterEach(async () => {
  for (const path of tmpPaths.splice(0)) {
    await rm(path, { recursive: true, force: true });
  }
});

async function tempConfig() {
  const root = await mkdtemp(join(tmpdir(), "aspace-runtime-tools-"));
  tmpPaths.push(root);
  return loadConfig({
    AGENT_SPACE_HOME: root,
    RUNTIME_TOOLS_ROOT: join(root, "runtime-tools"),
  });
}

class FakeInstaller implements RuntimeToolInstallRunner {
  calls: Array<{ package_ref: string; prefix: string; cache_dir: string }> = [];

  async run(input: { package_ref: string; prefix: string; cache_dir: string }): Promise<void> {
    this.calls.push(input);
    const isClaude = input.package_ref.startsWith("@anthropic-ai/claude-code@");
    const packageDir = isClaude
      ? join(input.prefix, "node_modules", "@anthropic-ai", "claude-code")
      : join(input.prefix, "node_modules", "@openai", "codex");
    const binName = isClaude ? "claude" : "codex";
    await mkdir(packageDir, { recursive: true });
    if (!isClaude) {
      await mkdir(join(input.prefix, "node_modules", "@openai", "codex-linux-x64"), { recursive: true });
    }
    await mkdir(join(input.prefix, "node_modules", ".bin"), { recursive: true });
    await writeFile(join(packageDir, "package.json"), JSON.stringify({ version: "1.2.3" }));
    const bin = join(input.prefix, "node_modules", ".bin", binName);
    await writeFile(bin, "#!/bin/sh\nexit 0\n");
    await chmod(bin, 0o755);
  }
}

describe("RuntimeToolRegistry", () => {
  it("installs an allowlisted npm CLI into the instance runtime-tools root and resolves active executable", async () => {
    const cfg = await tempConfig();
    const installer = new FakeInstaller();
    const registry = new RuntimeToolRegistry(cfg, installer);

    const result = await registry.install("claude_code", { version: "latest" });
    expect(result).toMatchObject({
      runtime: "claude_code",
      installed: true,
      installed_version: "1.2.3",
      activated: true,
      active_version: "1.2.3",
    });
    expect(installer.calls[0].package_ref).toBe("@anthropic-ai/claude-code@latest");
    expect(installer.calls[0].cache_dir).toBe(join(cfg.agentSpaceHome, "cache", "npm"));

    const resolved = await registry.resolveForExecution("claude_code");
    expect(resolved).toMatchObject({
      runtime: "claude_code",
      executable_path: join(
        cfg.cliToolsRoot,
        "claude_code",
        "versions",
        "1.2.3",
        "node_modules",
        ".bin",
        "claude",
      ),
      version: "1.2.3",
      source: "npm",
    });
  });

  it("rejects non-allowlisted runtimes and invalid version refs", async () => {
    const registry = new RuntimeToolRegistry(await tempConfig(), new FakeInstaller());
    await expect(registry.install("random_cli", { version: "latest" })).rejects.toBeInstanceOf(
      RuntimeToolError,
    );
    await expect(registry.install("codex_cli", { version: "../../../bad" })).rejects.toMatchObject({
      code: "invalid_runtime_tool_version",
    });
  });

  it("does not resolve an active symlink outside the managed versions root", async () => {
    const cfg = await tempConfig();
    const runtimeRoot = join(cfg.cliToolsRoot, "claude_code");
    await mkdir(runtimeRoot, { recursive: true });
    await symlink("../../escape", join(runtimeRoot, "active"));

    const status = await new RuntimeToolRegistry(cfg, new FakeInstaller()).status("claude_code");
    expect(status.installed).toBe(false);
    expect(status.active_version).toBeNull();
    expect(status.executable_path).toBeNull();
    expect(status.warnings).toContain("active symlink target is invalid");
  });

  it("marks codex_cli unavailable when the native optional package is missing", async () => {
    const cfg = await tempConfig();
    const versionRoot = join(cfg.cliToolsRoot, "codex_cli", "versions", "1.2.3");
    const packageDir = join(versionRoot, "node_modules", "@openai", "codex");
    await mkdir(packageDir, { recursive: true });
    await mkdir(join(versionRoot, "node_modules", ".bin"), { recursive: true });
    await writeFile(join(packageDir, "package.json"), JSON.stringify({ version: "1.2.3" }));
    const bin = join(versionRoot, "node_modules", ".bin", "codex");
    await writeFile(bin, "#!/bin/sh\nexit 0\n");
    await chmod(bin, 0o755);
    await symlink("versions/1.2.3", join(cfg.cliToolsRoot, "codex_cli", "active"));

    const status = await new RuntimeToolRegistry(cfg, new FakeInstaller()).status("codex_cli");
    expect(status.installed).toBe(false);
    expect(status.executable_exists).toBe(false);
    expect(status.warnings).toContain("@openai/codex-linux-x64 is missing; reinstall the Codex runtime tool.");
  });
});
