import type {
  RunAdapterResultEnvelope,
  RunExecuteRequest,
  RunJobResult,
  RunMaterializationItemSummary,
  RunPythonContextPortRequest,
  RunPythonContextPortResponse,
  RunStatus,
  RunTerminalStatus,
} from "@agent-space/protocol" with { "resolution-mode": "import" };
import type { ControlPlaneConfig } from "../../config";
import {
  executeManagedApiNoToolAdapter,
  type ManagedApiNoToolAdapterDeps,
} from "./managedApiAdapter";
import {
  executeVendorCliAdapter,
  type CliProcessRegistry,
  type VendorCliAdapterDeps,
} from "./vendorCliAdapter";
import type {
  PgRunRepository,
  RunEventInput,
  RunRecord,
  RunStepInput,
  RunStepRecord,
  RunTerminalUpdate,
} from "./repository";
import {
  redactEvidenceText,
  sanitizeEvidenceJson,
} from "./evidenceRedaction";
import {
  EPHEMERAL_CLEANUP_KIND,
  prepareEphemeralDir,
  removeEphemeralDir,
  workingDirScopeForLevel,
} from "./ephemeralSandbox";
import type { RunWorkspaceManagerPort } from "../workspaces";
import {
  isVendorCliAdapter,
  targetFormatForAdapter,
} from "../runtimeAdapters";
import type { RunMaterializationService } from "./materializationService";
import type { ContextPrepareInput, ContextPrepareResult } from "../context";

export interface RunExecutionRepositoryPort {
  getRun(spaceId: string, runId: string): Promise<RunRecord | null>;
  resolveRunActorId(
    run: Pick<RunRecord, "space_id" | "instructed_by_user_id">,
    commandSource: string,
  ): Promise<string>;
  markRunRunning(input: {
    run_id: string;
    space_id: string;
    started_at: string;
    required_sandbox_level?: string | null;
  }): Promise<RunRecord | null>;
  updateRunSandboxLevel(input: {
    run_id: string;
    space_id: string;
    required_sandbox_level: string;
  }): Promise<void>;
  markRunTerminal(input: RunTerminalUpdate): Promise<RunRecord | null>;
  appendRunEvent(input: RunEventInput): Promise<unknown>;
  createRunStep(input: RunStepInput): Promise<RunStepRecord>;
  updateRunStepStatus(input: {
    step_id: string;
    run_id: string;
    space_id: string;
    status: "succeeded" | "failed" | "skipped" | "cancelled";
    ended_at: string;
    output_summary?: string | null;
    error_type?: string | null;
    error_message?: string | null;
  }): Promise<boolean>;
  tryAcquireExecutionLock(input: {
    run_id: string;
    worker_id: string;
    job_id?: string | null;
  }): Promise<boolean>;
  releaseExecutionLock(runId: string): Promise<void>;
}

export interface RunExecutionAdapterDeps {
  managedApi?: ManagedApiNoToolAdapterDeps;
  vendorCli?: VendorCliAdapterDeps;
  materializer?: RunMaterializationService;
  contextPorts?: RunPreparationPortClient;
  contextPreparer?: RunContextPrepareClient;
  workspaceManager?: RunWorkspaceManagerPort;
  codePatchCollector?: RunCodePatchCollectorPort;
  /**
   * Shared CLI process registry. Execute registers spawned CLI processes here;
   * cancelRun terminates them through it. Must be the same instance across the
   * HTTP routes and the job worker so a stop from another request can reach a
   * running process.
   */
  processRegistry?: CliProcessRegistry;
}

export interface RunPreparationPortClient {
  call(request: RunPythonContextPortRequest): Promise<RunPythonContextPortResponse>;
}

export interface RunContextPrepareClient {
  prepare(input: ContextPrepareInput): Promise<ContextPrepareResult>;
}

export interface RunCodePatchCollectorPort {
  collect(input: {
    run: RunRecord;
    worktreePath: string | null;
    baseCommitSha: string | null;
  }): Promise<{ item: RunMaterializationItemSummary; errors: string[] } | null>;
}

export interface RunExecutionInput extends RunExecuteRequest {
  prompt?: string | null;
  system_prompt?: string | null;
  model?: string | null;
  max_tokens?: number | null;
  context_text?: string | null;
  sandbox_cwd?: string | null;
  adapter_config?: Record<string, unknown>;
  risk_level?: string | null;
  timeout_ms?: number | null;
}

