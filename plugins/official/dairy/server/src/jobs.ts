import type { Queryable, PluginJobHandler } from "@agent-space/protocol" with { "resolution-mode": "import" };
import { dairyRepository } from "./domain/repository";

export const JOB_TYPE_DAIRY_REFLECTION = "dairy_reflection";

export interface DairyReflectionJobPayload {
  user_id: string;
  entry_id: string;
  entry_date: string;
}

export function buildDairyReflectionHandler(db: Queryable, pluginId: string): PluginJobHandler {
  return async (job) => {
    const { user_id, entry_id, entry_date } = job.payload as unknown as DairyReflectionJobPayload;

    if (!(await dairyRepository.isAiReflectionEnabled(db, pluginId, user_id))) {
      return { skipped: true, reason: "reflection_disabled" };
    }

    const pastEntries = await dairyRepository.findOnThisDay(db, user_id, entry_date);
    const relevant = pastEntries.filter((e) => e.id !== entry_id);

    if (relevant.length === 0) {
      return { skipped: true, reason: "no_past_entries" };
    }

    const lines = [
      `On this day across ${relevant.length} previous year(s):`,
      "",
      ...relevant.map(
        (e) =>
          `**${e.entry_date}**: ${e.content.slice(0, 200)}${e.content.length > 200 ? "..." : ""}`,
      ),
    ];

    await dairyRepository.insertReflection(
      db,
      entry_id,
      new Date().toISOString().slice(0, 10),
      lines.join("\n"),
      "stub",
    );

    return { entry_id, past_entries_count: relevant.length };
  };
}
