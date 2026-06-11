"""Safe argv renderer for local CLI runtime adapters."""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .specs import RuntimeAdapterSpec

_VAR_RE = re.compile(r"{([a-zA-Z_][a-zA-Z0-9_]*)}")
_SECRET_KEYS = {"prompt", "context", "api_key", "token", "secret", "password"}


class CommandRenderError(ValueError):
    def __init__(self, error_code: str, message: str):
        self.error_code = error_code
        self.message = message
        super().__init__(message)


@dataclass(frozen=True)
class RenderedCommand:
    argv: list[str]
    redacted_argv: list[str]
    stdin: str | None = None
    redacted_stdin: str | None = None
    env: dict[str, str] = field(default_factory=dict)
    permission_bypass_used: bool = False


def _validate_executable_override(spec: RuntimeAdapterSpec, executable_path: str) -> str:
    if "\x00" in executable_path:
        raise CommandRenderError("invalid_executable_path", "executable_path contains a null byte")
    if not spec.executable.allow_path_override:
        raise CommandRenderError("executable_override_not_allowed", "executable_path override is not allowed")
    path = Path(executable_path)
    if not path.is_absolute():
        raise CommandRenderError("executable_override_not_absolute", "executable_path override must be an absolute path")
    try:
        path = path.resolve(strict=True)
    except FileNotFoundError as exc:
        raise CommandRenderError("executable_not_found", "executable_path override does not exist") from exc
    except Exception as exc:
        raise CommandRenderError("invalid_executable_path", "executable_path could not be resolved") from exc
    if not os.access(path, os.X_OK):
        raise CommandRenderError("executable_not_executable", "executable_path is not executable")
    return str(path)


def resolve_executable_for_execution(spec: RuntimeAdapterSpec, executable_path: str | None = None) -> str:
    if executable_path:
        return _validate_executable_override(spec, executable_path)
    if not spec.executable.command:
        raise CommandRenderError("executable_missing", "spec does not declare an executable")
    resolved = shutil.which(spec.executable.command)
    return resolved or spec.executable.command


def resolve_executable_for_detection(spec: RuntimeAdapterSpec, executable_path: str | None = None) -> str:
    if executable_path:
        return _validate_executable_override(spec, executable_path)
    if not spec.executable.command:
        raise CommandRenderError("executable_missing", "spec does not declare an executable")
    resolved = shutil.which(spec.executable.command)
    if not resolved:
        raise CommandRenderError("executable_not_found", f"'{spec.executable.command}' not found in PATH")
    return resolved


def render_command(
    *,
    spec: RuntimeAdapterSpec,
    prompt: str,
    mode: str = "headless",
    model: str | None = None,
    permission_bypass: bool = False,
    executable_path: str | None = None,
) -> RenderedCommand:
    executable = resolve_executable_for_execution(spec, executable_path)
    template = spec.invocation.headless_command_template
    if mode == "interactive" and spec.invocation.interactive_command_template:
        template = spec.invocation.interactive_command_template
    values: dict[str, Any] = {"executable": executable, "prompt": prompt}
    argv = _render_template(template, values)
    redacted = _render_template(template, {**values, "prompt": "[REDACTED_PROMPT]"})

    extra_args: list[str] = []
    if model:
        if not spec.model.supports_model_override:
            raise CommandRenderError(
                "model_override_not_supported",
                f"adapter_type '{spec.adapter_type}' does not support model override",
            )
        extra_args.extend(_render_template(spec.model.model_arg_template or [], {"model": model}))

    if permission_bypass:
        if not spec.permissions.supports_permission_bypass:
            raise CommandRenderError(
                "permission_bypass_not_supported",
                f"adapter_type '{spec.adapter_type}' does not support permission bypass",
            )
        extra_args.extend(spec.permissions.permission_bypass_arg_template or [])

    if extra_args:
        insert_at = next((idx for idx, arg in enumerate(argv) if arg == prompt), len(argv))
        argv[insert_at:insert_at] = extra_args
        redacted_insert_at = next((idx for idx, arg in enumerate(redacted) if arg == "[REDACTED_PROMPT]"), len(redacted))
        redacted[redacted_insert_at:redacted_insert_at] = extra_args

    stdin = prompt if spec.invocation.argument_rendering_strategy == "stdin" else None
    redacted_stdin = "[REDACTED_PROMPT]" if stdin is not None else None
    if stdin is not None:
        argv = [arg for arg in argv if arg != prompt]
        redacted = [arg for arg in redacted if arg != "[REDACTED_PROMPT]"]
    bypass_args = spec.permissions.permission_bypass_arg_template or []
    permission_bypass_used = bool(permission_bypass and bypass_args and all(arg in argv for arg in bypass_args))
    return RenderedCommand(
        argv=argv,
        redacted_argv=redacted,
        stdin=stdin,
        redacted_stdin=redacted,
        permission_bypass_used=permission_bypass_used,
    )


def _render_template(template: list[str], values: dict[str, Any]) -> list[str]:
    rendered: list[str] = []
    for part in template:
        names = _VAR_RE.findall(part)
        for name in names:
            if name not in values:
                raise CommandRenderError("unknown_template_variable", f"unknown command template variable: {name}")
        out = part
        for name in names:
            out = out.replace("{" + name + "}", str(values[name]))
        rendered.append(out)
    return rendered


def redact_command_log(argv: list[str]) -> list[str]:
    redacted: list[str] = []
    for item in argv:
        lowered = item.lower()
        if any(key in lowered for key in _SECRET_KEYS):
            redacted.append("[REDACTED]")
        else:
            redacted.append(item)
    return redacted
