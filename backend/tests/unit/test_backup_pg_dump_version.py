"""BackupService pg_dump must match the PostgreSQL server major version.

Online BackupService shells out to ``pg_dump`` inside the backend container.
``pg_dump`` refuses to dump a server newer than the client, so the backend image
must install the PostgreSQL client whose major version matches the ``postgres``
server image in docker-compose. These static checks guard the chosen design
(install the exact matching client) against regressions such as reverting to the
generic, older Debian ``postgresql-client`` package.
"""
from __future__ import annotations

from pathlib import Path
import re

REPO_ROOT = Path(__file__).resolve().parents[3]
DOCKERFILE = REPO_ROOT / "backend" / "Dockerfile"
COMPOSE_FILES = [
    REPO_ROOT / "ops" / "compose" / "docker-compose.dev.yml",
    REPO_ROOT / "ops" / "compose" / "docker-compose.test.yml",
    REPO_ROOT / "ops" / "compose" / "docker-compose.prod.yml",
]


def _server_majors() -> set[int]:
    majors = set()
    for f in COMPOSE_FILES:
        for m in re.finditer(r"image:\s*postgres:\$\{POSTGRES_MAJOR:-(\d+)\}", f.read_text()):
            majors.add(int(m.group(1)))
    return majors


def test_compose_uses_consistent_postgres_major():
    majors = _server_majors()
    assert majors, "no postgres:${POSTGRES_MAJOR:-<major>} image found in compose files"
    assert len(majors) == 1, f"compose files disagree on postgres major: {majors}"
    major = next(iter(majors))

    for f in COMPOSE_FILES:
        text = f.read_text()
        assert f"image: postgres:${{POSTGRES_MAJOR:-{major}}}" in text
        assert f"PG_MAJOR: ${{POSTGRES_MAJOR:-{major}}}" in text


def test_compose_uses_stable_postgres_container_names():
    for mode in ("dev", "test", "prod"):
        text = (REPO_ROOT / "ops" / "compose" / f"docker-compose.{mode}.yml").read_text()
        assert f"container_name: agent-space-{mode}-postgres" in text


def test_test_compose_keeps_backend_internal_port_8000_with_host_8100():
    text = (REPO_ROOT / "ops" / "compose" / "docker-compose.test.yml").read_text()
    assert '- "8100:8000"' in text
    assert "command: uvicorn app.main:app --host 0.0.0.0 --port 8000" in text
    assert "CONTROL_PLANE_API_URL=${CONTROL_PLANE_API_URL:-http://control-plane:8010}" in text
    assert "8100:8100" not in text
    assert "backend:8100" not in text
    assert "--port 8100" not in text


def test_dockerfile_pins_matching_pg_client_major():
    text = DOCKERFILE.read_text()
    server_majors = _server_majors()
    assert len(server_majors) == 1
    server_major = next(iter(server_majors))

    pg_major_match = re.search(r"ARG\s+PG_MAJOR=(\d+)", text)
    assert pg_major_match, "Dockerfile must declare ARG PG_MAJOR=<major>"
    assert re.search(r"ENV\s+PG_MAJOR=\$\{PG_MAJOR\}", text), (
        "Dockerfile must export ENV PG_MAJOR=${PG_MAJOR}"
    )
    client_major = int(pg_major_match.group(1))

    assert client_major == server_major, (
        f"backend pg client major ({client_major}) must match postgres server "
        f"major ({server_major}); pg_dump cannot dump a newer server"
    )
    # The matching client must actually be installed.
    assert 'postgresql-client-${PG_MAJOR}' in text or f"postgresql-client-{server_major}" in text, (
        "Dockerfile must install postgresql-client-${PG_MAJOR} (the matching client)"
    )


def test_dockerfile_does_not_install_generic_postgresql_client():
    """The generic (unversioned) Debian postgresql-client is an older major — forbid it."""
    # Only inspect actual instructions, not explanatory comments.
    instructions = "\n".join(
        line for line in DOCKERFILE.read_text().splitlines()
        if not line.lstrip().startswith("#")
    )
    # Match 'postgresql-client' NOT immediately followed by '-' (version) or '$' (var).
    bad = re.findall(r"postgresql-client(?![-\$])", instructions)
    assert not bad, (
        "Dockerfile installs the generic 'postgresql-client' (wrong major). "
        "Install the version-pinned 'postgresql-client-${PG_MAJOR}' instead."
    )
