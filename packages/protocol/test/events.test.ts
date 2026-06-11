import { describe, it, expect } from "vitest";
import {
  EventEnvelopeSchema,
  ActivityCreatedEventSchema,
  RunStatusChangedEventSchema,
  RunEventAppendedEventSchema,
  AnyEventSchema,
  EventType,
} from "../src/events";

const base = {
  event_id: "e1",
  occurred_at: "2026-06-09T12:00:00+00:00",
  space_id: "s1",
};

describe("event contracts", () => {
  it("parses the generic envelope with an unknown payload", () => {
    const env = EventEnvelopeSchema.parse({
      ...base,
      type: "anything",
      payload: {},
    });
    expect(env.space_id).toBe("s1");
  });

  it("parses an ActivityCreatedEvent embedding an ActivityDTO", () => {
    const ev = ActivityCreatedEventSchema.parse({
      ...base,
      type: EventType.ActivityCreated,
      payload: {
        activity: {
          id: "a1",
          space_id: "s1",
          activity_type: "user_capture",
          visibility: "space_shared",
          occurred_at: "2026-06-09T12:00:00+00:00",
          created_at: "2026-06-09T12:00:00+00:00",
        },
      },
    });
    expect(ev.payload.activity.id).toBe("a1");
  });

  it("parses a RunStatusChangedEvent", () => {
    const ev = RunStatusChangedEventSchema.parse({
      ...base,
      type: EventType.RunStatusChanged,
      payload: { run_id: "r1", status: "running", previous_status: "queued" },
    });
    expect(ev.payload.status).toBe("running");
  });

  it("rejects a RunEventAppendedEvent with a malformed embedded DTO", () => {
    const result = RunEventAppendedEventSchema.safeParse({
      ...base,
      type: EventType.RunEventAppended,
      payload: { event: { id: "x" } }, // missing required RunEventDTO fields
    });
    expect(result.success).toBe(false);
  });

  it("routes via the discriminated union on `type`", () => {
    const parsed = AnyEventSchema.parse({
      ...base,
      type: EventType.RunStatusChanged,
      payload: { run_id: "r1", status: "succeeded" },
    });
    expect(parsed.type).toBe("run.status_changed");
    if (parsed.type === "run.status_changed") {
      expect(parsed.payload.run_id).toBe("r1");
    }
  });
});
