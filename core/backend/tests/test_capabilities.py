import os
import pytest
import tempfile
import yaml
from pathlib import Path

from app.capabilities.loader import load_capability_manifest, scan_capabilities
from app.capabilities.registry import CapabilityRegistry


def _write_cap(directory: Path, manifest: dict):
    cap_dir = directory / manifest["id"].replace(".", "_")
    cap_dir.mkdir()
    with open(cap_dir / "capability.yaml", "w") as f:
        yaml.dump(manifest, f)
    return cap_dir


def test_load_valid_manifest(tmp_path):
    cap_dir = tmp_path / "test.cap"
    cap_dir.mkdir()
    manifest = {
        "id": "test.cap",
        "name": "Test Capability",
        "version": "1.0.0",
        "description": "A test capability.",
    }
    with open(cap_dir / "capability.yaml", "w") as f:
        yaml.dump(manifest, f)

    loaded = load_capability_manifest(cap_dir)
    assert loaded is not None
    assert loaded["id"] == "test.cap"
    assert loaded["version"] == "1.0.0"


def test_load_missing_manifest(tmp_path):
    cap_dir = tmp_path / "empty"
    cap_dir.mkdir()
    assert load_capability_manifest(cap_dir) is None


def test_load_manifest_missing_required_field(tmp_path):
    cap_dir = tmp_path / "bad.cap"
    cap_dir.mkdir()
    with open(cap_dir / "capability.yaml", "w") as f:
        yaml.dump({"id": "bad.cap", "name": "Bad"}, f)  # missing version + description
    assert load_capability_manifest(cap_dir) is None


def test_scan_capabilities(tmp_path):
    valid = {"id": "a.cap", "name": "A", "version": "1.0.0", "description": "A cap"}
    _write_cap(tmp_path, valid)

    bad_dir = tmp_path / "empty_cap"
    bad_dir.mkdir()

    results = scan_capabilities(str(tmp_path))
    loaded = [r for r, e in results if not e]
    failed = [e for _, e in results if e]
    assert len(loaded) >= 1
    assert any("a.cap" == m["id"] for m in loaded)


def test_registry_loads_from_dir(db, tmp_path):
    manifest = {"id": "test.reg", "name": "Reg Test", "version": "0.1.0", "description": "Reg test cap"}
    _write_cap(tmp_path, manifest)

    from app.config import settings
    original = settings.capabilities_dir
    settings.capabilities_dir = str(tmp_path)
    try:
        registry = CapabilityRegistry(db)
        result = registry.reload()
        assert result["loaded"] >= 1
        cap = registry.get("test.reg")
        assert cap is not None
        assert cap.name == "Reg Test"
    finally:
        settings.capabilities_dir = original


def test_registry_reload_updates_existing(db, tmp_path):
    manifest = {"id": "upd.cap", "name": "Old Name", "version": "1.0.0", "description": "Test"}
    cap_dir = _write_cap(tmp_path, manifest)

    from app.config import settings
    original = settings.capabilities_dir
    settings.capabilities_dir = str(tmp_path)
    try:
        registry = CapabilityRegistry(db)
        registry.reload()

        # Update the manifest
        manifest["name"] = "New Name"
        manifest["version"] = "1.1.0"
        with open(cap_dir / "capability.yaml", "w") as f:
            yaml.dump(manifest, f)

        registry.reload()
        cap = registry.get("upd.cap")
        assert cap.name == "New Name"
        assert cap.version == "1.1.0"
    finally:
        settings.capabilities_dir = original
