"""
Tests for ContextCompiler.

Verifies:
  - Claude target generates CLAUDE.md with expected content
  - Codex target generates AGENTS.md with expected content
  - Generated context does not include cross-space memory (compiler only renders
    what is in the context dict; cross-space isolation is enforced by ContextBuilder)
  - Generated file is written to sandbox dir, not the real workspace
  - No file is written when sandbox_dir is omitted
  - Compiler can be extended for new targets (generic / cursor)
  - Concise rendering: only title + content are included, never raw memory dumps
  - Optional sections (policy, tools, validation, constraints, output format)
  - Empty memory lists produce no section for that scope
"""

import pytest
from pathlib import Path

from app.memory.context_compiler import ContextCompiler, TargetFormat, CompiledContext


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _context(
    user_memory=None,
    workspace_memory=None,
    capability_memory=None,
    agent_memory=None,
    system_policy=None,
    recent_session_summary=None,
    relevant_episodes=None,
):
    return {
        "user_memory": user_memory or [],
        "workspace_memory": workspace_memory or [],
        "capability_memory": capability_memory or [],
        "agent_memory": agent_memory or [],
        "system_policy": system_policy or [],
        "recent_session_summary": recent_session_summary or [],
        "relevant_episodes": relevant_episodes or [],
    }


def _mem(title: str, content: str, **extra) -> dict:
    return {"title": title, "content": content, **extra}


# ---------------------------------------------------------------------------
# Target → filename mapping
# ---------------------------------------------------------------------------

def test_claude_target_generates_claude_md(tmp_path):
    compiled = ContextCompiler().compile(
        context=_context(),
        target=TargetFormat.claude,
        task_goal="Write unit tests",
        sandbox_dir=str(tmp_path),
    )
    assert compiled.instruction_file_path == str(tmp_path / "CLAUDE.md")
    assert (tmp_path / "CLAUDE.md").exists()


def test_codex_target_generates_agents_md(tmp_path):
    compiled = ContextCompiler().compile(
        context=_context(),
        target=TargetFormat.codex,
        task_goal="Refactor the auth module",
        sandbox_dir=str(tmp_path),
    )
    assert compiled.instruction_file_path == str(tmp_path / "AGENTS.md")
    assert (tmp_path / "AGENTS.md").exists()


def test_cursor_target_generates_cursorrules(tmp_path):
    compiled = ContextCompiler().compile(
        context=_context(),
        target=TargetFormat.cursor,
        task_goal="Add linting",
        sandbox_dir=str(tmp_path),
    )
    assert (tmp_path / ".cursorrules").exists()


def test_generic_target_generates_context_md(tmp_path):
    compiled = ContextCompiler().compile(
        context=_context(),
        target=TargetFormat.generic,
        task_goal="Task",
        sandbox_dir=str(tmp_path),
    )
    assert (tmp_path / "CONTEXT.md").exists()


# ---------------------------------------------------------------------------
# Content — task goal and memory sections
# ---------------------------------------------------------------------------

def test_task_goal_is_present_in_output(tmp_path):
    compiled = ContextCompiler().compile(
        context=_context(),
        target=TargetFormat.claude,
        task_goal="Add pagination to the API",
        sandbox_dir=str(tmp_path),
    )
    content = (tmp_path / "CLAUDE.md").read_text()
    assert "Add pagination to the API" in content


def test_user_memory_rendered(tmp_path):
    ctx = _context(user_memory=[_mem("Prefers Python", "User prefers Python over Go.")])
    content = ContextCompiler().compile(
        context=ctx, target=TargetFormat.claude, task_goal="Task", sandbox_dir=str(tmp_path),
    )
    text = (tmp_path / "CLAUDE.md").read_text()
    assert "Prefers Python" in text
    assert "User prefers Python over Go." in text


