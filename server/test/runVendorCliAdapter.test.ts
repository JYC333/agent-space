import { mkdir, mkdtemp, readFile, rm, symlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { loadConfig } from "../src/config";
import {
  buildSubprocessEnv,
  DockerCliCommandExecutor,
  executeVendorCliAdapter,
  parseOpenCodeOutput,
  type CliCommandExecutor,
  type CliCredentialBrokerPort,
  type CliExecutionResult,
} from "../src/modules/runs/vendorCliAdapter";
import { ProviderProxyLeaseRegistry } from "../src/modules/providers/proxy/lease";
import type { RuntimeToolResolverPort } from "../src/modules/runtimeTools";
import type { RunRecord } from "../src/modules/runs/repository";

const tmpPaths: string[] = [];

afterEach(async () => {
  for (const path of tmpPaths.splice(0)) {
    await rm(path, { recursive: true, force: true });
  }
});

function config() {
  return loadConfig({
    SERVER_DATABASE_URL: "postgresql://server@db:5432/agent_space",
    SERVER_INTERNAL_TOKEN: "internal-token",
  });
}

function run(overrides: Partial<RunRecord> = {}): RunRecord {
  return {
    id: "run-1",
    space_id: "space-1",
    agent_id: "agent-1",
    agent_version_id: "agent-version-1",
    status: "running",
    mode: "headless",
    prompt: "Fix the bug",
    instruction: null,
    workspace_id: "workspace-1",
    session_id: null,
    project_id: null,
    adapter_type: "codex_cli",
    model_provider_id: null,
    required_sandbox_level: "worktree",
    trigger_origin: "manual",
    started_at: null,
    ended_at: null,
    ...overrides,
  };
}

class FakeBroker implements CliCredentialBrokerPort {
  grants: Array<{
    runId: string;
    spaceId: string;
    runtime: string;
    executorMode: string;
    profileId?: string | null;
  }> = [];
  cleanups: string[] = [];
  granted = true;

  async grantForRun(
    runId: string,
    spaceId: string,
    runtime: string,
    executorMode: "worktree" | "docker",
    profileId?: string | null,
  ) {
    this.grants.push({ runId, spaceId, runtime, executorMode, profileId });
    const env: Record<string, string> = this.granted
      ? {
          HOME: `/tmp/runtime-home/${runId}`,
          SHOULD_NOT_PASS: "no",
        }
      : {};
    return {
      granted: this.granted,
      profile_id: this.granted ? profileId ?? "default-profile-id" : null,
      runtime,
      executor_mode: executorMode,
      readonly: false,
      temp_home: this.granted ? `/tmp/runtime-home/${runId}` : null,
      host_source_path: null,
      target_path: null,
      env,
      network_profile_id: null,
      fallback_reason: this.granted ? null : "no_profile_configured",
    };
  }

  async cleanupRunHome(runId: string): Promise<void> {
    this.cleanups.push(runId);
  }
}

class TempCodexBroker extends FakeBroker {
  tempHome: string | null = null;
  profileDir: string | null = null;

  async grantForRun(
    runId: string,
    spaceId: string,
    runtime: string,
    executorMode: "worktree" | "docker",
    profileId?: string | null,
  ) {
    this.grants.push({ runId, spaceId, runtime, executorMode, profileId });
    const root = await mkdtemp(join(tmpdir(), "aspace-runtime-home-"));
    tmpPaths.push(root);
    this.tempHome = join(root, "home");
    this.profileDir = join(root, "profile");
    await mkdir(this.tempHome, { recursive: true });
    await mkdir(this.profileDir, { recursive: true });
    await writeFile(join(this.profileDir, "auth.json"), "{\"token\":\"login-state\"}", "utf8");
    await symlink(this.profileDir, join(this.tempHome, ".codex"));
    return {
      granted: true,
      profile_id: profileId ?? "default-profile-id",
      runtime,
      executor_mode: executorMode,
      readonly: false,
      temp_home: this.tempHome,
      host_source_path: null,
      target_path: null,
      env: { HOME: this.tempHome },
      network_profile_id: null,
      fallback_reason: null,
    };
  }
}

class FakeExecutor implements CliCommandExecutor {
  calls: Array<{
    command: string[];
    cwd: string | null;
    timeout_seconds: number;
    env: Record<string, string>;
    run_id: string;
    stdin: string | null;
    docker?: {
      image: string;
      sandbox_cwd: string;
      cli_tools_root: string;
      credential_source_path: string | null;
      credential_target_path: string | null;
    };
  }> = [];
  result: CliExecutionResult = {
    returncode: 0,
    stdout: "cli output",
    stderr: "",
    timed_out: false,
  };

  async runCommand(input: {
    command: string[];
    cwd: string | null;
    timeout_seconds: number;
    env: Record<string, string>;
    run_id: string;
    stdin: string | null;
    docker?: {
      image: string;
      sandbox_cwd: string;
      cli_tools_root: string;
      credential_source_path: string | null;
      credential_target_path: string | null;
    };
  }): Promise<CliExecutionResult> {
    this.calls.push(input);
    return this.result;
  }
}

class FakeTools implements RuntimeToolResolverPort {
  async resolveForExecution(runtime: string) {
    return {
      runtime,
      executable_path: process.execPath,
      version: "test-version",
      source: "npm" as const,
      package_name: runtime === "claude_code" ? "@anthropic-ai/claude-code" : "@openai/codex",
    };
  }
}

describe("executeVendorCliAdapter", () => {
  it("runs codex_cli with credential grant, safe env, redacted command log, and AGENserver context", async () => {
    const sandbox = await mkdtemp(join(tmpdir(), "aspace-cli-"));
    tmpPaths.push(sandbox);
    const broker = new FakeBroker();
    const executor = new FakeExecutor();

    const result = await executeVendorCliAdapter(
      config(),
      {
        run: run(),
        sandbox_cwd: sandbox,
        context_text: "Repo instructions",
        adapter_config: {
          credential_profile_id: "11111111-1111-4111-8111-111111111111",
          timeout: 120,
        },
      },
      { credentialBroker: broker, executor, toolRegistry: new FakeTools() },
    );

    expect(await readFile(join(sandbox, "AGENTS.md"), "utf8")).toBe("Repo instructions");
    expect(broker.grants).toEqual([
      {
        runId: "run-1",
        spaceId: "space-1",
        runtime: "codex_cli",
        executorMode: "worktree",
        profileId: "11111111-1111-4111-8111-111111111111",
      },
    ]);
    expect(broker.cleanups).toEqual(["run-1"]);
    expect(executor.calls[0]).toMatchObject({
      command: [
        process.execPath,
        "--ask-for-approval",
        "never",
        "exec",
        "--skip-git-repo-check",
        "--sandbox",
        "workspace-write",
        "Fix the bug",
      ],
      cwd: sandbox,
      timeout_seconds: 120,
      run_id: "run-1",
      stdin: null,
    });
    expect(executor.calls[0].env.OPENAI_API_KEY).toBeUndefined();
    expect(executor.calls[0].env.CODEX_HOME).toBe("/tmp/runtime-home/run-1/.codex");
    expect(executor.calls[0].env.SHOULD_NOT_PASS).toBeUndefined();
    expect(result).toMatchObject({
      adapter_type: "codex_cli",
      adapter_kind: "local_cli",
      success: true,
      output_text: "cli output",
      error_code: null,
      metadata_json: {
        credential_profile_id: "11111111-1111-4111-8111-111111111111",
        context_file_type: "AGENTS.md",
        rendered_in_sandbox: true,
      },
      adapter_log_json: {
        command: [
          process.execPath,
          "--ask-for-approval",
          "never",
          "exec",
          "--skip-git-repo-check",
          "--sandbox",
          "workspace-write",
          "[REDACTED_PROMPT]",
        ],
        timeout_seconds: 120,
      },
    });
  });

  it("runs an ephemeral (no-workspace) CLI in the prepared working dir", async () => {
    const sandbox = await mkdtemp(join(tmpdir(), "aspace-cli-eph-"));
    tmpPaths.push(sandbox);
    const broker = new FakeBroker();
    const executor = new FakeExecutor();

    const result = await executeVendorCliAdapter(
      config(),
      {
        run: run({ required_sandbox_level: "ephemeral", workspace_id: null }),
        sandbox_cwd: sandbox,
        context_text: "Daily organize",
        adapter_config: { credential_profile_id: "11111111-1111-4111-8111-111111111111", timeout: 60 },
      },
      { credentialBroker: broker, executor, toolRegistry: new FakeTools() },
    );

    expect(result).toMatchObject({
      adapter_type: "codex_cli",
      success: true,
      error_code: null,
    });
    expect(executor.calls[0]).toMatchObject({ cwd: sandbox, run_id: "run-1" });
    expect(await readFile(join(sandbox, "AGENTS.md"), "utf8")).toBe("Daily organize");
  });

  it("writes run-scoped Codex provider config for an OpenAI-compatible provider", async () => {
    const sandbox = await mkdtemp(join(tmpdir(), "aspace-cli-codex-provider-"));
    tmpPaths.push(sandbox);
    const broker = new TempCodexBroker();
    const executor = new FakeExecutor();
    const leases = new ProviderProxyLeaseRegistry();

    const result = await executeVendorCliAdapter(
      config(),
      {
        run: run({
          model_provider_id: "provider-openai",
        }),
        sandbox_cwd: sandbox,
        context_text: "Codex instructions",
        adapter_config: { credential_profile_id: "11111111-1111-4111-8111-111111111111" },
      },
      {
        credentialBroker: broker,
        executor,
        toolRegistry: new FakeTools(),
        providerLeaseRegistry: leases,
        providerProxyBaseUrl: "http://127.0.0.1:49152",
        providerResolver: {
          async getProvider(_spaceId, providerId) {
            return {
              id: providerId,
              space_id: "space-1",
              name: "MiniMax",
              provider_type: "other",
              base_url: "https://api.minimaxi.com/anthropic",
              openai_compatible_base_url: "https://api.minimaxi.com/v1",
              claude_compatible_base_url: "https://api.minimaxi.com/anthropic",
              default_model: "MiniMax-M3",
              available_models: ["MiniMax-M3", "MiniMax-M2.7"],
              enabled: true,
              is_default: false,
            };
          },
        },
      },
    );

    expect(result.success).toBe(true);
    expect(broker.tempHome).toBeTruthy();
    expect(executor.calls[0].env.HOME).toBe(broker.tempHome);
    expect(executor.calls[0].env.CODEX_HOME).toBe(join(broker.tempHome!, ".codex"));
    expect(executor.calls[0].env.OPENAI_API_KEY).toBeUndefined();
    expect(executor.calls[0].env.ANTHROPIC_AUTH_TOKEN).toBeUndefined();

    const codexDir = executor.calls[0].env.CODEX_HOME;
    const configToml = await readFile(join(codexDir, "config.toml"), "utf8");
    expect(executor.calls[0].command).toEqual([
      process.execPath,
      "--ask-for-approval",
      "never",
      "exec",
      "--skip-git-repo-check",
      "--sandbox",
      "workspace-write",
      "Fix the bug",
    ]);
    expect(configToml).toContain('model = "MiniMax-M3"');
    expect(configToml).toContain('model_provider = "agent_space_provider"');
    expect(configToml).toContain(
      `model_catalog_json = "${join(codexDir, "model-catalogs", "agent-space-provider.json")}"`,
    );
    expect(configToml).toContain('base_url = "http://127.0.0.1:49152/openai/');
    expect(configToml).toContain('wire_api = "responses"');
    expect(configToml).toContain('experimental_bearer_token = "');
    expect(configToml).not.toContain("provider-secret");
    await expect(readFile(join(codexDir, "auth.json"), "utf8")).resolves.toContain("login-state");
    const catalog = JSON.parse(
      await readFile(join(codexDir, "model-catalogs", "agent-space-provider.json"), "utf8"),
    ) as {
      models: Array<{
        slug: string;
        default_reasoning_level: string;
        supported_reasoning_levels: Array<{ effort: string; description: string }>;
        base_instructions: string;
        supports_reasoning_summaries: boolean;
        truncation_policy: { mode: string; limit: number };
      }>;
    };
    expect(catalog.models.map((model) => model.slug)).toEqual(["MiniMax-M3", "MiniMax-M2.7"]);
    expect(catalog.models[0]).toMatchObject({
      default_reasoning_level: "none",
      supported_reasoning_levels: [{ effort: "none", description: "Reasoning off" }],
      supports_reasoning_summaries: false,
      truncation_policy: { mode: "bytes", limit: 10000 },
    });
    expect(catalog.models[0].base_instructions).toContain("using MiniMax-M3 through MiniMax");
    expect(leases.size()).toBe(0);
    expect(result.metadata_json).toMatchObject({
      runtime_provider_id: "provider-openai",
      runtime_provider_model: "MiniMax-M3",
      runtime_provider_protocol: "openai_responses",
      runtime_provider_proxy: true,
    });
  });

  it("injects Claude-compatible provider env only for a configured claude_code provider", async () => {
    const sandbox = await mkdtemp(join(tmpdir(), "aspace-cli-claude-"));
    tmpPaths.push(sandbox);
    const executor = new FakeExecutor();
    const leases = new ProviderProxyLeaseRegistry();

    const result = await executeVendorCliAdapter(
      config(),
      {
        run: run({
          adapter_type: "claude_code",
          model_provider_id: "provider-claude",
          model_override_json: { model: "MiniMax-M2.7", source: "agent_default" },
        }),
        sandbox_cwd: sandbox,
        context_text: "Claude instructions",
        adapter_config: { credential_profile_id: "22222222-2222-4222-8222-222222222222" },
      },
      {
        credentialBroker: new FakeBroker(),
        executor,
        toolRegistry: new FakeTools(),
        providerLeaseRegistry: leases,
        providerProxyBaseUrl: "http://127.0.0.1:49152",
        providerResolver: {
          async getProvider(_spaceId, providerId) {
            return {
              id: providerId,
              space_id: "space-1",
              name: "MiniMax",
              provider_type: "other",
              base_url: "https://api.minimaxi.com/v1",
              openai_compatible_base_url: null,
              claude_compatible_base_url: "https://api.minimaxi.com/anthropic",
              default_model: "MiniMax-M2.7",
              available_models: ["MiniMax-M2.7"],
              enabled: true,
              is_default: false,
            };
          },
        },
      },
    );

    expect(result.success).toBe(true);
    expect(executor.calls[0].env.ANTHROPIC_BASE_URL).toMatch(
      /^http:\/\/127\.0\.0\.1:49152\/anthropic\/[-0-9a-f]+$/,
    );
    expect(executor.calls[0].env.ANTHROPIC_AUTH_TOKEN).toMatch(/^[A-Za-z0-9_-]+$/);
    expect(executor.calls[0].env).toMatchObject({
      ANTHROPIC_MODEL: "MiniMax-M2.7",
      ANTHROPIC_DEFAULT_SONNET_MODEL: "MiniMax-M2.7",
      ANTHROPIC_DEFAULT_OPUS_MODEL: "MiniMax-M2.7",
      ANTHROPIC_DEFAULT_HAIKU_MODEL: "MiniMax-M2.7",
    });
    expect(leases.size()).toBe(0);
    expect(result.metadata_json).toMatchObject({
      claude_compatible_provider_id: "provider-claude",
      claude_compatible_model: "MiniMax-M2.7",
      claude_compatible_provider_proxy: true,
    });
  });

  it("fails closed when a selected Claude provider has no compatible URL", async () => {
    const sandbox = await mkdtemp(join(tmpdir(), "aspace-cli-claude-missing-"));
    tmpPaths.push(sandbox);
    const executor = new FakeExecutor();

    const result = await executeVendorCliAdapter(
      config(),
      {
        run: run({ adapter_type: "claude_code", model_provider_id: "provider-plain" }),
        sandbox_cwd: sandbox,
        adapter_config: { credential_profile_id: "22222222-2222-4222-8222-222222222222" },
      },
      {
        credentialBroker: new FakeBroker(),
        executor,
        toolRegistry: new FakeTools(),
        providerResolver: {
          async getProvider(_spaceId, providerId) {
            return {
              id: providerId,
              space_id: "space-1",
              name: "Plain",
              provider_type: "anthropic",
              base_url: "https://api.anthropic.com",
              openai_compatible_base_url: null,
              claude_compatible_base_url: null,
              default_model: "claude-sonnet-4-6",
              available_models: ["claude-sonnet-4-6"],
              enabled: true,
              is_default: false,
            };
          },
        },
      },
    );

    expect(result).toMatchObject({
      success: false,
      error_code: "claude_compatible_base_url_required",
    });
    expect(executor.calls).toHaveLength(0);
  });

  it("fails closed when a selected Codex provider has no OpenAI-compatible URL", async () => {
    const sandbox = await mkdtemp(join(tmpdir(), "aspace-cli-codex-missing-"));
    tmpPaths.push(sandbox);
    const executor = new FakeExecutor();

    const result = await executeVendorCliAdapter(
      config(),
      {
        run: run({ adapter_type: "codex_cli", model_provider_id: "provider-plain" }),
        sandbox_cwd: sandbox,
        adapter_config: { credential_profile_id: "11111111-1111-4111-8111-111111111111" },
      },
      {
        credentialBroker: new FakeBroker(),
        executor,
        toolRegistry: new FakeTools(),
        providerResolver: {
          async getProvider(_spaceId, providerId) {
            return {
              id: providerId,
              space_id: "space-1",
              name: "Plain",
              provider_type: "openai",
              base_url: "https://api.example.test/v1",
              openai_compatible_base_url: null,
              claude_compatible_base_url: null,
              default_model: "example-model",
              available_models: ["example-model"],
              enabled: true,
              is_default: false,
            };
          },
        },
      },
    );

    expect(result).toMatchObject({
      success: false,
      error_code: "openai_compatible_base_url_required",
    });
    expect(executor.calls).toHaveLength(0);
  });

  it("fails closed for an ephemeral CLI without a prepared working dir", async () => {
    const broker = new FakeBroker();
    const executor = new FakeExecutor();

    const result = await executeVendorCliAdapter(
      config(),
      {
        run: run({ required_sandbox_level: "ephemeral", workspace_id: null }),
        sandbox_cwd: null,
        adapter_config: { credential_profile_id: "11111111-1111-4111-8111-111111111111" },
      },
      { credentialBroker: broker, executor, toolRegistry: new FakeTools() },
    );

    expect(result).toMatchObject({
      success: false,
      error_code: "workspace_prepare_failed",
    });
    expect(executor.calls).toEqual([]);
    expect(broker.grants).toEqual([]);
  });

  it("renders claude_code model and permission-bypass args only when policy allows", async () => {
    const sandbox = await mkdtemp(join(tmpdir(), "aspace-claude-"));
    tmpPaths.push(sandbox);
    const broker = new FakeBroker();
    const executor = new FakeExecutor();

    const result = await executeVendorCliAdapter(
      config(),
      {
        run: run({ adapter_type: "claude_code" }),
        sandbox_cwd: sandbox,
        model: "claude-sonnet",
        risk_level: "high",
      adapter_config: {
          permission_bypass: true,
          runtime_policy_json: { allow_permission_bypass: true },
        },
      },
      { credentialBroker: broker, executor, toolRegistry: new FakeTools() },
    );

    expect(executor.calls[0].command).toEqual([
      process.execPath,
      "--print",
      "--model",
      "claude-sonnet",
      "--dangerously-skip-permissions",
      "Fix the bug",
    ]);
    expect(result.metadata_json).toMatchObject({
      adapter_type: "claude_code",
      permission_bypass_requested: true,
      permission_bypass_used: true,
      context_file_type: "CLAUDE.md",
    });
    const claudeSettings = JSON.parse(await readFile(join(sandbox, ".claude", "settings.json"), "utf8")) as {
      permissions?: { deny?: string[] };
    };
    expect(claudeSettings.permissions?.deny).toContain("Task");
  });

  it("fails closed when the credential profile is missing", async () => {
    const broker = new FakeBroker();
    broker.granted = false;
    const executor = new FakeExecutor();

    const result = await executeVendorCliAdapter(
      config(),
      {
        run: run(),
        sandbox_cwd: "/tmp/worktree",
        adapter_config: { credential_profile_id: "33333333-3333-4333-8333-333333333333" },
      },
      { credentialBroker: broker, executor },
    );

    expect(executor.calls).toEqual([]);
    expect(result).toMatchObject({
      success: false,
      error_code: "runtime_credential_profile_required",
      metadata_json: {
        fallback_reason: "no_profile_configured",
      },
    });
  });

  it("uses the isolated Docker executor for critical CLI runs", async () => {
    const broker = new FakeBroker();
    const executor = new FakeExecutor();

    await expect(
      executeVendorCliAdapter(
        config(),
        { run: run({ required_sandbox_level: "none" }), sandbox_cwd: "/tmp/worktree" },
        { credentialBroker: broker, executor },
      ),
    ).resolves.toMatchObject({
      success: false,
      error_code: "file_access_adapter_requires_worktree_policy",
    });

    const sandbox = await mkdtemp(join(tmpdir(), "aspace-docker-") );
    tmpPaths.push(sandbox);
    const result = await executeVendorCliAdapter(
      config(),
      { run: run({ required_sandbox_level: "one_shot_docker" }), sandbox_cwd: sandbox },
      { credentialBroker: broker, executor, toolRegistry: new FakeTools() },
    );
    expect(result).toMatchObject({ success: true });
    expect(broker.grants[0]?.executorMode).toBe("docker");
    expect(executor.calls[0]?.docker).toMatchObject({
      image: "agent-space-sandbox",
      sandbox_cwd: sandbox,
      cli_tools_root: "/aspace/runtime-tools",
    });
  });

  it("assembles a fail-closed Docker command with read-only credentials and resource limits", async () => {
    const launcher = new FakeExecutor();
    const executor = new DockerCliCommandExecutor(launcher);
    await executor.runCommand({
      command: ["/tmp/aspace/runtime-tools/codex_cli/versions/v1/bin/codex", "--dir", "/tmp/aspace/sandboxes/run-1"],
      cwd: "/tmp/aspace/sandboxes/run-1",
      timeout_seconds: 30,
      env: { PATH: "/usr/bin", HOME: "/host/home", ANTHROPIC_AUTH_TOKEN: "must-not-enter" },
      run_id: "run-1",
      stdin: null,
      docker: {
        image: "agent-space-sandbox",
        sandbox_cwd: "/tmp/aspace/sandboxes/run-1",
        sandbox_root: "/tmp/aspace/sandboxes",
        cli_tools_root: "/tmp/aspace/runtime-tools",
        credential_root: "/tmp/aspace/secrets",
        credential_source_path: "/tmp/aspace/secrets/codex",
        credential_target_path: "/home/agent/.codex",
      },
    });
    const command = launcher.calls[0]?.command ?? [];
    expect(command).toContain("--network");
    expect(command).toContain("none");
    expect(command).toContain("--read-only");
    expect(command).toContain("--cap-drop");
    expect(command).toContain("ALL");
    expect(command).toContain("--pids-limit");
    expect(command).toContain("256");
    expect(command).toContain("--volume");
    expect(command).toContain("/tmp/aspace/secrets/codex:/home/sandbox/.codex:ro");
    expect(command).not.toContain("must-not-enter");
  });

  it("runs OpenCode with a sandbox config that denies Task and locks tools", async () => {
    const sandbox = await mkdtemp(join(tmpdir(), "aspace-opencode-"));
    tmpPaths.push(sandbox);
    const broker = new FakeBroker();
    const executor = new FakeExecutor();
    executor.result.stdout = '{"type":"text","text":"structured answer"}\n{"part":{"text":"more"}}';
    const result = await executeVendorCliAdapter(
      config(),
      { run: run({ adapter_type: "opencode" }), sandbox_cwd: sandbox, model: "provider/model" },
      { credentialBroker: broker, executor, toolRegistry: new FakeTools() },
    );
    expect(result).toMatchObject({
      success: true,
      adapter_type: "opencode",
      output_text: "structured answer\nmore",
      output_json: { format: "opencode_jsonl" },
    });
    expect(executor.calls[0]?.command).toEqual([
      process.execPath,
      "run",
      "--format",
      "json",
      "--agent",
      "agent-space-locked",
      "--dir",
      sandbox,
      "--model",
      "provider/model",
      "Fix the bug",
    ]);
    const configJson = JSON.parse(await readFile(join(sandbox, "opencode.json"), "utf8")) as Record<string, unknown>;
    expect(configJson).toMatchObject({
      agent: {
        "agent-space-locked": {
          permission: {
            task: { "*": "deny" },
            edit: { "*": "allow" },
            bash: { "*": "allow" },
            webfetch: "deny",
          },
        },
      },
    });
  });

  it("falls back to stdout when an OpenCode stream contains no JSON events", () => {
    expect(parseOpenCodeOutput("plain output")).toEqual({ text: "plain output", output_json: null, event_count: 0 });
  });

  it("maps nonzero and timeout results to CLI adapter failures", async () => {
    const sandbox = await mkdtemp(join(tmpdir(), "aspace-cli-failure-"));
    tmpPaths.push(sandbox);
    const broker = new FakeBroker();
    const executor = new FakeExecutor();
    executor.result = {
      returncode: 7,
      stdout: "",
      stderr: "token=secret failed",
      timed_out: false,
    };

    const failed = await executeVendorCliAdapter(
      config(),
      {
        run: run(),
        sandbox_cwd: sandbox,
      },
      { credentialBroker: broker, executor, toolRegistry: new FakeTools() },
    );

    expect(failed).toMatchObject({
      success: false,
      error_code: "cli_adapter_nonzero_exit",
      error_message: "[REDACTED_SECRET] failed",
      exit_code: 7,
    });

    executor.result = {
      returncode: -1,
      stdout: "",
      stderr: "too slow",
      timed_out: true,
    };
    const timedOut = await executeVendorCliAdapter(
      config(),
      {
        run: run(),
        sandbox_cwd: sandbox,
      },
      { credentialBroker: broker, executor, toolRegistry: new FakeTools() },
    );

    expect(timedOut).toMatchObject({
      success: false,
      error_code: "cli_adapter_timeout",
      exit_code: -1,
    });
  });
});

describe("buildSubprocessEnv", () => {
  it("keeps only safe ambient variables and broker injected HOME", () => {
    process.env.ASPACE_SHOULD_NOT_LEAK = "secret";
    process.env.LC_TEST_VALUE = "ok";

    const env = buildSubprocessEnv({
      HOME: "/tmp/home",
      CODEX_HOME: "/tmp/broker-codex-home",
      ANTHROPIC_API_KEY: "sk-test",
      ANTHROPIC_AUTH_TOKEN: "should-not-pass-from-broker",
      GEMINI_API_KEY: "gemini-test",
      OPENAI_API_KEY: "sk-should-not-pass",
      HTTPS_PROXY: "http://broker-proxy.invalid:8080",
      AWS_SECRET_ACCESS_KEY: "secret",
    }, {
      CODEX_HOME: "/tmp/home/.codex",
      ANTHROPIC_BASE_URL: "http://127.0.0.1:49152/anthropic/lease-1",
      ANTHROPIC_AUTH_TOKEN: "lease-token",
      HTTPS_PROXY: "http://127.0.0.1:7890",
      HTTP_PROXY: "http://127.0.0.1:7890",
      NO_PROXY: "localhost,127.0.0.1,::1",
    });

    expect(env.HOME).toBe("/tmp/home");
    expect(env.CODEX_HOME).toBe("/tmp/home/.codex");
    expect(env.ANTHROPIC_API_KEY).toBeUndefined();
    expect(env.ANTHROPIC_BASE_URL).toBe("http://127.0.0.1:49152/anthropic/lease-1");
    expect(env.ANTHROPIC_AUTH_TOKEN).toBe("lease-token");
    expect(env.HTTPS_PROXY).toBe("http://127.0.0.1:7890");
    expect(env.HTTP_PROXY).toBe("http://127.0.0.1:7890");
    expect(env.NO_PROXY).toBe("localhost,127.0.0.1,::1");
    expect(env.GEMINI_API_KEY).toBeUndefined();
    expect(env.OPENAI_API_KEY).toBeUndefined();
    expect(env.LC_TEST_VALUE).toBe("ok");
    expect(env.ASPACE_SHOULD_NOT_LEAK).toBeUndefined();
    expect(env.AWS_SECRET_ACCESS_KEY).toBeUndefined();

    delete process.env.ASPACE_SHOULD_NOT_LEAK;
    delete process.env.LC_TEST_VALUE;
  });
});
