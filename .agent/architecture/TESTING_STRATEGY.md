# Testing Strategy

Date: 2026-05-14

This document defines the current backend testing architecture. The suite is organized by product confidence layer, not by implementation package.

## Test Layers

Canonical backend tests live under:

```text
core/backend/tests/
  unit/
  contracts/
  invariants/
  workflows/
  support/
```

`tests/unit` contains deterministic rule and boundary tests. Use it for policy decisions, path decisions, state transitions, parser behavior, serialization contracts, and small pure functions. Unit tests must not require the database, network, real runtime execution, or real provider calls.

`tests/contracts` contains public boundary tests. Use it for API response shapes, status codes, request validation, adapter/provider protocol contracts, schema checks, storage/path contracts, and observable side effects across a public boundary. API contract tests use `TestClient` and real database state.

`tests/invariants` contains cross-cutting product rules that must hold even when internals change. Use it for space isolation, approval gates, run auditability, artifact path boundaries, terminal run state, workspace path enforcement, memory mutation boundaries, proposal application boundaries, and runtime/provider separation.

`tests/workflows` contains multi-step product flows from request to durable result. Use it for activity-to-memory, run execution, run output materialization, produced artifact paths, proposal approval, home summary behavior, workspace code proposal flows, and runtime failure handling. Workflow tests assert final observable state and audit trail.

`tests/support` contains shared factories, fixtures, fake runtimes, fake providers, and assertion helpers. Support code should make valid product states easy to create and invalid states explicit at the call site.

## What To Test

Protect product behavior:

- API contracts and public response shapes.
- Durable database state.
- Artifacts, proposals, activity records, memories, runs, and audit records.
- Authorization, space isolation, workspace path boundaries, and proposal gates.
- Runtime failure behavior and absence of partial side effects.
- Run output materialization from structured runtime output.

Assert observable outcomes. A useful test should still be meaningful if the implementation moves behind the same public behavior.

## What Not To Test

Do not add tests for:

- Removed routes.
- Retired API surfaces.
- Private service call chains.
- Mock call order.
- Coverage-only execution with no product assertion.
- Implementation-specific module boundaries.
- Vendor internals behind runtime/provider adapters.
- CSS classes or frontend styling details in backend tests.

## Fixtures And Factories

Factories must create valid minimal objects by default. Required ownership fields such as `space_id`, `created_by_user_id`, `workspace_id`, and related actor IDs should be visible at call sites when the rule under test depends on them.

Rules:

- Prefer real database rows over deep mocks for contracts, invariants, and workflows.
- Keep invalid states explicit in the test body or factory name.
- Do not hide durable mutations behind generic factory names.
- Do not create proposals, memories, artifacts, or approval events as side effects unless the factory name states that behavior.
- Keep cross-space and cross-user variants easy to create.
- Assertion helpers must inspect observable state and must not create data silently.

## Fake Runtime And Provider Rules

Runtime and provider execution are external boundaries. Tests should use deterministic fakes instead of live providers, CLIs, or sandboxes unless a specifically named external integration check is being run outside the canonical suite.

Rules:

- Fake runtimes return deterministic `output_text`, `output_json`, errors, and `produced_artifact_paths`.
- Fake providers return deterministic model responses and structured failures.
- Invariant and workflow tests may mock runtime/provider execution, but should use real services and database state around that boundary.
- Runtime adapter behavior and model provider behavior must remain separate in tests and production code.

## API And TestClient Commit Rules

`TestClient` requests run through the application boundary and must see committed setup state.

Rules:

- Commit database rows before issuing a `TestClient` request that depends on them.
- Commit factory-created setup rows when the API request must load them through a new request/session path.
- After the request, refresh or re-query rows before asserting changed durable state.
- Do not rely on uncommitted ORM identity-map state for API contract assertions.
- Rollback-only setup is acceptable only for tests that never cross the API boundary.

## Proposal And Run Rules

- `/api/v1/proposals` is the only product API for proposal review and application.
- Proposal acceptance is explicit; proposals are never auto-applied.
- Runs must remain auditable through durable state and activity/output records.
- `output_text` alone does not create a proposal.
- Structured run output may create artifacts and proposals only through current materialization rules.

## Canonical Command

Pytest configures an isolated `AGENT_SPACE_HOME` in `tests/conftest.py` before importing the app. Use the canonical layered suite command:

```bash
cd core/backend && python3 -m pytest tests/unit tests/contracts tests/invariants tests/workflows -v --tb=short
```

Do not point tests at a real mode data tree. Use `AGENT_SPACE_PYTEST_USE_REAL_HOME=1` only for explicit manual debugging.
