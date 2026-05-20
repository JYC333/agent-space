from __future__ import annotations

"""Persist external capability enable/disable state outside capability manifests."""

import logging
from pathlib import Path

import yaml

from ..config import settings

log = logging.getLogger(__name__)

_SETTINGS_KEY = "capabilities"
_ENABLED_KEY = "enabled_external_capabilities"


def _instance_root(instance_root: str | None = None) -> Path:
    if instance_root is not None:
        return Path(instance_root).resolve()
    return Path(settings.instance_root).resolve()


def _settings_path(instance_root: str | None = None) -> Path:
    return _instance_root(instance_root) / "config" / "settings.yaml"


def load_enabled_external_capabilities(instance_root: str | None = None) -> set[str]:
    path = _settings_path(instance_root)
    if not path.exists():
        return set()
    try:
        with open(path, encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        raw = ((cfg.get(_SETTINGS_KEY) or {}).get(_ENABLED_KEY)) or []
        if not isinstance(raw, list):
            log.warning(
                "settings.yaml %s.%s must be a list",
                _SETTINGS_KEY,
                _ENABLED_KEY,
            )
            return set()
        return {item for item in raw if isinstance(item, str)}
    except Exception as exc:
        log.warning("settings.yaml parse error: %s", exc)
        return set()


def set_external_capability_enabled(
    capability_id: str,
    enabled: bool,
    *,
    instance_root: str | None = None,
) -> None:
    path = _settings_path(instance_root)
    path.parent.mkdir(parents=True, exist_ok=True)

    cfg: dict = {}
    if path.exists():
        try:
            with open(path, encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
        except Exception as exc:
            log.warning("settings.yaml parse error during update: %s", exc)
            cfg = {}

    caps_section = cfg.setdefault(_SETTINGS_KEY, {})
    current = caps_section.get(_ENABLED_KEY) or []
    if not isinstance(current, list):
        current = []
    enabled_ids = {item for item in current if isinstance(item, str)}

    if enabled:
        enabled_ids.add(capability_id)
    else:
        enabled_ids.discard(capability_id)

    caps_section[_ENABLED_KEY] = sorted(enabled_ids)
    cfg[_SETTINGS_KEY] = caps_section

    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, default_flow_style=False, sort_keys=False)