interface PreparedRuntimeContext {
  prompt: string | null;
  sandbox_cwd: string | null;
  context_text: string | null;
  adapter_config: Record<string, unknown>;
  risk_level: string | null;
  cleanup: {
    cleanup_kind: string;
    sandbox_cwd: string | null;
    workspace_root: string | null;
  } | null;
  sandbox_kind: string | null;
  base_commit_sha: string | null;
}

interface ResolvedRuntimePolicy {
  adapter_type: string | null;
  adapter_config: Record<string, unknown>;
  risk_level: string | null;
  required_sandbox_level: string | null;
}

class RunPreparationError extends Error {
  constructor(
    readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = "RunPreparationError";
  }
}

export class RunOrchestrationService {
  constructor(
    private readonly config: ControlPlaneConfig,
    private readonly repository: RunExecutionRepositoryPort | PgRunRepository,
    private readonly adapters: RunExecutionAdapterDeps = {},
  ) {}

  async executeRun(input: RunExecutionInput): Promise<RunJobResult> {
    const startedAt = new Date().toISOString();
    const run = await this.repository.getRun(input.space_id, input.run_id);
    if (!run) {
      return {
        run_id: input.run_id,
        status: "unknown",
        error_code: "run_not_found",
        error: "Run not found in this space.",
      };
    }
    if (isTerminalRunStatus(run.status)) {
      return {
        run_id: run.id,
        status: run.status,
        skipped: true,
        skip_reason: "run_already_terminal",
      };
    }

    const locked = await this.repository.tryAcquireExecutionLock({
      run_id: run.id,
      worker_id: input.worker_id,
      job_id: input.job_id ?? null,
    });
    if (!locked) {
      // Python parity: duplicate execution returns the error result without
      // writing run evidence (event_type has a closed CHECK constraint).
      return {
        run_id: run.id,
        status: protocolRunStatus(run.status),
        skipped: true,
        skip_reason: "duplicate_execution",
        error_code: "duplicate_execution",
        error: "Run is already being executed by another worker.",
      };
    }

    let step: RunStepRecord | null = null;
    let preparedRuntime: PreparedRuntimeContext | null = null;
    try {
      const running = await this.repository.markRunRunning({
        run_id: run.id,
        space_id: run.space_id,
        started_at: startedAt,
        required_sandbox_level: run.required_sandbox_level,
      });
      if (!running) {
        const current = await this.repository.getRun(run.space_id, run.id);
        return {
          run_id: run.id,
          status: protocolRunStatus(current?.status ?? run.status),
          skipped: true,
          skip_reason: "run_not_queued",
        };
      }

      // Policy gate + server-owned adapter resolution FIRST: runtime.execute
      // and runtime.use_credential are enforced by the Python-owned policy
      // context, which also returns the resolved adapter type / config (never
      // trusting caller-supplied adapter config). The resolved adapter type
      // then drives evidence metadata, worktree preparation, and routing.
      const resolved = await this.enforceRuntimePolicy(running, input);
      const effectiveRun: RunRecord = {
        ...running,
        adapter_type: resolved.adapter_type,
        // Honor the policy-resolved sandbox level (e.g. ephemeral for a
        // no-workspace CLI run); the stored row level is the creation-time
        // default and is not re-derived under TS authority.
        required_sandbox_level:
          resolved.required_sandbox_level ?? running.required_sandbox_level,
      };
      // Persist the resolved level so the run read model / trace reflects what
      // actually executed (not the creation-time default).
      if (
        effectiveRun.required_sandbox_level &&
        effectiveRun.required_sandbox_level !== running.required_sandbox_level
      ) {
        await this.repository.updateRunSandboxLevel({
          run_id: effectiveRun.id,
          space_id: effectiveRun.space_id,
          required_sandbox_level: effectiveRun.required_sandbox_level,
        });
      }
      const effectiveInput: RunExecutionInput = {
        ...input,
        adapter_config: resolved.adapter_config,
        risk_level: resolved.risk_level,
      };

      // run_steps.actor_id is a non-null Actor FK; worker ids carry transport
      // identity only and go to metadata. Event/step types must stay within
      // the Python CHECK constraint lists (ck_run_events_event_type,
      // ck_run_steps_step_type).
      const actorId = await this.repository.resolveRunActorId(
        effectiveRun,
        input.command_source,
      );
      step = await this.repository.createRunStep({
        run_id: effectiveRun.id,
        space_id: effectiveRun.space_id,
        actor_id: actorId,
        step_type: "adapter_started",
        status: "running",
        title: "Runtime adapter execution",
        workspace_id: effectiveRun.workspace_id,
        session_id: effectiveRun.session_id,
        started_at: startedAt,
        metadata_json: {
          adapter_type: effectiveRun.adapter_type,
          command_source: input.command_source,
          worker_id: input.worker_id,
        },
      });
      await this.repository.appendRunEvent({
        run_id: effectiveRun.id,
        space_id: effectiveRun.space_id,
        event_type: "adapter_invoked",
        status: "running",
        step_id: step.id,
        actor_id: actorId,
        summary: "Runtime adapter started.",
        workspace_id: effectiveRun.workspace_id,
        metadata_json: {
          adapter_type: effectiveRun.adapter_type,
          command_source: input.command_source,
          worker_id: input.worker_id,
        },
      });

      preparedRuntime = await this.prepareRuntimeContext(effectiveRun, effectiveInput);
      const adapterResult = await this.invokeAdapter(
        effectiveRun,
        inputWithPreparedRuntime(effectiveInput, preparedRuntime),
      );
      const terminalStatus = terminalStatusFromAdapter(adapterResult);
      const completedAt = adapterResult.completed_at ?? new Date().toISOString();
      const materialization = this.adapters.materializer
        ? await this.adapters.materializer.materializeAdapterResult({
            run: running,
            adapterResult,
            sandbox_cwd: preparedRuntime?.sandbox_cwd ?? null,
          })
        : { items: [], errors: [] };
      const codePatch = adapterResult.success
        ? await this.collectCodePatch(effectiveRun, preparedRuntime)
        : null;
      if (codePatch) {
        materialization.items.push(codePatch.item);
        materialization.errors.push(...codePatch.errors);
      }

      const terminalRun = await this.repository.markRunTerminal({
        run_id: running.id,
        space_id: running.space_id,
        status: terminalStatus,
        output_text: adapterResult.output_text,
        output_json: outputJsonWithMaterialization(
          adapterResult.output_json,
          materialization.items,
          materialization.errors,
        ),
        error_json: adapterErrorJson(adapterResult),
        exit_code: adapterResult.exit_code,
        completed_at: completedAt,
        usage_json: adapterResult.usage ?? {},
      });
      if (!terminalRun) {
        // The run reached a terminal state while the adapter was executing —
        // a concurrent cancel owns the terminal write. Do not overwrite it.
        const current = await this.repository.getRun(running.space_id, running.id);
        const currentStatus = protocolRunStatus(current?.status ?? "cancelled");
        await this.repository.updateRunStepStatus({
          step_id: step.id,
          run_id: running.id,
          space_id: running.space_id,
          status: "cancelled",
          ended_at: completedAt,
          error_type: "run_cancelled",
          error_message: "Adapter finished after the run was cancelled; result not applied.",
        });
        await this.repository.appendRunEvent({
          run_id: running.id,
          space_id: running.space_id,
          event_type: "adapter_completed",
          status: "cancelled",
          step_id: step.id,
          summary: "Adapter finished after the run was cancelled; result not applied.",
          error_code: "run_cancelled",
          workspace_id: running.workspace_id,
          metadata_json: {
            adapter_type: adapterResult.adapter_type,
            adapter_kind: adapterResult.adapter_kind,
            exit_code: adapterResult.exit_code,
          },
        });
        return {
          run_id: running.id,
          status: currentStatus,
          skipped: true,
          skip_reason: "run_already_terminal",
        };
      }
      await this.appendMaterializationEvents(running, materialization.items);
      await this.repository.updateRunStepStatus({
        step_id: step.id,
        run_id: running.id,
        space_id: running.space_id,
        status: adapterResult.success ? "succeeded" : "failed",
        ended_at: completedAt,
        output_summary: adapterResult.success ? summarizeOutput(adapterResult.output_text) : null,
        error_type: adapterResult.error_code ?? null,
        error_message: adapterResult.error_message ?? null,
      });
      await this.repository.appendRunEvent({
        run_id: running.id,
        space_id: running.space_id,
        event_type: "adapter_completed",
        status: adapterResult.success ? "succeeded" : "failed",
        step_id: step.id,
        summary: adapterResult.success
          ? "Runtime adapter completed successfully."
          : "Runtime adapter failed.",
        error_code: adapterResult.error_code ?? null,
        error_message: adapterResult.error_message ?? null,
        workspace_id: running.workspace_id,
        metadata_json: {
          adapter_type: adapterResult.adapter_type,
          adapter_kind: adapterResult.adapter_kind,
          exit_code: adapterResult.exit_code,
        },
      });
      if (this.adapters.materializer && isTerminalRunStatus(terminalStatus)) {
        const finalization = await this.adapters.materializer.finalizeRun({
          ...running,
          status: terminalStatus,
          ended_at: completedAt,
        });
        if (finalization.status !== "succeeded") {
          await this.appendFinalizationEvent(running, finalization);
        }
      }

      return {
        run_id: running.id,
        status: terminalStatus,
        error_code: adapterResult.error_code ?? null,
        error_text: adapterResult.error_message ?? null,
      };
    } catch (error) {
      const completedAt = new Date().toISOString();
      const message = errorMessage(error);
      const errorCode =
        error instanceof RunPreparationError ? error.code : "run_orchestration_failed";
      await this.repository.markRunTerminal({
        run_id: run.id,
        space_id: run.space_id,
        status: "failed",
        output_text: "",
        output_json: {},
        error_json: {
          error_code: errorCode,
          error_text: message,
        },
        exit_code: 1,
        completed_at: completedAt,
        usage_json: {},
      });
      if (step) {
        await this.repository.updateRunStepStatus({
          step_id: step.id,
          run_id: run.id,
          space_id: run.space_id,
          status: "failed",
          ended_at: completedAt,
          error_type: errorCode,
          error_message: message,
        });
      }
      await this.repository.appendRunEvent({
        run_id: run.id,
        space_id: run.space_id,
        event_type: "adapter_completed",
        status: "failed",
        step_id: step?.id ?? null,
        summary: "Run orchestration failed before or during adapter execution.",
        error_code: errorCode,
        error_message: message,
        workspace_id: run.workspace_id,
        metadata_json: { orchestration_failure: true },
      });
      return {
        run_id: run.id,
        status: "failed",
        error_code: errorCode,
        error: message,
      };
    } finally {
      await this.cleanupRuntimeContext(preparedRuntime, run);
      await this.repository.releaseExecutionLock(run.id);
    }
  }

