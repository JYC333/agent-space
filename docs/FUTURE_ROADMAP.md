# Future Roadmap

This document lists future work items that are explicitly deferred from the current product.
Items here are not planned for the near term. Each requires a new design before implementation
begins.

---

## PersonalMemoryGrant Expansion

- **Full shared-content pipeline from approved egress_review.** Applying an `egress_review`
  proposal is currently metadata-only (no shared artifact or memory is created).
  A future phase would wire the full shared-content apply pipeline with content review,
  semantic leakage detection/redaction, and granting-user approval.

- **Semantic leakage detection and redaction.** Exact `personal_context_block` echoes
  are currently redacted from persisted run output. Paraphrased or inferred personal-memory
  meaning in egress_review proposals must be reviewed manually. Automated semantic
  leakage detection requires a new design.

- **Long-lived grants.** Grants are currently one-time and run-scoped. Multi-use and
  long-lived grants require explicit policy and lifecycle design.

- **Agent-level grants.** `target_agent_id`-scoped grants are deferred. Requires agent
  lifecycle and scope definitions.

- **Space-level grants.** Space-wide grant scope is deferred (too broad for safe dogfooding).

- **Multi-user grants.** Currently one granting user per grant is supported. Multi-user
  grants require new consent and audit design.

- **Restricted / highly_restricted grant model.** Currently only `normal` and `sensitive`
  memory sensitivity levels are grant-readable. `restricted` and `highly_restricted` require
  explicit future policy.

- **Admin grant-stats endpoint.** `GET /api/v1/spaces/{space_id}/grant-stats` for space
  admin aggregate grant statistics. Must return safe aggregate counts only (no personal
  memory content, no granting user identity).

- **Consuming-only sub-limit.** Combined active+consuming cap of 10 is enforced. A
  separate consuming-only cap of 3 is deferred pending usage data.

---

## Federation

- **Federation / cross-instance transfer.** Multi-deployment identity, remote fetch,
  synchronization, and authorization are explicitly deferred. See
  `docs/FEDERATED_ACCESS_MODEL.md`.

- **Direct cross-space reads.** General direct reads remain deny-by-default.
  Local transfer uses targeted immutable publication/import instead.

---

## Publication Expansion

- **Cross-instance publication.** Local targeted publication/import is implemented;
  anonymous catalogs and cross-instance delivery remain deferred.

---

## PersonalView and Cross-Space Aggregation

- **PersonalView.** Cross-space aggregation from a user's perspective (personal feed,
  memories across spaces, participation records) is not implemented. Requires a dedicated
  API and aggregation design that does not copy raw shared content.

- **ParticipationRecord.** Personal ledger entry for shared-space activity. Not implemented.
  Must not copy raw shared-space content into personal space.

- **`/me` aggregation pagination and performance.** Current personal-space aggregate
  endpoints have no pagination or caching optimizations for large data sets.

---

## Policy Enforcement

- **Additional persisted policy classes.** Currently active: `memory.private_placement` and `run.user_private_scope`. Candidates for next: `runtime.execute`, `credential.access`.

- **Additional policy audit coverage.** `PolicyDecisionRecord` is the queryable
  durable audit table for wired sensitive-action decisions; structured domain
  policy traces also remain available. Future work may wire additional actions
  only when corresponding enforcement surfaces exist.

- **Credential access grants.** Per-run/per-tool credential scope. Currently the
  credential resolver is a single boundary with no per-run grants.

---

## Infrastructure and Scale

- **Production-grade rate limits and advisory locks.** Current rate limits are service-layer
  only. The advisory lock for backups is single-host. Distributed locking is not designed.

- **Offsite / cloud backup automation.** Current backup strategy is manual GPG + external
  transfer. Automated offsite replication is deferred.

---

## Test Suite

- **Frontend component tests for PersonalMemoryGrant flow.** Automated frontend coverage
  for the grant/egress/approval UI remains future work.

---

## UI and Frontend

- **UI dashboard for grants and proposals.** A dedicated grant management view beyond
  the per-run panel is deferred.

- **Frontend component tests for PersonalMemoryGrant flow.** No automated frontend
  component tests exist for the grant/egress/approval UI. Manual checklist is the
  current verification method.

---

## See Also

- `docs/PERSONAL_MEMORY_GRANT.md` — PersonalMemoryGrant current state and deferred items
- `docs/CONTENT_PUBLICATIONS.md` — targeted immutable publication/import
- `docs/POLICY_AND_PRIVACY_BOUNDARIES.md` — current enforcement and deferred items
- `docs/FEDERATED_ACCESS_MODEL.md` — federation design (deferred)
- `.agent/architecture/ROADMAP_AND_FUTURE_RISKS.md` — broader capability roadmap
