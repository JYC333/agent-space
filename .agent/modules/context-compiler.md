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

## Invariants
- Vendor files are never written to the real workspace
- Changes agents make to generated files do not propagate to MemoryStore
- Compiled content is stored in `ContextSnapshot.compiled_content` for audit

## Related Files
- `core/backend/app/memory/context_compiler.py`
- `core/backend/app/memory/context_builder.py`
- `core/backend/app/memory/security.py`
- `core/backend/app/models.py` — `ContextSnapshot`
- `.agent/context-bundles.yaml`

## Related Decisions
- [0004-context-wrapper.md](../decisions/0004-context-wrapper.md)
