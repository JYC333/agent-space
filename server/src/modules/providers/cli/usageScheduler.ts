import type { FastifyBaseLogger } from "fastify";
import type { CliUsageEntry } from "./credentialBroker";

export const CLI_USAGE_REFRESH_INTERVAL_MS = 3 * 60 * 60 * 1000;
const DEFAULT_RUNTIMES = ["claude_code", "codex_cli"] as const;

type TimerHandle = ReturnType<typeof setInterval>;

export interface CliUsageRefreshBroker {
  refreshStaleCliQuota(runtime: string, maxAgeMs: number): Promise<CliUsageEntry | null>;
}

export interface CliUsageRefreshScheduler {
  refreshDueUsage(): Promise<void>;
  stop(): void;
}

export interface CliUsageRefreshSchedulerOptions {
  intervalMs?: number;
  maxAgeMs?: number;
  runtimes?: readonly string[];
  isEnabled?: () => boolean | Promise<boolean>;
  logger?: Pick<FastifyBaseLogger, "debug" | "warn">;
}

export function startCliUsageRefreshScheduler(
  broker: CliUsageRefreshBroker,
  options: CliUsageRefreshSchedulerOptions = {},
): CliUsageRefreshScheduler {
  const intervalMs = options.intervalMs ?? CLI_USAGE_REFRESH_INTERVAL_MS;
  const maxAgeMs = options.maxAgeMs ?? intervalMs;
  const runtimes = options.runtimes ?? DEFAULT_RUNTIMES;
  let stopped = false;
  let running = false;

  async function refreshDueUsage(): Promise<void> {
    if (stopped || running) return;
    running = true;
    try {
      if (options.isEnabled && !(await options.isEnabled())) {
        options.logger?.debug("CLI usage quota auto-refresh disabled");
        return;
      }
      for (const runtime of runtimes) {
        try {
          const entry = await broker.refreshStaleCliQuota(runtime, maxAgeMs);
          if (entry) {
            options.logger?.debug({ runtime, checked_at: entry.quota?.checked_at }, "CLI usage quota refreshed");
          }
        } catch (error) {
          options.logger?.warn(
            {
              runtime,
              err: error instanceof Error ? error.message : String(error),
            },
            "CLI usage quota refresh failed",
          );
        }
      }
    } finally {
      running = false;
    }
  }

  const timer: TimerHandle = setInterval(() => {
    void refreshDueUsage();
  }, intervalMs);
  timer.unref?.();

  return {
    refreshDueUsage,
    stop() {
      stopped = true;
      clearInterval(timer);
    },
  };
}
