"""Activity consolidation — classifier → validator → proposal producer."""

from .constants import CONSOLIDATION_COMPILER_VERSION, MEMORY_EVOLVER_COMPILER_VERSION
from .service import ActivityConsolidationService, ConsolidationRunResult, run_memory_consolidation_job_payload

__all__ = [
    "CONSOLIDATION_COMPILER_VERSION",
    "MEMORY_EVOLVER_COMPILER_VERSION",
    "ActivityConsolidationService",
    "ConsolidationRunResult",
    "run_memory_consolidation_job_payload",
]
