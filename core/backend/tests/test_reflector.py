"""
Tests for MemoryReflector — placeholder and LLM modes.
"""
import json
import pytest
from unittest.mock import MagicMock, patch

from app.memory.reflector import MemoryReflector, _classify_message, _extract_title
from app.models import Message
from app.memory.proposals import MemoryProposalService
from tests.conftest import SPACE, USER


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def test_classify_preference_signal():
    result = _classify_message("I prefer dark mode for coding.")
    assert result is not None
    memory_type, namespace = result
    assert memory_type == "preference"
    assert "preferences" in namespace


def test_classify_goal_signal():
    result = _classify_message("My goal is to learn Rust this year.")
    assert result is not None
    assert result[0] == "semantic"
    assert "goals" in result[1]


def test_classify_fact_signal():
    result = _classify_message("I am a backend engineer.")
    assert result is not None
    assert result[0] == "semantic"
    assert "profile" in result[1]


def test_classify_uninteresting_message():
    assert _classify_message("What time is it?") is None
    assert _classify_message("OK, thanks.") is None


def test_extract_title_short():
    assert _extract_title("I prefer Python") == "I prefer Python"


def test_extract_title_truncates_long():
    long_content = "x" * 100
    title = _extract_title(long_content)
    assert len(title) <= 80


def test_extract_title_first_sentence():
    title = _extract_title("I prefer dark mode. Everything else is secondary.")
    assert title == "I prefer dark mode"


# ---------------------------------------------------------------------------
# Placeholder mode (no LLM, no API key needed)
# ---------------------------------------------------------------------------

def _seed_messages(db, session_id: str, contents: list[str]) -> list[Message]:
    from app.models import Session as ChatSession
    # Message.session_id is a FK — ensure the parent session exists
    if not db.query(ChatSession).filter(ChatSession.id == session_id).first():
        db.add(ChatSession(id=session_id, space_id=SPACE, user_id=USER))
        db.commit()

    msgs = []
    for content in contents:
        msg = Message(
            id=f"msg-{session_id}-{len(msgs)}",
            session_id=session_id,
            space_id=SPACE,
            user_id=USER,
            role="user",
            content=content,
        )
        db.add(msg)
        msgs.append(msg)
    db.commit()
    return msgs


def test_placeholder_mode_extracts_preference(db, monkeypatch):
    monkeypatch.setattr("app.config.settings.reflector_mode", "placeholder")
    _seed_messages(db, "session-1", ["I prefer tabs over spaces."])
    reflector = MemoryReflector(db)
    proposals = reflector.reflect("session-1", SPACE, USER)
    assert len(proposals) == 1
    assert proposals[0].memory_type == "preference"


def test_placeholder_mode_ignores_uninteresting(db, monkeypatch):
    monkeypatch.setattr("app.config.settings.reflector_mode", "placeholder")
    _seed_messages(db, "session-2", ["Hello!", "How are you?", "OK bye."])
    reflector = MemoryReflector(db)
    proposals = reflector.reflect("session-2", SPACE, USER)
    assert proposals == []


def test_placeholder_mode_deduplicates_titles(db, monkeypatch):
    monkeypatch.setattr("app.config.settings.reflector_mode", "placeholder")
    # Both messages produce the same extracted title ("I prefer Python over Java")
    # because _extract_title splits on sentence boundaries.
    _seed_messages(db, "session-3", [
        "I prefer Python over Java. It is more readable.",
        "I prefer Python over Java. The ecosystem is great.",
    ])
    reflector = MemoryReflector(db)
    proposals = reflector.reflect("session-3", SPACE, USER)
    assert len(proposals) == 1


def test_placeholder_mode_multiple_types(db, monkeypatch):
    monkeypatch.setattr("app.config.settings.reflector_mode", "placeholder")
    _seed_messages(db, "session-4", [
        "I prefer vim over emacs.",
        "My goal is to ship by Q3.",
        "I am a senior staff engineer.",
    ])
    reflector = MemoryReflector(db)
    proposals = reflector.reflect("session-4", SPACE, USER)
    assert len(proposals) == 3
    types = {p.memory_type for p in proposals}
    assert "preference" in types
    assert "semantic" in types


def test_placeholder_mode_only_processes_user_messages(db, monkeypatch):
    monkeypatch.setattr("app.config.settings.reflector_mode", "placeholder")
    from app.models import Session as ChatSession
    db.add(ChatSession(id="session-5", space_id=SPACE, user_id=USER))
    db.commit()
    # Assistant message with preference signal — should NOT be extracted
    msg = Message(
        id="asst-msg",
        session_id="session-5",
        space_id=SPACE,
        user_id=USER,
        role="assistant",
        content="I prefer to help you.",
    )
    db.add(msg)
    db.commit()

    reflector = MemoryReflector(db)
    proposals = reflector.reflect("session-5", SPACE, USER)
    assert proposals == []


