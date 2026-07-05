import type {
  RunAdapterResultEnvelope,
  RunExecuteRequest,
  RunJobResult,
  RunMaterializationItemSummary,
} from "@agent-space/protocol" with { "resolution-mode": "import" };
import type { ServerConfig } from "../../config";
import { getDbPool } from "../../db/pool";
import {
  executeManagedApiNoToolAdapter,
  type ManagedApiNoToolAdapterDeps,
} from "./managedApiAdapter";
import {
  executeVendorCliAdapter,
  type VendorCliAdapterDeps,
} from "./vendorCliAdapter";
import { AgentGroupRunLifecycleProjector } from "../agentGroups/lifecycleProjector";
import type { CliProcessRegistry } from "./localCliExecution";
import type {
  PgRunRepository,
  RunEventInput,
  RunRecord,
  RunStepInput,
  RunStepRecord,
  RunTerminalUpdate,
} from "./repository";
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
import { loadActionRegistry } from "../policy/actionRegistry";
import { enforce, type EnforceResult } from "../policy/service";
import { RuntimeToolRegistry } from "../runtimeTools";
import { resolveRuntimeToolVersionForSpace } from "../runtimeTools/policies";
import { RunApprovalRequiredError, RunPreparationError } from "./orchestrationErrors";
import {
  adapterErrorJson,
  adapterFailureEnvelope,
  adapterTimeoutEnvelope,
  errorMessage,
  inputWithPreparedRuntime,
  isHardTerminalRunStatus,
  isTerminalRunStatus,
  materializationEventStatus,
  outputJsonWithMaterialization,
  protocolRunStatus,
  recordValue,
  summarizeOutput,
  terminalStatusFromAdapter,
  toRunPreparationError,
  waitingForDependencyFromAdapter,
  withTimeout,
} from "./orchestrationResults";

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
  markRunDegraded?(input: {
    run_id: string;
    space_id: string;
    completed_at: string;
    error_code: string;
    error_message: string;
  }): Promise<RunRecord | null>;
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
  markRunWaitingForReview(input: {
    run_id: string;
    space_id: string;
    approval_code: string;
    message: string;
    paused_at: string;
  }): Promise<RunRecord | null>;
  markRunWaitingForDependency(input: {
    run_id: string;
    space_id: string;
    output_json: unknown;
    paused_at: string;
  }): Promise<RunRecord | null>;
}

export interface RunExecutionAdapterDeps {
  managedApi?: ManagedApiNoToolAdapterDeps;
  vendorCli?: VendorCliAdapterDeps;
  materializer?: RunMaterializationService;
  contextPreparer?: RunContextPrepareClient;
  workspaceManager?: RunWorkspaceManagerPort;
  codePatchCollector?: RunCodePatchCollectorPort;
  policyEnforcer?: RunPolicyEnforcer;
  runtimeToolVersionResolver?: RunRuntimeToolVersionResolver;
  delegationProjector?: RunDelegationLifecycleProjectorPort;
  /**
   * Shared CLI process registry. Execute registers spawned CLI processes here;
   * cancelRun terminates them through it. Must be the same instance across the
   * HTTP routes and the job worker so a stop from another request can reach a
   * running process.
   */
  processRegistry?: CliProcessRegistry;
}

export interface RunDelegationLifecycleProjectorPort {
  markDelegatedRunRunning(run: RunRecord): Promise<void>;
  markDelegatedRunTerminal(run: RunRecord): Promise<void>;
}

export type RunPolicyEnforcer = (
  request: Parameters<typeof enforce>[2],
) => Promise<EnforceResult>;

export type RunRuntimeToolVersionResolver = (input: {
  spaceId: string;
  runtime: string;
  requestedVersion: string | null;
}) => Promise<string>;

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

export class RunOrchestrationService {
  private readonly delegationProjector: RunDelegationLifecycleProjectorPort | null;

  constructor(
    private readonly config: ServerConfig,
    private readonly repository: RunExecutionRepositoryPort | PgRunRepository,
    private readonly adapters: RunExecutionAdapterDeps = {},
  ) {
    this.delegationProjector =
      adapters.delegationProjector ?? AgentGroupRunLifecycleProjector.fromConfig(config);
  }

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
    if (run.status === "waiting_for_dependency") {
      return {
        run_id: run.id,
        status: "waiting_for_dependency",
        skipped: true,
        skip_reason: "run_waiting_for_dependency",
      };
    }

