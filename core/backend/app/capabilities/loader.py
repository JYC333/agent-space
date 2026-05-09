"""
CapabilityLoader — scans the capabilities/ directory and parses capability.yaml files.
"""

from pathlib import Path
from typing import Optional
import yaml


REQUIRED_FIELDS = {"id", "name", "version", "description"}


def load_capability_manifest(capability_dir: Path) -> dict | None:
    """Load and validate a capability.yaml from a capability directory."""
    yaml_path = capability_dir / "capability.yaml"
    if not yaml_path.exists():
        return None

    try:
        with open(yaml_path) as f:
            manifest = yaml.safe_load(f)
    except Exception:
        return None

    if not isinstance(manifest, dict):
        return None

    missing = REQUIRED_FIELDS - set(manifest.keys())
    if missing:
        return None

    manifest["_dir"] = str(capability_dir)
    return manifest


def scan_capabilities(capabilities_dir: str) -> list[tuple[dict, list[str]]]:
    """
    Scan the capabilities directory.

    Returns list of (manifest, errors) tuples.
    Errors is empty on success.
    """
    root = Path(capabilities_dir)
    if not root.exists():
        return []

    results = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        manifest = load_capability_manifest(child)
        if manifest is None:
            errors = [f"Failed to load capability.yaml in {child}"]
            results.append(({}, errors))
        else:
            results.append((manifest, []))

    return results
