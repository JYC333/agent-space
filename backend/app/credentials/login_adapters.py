from __future__ import annotations

import re
from typing import Callable


LoginOutputParser = Callable[[str], dict]

_ANSI_RE = re.compile(rb'\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
_CODEX_DEVICE_AUTH_URL_RE = re.compile(r'https://auth\.openai\.com/codex/device\b')
_DEVICE_CODE_RE = re.compile(r'\b[A-Z0-9]{4,8}-[A-Z0-9]{4,8}\b')
_DEVICE_EXPIRES_RE = re.compile(r'expires in\s+(\d+)\s+minutes?', re.IGNORECASE)


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub(b"", text.encode("utf-8", errors="ignore")).decode("utf-8", errors="ignore")


def create_codex_output_parser() -> LoginOutputParser:
    last_device_auth_key = ""

    def parse(buffer: str) -> dict:
        nonlocal last_device_auth_key
        clean = _strip_ansi(buffer)
        url_match = _CODEX_DEVICE_AUTH_URL_RE.search(clean)
        code_match = _DEVICE_CODE_RE.search(clean)
        if not url_match or not code_match:
            return {}

        event = {
            "type": "device_auth",
            "url": url_match.group(0),
            "code": code_match.group(0),
        }
        expires_match = _DEVICE_EXPIRES_RE.search(clean)
        if expires_match:
            event["expires_in_minutes"] = int(expires_match.group(1))

        key = f"{event['url']}|{event['code']}"
        events = []
        if key != last_device_auth_key:
            last_device_auth_key = key
            events.append(event)
        return {
            "events": events,
            "suppress_default_code_prompt": True,
        }

    return parse


RUNTIME_LOGIN_CONFIG: dict[str, dict] = {
    "claude_code": {
        "method": "cli",
        "command": ["claude", "/login"],
        "home_subdir": ".claude",
        "label": "Claude Code",
        "hint_cli": "A browser URL will appear - open it to authorize your Claude.ai account.",
    },
    "codex_cli": {
        "method": "cli",
        "command": ["codex", "login", "--device-auth"],
        "home_subdir": ".codex",
        "label": "Codex CLI",
        "hint_cli": "Open the device-auth URL in your browser, then enter the one-time code shown here.",
        "create_output_parser": create_codex_output_parser,
    },
    "opencode": {
        "method": "cli",
        "command": ["opencode", "auth", "login"],
        "home_subdir": ".opencode",
        "label": "OpenCode",
        "hint_cli": "Follow the prompts to complete login.",
    },
    "gemini_cli": {
        "method": "cli",
        "command": ["gemini", "auth"],
        "home_subdir": ".gemini",
        "label": "Gemini CLI",
        "hint_cli": "A browser URL will appear - open it to authorize Gemini CLI.",
    },
}
