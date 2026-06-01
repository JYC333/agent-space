from __future__ import annotations
"""
Security scanner for context compilation.

Runs before any content is included in a compiled context package:
  - Secret/credential pattern detection
  - Prompt injection pattern detection
  - Sensitive path blocking
  - Binary file rejection

All scans are conservative false-positive friendly — when in doubt, flag.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class SecurityScanResult:
    passed: bool
    # Matched pattern labels, e.g. ["api_key", "aws_access_key"]
    secrets_found: list[str] = field(default_factory=list)
    # Matched injection fragments (truncated to 80 chars)
    injection_risks: list[str] = field(default_factory=list)
    # Paths that matched the sensitive path list
    blocked_paths: list[str] = field(default_factory=list)

    def summary(self) -> str:
        parts: list[str] = []
        if self.secrets_found:
            parts.append(f"secrets:{','.join(self.secrets_found)}")
        if self.injection_risks:
            parts.append(f"injection:{len(self.injection_risks)}_pattern(s)")
        if self.blocked_paths:
            parts.append(f"blocked_path:{','.join(self.blocked_paths)}")
        return "; ".join(parts) if parts else "clean"


# ---------------------------------------------------------------------------
# Secret patterns
# ---------------------------------------------------------------------------

_SECRET_PATTERNS: list[tuple[re.Pattern, str]] = [
    # Generic API key / token assignments
    (re.compile(
        r'(?i)(api[_-]?key|apikey|api_secret|access[_-]?token|secret[_-]?key|bearer)\s*[:=]\s*["\']?[A-Za-z0-9\-_.~+/]{20,}["\']?'
    ), "api_key"),
    # AWS access key ID
    (re.compile(r'AKIA[0-9A-Z]{16}'), "aws_access_key"),
    # AWS secret
    (re.compile(
        r'(?i)aws[_-]?secret[_-]?access[_-]?key\s*[:=]\s*[A-Za-z0-9/+]{40}'
    ), "aws_secret"),
    # Generic password assignment
    (re.compile(
        r'(?i)(password|passwd|pwd)\s*[:=]\s*["\']?[^\s"\']{8,}["\']?'
    ), "password"),
    # PEM private key header
    (re.compile(r'-----BEGIN\s+(RSA\s+|EC\s+|OPENSSH\s+)?PRIVATE KEY-----'), "private_key"),
    # GitHub PAT / fine-grained
    (re.compile(r'gh[pousr]_[A-Za-z0-9]{36,}'), "github_token"),
    # OpenAI key
    (re.compile(r'sk-[A-Za-z0-9]{48,}'), "openai_key"),
    # Anthropic key
    (re.compile(r'sk-ant-[A-Za-z0-9\-]{80,}'), "anthropic_key"),
    # Slack token
    (re.compile(r'xox[baprs]-[0-9A-Za-z\-]{10,}'), "slack_token"),
    # Generic hex secret (32+ hex chars after assignment keyword)
    (re.compile(
        r'(?i)(secret|token|key)\s*[:=]\s*["\']?[0-9a-f]{32,}["\']?'
    ), "hex_secret"),
    # Database DSN with embedded credentials
    (re.compile(
        r'(?i)(postgres|mysql|mongodb|redis)://[^:@\s]+:[^@\s]+@'
    ), "db_dsn_credentials"),
]


# ---------------------------------------------------------------------------
# Prompt injection patterns
# ---------------------------------------------------------------------------

_INJECTION_PATTERNS: list[re.Pattern] = [
    re.compile(r'(?i)ignore\s+(previous|all|above|prior|the\s+above)\s+(instructions?|prompts?|context|rules?)'),
    re.compile(r'(?i)(you\s+are\s+now|from\s+now\s+on\s+you\s+are|act\s+as|pretend\s+(to\s+be|you\s+are))\s'),
    re.compile(r'(?i)(forget|disregard|override|bypass)\s+(your|all|previous|the\s+above)\s+(instructions?|rules?|guidelines?|constraints?)'),
    re.compile(r'(?i)system\s*:\s*(you\s+(are|must|should)|i\s+am\s+your)'),
    # Model-specific control tokens
    re.compile(r'<\|im_start\||<\|im_end\|>|\[INST\]|\[/INST\]|<<SYS>>|<</SYS>>'),
    re.compile(r'(?i)###\s*(human|assistant|system|instruction)\s*:'),
    # Jailbreak phrases
    re.compile(r'(?i)(developer\s+mode|jailbreak\s+mode|DAN\s+mode|do\s+anything\s+now)'),
    # Indirect injection via "please repeat" style
    re.compile(r'(?i)print\s+(your\s+)?(system\s+prompt|instructions?|original\s+prompt)'),
]


# ---------------------------------------------------------------------------
# Sensitive path patterns
# ---------------------------------------------------------------------------

_SENSITIVE_PATH_PATTERNS: list[re.Pattern] = [
    re.compile(r'/(etc/passwd|etc/shadow|etc/sudoers|etc/hosts)'),
    re.compile(r'\.env(\.\w+)?$'),
    re.compile(r'\.(pem|key|p12|pfx|jks|pkcs12)$', re.IGNORECASE),
    re.compile(r'id_(rsa|ecdsa|ed25519|dsa)(\.pub)?$'),
    re.compile(r'/(\.ssh|\.gnupg)/'),
    re.compile(r'/(secrets?|credentials?|tokens?)\.(json|yaml|yml|env|toml)$', re.IGNORECASE),
    re.compile(r'/\.netrc$'),
    re.compile(r'/(aws|gcp|azure)/credentials$', re.IGNORECASE),
    re.compile(r'/\.aws/(credentials|config)$'),
    re.compile(r'/(keystore|truststore)\.(jks|p12)$', re.IGNORECASE),
]

# Binary file extensions that should be rejected unless explicitly supported
_BINARY_EXTENSIONS: frozenset[str] = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp",
    ".mp3", ".mp4", ".wav", ".avi", ".mov", ".mkv",
    ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar",
    ".exe", ".dll", ".so", ".dylib", ".bin",
    ".pdf", ".docx", ".xlsx", ".pptx",
    ".db",
    ".pyc", ".pyo", ".class",
    ".wasm",
})


# ---------------------------------------------------------------------------
# Public scanning functions
# ---------------------------------------------------------------------------

def scan_content(text: str, source_label: str = "") -> SecurityScanResult:
    """
    Scan arbitrary text for secrets and prompt injection.
    source_label is used only for reporting; does not affect scan logic.
    """
    secrets: list[str] = []
    for pattern, name in _SECRET_PATTERNS:
        if pattern.search(text):
            secrets.append(name)

    injections: list[str] = []
    for pattern in _INJECTION_PATTERNS:
        m = pattern.search(text)
        if m:
            injections.append(m.group(0)[:80])

    passed = not secrets and not injections
    return SecurityScanResult(
        passed=passed,
        secrets_found=secrets,
        injection_risks=injections,
    )


def scan_path(path: str) -> bool:
    """Return True if the path matches a sensitive path pattern (should be blocked)."""
    for pattern in _SENSITIVE_PATH_PATTERNS:
        if pattern.search(path):
            return True
    return False


def is_binary_path(path: str) -> bool:
    """Return True if the file extension indicates binary content."""
    return Path(path).suffix.lower() in _BINARY_EXTENSIONS


def scan_attachment(path: str, content: str | None = None) -> SecurityScanResult:
    """
    Full scan for a file attachment: path policy + optional content scan.
    Binary files are rejected regardless of content.
    """
    blocked: list[str] = []

    if is_binary_path(path):
        return SecurityScanResult(
            passed=False,
            blocked_paths=[path],
            secrets_found=["binary_file"],
        )

    if scan_path(path):
        blocked.append(path)

    content_result = scan_content(content or "", source_label=path)

    return SecurityScanResult(
        passed=not blocked and content_result.passed,
        secrets_found=content_result.secrets_found,
        injection_risks=content_result.injection_risks,
        blocked_paths=blocked,
    )
