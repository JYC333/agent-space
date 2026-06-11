from __future__ import annotations

"""System AgentTemplate seeder.

Seeds the built-in *system-scoped* agent templates (the factory catalog). These
are global (scope=system, no space_id, no owner_user_id), idempotent by key, and
seeded once at startup — they do NOT depend on any space existing.

Template definitions live in ``catalog/agent_templates/<key>/template.yaml``.
The seeder scans that directory, reads each YAML file, and upserts rows
idempotently:

  - key not in DB  → INSERT template + v1 version, publish.
  - key exists, content unchanged → skip.
  - key exists, content changed → create a new version (v2, v3, …), update
    current_version_id. Old versions are preserved.

Templates are factories, not runtime objects. Agents are created FROM these
templates via AgentTemplateService.create_agent_from_template (copy-on-create).
"""

import hashlib
import json
import os
import uuid
from pathlib import Path
from datetime import UTC, datetime
from typing import Any

import yaml
from sqlalchemy.orm import Session

from ..models import AgentTemplate, AgentTemplateVersion

_HERE = Path(__file__).resolve()


def _template_dir() -> Path:
    """Resolve the built-in templates directory across source + container layouts.

    Order: ``AGENT_TEMPLATES_DIR`` env override, the source-tree sibling of the
    source-tree catalog (``catalog/agent_templates``), and the in-image / mounted
    copy at ``<app_root>/agent_templates`` (``/app/agent_templates`` in Docker).
    Returns the first that exists, else the source-tree path (so an empty dir is a
    visible misconfiguration rather than a silent wrong path).
    """
    candidates = []
    env = os.environ.get("AGENT_TEMPLATES_DIR")
    if env:
        candidates.append(Path(env))
    # Source tree: backend/app/agents/ -> catalog/agent_templates
    candidates.append(_HERE.parents[3] / "catalog" / "agent_templates")
    # Bundled/mounted next to the app package: /app/agent_templates
    candidates.append(_HERE.parents[2] / "agent_templates")
    for path in candidates:
        if path.is_dir():
            return path
    return candidates[-1] if candidates else _HERE.parents[3] / "catalog" / "agent_templates"


def _new_id() -> str:
    return str(uuid.uuid4())


def _load_templates() -> list[dict[str, Any]]:
    """Scan the templates directory and return parsed template specs."""
    specs = []
    templates_dir = _template_dir()
    if not templates_dir.exists():
        return specs
    for path in sorted(templates_dir.glob("*/template.yaml")):
        with path.open("r", encoding="utf-8") as f:
            spec = yaml.safe_load(f)
        spec["_source_path"] = str(path)
        specs.append(spec)
    return specs


def _build_version_fields(spec: dict[str, Any]) -> dict[str, Any]:
    """Extract DB-ready version fields from a YAML spec."""
    return {
        "system_prompt": spec.get("system_prompt", ""),
        "model_config_json": spec.get("model_config") or {},
        "context_policy_json": spec.get("context_policy") or {},
        "memory_policy_json": spec.get("memory_policy") or {},
        "tool_policy_json": spec.get("tool_policy") or {},
        "runtime_policy_json": spec.get("runtime_policy") or {},
        "output_policy_json": spec.get("output_policy") or {},
        "schedule_defaults_json": spec.get("schedule_defaults") or {},
        "output_schema_json": spec.get("output_schema") or {},
    }


def _content_hash(fields: dict[str, Any]) -> str:
    """Stable hash of version fields — used to detect content changes."""
    canonical = json.dumps(fields, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def seed_system_templates(db: Session) -> int:
    """Idempotently ensure all system agent templates exist (published).

    Returns the number of templates created or updated on this call.
    """
    specs = _load_templates()
    touched = 0
    now = datetime.now(UTC)

    for spec in specs:
        key = spec.get("key")
        if not key:
            continue

        version_fields = _build_version_fields(spec)
        new_hash = _content_hash(version_fields)

        existing: AgentTemplate | None = (
            db.query(AgentTemplate)
            .filter(AgentTemplate.scope == "system", AgentTemplate.key == key)
            .first()
        )

        if existing is None:
            # First time: create template + v1 version.
            tpl = AgentTemplate(
                id=_new_id(),
                key=key,
                name=spec.get("name", key),
                description=(spec.get("description") or "").strip(),
                category=spec.get("category", "general"),
                scope="system",
                space_id=None,
                owner_user_id=None,
                # Most system templates are public factory entries. The
                # personal_assistant seed spec opts into system_internal so it is
                # hidden from the public library and user create-from-template.
                visibility=spec.get("visibility", "system_public"),
                status="published",
            )
            db.add(tpl)
            db.flush()

            version = AgentTemplateVersion(
                id=_new_id(),
                template_id=tpl.id,
                version="v1",
                **version_fields,
                created_by_user_id=None,
                published_at=now,
            )
            db.add(version)
            db.flush()
            tpl.current_version_id = version.id
            touched += 1

        else:
            # Already exists — check if content changed.
            current_ver: AgentTemplateVersion | None = (
                db.query(AgentTemplateVersion)
                .filter(AgentTemplateVersion.id == existing.current_version_id)
                .first()
            )
            if current_ver is not None:
                current_fields = _build_version_fields({
                    "system_prompt": current_ver.system_prompt,
                    "model_config": current_ver.model_config_json,
                    "context_policy": current_ver.context_policy_json,
                    "memory_policy": current_ver.memory_policy_json,
                    "tool_policy": current_ver.tool_policy_json,
                    "runtime_policy": current_ver.runtime_policy_json,
                    "output_policy": current_ver.output_policy_json,
                    "schedule_defaults": current_ver.schedule_defaults_json,
                    "output_schema": current_ver.output_schema_json,
                })
                if _content_hash(current_fields) == new_hash:
                    continue  # Unchanged — skip.

            # Content changed: bump version label.
            existing_versions = (
                db.query(AgentTemplateVersion)
                .filter(AgentTemplateVersion.template_id == existing.id)
                .count()
            )
            next_label = f"v{existing_versions + 1}"
            new_version = AgentTemplateVersion(
                id=_new_id(),
                template_id=existing.id,
                version=next_label,
                **version_fields,
                created_by_user_id=None,
                published_at=now,
            )
            db.add(new_version)
            db.flush()
            existing.current_version_id = new_version.id
            existing.name = spec.get("name", key)
            existing.description = (spec.get("description") or "").strip()
            touched += 1

    if touched:
        db.commit()
    return touched
