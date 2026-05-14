# Module: Context Compiler

## Purpose
Translate a ContextPackage into a CLI-specific instruction file written to the sandbox. Security scanning, token budgeting, trust labels, and `.agent/` doc loading happen here.

## Owns
- `ContextCompiler` class, `TargetFormat` enum, `CompiledContext` dataclass
- Security scanning of all content before inclusion (via `security.py`)
- Token/character budget enforcement (128k chars default, priority-ordered truncation)
- Trust label annotation per section (`[system]`, `[user]`, `[workspace]`, etc.)
- Progressive `.agent/` doc loading (root docs always; module docs when `touched_files` matches)
- Vendor file header marking files as generated, not source of truth
- SOUL.md generation from agent-scoped identity memories
- Sandbox hook scripts (PostToolUse docs-sync reminders)

## Target → File Mapping

| Target | File(s) written |
|---|---|
| `claude` | `CLAUDE.md` + `SOUL.md` (if agent identity present) |
| `codex` | `AGENTS.md` |
| `cursor` | `.cursorrules` |
| `generic` | `CONTEXT.md` |
| `soul` | `SOUL.md` |
| `prompt` | `prompt.md` |

## Section Priority (lower = kept first when budget exceeded)

| Priority | Section | Source |
|---|---|---|
| 0 | Task | task_goal, always present |
| 1 | System Policy | system-scoped memories |
| 2 | User Context | user-scoped memories |
| 3 | Project Docs | `.agent/` root docs |
| 4 | Project Context | workspace + capability memories |
| 5 | Agent Context | agent-scoped memories |
| 6 | Module Docs | `.agent/modules/*.md`, task-relevant only |
| 7 | Attached Context | resolved ContextAttachments |
| 8 | Recent Activity | episodic memories |
| 9 | Session History | session summaries |
| 10–14 | Tools, Sandbox, Validation, Constraints, Output | compile() args |

## Integration

```
ContextBuilder.build(attachments=[...], workspace_path=...) → ContextPackage
     ↓
ContextCompiler.compile(context, target, task_goal, sandbox_dir,
                         workspace_path, touched_files)
     ↓
{sandbox_dir}/CLAUDE.md  (or AGENTS.md etc.)
{sandbox_dir}/SOUL.md    (if agent identity present)
{sandbox_dir}/.claude/settings.json + hooks/check-docs-sync.sh
```

## ContextDigest cache layer

`ContextSnapshotPopulator` tries to load active `ContextDigest` rows before rendering the stable prefix.

- When active digests exist (policy_bundle / workspace / agent), their rendered content is injected as `[digest:<type>:v<N>]` blocks in `stable_prefix`, replacing direct policy/memory rendering for those sections.
- If no active digest exists for a scope, the populator falls back to direct `MemoryRetriever` behaviour (MF5 path).
- `ContextSnapshot.source_refs_json` always includes `context_digest` entries recording `source_memory_ids`, `source_policy_ids`, and `source_relation_ids` for full auditability — digest does not replace source traceability.
- `ContextSnapshot.retrieval_trace_json` records `digest_used`, `digest_types`, `digest_versions`, `dirty_digest_used`, and `fallback_to_memory_retriever`.
- Dirty digests are still used but flagged in `retrieval_trace_json.dirty_digest_used=true`. Execution is never blocked by a missing or dirty digest.

### ContextDigest principles
- `ContextDigest` is a derived cache — not Memory, not Policy, not a source of truth.
- Digest does not create Proposal. Digest can be deleted and regenerated.
- Digest summarises active approved Memory/Policy only (no unapproved proposal content).
- Supported `digest_type` values: `policy_bundle`, `workspace`, `agent`.
- Personal Radius / external sources are out of scope.

## Invariants
- Vendor files are never written to the real workspace
- Changes agents make to generated files do not propagate to MemoryStore
- Compiled content (prefix + tail) is stored in `ContextSnapshot` columns for audit
- Snapshot population failure blocks adapter execution
- Missing digest never blocks execution; populator falls back gracefully

## Related Files
- `core/backend/app/memory/context_compiler.py`
- `core/backend/app/memory/context_builder.py`
- `core/backend/app/memory/digest_service.py` — `ContextDigestService`
- `core/backend/app/memory/security.py`
- `core/backend/app/models.py` — `ContextSnapshot`, `ContextDigest`
- `core/backend/app/runs/context_snapshot_populator.py`
- `.agent/context-bundles.yaml`

## Related Decisions
- [0004-context-wrapper.md](../decisions/0004-context-wrapper.md)
