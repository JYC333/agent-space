# Memory, Activity, and Provenance

## Activity-First Raw Input

Raw input must enter Activity before reaching Memory or Proposal.

| Capture kind | Entry point | Record type |
|---|---|---|
| Non-chat: thought, snippet, note, link, paste | `POST /api/v1/activity` | `ActivityRecord` |
| Chat / Ask Agent / conversation | `POST /api/v1/sessions` + messages | `Session` + `Message` |
| Run output | `ActivityRecord` with `activity_type=run_event` | `ActivityRecord` |
| Workspace event | `ActivityRecord` with `activity_type=workspace_event` | `ActivityRecord` |

Sessions must not be used as generic raw-capture storage for non-chat content.

## Activity → Proposal → Memory Flow

```
ActivityRecord (raw capture)
  ↓ ActivityConsolidationService → MemoryCandidateClassifier → MemoryProposalProducer
Proposal (pending; payload_json.provenance_entries contains activity entry)
  ↓ SourceMonitoringService gate
  ↓ ProposalService.accept → ProposalApplyService.apply
  ↓ MemoryProposalApplier.apply_create / apply_update
MemoryEntry (active)
  + ProvenanceLink rows (source_type=activity, source_type=proposal)
```

Memory writes are **proposal-first**. The public memory write API returns `ProposalOut` (HTTP 202). `ProposalApplyService.apply` is the only path that creates active `MemoryEntry` from a proposal.

## Source and Provenance Field Mapping

### ActivityRecord — Raw Capture Layer

| Field | Responsibility |
|---|---|
| `activity_type` / `source_kind` | Source identity: what kind of raw input. Values: `user_capture`, `chat_message`, `run_event`, `workspace_event`, `external_source`, etc. |
| `source_url` | Source identity: origin URL for web captures. Not trusted evidence by itself. |
| `content` | Raw input payload. Not Memory. |
| `source_trust` | Trust state resolved from `activity_type` if not explicitly set. |
| `source_integrity_json` | Evidence payload: optional integrity/checksum metadata. |
| `payload_json` / `metadata_json` | Source metadata: structured capture metadata. |

### ContextSource

The `context_sources` table was removed from the schema. It is not present in the current
migration and `test_canonical_schema.py` asserts it does not exist. Provenance uses
`ActivityRecord` + `ProvenanceLink` instead. A future first-class Source model would be
a new table, not a revival of this removed table.

### ProvenanceLink — Provenance Chain

| Field | Responsibility |
|---|---|
| `source_type` | Kind of producing object: `activity`, `proposal`, `memory`, `artifact`, `run_step`, `external_source`, `user_confirmation`. |
| `source_id` | ID of the producing object. |
| `source_trust` | Trust level of this provenance link. |
| `evidence_json` | Structured evidence at this link in the chain. |
| `target_type` / `target_id` | What this link is attached to (memory, policy, etc.). |

### Proposal Provenance Fields

| Field | Responsibility |
|---|---|
| `provenance_entries` | List of `{source_type, source_id, source_trust, evidence_json}`. Canonical format. |
| `source_monitoring_result` | Snapshot of SourceMonitoring gate at proposal creation or acceptance. |
| `consolidation_run_id` | Which consolidation run produced this proposal. |
| `activity_batch_hash` | Hash of contributing activity IDs. |
| `source_run_id` (legacy) | Denormalized run reference; normalized into `provenance_entries` at build time. |
| `source_activity_id` (legacy) | Normalized into `provenance_entries` via `provenance_entries_from_payload`; stripped from new proposals by `strip_legacy_provenance_keys`. |

### MemoryEntry — Approved Knowledge Layer

| Field | Responsibility |
|---|---|
| `source_trust` | Dominant trust level from accepted provenance_entries. |
| `source_activity_id` | FK to originating ActivityRecord. Preserved from `first_activity_id(provenance_entries)` at apply time. |
| `created_from_proposal_id` / `source_proposal_id` | Links MemoryEntry back to accepted Proposal. |
| `last_verified_at` | Last time this memory claim was explicitly verified. |