  async cancelRun(input: {
    run_id: string;
    space_id: string;
    requested_by_user_id?: string | null;
    reason?: string | null;
    terminate_process?: boolean;
  }): Promise<RunJobResult> {
    const completedAt = new Date().toISOString();
    const run = await this.repository.getRun(input.space_id, input.run_id);
    if (!run) {
      return {
        run_id: input.run_id,
        status: "unknown",
        error_code: "run_not_found",
        error: "Run not found in this space.",
      };
    }
    // Parity with Python stop_run: queued, running, and waiting_for_review runs
    // are cancellable; hard-terminal runs are a no-op.
    if (isHardTerminalRunStatus(run.status)) {
      return {
        run_id: run.id,
        status: protocolRunStatus(run.status),
        skipped: true,
        skip_reason: "run_already_terminal",
      };
    }

    // SIGTERM a TS-registered CLI subprocess before the DB status change
    // (best-effort, same as the Python process registry behavior).
    let processTerminated = false;
    if (input.terminate_process !== false && this.adapters.processRegistry) {
      try {
        processTerminated = this.adapters.processRegistry.terminate(run.id);
      } catch {
        processTerminated = false;
      }
    }

    const updated = await this.repository.markRunTerminal({
      run_id: run.id,
      space_id: run.space_id,
      status: "cancelled",
      output_text: "",
      output_json: {},
      error_json: {
        error_code: "run_cancelled",
        error_text: input.reason ?? "Run cancelled.",
        requested_by_user_id: input.requested_by_user_id ?? null,
        process_terminated: processTerminated,
      },
      exit_code: 1,
      completed_at: completedAt,
      usage_json: {},
    });
    if (!updated) {
      const current = await this.repository.getRun(input.space_id, run.id);
      return {
        run_id: run.id,
        status: protocolRunStatus(current?.status ?? run.status),
        skipped: true,
        skip_reason: "run_already_terminal",
      };
    }
    // Python stop_run parity: cancellation evidence lives on the run row
    // (error_json carries requester + process_terminated); no run_event is
    // appended (event_type has a closed CHECK constraint with no cancel type).
    return { run_id: run.id, status: "cancelled", error_code: "run_cancelled" };
  }

