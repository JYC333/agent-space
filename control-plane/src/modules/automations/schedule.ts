export class InvalidScheduleError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "InvalidScheduleError";
  }
}

interface ParsedCron {
  minutes: Set<number>;
  hours: Set<number>;
  daysOfMonth: Set<number>;
  months: Set<number>;
  daysOfWeek: Set<number>;
  dayOfMonthWildcard: boolean;
  dayOfWeekWildcard: boolean;
}

interface LocalDateTimeParts {
  year: number;
  month: number;
  day: number;
  hour: number;
  minute: number;
}

const MAX_SEARCH_MINUTES = 2 * 366 * 24 * 60;

export function parseSchedule(configJson: Record<string, unknown> | null): {
  cron: string;
  timezone: string;
} {
  const cfg = configJson ?? {};
  const cron = cfg.cron;
  if (typeof cron !== "string" || !cron.trim()) {
    throw new InvalidScheduleError("schedule automation requires config_json.cron");
  }
  parseCron(cron);
  const timezone = typeof cfg.timezone === "string" && cfg.timezone.trim() ? cfg.timezone : "UTC";
  assertValidTimezone(timezone);
  return { cron, timezone };
}

export function computeNextRunAt(
  configJson: Record<string, unknown> | null,
  after: Date = new Date(),
): Date {
  const { cron, timezone } = parseSchedule(configJson);
  const parsed = parseCron(cron);
  let candidate = addLocalMinutes(truncateToLocalMinute(zonedParts(after, timezone)), 1);

  for (let i = 0; i < MAX_SEARCH_MINUTES; i += 1) {
    if (cronMatches(parsed, candidate)) {
      const utc = zonedLocalToUtc(candidate, timezone);
      if (utc.getTime() > after.getTime() && localPartsEqual(zonedParts(utc, timezone), candidate)) {
        return utc;
      }
    }
    candidate = addLocalMinutes(candidate, 1);
  }

  throw new InvalidScheduleError("Invalid schedule: no matching slot found within two years");
}

function parseCron(cron: string): ParsedCron {
  const fields = cron.trim().split(/\s+/);
  if (fields.length !== 5) {
    throw new InvalidScheduleError(`Invalid cron expression: ${JSON.stringify(cron)}`);
  }
  const [minute, hour, dayOfMonth, month, dayOfWeek] = fields;
  const dayOfMonthWildcard = dayOfMonth === "*";
  const dayOfWeekWildcard = dayOfWeek === "*";
  return {
    minutes: parseCronField(minute, 0, 59, "minute"),
    hours: parseCronField(hour, 0, 23, "hour"),
    daysOfMonth: parseCronField(dayOfMonth, 1, 31, "day of month"),
    months: parseCronField(month, 1, 12, "month"),
    daysOfWeek: parseCronField(dayOfWeek, 0, 7, "day of week", (value) => (value === 7 ? 0 : value)),
    dayOfMonthWildcard,
    dayOfWeekWildcard,
  };
}

function parseCronField(
  field: string,
  min: number,
  max: number,
  label: string,
  normalize: (value: number) => number = (value) => value,
): Set<number> {
  const values = new Set<number>();
  for (const rawPart of field.split(",")) {
    const part = rawPart.trim();
    if (!part) throw new InvalidScheduleError(`Invalid cron ${label} field: ${JSON.stringify(field)}`);
    const [rangePart, stepPart] = part.split("/");
    if (part.split("/").length > 2) {
      throw new InvalidScheduleError(`Invalid cron ${label} field: ${JSON.stringify(field)}`);
    }
    const step = stepPart === undefined ? 1 : parsePositiveInt(stepPart, label);
    let start: number;
    let end: number;
    if (rangePart === "*") {
      start = min;
      end = max;
    } else if (rangePart.includes("-")) {
      const [startRaw, endRaw] = rangePart.split("-");
      if (!startRaw || !endRaw || rangePart.split("-").length !== 2) {
        throw new InvalidScheduleError(`Invalid cron ${label} field: ${JSON.stringify(field)}`);
      }
      start = parseBoundedInt(startRaw, min, max, label);
      end = parseBoundedInt(endRaw, min, max, label);
      if (start > end) {
        throw new InvalidScheduleError(`Invalid cron ${label} range: ${JSON.stringify(rangePart)}`);
      }
    } else {
      start = parseBoundedInt(rangePart, min, max, label);
      end = start;
    }
    for (let value = start; value <= end; value += step) {
      values.add(normalize(value));
    }
  }
  if (values.size === 0) {
    throw new InvalidScheduleError(`Invalid cron ${label} field: ${JSON.stringify(field)}`);
  }
  return values;
}

