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

export function registerAgentRunHandler(
  registry: JobHandlerRegistry,
  config: ServerConfig,
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
  });

  registry.register("agent_run", async (job) => handleAgentRun(job, orchestration));
}

async function handleAgentRun(
  job: JobEnvelopeForHandler,
  orchestration: RunOrchestrationService,
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
  return orchestration.executeRun({
    run_id: runId,
    space_id: job.space_id,
    worker_id: job.worker_id,
    job_id: job.job_id,
    command_source: "job",
  });
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