  /**
   * Enforce runtime.execute / runtime.use_credential and resolve the
   * server-owned adapter type and config through the Python policy port.
   * Caller-supplied adapter config is the base, but the policy-resolved config
   * (from AgentVersion runtime config/policy) overrides it. Executable paths,
   * permission bypass, and runtime policy never come from the request.
   * A non-allowed decision throws RunPreparationError (mapped to a terminal
   * failed run by the executeRun catch block).
   */
  private async enforceRuntimePolicy(
    run: RunRecord,
    input: RunExecutionInput,
  ): Promise<ResolvedRuntimePolicy> {
    const base: ResolvedRuntimePolicy = {
      adapter_type: run.adapter_type,
      adapter_config: { ...(input.adapter_config ?? {}) },
      risk_level: input.risk_level ?? null,
      required_sandbox_level: run.required_sandbox_level ?? null,
    };
    const ports = this.adapters.contextPorts;
    if (!ports) return base;

    const policy = await this.callPreparationPort(
      ports,
      {
        operation: "policy.enforce",
        run_id: run.id,
        space_id: run.space_id,
        payload_json: {
          adapter_type: run.adapter_type,
          command_source: input.command_source,
        },
      },
      "policy_denied",
    );
    const policyResult = recordValue(policy.result_json);
    return {
      adapter_type: stringValue(policyResult.adapter_type) ?? base.adapter_type,
      adapter_config: {
        ...base.adapter_config,
        ...recordValue(policyResult.adapter_config),
      },
      risk_level: stringValue(policyResult.risk_level) ?? base.risk_level,
      required_sandbox_level:
        stringValue(policyResult.required_sandbox_level) ?? base.required_sandbox_level,
    };
  }

