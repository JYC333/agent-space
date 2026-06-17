import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { loadConfig } from "../src/config";
import {
  buildSubprocessEnv,
  executeVendorCliAdapter,
  type CliCommandExecutor,
  type CliCredentialBrokerPort,
  type CliExecutionResult,
} from "../src/modules/runs/vendorCliAdapter";
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
    CONTROL_PLANE_PYTHON_API_BASE_URL: "http://python.test",
    CONTROL_PLANE_DATABASE_URL: "postgresql://cp@db:5432/agent_space",
    CONTROL_PLANE_INTERNAL_TOKEN: "internal-token",
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
    runtime: string;
    executorMode: string;
    profileId?: string | null;
  }> = [];
  cleanups: string[] = [];
  granted = true;

  async grantForRun(
    runId: string,
    runtime: string,
    executorMode: "worktree" | "docker",
    profileId?: string | null,
  ) {
    this.grants.push({ runId, runtime, executorMode, profileId });
    const env: Record<string, string> = this.granted
      ? {
          HOME: `/tmp/runtime-home/${runId}`,
          SHOULD_NOT_PASS: "no",
        }
      : {};
    return {
      granted: this.granted,
      profile_id: this.granted ? profileId ?? `${runtime}/default` : null,
      runtime,
      executor_mode: executorMode,
      readonly: false,
      temp_home: this.granted ? `/tmp/runtime-home/${runId}` : null,
      host_source_path: null,
      target_path: null,
      env,
      fallback_reason: this.granted ? null : "no_profile_configured",
    };
  }

  async cleanupRunHome(runId: string): Promise<void> {
    this.cleanups.push(runId);
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
  it("runs codex_cli with credential grant, safe env, redacted command log, and AGENTS context", async () => {
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
          credential_profile_id: "codex_cli/default",
          timeout: 120,
        },
      },
      { credentialBroker: broker, executor, toolRegistry: new FakeTools() },
    );

    expect(await readFile(join(sandbox, "AGENTS.md"), "utf8")).toBe("Repo instructions");
    expect(broker.grants).toEqual([
      {
        runId: "run-1",
        runtime: "codex_cli",
        executorMode: "worktree",
        profileId: "codex_cli/default",
      },
    ]);
    expect(broker.cleanups).toEqual(["run-1"]);
    expect(executor.calls[0]).toMatchObject({
      command: [process.execPath, "Fix the bug"],
      cwd: sandbox,
      timeout_seconds: 120,
      run_id: "run-1",
      stdin: null,
    });
    expect(executor.calls[0].env.OPENAI_API_KEY).toBeUndefined();
    expect(executor.calls[0].env.SHOULD_NOT_PASS).toBeUndefined();
    expect(result).toMatchObject({
      adapter_type: "codex_cli",
      adapter_kind: "local_cli",
      success: true,
      output_text: "cli output",
      error_code: null,
      metadata_json: {
        credential_profile_id: "codex_cli/default",
        context_file_type: "AGENTS.md",
        rendered_in_sandbox: true,
      },
      adapter_log_json: {
        command: [process.execPath, "[REDACTED_PROMPT]"],
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
        adapter_config: { credential_profile_id: "codex_cli/default", timeout: 60 },
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

  it("fails closed for an ephemeral CLI without a prepared working dir", async () => {
    const broker = new FakeBroker();
    const executor = new FakeExecutor();

    const result = await executeVendorCliAdapter(
      config(),
      {
        run: run({ required_sandbox_level: "ephemeral", workspace_id: null }),
        sandbox_cwd: null,
        adapter_config: { credential_profile_id: "codex_cli/default" },
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
        adapter_config: { credential_profile_id: "codex_cli/missing" },
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

  it("fails closed for missing workspace policy, docker sandbox, and planned adapters before credentials", async () => {
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

    await expect(
      executeVendorCliAdapter(
        config(),
        { run: run({ required_sandbox_level: "one_shot_docker" }), sandbox_cwd: "/tmp/worktree" },
        { credentialBroker: broker, executor },
      ),
    ).resolves.toMatchObject({
      success: false,
      error_code: "docker_sandbox_not_implemented",
    });

    await expect(
      executeVendorCliAdapter(
        config(),
        { run: run({ adapter_type: "opencode" }), sandbox_cwd: "/tmp/worktree" },
        { credentialBroker: broker, executor },
      ),
    ).resolves.toMatchObject({
      success: false,
      error_code: "runtime_adapter_not_implemented",
    });

    expect(broker.grants).toEqual([]);
    expect(executor.calls).toEqual([]);
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
      ANTHROPIC_API_KEY: "sk-test",
      GEMINI_API_KEY: "gemini-test",
      OPENAI_API_KEY: "sk-should-not-pass",
      AWS_SECRET_ACCESS_KEY: "secret",
    });

    expect(env.HOME).toBe("/tmp/home");
    expect(env.ANTHROPIC_API_KEY).toBeUndefined();
    expect(env.GEMINI_API_KEY).toBeUndefined();
    expect(env.OPENAI_API_KEY).toBeUndefined();
    expect(env.LC_TEST_VALUE).toBe("ok");
    expect(env.ASPACE_SHOULD_NOT_LEAK).toBeUndefined();
    expect(env.AWS_SECRET_ACCESS_KEY).toBeUndefined();

    delete process.env.ASPACE_SHOULD_NOT_LEAK;
    delete process.env.LC_TEST_VALUE;
  });
});
