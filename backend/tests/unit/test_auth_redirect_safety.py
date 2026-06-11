"""Unit tests for the post-login redirect safety guard."""

from app.auth.api import _safe_next_url


def test_relative_path_allowed():
    assert _safe_next_url("/invitations/tok123") == "/invitations/tok123"


def test_relative_path_with_query_allowed():
    assert _safe_next_url("/invitations/tok123?auto=1") == "/invitations/tok123?auto=1"


def test_root_path_allowed():
    assert _safe_next_url("/") == "/"


def test_absolute_url_rejected():
    assert _safe_next_url("https://evil.com") == ""


def test_absolute_http_rejected():
    assert _safe_next_url("http://evil.com/steal") == ""


def test_protocol_relative_rejected():
    assert _safe_next_url("//evil.com") == ""


def test_empty_string_rejected():
    assert _safe_next_url("") == ""


def test_no_leading_slash_rejected():
    assert _safe_next_url("evil.com/path") == ""


def test_javascript_scheme_rejected():
    assert _safe_next_url("javascript:alert(1)") == ""
