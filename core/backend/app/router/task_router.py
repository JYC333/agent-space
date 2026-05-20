from __future__ import annotations
"""
TaskRouter — routes agent runs to the appropriate adapter based on task requirements.

Principle:
  CLI adapters (claude_code, codex_cli) are expensive execution runtimes.
  They should only be used when the task genuinely needs filesystem access,
  terminal execution, or git operations.

  Lightweight text tasks (summarization, classification, memory extraction,
  digest generation, tagging, title generation) do not need CLI capabilities.
  When a CLI adapter is requested for a lightweight task, the router returns
  the requested adapter unchanged — the caller is responsible for choosing an
  appropriate non-CLI adapter (e.g. capability) for tasks that don't need CLI.

Policy:
  anthropic_api is NOT a supported adapter type. Anthropic/Claude usage must
  go through CLI integrations (claude_code / claude_cli) only.
  Do NOT add anthropic_api or anthropic_messages as downgrade targets.

Decision logic:
  If any of requires_filesystem | requires_terminal | requires_git is True,
  or requires_long_reasoning is True, keep the requested CLI adapter.
  Otherwise, return the requested adapter unchanged (no automatic downgrade).
"""

from dataclasses import dataclass, field

_CLI_ADAPTERS: frozenset[str] = frozenset({"claude_code", "claude_cli", "codex_cli"})

_LIGHTWEIGHT_TASK_TYPES: frozenset[str] = frozenset({
    "summarize",
    "classify",
    "tag",
    "extract",
    "memory_extract",
    "title_generate",
    "digest",
    "activity_compress",
    "duplicate_detect",
    "wiki_draft",
    "card_draft",
})

_HEAVY_TASK_TYPES: frozenset[str] = frozenset({
    "code_modify",
    "structure_change",
    "test_fix",
    "migration",
    "repo_analysis",
    "dependency_debug",
    "patch",
    "debug",
    "build",
})


@dataclass
class TaskClassification:
    task_type: str = "generic"
    risk_level: str = "medium"
    requires_filesystem: bool = False
    requires_terminal: bool = False
    requires_git: bool = False
    requires_long_reasoning: bool = False
    extra: dict = field(default_factory=dict)

    @property
    def needs_cli(self) -> bool:
        if self.requires_filesystem or self.requires_terminal or self.requires_git:
            return True
        if self.requires_long_reasoning:
            return True
        if self.task_type in _HEAVY_TASK_TYPES:
            return True
        return False


class TaskRouter:
    """
    Resolves the effective adapter type for a run request.

    Usage:
        router = TaskRouter()
        effective = router.resolve_adapter(requested_adapter, classification)
    """

    def resolve_adapter(
        self,
        requested_adapter: str,
        classification: TaskClassification,
    ) -> str:
        """
        Return the adapter type that should actually execute this task.

        If the requested adapter is already non-CLI, return it unchanged.
        If the requested adapter is a CLI type and the task needs CLI, keep it.
        If the requested adapter is a CLI type but the task does NOT need CLI,
        return the requested adapter unchanged — no automatic downgrade to a
        direct API adapter (anthropic_api is not a supported adapter type).
        The caller should request an appropriate non-CLI adapter directly.
        """
        if requested_adapter not in _CLI_ADAPTERS:
            return requested_adapter

        # CLI adapter: always return as-is.
        # The caller is responsible for choosing the right adapter for the task.
        return requested_adapter

    def classify_from_request(
        self,
        task_type: str | None,
        risk_level: str,
        requires_filesystem: bool,
        requires_terminal: bool,
        requires_git: bool,
        requires_long_reasoning: bool,
    ) -> TaskClassification:
        resolved_type = task_type or "generic"
        return TaskClassification(
            task_type=resolved_type,
            risk_level=risk_level,
            requires_filesystem=requires_filesystem,
            requires_terminal=requires_terminal,
            requires_git=requires_git,
            requires_long_reasoning=requires_long_reasoning,
        )
