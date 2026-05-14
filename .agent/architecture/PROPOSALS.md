# Proposals

Date: 2026-05-14

Proposals are the product review and application boundary for durable mutations.

## Product API

- `/api/v1/proposals` is the only product API for proposal review and application.
- `GET /api/v1/proposals` defaults to pending proposals.
- `status=all` is explicit and returns proposals across statuses.
- Supported proposal types are `memory_update` and `code_patch`.
- Accept returns the general `ProposalAcceptOut` response shape.
- A proposal is never auto-applied.

## Application Rules

- `memory_update` creates or updates durable memory only when accepted.
- `code_patch` updates workspace files only when accepted.
- Rejected, accepted, expired, or superseded proposals cannot be applied again.
- Cross-space or unauthorized access must not reveal proposal details.

## Audit Rules

- Proposal creation, acceptance, and rejection must be durable.
- Accepted proposals keep enough result detail for callers to identify the applied product effect.
- Proposal application must be idempotence-safe at the API boundary: repeated accept attempts must not repeat the mutation.
