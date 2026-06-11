/**
 * Event envelopes — **contracts only, not an event bus.**
 *
 * An event describes something that already happened, server-side. These schemas
 * define the *shape* of such a notification on the wire. This package provides
 * **no** publisher, subscriber, transport, or dispatch — only the message
 * contract. Events originate from the Python authority; a future TS gateway or
 * client may carry them, but none is implemented here.
 *
 * Each event is the generic {@link EventEnvelopeSchema} narrowed to a literal
 * `type` and a concrete `payload`. Payloads embed the DTOs from `schemas.ts`.
 *
 * Depends only on `./common`, `./schemas` and `zod`.
 */

import { z } from "zod";
import { IdSchema, ISODateTimeSchema } from "./common";
import {
  ActivityDTOSchema,
  ProposalDTOSchema,
  RunEventDTOSchema,
  ArtifactDTOSchema,
  MemoryDTOSchema,
} from "./schemas";

/** Generic event envelope. The per-event schemas below narrow `type`+`payload`. */
export const EventEnvelopeSchema = z.object({
  event_id: IdSchema,
  type: z.string(),
  occurred_at: ISODateTimeSchema,
  space_id: IdSchema,
  payload: z.unknown(),
});
export type EventEnvelope = z.infer<typeof EventEnvelopeSchema>;

function eventSchema<TType extends string, TPayload extends z.ZodTypeAny>(
  type: TType,
  payload: TPayload,
) {
  return z.object({
    event_id: IdSchema,
    type: z.literal(type),
    occurred_at: ISODateTimeSchema,
    space_id: IdSchema,
    payload,
  });
}

// ---------------------------------------------------------------------------
// Event type discriminators
// ---------------------------------------------------------------------------

export const EventType = {
  ActivityCreated: "activity.created",
  ProposalCreated: "proposal.created",
  ProposalStatusChanged: "proposal.status_changed",
  RunStatusChanged: "run.status_changed",
  RunEventAppended: "run.event_appended",
  ArtifactCreated: "artifact.created",
  MemoryChanged: "memory.changed",
} as const;
export type EventTypeValue = (typeof EventType)[keyof typeof EventType];

// ---------------------------------------------------------------------------
// Payloads + event envelopes
// ---------------------------------------------------------------------------

export const ActivityCreatedPayloadSchema = z.object({
  activity: ActivityDTOSchema,
});
export const ActivityCreatedEventSchema = eventSchema(
  EventType.ActivityCreated,
  ActivityCreatedPayloadSchema,
);
export type ActivityCreatedEvent = z.infer<typeof ActivityCreatedEventSchema>;

export const ProposalCreatedPayloadSchema = z.object({
  proposal: ProposalDTOSchema,
});
export const ProposalCreatedEventSchema = eventSchema(
  EventType.ProposalCreated,
  ProposalCreatedPayloadSchema,
);
export type ProposalCreatedEvent = z.infer<typeof ProposalCreatedEventSchema>;

export const ProposalStatusChangedPayloadSchema = z.object({
  proposal_id: IdSchema,
  status: z.string(),
  previous_status: z.string().nullish(),
  decided_at: ISODateTimeSchema.nullish(),
});
export const ProposalStatusChangedEventSchema = eventSchema(
  EventType.ProposalStatusChanged,
  ProposalStatusChangedPayloadSchema,
);
export type ProposalStatusChangedEvent = z.infer<
  typeof ProposalStatusChangedEventSchema
>;

export const RunStatusChangedPayloadSchema = z.object({
  run_id: IdSchema,
  status: z.string(),
  previous_status: z.string().nullish(),
});
export const RunStatusChangedEventSchema = eventSchema(
  EventType.RunStatusChanged,
  RunStatusChangedPayloadSchema,
);
export type RunStatusChangedEvent = z.infer<typeof RunStatusChangedEventSchema>;

export const RunEventAppendedPayloadSchema = z.object({
  event: RunEventDTOSchema,
});
export const RunEventAppendedEventSchema = eventSchema(
  EventType.RunEventAppended,
  RunEventAppendedPayloadSchema,
);
export type RunEventAppendedEvent = z.infer<typeof RunEventAppendedEventSchema>;

export const ArtifactCreatedPayloadSchema = z.object({
  artifact: ArtifactDTOSchema,
});
export const ArtifactCreatedEventSchema = eventSchema(
  EventType.ArtifactCreated,
  ArtifactCreatedPayloadSchema,
);
export type ArtifactCreatedEvent = z.infer<typeof ArtifactCreatedEventSchema>;

export const MEMORY_CHANGE_VALUES = ["created", "updated", "deleted"] as const;
export type MemoryChangeValue = (typeof MEMORY_CHANGE_VALUES)[number];
export const MemoryChangedPayloadSchema = z.object({
  memory_id: IdSchema,
  change: z.string(), // one of MEMORY_CHANGE_VALUES; permissive per protocol convention
  memory: MemoryDTOSchema.nullish(),
});
export const MemoryChangedEventSchema = eventSchema(
  EventType.MemoryChanged,
  MemoryChangedPayloadSchema,
);
export type MemoryChangedEvent = z.infer<typeof MemoryChangedEventSchema>;

/** Discriminated union of all known events, keyed on `type`. */
export const AnyEventSchema = z.discriminatedUnion("type", [
  ActivityCreatedEventSchema,
  ProposalCreatedEventSchema,
  ProposalStatusChangedEventSchema,
  RunStatusChangedEventSchema,
  RunEventAppendedEventSchema,
  ArtifactCreatedEventSchema,
  MemoryChangedEventSchema,
]);
export type AnyEvent = z.infer<typeof AnyEventSchema>;