    const locked = await this.repository.tryAcquireExecutionLock({
      run_id: run.id,
      worker_id: input.worker_id,
      job_id: input.job_id ?? null,
    });
    if (!locked) {
      // Duplicate execution returns the error result without writing run
      // evidence (event_type has a closed CHECK constraint).
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
      await this.markDelegatedRunRunningBestEffort(running);

      // Policy gate + server-owned adapter resolution first. The run row and
      // agent/runtime configuration own the adapter and sandbox level; request
      // bodies never override executable paths, permissions, or runtime policy.
      const resolved = await this.enforceRuntimePolicy(running, input);
      const effectiveRun: RunRecord = {
        ...running,
        adapter_type: resolved.adapter_type,
        // Honor the policy-resolved sandbox level (e.g. ephemeral for a
        // no-workspace CLI run); the stored row level is the creation-time
        // default and is not re-derived under server authority.
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
      // the database CHECK constraint lists (ck_run_events_event_type,
      // ck_run_steps_step_type).
      const actorId = await this.repository.resolveRunActorId(
        effectiveRun,
        input.command_source,
      );
      step = await this.createRunStepBestEffort({
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
      await this.appendRunEventBestEffort({
        run_id: effectiveRun.id,
        space_id: effectiveRun.space_id,
        event_type: "adapter_invoked",
        status: "running",
        step_id: step?.id ?? null,
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
      const completedAt = adapterResult.completed_at ?? new Date().toISOString();
      const waitingForDependency = waitingForDependencyFromAdapter(adapterResult);
      if (waitingForDependency) {
        const waitingRun = await this.repository.markRunWaitingForDependency({
          run_id: running.id,
          space_id: running.space_id,
          output_json: outputJsonWithMaterialization(adapterResult.output_json, [], []),
          paused_at: completedAt,
        });
        if (!waitingRun) {
          const current = await this.repository.getRun(running.space_id, running.id);
          const currentStatus = protocolRunStatus(current?.status ?? "cancelled");
          if (step) await this.updateRunStepStatusBestEffort({
            step_id: step.id,
            run_id: running.id,
            space_id: running.space_id,
            status: "cancelled",
            ended_at: completedAt,
            error_type: "run_cancelled",
            error_message: "Adapter paused after the run was cancelled; wait state not applied.",
          });
          await this.appendRunEventBestEffort({
            run_id: running.id,
            space_id: running.space_id,
            event_type: "adapter_completed",
            status: "cancelled",
            step_id: step?.id ?? null,
            summary: "Adapter paused after the run was cancelled; wait state not applied.",
            error_code: "run_cancelled",
            workspace_id: running.workspace_id,
            metadata_json: {
              adapter_type: adapterResult.adapter_type,
              adapter_kind: adapterResult.adapter_kind,
            },
          });
          return {
            run_id: running.id,
            status: currentStatus,
            skipped: true,
            skip_reason: "run_already_terminal",
          };
        }
        if (step) await this.updateRunStepStatusBestEffort({
          step_id: step.id,
          run_id: running.id,
          space_id: running.space_id,
          status: "succeeded",
          ended_at: completedAt,
          output_summary: "Waiting for room agent results.",
        });
        await this.appendRunEventBestEffort({
          run_id: running.id,
          space_id: running.space_id,
          event_type: "adapter_completed",
          status: "warning",
          step_id: step?.id ?? null,
          summary: "Runtime adapter paused while waiting for room agent results.",
          workspace_id: running.workspace_id,
          metadata_json: {
            adapter_type: adapterResult.adapter_type,
            adapter_kind: adapterResult.adapter_kind,
            waiting_for_results: waitingForDependency,
          },
        });
        return {
          run_id: waitingRun.id,
          status: "waiting_for_dependency",
          metadata_json: { waiting_for_results: waitingForDependency } as RunJobResult["metadata_json"],
        };
      }
      const adapterTerminalStatus = terminalStatusFromAdapter(adapterResult);
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
      const terminalStatus = adapterResult.success && materialization.errors.length > 0
        ? "degraded"
        : adapterTerminalStatus;

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
        if (step) await this.updateRunStepStatusBestEffort({
          step_id: step.id,
          run_id: running.id,
          space_id: running.space_id,
          status: "cancelled",
          ended_at: completedAt,
          error_type: "run_cancelled",
          error_message: "Adapter finished after the run was cancelled; result not applied.",
        });
        await this.appendRunEventBestEffort({
          run_id: running.id,
          space_id: running.space_id,
          event_type: "adapter_completed",
          status: "cancelled",
          step_id: step?.id ?? null,
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
      let finalTerminalRun = terminalRun;
      await this.appendMaterializationEvents(running, materialization.items);
      if (step) await this.updateRunStepStatusBestEffort({
        step_id: step.id,
        run_id: running.id,
        space_id: running.space_id,
        status: adapterResult.success ? "succeeded" : "failed",
        ended_at: completedAt,
        output_summary: adapterResult.success ? summarizeOutput(adapterResult.output_text) : null,
        error_type: adapterResult.error_code ?? null,
        error_message: adapterResult.error_message ?? null,
      });
      await this.appendRunEventBestEffort({
        run_id: running.id,
        space_id: running.space_id,
        event_type: "adapter_completed",
        status: adapterResult.success ? "succeeded" : "failed",
        step_id: step?.id ?? null,
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
      let returnedStatus = terminalStatus;
      if (this.adapters.materializer && isTerminalRunStatus(terminalStatus)) {
        const finalization = await this.adapters.materializer.finalizeRun({
          ...running,
          status: terminalStatus,
          ended_at: completedAt,
        });
        if (finalization.status !== "succeeded") {
          await this.appendFinalizationEvent(running, finalization);
          if (adapterResult.success && terminalStatus === "succeeded") {
            const degraded = await this.markRunDegradedBestEffort({
              run_id: running.id,
              space_id: running.space_id,
              completed_at: completedAt,
              error_code: finalization.error_code ?? "finalization_failed",
              error_message: finalization.error_message ?? "Run finalization failed.",
            });
            if (degraded) {
              returnedStatus = "degraded";
              finalTerminalRun = degraded;
            }
          }
        }
      }
      await this.markDelegatedRunTerminalBestEffort(finalTerminalRun);

      return {
        run_id: running.id,
        status: returnedStatus,
        error_code: adapterResult.error_code ?? null,
        error_text: adapterResult.error_message ?? null,
      };
    } catch (error) {
      const completedAt = new Date().toISOString();
      const message = errorMessage(error);
      if (error instanceof RunApprovalRequiredError) {
        await this.repository.markRunWaitingForReview({
          run_id: run.id,
          space_id: run.space_id,
          approval_code: error.code,
          message,
          paused_at: completedAt,
        });
        return {
          run_id: run.id,
          status: "waiting_for_review",
          error_code: error.code,
        };
      }
      const errorCode =
        error instanceof RunPreparationError ? error.code : "run_orchestration_failed";
      const failedRun = await this.repository.markRunTerminal({
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
      if (failedRun) await this.markDelegatedRunTerminalBestEffort(failedRun);
      if (step) {
        await this.updateRunStepStatusBestEffort({
          step_id: step.id,
          run_id: run.id,
          space_id: run.space_id,
          status: "failed",
          ended_at: completedAt,
          error_type: errorCode,
          error_message: message,
        });
      }
      await this.appendRunEventBestEffort({
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
    // queued, running, waiting_for_review, and waiting_for_dependency runs are cancellable;
    // hard-terminal runs are a no-op.
    if (isHardTerminalRunStatus(run.status)) {
      return {
        run_id: run.id,
        status: protocolRunStatus(run.status),
        skipped: true,
        skip_reason: "run_already_terminal",
      };
    }

    // SIGTERM a server-registered CLI subprocess before the DB status change
    // (best-effort).
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
    await this.markDelegatedRunTerminalBestEffort(updated);
    // Cancellation evidence lives on the run row (error_json carries requester
    // + process_terminated); no run_event is appended (event_type has a closed
    // CHECK constraint with no cancel type).
    return { run_id: run.id, status: "cancelled", error_code: "run_cancelled" };
  }

  /**
   * Enforce runtime.execute using the server policy service. Caller-supplied
   * adapter config is only a local base passed by trusted internal callers;
   * executable paths, permission bypass, and runtime policy never come from
   * the public request.
   * A non-allowed decision throws RunPreparationError (mapped to a terminal
   * failed run by the executeRun catch block).
   */
  private async enforceRuntimePolicy(
    run: RunRecord,
    input: RunExecutionInput,
  ): Promise<ResolvedRuntimePolicy> {
    const runtimeConfig = recordValue(run.runtime_config_json);
    const callerConfig = input.command_source === "http" ? {} : input.adapter_config ?? {};
    const base: ResolvedRuntimePolicy = {
      adapter_type: run.adapter_type,
      adapter_config: { ...runtimeConfig, ...callerConfig },
      risk_level: input.risk_level ?? null,
      required_sandbox_level: run.required_sandbox_level ?? null,
    };
    const policyRequest: Parameters<typeof enforce>[2] = {
      action: "runtime.execute",
      actor_type: "run",
      actor_id: run.id,
      space_id: run.space_id,
      resource_type: "runtime",
      resource_id: run.adapter_type ?? "default",
      resource_space_id: run.space_id,
      run_id: run.id,
      context: {
        adapter_type: run.adapter_type,
        command_source: input.command_source,
        risk_level: base.risk_level,
        required_sandbox_level: base.required_sandbox_level,
      },
      metadata_json: {
        adapter_type: run.adapter_type,
        command_source: input.command_source,
        required_sandbox_level: base.required_sandbox_level,
      },
      force_record: false,
    };
    if (!this.hasGrantedApproval(run, "policy_requires_approval_runtime_execute")) {
      await this.enforcePolicyRequest(
        policyRequest,
        "policy_requires_approval_runtime_execute",
        "policy_denied_runtime_execute",
        "runtime.execute denied by policy.",
      );
    }
    if (run.model_provider_id && !this.hasGrantedApproval(run, "policy_requires_approval_runtime_use_credential")) {
      await this.enforcePolicyRequest(
        {
          action: "runtime.use_credential",
          actor_type: "run",
          actor_id: run.id,
          space_id: run.space_id,
          resource_type: "model_provider",
          resource_id: run.model_provider_id,
          resource_space_id: run.space_id,
          run_id: run.id,
          context: {
            adapter_type: run.adapter_type,
            command_source: input.command_source,
            trigger_origin: run.trigger_origin,
            risk_level: base.risk_level,
          },
          metadata_json: {
            adapter_type: run.adapter_type,
            command_source: input.command_source,
            trigger_origin: run.trigger_origin,
            credential_kind: "model_provider",
            provider_id: run.model_provider_id,
          },
          force_record: false,
        },
        "policy_requires_approval_runtime_use_credential",
        "policy_denied_runtime_use_credential",
        "runtime.use_credential denied by policy.",
      );
    }
    if (isVendorCliAdapter(run.adapter_type)) {
      const credentialProfileId = stringConfigValue(base.adapter_config.credential_profile_id);
      const requestedRuntimeToolVersion = stringConfigValue(base.adapter_config.runtime_tool_version);
      try {
        base.adapter_config.runtime_tool_version = await this.resolveRuntimeToolVersion({
          spaceId: run.space_id,
          runtime: run.adapter_type ?? "",
          requestedVersion: requestedRuntimeToolVersion,
        });
      } catch (error) {
        throw new RunPreparationError(
          "runtime_tool_version_unavailable",
          error instanceof Error ? error.message : "Runtime tool version is unavailable.",
        );
      }
      if (!this.hasGrantedApproval(run, "policy_requires_approval_runtime_use_credential")) {
        await this.enforcePolicyRequest(
          {
            action: "runtime.use_credential",
            actor_type: "run",
            actor_id: run.id,
            space_id: run.space_id,
            resource_type: "cli_credential_profile",
            resource_id: credentialProfileId ?? `${run.adapter_type ?? "cli"}:default`,
            resource_space_id: run.space_id,
            run_id: run.id,
            context: {
              adapter_type: run.adapter_type,
              command_source: input.command_source,
              trigger_origin: run.trigger_origin,
              credential_profile_id: credentialProfileId,
              risk_level: base.risk_level,
            },
            metadata_json: {
              adapter_type: run.adapter_type,
              command_source: input.command_source,
              trigger_origin: run.trigger_origin,
              credential_kind: "cli_profile",
              credential_profile_id: credentialProfileId,
            },
            force_record: false,
          },
          "policy_requires_approval_runtime_use_credential",
          "policy_denied_runtime_use_credential",
          "runtime.use_credential denied by policy.",
        );
      }
    }
    return base;
  }

  private async resolveRuntimeToolVersion(input: {
    spaceId: string;
    runtime: string;
    requestedVersion: string | null;
  }): Promise<string> {
    if (this.adapters.runtimeToolVersionResolver) {
      return this.adapters.runtimeToolVersionResolver(input);
    }
    if (!this.config.databaseUrl) {
      throw new Error("SERVER_DATABASE_URL is required");
    }
    return resolveRuntimeToolVersionForSpace(
      getDbPool(this.config.databaseUrl),
      new RuntimeToolRegistry(this.config),
      input.spaceId,
      input.runtime,
      input.requestedVersion,
    );
  }

  private async enforcePolicyRequest(
    policyRequest: Parameters<typeof enforce>[2],
    requiresApprovalCode: string,
    deniedCode: string,
    fallbackMessage: string,
  ): Promise<void> {
    const policy = this.adapters.policyEnforcer
      ? await this.adapters.policyEnforcer(policyRequest)
      : await enforce(this.config, await loadActionRegistry(), policyRequest);
    if (policy.status !== "allow") {
      if (policy.error_code === "policy_requires_approval") {
        throw new RunApprovalRequiredError(requiresApprovalCode, policy.message ?? fallbackMessage);
      }
      throw new RunPreparationError(deniedCode, policy.message ?? fallbackMessage);
    }
  }

  private hasGrantedApproval(run: RunRecord, approvalCode: string): boolean {
    const snap = recordValue(run.permission_snapshot_json);
    const grants = snap?.policy_grants;
    if (!Array.isArray(grants)) return false;
    return grants.some(
      (g) => typeof g === "object" && g !== null && (g as Record<string, unknown>).approval_code === approvalCode,
    );
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
          // Run-scope sandbox: the server owns provisioning + teardown of a throwaway
          // working dir. No git, no persistent workspace.
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
          await this.appendRunEventBestEffort({
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
              "server run execution requires a native workspace manager for worktree sandbox.",
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
            await this.appendRunEventBestEffort({
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
      prepared.context_text = contextResult.runtime_context_text ?? prepared.context_text;
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

  private async cleanupRuntimeContext(
    prepared: PreparedRuntimeContext | null,
    run: RunRecord,
  ): Promise<void> {
    if (!prepared?.cleanup) return;
    // server-owned ephemeral dir: remove directly.
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
          model: input.model ?? null,
          system_prompt: input.system_prompt ?? run.system_prompt ?? null,
          prompt: input.prompt ?? null,
          context_text: input.context_text ?? null,
          context_snapshot_id: run.context_snapshot_id,
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
      `Runtime adapter '${run.adapter_type ?? "unknown"}' is not executable in server runs.`,
    );
  }

  private async appendMaterializationEvents(
    run: RunRecord,
    items: RunMaterializationItemSummary[],
  ): Promise<void> {
    for (const item of items) {
      if (item.kind === "artifact") {
        await this.appendRunEventBestEffort({
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
        await this.appendRunEventBestEffort({
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
          await this.appendRunEventBestEffort({
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
        await this.appendRunEventBestEffort({
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
      } else if (item.kind === "delegation") {
        const metadata = recordValue(item.metadata_json);
        if (metadata.service_event_written === true) continue;
        await this.appendRunEventBestEffort({
          run_id: run.id,
          space_id: run.space_id,
          event_type: "delegation_requested",
          status: materializationEventStatus(item),
          workspace_id: run.workspace_id,
          error_code: item.error_code ?? null,
          error_message: item.error_message ?? null,
          summary: "Runtime delegation materialization failed",
          metadata_json: {
            source: "adapter_output",
            kind: item.kind,
            ...metadata,
          },
        });
      } else {
        await this.appendRunEventBestEffort({
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
    await this.appendRunEventBestEffort({
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

  private async createRunStepBestEffort(input: RunStepInput): Promise<RunStepRecord | null> {
    try {
      return await this.repository.createRunStep(input);
    } catch {
      return null;
    }
  }

  private async updateRunStepStatusBestEffort(
    input: Parameters<RunExecutionRepositoryPort["updateRunStepStatus"]>[0],
  ): Promise<boolean> {
    try {
      return await this.repository.updateRunStepStatus(input);
    } catch {
      return false;
    }
  }

  private async appendRunEventBestEffort(input: RunEventInput): Promise<void> {
    try {
      await this.repository.appendRunEvent(input);
    } catch {
      return;
    }
  }

  private async markDelegatedRunRunningBestEffort(run: RunRecord): Promise<void> {
    try {
      await this.delegationProjector?.markDelegatedRunRunning(run);
    } catch {
      return;
    }
  }

  private async markDelegatedRunTerminalBestEffort(run: RunRecord): Promise<void> {
    try {
      await this.delegationProjector?.markDelegatedRunTerminal(run);
    } catch {
      return;
    }
  }

  private async markRunDegradedBestEffort(input: {
    run_id: string;
    space_id: string;
    completed_at: string;
    error_code: string;
    error_message: string;
  }): Promise<RunRecord | null> {
    try {
      return await this.repository.markRunDegraded?.(input) ?? null;
    } catch {
      return null;
    }
  }
}

function stringConfigValue(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}
