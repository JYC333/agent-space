"""
Memory access policies (scopes, proposals) and validators.

Row-level read authorization lives in ``read_auth.can_read_memory`` — use that
for every memory read path instead of duplicating visibility logic here.
"""

SCOPE_HIERARCHY = ["system", "space", "user", "workspace", "capability", "agent"]

# Scopes that require user approval before writing
PROPOSAL_REQUIRED_SCOPES = {"user", "workspace", "space", "system"}

# Scopes an agent can write directly (only ephemeral/session scopes)
DIRECT_WRITE_SCOPES = {"agent"}


def requires_proposal(scope: str) -> bool:
    return scope in PROPOSAL_REQUIRED_SCOPES


def validate_memory_type(memory_type: str) -> bool:
    return memory_type in {"preference", "semantic", "episodic", "procedural", "project"}


def validate_scope(scope: str) -> bool:
    return scope in set(SCOPE_HIERARCHY)


def validate_status(status: str) -> bool:
    return status in {"active", "archived", "proposed", "rejected", "superseded"}
