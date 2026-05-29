from __future__ import annotations

import subprocess
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session
from ulid import ULID

from ..models import Run, RuntimeAdapter
from ..runtimes.command_renderer import CommandRenderError, resolve_executable_for_detection
from ..runtimes.specs import RuntimeAdapterSpec, get_runtime_adapter_spec, list_runtime_adapter_specs
from ..runtimes.usage import get_usage_provider
from ..schemas import RuntimeAdapterCreate, RuntimeAdapterStatusOut, RuntimeAdapterUpdate

HEALTH_STATUSES = {"unknown", "ok", "warning", "error", "unimplemented", "disabled"}
QUOTA_STATUSES = {"unknown", "enough", "medium", "low", "exhausted"}


def _new_id() -> str:
    return str(ULID())


def _validate_status_values(*, health_status: str | None = None, quota_status: str | None = None) -> None:
    if health_status is not None and health_status not in HEALTH_STATUSES:
        raise ValueError(f"Invalid runtime adapter health_status: {health_status}")
    if quota_status is not None and quota_status not in QUOTA_STATUSES:
        raise ValueError(f"Invalid runtime adapter quota_status: {quota_status}")


def _format_render_warning(exc: CommandRenderError, *, override: str | None) -> str:
    if override:
        return f"{exc.error_code}: {exc.message}"
    return exc.message