function parsePositiveInt(value: string, label: string): number {
  if (!/^\d+$/.test(value)) {
    throw new InvalidScheduleError(`Invalid cron ${label} step: ${JSON.stringify(value)}`);
  }
  const parsed = Number(value);
  if (!Number.isSafeInteger(parsed) || parsed < 1) {
    throw new InvalidScheduleError(`Invalid cron ${label} step: ${JSON.stringify(value)}`);
  }
  return parsed;
}

function parseBoundedInt(value: string, min: number, max: number, label: string): number {
  if (!/^\d+$/.test(value)) {
    throw new InvalidScheduleError(`Invalid cron ${label} value: ${JSON.stringify(value)}`);
  }
  const parsed = Number(value);
  if (!Number.isSafeInteger(parsed) || parsed < min || parsed > max) {
    throw new InvalidScheduleError(`Invalid cron ${label} value: ${JSON.stringify(value)}`);
  }
  return parsed;
}

function cronMatches(cron: ParsedCron, parts: LocalDateTimeParts): boolean {
  if (!cron.minutes.has(parts.minute) || !cron.hours.has(parts.hour) || !cron.months.has(parts.month)) {
    return false;
  }
  const dayOfMonthMatches = cron.daysOfMonth.has(parts.day);
  const dayOfWeekMatches = cron.daysOfWeek.has(localDayOfWeek(parts));
  if (cron.dayOfMonthWildcard && cron.dayOfWeekWildcard) return true;
  if (cron.dayOfMonthWildcard) return dayOfWeekMatches;
  if (cron.dayOfWeekWildcard) return dayOfMonthMatches;
  return dayOfMonthMatches || dayOfWeekMatches;
}

function assertValidTimezone(timezone: string): void {
  try {
    new Intl.DateTimeFormat("en-US", { timeZone: timezone }).format(new Date());
  } catch {
    throw new InvalidScheduleError(`Invalid timezone: ${JSON.stringify(timezone)}`);
  }
}

function truncateToLocalMinute(parts: LocalDateTimeParts): LocalDateTimeParts {
  return {
    year: parts.year,
    month: parts.month,
    day: parts.day,
    hour: parts.hour,
    minute: parts.minute,
  };
}

function addLocalMinutes(parts: LocalDateTimeParts, minutes: number): LocalDateTimeParts {
  const date = new Date(Date.UTC(parts.year, parts.month - 1, parts.day, parts.hour, parts.minute + minutes));
  return {
    year: date.getUTCFullYear(),
    month: date.getUTCMonth() + 1,
    day: date.getUTCDate(),
    hour: date.getUTCHours(),
    minute: date.getUTCMinutes(),
  };
}

function localDayOfWeek(parts: Pick<LocalDateTimeParts, "year" | "month" | "day">): number {
  return new Date(Date.UTC(parts.year, parts.month - 1, parts.day)).getUTCDay();
}

function zonedParts(date: Date, timeZone: string): LocalDateTimeParts {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(date);
  const part = (type: Intl.DateTimeFormatPartTypes) =>
    Number(parts.find((item) => item.type === type)?.value ?? 0);
  return {
    year: part("year"),
    month: part("month"),
    day: part("day"),
    hour: part("hour"),
    minute: part("minute"),
  };
}

function zonedLocalToUtc(parts: LocalDateTimeParts, timeZone: string): Date {
  const target = Date.UTC(parts.year, parts.month - 1, parts.day, parts.hour, parts.minute, 0, 0);
  let guess = target;
  for (let i = 0; i < 4; i += 1) {
    const actual = zonedParts(new Date(guess), timeZone);
    const actualAsUtc = Date.UTC(
      actual.year,
      actual.month - 1,
      actual.day,
      actual.hour,
      actual.minute,
      0,
      0,
    );
    const delta = actualAsUtc - target;
    if (delta === 0) break;
    guess -= delta;
  }
  return new Date(guess);
}

function localPartsEqual(left: LocalDateTimeParts, right: LocalDateTimeParts): boolean {
  return (
    left.year === right.year &&
    left.month === right.month &&
    left.day === right.day &&
    left.hour === right.hour &&
    left.minute === right.minute
  );
}