def test_workspace_memory_rendered(tmp_path):
    ctx = _context(workspace_memory=[_mem("Repo layout", "src/ contains all source files.")])
    ContextCompiler().compile(
        context=ctx, target=TargetFormat.claude, task_goal="Task", sandbox_dir=str(tmp_path),
    )
    text = (tmp_path / "CLAUDE.md").read_text()
    assert "Repo layout" in text
    assert "src/ contains all source files." in text


def test_system_policy_rendered(tmp_path):
    ctx = _context(system_policy=[_mem("", "Always be concise.")])
    ContextCompiler().compile(
        context=ctx, target=TargetFormat.claude, task_goal="Task", sandbox_dir=str(tmp_path),
    )
    text = (tmp_path / "CLAUDE.md").read_text()
    assert "Always be concise." in text


def test_empty_memories_produce_no_section(tmp_path):
    ctx = _context()  # all empty
    ContextCompiler().compile(
        context=_context(), target=TargetFormat.claude, task_goal="Task", sandbox_dir=str(tmp_path),
    )
    text = (tmp_path / "CLAUDE.md").read_text()
    assert "User Context" not in text
    assert "Project Context" not in text
    assert "System Policy" not in text


# ---------------------------------------------------------------------------
# Cross-space isolation (compiler renders only what is in the context dict)
# ---------------------------------------------------------------------------

def test_cross_space_memory_excluded_if_not_in_context(tmp_path):
    # ContextBuilder enforces the boundary; ContextCompiler renders only what it receives.
    # A context dict built for space_b must not contain space_a data.
    ctx = _context(user_memory=[_mem("space_b pref", "space_b content")])
    ContextCompiler().compile(
        context=ctx, target=TargetFormat.claude, task_goal="Task", sandbox_dir=str(tmp_path),
    )
    text = (tmp_path / "CLAUDE.md").read_text()
    assert "space_a" not in text
    assert "space_b content" in text


# ---------------------------------------------------------------------------
# File location — sandbox, not workspace
# ---------------------------------------------------------------------------

def test_file_written_to_sandbox_not_workspace(tmp_path):
    sandbox_dir = tmp_path / "sandbox"
    workspace_dir = tmp_path / "workspace"
    sandbox_dir.mkdir()
    workspace_dir.mkdir()

    ContextCompiler().compile(
        context=_context(user_memory=[_mem("T", "C")]),
        target=TargetFormat.claude,
        task_goal="Task",
        sandbox_dir=str(sandbox_dir),
    )

    assert (sandbox_dir / "CLAUDE.md").exists()
    assert not (workspace_dir / "CLAUDE.md").exists()


# ---------------------------------------------------------------------------
# No sandbox_dir → no file written
# ---------------------------------------------------------------------------

def test_no_file_written_without_sandbox_dir():
    compiled = ContextCompiler().compile(
        context=_context(user_memory=[_mem("T", "C")]),
        target=TargetFormat.claude,
        task_goal="Task",
        sandbox_dir=None,
    )
    assert compiled.instruction_file_path is None


# ---------------------------------------------------------------------------
# task_prompt is always the raw task goal (not JSON dump)
# ---------------------------------------------------------------------------

def test_task_prompt_is_task_goal_not_json_dump(tmp_path):
    goal = "Fix the login bug"
    compiled = ContextCompiler().compile(
        context=_context(user_memory=[_mem("Pref", "val")]),
        target=TargetFormat.claude,
        task_goal=goal,
        sandbox_dir=str(tmp_path),
    )
    assert compiled.task_prompt == goal
    assert "{" not in compiled.task_prompt  # no JSON in the prompt


# ---------------------------------------------------------------------------
# Optional sections
# ---------------------------------------------------------------------------

def test_allowed_tools_section(tmp_path):
    ContextCompiler().compile(
        context=_context(),
        target=TargetFormat.claude,
        task_goal="Task",
        sandbox_dir=str(tmp_path),
        allowed_tools=["Bash", "Read", "Edit"],
    )
    text = (tmp_path / "CLAUDE.md").read_text()
    assert "Allowed Tools" in text
    assert "- Bash" in text
    assert "- Read" in text