def test_placeholder_mode_empty_session(db, monkeypatch):
    monkeypatch.setattr("app.config.settings.reflector_mode", "placeholder")
    reflector = MemoryReflector(db)
    proposals = reflector.reflect("session-empty", SPACE, USER)
    assert proposals == []


# ---------------------------------------------------------------------------
# LLM mode — mock the Anthropic client
# ---------------------------------------------------------------------------

def _make_mock_response(items: list[dict]) -> MagicMock:
    content = MagicMock()
    content.text = json.dumps(items)
    response = MagicMock()
    response.content = [content]
    return response


def test_llm_mode_parses_response(db, monkeypatch):
    monkeypatch.setattr("app.config.settings.reflector_mode", "llm")
    monkeypatch.setattr("app.config.settings.anthropic_api_key", "sk-test")

    _seed_messages(db, "session-llm-1", ["I prefer dark mode."])

    mock_response = _make_mock_response([{
        "memory_type": "preference",
        "target_namespace": "user.default.preferences",
        "proposed_title": "Prefers dark mode",
        "proposed_content": "User prefers dark mode.",
        "rationale": "Explicitly stated.",
    }])

    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response
    mock_anthropic = MagicMock()
    mock_anthropic.Anthropic.return_value = mock_client

    import sys
    monkeypatch.setitem(sys.modules, "anthropic", mock_anthropic)

    reflector = MemoryReflector(db)
    proposals = reflector.reflect("session-llm-1", SPACE, USER)

    assert len(proposals) == 1
    assert proposals[0].proposed_title == "Prefers dark mode"
    assert proposals[0].memory_type == "preference"


def test_llm_mode_handles_empty_response(db, monkeypatch):
    monkeypatch.setattr("app.config.settings.reflector_mode", "llm")
    monkeypatch.setattr("app.config.settings.anthropic_api_key", "sk-test")

    _seed_messages(db, "session-llm-2", ["Hello there."])

    mock_response = _make_mock_response([])
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response
    mock_anthropic = MagicMock()
    mock_anthropic.Anthropic.return_value = mock_client

    import sys
    monkeypatch.setitem(sys.modules, "anthropic", mock_anthropic)

    reflector = MemoryReflector(db)
    proposals = reflector.reflect("session-llm-2", SPACE, USER)
    assert proposals == []


def test_llm_mode_falls_back_to_placeholder_on_bad_json(db, monkeypatch):
    monkeypatch.setattr("app.config.settings.reflector_mode", "llm")
    monkeypatch.setattr("app.config.settings.anthropic_api_key", "sk-test")

    _seed_messages(db, "session-llm-3", ["I prefer Rust."])

    content = MagicMock()
    content.text = "not valid json {{{"
    mock_response = MagicMock()
    mock_response.content = [content]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response
    mock_anthropic = MagicMock()
    mock_anthropic.Anthropic.return_value = mock_client

    import sys
    monkeypatch.setitem(sys.modules, "anthropic", mock_anthropic)

    reflector = MemoryReflector(db)
    # Bad JSON → returns [] (no crash)
    proposals = reflector.reflect("session-llm-3", SPACE, USER)
    assert proposals == []


def test_llm_mode_falls_back_to_placeholder_without_api_key(db, monkeypatch):
    monkeypatch.setattr("app.config.settings.reflector_mode", "llm")
    monkeypatch.setattr("app.config.settings.anthropic_api_key", "")

    _seed_messages(db, "session-llm-4", ["I prefer dark mode."])

    reflector = MemoryReflector(db)
    # No key → falls back to placeholder
    proposals = reflector.reflect("session-llm-4", SPACE, USER)
    assert len(proposals) == 1


def test_llm_mode_falls_back_when_import_fails(db, monkeypatch):
    monkeypatch.setattr("app.config.settings.reflector_mode", "llm")
    monkeypatch.setattr("app.config.settings.anthropic_api_key", "sk-test")
    _seed_messages(db, "session-llm-5", ["I prefer dark mode."])

    import sys
    monkeypatch.setitem(sys.modules, "anthropic", None)

    reflector = MemoryReflector(db)
    proposals = reflector.reflect("session-llm-5", SPACE, USER)
    # Falls back to placeholder
    assert len(proposals) == 1
