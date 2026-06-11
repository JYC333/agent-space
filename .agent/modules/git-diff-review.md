# Module: Git Diff Review

## Status
**PLANNED** — No backend or frontend implementation yet. Workspace model and git integration not built.

## Purpose
Allow users to review, annotate, and approve agent-generated or human-authored code changes before they are committed or pushed. Git diff review is the checkpoint surface for agentic code changes — the place where AI output meets human approval before entering version control.

## Owns
- Diff fetch and parse (from workspace git repos)
- DiffViewer UI component (unified and split modes)
- Inline comment / annotation on diff hunks
- Approval and reject actions for staged diffs
- Agent-change attribution (which run produced this diff?)

## Does Not Own
- Git operations execution (workspace runner / future workspace-console module)
- File editing (workspace console)
- Agent run orchestration (agents module)

## Key Concepts

- **Staged diff**: changes in the workspace git index (git diff --cached)
- **Working diff**: unstaged changes (git diff)
- **Patch set**: a named collection of diffs from a single agent run or user session
- **Annotation**: a comment attached to a specific line or hunk in the diff
- **Approval**: user confirms the diff is acceptable — triggers `git commit` via workspace runner

## Data Flow

```
Agent run modifies files in workspace
    ↓
WorkspaceRunner detects changed files (git diff --stat)
    ↓
Patch set created and stored (raw git patch text)
    ↓
DiffReview record created (status=pending)
    ↓
User sees pending review in Workspaces nav or Proposals inbox
    ↓
User opens DiffViewer: reads hunk by hunk, adds annotations
    ↓
Approve → WorkspaceRunner runs git commit -m "..." 
Reject → git checkout -- . (discard)
Request changes → agent re-runs with annotation context
```

## Key Model (Planned)

```
DiffReview:
  id, space_id, workspace_id, user_id
  source_run_id   — FK → Run (null if human-authored)
  patch_text      — raw unified diff
  file_paths      — JSON list of affected paths
  status          — pending | approved | rejected | revision_requested
  commit_sha      — set after approval + commit
  created_at, reviewed_at

DiffAnnotation:
  id, diff_review_id, user_id
  file_path, hunk_index, line_number
  body            — comment text
  created_at
```

## UI: DiffViewer Component

- Unified diff view by default; toggle to split view
- Syntax highlighting per file extension
- Line-level comment thread (click line number → add annotation)
- Collapse/expand hunks
- File tree sidebar: list affected files; click to jump

## UI: Diff Review Page

- Header: run attribution (agent name, run ID, timestamp), file count, +/- stats
- DiffViewer (center panel)
- Right panel: annotations list, approval actions
- Actions: Approve (commit), Reject (discard), Request Changes (re-run with notes)

## Invariants
- Patch text is stored verbatim — never re-computed after initial capture
- Approving a diff must not silently skip failing tests (future: test gate before commit)
- Annotations are preserved even after rejection (audit trail)
- DiffViewer must render correctly for binary file diffs (show "Binary file changed")
- Agent-sourced diffs always display run attribution — never shown as "human change"

## Related Files
- `backend/app/models.py` — TODO: add DiffReview, DiffAnnotation models
- `backend/app/api/` — TODO: add diff-review router
- `apps/web/src/components/DiffViewer.tsx` — TODO: DiffViewer primitive
- `apps/web/src/pages/` — TODO: diff review page

## Related Modules
- [workspace-console.md](workspace-console.md) — file browser and workspace operations
- [agents.md](agents.md) — source of agent-generated diffs
- [proposals.md](proposals.md) — diff approval is a specialized proposal flow
- [frontend-layout.md](frontend-layout.md) — DiffViewer is a center-panel primitive
