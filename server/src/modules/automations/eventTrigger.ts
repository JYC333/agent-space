import { HttpError } from "../routeUtils/common";

/**
 * Internal event trigger: `trigger_type = 'event'` automations fire when an
 * intake scan materializes new items, delivered through the job queue (see
 * intake/automationEventEmitter.ts and intakeEventHandler.ts). This is a peer
 * of manual/schedule, not a scheduler variant — event automations never enter
 * the heartbeat sweep. The external trigger registry remains deferred.
 */

export const INTAKE_ITEMS_MATERIALIZED_EVENT = "intake.items_materialized";

const MAX_MIN_NEW_ITEMS = 1000;
const MAX_COOLDOWN_SECONDS = 86_400;
const DEFAULT_COOLDOWN_SECONDS = 900;

export interface IntakeEventTriggerConfig {
  minNewItems: number;
  cooldownSeconds: number;
  sourceConnectionIds: string[];
}

export function parseIntakeEventTriggerConfig(
  configJson: Record<string, unknown> | null | undefined,
): IntakeEventTriggerConfig {
  const config = configJson && typeof configJson === "object" ? configJson : {};
  const event = (config as Record<string, unknown>).event;
  if (!event || typeof event !== "object" || Array.isArray(event)) {
    throw new HttpError(422, "Event automations require a config_json.event object");
  }
  const record = event as Record<string, unknown>;
  if (record.type !== INTAKE_ITEMS_MATERIALIZED_EVENT) {
    throw new HttpError(
      422,
      `config_json.event.type must be ${JSON.stringify(INTAKE_ITEMS_MATERIALIZED_EVENT)}`,
    );
  }
  return {
    minNewItems: boundedInt(record.min_new_items, "event.min_new_items", 1, 1, MAX_MIN_NEW_ITEMS),
    cooldownSeconds: boundedInt(
      record.cooldown_seconds,
      "event.cooldown_seconds",
      DEFAULT_COOLDOWN_SECONDS,
      0,
      MAX_COOLDOWN_SECONDS,
    ),
    sourceConnectionIds: stringArray(record.source_connection_ids, "event.source_connection_ids"),
  };
}

export function isInEventCooldown(
  lastFiredAt: string | null,
  cooldownSeconds: number,
  now: Date = new Date(),
): boolean {
  if (!lastFiredAt || cooldownSeconds <= 0) return false;
  const last = Date.parse(lastFiredAt);
  if (Number.isNaN(last)) return false;
  return now.getTime() - last < cooldownSeconds * 1000;
}

function boundedInt(value: unknown, field: string, fallback: number, min: number, max: number): number {
  if (value === undefined || value === null) return fallback;
  if (typeof value !== "number" || !Number.isInteger(value) || value < min || value > max) {
    throw new HttpError(422, `config_json.${field} must be an integer between ${min} and ${max}`);
  }
  return value;
}

function stringArray(value: unknown, field: string): string[] {
  if (value === undefined || value === null) return [];
  if (!Array.isArray(value) || value.some((entry) => typeof entry !== "string" || !entry)) {
    throw new HttpError(422, `config_json.${field} must be an array of non-empty strings`);
  }
  return value as string[];
}
