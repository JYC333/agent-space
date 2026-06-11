# Capability System

## What is a capability?

A capability is a versioned, self-describing unit of agent behaviour.
It is not just a prompt — it is a folder containing:

```
capabilities/<capability-id>/
├── capability.yaml     Manifest (required)
├── README.md           Human docs (optional)
├── main.py             Entry module (when using python_module entrypoint)
└── tests/              Capability tests (optional)
```

## capability.yaml fields

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

Only `entrypoint.type: python_module` is executable in the current backend. Shell commands, remote code loading, network/filesystem permissions beyond empty allowlists, and subprocess execution are rejected by the capability runtime.

## Capability Registry

The `CapabilityRegistry` loads capabilities from two sources:

1. **Builtin** — manifests under `catalog/capabilities/` (bundled with the backend).
2. **External workspace** — manifests under local roots registered on a `capability_library` workspace.

Reload happens on backend startup and on `POST /api/v1/capabilities/reload`.

### External workspace discovery

Register a workspace with:

- `workspace_type = "capability_library"` — real `Workspace.workspace_type` column
- `metadata_json.capability_roots` — list of relative local paths, e.g. `["capabilities"]`

Example workspace create payload fields:

```json
{
  "workspace_type": "capability_library",
  "metadata_json": {
    "capability_roots": ["capabilities"]
  }
}
```

External capability roots are **local only**. The registry does not scan GitHub URLs, remote URLs, absolute paths, or paths that escape the workspace root. Ordinary (`project`) workspaces are not scanned.

### Enable / disable state

| Source | Default | Persisted? |
|--------|---------|------------|
| Builtin | manifest `enabled` (default `true`) | No — manifest is source of truth on reload |
| External workspace | disabled | Yes — `$AGENT_SPACE_HOME/config/settings.yaml` |

Persisted shape:

```yaml
capabilities:
  enabled_external_capabilities:
    - research_intake
    - rss_watch
```

Manifests define capability code and metadata; they are **not** the local trust/enable store for external capabilities. Persisted IDs for capabilities that are no longer discovered are ignored safely. Newly discovered external capabilities are never auto-enabled.

This is not a marketplace or remote install system.

## Built-in capabilities

| ID | Purpose |
|---|---|
| `memory.reflect` | Analyze sessions, generate memory proposals |

## Execution

Capability runs use `adapter_type="capability"` on a `Run`. The runtime adapter loads the manifest from the registry, verifies the capability is discovered and enabled, validates entrypoint/permissions, imports the local module, and calls `execute(context)`.

## Related code

- `backend/app/capabilities/registry.py`
- `backend/app/capabilities/enabled_store.py`
- `backend/app/capabilities/loader.py`
- `backend/app/runtimes/adapters/capability.py`
