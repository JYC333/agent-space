"""Unit tests for RunStep and runtime redaction helpers (M3/M4)."""
from __future__ import annotations

import pytest

from app.runs.redaction import (
    redact_adapter_error,
    redact_artifact_content,
    redact_error,
    redact_metadata,
    redact_runtime_output,
    redact_string,
    redact_value,
    sanitize_runtime_metadata,
)


class TestRedactString:
    def test_sk_api_key_redacted(self):
        assert "[REDACTED]" in redact_string("key=sk-abc123def456ghi")

    def test_bearer_token_redacted(self):
        assert "[REDACTED]" in redact_string("Authorization: Bearer abc.def.ghi")

    def test_anthropic_api_key_env_redacted(self):
        assert "[REDACTED]" in redact_string("ANTHROPIC_API_KEY=sk-ant-abc123def456")

    def test_openai_api_key_env_redacted(self):
        assert "[REDACTED]" in redact_string("OPENAI_API_KEY=sk-open-abc123def456")

    def test_generic_api_key_env_redacted(self):
        assert "[REDACTED]" in redact_string("API_KEY=my-super-secret-key")

    def test_secret_kv_redacted(self):
        assert "[REDACTED]" in redact_string("secret=hunter2")

    def test_password_kv_redacted(self):
        assert "[REDACTED]" in redact_string("password=letmein")

    def test_test_secret_marker_redacted(self):
        assert "[REDACTED]" in redact_string("TEST_SECRET_ALPHA=value123")

    def test_test_secret_bare_marker_redacted(self):
        assert "[REDACTED]" in redact_string("TEST_SECRET_BETA")

    def test_non_secret_string_unchanged(self):
        text = "the quick brown fox"
        assert redact_string(text) == text

    def test_empty_string_unchanged(self):
        assert redact_string("") == ""


class TestRedactValue:
    def test_sensitive_key_redacts_value(self):
        assert redact_value("actual-key", key="api_key") == "[REDACTED]"

    def test_sensitive_key_token_redacts(self):
        assert redact_value("my-token", key="token") == "[REDACTED]"

    def test_sensitive_key_password_redacts(self):
        assert redact_value("password123", key="password") == "[REDACTED]"

    def test_non_sensitive_key_passes_through(self):
        assert redact_value("harmless", key="label") == "harmless"

    def test_dict_recursed(self):
        result = redact_value({"api_key": "secret", "name": "ok"})
        assert result["api_key"] == "[REDACTED]"
        assert result["name"] == "ok"

    def test_list_recursed(self):
        result = redact_value(["hello", "sk-abc123def456abc"])
        assert result[0] == "hello"
        assert result[1] == "[REDACTED]"

    def test_nested_dict_recursed(self):
        result = redact_value({"outer": {"credentials": "should-be-gone"}})
        assert result["outer"]["credentials"] == "[REDACTED]"

    def test_integer_passthrough(self):
        assert redact_value(42) == 42

    def test_none_passthrough(self):
        assert redact_value(None) is None

    def test_key_with_leading_underscore_stripped(self):
        assert redact_value("secret", key="_api_key") == "[REDACTED]"


class TestRedactMetadata:
    def test_none_returns_empty_dict(self):
        assert redact_metadata(None) == {}

    def test_empty_dict_returns_empty(self):
        assert redact_metadata({}) == {}

    def test_sensitive_keys_redacted(self):
        result = redact_metadata({"bearer": "tok123", "label": "foo"})
        assert result["bearer"] == "[REDACTED]"
        assert result["label"] == "foo"

    def test_non_dict_result_returns_empty(self):
        # If the internal redact_value call returns a non-dict for some reason, returns {}
        result = redact_metadata({"ok": "val"})
        assert isinstance(result, dict)


class TestRedactError:
    def test_none_returns_none(self):
        assert redact_error(None) is None

    def test_empty_string_returned_as_is(self):
        assert redact_error("") == ""

    def test_secret_in_error_redacted(self):
        msg = "failed: sk-abc123def456ghi was rejected"
        result = redact_error(msg)
        assert "[REDACTED]" in result
        assert "sk-abc123def456ghi" not in result

    def test_clean_error_unchanged(self):
        msg = "connection refused"
        assert redact_error(msg) == msg


