from __future__ import annotations
"""
MemoryReflector — analyzes a session's messages and generates memory proposals.

Non-LLM mode: deterministic extraction without an external model.
Mode "llm": calls a configured ModelProvider (OpenAI-compatible only) via the
             provider_client module.  Anthropic is not supported as a direct
             provider — use an OpenAI-compatible provider.
"""

import json
import re
from typing import Optional
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Message
from ..proposals import ProposalService
from ..providers import complete_text
from .provider_client import resolve_reflector_provider_id


# Signal phrases that suggest a memory-worthy statement
_PREFERENCE_SIGNALS = [
    r"\bi prefer\b", r"\bi like\b", r"\bi dislike\b", r"\bi hate\b",
    r"\bi always\b", r"\bi never\b", r"\bmy preference\b", r"\bi want\b",
]
_GOAL_SIGNALS = [
    r"\bmy goal\b", r"\bi am trying to\b", r"\bi want to\b",
    r"\bmy objective\b", r"\bi am building\b", r"\bwe are building\b",
]
_FACT_SIGNALS = [
    r"\bi am a\b", r"\bi work as\b", r"\bmy name is\b",
    r"\bmy company\b", r"\bmy team\b", r"\bi use\b", r"\bwe use\b",
]


def _matches(text: str, patterns: list[str]) -> bool:
    lower = text.lower()
    return any(re.search(p, lower) for p in patterns)


def _classify_message(content: str) -> tuple[str, str] | None:
    """Return (memory_type, namespace) if the message looks memory-worthy, else None."""
    if _matches(content, _PREFERENCE_SIGNALS):
        return "preference", "user.default.preferences"
    if _matches(content, _GOAL_SIGNALS):
        return "semantic", "user.default.goals"
    if _matches(content, _FACT_SIGNALS):
        return "semantic", "user.default.profile"
    return None


def _extract_title(content: str) -> str:
    first_sentence = re.split(r"[.!?]", content)[0].strip()
    if len(first_sentence) > 80:
        return first_sentence[:77] + "..."
    return first_sentence or content[:80]


class MemoryReflector:
    def __init__(self, db: Session):
        self.db = db
        self.proposal_svc = ProposalService(db)

    def reflect(
        self,
        session_id: str,
        space_id: str,
        user_id: str,
        workspace_id: str | None = None,
    ) -> list:
        messages = (
            self.db.query(Message)
            .filter(Message.session_id == session_id, Message.role == "user")
            .order_by(Message.created_at)
            .all()
        )

        if settings.reflector_mode == "llm":
            return self._reflect_llm(
                messages, session_id, space_id, user_id, workspace_id
            )
        return self._reflect_pattern(
            messages, session_id, space_id, user_id, workspace_id
        )

    def _reflect_pattern(
        self,
        messages: list[Message],
        session_id: str,
        space_id: str,
        user_id: str,
        workspace_id: str | None,
    ) -> list:
        proposals = []
        seen_titles: set[str] = set()

        for msg in messages:
            classification = _classify_message(msg.content)
            if not classification:
                continue

            memory_type, namespace = classification
            title = _extract_title(msg.content)

            if title in seen_titles:
                continue
            seen_titles.add(title)

            proposal = self.proposal_svc.create_proposal(
                space_id=space_id,
                user_id=user_id,
                target_scope="user",
                target_namespace=namespace,
                memory_type=memory_type,
                proposed_title=title,
                proposed_content=msg.content,
                rationale=f"Extracted from session message using pattern matching ({memory_type}).",
                workspace_id=workspace_id,
                source_session_id=session_id,
            )
            proposals.append(proposal)

        return proposals

    def _reflect_llm(
        self,
        messages: list[Message],
        session_id: str,
        space_id: str,
        user_id: str,
        workspace_id: str | None,
    ) -> list:
        """Use a configured ModelProvider to generate structured memory proposals.

        Resolves provider config via ``settings.reflector_model_provider_id``
        (a ModelProvider row ID).  Credentials are decrypted through
        Credential.secret_ref — never read from environment variables.

        Raises:
            ReflectorModelProviderMissingError: no provider configured
            ProviderUnavailableError: configured provider missing/disabled
            UnsupportedProviderError: provider_type unknown/unsupported
        """
        provider_id, model = resolve_reflector_provider_id(settings)

        conversation = "\n".join(
            f"[{m.role.upper()}]: {m.content}" for m in messages
        )

        system_prompt = """You are a memory extraction assistant. Analyze the conversation and extract memory-worthy information.

Output a JSON array of memory proposals. Each proposal must have:
- memory_type: one of preference, semantic, episodic, procedural, project
- target_namespace: e.g. user.default.preferences, user.default.goals, user.default.profile
- proposed_title: short, descriptive title (max 80 chars)
- proposed_content: the full content to store
- rationale: why this is worth remembering

Return ONLY valid JSON. Example:
[{"memory_type": "preference", "target_namespace": "user.default.preferences", "proposed_title": "Prefers Python over Node", "proposed_content": "The user prefers Python for backend work.", "rationale": "User explicitly stated this preference."}]

If nothing is memory-worthy, return an empty array: []"""

        raw = complete_text(
            self.db,
            provider_id=provider_id,
            model=model,
            system=system_prompt,
            user=f"Conversation:\n\n{conversation}",
        ).text

        try:
            items = json.loads(raw.strip())
        except json.JSONDecodeError:
            return []

        proposals = []
        for item in items:
            proposal = self.proposal_svc.create_proposal(
                space_id=space_id,
                user_id=user_id,
                target_scope="user",
                target_namespace=item.get("target_namespace", "user.default"),
                memory_type=item.get("memory_type", "semantic"),
                proposed_title=item.get("proposed_title", "Untitled"),
                proposed_content=item.get("proposed_content", ""),
                rationale=item.get("rationale", "Generated by LLM reflector."),
                workspace_id=workspace_id,
                source_session_id=session_id,
            )
            proposals.append(proposal)

        return proposals
