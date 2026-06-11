"""Public facade for participation recording."""

from __future__ import annotations

from .service import record_participation, try_record_participation

__all__ = ["record_participation", "try_record_participation"]
