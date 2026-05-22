from __future__ import annotations

"""Registered policy domains for memory access control."""

from dataclasses import dataclass
from typing import Literal

PolicyDomainStatus = Literal["enforced", "deferred", "deny_by_default"]

MEMORY_PRIVATE_PLACEMENT = "memory.private_placement"
MEMORY_CROSS_SPACE_READ = "memory.cross_space_read"
RUN_USER_PRIVATE_SCOPE = "run.user_private_scope"


@dataclass(frozen=True)
class PolicyDomainSpec:
    domain: str
    purpose: str
    status: PolicyDomainStatus
    enforcement_point: str


DOMAIN_REGISTRY: dict[str, PolicyDomainSpec] = {
    MEMORY_PRIVATE_PLACEMENT: PolicyDomainSpec(
        domain=MEMORY_PRIVATE_PLACEMENT,
        purpose="visibility=private may only be stored in personal-type spaces",
        status="enforced",
        enforcement_point="app.memory.store.MemoryStore.create (via policy.enforcement.check_private_placement)",
    ),
    RUN_USER_PRIVATE_SCOPE: PolicyDomainSpec(
        domain=RUN_USER_PRIVATE_SCOPE,
        purpose="Same-space run context may include private memories owned by instructed user",
        status="enforced",
        enforcement_point="app.memory.retriever.MemoryRetriever hard filter (via policy.enforcement.can_read_memory_in_run_context)",
    ),
    MEMORY_CROSS_SPACE_READ: PolicyDomainSpec(
        domain=MEMORY_CROSS_SPACE_READ,
        purpose=(
            "Cross-space memory reads (future: explicit grants + policy; "
            "SourcePointer metadata does not activate this domain)"
        ),
        status="deferred",
        enforcement_point="app.memory.retriever.MemoryRetriever space_id hard filter (deny by default)",
    ),
}

SECURITY_SENSITIVE_DOMAINS = frozenset(
    {
        MEMORY_PRIVATE_PLACEMENT,
        MEMORY_CROSS_SPACE_READ,
        RUN_USER_PRIVATE_SCOPE,
    }
)

ALL_REGISTERED_DOMAINS = frozenset(DOMAIN_REGISTRY.keys())
