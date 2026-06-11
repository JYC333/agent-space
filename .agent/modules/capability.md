# Module: Capability

## Purpose
Capabilities are installed, file-defined units of backend behavior that can be executed through the normal Run system. A capability has a manifest, local code, declared permissions, and declared output types.

## Owns
- YAML manifest discovery from builtin capabilities and explicitly configured local workspace roots.
- In-memory capability registry records.
- Enable/disable state: manifest `enabled` for builtins; persisted instance config for external capabilities.
- Local capability execution through `adapter_type="capability"`.

## Does Not Own
- Automation, schedules, or cron triggers.
- Capability marketplace installation.
- GitHub or remote repository scanning.
- Repository clone/install flows.
- DB-backed capability lifecycle tables.
- Agent-produced capability updates.
- Proposal approval for code or capability changes.

## Manifest Shape

```yaml
id: research_intake
name: Research Intake
version: 0.1.0
description: Parse an intake payload into structured research output
enabled: false

entrypoint:
  type: python_module
  module: capabilities.research_intake.main
  function: execute

permissions:
  network:
    allow: []
  filesystem:
    read: []
    write: []
  subprocess:
    allow: false

outputs:
  artifact_types:
    - research_intake.result.v1
```

Only `entrypoint.type: python_module` is executable in the current backend. Shell commands, remote code loading, package installation, network permissions, filesystem permissions, and subprocess execution are not supported by the capability runtime.

## Discovery

The registry loads two sources:

- `builtin`: diagnostic/example capabilities bundled under `catalog/capabilities/`.
- `external_workspace`: workflow capabilities stored in a local registered Workspace.

External capability roots are configured on a workspace registered as a capability library:

```json
{
  "workspace_type": "capability_library",
  "metadata_json": {
    "capability_roots": ["capabilities"]
  }
}
```

`workspace_type` is the real `Workspace.workspace_type` column (not stored in `metadata_json`). `capability_roots` lives in `metadata_json` only. The registry scans only workspaces in the current space with `workspace_type="capability_library"`. It does not scan ordinary workspaces, GitHub URLs, remote URLs, or clone repositories.

Each `capability_roots` entry must be a **local relative path**, must not contain `..`, and must resolve inside the workspace root through `workspace_absolute_root` and `PathPolicy`. The registry scans only direct child directories containing `capability.yaml`.

Builtin capabilities follow their manifest `enabled` value. External capabilities default to disabled when discovered. Enable/disable for external capabilities is persisted outside manifests in `$AGENT_SPACE_HOME/config/settings.yaml`:

```yaml
capabilities:
  enabled_external_capabilities:
    - research_intake
    - rss_watch
```

Manifests are source definitions only — they are not the local trust/enable store. Persisted enabled IDs that no longer resolve to a discovered capability are ignored safely on reload. Newly discovered external capabilities are never auto-enabled. This is still not a marketplace or remote install system.

## Execution Model

Capability execution is represented as a `Run`:

- `adapter_type="capability"` selects the capability runtime adapter.
- `capability_id` selects the installed manifest.
- `project_id` and `workspace_id` remain optional Run scope fields.
- The adapter loads the manifest from registry metadata, verifies the capability is enabled, validates the allowlisted entrypoint and minimal permissions, imports the local module from the installed capability directory/root, and calls `execute(context)`.

The capability function receives:

```python
{
    "run_id": "...",
    "space_id": "...",
    "project_id": "...",
    "workspace_id": "...",
    "capability_id": "...",
    "input": {...},
}
```

The function returns:

```python
{
    "status": "succeeded",
    "output": {...},
    "artifacts": [...],
    "activities": [...],
}
```

Returned artifacts are materialized as `Artifact` rows linked to the Run and project. Returned activities are materialized as `ActivityRecord` rows with `source_kind="run_event"` unless the capability supplies a valid source kind.

## Boundaries

- Executing a capability never installs, updates, or enables capabilities.
- Capability code must not mutate core code directly.
- Durable changes still go through proposals; capability execution does not bypass proposal approval.
- Capability development remains a separate coding-agent workspace, sandbox, and reviewed `code_patch` or future `capability_update` proposal flow.
- External capability installation and updates should eventually go through proposal review.
- Automation can later trigger capability Runs, but scheduling is not part of this module.

## Related Files

- `backend/app/capabilities/registry.py`
- `backend/app/capabilities/enabled_store.py`
- `backend/app/capabilities/loader.py`
- `backend/app/runtimes/adapters/capability.py`
- `backend/app/runs/run_output_materialization.py`
- `catalog/capabilities/memory_reflect/`
