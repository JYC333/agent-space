import { describe, expect, it } from "vitest";
import { loadConfig } from "../src/config";
import {
  RunOrchestrationService,
  type RunExecutionRepositoryPort,
} from "../src/modules/runs/orchestrationService";
import { RunMaterializationService } from "../src/modules/runs/materializationService";
import type {
  RunEventInput,
  RunRecord,
  RunStepInput,
  RunStepRecord,
  RunTerminalUpdate,
} from "../src/modules/runs/repository";
import type { RunAdapterResultEnvelope } from "@agent-space/protocol" with { "resolution-mode": "import" };
import type {
  RunPythonContextPortRequest,
  RunPythonContextPortResponse,
} from "@agent-space/protocol" with { "resolution-mode": "import" };
import type { RuntimeToolResolverPort } from "../src/modules/runtimeTools";
import type { PreparedWorkspaceRuntime, RunWorkspaceManagerPort } from "../src/modules/workspaces";

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
    status: "queued",
    mode: "live",
    prompt: "Say hello",
    instruction: null,
    workspace_id: null,
    session_id: null,
    project_id: null,
    adapter_type: "model_api",
    model_provider_id: "provider-1",
    required_sandbox_level: "none",
    trigger_origin: "manual",
    started_at: null,
    ended_at: null,
    ...overrides,
  };
}

class FakeRepo implements RunExecutionRepositoryPort {
  calls: string[] = [];
  terminalUpdates: RunTerminalUpdate[] = [];
  run: RunRecord | null = run();
  lockAcquired = true;

  async getRun(spaceId: string, runId: string): Promise<RunRecord | null> {
    this.calls.push(`get:${spaceId}:${runId}`);
    return this.run;
  }

  async resolveRunActorId(
    run: Pick<RunRecord, "space_id" | "instructed_by_user_id">,
    commandSource: string,
  ): Promise<string> {
    this.calls.push(`actor:${run.instructed_by_user_id ?? commandSource}`);
    return "actor-1";
  }

  async markRunRunning(input: {
    run_id: string;
    space_id: string;
    started_at: string;
    required_sandbox_level?: string | null;
  }): Promise<RunRecord | null> {
    this.calls.push(`running:${input.run_id}`);
    if (!this.run || this.run.status !== "queued") return null;
    this.run = { ...this.run, status: "running", started_at: input.started_at };
    return this.run;
  }

  async updateRunSandboxLevel(input: {
    run_id: string;
    space_id: string;
    required_sandbox_level: string;
  }): Promise<void> {
    this.calls.push(`sandbox_level:${input.required_sandbox_level}`);
    if (this.run) this.run = { ...this.run, required_sandbox_level: input.required_sandbox_level };
  }

  async markRunTerminal(input: RunTerminalUpdate): Promise<RunRecord | null> {
    this.calls.push(`terminal:${input.status}`);
    // Mirror the SQL guard: terminal runs are never overwritten.
    if (
      this.run &&
      ["succeeded", "failed", "degraded", "cancelled"].includes(this.run.status)
    ) {
      return null;
    }
    this.terminalUpdates.push(input);
    if (this.run) this.run = { ...this.run, status: input.status, ended_at: input.completed_at };
    return this.run;
  }

  async appendRunEvent(input: RunEventInput): Promise<unknown> {
    this.calls.push(`event:${input.event_type}:${input.status}`);
    return {};
  }

  async createRunStep(input: RunStepInput): Promise<RunStepRecord> {
    this.calls.push(`step:${input.step_type}:${input.status}`);
    return {
      id: "step-1",
      space_id: input.space_id,
      run_id: input.run_id,
      step_index: 0,
      step_type: input.step_type,
      status: input.status,
    };
  }

  async updateRunStepStatus(input: {
    step_id: string;
    run_id: string;
    space_id: string;
    status: "succeeded" | "failed" | "skipped" | "cancelled";
    ended_at: string;
    output_summary?: string | null;
    error_type?: string | null;
    error_message?: string | null;
  }): Promise<boolean> {
    this.calls.push(`step_done:${input.status}`);
    return true;
  }

