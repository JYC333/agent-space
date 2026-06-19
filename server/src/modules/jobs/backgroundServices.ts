import type { ServerConfig } from "../../config";
import { getDbPool } from "../../db/pool";
import { startSchedulerRegistry, type ScheduledTask } from "./schedulerRegistry";
import { scanDailyReportsAndEnqueue } from "../dailyReports/scheduler";
import { scanAutomationsAndFire } from "../automations/scheduler";
import { runScheduledBackup } from "../backups/service";
import { IntakeExtractionWorker } from "../intake/extractionWorker";
import { PgJobQueueRepository } from "./repository";
import { startJobsWorker, type JobsWorkerHandle } from "./workerRuntime";
import type { PluginHost } from "../plugins/host";

export interface BackgroundServicesHandle {
  worker: JobsWorkerHandle | null;
  scheduler: { stop(): Promise<void> };
}

export function startBackgroundServices(
  config: ServerConfig,
  log?: {
    info(message: string): void;
    warn(message: string): void;
    error(message: string): void;
  },
  pluginHost?: PluginHost,
): BackgroundServicesHandle {
  const worker = startJobsWorker(config, log, pluginHost);
  const tasks: ScheduledTask[] = [
    // Plugin-contributed scheduler tasks (fan out to enabled users internally).
    ...(pluginHost?.getSchedulerTasks() ?? []),
  ];

  if (config.dailyReportSchedulerEnabled && worker) {
    tasks.push({
      name: "daily_report_scheduler",
      intervalSeconds: config.dailyReportSchedulerIntervalSeconds,
      run: async () => {
        const enqueued = await scanDailyReportsAndEnqueue(config, worker.queue);
        if (enqueued > 0) log?.info(`[scheduler] daily_report enqueued ${enqueued} job(s)`);
      },
      runOnStart: true,
    });
  }

  if (config.automationSchedulerEnabled) {
    tasks.push({
      name: "automation_scheduler",
      intervalSeconds: config.automationSchedulerIntervalSeconds,
      run: async () => {
        const fired = await scanAutomationsAndFire(config);
        if (fired > 0) log?.info(`[scheduler] automation fired ${fired} automation(s)`);
      },
      runOnStart: true,
    });
  }

  if (config.memoryAccessLogRetentionEnabled && config.databaseUrl) {
    tasks.push({
      name: "memory_access_log_retention",
      intervalSeconds: config.memoryAccessLogPruneIntervalSeconds,
      run: async () => {
        const deleted = await pruneMemoryAccessLogs(config);
        if (deleted > 0) log?.info(`[scheduler] memory_access_log pruned ${deleted} row(s)`);
      },
      runOnStart: false,
    });
  }

  if (config.intakeExtractionSchedulerEnabled && config.databaseUrl) {
    tasks.push({
      name: "intake_extraction_scheduler",
      intervalSeconds: config.intakeExtractionSchedulerIntervalSeconds,
      run: async () => {
        const processed = await processPendingIntakeJobs(config, log);
        if (processed > 0) log?.info(`[scheduler] intake processed ${processed} extraction job(s)`);
      },
      runOnStart: true,
    });
  }

  if (config.backupEnabled) {
    tasks.push({
      name: "backup_scheduler",
      intervalSeconds: config.backupIntervalHours * 3600,
      run: async () => {
        await runScheduledBackup(config);
        log?.info("[scheduler] backup_scheduler completed tick");
      },
      runOnStart: config.backupOnStartup,
      awaitRunOnStart: false,
    });
  }

  const scheduler = startSchedulerRegistry(tasks, log);
  return { worker, scheduler };
}

export async function pruneMemoryAccessLogs(config: ServerConfig): Promise<number> {
  if (!config.databaseUrl) return 0;
  const db = getDbPool(config.databaseUrl);
  const cutoff = new Date(
    Date.now() - config.memoryAccessLogRetentionDays * 24 * 60 * 60 * 1000,
  ).toISOString();
  const result = await db.query(
    `DELETE FROM memory_access_logs WHERE accessed_at < $1`,
    [cutoff],
  );
  return result.rowCount ?? 0;
}

async function processPendingIntakeJobs(
  config: ServerConfig,
  log?: { warn(message: string): void },
): Promise<number> {
  if (!config.databaseUrl) return 0;
  const db = getDbPool(config.databaseUrl);
  const worker = new IntakeExtractionWorker(db, config);
  const pending = await db.query<{ id: string; space_id: string }>(
    `SELECT id, space_id
       FROM extraction_jobs
      WHERE status = 'pending'
      ORDER BY created_at ASC
      LIMIT 10`,
  );
  let count = 0;
  for (const row of pending.rows) {
    try {
      await worker.runPendingJob(row.id, row.space_id);
      count += 1;
    } catch (err) {
      log?.warn(
        `[intake-extraction] job ${row.id} failed: ${err instanceof Error ? err.message : String(err)}`,
      );
    }
  }
  return count;
}

// Re-export for tests that need queue without full worker.
export { PgJobQueueRepository };
