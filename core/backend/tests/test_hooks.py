"""
Tests for post-run hooks — docs_sync_reminder and the hook registration system.
"""
import logging
import pytest
from unittest.mock import MagicMock

from app.agents.runner import register_post_run_hook, _fire_post_run_hooks, _POST_RUN_HOOKS
from app.agents.base import AgentRunResult


def _make_run(adapter_type="echo", run_id="test-run"):
    run = MagicMock()
    run.id = run_id
    run.adapter_type = adapter_type
    return run


def _make_result(output=""):
    return AgentRunResult(success=True, output=output)


# ---------------------------------------------------------------------------
# Hook registration
# ---------------------------------------------------------------------------

def test_register_and_fire_custom_hook():
    fired = []

    @register_post_run_hook
    def my_hook(run, result):
        fired.append((run.id, result.output))

    run = _make_run()
    result = _make_result("hello")
    _fire_post_run_hooks(run, result)

    assert (run.id, "hello") in fired

    # Clean up — remove our test hook so it doesn't bleed into other tests
    _POST_RUN_HOOKS.remove(my_hook)


def test_fire_hooks_with_none_result():
    errors = []

    @register_post_run_hook
    def safe_hook(run, result):
        errors.append(result)  # None is valid

    _fire_post_run_hooks(_make_run(), None)
    assert None in errors

    _POST_RUN_HOOKS.remove(safe_hook)


def test_fire_hooks_swallows_exceptions():
    @register_post_run_hook
    def bad_hook(run, result):
        raise RuntimeError("hook failure")

    # Should not raise
    _fire_post_run_hooks(_make_run(), _make_result())

    _POST_RUN_HOOKS.remove(bad_hook)


def test_fire_hooks_logs_exception_but_continues(caplog):
    called_after = []

    @register_post_run_hook
    def raises(run, result):
        raise ValueError("boom")

    @register_post_run_hook
    def after(run, result):
        called_after.append(True)

    with caplog.at_level(logging.WARNING, logger="app.agents.hooks"):
        _fire_post_run_hooks(_make_run(), _make_result())

    assert called_after  # second hook still ran
    assert any("boom" in r.message for r in caplog.records)

    _POST_RUN_HOOKS.remove(raises)
    _POST_RUN_HOOKS.remove(after)


# ---------------------------------------------------------------------------
# docs_sync_reminder hook
# ---------------------------------------------------------------------------

def test_docs_sync_reminder_logs_on_structural_file_mention(caplog):
    import app.agents.hooks  # ensure hook is registered via import

    run = _make_run(adapter_type="claude_code", run_id="run-abc")
    result = _make_result(output="I edited models.py to add a new field.")

    with caplog.at_level(logging.INFO, logger="app.agents.hooks"):
        _fire_post_run_hooks(run, result)

    assert any("models.py" in r.message for r in caplog.records)


def test_docs_sync_reminder_silent_when_no_structural_file(caplog):
    import app.agents.hooks  # noqa

    run = _make_run()
    result = _make_result(output="Everything looks good. No changes made.")

    with caplog.at_level(logging.INFO, logger="app.agents.hooks"):
        _fire_post_run_hooks(run, result)

    # No structural file names → no log message from docs_sync_reminder
    assert not any("review .agent/ docs" in r.message for r in caplog.records)


def test_docs_sync_reminder_silent_when_result_is_none():
    import app.agents.hooks  # noqa
    run = _make_run()
    # Should not raise
    _fire_post_run_hooks(run, None)


def test_docs_sync_reminder_detects_multiple_files(caplog):
    import app.agents.hooks  # noqa

    run = _make_run()
    result = _make_result(output="Updated runner.py and context_compiler.py")

    with caplog.at_level(logging.INFO, logger="app.agents.hooks"):
        _fire_post_run_hooks(run, result)

    relevant = [r for r in caplog.records if "review .agent/ docs" in r.message]
    assert len(relevant) == 1
    assert "runner.py" in relevant[0].message
    assert "context_compiler.py" in relevant[0].message
