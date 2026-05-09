# Module: Capability

## Purpose
Define, register, and lifecycle-manage code-defined skills that agents can invoke. A capability is more than a prompt — it includes code, tests, permissions, and versioning.

## Owns
- `Capability` ORM model and registry
- `CapabilityVersion` — version history
- `CapabilityTest` — test results per version
- YAML manifest loader (`capabilities/registry.py`)
- Capability seeding at startup

## Does Not Own
- Agent assignment of capabilities (stored on Agent.capabilities_json)
- Proposal approval for capability changes (proposals module)
- Tool permissions enforcement (policy module)

## Key Models

```
Capability:
  id, name, version, description
  entrypoint  — code path or command
  manifest_json  — full YAML parsed
  enabled (bool)
  created_at, updated_at

CapabilityVersion:
  capability_id, version, manifest_json
  status (draft|proposed|testing|enabled|disabled|deprecated|rejected|archived)
  created_at

CapabilityTest:
  capability_id, version, test_name
  status (pass|fail|skip), output, created_at
```

## Capability Manifest (YAML)

```yaml
id: my.capability
name: My Capability
version: "1.0"
description: What this capability does
entrypoint: python my_capability/main.py
permissions:
  tools: [read_file, write_memory_proposal]
  memory_scopes: [user, workspace]
prompts:
  system: ...
tests:
  - name: basic_test
    input: ...
    expected_output: ...
```

## Lifecycle

```
draft → proposed → testing → enabled
                ↓          ↓
             rejected    disabled → deprecated → archived
```

- `draft` — created locally, not reviewed
- `proposed` — submitted for approval
- `testing` — sandbox test runs in progress
- `enabled` — active and available to agents
- `disabled` — temporarily disabled
- `deprecated` — replaced by newer version
- `archived` — permanently retired

## Main Flows

**Register capability:**
1. Create `core/capabilities/<id>/capability.yaml`
2. `POST /api/v1/capabilities/reload` or restart server
3. `CapabilityRegistry` loads and validates manifest
4. `Capability` record created/updated in DB

**Self-evolution (agent modifying capabilities):**
1. Agent generates `capability_install` proposal
2. Sandbox test runs validate the new version
3. User approves → capability version promoted to `enabled`
4. Old version deprecated

## Invariants
- A capability without tests and a manifest is incomplete — cannot be `enabled`
- Capability changes from agents must go through `capability_install` proposals
- `enabled` capabilities must pass their tests in CI-equivalent before promotion

## Related Files
- `core/capabilities/` — YAML manifests
- `core/backend/app/capabilities/registry.py` — manifest loader
- `core/backend/app/models.py` — Capability, CapabilityVersion, CapabilityTest

## Built-in Capabilities
- `agent.echo` — echo adapter demo
- `memory.reflect` — session → memory proposals
