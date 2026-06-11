from __future__ import annotations

import socket
import urllib.error
import urllib.request

import pytest

from app.intake import url_validator as uv
from app.intake.service import _safe_error


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/resource",
        "http://127.0.0.1/resource",
        "http://10.0.0.1/resource",
        "http://172.16.0.2/resource",
        "http://192.168.1.2/resource",
        "http://[::1]/resource",
        "http://[fe80::1]/resource",
        "https://example.local/resource",
        "https://example.internal/resource",
        "https://example.intranet/resource",
        "https://example.corp/resource",
        "ftp://example.com/resource",
        "file:///tmp/private",
        "https://example.com:444/resource",
    ],
)
def test_validate_intake_url_rejects_unsafe_static_urls(url):
    with pytest.raises(uv.InvalidIntakeURL):
        uv.validate_intake_url(url)


def test_safe_http_get_rejects_dns_resolution_to_private_ip(monkeypatch):
    def fake_getaddrinfo(host, port, proto=0):
        return [(socket.AF_INET, socket.SOCK_STREAM, proto, "", ("10.1.2.3", 0))]

    monkeypatch.setattr(uv.socket, "getaddrinfo", fake_getaddrinfo)

    with pytest.raises(uv.InvalidIntakeURL, match="restricted range"):
        uv.safe_http_get("https://example.com/resource")


def test_safe_redirect_handler_rejects_redirect_to_private_url():
    handler = uv._SafeRedirectHandler()
    req = urllib.request.Request("https://example.com/start")

    with pytest.raises(urllib.error.URLError):
        handler.redirect_request(req, None, 302, "Found", {}, "http://127.0.0.1/admin")


def test_safe_http_get_rejects_oversized_response(monkeypatch):
    class FakeResponse:
        headers = {"Content-Type": "text/plain"}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, _size):
            return b"abcdef"

    class FakeOpener:
        def open(self, _req, timeout):
            return FakeResponse()

    monkeypatch.setattr(uv, "_validate_and_resolve", lambda url: url)
    monkeypatch.setattr(uv.urllib.request, "build_opener", lambda *_args, **_kwargs: FakeOpener())

    with pytest.raises(uv.IntakeResponseTooLarge):
        uv.safe_http_get("https://example.com/resource", max_bytes=5)


def test_error_messages_are_sanitized_and_bounded():
    msg = _safe_error(Exception("<script>secret</script>" + ("x" * 1000)))
    assert "<script>" not in msg
    assert "</script>" not in msg
    assert len(msg) <= 256
