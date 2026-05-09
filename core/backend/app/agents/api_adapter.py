from __future__ import annotations
"""
AnthropicAPIAdapter — lightweight adapter that calls the Anthropic SDK directly.

Use this for tasks that do not need filesystem access, terminal execution, or git.
Examples: summarization, classification, memory extraction, title generation, digest.

Unlike the CLI adapters, this adapter:
  - Runs in-process (no subprocess, no sandbox, no worktree)
  - Is always available when ANTHROPIC_API_KEY is set
  - Formats context as a system prompt prefix, not a CLAUDE.md file
"""

import json
import logging
from datetime import datetime, UTC

from .base import AgentAdapter, AgentRunResult, CLIAdapterCapabilities

log = logging.getLogger(__name__)

_CONTEXT_TEMPLATE = """You are operating inside the agent-space system.

## Context
{context_summary}
"""


def _summarize_context(context: dict) -> str:
    parts: list[str] = []
    for key in ("user_memory", "workspace_memory", "system_policy"):
        items = context.get(key, [])
        if items:
            parts.append(f"### {key}")
            for item in items[:5]:
                if isinstance(item, dict):
                    parts.append(f"- {item.get('title', '')}: {item.get('content', '')[:200]}")
    return "\n".join(parts) if parts else "(no context)"


class AnthropicAPIAdapter(AgentAdapter):
    """Calls the Anthropic Messages API directly — no CLI, no subprocess."""

    def __init__(self, model: str | None = None):
        self._model = model

    @property
    def adapter_type(self) -> str:
        return "anthropic_api"

    def is_available(self) -> bool:
        try:
            import anthropic  # noqa: F401
        except ImportError:
            return False
        from ..config import settings
        return bool(settings.anthropic_api_key)

    def get_capabilities(self) -> CLIAdapterCapabilities:
        return CLIAdapterCapabilities(
            supports_headless_run=True,
            supports_interactive_run=False,
            supports_streaming_logs=False,
            supports_model_override=True,
        )

    def run(
        self,
        prompt: str,
        context: dict,
        workspace_path: str | None = None,
        timeout: int = 300,
        conversation: list[dict] | None = None,
        **_kwargs,
    ) -> AgentRunResult:
        """
        Run a prompt via the Anthropic Messages API.

        conversation: optional list of prior {role, content} messages for
        multi-turn sessions. When provided, the prompt is appended as a new
        user message and the full history is sent to the API.
        """
        started_at = datetime.now(UTC)
        try:
            import anthropic
        except ImportError:
            return AgentRunResult(
                success=False,
                output="",
                error="anthropic package not installed",
                started_at=started_at,
                completed_at=datetime.now(UTC),
            )

        from ..config import settings

        model = self._model or settings.default_model
        system_prompt = _CONTEXT_TEMPLATE.format(
            context_summary=_summarize_context(context)
        )

        # Build messages array: prior conversation + new user message
        messages: list[dict] = list(conversation) if conversation else []
        messages.append({"role": "user", "content": prompt})

        try:
            client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
            response = client.messages.create(
                model=model,
                max_tokens=4096,
                system=system_prompt,
                messages=messages,
            )
            output = response.content[0].text if response.content else ""
            return AgentRunResult(
                success=True,
                output=output,
                started_at=started_at,
                completed_at=datetime.now(UTC),
            )
        except Exception as exc:
            log.warning("AnthropicAPIAdapter error: %s", exc)
            return AgentRunResult(
                success=False,
                output="",
                error=str(exc),
                started_at=started_at,
                completed_at=datetime.now(UTC),
            )
