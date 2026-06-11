import { describe, it, expect, expectTypeOf } from "vitest";
import * as protocol from "../src/index";
import {
  PROTOCOL_VERSION,
  VISIBILITY_VALUES,
  AnyCommandSchema,
  AnyEventSchema,
  CommandType,
  EventType,
  type ActivityDTO,
  type StartRunCommand,
  type RunStatusChangedEvent,
} from "../src/index";

describe("index smoke import", () => {
  it("re-exports the public surface from src/index.ts", () => {
    // Schemas (values)
    expect(protocol.ActivityDTOSchema).toBeDefined();
    expect(protocol.ProposalDTOSchema).toBeDefined();
    expect(protocol.RunDTOSchema).toBeDefined();
    expect(protocol.RunEventDTOSchema).toBeDefined();
    expect(protocol.ArtifactDTOSchema).toBeDefined();
    expect(protocol.MemoryDTOSchema).toBeDefined();
    expect(protocol.KnowledgeItemDTOSchema).toBeDefined();
    expect(protocol.SpaceRefSchema).toBeDefined();
    expect(protocol.UserRefSchema).toBeDefined();
    expect(protocol.AgentRefSchema).toBeDefined();
    expect(protocol.WorkspaceRefSchema).toBeDefined();
    expect(protocol.ProjectRefSchema).toBeDefined();

    // Command + event contracts
    expect(protocol.CommandEnvelopeSchema).toBeDefined();
    expect(protocol.CreateCaptureCommandSchema).toBeDefined();
    expect(protocol.StartRunCommandSchema).toBeDefined();
    expect(protocol.AnyCommandSchema).toBeDefined();
    expect(protocol.EventEnvelopeSchema).toBeDefined();
    expect(protocol.AnyEventSchema).toBeDefined();
  });

  it("exposes stable value sets", () => {
    expect(PROTOCOL_VERSION).toBe("0.0.0");
    expect(VISIBILITY_VALUES).toContain("space_shared");
    expect(CommandType.StartRun).toBe("run.start");
    expect(EventType.RunStatusChanged).toBe("run.status_changed");
  });

  it("exposes the discriminated unions", () => {
    expect(AnyCommandSchema.options.length).toBe(5);
    expect(AnyEventSchema.options.length).toBe(7);
  });
});

describe("type-level contracts (typecheck test)", () => {
  it("infers DTO and envelope types from schemas", () => {
    expectTypeOf<ActivityDTO>().toHaveProperty("space_id");
    expectTypeOf<ActivityDTO["space_id"]>().toEqualTypeOf<string>();
    expectTypeOf<StartRunCommand["type"]>().toEqualTypeOf<"run.start">();
    expectTypeOf<RunStatusChangedEvent["type"]>().toEqualTypeOf<"run.status_changed">();
  });
});
