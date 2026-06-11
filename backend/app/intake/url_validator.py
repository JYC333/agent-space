"""Safe URL validation and SSRF-aware HTTP fetch for intake connectors."""
from __future__ import annotations

import ipaddress
import re
import socket
import urllib.error
import urllib.request
from urllib.parse import urljoin, urlparse

_ALLOWED_SCHEMES = {"http", "https"}
_ALLOWED_PORTS: frozenset[int | None] = frozenset({None, 80, 443})
_MAX_REDIRECTS = 5

_LOCAL_HOSTNAMES = re.compile(
    r"^(localhost|.*\.local|.*\.internal|.*\.intranet|.*\.corp)$",
    re.IGNORECASE,
)


class InvalidIntakeURL(Exception):
    pass


class IntakeResponseTooLarge(Exception):
    error_code = "response_too_large"


def _is_ip_unsafe(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_unspecified
        or addr.is_reserved
    )


def _check_ip_literal(hostname: str) -> None:
    try:
        addr = ipaddress.ip_address(hostname)
    except ValueError:
        return
    if _is_ip_unsafe(addr):
        raise InvalidIntakeURL(f"Private/local/reserved network address not allowed: {hostname}")


def _resolve_host(hostname: str) -> None:
    try:
        results = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise InvalidIntakeURL(f"DNS resolution failed for {hostname!r}: {exc}") from exc
    if not results:
        raise InvalidIntakeURL(f"DNS returned no addresses for {hostname!r}")
    for _family, _type, _proto, _canonname, sockaddr in results:
        try:
            addr = ipaddress.ip_address(sockaddr[0])
        except ValueError:
            continue
        if _is_ip_unsafe(addr):
            raise InvalidIntakeURL(
                f"Resolved IP {sockaddr[0]} for {hostname!r} is in a restricted range"
            )


def _validate_url_static(url: str) -> tuple[str, str]:
    if not url or not isinstance(url, str):
        raise InvalidIntakeURL("URL must be a non-empty string")

    url = url.strip()
    try:
        parsed = urlparse(url)
    except Exception as exc:
        raise InvalidIntakeURL("Malformed URL") from exc

    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise InvalidIntakeURL(
            f"Unsupported protocol {parsed.scheme!r}: only http and https are allowed"
        )

    hostname = parsed.hostname or ""
    if not hostname:
        raise InvalidIntakeURL("URL must include a hostname")
    if _LOCAL_HOSTNAMES.match(hostname):
        raise InvalidIntakeURL(f"Local/private hostname not allowed: {hostname}")

    _check_ip_literal(hostname)

    port = parsed.port
    if port not in _ALLOWED_PORTS:
        raise InvalidIntakeURL(f"Port {port} is not allowed; only ports 80 and 443 are permitted")

    return url, hostname


def validate_intake_url(url: str) -> str:
    validated, _ = _validate_url_static(url)
    return validated


def _validate_and_resolve(url: str) -> str:
    validated, hostname = _validate_url_static(url)
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        _resolve_host(hostname)
    return validated


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    max_redirections = _MAX_REDIRECTS

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        newurl = urljoin(req.full_url, newurl)
        try:
            _validate_and_resolve(newurl)
        except InvalidIntakeURL as exc:
            raise urllib.error.URLError(f"Redirect to unsafe URL blocked: {exc}") from exc
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def safe_http_get(
    url: str,
    *,
    timeout: int = 15,
    max_bytes: int = 10 * 1024 * 1024,
    extra_headers: dict[str, str] | None = None,
) -> tuple[bytes, str]:
    _validate_and_resolve(url)

    opener = urllib.request.build_opener(_SafeRedirectHandler)
    headers: dict[str, str] = {"User-Agent": "agent-space-intake/1.0"}
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(url, headers=headers)

    with opener.open(req, timeout=timeout) as resp:
        content_type: str = resp.headers.get("Content-Type", "")
        data: bytes = resp.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise IntakeResponseTooLarge(f"Response body exceeded {max_bytes} bytes")
    return data, content_type


def extract_domain(url: str | None) -> str | None:
    if not url:
        return None
    try:
        return urlparse(url).hostname or None
    except Exception:
        return None