  private async prepareRuntimeContext(
    run: RunRecord,
    input: RunExecutionInput,
  ): Promise<PreparedRuntimeContext> {
    const prepared: PreparedRuntimeContext = {
      prompt: input.prompt ?? run.prompt ?? null,
      sandbox_cwd: input.sandbox_cwd ?? null,
      context_text: input.context_text ?? null,
      adapter_config: { ...(input.adapter_config ?? {}) },
      risk_level: input.risk_level ?? null,
      cleanup: null,
      sandbox_kind: null,
      base_commit_sha: null,
    };

    try {
      if (isVendorCliAdapter(run.adapter_type) && !prepared.sandbox_cwd) {
        const scope = workingDirScopeForLevel(run.required_sandbox_level);
        if (scope === "ephemeral") {
          // Run-scope sandbox: TS owns provisioning + teardown of a throwaway
          // working dir. No Python workspace.prepare port, no git, no workspace.
          prepared.sandbox_cwd = await prepareEphemeralDir(
            this.config.sandboxRoot,
            run.space_id,
            run.id,
          );
          prepared.cleanup = {
            cleanup_kind: EPHEMERAL_CLEANUP_KIND,
            sandbox_cwd: prepared.sandbox_cwd,
            workspace_root: null,
          };
          prepared.sandbox_kind = "ephemeral";
          await this.repository.appendRunEvent({
            run_id: run.id,
            space_id: run.space_id,
            event_type: "sandbox_created",
            status: "succeeded",
            workspace_id: run.workspace_id,
            metadata_json: {
              required_sandbox_level: run.required_sandbox_level,
              sandbox_kind: "ephemeral",
            },
          });
        } else if (scope === "worktree") {
          const manager = this.adapters.workspaceManager;
          if (!manager) {
            throw new RunPreparationError(
              "workspace_prepare_failed",
              "TS run execution requires a native workspace manager for worktree sandbox.",
            );
          }
          const workspaceResult = await manager.prepareRunWorkspace(run);
          prepared.sandbox_cwd = workspaceResult.sandbox_cwd;
          prepared.cleanup = {
            cleanup_kind: workspaceResult.cleanup_kind,
            sandbox_cwd: prepared.sandbox_cwd,
            workspace_root: workspaceResult.workspace_root,
          };
          prepared.sandbox_kind = workspaceResult.sandbox_kind;
          prepared.base_commit_sha = workspaceResult.base_commit_sha;
          if (prepared.sandbox_cwd) {
            await this.repository.appendRunEvent({
              run_id: run.id,
              space_id: run.space_id,
              event_type: "sandbox_created",
              status: "succeeded",
              workspace_id: run.workspace_id,
              metadata_json: {
                required_sandbox_level: run.required_sandbox_level,
                sandbox_kind: workspaceResult.sandbox_kind,
                base_commit_sha: workspaceResult.base_commit_sha,
                workspace_is_dirty: workspaceResult.workspace_is_dirty,
              },
            });
          }
        }
      }

      const contextPreparer = this.adapters.contextPreparer;
      if (!contextPreparer) {
        return prepared;
      }
      const contextResult = await contextPreparer.prepare({
        runId: run.id,
        spaceId: run.space_id,
        adapterType: run.adapter_type,
        sandboxCwd: prepared.sandbox_cwd,
        targetFormat: targetFormatForAdapter(run.adapter_type),
        workspacePath: prepared.cleanup?.workspace_root ?? null,
      });
      prepared.prompt = contextResult.runtime_prompt ?? prepared.prompt;
      if (contextResult.context_rendered) {
        prepared.context_text = null;
        prepared.adapter_config.context_file_already_rendered = true;
        prepared.adapter_config.context_target_format = contextResult.target_format ?? null;
      }
      return prepared;
    } catch (error) {
      await this.cleanupRuntimeContext(prepared, run);
      throw toRunPreparationError(error, "context_prepare_failed");
    }
  }

