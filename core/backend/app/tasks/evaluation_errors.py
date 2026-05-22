"""Domain exceptions for TaskEvaluationService."""


class TaskEvaluationError(Exception):
    """Base exception for task evaluation failures."""


class TaskEvaluationNotFoundError(TaskEvaluationError):
    """Raised when a required object (task, run, run evaluation, TaskRun link) is not found."""


class TaskEvaluationInvalidRequestError(TaskEvaluationError):
    """Raised when a manual evaluation payload is invalid."""
