"""Public facade for the ``activity`` module — the raw-input front door.

Re-exports the symbols other modules import from ``activity`` today
(``agents``, ``intake``). Callers should depend on ``app.activity`` rather than
``activity.service`` / ``activity.input_summary_service``.
"""

from __future__ import annotations

from .input_summary_service import (
    InputSummaryCrossSpaceError,
    InputSummaryNoContentError,
    InputSummaryProviderCallError,
    InputSummaryProviderMissingError,
    InputSummaryService,
)
from .service import ActivityService

__all__ = [
    "ActivityService",
    "InputSummaryService",
    "InputSummaryCrossSpaceError",
    "InputSummaryNoContentError",
    "InputSummaryProviderCallError",
    "InputSummaryProviderMissingError",
]
