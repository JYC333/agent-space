from __future__ import annotations

from typing import Any


def execute(context: dict[str, Any]) -> dict[str, Any]:
    payload = dict(context.get("input") or {})
    messages = payload.get("messages") or []
    if not isinstance(messages, list):
        messages = []

    return {
        "status": "succeeded",
        "output": {
            "message_count": len(messages),
            "proposal_count": 0,
            "mode": payload.get("mode") or "pattern",
        },
        "artifacts": [
            {
                "artifact_type": "memory.reflection.v1",
                "title": "Memory Reflection",
                "content": "Memory reflection completed. No proposals were emitted by the capability skeleton.",
                "metadata_json": {
                    "message_count": len(messages),
                    "proposal_count": 0,
                },
            }
        ],
        "activities": [
            {
                "activity_type": "capability_event",
                "title": "Memory reflection executed",
                "payload_json": {
                    "capability_id": context.get("capability_id"),
                    "message_count": len(messages),
                },
            }
        ],
    }