  private async callPreparationPort(
    ports: RunPreparationPortClient,
    request: RunPythonContextPortRequest,
    fallbackCode: string,
  ): Promise<RunPythonContextPortResponse> {
    try {
      const response = await ports.call(request);
      if (response.status !== "succeeded") {
        throw new RunPreparationError(
          response.error_code ?? fallbackCode,
          response.message ?? `${request.operation} did not succeed.`,
        );
      }
      return response;
    } catch (error) {
      throw toRunPreparationError(error, fallbackCode);
    }
  }

  private async cleanupRuntimeContext(
    prepared: PreparedRuntimeContext | null,
    run: RunRecord,
  ): Promise<void> {
    if (!prepared?.cleanup) return;
    // TS-owned ephemeral dir: remove directly, never via the Python port.
    if (prepared.cleanup.cleanup_kind === EPHEMERAL_CLEANUP_KIND) {
      try {
        await removeEphemeralDir(this.config.sandboxRoot, prepared.cleanup.sandbox_cwd);
      } catch {
        return;
      }
      prepared.cleanup = null;
      return;
    }
    if (!this.adapters.workspaceManager) return;
    try {
      await this.adapters.workspaceManager.cleanupRunWorkspace({
        runId: run.id,
        spaceId: run.space_id,
        cleanupKind: prepared.cleanup.cleanup_kind,
        sandboxCwd: prepared.cleanup.sandbox_cwd,
        workspaceRoot: prepared.cleanup.workspace_root,
      });
    } catch {
      return;
    }
    prepared.cleanup = null;
  }

  private async collectCodePatch(
    run: RunRecord,
    prepared: PreparedRuntimeContext | null,
  ): Promise<{ item: RunMaterializationItemSummary; errors: string[] } | null> {
    if (
      prepared?.sandbox_kind !== "worktree" ||
      !prepared.sandbox_cwd ||
      !this.adapters.codePatchCollector
    ) {
      return null;
    }
    return this.adapters.codePatchCollector.collect({
      run,
      worktreePath: prepared.sandbox_cwd,
      baseCommitSha: prepared.base_commit_sha,
    });
  }

  private async invokeAdapter(
    run: RunRecord,
    input: RunExecutionInput,
  ): Promise<RunAdapterResultEnvelope> {
    const promise = this.invokeAdapterUnbounded(run, input);
    if (!input.timeout_ms || input.timeout_ms <= 0) return promise;
    return withTimeout(
      promise,
      input.timeout_ms,
      adapterTimeoutEnvelope(run, input.timeout_ms),
    );
  }

  private async invokeAdapterUnbounded(
    run: RunRecord,
    input: RunExecutionInput,
  ): Promise<RunAdapterResultEnvelope> {
    if (run.adapter_type === "model_api" || run.adapter_type === "ts_agent_host") {
      return executeManagedApiNoToolAdapter(
        this.config,
        {
          run,
          model_provider_id: run.model_provider_id,
          model: input.model ?? null,
          system_prompt: input.system_prompt ?? run.system_prompt ?? null,
          prompt: input.prompt ?? null,
          max_tokens: input.max_tokens ?? null,
        },
        this.adapters.managedApi,
      );
    }
    if (run.adapter_type === "claude_code" || run.adapter_type === "codex_cli") {
      return executeVendorCliAdapter(
        this.config,
        {
          run,
          prompt: input.prompt ?? null,
          model: input.model ?? null,
          sandbox_cwd: input.sandbox_cwd ?? null,
          context_text: input.context_text ?? null,
          adapter_config: input.adapter_config ?? {},
          risk_level: input.risk_level ?? null,
          process_registry: this.adapters.processRegistry,
        },
        this.adapters.vendorCli,
      );
    }
    return adapterFailureEnvelope(
      run,
      "runtime_adapter_not_implemented",
      `Runtime adapter '${run.adapter_type ?? "unknown"}' is not executable in TS runs.`,
    );
  }

