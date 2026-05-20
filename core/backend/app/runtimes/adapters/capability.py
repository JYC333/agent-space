"""Runtime adapter for executing installed local capabilities."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

from ...capabilities.registry import FileDefinedCapability, load_installed_capability
from ...config import settings
from ..base import BaseRuntimeAdapter, RuntimeAdapterResult, RuntimeExecutionContext


_SUPPORTED_ENTRYPOINT_TYPES = {"python_module"}
_SUPPORTED_PERMISSION_KEYS = {"network", "filesystem", "subprocess"}
_SUPPORTED_NETWORK_KEYS = {"allow"}
_SUPPORTED_FILESYSTEM_KEYS = {"read", "write"}
_SUPPORTED_SUBPROCESS_KEYS = {"allow"}


class CapabilityRuntimeAdapter(BaseRuntimeAdapter):
    """Execute an enabled file-defined capability via an allowlisted entrypoint."""

    adapter_type = "capability"
    requires_credentials = False
    requires_file_access = False
    supports_sandboxed_execution = False

    def execute(self, ctx: RuntimeExecutionContext) -> RuntimeAdapterResult:
        try:
            if not ctx.capability_id:
                return _failure("capability_id_missing", "Run.capability_id is required")

            cap = self._configured_capability(ctx)
            if cap is None:
                cap = load_installed_capability(ctx.capability_id, space_id=ctx.space_id)
            if cap is None:
                return _failure(
                    "capability_not_found",
                    f"Capability '{ctx.capability_id}' is not installed",
                )
            if not cap.enabled:
                return _failure(
                    "capability_disabled",
                    f"Capability '{ctx.capability_id}' is disabled",
                )

            self._validate_permissions(cap)
            entrypoint = self._validated_entrypoint(cap)
            fn = self._load_function(cap, entrypoint)
            result = fn(self._context_payload(ctx))
            output_json = self._validated_result(cap, result)
            return RuntimeAdapterResult(
                success=True,
                output_json=output_json,
                output_text="",
                exit_code=0,
                adapter_metadata={
                    "adapter_type": self.adapter_type,
                    "capability_id": cap.id,
                    "capability_version": cap.version,
                    "entrypoint_type": entrypoint["type"],
                },
            )
        except CapabilityRuntimeError as exc:
            return _failure(exc.error_code, exc.message)
        except Exception as exc:  # noqa: BLE001
            return _failure("capability_execution_error", f"Capability execution failed: {exc}")

    def _configured_capability(self, ctx: RuntimeExecutionContext) -> FileDefinedCapability | None:
        data = ctx.adapter_config.get("capability")
        if not isinstance(data, dict):
            return None
        if data.get("id") != ctx.capability_id:
            return None
        required = {
            "id",
            "name",
            "version",
            "description",
            "manifest_dir",
            "manifest_json",
        }
        if not required.issubset(data):
            return None
        return FileDefinedCapability(
            id=str(data["id"]),
            name=str(data["name"]),
            version=str(data["version"]),
            description=str(data.get("description") or ""),
            entrypoint=data.get("entrypoint"),
            manifest_dir=str(data["manifest_dir"]),
            manifest_json=dict(data["manifest_json"]),
            source=str(data.get("source") or "builtin"),
            workspace_id=data.get("workspace_id"),
            root_path=data.get("root_path"),
            manifest_path=data.get("manifest_path"),
            enabled=bool(data.get("enabled", False)),
        )

    def _validated_entrypoint(self, cap: FileDefinedCapability) -> dict[str, str]:
        entrypoint = cap.entrypoint
        if not isinstance(entrypoint, dict):
            raise CapabilityRuntimeError(
                "capability_entrypoint_missing",
                f"Capability '{cap.id}' must declare an entrypoint object",
            )
        etype = entrypoint.get("type")
        module = entrypoint.get("module")
        function = entrypoint.get("function")
        if etype not in _SUPPORTED_ENTRYPOINT_TYPES:
            raise CapabilityRuntimeError(
                "capability_entrypoint_unsupported",
                f"Unsupported capability entrypoint type: {etype!r}",
            )
        if not isinstance(module, str) or not module.strip():
            raise CapabilityRuntimeError(
                "capability_entrypoint_invalid",
                "Capability entrypoint.module must be a non-empty string",
            )
        if not isinstance(function, str) or not function.strip():
            raise CapabilityRuntimeError(
                "capability_entrypoint_invalid",
                "Capability entrypoint.function must be a non-empty string",
            )
        return {"type": etype, "module": module.strip(), "function": function.strip()}

    def _load_function(self, cap: FileDefinedCapability, entrypoint: dict[str, str]):
        module_name = entrypoint["module"]
        root = Path(cap.root_path or settings.capabilities_dir).resolve()
        module_root = root.name
        if not module_name.startswith(f"{module_root}."):
            raise CapabilityRuntimeError(
                "capability_entrypoint_invalid",
                f"Capability module must be under local package '{module_root}'",
            )

        cap_dir = Path(cap.manifest_dir).resolve()
        parts = module_name.split(".")
        if len(parts) < 3 or parts[1] != cap_dir.name:
            raise CapabilityRuntimeError(
                "capability_entrypoint_invalid",
                "Capability module must target its installed capability directory",
            )

        module_file = (cap_dir.joinpath(*parts[2:])).with_suffix(".py").resolve()
        try:
            module_file.relative_to(root)
            module_file.relative_to(cap_dir)
        except ValueError as exc:
            raise CapabilityRuntimeError(
                "capability_entrypoint_invalid",
                "Capability module must resolve inside its installed capability directory",
            ) from exc
        if not module_file.is_file():
            raise CapabilityRuntimeError(
                "capability_entrypoint_invalid",
                f"Capability module file '{module_file.name}' was not found",
            )

        unique_module_name = f"_capability_{cap.id.replace('-', '_')}_{abs(hash(str(module_file)))}"
        spec = importlib.util.spec_from_file_location(unique_module_name, module_file)
        if spec is None or spec.loader is None:
            raise CapabilityRuntimeError(
                "capability_entrypoint_invalid",
                "Capability module could not be loaded",
            )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        fn = getattr(module, entrypoint["function"], None)
        if not callable(fn):
            raise CapabilityRuntimeError(
                "capability_entrypoint_invalid",
                f"Capability function '{entrypoint['function']}' is not callable",
            )
        return fn

    def _validate_permissions(self, cap: FileDefinedCapability) -> None:
        permissions = cap.manifest_json.get("permissions") or {}
        if not isinstance(permissions, dict):
            raise CapabilityRuntimeError(
                "capability_permissions_invalid",
                "Capability permissions must be an object",
            )
        unsupported = set(permissions) - _SUPPORTED_PERMISSION_KEYS
        if unsupported:
            raise CapabilityRuntimeError(
                "capability_permissions_unsupported",
                f"Unsupported capability permissions: {sorted(unsupported)}",
            )

        network = permissions.get("network") or {}
        filesystem = permissions.get("filesystem") or {}
        subprocess = permissions.get("subprocess") or {}
        self._validate_permission_object("network", network, _SUPPORTED_NETWORK_KEYS)
        self._validate_permission_object("filesystem", filesystem, _SUPPORTED_FILESYSTEM_KEYS)
        self._validate_permission_object("subprocess", subprocess, _SUPPORTED_SUBPROCESS_KEYS)

        if network.get("allow") not in (None, []):
            raise CapabilityRuntimeError(
                "capability_permissions_unsupported",
                "Capability network permissions are not enforced in v1; network.allow must be empty",
            )
        if filesystem.get("read") not in (None, []):
            raise CapabilityRuntimeError(
                "capability_permissions_unsupported",
                "Capability filesystem.read permissions are not enforced in v1; read must be empty",
            )
        if filesystem.get("write") not in (None, []):
            raise CapabilityRuntimeError(
                "capability_permissions_unsupported",
                "Capability filesystem.write permissions are not enforced in v1; write must be empty",
            )
        if subprocess.get("allow") is True:
            raise CapabilityRuntimeError(
                "capability_permissions_unsupported",
                "Capability subprocess execution is not supported in v1",
            )

    def _validate_permission_object(
        self,
        name: str,
        value: Any,
        supported_keys: set[str],
    ) -> None:
        if not isinstance(value, dict):
            raise CapabilityRuntimeError(
                "capability_permissions_invalid",
                f"Capability permissions.{name} must be an object",
            )
        unsupported = set(value) - supported_keys
        if unsupported:
            raise CapabilityRuntimeError(
                "capability_permissions_unsupported",
                f"Unsupported capability permissions.{name} fields: {sorted(unsupported)}",
            )

    def _context_payload(self, ctx: RuntimeExecutionContext) -> dict[str, Any]:
        input_payload: dict[str, Any] = {}
        prompt = (ctx.prompt or "").strip()
        if prompt and prompt != "(empty prompt)":
            try:
                parsed = json.loads(prompt)
            except json.JSONDecodeError:
                input_payload = {"prompt": prompt}
            else:
                input_payload = parsed if isinstance(parsed, dict) else {"value": parsed}

        return {
            "run_id": ctx.run_id,
            "space_id": ctx.space_id,
            "project_id": ctx.project_id,
            "workspace_id": ctx.workspace_id,
            "capability_id": ctx.capability_id,
            "input": input_payload,
        }

    def _validated_result(self, cap: FileDefinedCapability, result: Any) -> dict[str, Any]:
        if not isinstance(result, dict):
            raise CapabilityRuntimeError(
                "capability_result_invalid",
                "Capability execute() must return an object",
            )

        status = str(result.get("status") or "succeeded")
        if status not in {"succeeded", "failed"}:
            raise CapabilityRuntimeError(
                "capability_result_invalid",
                "Capability result.status must be 'succeeded' or 'failed'",
            )
        if status == "failed":
            raise CapabilityRuntimeError(
                "capability_result_failed",
                str(result.get("error") or "Capability returned failed status"),
            )

        output = result.get("output")
        if output is not None and not isinstance(output, dict):
            raise CapabilityRuntimeError(
                "capability_result_invalid",
                "Capability result.output must be an object when provided",
            )
        artifacts = _list_of_objects(result.get("artifacts"), "artifacts")
        activities = _list_of_objects(result.get("activities"), "activities")
        self._validate_declared_artifact_types(cap, artifacts)

        return {
            "capability_id": cap.id,
            "capability_version": cap.version,
            "status": status,
            "output": output or {},
            "artifacts": artifacts,
            "activities": activities,
        }

    def _validate_declared_artifact_types(
        self,
        cap: FileDefinedCapability,
        artifacts: list[dict[str, Any]],
    ) -> None:
        outputs = cap.manifest_json.get("outputs") or {}
        if not isinstance(outputs, dict):
            raise CapabilityRuntimeError(
                "capability_outputs_invalid",
                "Capability outputs must be an object",
            )
        declared = outputs.get("artifact_types")
        if declared is None:
            return
        if not isinstance(declared, list) or not all(isinstance(v, str) for v in declared):
            raise CapabilityRuntimeError(
                "capability_outputs_invalid",
                "Capability outputs.artifact_types must be a list of strings",
            )
        allowed = set(declared)
        for spec in artifacts:
            artifact_type = str(spec.get("artifact_type") or "report")
            if artifact_type not in allowed:
                raise CapabilityRuntimeError(
                    "capability_result_invalid",
                    f"Capability returned undeclared artifact_type '{artifact_type}'",
                )


class CapabilityRuntimeError(Exception):
    def __init__(self, error_code: str, message: str):
        super().__init__(message)
        self.error_code = error_code
        self.message = message


def _list_of_objects(value: Any, field: str) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise CapabilityRuntimeError(
            "capability_result_invalid",
            f"Capability result.{field} must be a list",
        )
    items: list[dict[str, Any]] = []
    for i, item in enumerate(value):
        if not isinstance(item, dict):
            raise CapabilityRuntimeError(
                "capability_result_invalid",
                f"Capability result.{field}[{i}] must be an object",
            )
        items.append(item)
    return items


def _failure(error_code: str, error_text: str) -> RuntimeAdapterResult:
    return RuntimeAdapterResult(
        success=False,
        error_code=error_code,
        error_text=error_text[:2000],
        exit_code=1,
        adapter_metadata={"adapter_type": CapabilityRuntimeAdapter.adapter_type},
    )
