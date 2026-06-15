"""Generate the cross-language memory read-authorization parity fixture.

Runs the real Python ``can_read_memory`` + ``summary_only_redact_content`` over a
matrix that exercises every visibility, sensitivity, owner/scope, workspace, and
selected-user branch, and emits ``{input, expected}`` cases. The TS
``canReadMemory`` / ``summaryOnlyRedactContent`` must match exactly — this is the
security boundary for the memory-read slice, so any divergence is a leak.

Usage (from backend/):
    .venv/bin/python -m tests.support.gen_memory_read_auth_parity \
        > ../control-plane/test/fixtures/memory_read_auth_parity.json
"""

import json
import sys
from types import SimpleNamespace

sys.path.insert(0, ".")

from app.memory.read_auth import (  # noqa: E402
    can_read_memory,
    summary_only_redact_content,
)


def _mem(**kw):
    """A MemoryEntry-like object with the fields the auth logic reads."""
    base = {
        "space_id": "space-1",
        "deleted_at": None,
        "sensitivity_level": "normal",
        "visibility": "private",
        "owner_user_id": None,
        "scope_type": "user",
        "workspace_id": None,
        "selected_user_ids": None,
    }
    base.update(kw)
    return SimpleNamespace(**base)


VIS = [
    "private",
    "space_shared",
    "workspace_shared",
    "selected_users",
    "restricted",
    "summary_only",
    "public_template",
]

cases = []

# 1. Cross-space deny + soft-deleted deny.
cases.append({"mem": {"space_id": "space-2", "visibility": "space_shared"}, "ctx": {}})
cases.append({"mem": {"deleted_at": "2026-01-01T00:00:00Z", "visibility": "space_shared"}, "ctx": {}})

# 2. Owner always reads (except is itself the highly_restricted owner case below).
for vis in VIS:
    cases.append({"mem": {"visibility": vis, "owner_user_id": "user-1"}, "ctx": {}})

# 3. Non-owner against each visibility.
for vis in VIS:
    cases.append({"mem": {"visibility": vis, "owner_user_id": "owner-x"}, "ctx": {}})

# 4. highly_restricted: only owner.
cases.append({"mem": {"sensitivity_level": "highly_restricted", "owner_user_id": "user-1", "visibility": "space_shared"}, "ctx": {}})
cases.append({"mem": {"sensitivity_level": "highly_restricted", "owner_user_id": "owner-x", "visibility": "space_shared"}, "ctx": {}})

# 5. workspace_shared: match / mismatch / null on either side.
cases.append({"mem": {"visibility": "workspace_shared", "owner_user_id": "owner-x", "workspace_id": "ws-1"}, "ctx": {"workspaceId": "ws-1"}})
cases.append({"mem": {"visibility": "workspace_shared", "owner_user_id": "owner-x", "workspace_id": "ws-1"}, "ctx": {"workspaceId": "ws-2"}})
cases.append({"mem": {"visibility": "workspace_shared", "owner_user_id": "owner-x", "workspace_id": None}, "ctx": {"workspaceId": "ws-1"}})
cases.append({"mem": {"visibility": "workspace_shared", "owner_user_id": "owner-x", "workspace_id": "ws-1"}, "ctx": {}})

# 6. selected_users / restricted: list contains / not / string form.
cases.append({"mem": {"visibility": "selected_users", "owner_user_id": "owner-x", "selected_user_ids": ["user-1", "user-9"]}, "ctx": {}})
cases.append({"mem": {"visibility": "selected_users", "owner_user_id": "owner-x", "selected_user_ids": ["user-9"]}, "ctx": {}})
cases.append({"mem": {"visibility": "restricted", "owner_user_id": "owner-x", "selected_user_ids": "user-1"}, "ctx": {}})
cases.append({"mem": {"visibility": "restricted", "owner_user_id": "owner-x", "selected_user_ids": None}, "ctx": {}})

# 7. system scope: excluded unless include_system_scope.
cases.append({"mem": {"scope_type": "system", "visibility": "space_shared", "owner_user_id": None}, "ctx": {}})
cases.append({"mem": {"scope_type": "system", "visibility": "space_shared", "owner_user_id": None}, "ctx": {"includeSystemScope": True}})

# 8. public_template: excluded unless include_public_templates.
cases.append({"mem": {"visibility": "public_template", "owner_user_id": "owner-x"}, "ctx": {}})
cases.append({"mem": {"visibility": "public_template", "owner_user_id": "owner-x"}, "ctx": {"includePublicTemplates": True}})

# 9. summary_only redaction: owner not redacted, non-owner redacted.
cases.append({"mem": {"visibility": "summary_only", "owner_user_id": "user-1"}, "ctx": {}})
cases.append({"mem": {"visibility": "summary_only", "owner_user_id": "owner-x"}, "ctx": {}})


USER = "user-1"
SPACE = "space-1"

out = []
for case in cases:
    mem = _mem(**case["mem"])
    ctx = case["ctx"]
    allowed = can_read_memory(
        mem,
        user_id=USER,
        space_id=SPACE,
        workspace_id=ctx.get("workspaceId"),
        include_system_scope=ctx.get("includeSystemScope", False),
        include_public_templates=ctx.get("includePublicTemplates", False),
    )
    redact = summary_only_redact_content(mem, viewer_user_id=USER)
    out.append(
        {
            "memory": {
                "space_id": mem.space_id,
                "deleted_at": mem.deleted_at,
                "sensitivity_level": mem.sensitivity_level,
                "visibility": mem.visibility,
                "owner_user_id": mem.owner_user_id,
                "scope_type": mem.scope_type,
                "workspace_id": mem.workspace_id,
                "selected_user_ids": mem.selected_user_ids,
            },
            "ctx": {
                "userId": USER,
                "spaceId": SPACE,
                "workspaceId": ctx.get("workspaceId"),
                "includeSystemScope": ctx.get("includeSystemScope", False),
                "includePublicTemplates": ctx.get("includePublicTemplates", False),
            },
            "expected": {"can_read": allowed, "redact_content": redact},
        }
    )

print(json.dumps(out, indent=2))
