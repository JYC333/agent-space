import { afterEach, describe, expect, it, vi } from "vitest";
import {
  startCliUsageRefreshScheduler,
  type CliUsageRefreshScheduler,
} from "../src/modules/providers";

let scheduler: CliUsageRefreshScheduler | null = null;

afterEach(() => {
  scheduler?.stop();
  scheduler = null;
  vi.useRealTimers();
});

describe("startCliUsageRefreshScheduler", () => {
  it("refreshes stale usage on the configured interval", async () => {
    vi.useFakeTimers();
    const calls: Array<{ runtime: string; maxAgeMs: number }> = [];
    scheduler = startCliUsageRefreshScheduler(
      {
        async refreshStaleCliQuota(runtime, maxAgeMs) {
          calls.push({ runtime, maxAgeMs });
          return null;
        },
      },
      { intervalMs: 50, maxAgeMs: 123, runtimes: ["claude_code"] },
    );

    await vi.advanceTimersByTimeAsync(50);

    expect(calls).toEqual([{ runtime: "claude_code", maxAgeMs: 123 }]);
  });

  it("does not start a second refresh while one is still running", async () => {
    let release!: () => void;
    const blocked = new Promise<void>((resolve) => {
      release = resolve;
    });
    const calls: string[] = [];

    scheduler = startCliUsageRefreshScheduler(
      {
        async refreshStaleCliQuota(runtime) {
          calls.push(runtime);
          await blocked;
          return null;
        },
      },
      { intervalMs: 1_000_000, runtimes: ["claude_code"] },
    );

    const first = scheduler.refreshDueUsage();
    const second = scheduler.refreshDueUsage();
    expect(calls).toEqual(["claude_code"]);

    release();
    await Promise.all([first, second]);
  });

  it("skips broker refresh when auto-refresh is disabled", async () => {
    vi.useFakeTimers();
    let calls = 0;
    scheduler = startCliUsageRefreshScheduler(
      {
        async refreshStaleCliQuota() {
          calls += 1;
          return null;
        },
      },
      { intervalMs: 50, isEnabled: () => false },
    );

    await vi.advanceTimersByTimeAsync(50);

    expect(calls).toBe(0);
  });
});