class RuntimeAdapterService:
    def __init__(self, db: Session):
        self.db = db

    def catalog(self) -> list[dict[str, Any]]:
        return [spec.catalog_dict() for spec in list_runtime_adapter_specs()]

    def list(self, space_id: str) -> list[RuntimeAdapter]:
        return (
            self.db.query(RuntimeAdapter)
            .filter(RuntimeAdapter.space_id == space_id)
            .order_by(RuntimeAdapter.created_at)
            .all()
        )

    def get(self, adapter_id: str, space_id: str) -> RuntimeAdapter | None:
        return (
            self.db.query(RuntimeAdapter)
            .filter(RuntimeAdapter.id == adapter_id, RuntimeAdapter.space_id == space_id)
            .first()
        )

    def create(self, data: RuntimeAdapterCreate, space_id: str) -> RuntimeAdapter:
        spec = get_runtime_adapter_spec(data.adapter_type)
        enabled = bool(data.enabled)
        health_status = data.health_status
        quota_status = data.quota_status
        _validate_status_values(health_status=health_status, quota_status=quota_status)
        if spec.implementation_status != "implemented":
            if enabled:
                raise ValueError(f"Adapter type '{data.adapter_type}' is {spec.implementation_status} and cannot be enabled")
            health_status = "unimplemented"
            quota_status = "unknown"
        config = dict(data.config_json or {})
        for key in ("executable_path", "default_mode", "notes"):
            value = getattr(data, key)
            if value is not None:
                config[key] = value
        if config.get("executable_path"):
            resolve_executable_for_detection(spec, str(config["executable_path"]))
        row = RuntimeAdapter(
            id=_new_id(),
            space_id=space_id,
            name=data.name,
            adapter_type=data.adapter_type,
            enabled=enabled,
            provider_id=data.provider_id,
            credential_id=data.credential_id,
            credential_profile_id=data.credential_profile_id,
            config_json=config,
            health_status=health_status,
            quota_status=quota_status,
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def update(self, adapter_id: str, space_id: str, data: RuntimeAdapterUpdate) -> RuntimeAdapter | None:
        row = self.get(adapter_id, space_id)
        if row is None:
            return None
        spec = get_runtime_adapter_spec(row.adapter_type)
        patch = data.model_dump(exclude_unset=True)
        if patch.get("enabled") is True and spec.implementation_status != "implemented":
            raise ValueError(f"Adapter type '{row.adapter_type}' is {spec.implementation_status} and cannot be enabled")
        _validate_status_values(
            health_status=patch.get("health_status"),
            quota_status=patch.get("quota_status"),
        )
        if spec.implementation_status != "implemented":
            patch["enabled"] = False
            patch["health_status"] = "unimplemented"
            patch.setdefault("quota_status", "unknown")
        config = dict(row.config_json or {})
        for key in ("executable_path", "default_mode", "notes", "permission_bypass"):
            if key in patch:
                value = patch.pop(key)
                if value is None:
                    config.pop(key, None)
                else:
                    config[key] = value
        if "config_json" in patch and patch["config_json"] is not None:
            config.update(patch.pop("config_json"))
        if config.get("executable_path"):
            resolve_executable_for_detection(spec, str(config["executable_path"]))
        for field, value in patch.items():
            setattr(row, field, value)
        row.config_json = config
        self.db.commit()
        self.db.refresh(row)
        return row

    def delete(self, adapter_id: str, space_id: str) -> bool:
        row = self.get(adapter_id, space_id)
        if row is None:
            return False
        self.db.delete(row)
        self.db.commit()
        return True

    def detect_all(self, space_id: str) -> list[RuntimeAdapterStatusOut]:
        counts = dict(
            self.db.query(RuntimeAdapter.adapter_type, func.count(RuntimeAdapter.id))
            .filter(RuntimeAdapter.space_id == space_id)
            .group_by(RuntimeAdapter.adapter_type)
            .all()
        )
        return [
            self.status_for_spec(spec, configured_count=int(counts.get(spec.adapter_type, 0)))
            for spec in list_runtime_adapter_specs()
        ]

    def detect_one(self, adapter_type: str, space_id: str | None = None) -> RuntimeAdapterStatusOut:
        configured_count = 0
        if space_id is not None:
            configured_count = (
                self.db.query(RuntimeAdapter)
                .filter(RuntimeAdapter.space_id == space_id, RuntimeAdapter.adapter_type == adapter_type)
                .count()
            )
        return self.status_for_spec(get_runtime_adapter_spec(adapter_type), configured_count=configured_count)

    def status(self, adapter: RuntimeAdapter) -> RuntimeAdapterStatusOut:
        return self.status_for_adapter(adapter)

    def probe(self, adapter: RuntimeAdapter) -> RuntimeAdapterStatusOut:
        return self.status(adapter)

    def usage(self, adapter: RuntimeAdapter, *, refresh: bool = False) -> dict[str, Any]:
        spec = get_runtime_adapter_spec(adapter.adapter_type)
        provider = get_usage_provider(self.db, spec, adapter)
        return provider.refresh_usage() if refresh else provider.read_cached_usage()

    def status_for_spec(self, spec: RuntimeAdapterSpec, *, configured_count: int = 0) -> RuntimeAdapterStatusOut:
        return self._build_status(spec, adapter=None, configured_count=configured_count)

    def status_for_adapter(self, adapter: RuntimeAdapter) -> RuntimeAdapterStatusOut:
        spec = get_runtime_adapter_spec(adapter.adapter_type)
        configured_count = (
            self.db.query(RuntimeAdapter)
            .filter(RuntimeAdapter.space_id == adapter.space_id, RuntimeAdapter.adapter_type == adapter.adapter_type)
            .count()
        )
        return self._build_status(spec, adapter=adapter, configured_count=configured_count)

    def _build_status(
        self,
        spec: RuntimeAdapterSpec,
        *,
        adapter: RuntimeAdapter | None,
        configured_count: int = 0,
    ) -> RuntimeAdapterStatusOut:
        executable_path = None
        installed = spec.runtime_kind == "native"
        version = None
        warnings: list[str] = []
        if spec.runtime_kind == "local_cli":
            override = (adapter.config_json or {}).get("executable_path") if adapter else None
            try:
                executable_path = resolve_executable_for_detection(spec, override)
                installed = True
                if spec.executable.version_command:
                    cmd = [
                        executable_path if part == "{executable}" else part
                        for part in spec.executable.version_command
                    ]
                    res = subprocess.run(cmd, capture_output=True, text=True, timeout=5, shell=False)
                    version = (res.stdout.strip() or res.stderr.strip() or None)
            except CommandRenderError as exc:
                installed = False
                executable_path = str(override) if override else None
                warnings.append(_format_render_warning(exc, override=str(override) if override else None))
            except Exception as exc:  # noqa: BLE001
                installed = False
                warnings.append(str(exc))
        if spec.implementation_status != "implemented":
            warnings.append(f"Adapter is {spec.implementation_status} and cannot execute.")
        credential_profile_id = getattr(adapter, "credential_profile_id", None)
        credential_ready = spec.credentials.credential_mode != "cli_profile"
        if spec.credentials.credential_mode == "cli_profile":
            try:
                from ..credentials.broker import CredentialBroker
                runtime = spec.credentials.credential_runtime_name or spec.adapter_type
                credential_ready = CredentialBroker().profile_ready(runtime, credential_profile_id)
            except Exception:
                credential_ready = False
        last = None
        if adapter is not None:
            q = self.db.query(Run).filter(Run.space_id == adapter.space_id)
            q_by_id = q.filter(Run.runtime_adapter_id == adapter.id)
            last = q_by_id.order_by(Run.created_at.desc()).first()
            if last is None:
                last = (
                    q.filter(Run.adapter_type == spec.adapter_type)
                    .filter(Run.runtime_adapter_id.is_(None))
                    .order_by(Run.created_at.desc())
                    .first()
                )
        health_status = getattr(adapter, "health_status", None) if adapter else None
        if health_status is None:
            health_status = "unimplemented" if spec.implementation_status != "implemented" else "unknown"
        quota_status = getattr(adapter, "quota_status", "unknown") if adapter else "unknown"
        return RuntimeAdapterStatusOut(
            runtime_adapter_id=getattr(adapter, "id", None),
            adapter_type=spec.adapter_type,
            implementation_status=spec.implementation_status,
            configured_count=configured_count,
            configured=adapter is not None,
            enabled=bool(adapter.enabled) if adapter else spec.enabled_by_default,
            installed=installed,
            executable_path=executable_path,
            version=version,
            credential_required=spec.credentials.credential_mode != "none",
            credential_profile_id=credential_profile_id,
            credential_ready=credential_ready,
            model_provider_required=spec.model.model_provider_mode == "required",
            model_provider_ready=bool(getattr(adapter, "provider_id", None)) if adapter else False,
            supports_headless=bool(spec.invocation.headless_command_template) or spec.runtime_kind == "native",
            supports_interactive=bool(spec.invocation.interactive_command_template),
            supports_model_override=spec.model.supports_model_override,
            supports_usage_probe=spec.usage.supports_usage_probe,
            usage_accuracy=spec.usage.usage_accuracy,
            minimum_sandbox_level=spec.sandbox.minimum_sandbox_level,
            last_run_status=getattr(last, "status", None),
            last_error_code=(last.error_json or {}).get("error_code") if last and last.error_json else None,
            health_status=health_status,
            quota_status=quota_status,
            warnings=warnings,
        )
