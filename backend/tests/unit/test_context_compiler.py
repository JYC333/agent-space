"""
Boundary unit tests for ContextCompiler — deterministic compile outcomes, no adapters.
"""
from pathlib import Path

from app.memory.context_compiler import ContextCompiler, TargetFormat, CompiledContext


def test_compile_empty_context_stable_shape(tmp_path):
    sandbox = tmp_path / "sb"
    out = ContextCompiler().compile(
        context={},
        target=TargetFormat.claude,
        task_goal="do the thing",
        sandbox_dir=str(sandbox),
        workspace_path=None,
        budget_chars=128_000,
    )
    assert isinstance(out, CompiledContext)
    assert out.task_prompt == "do the thing"
    assert out.target == TargetFormat.claude
    assert out.instruction_file_path is not None
    p = Path(out.instruction_file_path)
    assert p.name == "CLAUDE.md"
    assert p.exists()
    assert out.total_chars > 0
    assert isinstance(out.dropped_sections, list)


def test_compile_redacts_failing_security_scan(tmp_path):
    ctx = {
        "user_memory": [
            {
                "id": "m1",
                "title": "x",
                "content": "password=SuperSecretValueHere123",
            }
        ]
    }
    out = ContextCompiler().compile(
        context=ctx,
        target=TargetFormat.generic,
        task_goal="t",
        sandbox_dir=str(tmp_path / "sb2"),
        workspace_path=None,
    )
    assert out.scan_result is not None
    assert out.scan_result.passed is False
    text = Path(out.instruction_file_path).read_text(encoding="utf-8")
    assert "REDACTED" in text or "_redacted" in text


def test_compile_without_sandbox_dir_returns_no_instruction_path():
    out = ContextCompiler().compile(
        context={},
        target=TargetFormat.prompt,
        task_goal="solo",
        sandbox_dir=None,
    )
    assert out.instruction_file_path is None
    assert out.total_chars > 0
