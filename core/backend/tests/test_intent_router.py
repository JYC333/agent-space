"""
Tests for IntentRouter — slash-command routing.
"""
import pytest
from app.router.intent_router import IntentRouter, RoutingDecision

SPACE = "personal"
USER = "default_user"

router = IntentRouter()


# ---------------------------------------------------------------------------
# Non-commands — should return None
# ---------------------------------------------------------------------------

def test_plain_message_returns_none():
    assert router.route("Hello, how are you?", SPACE, USER) is None


def test_empty_string_returns_none():
    assert router.route("", SPACE, USER) is None


def test_whitespace_only_returns_none():
    assert router.route("   ", SPACE, USER) is None


def test_question_returns_none():
    assert router.route("What can you do?", SPACE, USER) is None


# ---------------------------------------------------------------------------
# /memory reflect
# ---------------------------------------------------------------------------

def test_memory_reflect_routes_correctly():
    result = router.route("/memory reflect", SPACE, USER)
    assert result is not None
    assert result.action == "agent.run"
    assert result.agent_id == "system.memory-curator-agent"
    assert result.capability_id == "memory.reflect"
    assert result.space_id == SPACE


def test_memory_reflect_with_extra_args():
    result = router.route("/memory reflect extra args", SPACE, USER)
    assert result is not None
    assert result.capability_id == "memory.reflect"


def test_memory_reflect_preserves_workspace_id():
    result = router.route("/memory reflect", SPACE, USER, workspace_id="ws-1")
    assert result.workspace_id == "ws-1"


def test_memory_reflect_no_workspace_id_is_none():
    result = router.route("/memory reflect", SPACE, USER)
    assert result.workspace_id is None


# ---------------------------------------------------------------------------
# /agent run <name>
# ---------------------------------------------------------------------------

def test_agent_run_routes_correctly():
    result = router.route("/agent run my-agent", SPACE, USER)
    assert result is not None
    assert result.action == "agent.run"
    assert result.agent_id == "my-agent"
    assert result.space_id == SPACE


def test_agent_run_with_hyphenated_name():
    result = router.route("/agent run code-reviewer", SPACE, USER)
    assert result.agent_id == "code-reviewer"


def test_agent_run_with_extra_args_stored_in_params():
    result = router.route("/agent run my-agent arg1 arg2", SPACE, USER)
    assert result.agent_id == "my-agent"
    assert "extra" in result.params
    assert "arg1" in result.params["extra"]


def test_agent_run_missing_name_returns_none():
    # "/agent run" with no name doesn't match case ["agent", "run", agent_name, *rest]
    result = router.route("/agent run", SPACE, USER)
    assert result is None


# ---------------------------------------------------------------------------
# /capabilities list
# ---------------------------------------------------------------------------

def test_capabilities_list_routes_correctly():
    result = router.route("/capabilities list", SPACE, USER)
    assert result is not None
    assert result.action == "capabilities.list"
    assert result.space_id == SPACE


def test_capabilities_list_no_agent_id():
    result = router.route("/capabilities list", SPACE, USER)
    assert result.agent_id is None


# ---------------------------------------------------------------------------
# Unrecognised commands → None
# ---------------------------------------------------------------------------

def test_unknown_command_returns_none():
    assert router.route("/foobar", SPACE, USER) is None


def test_partial_command_returns_none():
    assert router.route("/memory", SPACE, USER) is None


def test_wrong_subcommand_returns_none():
    assert router.route("/memory delete", SPACE, USER) is None


def test_agent_without_run_returns_none():
    assert router.route("/agent list", SPACE, USER) is None


# ---------------------------------------------------------------------------
# RoutingDecision defaults
# ---------------------------------------------------------------------------

def test_routing_decision_defaults():
    d = RoutingDecision()
    assert d.agent_id is None
    assert d.capability_id is None
    assert d.workspace_id is None
    assert d.params == {}
