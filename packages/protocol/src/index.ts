/**
 * @agent-space/protocol — shared, framework-free wire contracts.
 *
 * This is the single public entry point. It re-exports the protocol's
 * primitives, DTOs, command contracts and event contracts. It owns **schemas and
 * types only** — no handlers, no transport, no business logic, no authority.
 * Authority is owned by the runtime service that registers each route; this
 * package only describes the wire contracts.
 *
 * The package depends only on `zod`. Importing it must never pull in frontend,
 * backend, database, or runtime code. See
 * `.agent/architecture/TS_PROTOCOL_FOUNDATION.md`.
 */

// Primitives + value sets
export * from "./common.js";

// Zod schemas (single source of truth for data shapes)
export * from "./schemas.js";

// Inferred DTO types
export * from "./dto.js";

// Command contracts (schemas + types)
export * from "./commands.js";

// Event contracts (schemas + types)
export * from "./events.js";

// Canonical model contracts (request/message/usage + streaming events)
export * from "./model.js";

// Provider + credential-channel contracts
export * from "./providers.js";

// CLI credential-channel contracts
export * from "./credentials.js";

// Identity introspection contract
export * from "./auth.js";

// Provider DB read allowlist
export * from "./providersDb.js";

// Provider and credential runtime boundary contracts
export * from "./providerCredentialsRuntime.js";

// TS runtime-host boundary contracts
export * from "./runtimeHost.js";

// Stage 4 run orchestration contracts
export * from "./runOrchestration.js";

// Stage 4 Python-owned context port contracts
export * from "./runContextPorts.js";

// Policy enforcement contracts
export * from "./policy.js";

// Proposal review contracts
export * from "./proposals.js";

// Stage 6 memory + sessions migration contracts
export * from "./memorySessions.js";
