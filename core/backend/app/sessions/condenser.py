from __future__ import annotations
import uuid
"""
SessionCondenser — pattern-based MVP for session → derived summary.

Invariants:
- Never creates a MemoryEntry (active or proposed).
- Never creates a Proposal.
- SessionSummary is derived context, not source of truth.
- Multiple summaries per session: latest active is the one used by ContextBuilder.
"""

import logging
import re
from collections import Counter
from datetime import UTC, datetime

from sqlalchemy.orm import Session as DBSession

from ..models import Message, SessionSummary

log = logging.getLogger(__name__)

_CONDENSER_VERSION = "pattern.v1"
_STOPWORDS = frozenset(
    "a an the is are was were be been being have has had do does did will would could should "
    "may might shall can i you he she it we they me him her us them my your his its our their "
    "this that these those and or but not in on at to of for with by from up out as so if then "
    "no yes just also like more some any all here there when where how what who".split()
)
_MAX_MESSAGES = 40
_MAX_SUMMARY_CHARS = 1_200


def _new_id() -> str:
    return str(uuid.uuid4())


def _extract_keywords(text: str, top_n: int = 8) -> list[str]:
    words = re.findall(r"[a-zA-Z]{3,}", text.lower())
    filtered = [w for w in words if w not in _STOPWORDS]
    return [w for w, _ in Counter(filtered).most_common(top_n)]


def _summarise_messages(messages: list[Message]) -> str:
    """
    Pattern-based condensation: extracts role counts, key user phrases, top keywords.
    Produces a 1–3 sentence plaintext summary. No LLM calls.
    """
    user_turns = [m for m in messages if m.role == "user"]
    assistant_turns = [m for m in messages if m.role == "assistant"]

    total = len(messages)
    lines: list[str] = [f"Session with {total} messages ({len(user_turns)} user, {len(assistant_turns)} assistant)."]

    # Extract first non-trivial user message as the stated goal
    goal_sentence = ""
    for m in user_turns[:3]:
        text = (m.content or "").strip()
        if len(text) > 20:
            # Trim to first sentence
            sentence = re.split(r"[.!?\n]", text)[0].strip()
            if sentence:
                goal_sentence = sentence[:200]
                break
    if goal_sentence:
        lines.append(f"User goal: {goal_sentence}.")

    # Keyword extraction across all content
    all_text = " ".join(
        (m.content or "")
        for m in messages
        if m.role in ("user", "assistant")
    )
    keywords = _extract_keywords(all_text)
    if keywords:
        lines.append(f"Key topics: {', '.join(keywords)}.")

    summary = " ".join(lines)
    return summary[:_MAX_SUMMARY_CHARS]


class SessionCondenser:
    """
    Condenses a session's messages into a derived SessionSummary.

    Never writes MemoryEntry, Proposal, or Policy.
    """

    def __init__(self, db: DBSession) -> None:
        self._db = db

    def get_latest(self, session_id: str, space_id: str) -> SessionSummary | None:
        """Return the current active summary for a session, or None."""
        return (
            self._db.query(SessionSummary)
            .filter(
                SessionSummary.session_id == session_id,
                SessionSummary.space_id == space_id,
                SessionSummary.status == "active",
            )
            .order_by(SessionSummary.version.desc())
            .first()
        )

    def condense(self, session_id: str, space_id: str, user_id: str | None = None) -> SessionSummary:
        """
        Condense the session's messages into a new SessionSummary.

        Supersedes any existing active summary for this session.
        Never creates MemoryEntry or Proposal.
        Queries messages filtered by both session_id and space_id.
        """
        messages = (
            self._db.query(Message)
            .filter(Message.session_id == session_id, Message.space_id == space_id)
            .order_by(Message.created_at.asc())
            .limit(_MAX_MESSAGES)
            .all()
        )

        if not messages:
            summary_text = "Empty session — no messages to summarise."
            first_msg_id = None
            last_msg_id = None
        else:
            summary_text = _summarise_messages(messages)
            first_msg_id = messages[0].id
            last_msg_id = messages[-1].id

        # Char-level token estimates (≈ 4 chars/token approximation)
        source_chars = sum(len(m.content or "") for m in messages)
        summary_chars = len(summary_text)

        keywords = _extract_keywords(
            " ".join(m.content or "" for m in messages if m.role in ("user", "assistant"))
        )
        user_turns = [m for m in messages if m.role == "user"]
        assistant_turns = [m for m in messages if m.role == "assistant"]
        summary_json_value: dict = {
            "condenser_version": _CONDENSER_VERSION,
            "role_counts": {"user": len(user_turns), "assistant": len(assistant_turns)},
            "top_keywords": keywords,
            "source_range": {
                "first_message_id": first_msg_id,
                "last_message_id": last_msg_id,
                "message_count": len(messages),
            },
        }

        # Supersede existing active summary
        existing = self.get_latest(session_id, space_id)
        new_version = 1
        if existing is not None:
            existing.status = "superseded"
            self._db.add(existing)
            new_version = existing.version + 1

        row = SessionSummary(
            id=_new_id(),
            space_id=space_id,
            session_id=session_id,
            user_id=user_id,
            version=new_version,
            status="active",
            summary_text=summary_text,
            source_message_count=len(messages),
            source_first_message_id=first_msg_id,
            source_last_message_id=last_msg_id,
            summary_json=summary_json_value,
            token_estimate_before=source_chars // 4,
            token_estimate_after=summary_chars // 4,
            condenser_version=_CONDENSER_VERSION,
            created_at=datetime.now(UTC),
        )
        self._db.add(row)
        self._db.flush()
        log.debug(
            "SessionCondenser: condensed session=%s v%d (%d msgs)",
            session_id,
            new_version,
            len(messages),
        )
        return row
