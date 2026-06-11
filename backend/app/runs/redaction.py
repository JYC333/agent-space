"""Redaction helpers for RunStep metadata, errors, and runtime outputs (M3/M4).

Rules:
- API key patterns (sk-*, ANTHROPIC_API_KEY=..., etc.) are replaced with [REDACTED].
- Bearer/token header values are replaced with [REDACTED].
- Known test-secret markers are replaced with [REDACTED].
- Env-var style KEY=value pairs with sensitive key names are replaced.
- Nested dicts/lists are walked recursively.
- Non-string scalar values are passed through unchanged.

Step writes must never persist raw secrets.  Callers are responsible for
not passing raw environment dumps or full credential payloads.

M4 additions:
- ``redact_runtime_output`` sanitizes a full adapter output dict (stdout, stderr,
  adapter_log_json, adapter_metadata) before it is written to Run.output_json.
- ``redact_adapter_error`` is a named alias of ``redact_error`` for clarity at
  call sites that handle adapter-level errors.
- ``sanitize_runtime_metadata`` is an alias of ``redact_metadata`` for call
  sites that handle adapter metadata before RunStep persistence.
- ``redact_artifact_content`` sanitizes text generated from adapter output
  before it is persisted as an artifact.
"""

from __future__ import annotations

import re
from typing import Any

_SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9\-_]{8,}", re.IGNORECASE),
    re.compile(r"ANTHROPIC_API_KEY\s*=\s*\S+", re.IGNORECASE),
    re.compile(r"OPENAI_API_KEY\s*=\s*\S+", re.IGNORECASE),
    re.compile(r"API_KEY\s*=\s*\S+", re.IGNORECASE),
    re.compile(r"Bearer\s+[A-Za-z0-9\-_\.]+", re.IGNORECASE),
    re.compile(r"token\s*=\s*[A-Za-z0-9\-_\.]{8,}", re.IGNORECASE),
    re.compile(r"secret\s*=\s*\S+", re.IGNORECASE),
    re.compile(r"password\s*=\s*\S+", re.IGNORECASE),
    re.compile(r"TEST_SECRET_[A-Z0-9_]+\s*=\s*\S*", re.IGNORECASE),
    re.compile(r"TEST_SECRET_[A-Z0-9_]+", re.IGNORECASE),
]

_SENSITIVE_KEY_NAMES = frozenset({
    "api_key", "apikey", "api_token", "token", "secret", "password",
    "passwd", "credential", "credentials", "private_key", "access_token",
    "refresh_token", "auth_token", "bearer", "authorization",
    "anthropic_api_key", "openai_api_key",
})


def redact_string(value: str) -> str:
    """Replace known secret patterns in a string with [REDACTED]."""
    for pattern in _SECRET_PATTERNS:
        value = pattern.sub("[REDACTED]", value)
    return value


def redact_value(value: Any, *, key: str | None = None) -> Any:
    """Recursively sanitize a value, replacing secrets with [REDACTED].

    If ``key`` is a known sensitive key name the entire value is replaced.
    """
    if key and str(key).lower().strip("_- ") in _SENSITIVE_KEY_NAMES:
        return "[REDACTED]"

    if isinstance(value, str):
        return redact_string(value)

    if isinstance(value, dict):
        return {k: redact_value(v, key=k) for k, v in value.items()}

    if isinstance(value, list):
        return [redact_value(item) for item in value]

    return value


def redact_metadata(metadata: dict | None) -> dict:
    """Sanitize a metadata dict for safe storage in RunStep.metadata_json."""
    if not metadata:
        return {}
    result = redact_value(metadata)
    if not isinstance(result, dict):
        return {}
    return result


def redact_error(error: str | None) -> str | None:
    """Sanitize an error string for safe storage in RunStep.error_message."""
    if not error:
        return error
    return redact_string(str(error))


# ---------------------------------------------------------------------------
# M4 runtime-output redaction helpers
# ---------------------------------------------------------------------------

def redact_adapter_error(error: str | None) -> str | None:
    """Sanitize an adapter error string before persistence in RunStep or Run row.

    Named alias of ``redact_error`` for clarity at runtime adapter call sites.
    """
    return redact_error(error)


def sanitize_runtime_metadata(metadata: dict | None) -> dict:
    """Sanitize adapter metadata dict before persistence in RunStep.metadata_json.

    Named alias of ``redact_metadata`` for clarity at runtime adapter call sites.
    """
    return redact_metadata(metadata)


def redact_runtime_output(output: dict | None) -> dict | None:
    """Sanitize a full runtime adapter output dict before writing to Run.output_json.

    Applies recursive redaction so that any accidental secret exposure in
    stdout, stderr, adapter_log_json, or adapter_metadata is caught before
    the value is persisted to the database.
    """
    if not output:
        return output
    result = redact_value(output)
    if not isinstance(result, dict):
        return output
    return result


def redact_artifact_content(text: str | None) -> str | None:
    """Sanitize adapter-generated text before persisting as an artifact.

    Applies string-level redaction to catch any accidental secret that an
    adapter might include in its output text.
    """
    if not text:
        return text
    return redact_string(str(text))
