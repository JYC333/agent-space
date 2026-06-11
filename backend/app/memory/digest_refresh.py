from __future__ import annotations
"""
ContextDigestRefreshService — explicit refresh gate for dirty ContextDigest rows.

Design principle:
  Digests are never auto-regenerated when marked dirty. This service is the
  single explicit call site for regeneration. Callers decide when to pay the
  cost; dirty digests remain readable (stale but available) until refreshed.

Usage:
    svc = ContextDigestRefreshService(db)
    # Refresh a specific dirty digest:
    digest = svc.refresh(space_id, "workspace", workspace_id, "workspace")
    # Refresh all dirty digests for a space:
    refreshed = svc.refresh_all_dirty(space_id)
"""

import logging
from typing import Optional

from sqlalchemy.orm import Session as DBSession

from ..models import ContextDigest
from .digest_service import ContextDigestService

log = logging.getLogger(__name__)

_SUPPORTED_DIGEST_TYPES = frozenset({"policy_bundle", "workspace", "agent"})


class ContextDigestRefreshService:
    """
    Regenerates dirty ContextDigest rows via the appropriate ContextDigestService method.

    Never writes MemoryEntry, Proposal, or Policy.
    Only reads active MemoryEntry and active/enabled Policy rows (delegated to ContextDigestService).
    """

    def __init__(self, db: DBSession) -> None:
        self._db = db
        self._svc = ContextDigestService(db)

    def refresh(
        self,
        space_id: str,
        scope_type: str,
        scope_id: Optional[str],
        digest_type: str,
    ) -> ContextDigest:
        """
        Explicitly regenerate the digest for the given scope.

        Works whether or not the digest is currently dirty — idempotent
        when sources have not changed (ContextDigestService.generate_* reuses
        existing digest when source_hash is unchanged).
        """
        if digest_type not in _SUPPORTED_DIGEST_TYPES:
            raise ValueError(f"Unsupported digest_type: {digest_type!r}. Must be one of {sorted(_SUPPORTED_DIGEST_TYPES)}")

        log.debug(
            "ContextDigestRefreshService.refresh: space=%s scope_type=%s scope_id=%s type=%s",
            space_id, scope_type, scope_id, digest_type,
        )

        if digest_type == "policy_bundle":
            return self._svc.generate_policy_bundle_digest(
                space_id, scope_type=scope_type, scope_id=scope_id
            )
        elif digest_type == "workspace":
            if not scope_id:
                raise ValueError("scope_id required for digest_type='workspace'")
            return self._svc.generate_workspace_digest(space_id, scope_id)
        else:  # agent
            if not scope_id:
                raise ValueError("scope_id required for digest_type='agent'")
            return self._svc.generate_agent_digest(space_id, scope_id)

    def refresh_all_dirty(self, space_id: str) -> list[ContextDigest]:
        """
        Regenerate every digest currently marked dirty for the given space.

        Returns the list of refreshed ContextDigest rows. Failures for individual
        digests are logged and skipped so that one bad scope does not block others.
        """
        dirty_rows = (
            self._db.query(ContextDigest)
            .filter(
                ContextDigest.space_id == space_id,
                ContextDigest.status == "dirty",
            )
            .all()
        )

        if not dirty_rows:
            log.debug("ContextDigestRefreshService.refresh_all_dirty: no dirty digests for space=%s", space_id)
            return []

        refreshed: list[ContextDigest] = []
        for row in dirty_rows:
            try:
                result = self.refresh(space_id, row.scope_type, row.scope_id, row.digest_type)
                refreshed.append(result)
                log.debug(
                    "ContextDigestRefreshService: refreshed %s/%s/%s → v%d",
                    row.digest_type, row.scope_type, row.scope_id, result.version,
                )
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "ContextDigestRefreshService: failed to refresh %s/%s/%s: %s",
                    row.digest_type, row.scope_type, row.scope_id, exc,
                )

        return refreshed

    def get_dirty_count(self, space_id: str) -> int:
        """Return the number of dirty digests for quick health checks."""
        return (
            self._db.query(ContextDigest)
            .filter(
                ContextDigest.space_id == space_id,
                ContextDigest.status == "dirty",
            )
            .count()
        )
