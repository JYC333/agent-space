"""CLI output parser registry."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ParsedRuntimeOutput:
    output_text: str
    output_json: dict[str, Any] | None = None
    estimated_usage: dict[str, Any] | None = None
    produced_artifact_paths: list[Any] = field(default_factory=list)
    error_code: str | None = None
    error_text: str | None = None
    redacted_stdout: str = ""
    redacted_stderr: str = ""


class CLIOutputParser:
    parser_type = "generic"

    def parse(self, *, stdout: str, stderr: str, exit_code: int | None) -> ParsedRuntimeOutput:
        redacted_stdout = _redact(stdout or "")
        redacted_stderr = _redact(stderr or "")
        err = redacted_stderr if exit_code not in (0, None) else None
        return ParsedRuntimeOutput(
            output_text=redacted_stdout,
            output_json=None,
            error_code="cli_adapter_nonzero_exit" if exit_code not in (0, None) else None,
            error_text=err,
            redacted_stdout=redacted_stdout,
            redacted_stderr=redacted_stderr,
        )


class PlainTextOutputParser(CLIOutputParser):
    parser_type = "plain_text"


_PARSERS: dict[str, CLIOutputParser] = {
    "generic": CLIOutputParser(),
    "plain_text": PlainTextOutputParser(),
}


def get_output_parser(parser_type: str) -> CLIOutputParser:
    return _PARSERS.get(parser_type, _PARSERS["generic"])


def _redact(text: str) -> str:
    # Keep this intentionally conservative. Prompts and secrets should never be
    # placed in stderr/stdout logs by the renderer, but trim huge payloads.
    if len(text) > 12000:
        return text[:12000] + "\n[TRUNCATED]"
    return text
