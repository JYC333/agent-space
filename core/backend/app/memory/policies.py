"""
Memory access policies.

Defines which scopes are readable/writable given space/user/workspace context.
Agents must go through proposals for long-term memory writes.
"""

SCOPE_HIERARCHY = ["system", "space", "user", "workspace", "capability", "agent"]

# Scopes that require user approval before writing
PROPOSAL_REQUIRED_SCOPES = {"user", "workspace", "space", "system"}

# Scopes an agent can write directly (only ephemeral/session scopes)
DIRECT_WRITE_SCOPES = {"agent"}


def can_read(
    scope: str,
    requesting_user_id: str,
    owner_user_id: str,
    visibility: str,
    space_id: str,
    requesting_space_id: str,
    workspace_id: str | None = None,
    requesting_workspace_id: str | None = None,
) -> bool:
    # Hard boundary — never cross space lines
    if space_id != requesting_space_id:
        return False

    if visibility == "private":
        return requesting_user_id == owner_user_id

    if visibility == "workspace_shared":
        if workspace_id and requesting_workspace_id:
            return workspace_id == requesting_workspace_id
        return requesting_user_id == owner_user_id

    if visibility == "space_shared":
        return True

    return False


def requires_proposal(scope: str) -> bool:
    return scope in PROPOSAL_REQUIRED_SCOPES


def validate_memory_type(memory_type: str) -> bool:
    return memory_type in {"preference", "semantic", "episodic", "procedural", "project"}


def validate_scope(scope: str) -> bool:
    return scope in set(SCOPE_HIERARCHY)


def validate_status(status: str) -> bool:
    return status in {"active", "archived", "proposed", "rejected", "superseded"}
