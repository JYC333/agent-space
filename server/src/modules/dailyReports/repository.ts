import { randomUUID } from "node:crypto";
import { HttpError, type Queryable } from "../routeUtils/common";

export interface DailyReportSettingRow {
  id: string;
  space_id: string;
  user_id: string;
  enabled: boolean;
  local_time: string;
  timezone: string;
  include_source_types_json: unknown;
  create_experience_proposals: boolean;
  create_memory_proposals: boolean;
  experience_confidence_threshold: number;
  memory_confidence_threshold: number;
  max_experience_proposals_per_day: number;
  max_memory_proposals_per_day: number;
  last_report_date: string | null;
  next_run_at: string | null;
  created_at: string;
  updated_at: string;
}

const SETTING_COLUMNS = `
  id, space_id, user_id, enabled, local_time, timezone, include_source_types_json,
  create_experience_proposals, create_memory_proposals, experience_confidence_threshold,
  memory_confidence_threshold, max_experience_proposals_per_day, max_memory_proposals_per_day,
  last_report_date, next_run_at, created_at, updated_at
`;

const VALID_SOURCE_TYPES = new Set(["user_capture"]);

export class PgDailyReportSettingsRepository {
  constructor(private readonly db: Queryable) {}

  async getOrCreate(spaceId: string, userId: string): Promise<DailyReportSettingRow> {
    const existing = await this.get(spaceId, userId);
    if (existing) return existing;
    const id = randomUUID();
    const now = new Date().toISOString();
    const result = await this.db.query<DailyReportSettingRow>(
      `INSERT INTO daily_capture_report_settings (
         id, space_id, user_id, enabled, local_time, timezone, include_source_types_json,
         create_experience_proposals, create_memory_proposals, experience_confidence_threshold,
         memory_confidence_threshold, max_experience_proposals_per_day, max_memory_proposals_per_day,
         created_at, updated_at
       ) VALUES (
         $1, $2, $3, false, '09:00', 'UTC', '["user_capture"]'::jsonb,
         true, true, 0.6, 0.7, 5, 3,
         $4, $4
       )
       RETURNING ${SETTING_COLUMNS}`,
      [id, spaceId, userId, now],
    );
    return result.rows[0]!;
  }

  async get(spaceId: string, userId: string): Promise<DailyReportSettingRow | null> {
    const result = await this.db.query<DailyReportSettingRow>(
      `SELECT ${SETTING_COLUMNS}
         FROM daily_capture_report_settings
        WHERE space_id = $1 AND user_id = $2`,
      [spaceId, userId],
    );
    return result.rows[0] ?? null;
  }

  async getById(spaceId: string, settingId: string): Promise<DailyReportSettingRow | null> {
    const result = await this.db.query<DailyReportSettingRow>(
      `SELECT ${SETTING_COLUMNS}
         FROM daily_capture_report_settings
        WHERE space_id = $1 AND id = $2`,
      [spaceId, settingId],
    );
    return result.rows[0] ?? null;
  }

