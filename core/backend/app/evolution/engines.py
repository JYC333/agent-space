from __future__ import annotations

"""LLM-backed evolution engine.

Engines produce structured output only. They never mutate prompts, capabilities,
memory, policy, files, or code.
"""

import json
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from ..providers.invocation import complete_text


@dataclass(frozen=True)
class EvolutionEngineOutput:
    engine: str
    report: dict
    prompt_revision: dict
    metadata: dict = field(default_factory=dict)


class LLMPromptEvolutionEngine:
    name = "llm_prompt_review"

    def __init__(
        self,
        db: Session,
        *,
        provider_id: str,
        model: str | None = None,
        api_key: str | None = None,
    ) -> None:
        self._db = db
        self._provider_id = provider_id
        self._model = model
        self._api_key = api_key

    def supports(self, target_type: str) -> bool:
        return target_type == "prompt"

    def run(self, context: dict) -> EvolutionEngineOutput:
        target = context.get("target") or {}
        capability = context.get("capability") or {}
        capability_key = target.get("capability_key")
        response = complete_text(
            self._db,
            provider_id=self._provider_id,
            model=self._model,
            api_key=self._api_key,
            system=_system_prompt(),
            user=_user_prompt(context),
            max_tokens=8000,
        )
        raw = _parse_json_object(response.text)
        report = raw.get("report")
        revision = raw.get("prompt_revision")
        if not isinstance(report, dict):
            raise ValueError("LLM evolution response missing report object")
        if not isinstance(revision, dict):
            raise ValueError("LLM evolution response missing prompt_revision object")

        revision["revision_format"] = revision.get("revision_format") or "prompt_revision.v1"
        revision["capability_key"] = revision.get("capability_key") or capability_key
        prompt = revision.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("LLM evolution prompt_revision.prompt must be a non-empty string")
        revision["prompt"] = prompt.strip()
        change_summary = revision.get("change_summary")
        if change_summary is None:
            revision["change_summary"] = []
        elif not isinstance(change_summary, list):
            raise ValueError("LLM evolution prompt_revision.change_summary must be a list")
        evidence_signal_ids = revision.get("evidence_signal_ids")
        if evidence_signal_ids is None:
            revision["evidence_signal_ids"] = []
        elif not isinstance(evidence_signal_ids, list):
            raise ValueError("LLM evolution prompt_revision.evidence_signal_ids must be a list")

        report.setdefault("engine", self.name)
        report.setdefault("target_id", target.get("id"))
        report.setdefault("target_type", target.get("target_type"))
        report.setdefault("capability_key", capability_key)
        report.setdefault("revision_format", revision["revision_format"])
        report.setdefault("model", response.model)
        return EvolutionEngineOutput(
            engine=self.name,
            report=report,
            prompt_revision=revision,
            metadata={
                "provider_id": self._provider_id,
                "model": response.model,
                "usage": response.usage,
                "capability_found": capability.get("found"),
            },
        )


def get_engine(
    name: str,
    db: Session,
    *,
    provider_id: str,
    model: str | None = None,
    api_key: str | None = None,
) -> LLMPromptEvolutionEngine:
    if name != "llm_prompt_review":
        raise ValueError(f"Unknown evolution engine {name!r}")
    return LLMPromptEvolutionEngine(db, provider_id=provider_id, model=model, api_key=api_key)


def _system_prompt() -> str:
    return (
        "You are an Agent Space evolution reviewer. Analyze the current target prompt, "
        "recent typed evidence signals, constraints, validation goals, and validation results. Propose a "
        "minimal prompt revision that addresses the evidence without directly "
        "mutating any system state.\n\n"
        "Return ONLY a JSON object with this shape:\n"
        "{\n"
        '  "report": {\n'
        '    "summary": "short rationale",\n'
        '    "signal_analysis": ["evidence-driven observations"],\n'
        '    "risk_notes": ["risks or review concerns"],\n'
        '    "expected_improvement": "what should improve"\n'
        "  },\n"
        '  "prompt_revision": {\n'
        '    "revision_format": "prompt_revision.v1",\n'
        '    "capability_key": "target capability key",\n'
        '    "prompt": "complete revised prompt text",\n'
        '    "change_summary": ["specific changes made"],\n'
        '    "evidence_signal_ids": ["signal ids used"]\n'
        "  }\n"
        "}\n\n"
        "Rules:\n"
        "- prompt must contain the complete revised prompt text, not a diff or operation list.\n"
        "- Keep the revision minimal and grounded in the provided signals.\n"
        "- Preserve prompt sections that are unrelated to the evidence.\n"
        "- Do not invent requirements that are not supported by signals or constraints.\n"
        "- Return JSON only. No markdown fences, prose, or comments."
    )


def _user_prompt(context: dict) -> str:
    target = context.get("target") or {}
    capability = context.get("capability") or {}
    payload = {
        "target": target,
        "capability": {
            "capability_key": capability.get("capability_key"),
            "found": capability.get("found"),
            "name": capability.get("name"),
            "version": capability.get("version"),
            "manifest_json": capability.get("manifest_json"),
            "prompt": capability.get("prompt"),
            "prompt_truncated": capability.get("prompt_truncated"),
        },
        "recent_signals": context.get("recent_signals") or [],
        "constraints": context.get("constraints") or [],
        "validation": context.get("validation") or {},
        "validation_goals": context.get("validation_goals") or [],
        "validation_results": context.get("validation_results") or [],
    }
    return (
        "Review this evolution context and produce the JSON prompt revision proposal.\n\n"
        + json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2)
    )


def _parse_json_object(text: str) -> dict:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise ValueError(f"LLM evolution response was not valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("LLM evolution response must be a JSON object")
    return value
