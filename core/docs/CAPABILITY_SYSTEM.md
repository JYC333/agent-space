# Capability System

## What is a capability?

A capability is a versioned, self-describing unit of agent behaviour.
It is not just a prompt — it is a folder containing:

```
capabilities/<capability-id>/
├── capability.yaml     Manifest (required)
├── README.md           Human docs
├── prompts/            Prompt templates
├── src/                Optional code
└── tests/              Capability tests
```

## capability.yaml fields

```yaml
id: memory.reflect          # Unique dot-separated ID
name: Memory Reflector      # Human name
version: "0.1.0"            # Semver
description: >              # Short description
  Analyzes sessions and proposes memories.

entrypoint: null            # Optional: path to entry script

memory_access:
  read:
    - scope: user
      types: [preference, semantic]
  write:
    - scope: user
      types: [preference, semantic]
      requires_proposal: true   # true = must go through proposal workflow

tools: []                   # Future: declared tool access
permissions:
  network: false
  filesystem: false
  subprocess: false

validation:
  min_messages: 1           # Capability-specific validation rules
```

## Capability Registry

The `CapabilityRegistry` scans `capabilities/` on startup and on `POST /api/v1/capabilities/reload`.

It:
1. Reads every `capability.yaml` in the directory
2. Validates required fields (`id`, `name`, `version`, `description`)
3. Upserts records into the `capabilities` database table
4. Reports loaded / failed counts

## Built-in capabilities

| ID | Purpose |
|---|---|
| `memory.reflect` | Analyze sessions, generate memory proposals |
| `agent.echo` | Dev/test: echo prompt and context back |

## Future capabilities (not yet implemented)

| ID | Purpose |
|---|---|
| `system.evolve` | Generate new capability code in sandbox, propose for approval |
| `research.web` | Web search + summarization with memory storage |
| `coding.agent` | Full CLI-based coding agent loop |
| `knowledge.wiki` | Personal knowledge base management |
