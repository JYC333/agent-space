from __future__ import annotations

from typing import Any


def execute(context: dict[str, Any]) -> dict[str, Any]:
    echoed = dict(context.get("input") or {})
    return {
        "status": "succeeded",
        "output": {
            "echoed_input": echoed,
            "run_id": context.get("run_id"),
            "capability_id": context.get("capability_id"),
        },
        "artifacts": [
            {
                "artifact_type": "agent.echo.result.v1",
                "title": "Echo Result",
                "content": "Echo capability executed.",
                "metadata_json": {"echoed_input": echoed},
            }
        ],
        "activities": [
            {
                "activity_type": "capability_event",
                "title": "Echo capability executed",
                "payload_json": {"capability_id": context.get("capability_id")},
            }
        ],
    }
