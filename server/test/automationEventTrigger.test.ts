import { describe, expect, it } from "vitest";
import {
  INTAKE_ITEMS_MATERIALIZED_EVENT,
  isInEventCooldown,
  parseIntakeEventTriggerConfig,
} from "../src/modules/automations/eventTrigger";

describe("parseIntakeEventTriggerConfig", () => {
  it("applies defaults: min_new_items 1, cooldown 900s, no allowlist", () => {
    expect(
      parseIntakeEventTriggerConfig({ event: { type: INTAKE_ITEMS_MATERIALIZED_EVENT } }),
    ).toEqual({ minNewItems: 1, cooldownSeconds: 900, sourceConnectionIds: [] });
  });

  it("accepts explicit bounds and connection allowlist", () => {
    expect(
      parseIntakeEventTriggerConfig({
        event: {
          type: INTAKE_ITEMS_MATERIALIZED_EVENT,
          min_new_items: 3,
          cooldown_seconds: 0,
          source_connection_ids: ["conn-1"],
        },
      }),
    ).toEqual({ minNewItems: 3, cooldownSeconds: 0, sourceConnectionIds: ["conn-1"] });
  });

  it("rejects a missing event object, wrong type, and out-of-range values", () => {
    expect(() => parseIntakeEventTriggerConfig({})).toThrowError(/event object/);
    expect(() => parseIntakeEventTriggerConfig({ event: { type: "other.event" } })).toThrowError(
      /event\.type/,
    );
    expect(() =>
      parseIntakeEventTriggerConfig({
        event: { type: INTAKE_ITEMS_MATERIALIZED_EVENT, cooldown_seconds: 100_000 },
      }),
    ).toThrowError(/cooldown_seconds/);
    expect(() =>
      parseIntakeEventTriggerConfig({
        event: { type: INTAKE_ITEMS_MATERIALIZED_EVENT, min_new_items: 0 },
      }),
    ).toThrowError(/min_new_items/);
    expect(() =>
      parseIntakeEventTriggerConfig({
        event: { type: INTAKE_ITEMS_MATERIALIZED_EVENT, source_connection_ids: [""] },
      }),
    ).toThrowError(/source_connection_ids/);
  });
});

describe("isInEventCooldown", () => {
  const now = new Date("2026-07-03T12:00:00.000Z");

  it("is in cooldown within the window and out of it after", () => {
    expect(isInEventCooldown("2026-07-03T11:55:00.000Z", 900, now)).toBe(true);
    expect(isInEventCooldown("2026-07-03T11:40:00.000Z", 900, now)).toBe(false);
  });

  it("never fired, zero cooldown, or unparsable timestamps are not in cooldown", () => {
    expect(isInEventCooldown(null, 900, now)).toBe(false);
    expect(isInEventCooldown("2026-07-03T11:59:59.000Z", 0, now)).toBe(false);
    expect(isInEventCooldown("not-a-date", 900, now)).toBe(false);
  });
});