def test_sandbox_policy_section(tmp_path):
    ContextCompiler().compile(
        context=_context(),
        target=TargetFormat.claude,
        task_goal="Task",
        sandbox_dir=str(tmp_path),
        sandbox_policy={"risk_level": "medium", "max_run_time_seconds": 120, "can_delegate": False},
    )
    text = (tmp_path / "CLAUDE.md").read_text()
    assert "Sandbox Policy" in text
    assert "isolated sandbox" in text
    assert "120s" in text
    assert "delegation" in text.lower()


def test_validation_commands_section(tmp_path):
    ContextCompiler().compile(
        context=_context(),
        target=TargetFormat.claude,
        task_goal="Task",
        sandbox_dir=str(tmp_path),
        validation_commands=["pytest tests/", "mypy app/"],
    )
    text = (tmp_path / "CLAUDE.md").read_text()
    assert "Validation" in text
    assert "`pytest tests/`" in text
    assert "`mypy app/`" in text


def test_constraints_section(tmp_path):
    ContextCompiler().compile(
        context=_context(),
        target=TargetFormat.claude,
        task_goal="Task",
        sandbox_dir=str(tmp_path),
        constraints=["Do not modify the database schema", "Keep backward compatibility"],
    )
    text = (tmp_path / "CLAUDE.md").read_text()
    assert "Constraints" in text
    assert "Do not modify the database schema" in text


def test_output_format_section(tmp_path):
    ContextCompiler().compile(
        context=_context(),
        target=TargetFormat.claude,
        task_goal="Task",
        sandbox_dir=str(tmp_path),
        output_format="Return a JSON object with keys: result, confidence",
    )
    text = (tmp_path / "CLAUDE.md").read_text()
    assert "Expected Output" in text
    assert "Return a JSON object" in text


# ---------------------------------------------------------------------------
# Memory cap — compiler limits items per scope
# ---------------------------------------------------------------------------

def test_compiler_caps_memories_per_scope(tmp_path):
    many = [_mem(f"Title {i}", f"Content {i}") for i in range(20)]
    ContextCompiler().compile(
        context=_context(user_memory=many),
        target=TargetFormat.claude,
        task_goal="Task",
        sandbox_dir=str(tmp_path),
    )
    text = (tmp_path / "CLAUDE.md").read_text()
    # Only first 5 rendered; item 5 (index 5) should not appear
    assert "Content 4" in text   # index 4 — within limit
    assert "Content 5" not in text  # index 5 — beyond limit


# ---------------------------------------------------------------------------
# Session summaries
# ---------------------------------------------------------------------------

def test_session_summary_rendered(tmp_path):
    ctx = _context(recent_session_summary=[
        {"session_id": "s1", "summary": "User set up the project.", "created_at": "2026-01-01T00:00:00"},
    ])
    ContextCompiler().compile(
        context=ctx, target=TargetFormat.claude, task_goal="Task", sandbox_dir=str(tmp_path),
    )
    text = (tmp_path / "CLAUDE.md").read_text()
    assert "Session History" in text
    assert "User set up the project." in text


# ---------------------------------------------------------------------------
# CompiledContext return type
# ---------------------------------------------------------------------------

def test_compiled_context_has_expected_target(tmp_path):
    compiled = ContextCompiler().compile(
        context=_context(), target=TargetFormat.codex, task_goal="Task", sandbox_dir=str(tmp_path),
    )
    assert compiled.target == TargetFormat.codex


def test_empty_context_dict_does_not_raise(tmp_path):
    compiled = ContextCompiler().compile(
        context={}, target=TargetFormat.claude, task_goal="Do something", sandbox_dir=str(tmp_path),
    )
    text = (tmp_path / "CLAUDE.md").read_text()
    assert "Do something" in text
