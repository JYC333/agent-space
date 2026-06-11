/**
 * @agent-space/protocol — shared, framework-free wire contracts.
 *
 * This is the single public entry point. It re-exports the protocol's
 * primitives, DTOs, command contracts and event contracts. It owns **schemas and
 * types only** — no handlers, no transport, no business logic, no authority.
 * Python remains the sole authority for every command and write.
 *
 * The package depends only on `zod`. Importing it must never pull in frontend,
 * backend, database, or runtime code. See
 * `.agent/architecture/TS_PROTOCOL_FOUNDATION.md`.
 */

// Primitives + value sets
export * from "./common";

// Zod schemas (single source of truth for data shapes)
export * from "./schemas";

// Inferred DTO types
export * from "./dto";

// Command contracts (schemas + types)
export * from "./commands";

// Event contracts (schemas + types)
export * from "./events";

// Canonical model contracts (request/message/usage + streaming events)
export * from "./model";
