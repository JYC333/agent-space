import type { Queryable, PluginScheduledTask } from "@agent-space/protocol" with { "resolution-mode": "import" };
import { dairyRepository } from "./domain/repository";

interface SchedulerLogger {
  info(message: string): void;
  warn(message: string): void;
}

export function buildDairyDailyPromptTask(
  db: Queryable,
  pluginId: string,
  log?: SchedulerLogger,
): PluginScheduledTask {
  return {
    name: "dairy_daily_prompt",
    intervalSeconds: 6 * 3600,
    runOnStart: false,
    run: async () => {
      const today = new Date().toISOString().slice(0, 10);
      const enabledUsers = await dairyRepository.findEnabledUserIds(db, pluginId);

      let reminded = 0;
      for (const userId of enabledUsers) {
        const existing = await dairyRepository.findEntry(db, userId, today);
        if (!existing) {
          log?.info(`[dairy] user ${userId} has not written today (${today})`);
          reminded++;
        }
      }

      if (reminded > 0) {
        log?.info(
          `[dairy] daily_prompt: ${reminded}/${enabledUsers.length} users reminded`,
        );
      }
    },
  };
}
