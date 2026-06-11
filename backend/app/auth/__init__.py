"""Public facade for the ``auth`` module — the most-imported kernel seam.

Re-exports the identity / session / space-authorization symbols other modules
import from ``auth`` today. Callers should depend on ``app.auth`` rather than
reaching into ``auth.api_key`` / ``auth.session`` / ``auth.policy`` /
``auth.service`` / ``auth.google`` directly.

Eager re-export is safe: ``auth`` submodules import only leaf utility packages
(``feature_gates``, ``param_binding``) and ``policy.roles`` at module load —
none import ``auth`` back, so there is no import cycle.
"""

from __future__ import annotations

from .api_key import get_identity, ApiKeyService
from .google import is_configured
from .policy import (
    can_manage_space_resources,
    can_use_space,
    require_invite_member,
    require_manage_space,
    require_use_space,
    require_view_space,
)
from .service import UserService
from .session import get_current_user

__all__ = [
    "get_identity",
    "ApiKeyService",
    "UserService",
    "get_current_user",
    "is_configured",
    "can_manage_space_resources",
    "can_use_space",
    "require_invite_member",
    "require_manage_space",
    "require_use_space",
    "require_view_space",
]
