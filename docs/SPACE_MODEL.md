# Space Model

## Concept

A **space** is the top-level isolation boundary in agent-space. One deployment instance
can host many spaces:

```
Deployment Instance
  ├── Personal Space   (personal, family)
  ├── Family Space     (household)
  └── Team Space       (small team)
```

## Database model

```sql
CREATE TABLE spaces (
  id TEXT PRIMARY KEY,           -- e.g. "personal", "family", "acme-team"
  name TEXT NOT NULL,
  type TEXT NOT NULL,            -- personal | household | team
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE space_memberships (
  id TEXT PRIMARY KEY,
  space_id TEXT NOT NULL REFERENCES spaces(id),
  user_id TEXT NOT NULL,
  role TEXT NOT NULL,            -- owner | admin | member | guest
  status TEXT NOT NULL,          -- active | invited | suspended
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE workspace_memberships (
  id TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL,
  user_id TEXT NOT NULL,
  role TEXT NOT NULL,            -- owner | editor | viewer | agent_operator
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
```

## Rules

- Every data record (Memory, Session, Task, Run, etc.) carries a `space_id`.
- The ContextBuilder requires `space_id` and `user_id` — it will raise if either is missing.
- Memory queries filter by `space_id` first. No query can retrieve memory across spaces.
- `space_shared` visibility means visible to all members of the same space.
- `workspace_shared` visibility means visible to workspace members only.
- `private` visibility means visible to the owner only.

## Roles

Space-level roles:
- `owner` — full control, can delete the space
- `admin` — manage members and workspaces
- `member` — normal access
- `guest` — read-only, limited access

Workspace-level roles:
- `owner` — full workspace control
- `editor` — read/write
- `viewer` — read-only
- `agent_operator` — can trigger agent runs
