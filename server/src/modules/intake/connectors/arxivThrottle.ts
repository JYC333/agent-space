/**
 * Best-effort process-local polite throttle for arXiv network calls
 * (export.arxiv.org API plus arxiv.org html/pdf fetches). arXiv asks clients
 * to keep at least ~3 seconds between requests. This only wraps arXiv calls;
 * other Intake fetches are not slowed down.
 */

interface ArxivThrottleRuntime {
  minIntervalMs: number;
  now: () => number;
  sleep: (ms: number) => Promise<void>;
}

const DEFAULT_RUNTIME: ArxivThrottleRuntime = {
  minIntervalMs: 3_000,
  now: () => Date.now(),
  sleep: (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
};

let runtime = DEFAULT_RUNTIME;
let nextSlotAt = 0;

/**
 * Reserves the next arXiv request slot and waits until it is available.
 * Concurrent callers are serialized at one request per minimum interval.
 */
export async function acquireArxivRequestSlot(): Promise<void> {
  const now = runtime.now();
  const waitMs = Math.max(0, nextSlotAt - now);
  nextSlotAt = Math.max(now, nextSlotAt) + runtime.minIntervalMs;
  if (waitMs > 0) await runtime.sleep(waitMs);
}

export function __setArxivThrottleForTests(overrides: Partial<ArxivThrottleRuntime> | null): void {
  runtime = { ...DEFAULT_RUNTIME, ...(overrides ?? {}) };
  nextSlotAt = 0;
}