  async update(
    spaceId: string,
    userId: string,
    body: Record<string, unknown>,
  ): Promise<DailyReportSettingRow> {
    const row = await this.getOrCreate(spaceId, userId);
    const now = new Date().toISOString();
    const enabled =
      body.enabled !== undefined ? requiredBoolean(body.enabled, "enabled") : row.enabled;
    const localTime =
      body.local_time !== undefined ? requiredLocalTime(body.local_time) : row.local_time;
    const timezone =
      body.timezone !== undefined ? requiredTimezone(body.timezone) : row.timezone;
    const includeSourceTypes =
      body.include_source_types !== undefined
        ? requiredSourceTypes(body.include_source_types)
        : undefined;
    const createExperienceProposals =
      body.create_experience_proposals !== undefined
        ? requiredBoolean(body.create_experience_proposals, "create_experience_proposals")
        : undefined;
    const createMemoryProposals =
      body.create_memory_proposals !== undefined
        ? requiredBoolean(body.create_memory_proposals, "create_memory_proposals")
        : undefined;
    const experienceConfidenceThreshold =
      body.experience_confidence_threshold !== undefined
        ? requiredThreshold(body.experience_confidence_threshold, "experience_confidence_threshold")
        : undefined;
    const memoryConfidenceThreshold =
      body.memory_confidence_threshold !== undefined
        ? requiredThreshold(body.memory_confidence_threshold, "memory_confidence_threshold")
        : undefined;
    const maxExperienceProposalsPerDay =
      body.max_experience_proposals_per_day !== undefined
        ? requiredIntegerRange(body.max_experience_proposals_per_day, "max_experience_proposals_per_day", 0, 20)
        : undefined;
    const maxMemoryProposalsPerDay =
      body.max_memory_proposals_per_day !== undefined
        ? requiredIntegerRange(body.max_memory_proposals_per_day, "max_memory_proposals_per_day", 0, 10)
        : undefined;
    const scheduleChanged =
      body.enabled !== undefined || body.local_time !== undefined || body.timezone !== undefined;
    if (scheduleChanged) {
      requiredLocalTime(localTime);
      requiredTimezone(timezone);
    }
    const nextRunAt = scheduleChanged
      ? computeInitialNextRunAt({ ...row, enabled, local_time: localTime, timezone })
      : row.next_run_at;
    const result = await this.db.query<DailyReportSettingRow>(
      `UPDATE daily_capture_report_settings
          SET enabled = $3,
              local_time = $4,
              timezone = $5,
              include_source_types_json = COALESCE($6::jsonb, include_source_types_json),
              create_experience_proposals = COALESCE($7, create_experience_proposals),
              create_memory_proposals = COALESCE($8, create_memory_proposals),
              experience_confidence_threshold = COALESCE($9, experience_confidence_threshold),
              memory_confidence_threshold = COALESCE($10, memory_confidence_threshold),
              max_experience_proposals_per_day = COALESCE($11, max_experience_proposals_per_day),
              max_memory_proposals_per_day = COALESCE($12, max_memory_proposals_per_day),
              next_run_at = $13,
              updated_at = $14
        WHERE space_id = $1 AND user_id = $2
        RETURNING ${SETTING_COLUMNS}`,
      [
        spaceId,
        userId,
        enabled,
        localTime,
        timezone,
        includeSourceTypes ? JSON.stringify(includeSourceTypes) : null,
        createExperienceProposals ?? null,
        createMemoryProposals ?? null,
        experienceConfidenceThreshold ?? null,
        memoryConfidenceThreshold ?? null,
        maxExperienceProposalsPerDay ?? null,
        maxMemoryProposalsPerDay ?? null,
        nextRunAt,
        now,
      ],
    );
    return result.rows[0] ?? row;
  }

  async listDue(nowIso: string): Promise<DailyReportSettingRow[]> {
    const result = await this.db.query<DailyReportSettingRow>(
      `SELECT ${SETTING_COLUMNS}
         FROM daily_capture_report_settings
        WHERE enabled = true
          AND next_run_at IS NOT NULL
          AND next_run_at <= $1`,
      [nowIso],
    );
    return result.rows;
  }

  async advanceNextRun(setting: DailyReportSettingRow, slotUtcIso: string): Promise<void> {
    const next = computeNextRunAfterSlot(setting, slotUtcIso);
    await this.db.query(
      `UPDATE daily_capture_report_settings
          SET next_run_at = $3, updated_at = $4
        WHERE id = $1 AND space_id = $2`,
      [setting.id, setting.space_id, next, new Date().toISOString()],
    );
  }

  toOut(row: DailyReportSettingRow): Record<string, unknown> {
    return {
      id: row.id,
      space_id: row.space_id,
      user_id: row.user_id,
      enabled: row.enabled,
      local_time: row.local_time,
      timezone: row.timezone,
      include_source_types: row.include_source_types_json,
      create_experience_proposals: row.create_experience_proposals,
      create_memory_proposals: row.create_memory_proposals,
      experience_confidence_threshold: row.experience_confidence_threshold,
      memory_confidence_threshold: row.memory_confidence_threshold,
      max_experience_proposals_per_day: row.max_experience_proposals_per_day,
      max_memory_proposals_per_day: row.max_memory_proposals_per_day,
      last_report_date: row.last_report_date,
      next_run_at: row.next_run_at,
      created_at: row.created_at,
      updated_at: row.updated_at,
    };
  }
}

function computeNextRunAfterSlot(setting: DailyReportSettingRow, slotUtcIso: string): string | null {
  if (!setting.enabled) return null;
  const localTime = parseLocalTime(setting.local_time);
  if (!localTime) return null;
  try {
    const tz = setting.timezone || "UTC";
    const slotLocal = zonedParts(new Date(slotUtcIso), tz);
    const nextLocal = addLocalDays({
      year: slotLocal.year,
      month: slotLocal.month,
      day: slotLocal.day,
      hour: localTime.hour,
      minute: localTime.minute,
    }, 1);
    return zonedLocalToUtc(nextLocal, tz).toISOString();
  } catch {
    return null;
  }
}

function requiredBoolean(value: unknown, field: string): boolean {
  if (typeof value !== "boolean") {
    throw new HttpError(422, `${field} must be a boolean`);
  }
  return value;
}

function requiredLocalTime(value: unknown): string {
  if (typeof value !== "string") {
    throw new HttpError(422, "local_time must be HH:MM (e.g. 08:30)");
  }
  const parsed = parseLocalTime(value);
  if (!parsed) {
    throw new HttpError(422, "local_time hour must be 00-23 and minute must be 00-59");
  }
  return value;
}

