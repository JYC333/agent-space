import { HttpError, objectValue, optionalString } from "../routeUtils/common";

const WINDOW_UNITS = ["date_window", "page_cursor", "id_cursor"] as const;
const QUOTA_WINDOWS = ["minute", "hour", "day"] as const;

export interface BackfillStrategy {
  window_unit: (typeof WINDOW_UNITS)[number];
  from: string | null;
  to: string | null;
  window_size: number;
  max_items: number;
  direction: "backward";
}

export interface BackfillQuotaPolicy {
  window: (typeof QUOTA_WINDOWS)[number];
  limit_count: number;
}

export interface BackfillSegmentWindow {
  from?: string;
  to?: string;
  cursor?: number;
  max_items: number;
}

export function normalizeStrategy(body: Record<string, unknown>): BackfillStrategy {
  const raw = objectValue(body.strategy);
  const windowUnit = optionalString(raw.window_unit) ?? "date_window";
  if (!WINDOW_UNITS.includes(windowUnit as BackfillStrategy["window_unit"])) {
    throw new HttpError(422, "invalid window_unit");
  }
  const direction = optionalString(raw.direction) ?? "backward";
  if (direction !== "backward") {
    throw new HttpError(422, "Only backward history import is currently supported");
  }
  return {
    window_unit: windowUnit as BackfillStrategy["window_unit"],
    from: optionalString(raw.from),
    to: optionalString(raw.to),
    window_size: boundedInteger(raw.window_size, 30, 1, 365, "strategy.window_size"),
    max_items: boundedInteger(raw.max_items, 100, 1, 10000, "strategy.max_items"),
    direction,
  };
}

export function normalizeQuota(value: unknown): BackfillQuotaPolicy {
  const raw = objectValue(value);
  const window = optionalString(raw.window) ?? "minute";
  if (!QUOTA_WINDOWS.includes(window as BackfillQuotaPolicy["window"])) {
    throw new HttpError(422, "invalid quota_policy.window");
  }
  return {
    window: window as BackfillQuotaPolicy["window"],
    limit_count: boundedInteger(raw.limit_count, 10, 1, 1000, "quota_policy.limit_count"),
  };
}

export function assertSupportedStrategy(connectorKey: string, strategy: BackfillStrategy): void {
  if (connectorKey !== "arxiv") {
    throw new HttpError(422, "History import is not supported by this connector");
  }
  if (!["date_window", "page_cursor"].includes(strategy.window_unit)) {
    throw new HttpError(422, "The connector does not support this history import strategy");
  }
}

/**
 * Deterministically plans the bounded segments for a history import strategy.
 * Stops as soon as the max_items budget is exhausted so no zero-item segment
 * is ever emitted (a segment that fetches nothing would still cost a job and
 * a quota unit).
 */
export function planSegments(strategy: BackfillStrategy): BackfillSegmentWindow[] {
  if (strategy.window_unit !== "date_window") return planCursorSegments(strategy.max_items);
  return planDateWindowSegments(strategy);
}

function planCursorSegments(maxItems: number): BackfillSegmentWindow[] {
  const count = Math.ceil(maxItems / 100);
  return Array.from({ length: count }, (_, index) => ({
    cursor: index,
    max_items: Math.min(100, maxItems - index * 100),
  }));
}

function planDateWindowSegments(strategy: BackfillStrategy): BackfillSegmentWindow[] {
  const end = strategy.to ? new Date(strategy.to) : new Date();
  const start = strategy.from ? new Date(strategy.from) : new Date(end.getTime() - 90 * 86400000);
  if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime()) || start >= end) {
    throw new HttpError(422, "invalid date window");
  }

  const windows: Array<{ from: string; to: string }> = [];
  let cursor = end;
  while (cursor > start && windows.length < 1000) {
    const from = new Date(Math.max(start.getTime(), cursor.getTime() - strategy.window_size * 86400000));
    windows.push({ from: from.toISOString(), to: cursor.toISOString() });
    cursor = from;
  }

  const segments: BackfillSegmentWindow[] = [];
  let remaining = strategy.max_items;
  for (let index = 0; index < windows.length && remaining > 0; index++) {
    const allocation = Math.min(100, Math.ceil(remaining / (windows.length - index)));
    remaining -= allocation;
    segments.push({ ...windows[index], max_items: allocation });
  }
  return segments;
}

function boundedInteger(value: unknown, fallback: number, min: number, max: number, field: string): number {
  const parsed = value === undefined ? fallback : Number(value);
  if (!Number.isInteger(parsed) || parsed < min || parsed > max) {
    throw new HttpError(422, `${field} must be an integer between ${min} and ${max}`);
  }
  return parsed;
}
