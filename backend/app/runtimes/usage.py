"""Runtime-generic usage provider abstraction."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Run, RuntimeAdapter
from .specs import RuntimeAdapterSpec


class RuntimeUsageProvider:
    def __init__(self, db: Session, spec: RuntimeAdapterSpec, adapter: RuntimeAdapter | None = None):
        self.db = db
        self.spec = spec
        self.adapter = adapter

    def read_cached_usage(self) -> dict[str, Any]:
        return self._fallback_usage()

    def refresh_usage(self) -> dict[str, Any]:
        data = self.read_cached_usage()
        if not self.spec.usage.supports_usage_probe:
            data["warning"] = "live usage probe is not available for this runtime adapter; returning cached run statistics"
        return data

    def parse_usage(self, raw: Any) -> dict[str, Any]:
        return {"raw": raw, "usage_accuracy": self.spec.usage.usage_accuracy}

    @property
    def usage_accuracy(self) -> str:
        return self.spec.usage.usage_accuracy

    def _fallback_usage(self) -> dict[str, Any]:
        q = self.db.query(Run).filter(Run.adapter_type == self.spec.adapter_type)
        runtime_adapter_id = None
        if self.adapter is not None:
            runtime_adapter_id = self.adapter.id
            q = q.filter(Run.space_id == self.adapter.space_id)
            q_by_id = q.filter(Run.runtime_adapter_id == self.adapter.id)
            if q_by_id.count() > 0:
                q = q_by_id
            else:
                q = q.filter(Run.runtime_adapter_id.is_(None))
        return {
            "adapter_type": self.spec.adapter_type,
            "runtime_adapter_id": runtime_adapter_id,
            "usage_accuracy": self.spec.usage.usage_accuracy,
            "supports_usage_probe": self.spec.usage.supports_usage_probe,
            "quota_status": getattr(self.adapter, "quota_status", "unknown") if self.adapter else "unknown",
            "run_count": q.count(),
            "last_run_at": q.with_entities(func.max(Run.started_at)).scalar(),
            "runtime_seconds": q.with_entities(func.sum(Run.runtime_seconds)).scalar() or 0,
        }


class ClaudeUsageProvider(RuntimeUsageProvider):
    def read_cached_usage(self) -> dict[str, Any]:
        cached = _read_json(_quota_cache_path())
        data = self._fallback_usage()
        data["cached_quota"] = cached
        return data

    def refresh_usage(self) -> dict[str, Any]:
        data = self._fallback_usage()
        data["cached_quota"] = _read_json(_quota_cache_path())
        data["warning"] = "live Claude quota probe is not available in this build"
        data["checked_at"] = datetime.now(UTC).isoformat()
        return data


def get_usage_provider(db: Session, spec: RuntimeAdapterSpec, adapter: RuntimeAdapter | None = None) -> RuntimeUsageProvider:
    if spec.usage.usage_probe_kind == "cached_claude_quota":
        return ClaudeUsageProvider(db, spec, adapter)
    return RuntimeUsageProvider(db, spec, adapter)


def _quota_cache_path() -> Path:
    return Path(settings.instance_root) / "cache" / "quota-cache.json"


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