  private async appendMaterializationEvents(
    run: RunRecord,
    items: RunMaterializationItemSummary[],
  ): Promise<void> {
    for (const item of items) {
      if (item.kind === "artifact") {
        await this.repository.appendRunEvent({
          run_id: run.id,
          space_id: run.space_id,
          event_type: "artifact_ingested",
          status: materializationEventStatus(item),
          artifact_id: item.artifact_id ?? null,
          workspace_id: run.workspace_id,
          error_code: item.error_code ?? null,
          error_message: item.error_message ?? null,
          metadata_json: {
            source: "adapter_output",
            ...recordValue(item.metadata_json),
          },
        });
      } else if (item.kind === "code_patch") {
        await this.repository.appendRunEvent({
          run_id: run.id,
          space_id: run.space_id,
          event_type: "patch_collected",
          status: materializationEventStatus(item),
          proposal_id: item.proposal_id ?? null,
          workspace_id: run.workspace_id,
          error_code: item.error_code ?? null,
          error_message: item.error_message ?? null,
          metadata_json: {
            source: "worktree",
            ...recordValue(item.metadata_json),
          },
        });
        if (item.proposal_id) {
          await this.repository.appendRunEvent({
            run_id: run.id,
            space_id: run.space_id,
            event_type: "proposal_created",
            status: materializationEventStatus(item),
            proposal_id: item.proposal_id,
            workspace_id: run.workspace_id,
            error_code: item.error_code ?? null,
            error_message: item.error_message ?? null,
            metadata_json: {
              source: "worktree",
              kind: item.kind,
              ...recordValue(item.metadata_json),
            },
          });
        }
      } else if (item.kind === "proposal") {
        await this.repository.appendRunEvent({
          run_id: run.id,
          space_id: run.space_id,
          event_type: "proposal_created",
          status: materializationEventStatus(item),
          proposal_id: item.proposal_id ?? null,
          workspace_id: run.workspace_id,
          error_code: item.error_code ?? null,
          error_message: item.error_message ?? null,
          metadata_json: {
            source: "adapter_output",
            kind: item.kind,
            ...recordValue(item.metadata_json),
          },
        });
      } else {
        await this.repository.appendRunEvent({
          run_id: run.id,
          space_id: run.space_id,
          event_type: "artifact_ingested",
          status: materializationEventStatus(item),
          workspace_id: run.workspace_id,
          error_code: item.error_code ?? null,
          error_message: item.error_message ?? null,
          summary: "Output activity materialization failed",
          metadata_json: {
            kind: item.kind,
            source: "adapter_output",
            ...recordValue(item.metadata_json),
          },
        });
      }
    }
  }

  private async appendFinalizationEvent(
    run: RunRecord,
    item: RunMaterializationItemSummary,
  ): Promise<void> {
    await this.repository.appendRunEvent({
      run_id: run.id,
      space_id: run.space_id,
      event_type: "run_finalized",
      status: materializationEventStatus(item),
      error_code: item.error_code ?? null,
      error_message: item.error_message ?? null,
      summary: item.status === "succeeded" ? "Run finalized." : "Run finalization failed.",
      metadata_json: recordValue(item.metadata_json),
    });
  }
}

function terminalStatusFromAdapter(result: RunAdapterResultEnvelope): RunTerminalStatus {
  if (result.success) return "succeeded";
  if (result.error_code === "run_cancelled") return "cancelled";
  return "failed";
}

function adapterErrorJson(result: RunAdapterResultEnvelope): unknown {
  if (result.success) return {};
  return sanitizeEvidenceJson({
    error_code: result.error_code ?? "adapter_failed",
    error_text: result.error_message ?? "Runtime adapter failed.",
    adapter_type: result.adapter_type,
    adapter_kind: result.adapter_kind,
    exit_code: result.exit_code,
  });
}