  async tryAcquireExecutionLock(input: {
    run_id: string;
    worker_id: string;
    job_id?: string | null;
  }): Promise<boolean> {
    this.calls.push(`lock:${input.run_id}:${input.worker_id}:${input.job_id ?? "none"}`);
    return this.lockAcquired;
  }

  async releaseExecutionLock(runId: string): Promise<void> {
    this.calls.push(`unlock:${runId}`);
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

class FakeMaterializationPorts {
  calls: RunPythonContextPortRequest[] = [];
  finalizations: Array<{ runId: string; spaceId: string }> = [];

  async call(request: RunPythonContextPortRequest): Promise<RunPythonContextPortResponse> {
    this.calls.push(request);
    return {
      operation: request.operation,
      owner: request.operation === "artifact.persist" ? "artifacts" : "proposals",
      status: "succeeded",
      result_json:
        request.operation === "artifact.persist"
          ? { artifact_id: "artifact-1" }
          : { proposal_id: "proposal-1" },
    };
  }

  async finalizeRun(runId: string, spaceId: string): Promise<RunPythonContextPortResponse> {
    this.finalizations.push({ runId, spaceId });
    return {
      operation: "finalization.finalize",
      owner: "runs_finalization",
      status: "succeeded",
      result_json: { run_finalization_id: "finalization-1" },
    };
  }
}

class FakePreparationPorts {
  calls: RunPythonContextPortRequest[] = [];
  policyResponse: RunPythonContextPortResponse | null = null;

  async call(request: RunPythonContextPortRequest): Promise<RunPythonContextPortResponse> {
    this.calls.push(request);
    if (request.operation === "policy.enforce") {
      return (
        this.policyResponse ?? {
          operation: request.operation,
          owner: "policy",
          status: "succeeded",
          result_json: {
            decision: "allowed",
            risk_level: "high",
            required_sandbox_level: "worktree",
            adapter_config: { credential_profile_id: "codex_cli/default" },
          },
        }
      );
    }
    if (request.operation === "workspace.prepare") {
      return {
        operation: request.operation,
        owner: "workspace_sandbox",
        status: "succeeded",
        result_json: {
          sandbox_cwd: "/tmp/aspace-prepared-run",
          cleanup_kind: "plain_workdir",
          sandbox_kind: "worktree",
          required_sandbox_level: "worktree",
        },
      };
    }
    if (request.operation === "context.prepare") {
      return {
        operation: request.operation,
        owner: "memory_context",
        status: "succeeded",
        result_json: {
          runtime_prompt: "prepared prompt",
          context_rendered: true,
          target_format: "codex_cli",
          instruction_file_path: "/tmp/aspace-prepared-run/AGENTS.md",
        },
      };
    }
    if (request.operation === "workspace.cleanup") {
      return {
        operation: request.operation,
        owner: "workspace_sandbox",
        status: "succeeded",
        result_json: { cleanup_kind: "plain_workdir" },
      };
    }
    return {
      operation: request.operation,
      owner: "policy",
      status: "not_implemented",
      error_code: "run_context_port_not_implemented",
      result_json: {},
    };
  }
}

class FakeContextPreparer {
  calls: Array<{
    runId: string;
    spaceId: string;
    adapterType: string | null;
    sandboxCwd: string | null;
    targetFormat: string | null;
    workspacePath: string | null;
  }> = [];

  async prepare(input: {
    runId: string;
    spaceId: string;
    adapterType: string | null;
    sandboxCwd: string | null;
    targetFormat: string | null;
    workspacePath: string | null;
  }) {
    this.calls.push(input);
    return {
      runtime_prompt: "prepared prompt",
      context_snapshot_id: "snapshot-1",
      context_rendered: true,
      target_format: input.targetFormat,
      instruction_file_path: input.sandboxCwd
        ? `${input.sandboxCwd}/AGENTS.md`
        : null,
      total_chars: 100,
      budget_chars: 128000,
      dropped_sections: [],
    };
  }
}

class FakeWorkspaceManager implements RunWorkspaceManagerPort {
  calls: string[] = [];

  async prepareRunWorkspace(run: RunRecord): Promise<PreparedWorkspaceRuntime> {
    this.calls.push(`prepare:${run.id}`);
    return {
      sandbox_cwd: "/tmp/aspace-prepared-run",
      cleanup_kind: "git_worktree",
      sandbox_kind: "worktree",
      workspace_root: "/tmp/workspace-root",
      base_commit_sha: "abc123",
      workspace_is_dirty: false,
    };
  }

  async cleanupRunWorkspace(input: {
    runId: string;
    spaceId: string;
    cleanupKind: string;
    sandboxCwd: string | null;
    workspaceRoot: string | null;
  }): Promise<void> {
    this.calls.push(`cleanup:${input.runId}:${input.cleanupKind}:${input.sandboxCwd}:${input.workspaceRoot}`);
  }

  async gcSandboxes(): Promise<{ removed: number; errors: number }> {
    this.calls.push("gc");
    return { removed: 0, errors: 0 };
  }
}

describe("RunOrchestrationService", () => {
  it("executes a managed API run with setup writes before adapter invocation and terminal writes after", async () => {
    const repo = new FakeRepo();
    repo.run = run({ system_prompt: "You are the space assistant.", instruction: null });
    const adapterCalls: string[] = [];
    const adapterRequests: Array<{ system_prompt?: string | null }> = [];
    const service = new RunOrchestrationService(config(), repo, {
      managedApi: {
        executeRuntimeHost: async (_config, request) => {
          adapterCalls.push(`adapter_after:${repo.calls.join("|")}`);
          adapterRequests.push(request);
          return {
            success: true,
            stdout: "done",
            stderr: "",
            output_text: "done",
            output_json: { adapter_type: "ts_agent_host" },
            exit_code: 0,
            error_text: null,
            error_code: null,
            started_at: "2026-06-12T10:00:00.000Z",
            completed_at: "2026-06-12T10:00:01.000Z",
            model: "gpt-4o-mini",
            usage: { input_tokens: 1, output_tokens: 1, total_tokens: 2 },
            events: [],
            adapter_metadata: { adapter_type: "ts_agent_host" },
            adapter_log_json: null,
          };
        },
      },
    });

    await expect(
      service.executeRun({
        run_id: "run-1",
        space_id: "space-1",
        worker_id: "worker-1",
        job_id: "job-1",
        command_source: "job",
      }),
    ).resolves.toMatchObject({ run_id: "run-1", status: "succeeded" });

    expect(adapterCalls[0]).toContain("running:run-1");
    expect(adapterCalls[0]).toContain("event:adapter_invoked:running");
    expect(adapterRequests[0]).toMatchObject({
      system_prompt: "You are the space assistant.",
      prompt: "Say hello",
    });
    expect(repo.calls).toEqual([
      "get:space-1:run-1",
      "lock:run-1:worker-1:job-1",
      "running:run-1",
      "actor:job",
      "step:adapter_started:running",
      "event:adapter_invoked:running",
      "terminal:succeeded",
      "step_done:succeeded",
      "event:adapter_completed:succeeded",
      "unlock:run-1",
    ]);
    expect(repo.terminalUpdates[0]).toMatchObject({
      status: "succeeded",
      output_text: "done",
      usage_json: { input_tokens: 1, output_tokens: 1, total_tokens: 2 },
    });
  });

  it("prevents duplicate execution before adapter invocation", async () => {
    const repo = new FakeRepo();
    repo.lockAcquired = false;
    const service = new RunOrchestrationService(config(), repo, {
      managedApi: {
        executeRuntimeHost: async () => {
          throw new Error("adapter should not run");
        },
      },
    });

    await expect(
      service.executeRun({
        run_id: "run-1",
        space_id: "space-1",
        worker_id: "worker-1",
        command_source: "job",
      }),
    ).resolves.toMatchObject({
      skipped: true,
      skip_reason: "duplicate_execution",
      error_code: "duplicate_execution",
    });

    // Python parity: duplicate execution returns the error result without
    // writing run evidence.
    expect(repo.calls).toEqual([
      "get:space-1:run-1",
      "lock:run-1:worker-1:none",
    ]);
  });

  it("maps adapter failures and orchestration exceptions to terminal failed runs", async () => {
    const repo = new FakeRepo();
    const service = new RunOrchestrationService(config(), repo, {
      managedApi: {
        executeRuntimeHost: async () => ({
          success: false,
          stdout: "",
          stderr: "bad",
          output_text: "",
          output_json: { adapter_type: "ts_agent_host" },
          exit_code: 1,
          error_text: "token=secret failed",
          error_code: "provider_invocation_failed",
          started_at: "2026-06-12T10:00:00.000Z",
          completed_at: "2026-06-12T10:00:01.000Z",
          model: null,
          usage: null,
          events: [],
          adapter_metadata: { adapter_type: "ts_agent_host" },
          adapter_log_json: null,
        }),
      },
    });

    await expect(
      service.executeRun({
        run_id: "run-1",
        space_id: "space-1",
        worker_id: "worker-1",
        command_source: "job",
      }),
    ).resolves.toMatchObject({
      status: "failed",
      error_code: "provider_invocation_failed",
      error_text: "[REDACTED_SECRET] failed",
    });
    expect(repo.terminalUpdates[0]).toMatchObject({
      status: "failed",
      error_json: {
        error_code: "provider_invocation_failed",
        error_text: "[REDACTED_SECRET] failed",
      },
    });
  });

  it("maps orchestration-level adapter timeout to a terminal failed run", async () => {
    const repo = new FakeRepo();
    const service = new RunOrchestrationService(config(), repo, {
      managedApi: {
        executeRuntimeHost: async () =>
          new Promise(() => {
            // Intentionally never resolves; the orchestration timeout owns the result.
          }),
      },
    });

    await expect(
      service.executeRun({
        run_id: "run-1",
        space_id: "space-1",
        worker_id: "worker-1",
        command_source: "job",
        timeout_ms: 1,
      }),
    ).resolves.toMatchObject({
      status: "failed",
      error_code: "adapter_timeout",
    });
    expect(repo.terminalUpdates[0]).toMatchObject({
      status: "failed",
      error_json: {
        error_code: "adapter_timeout",
      },
    });
    expect(repo.calls).toContain("unlock:run-1");
  });

  it("routes CLI runs through the vendor CLI adapter and supports cancellation", async () => {
    const repo = new FakeRepo();
    repo.run = run({
      adapter_type: "codex_cli",
      required_sandbox_level: "worktree",
      workspace_id: "workspace-1",
    });
    const executorResults: RunAdapterResultEnvelope[] = [];
    const service = new RunOrchestrationService(config(), repo, {
      vendorCli: {
        credentialBroker: {
          async grantForRun() {
            return {
              granted: true,
              profile_id: "codex_cli/default",
              runtime: "codex_cli",
              executor_mode: "worktree",
              readonly: false,
              temp_home: null,
              host_source_path: null,
              target_path: null,
              env: {},
              fallback_reason: null,
            };
          },
        },
        executor: {
          async runCommand() {
            return {
              returncode: 0,
              stdout: "cli ok",
              stderr: "",
              timed_out: false,
            };
          },
        },
        toolRegistry: new FakeTools(),
      },
    });

    await service.executeRun({
      run_id: "run-1",
      space_id: "space-1",
      worker_id: "worker-1",
      command_source: "job",
      sandbox_cwd: "/tmp",
      context_text: "context",
    });
    executorResults.push(repo.terminalUpdates[0].output_json as RunAdapterResultEnvelope);

    expect(repo.terminalUpdates[0]).toMatchObject({
      status: "succeeded",
      output_text: "cli ok",
    });

    repo.run = run({ status: "running" });
    await expect(
      service.cancelRun({
        run_id: "run-1",
        space_id: "space-1",
        requested_by_user_id: "user-1",
        reason: "stop requested",
      }),
    ).resolves.toMatchObject({ status: "cancelled", error_code: "run_cancelled" });
    expect(repo.terminalUpdates.at(-1)).toMatchObject({
      status: "cancelled",
      error_json: {
        error_code: "run_cancelled",
        requested_by_user_id: "user-1",
      },
    });
    expect(executorResults.length).toBe(1);
  });

  it("prepares CLI sandbox through the legacy workspace port and context natively", async () => {
    const repo = new FakeRepo();
    repo.run = run({
      adapter_type: "codex_cli",
      required_sandbox_level: "worktree",
      workspace_id: "workspace-1",
    });
    const ports = new FakePreparationPorts();
    const contextPreparer = new FakeContextPreparer();
    const workspaceManager = new FakeWorkspaceManager();
    const executorCalls: Array<{ command: string[]; cwd: string | null }> = [];
    const service = new RunOrchestrationService(config(), repo, {
      contextPorts: ports,
      contextPreparer,
      workspaceManager,
      vendorCli: {
        credentialBroker: {
          async grantForRun() {
            return {
              granted: true,
              profile_id: "codex_cli/default",
              runtime: "codex_cli",
              executor_mode: "worktree",
              readonly: false,
              temp_home: null,
              host_source_path: null,
              target_path: null,
              env: {},
              fallback_reason: null,
            };
          },
        },
        executor: {
          async runCommand(input) {
            executorCalls.push({ command: input.command, cwd: input.cwd });
            return {
              returncode: 0,
              stdout: "cli ok",
              stderr: "",
              timed_out: false,
            };
          },
        },
        toolRegistry: new FakeTools(),
      },
    });

    await expect(
      service.executeRun({
        run_id: "run-1",
        space_id: "space-1",
        worker_id: "worker-1",
        command_source: "job",
      }),
    ).resolves.toMatchObject({ status: "succeeded" });

    expect(ports.calls.map((call) => call.operation)).toEqual([
      "policy.enforce",
    ]);
    expect(workspaceManager.calls).toEqual([
      "prepare:run-1",
      "cleanup:run-1:git_worktree:/tmp/aspace-prepared-run:/tmp/workspace-root",
    ]);
    expect(contextPreparer.calls).toEqual([
      {
        runId: "run-1",
        spaceId: "space-1",
        adapterType: "codex_cli",
        sandboxCwd: "/tmp/aspace-prepared-run",
        targetFormat: "codex_cli",
        workspacePath: "/tmp/workspace-root",
      },
    ]);
    expect(executorCalls[0]).toEqual({
      command: [process.execPath, "prepared prompt"],
      cwd: "/tmp/aspace-prepared-run",
    });
    expect(repo.calls).toContain("event:sandbox_created:succeeded");
    expect(repo.terminalUpdates[0]).toMatchObject({
      status: "succeeded",
      output_text: "cli ok",
    });
  });

  it("writes materialization summaries and finalizes after terminal state", async () => {
    const repo = new FakeRepo();
    const ports = new FakeMaterializationPorts();
    const service = new RunOrchestrationService(config(), repo, {
      managedApi: {
        executeRuntimeHost: async () => ({
          success: true,
          stdout: "done",
          stderr: "",
          output_text: "done",
          output_json: {
            adapter_type: "ts_agent_host",
            artifacts: [{ title: "A" }],
            proposed_changes: [{ proposal_type: "memory_create" }],
          },
          exit_code: 0,
          error_text: null,
          error_code: null,
          started_at: "2026-06-12T10:00:00.000Z",
          completed_at: "2026-06-12T10:00:01.000Z",
          model: "gpt-4o-mini",
          usage: null,
          events: [],
          adapter_metadata: { adapter_type: "ts_agent_host" },
          adapter_log_json: null,
        }),
      },
      materializer: new RunMaterializationService(ports),
    });

    await service.executeRun({
      run_id: "run-1",
      space_id: "space-1",
      worker_id: "worker-1",
      command_source: "job",
    });

    expect(ports.calls.map((call) => call.operation)).toEqual([
      "artifact.persist",
      "artifact.persist",
      "proposal.create",
    ]);
    expect(repo.terminalUpdates[0].output_json).toMatchObject({
      adapter_type: "model_api",
      materialization: [
        { kind: "artifact", status: "succeeded", artifact_id: "artifact-1" },
        { kind: "artifact", status: "succeeded", artifact_id: "artifact-1" },
        { kind: "proposal", status: "succeeded", proposal_id: "proposal-1" },
      ],
    });
    expect(repo.calls).toContain("event:artifact_ingested:succeeded");
    expect(repo.calls).toContain("event:proposal_created:succeeded");
    // The Python-owned finalization port already writes the successful
    // run_finalized event; TS only appends this event when the port fails.
    expect(repo.calls).not.toContain("event:run_finalized:succeeded");
    expect(ports.finalizations).toEqual([{ runId: "run-1", spaceId: "space-1" }]);
  });

  it("fails closed before adapter invocation when policy denies the run", async () => {
    const repo = new FakeRepo();
    const ports = new FakePreparationPorts();
    ports.policyResponse = {
      operation: "policy.enforce",
      owner: "policy",
      status: "failed",
      error_code: "policy_denied",
      message: "Runtime execution denied by policy: blocked by rule",
      result_json: {},
    };
    let adapterInvoked = false;
    const service = new RunOrchestrationService(config(), repo, {
      contextPorts: ports,
      managedApi: {
        executeRuntimeHost: async () => {
          adapterInvoked = true;
          throw new Error("adapter must not run after policy denial");
        },
      },
    });

    await expect(
      service.executeRun({
        run_id: "run-1",
        space_id: "space-1",
        worker_id: "worker-1",
        command_source: "http",
      }),
    ).resolves.toMatchObject({ status: "failed", error_code: "policy_denied" });
    expect(adapterInvoked).toBe(false);
    expect(ports.calls.map((call) => call.operation)).toEqual(["policy.enforce"]);
    expect(repo.terminalUpdates[0]).toMatchObject({
      status: "failed",
      error_json: { error_code: "policy_denied" },
    });
    expect(repo.calls).toContain("unlock:run-1");
  });

  it("uses the policy-resolved adapter config instead of caller-supplied overrides", async () => {
    const repo = new FakeRepo();
    repo.run = run({
      adapter_type: "codex_cli",
      required_sandbox_level: "worktree",
      workspace_id: "workspace-1",
    });
    const ports = new FakePreparationPorts();
    ports.policyResponse = {
      operation: "policy.enforce",
      owner: "policy",
      status: "succeeded",
      result_json: {
        decision: "allowed",
        risk_level: "high",
        required_sandbox_level: "worktree",
        adapter_config: {
          credential_profile_id: "codex_cli/default",
        },
      },
    };
    const adapterConfigs: Array<Record<string, unknown>> = [];
    const service = new RunOrchestrationService(config(), repo, {
      contextPorts: ports,
      contextPreparer: new FakeContextPreparer(),
      workspaceManager: new FakeWorkspaceManager(),
      vendorCli: {
        credentialBroker: {
          async grantForRun() {
            return {
              granted: true,
              profile_id: "codex_cli/default",
              runtime: "codex_cli",
              executor_mode: "worktree" as const,
              readonly: false,
              temp_home: null,
              host_source_path: null,
              target_path: null,
              env: {},
              fallback_reason: null,
            };
          },
        },
        executor: {
          async runCommand(input) {
            adapterConfigs.push({ command: input.command });
            return { returncode: 0, stdout: "ok", stderr: "", timed_out: false };
          },
        },
        toolRegistry: new FakeTools(),
      },
    });

    await expect(
      service.executeRun({
        run_id: "run-1",
        space_id: "space-1",
        worker_id: "worker-1",
        command_source: "http",
        adapter_config: { executable_path: "/tmp/attacker-binary" },
      }),
    ).resolves.toMatchObject({ status: "succeeded" });
    expect(adapterConfigs[0].command).toEqual([process.execPath, "prepared prompt"]);
  });

  it("routes through the policy-resolved adapter type, not the run's stored type", async () => {
    // Regression for the real-stack defect: a run whose stored adapter_type is a
    // stale removed adapter must be routed by the type the
    // policy port resolves ("model_api"), or every such run wrongly falls to
    // runtime_adapter_not_implemented. Exercises the effectiveRun threading.
    const repo = new FakeRepo();
    repo.run = run({ adapter_type: "legacy_removed", required_sandbox_level: "none" })
    const ports = new FakePreparationPorts();
    ports.policyResponse = {
      operation: "policy.enforce",
      owner: "policy",
      status: "succeeded",
      result_json: {
        decision: "allowed",
        risk_level: "low",
        required_sandbox_level: "none",
        adapter_type: "model_api",
      },
    };
    let hostCalled = false;
    const service = new RunOrchestrationService(config(), repo, {
      contextPorts: ports,
      contextPreparer: new FakeContextPreparer(),
      managedApi: {
        executeRuntimeHost: async () => {
          hostCalled = true;
          return {
            success: true,
            stdout: "",
            stderr: "",
            output_text: "resolved-adapter ok",
            output_json: { adapter_type: "ts_agent_host" },
            exit_code: 0,
            error_text: null,
            error_code: null,
            started_at: "2026-06-12T10:00:00.000Z",
            completed_at: "2026-06-12T10:00:01.000Z",
            model: "gpt-4o-mini",
            usage: null,
            events: [],
            adapter_metadata: { adapter_type: "ts_agent_host" },
            adapter_log_json: null,
          };
        },
      },
    });

    await expect(
      service.executeRun({
        run_id: "run-1",
        space_id: "space-1",
        worker_id: "worker-1",
        command_source: "job",
      }),
    ).resolves.toMatchObject({ status: "succeeded" });
    // Routed to the managed API host (resolved type), not stale type→not_implemented.
    expect(hostCalled).toBe(true);
    expect(repo.terminalUpdates[0]).toMatchObject({ status: "succeeded", output_text: "resolved-adapter ok" });
  });

  it("terminates the registered CLI process on cancel", async () => {
    const repo = new FakeRepo();
    repo.run = run({ status: "running", adapter_type: "codex_cli" });
    const terminated: string[] = [];
    const service = new RunOrchestrationService(config(), repo, {
      processRegistry: {
        register() {},
        deregister() {},
        terminate(runId: string) {
          terminated.push(runId);
          return true;
        },
      },
    });

    await expect(
      service.cancelRun({
        run_id: "run-1",
        space_id: "space-1",
        requested_by_user_id: "user-1",
        reason: "stop requested",
      }),
    ).resolves.toMatchObject({ status: "cancelled", error_code: "run_cancelled" });
    expect(terminated).toEqual(["run-1"]);
    expect(repo.run?.status).toBe("cancelled");
  });

  it("does not overwrite a concurrent cancel when the adapter finishes", async () => {
    const repo = new FakeRepo();
    repo.run = run({
      adapter_type: "codex_cli",
      required_sandbox_level: "worktree",
      workspace_id: "workspace-1",
    });
    const service: RunOrchestrationService = new RunOrchestrationService(config(), repo, {
      contextPreparer: new FakeContextPreparer(),
      workspaceManager: new FakeWorkspaceManager(),
      vendorCli: {
        credentialBroker: {
          async grantForRun() {
            return {
              granted: true,
              profile_id: "codex_cli/default",
              runtime: "codex_cli",
              executor_mode: "worktree" as const,
              readonly: false,
              temp_home: null,
              host_source_path: null,
              target_path: null,
              env: {},
              fallback_reason: null,
            };
          },
        },
        executor: {
          async runCommand() {
            // A stop lands while the CLI is still running.
            await service.cancelRun({
              run_id: "run-1",
              space_id: "space-1",
              reason: "stop requested",
            });
            return { returncode: 0, stdout: "late ok", stderr: "", timed_out: false };
          },
        },
        toolRegistry: new FakeTools(),
      },
    });

    const result = await service.executeRun({
      run_id: "run-1",
      space_id: "space-1",
      worker_id: "worker-1",
      command_source: "http",
      sandbox_cwd: "/tmp",
      context_text: "context",
    });

    expect(result).toMatchObject({
      status: "cancelled",
      skipped: true,
      skip_reason: "run_already_terminal",
    });
    expect(repo.run?.status).toBe("cancelled");
    expect(repo.terminalUpdates.map((update) => update.status)).toEqual(["cancelled"]);
    expect(repo.calls).toContain("unlock:run-1");
  });
});
