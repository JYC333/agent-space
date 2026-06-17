"""Smoke tests for backend public module facades."""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_ROOT.parent


def _run_fresh_python(script: str, tmp_path: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(BACKEND_ROOT)
    env["AGENT_SPACE_HOME"] = str(tmp_path / "agent-space-home")
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(script)],
        cwd=BACKEND_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_public_facades_import_and_lazy_facades_stay_light(tmp_path):
    result = _run_fresh_python(
        """
        import importlib
        import sys

        lazy_modules = ["app.memory", "app.runs"]
        for name in lazy_modules:
            module = importlib.import_module(name)
            assert getattr(module, "__all__"), name

        assert "app.memory.context_builder" not in sys.modules
        assert "app.runs.execution" not in sys.modules
        assert "app.runs.run_service" not in sys.modules
        assert "app.proposals.service" not in sys.modules
        assert "app.proposals.apply_service" not in sys.modules

        from app.memory import ContextBuilderPort
        from app.runs import required_sandbox_level_for_risk

        assert ContextBuilderPort.__name__ == "ContextBuilderPort"
        assert callable(required_sandbox_level_for_risk)
        assert "app.memory.context_builder" not in sys.modules
        assert "app.runs.execution" not in sys.modules
        assert "app.runs.run_service" not in sys.modules
        assert "app.proposals.service" not in sys.modules
        assert "app.proposals.apply_service" not in sys.modules

        public_imports = {
            "app.activity": ["ActivityService", "InputSummaryService"],
            "app.auth": ["get_identity", "UserService"],
            "app.capabilities": ["CapabilityRegistry"],
            "app.credentials": ["CredentialBroker"],
            "app.participation": ["try_record_participation"],
            "app.policy": ["PolicyPort", "PolicyGateway"],
            "app.projects": ["ProjectService"],
            "app.proposals": [
                "proposal_to_out",
                "ProposalApplierRegistry",
                "ProposalApplyError",
                "get_proposal_applier_registry",
            ],
            "app.providers": ["complete_text", "ModelService"],
            "app.router": ["RouterService", "TaskClassification", "RoutingDecision"],
            "app.runtimes": ["BaseRuntimeAdapter"],
        }
        for module_name, names in public_imports.items():
            module = importlib.import_module(module_name)
            assert getattr(module, "__all__"), module_name
            for exported_name in names:
                assert getattr(module, exported_name) is not None, (module_name, exported_name)
        """,
        tmp_path,
    )

    assert result.returncode == 0, result.stderr + result.stdout


def test_control_plane_source_does_not_import_python_backend_internals():
    forbidden = [
        "../backend",
        "../../backend",
        "backend/app",
        "app/models.py",
        "migrations/",
    ]
    offenders: list[str] = []
    for path in (REPO_ROOT / "control-plane" / "src").rglob("*.ts"):
        text = path.read_text(encoding="utf-8")
        for needle in forbidden:
            if needle in text:
                offenders.append(f"{path.relative_to(REPO_ROOT)} contains {needle!r}")

    assert offenders == []
