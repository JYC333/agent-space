"""M5 policy enforcement inventory invariants."""

from pathlib import Path


def test_m5_policy_enforcement_inventory_documents_required_points():
    root = Path(__file__).resolve().parents[4]
    inventory = root / ".agent" / "architecture" / "POLICY_ENFORCEMENT_INVENTORY.md"
    text = inventory.read_text(encoding="utf-8")

    required_points = [
        "HTTP auth/session identity",
        "Space membership / selected space access",
        "Memory read authorization",
        "Memory write proposal creation",
        "Memory proposal apply",
        "Policy proposal apply",
        "Proposal accept/reject authorization",
        "Run creation",
        "Runtime execution",
        "Runtime credential use",
        "Task claim / assignment",
        "Workspace file read",
        "Workspace file write / code patch apply",
        "Sandbox path access",
        "Deployment/deployer calls",
        "Capability reload/enable",
        "Future automation trigger",
        "Future connector sync",
        "Future self-evolution actions",
    ]

    for point in required_points:
        assert point in text

    assert "memory.write_direct" in text
    assert "full enterprise RBAC" in text
    assert "full ABAC language" in text
    assert "For non-covered actions" in text
