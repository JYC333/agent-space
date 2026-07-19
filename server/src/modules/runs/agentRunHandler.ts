import type { ServerConfig } from "../../config";
import { getDbPool } from "../../db/pool";
import { RunMaterializationService } from "./materializationService";
import { RunOrchestrationService } from "./orchestrationService";
import { PgRunRepository } from "./repository";
import { sharedCliProcessRegistry } from "./processRegistry";
import { ContextPrepareService } from "../context";
import { PgCodePatchCollector, PgWorkspaceManager } from "../workspaces";
import { PgVerificationEngine } from "./verification";
import type { JobEnvelopeForHandler, JobHandlerRegistry } from "../jobs/handlerRegistry";
import type { JobHandlerResult } from "../jobs/handlerRegistry";
import { PgJobQueueRepository } from "../jobs/repository";
import type { RuntimeHostLogger } from "../runtimeHost";

export function registerAgentRunHandler(
  registry: JobHandlerRegistry,
  config: ServerConfig,
  runtimeHostLogger?: RuntimeHostLogger,
): void {
  if (!config.databaseUrl) return;

  const repository = PgRunRepository.fromConfig(config);
  const materializer = RunMaterializationService.fromConfig(config);
  const contextPreparer = new ContextPrepareService(config);
  const orchestration = new RunOrchestrationService(config, repository, {
    materializer,
    contextPreparer,
    workspaceManager: PgWorkspaceManager.fromConfig(config),
    codePatchCollector: PgCodePatchCollector.fromConfig(config),
    verificationEngine: PgVerificationEngine.fromConfig(config),
    processRegistry: sharedCliProcessRegistry,
    managedApi: { runtimeHostLogger },
  });

  registry.register("agent_run", async (job) => handleAgentRun(job, orchestration, config));
}

async function handleAgentRun(
  job: JobEnvelopeForHandler,
  orchestration: RunOrchestrationService,
  config: ServerConfig,
): Promise<JobHandlerResult> {
  const runId = stringValue(job.payload.run_id);
  if (!runId) {
    throw new Error(
      "agent_run payload requires run_id under the server runs authority; " +
        "task_id/agent_id create-and-execute payloads are not supported",
    );
  }
  if (!job.user_id) {
    throw new Error("agent_run job requires user_id");
  }
  const result = await orchestration.executeRun({
    run_id: runId,
    space_id: job.space_id,
    worker_id: job.worker_id,
    job_id: job.job_id,
    command_source: "job",
  });
  // Research runs use the normal Run/Materialization authority. This hook is
  // only a latency optimization: the reconciler observes the committed run
  // and advances the owning Project Research operation.
  if (result.status === "succeeded" || result.status === "failed" || result.status === "degraded" || result.status === "cancelled") {
    try {
      await new PgJobQueueRepository(getDbPool(config.databaseUrl!)).enqueue({
        job_type: "project_research_reconcile",
        space_id: job.space_id,
        user_id: job.user_id,
        payload: { run_id: runId, reason: "agent_run_terminal" },
      });
    } catch {
      // Preserve the completed Run if the latency nudge cannot be queued;
      // the periodic project research reconciler remains the recovery path.
    }
  }
  return result;
}

export async function enqueueAgentRunJob(
  config: ServerConfig,
  input: {
    run_id: string;
    space_id: string;
    user_id: string;
    agent_id?: string | null;
    workspace_id?: string | null;
    payload?: Record<string, unknown>;
  },
): Promise<void> {
  if (!config.databaseUrl) {
    throw new Error("enqueueAgentRunJob requires SERVER_DATABASE_URL");
  }
  const queue = new PgJobQueueRepository(getDbPool(config.databaseUrl));
  await queue.enqueue({
    job_type: "agent_run",
    space_id: input.space_id,
    user_id: input.user_id,
    agent_id: input.agent_id ?? null,
    workspace_id: input.workspace_id ?? null,
    payload: {
      run_id: input.run_id,
      ...(input.payload ?? {}),
    },
  });
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}