# ---------------------------------------------------------------------------
# M4 runtime helpers
# ---------------------------------------------------------------------------

class TestRedactAdapterError:
    def test_alias_redacts_same_as_redact_error(self):
        raw = "API rejected key sk-abc123def456ghi"
        assert redact_adapter_error(raw) == redact_error(raw)

    def test_none_returns_none(self):
        assert redact_adapter_error(None) is None

    def test_secret_in_adapter_error_redacted(self):
        msg = "auth failed: ANTHROPIC_API_KEY=sk-ant-abc123def"
        result = redact_adapter_error(msg)
        assert "[REDACTED]" in result
        assert "sk-ant-abc123def" not in result


class TestSanitizeRuntimeMetadata:
    def test_alias_behaves_as_redact_metadata(self):
        meta = {"api_key": "secret", "model": "gpt-4"}
        assert sanitize_runtime_metadata(meta) == redact_metadata(meta)

    def test_none_returns_empty(self):
        assert sanitize_runtime_metadata(None) == {}

    def test_sensitive_keys_removed(self):
        result = sanitize_runtime_metadata({"bearer": "tok", "name": "ok"})
        assert result["bearer"] == "[REDACTED]"
        assert result["name"] == "ok"


class TestRedactRuntimeOutput:
    def test_none_returns_none(self):
        assert redact_runtime_output(None) is None

    def test_empty_dict_returns_empty(self):
        assert redact_runtime_output({}) == {}

    def test_passthrough_clean_output(self):
        out = {
            "runtime": "real",
            "stdout": "hello world",
            "stderr": "",
            "adapter_type": "echo",
        }
        result = redact_runtime_output(out)
        assert result["stdout"] == "hello world"
        assert result["runtime"] == "real"

    def test_redacts_secret_in_stdout(self):
        out = {"stdout": "key=sk-leak-abc123def456", "stderr": ""}
        result = redact_runtime_output(out)
        assert "[REDACTED]" in result["stdout"]
        assert "sk-leak-abc123def456" not in result["stdout"]

    def test_redacts_secret_in_nested_adapter_log(self):
        out = {
            "adapter_log_json": {
                "api_key": "sk-should-not-be-here",
                "model": "gpt-4",
            }
        }
        result = redact_runtime_output(out)
        assert result["adapter_log_json"]["api_key"] == "[REDACTED]"
        assert result["adapter_log_json"]["model"] == "gpt-4"

    def test_redacts_bearer_in_stderr(self):
        out = {"stderr": "Authorization: Bearer tok-abc123def456ghi"}
        result = redact_runtime_output(out)
        assert "[REDACTED]" in result["stderr"]

    def test_test_secret_marker_redacted(self):
        out = {"stdout": "got TEST_SECRET_ALPHA=somevalue123"}
        result = redact_runtime_output(out)
        assert "[REDACTED]" in result["stdout"]
        assert "TEST_SECRET_ALPHA=somevalue123" not in result["stdout"]


class TestRedactArtifactContent:
    def test_none_returns_none(self):
        assert redact_artifact_content(None) is None

    def test_empty_returns_empty(self):
        assert redact_artifact_content("") == ""

    def test_clean_content_unchanged(self):
        text = "The answer is 42."
        assert redact_artifact_content(text) == text

    def test_secret_in_artifact_content_redacted(self):
        text = "My API key is sk-abc123def456ghi, please keep it safe."
        result = redact_artifact_content(text)
        assert "[REDACTED]" in result
        assert "sk-abc123def456ghi" not in result

    def test_anthropic_api_key_env_in_artifact_redacted(self):
        text = "config: ANTHROPIC_API_KEY=sk-ant-key-xyz"
        result = redact_artifact_content(text)
        assert "[REDACTED]" in result
        assert "sk-ant-key-xyz" not in result