function outputJsonWithMaterialization(
  outputJson: unknown,
  items: RunMaterializationItemSummary[],
  errors: string[],
): unknown {
  const output = recordValue(outputJson);
  if (items.length > 0) output.materialization = sanitizeEvidenceJson(items);
  if (errors.length > 0) output.materialization_errors = errors.map((error) => redactEvidenceText(error));
  return sanitizeEvidenceJson(output);
}

function materializationEventStatus(
  item: RunMaterializationItemSummary,
): "succeeded" | "failed" | "warning" | "skipped" {
  if (item.status === "succeeded") return "succeeded";
  if (item.status === "skipped") return "skipped";
  if (item.status === "warning") return "warning";
  return "failed";
}

function adapterFailureEnvelope(
  run: RunRecord,
  errorCode: string,
  message: string,
): RunAdapterResultEnvelope {
  const now = new Date().toISOString();
  return {
    adapter_type: run.adapter_type ?? "unknown",
    adapter_kind: "custom",
    success: false,
    output_text: "",
    output_json: { adapter_type: run.adapter_type ?? "unknown" },
    exit_code: 1,
    error_code: errorCode,
    error_message: redactEvidenceText(message),
    started_at: now,
    completed_at: now,
    usage: null,
    metadata_json: {
      adapter_type: run.adapter_type ?? "unknown",
    },
  };
}

function adapterTimeoutEnvelope(
  run: RunRecord,
  timeoutMs: number,
): RunAdapterResultEnvelope {
  const now = new Date().toISOString();
  return {
    adapter_type: run.adapter_type ?? "unknown",
    adapter_kind: run.adapter_type === "claude_code" || run.adapter_type === "codex_cli"
      ? "local_cli"
      : "managed_api",
    success: false,
    output_text: "",
    output_json: { adapter_type: run.adapter_type ?? "unknown" },
    exit_code: 1,
    error_code: "adapter_timeout",
    error_message: `Runtime adapter timed out after ${timeoutMs}ms.`,
    started_at: now,
    completed_at: now,
    usage: null,
    metadata_json: {
      adapter_type: run.adapter_type ?? "unknown",
      timeout_ms: timeoutMs,
    },
  };
}

function withTimeout<T>(
  promise: Promise<T>,
  timeoutMs: number,
  timeoutValue: T,
): Promise<T> {
  return new Promise((resolveValue, reject) => {
    const timer = setTimeout(() => resolveValue(timeoutValue), timeoutMs);
    promise.then(
      (value) => {
        clearTimeout(timer);
        resolveValue(value);
      },
      (error: unknown) => {
        clearTimeout(timer);
        reject(error);
      },
    );
  });
}

function inputWithPreparedRuntime(
  input: RunExecutionInput,
  prepared: PreparedRuntimeContext,
): RunExecutionInput {
  return {
    ...input,
    prompt: prepared.prompt,
    sandbox_cwd: prepared.sandbox_cwd,
    context_text: prepared.context_text,
    adapter_config: prepared.adapter_config,
    risk_level: prepared.risk_level ?? input.risk_level ?? null,
  };
}

function toRunPreparationError(error: unknown, fallbackCode: string): RunPreparationError {
  if (error instanceof RunPreparationError) return error;
  const code = errorCodeValue(error) ?? fallbackCode;
  return new RunPreparationError(code, errorMessage(error));
}

function errorCodeValue(error: unknown): string | null {
  if (error !== null && typeof error === "object") {
    const code = (error as { code?: unknown }).code;
    return typeof code === "string" && code ? code : null;
  }
  return null;
}

function isTerminalRunStatus(status: string): status is RunTerminalStatus | "waiting_for_review" {
  return [
    "succeeded",
    "failed",
    "degraded",
    "cancelled",
    "waiting_for_review",
  ].includes(status);
}

function isHardTerminalRunStatus(status: string): status is RunTerminalStatus {
  return ["succeeded", "failed", "degraded", "cancelled"].includes(status);
}

function protocolRunStatus(status: string): RunStatus | "unknown" {
  if (
    [
      "queued",
      "running",
      "succeeded",
      "failed",
      "degraded",
      "cancelled",
      "waiting_for_review",
    ].includes(status)
  ) {
    return status as RunStatus;
  }
  return "unknown";
}

function summarizeOutput(value: string | undefined): string | null {
  if (!value) return null;
  return redactEvidenceText(value.length > 500 ? `${value.slice(0, 500)}...` : value);
}

function errorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  if (typeof error === "string") return error;
  return "run orchestration failed";
}

function recordValue(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" && value ? value : null;
}