function requiredTimezone(value: unknown): string {
  if (typeof value !== "string" || !value.trim()) {
    throw new HttpError(422, "timezone must be a valid IANA timezone");
  }
  assertValidTimezone(value);
  return value;
}

function requiredSourceTypes(value: unknown): string[] {
  if (!Array.isArray(value) || !value.every((item): item is string => typeof item === "string")) {
    throw new HttpError(422, "include_source_types must be a list of strings");
  }
  const invalid = value.filter((item) => !VALID_SOURCE_TYPES.has(item));
  if (invalid.length > 0) {
    throw new HttpError(
      422,
      `include_source_types contains unsupported values: ${JSON.stringify(invalid)}`,
    );
  }
  return value;
}

function requiredThreshold(value: unknown, field: string): number {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0 || value > 1) {
    throw new HttpError(422, `${field} must be between 0.0 and 1.0`);
  }
  return value;
}

function requiredIntegerRange(value: unknown, field: string, min: number, max: number): number {
  if (typeof value !== "number" || !Number.isInteger(value) || value < min || value > max) {
    throw new HttpError(422, `${field} must be between ${min} and ${max}`);
  }
  return value;
}

export function assertValidTimezone(timezone: string): void {
  if (isValidTimezone(timezone)) return;
  throw new HttpError(422, `timezone ${JSON.stringify(timezone)} is not a valid IANA timezone`);
}

export function isValidTimezone(timezone: string): boolean {
  try {
    new Intl.DateTimeFormat("en-US", { timeZone: timezone }).format(new Date());
    return true;
  } catch {
    return false;
  }
}

export function assertValidLocalDate(localDate: string): void {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(localDate)) {
    throw new HttpError(422, "local_date must be YYYY-MM-DD");
  }
}

export function computeInitialNextRunAt(
  setting: Pick<DailyReportSettingRow, "enabled" | "local_time" | "timezone">,
  after: Date = new Date(),
): string | null {
  if (!setting.enabled) return null;
  const localTime = parseLocalTime(setting.local_time);
  if (!localTime) return null;
  try {
    const tz = setting.timezone || "UTC";
    const afterLocal = zonedParts(after, tz);
    let candidateLocal = {
      year: afterLocal.year,
      month: afterLocal.month,
      day: afterLocal.day,
      hour: localTime.hour,
      minute: localTime.minute,
    };
    let candidate = zonedLocalToUtc(candidateLocal, tz);
    if (candidate.getTime() <= after.getTime()) {
      candidateLocal = addLocalDays(candidateLocal, 1);
      candidate = zonedLocalToUtc(candidateLocal, tz);
    }
    return candidate.toISOString();
  } catch {
    return null;
  }
}

export function localDateFromSlot(slotUtcIso: string, timezone: string): string {
  try {
    const parts = zonedParts(new Date(slotUtcIso), timezone || "UTC");
    return `${parts.year}-${pad(parts.month)}-${pad(parts.day)}`;
  } catch {
    return new Date(slotUtcIso).toISOString().slice(0, 10);
  }
}

export function localDayUtcBounds(
  localDate: string,
  timezone: string,
): { startUtcIso: string; endUtcIso: string } {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(localDate);
  if (!match) throw new Error(`Invalid local_date ${JSON.stringify(localDate)}`);
  const startLocal = {
    year: Number(match[1]),
    month: Number(match[2]),
    day: Number(match[3]),
    hour: 0,
    minute: 0,
  };
  const endLocal = addLocalDays(startLocal, 1);
  return {
    startUtcIso: zonedLocalToUtc(startLocal, timezone || "UTC").toISOString(),
    endUtcIso: zonedLocalToUtc(endLocal, timezone || "UTC").toISOString(),
  };
}

interface LocalDateTimeParts {
  year: number;
  month: number;
  day: number;
  hour: number;
  minute: number;
}

function parseLocalTime(value: string): { hour: number; minute: number } | null {
  const match = /^([01]\d|2[0-3]):([0-5]\d)$/.exec(value);
  if (!match) return null;
  return { hour: Number(match[1]), minute: Number(match[2]) };
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

function addLocalDays(parts: LocalDateTimeParts, days: number): LocalDateTimeParts {
  const date = new Date(Date.UTC(parts.year, parts.month - 1, parts.day + days, parts.hour, parts.minute));
  return {
    year: date.getUTCFullYear(),
    month: date.getUTCMonth() + 1,
    day: date.getUTCDate(),
    hour: date.getUTCHours(),
    minute: date.getUTCMinutes(),
  };
}

function pad(value: number): string {
  return String(value).padStart(2, "0");
}