## Trust Vocabulary

Canonical values for `source_trust` across ActivityRecord, ProvenanceLink, and provenance_entries:

| Value | Meaning | Allowed for semantic Memory? |
|---|---|---|
| `user_confirmed` | Direct human input or explicit human approval | Yes |
| `internal_system` | Internal system-generated, auditable | Yes |
| `trusted_external` | External source explicitly marked trusted | Yes |
| `untrusted_external` | External source, not explicitly trusted | Only under `explicit_user_accept` |
| `agent_inferred` | Agent-inferred, no human confirmation | No |

Trust is resolved from `ActivityRecord.activity_type` by `_resolved_trust_from_activity` in `consolidation/classifier.py` if `source_trust` is not explicitly set. Unrecognized `activity_type` values default to `untrusted_external`.

## SourceMonitoring Trust Gate

`SourceMonitoringService` (`core/backend/app/memory/source_monitoring.py`) is the deterministic trust gate before any durable memory or policy apply.

Hard rules:
- `agent_inferred` alone → **reject** (cannot back active semantic memory or policy).
- `untrusted_external` alone → **require_review** (proceeds only under `explicit_user_accept` with result recorded).
- No provenance entries → **reject**.
- `user_confirmed`, `internal_system`, or `trusted_external` → **allow**.

The gate runs inside `ProposalApplyService._enforce_source_monitoring` before any durable write. `accept_context="explicit_user_accept"` is set by `ProposalService.accept` (the human approval API). No HTTP input can override `accept_context`.

Activity-first capture with `source_type=user_capture` resolves to `user_confirmed`, which satisfies the gate for semantic memory proposals.

## Direct Memory Write Policy Enforcement

`MemoryInternalWriter` enforces a `PolicyEngine` check with action `memory.write_direct` on all direct internal writes (create, update, delete, mark_status).

An active persisted `Policy` row with `domain=memory`, `action=memory.write_direct`, `effect=deny` blocks direct internal memory writes.

Approved proposal apply uses proposal-validated writer methods. Ordinary callers cannot pass a generic bypass reason string.

## Information Horizon — Candidate-Only Rule

Information Horizon content is **candidate-only**. It must not become active Memory without a proposal/review cycle.

Current enforcement:
- No `InformationItem`, `DiscoveryQueue`, or `ReadingState` table exists. These are deferred.
- Future horizon content must enter as `ActivityRecord` (or future `Source`) first.
- `ActivityConsolidationService` → `MemoryProposalProducer` is the only pipeline that creates Proposal rows from Activity. Proposals remain `pending` until explicitly accepted.
- `ProposalApplyService.apply` is the only path that creates active `MemoryEntry` from a proposal.
- No code path creates active Memory from horizon/candidate payload without proposal.

Future Information Horizon work must enter the Activity/Source → proposal path before Memory.

## Provenance Questions Answerable from Durable Records

| Question | Answer source |
|---|---|
| Which Activity generated this proposal? | `Proposal.payload_json["provenance_entries"]` with `source_type="activity"` |
| What source kind / URL was involved? | `ActivityRecord.activity_type`, `ActivityRecord.source_url` via `source_activity_id` |
| What trust state was known? | `Proposal.payload_json["provenance_entries"][*].source_trust`, `source_monitoring_result` |
| Was SourceMonitoring run? | `Proposal.payload_json["source_monitoring_result"]` |
| Which Proposal approved it? | `MemoryEntry.source_proposal_id` |
| Which MemoryEntry was created? | `Proposal.resulting_memory_id` (set at accept time) |
| What ProvenanceLinks survive after apply? | `ProvenanceLink` rows with `target_type="memory"`, `target_id=memory.id` |
