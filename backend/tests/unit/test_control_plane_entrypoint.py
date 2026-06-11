"""Static guards for the default client-facing control-plane topology."""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
COMPOSE_DIR = REPO_ROOT / "ops" / "compose"


def _compose(mode: str) -> str:
    return (COMPOSE_DIR / f"docker-compose.{mode}.yml").read_text()


def _service_block(compose_text: str, service: str) -> str:
    matches = list(re.finditer(r"^  [A-Za-z0-9_-]+:\n", compose_text, re.M))
    for index, match in enumerate(matches):
        if match.group(0) == f"  {service}:\n":
            end = matches[index + 1].start() if index + 1 < len(matches) else len(compose_text)
            return compose_text[match.start() : end]
    raise AssertionError(f"service not found: {service}")


def test_control_plane_is_in_every_compose_stack_and_depends_on_backend():
    for mode in ("dev", "test", "prod"):
        text = _compose(mode)
        control_plane = _service_block(text, "control-plane")
        assert "dockerfile: control-plane/Dockerfile" in control_plane
        assert "depends_on:\n      backend:\n        condition: service_healthy" in control_plane
        assert (
            "LEGACY_PYTHON_API_BASE_URL=${LEGACY_PYTHON_API_BASE_URL:-http://backend:8000}"
            in control_plane
        )
        assert "CONTROL_PLANE_ENABLE_LEGACY_PROXY=${CONTROL_PLANE_ENABLE_LEGACY_PROXY:-true}" in control_plane


def test_frontend_routes_to_control_plane_in_dev_and_test():
    for mode in ("dev", "test"):
        frontend = _service_block(_compose(mode), "frontend")
        assert "depends_on:\n      control-plane:\n        condition: service_healthy" in frontend
        assert "CONTROL_PLANE_API_URL=${CONTROL_PLANE_API_URL:-http://control-plane:8010}" in frontend
        assert "API_URL=http://backend" not in frontend
        assert "API_URL=http://localhost:8000" not in frontend


def test_prod_frontend_routes_api_to_control_plane_and_backend_is_not_public():
    text = _compose("prod")
    backend = _service_block(text, "backend")
    frontend = _service_block(text, "frontend")

    assert "ports:" not in backend
    assert "depends_on:\n      control-plane:\n        condition: service_healthy" in frontend
    assert '- "80:80"' in frontend


def test_prod_nginx_routes_api_to_control_plane():
    text = (REPO_ROOT / "apps" / "web" / "nginx.conf").read_text()
    assert "location /api/" in text
    assert "proxy_pass http://control-plane:8010;" in text
    assert "proxy_pass http://backend" not in text


def test_backend_and_control_plane_have_container_healthchecks():
    backend_dockerfile = (REPO_ROOT / "backend" / "Dockerfile").read_text()
    control_plane_dockerfile = (REPO_ROOT / "control-plane" / "Dockerfile").read_text()

    assert "HEALTHCHECK" in backend_dockerfile
    assert "http://localhost:8000/health" in backend_dockerfile
    assert "HEALTHCHECK" in control_plane_dockerfile
    assert "http://localhost:8010/health" in control_plane_dockerfile
