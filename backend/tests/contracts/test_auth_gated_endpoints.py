"""HTTP contract: system-metadata endpoints require authentication.

Covers:
- GET  /capabilities               401 without auth, 200 with auth
- GET  /capabilities/{id}          401 without auth, 200 with auth
- POST /capabilities/reload        401 without auth, 200 with auth
- GET  /jobs/handlers              401 without auth, 200 with auth
- GET  /workspace-console/runtimes 401 without auth, 200 with auth
- GET  /providers/litellm-providers 401 without auth, 200 with auth
- GET  /providers/catalog           401 without auth, 200 with auth
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _params(cross_space_pair: dict, side: str = "a") -> dict[str, str]:
    return {"space_id": cross_space_pair[f"space_{side}_id"]}


# ===========================================================================
# Capabilities
# ===========================================================================

class TestCapabilitiesAuth:
    def test_list_capabilities_unauthenticated_returns_401(self, api_client):
        r = api_client.get("/api/v1/capabilities")
        assert r.status_code == 401

    def test_get_capability_unauthenticated_returns_401(self, api_client):
        r = api_client.get("/api/v1/capabilities/nonexistent-cap")
        assert r.status_code == 401

    def test_reload_capabilities_unauthenticated_returns_401(self, api_client):
        r = api_client.post("/api/v1/capabilities/reload")
        assert r.status_code == 401

    def test_list_capabilities_authenticated_succeeds(self, api_client, db, cross_space_pair):
        r = cross_space_pair["client_a"].get(
            "/api/v1/capabilities",
            params=_params(cross_space_pair),
        )
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_get_capability_authenticated_returns_404_for_unknown(self, api_client, db, cross_space_pair):
        r = cross_space_pair["client_a"].get(
            "/api/v1/capabilities/does-not-exist",
            params=_params(cross_space_pair),
        )
        assert r.status_code == 404

    def test_reload_capabilities_authenticated_succeeds(self, api_client, db, cross_space_pair):
        r = cross_space_pair["client_a"].post(
            "/api/v1/capabilities/reload",
            params=_params(cross_space_pair),
        )
        assert r.status_code == 200


# ===========================================================================
# Jobs handlers
# ===========================================================================

class TestJobsHandlersAuth:
    def test_list_handlers_unauthenticated_returns_401(self, api_client):
        r = api_client.get("/api/v1/jobs/handlers")
        assert r.status_code == 401

    def test_list_handlers_authenticated_succeeds(self, api_client, db, cross_space_pair):
        r = cross_space_pair["client_a"].get(
            "/api/v1/jobs/handlers",
            params=_params(cross_space_pair),
        )
        assert r.status_code == 200
        assert isinstance(r.json(), list)


# ===========================================================================
# Workspace console runtimes
# ===========================================================================

class TestWorkspaceConsoleRuntimesAuth:
    def test_list_runtimes_unauthenticated_returns_401(self, api_client):
        r = api_client.get("/api/v1/workspace-console/runtimes")
        assert r.status_code == 401

    def test_list_runtimes_authenticated_succeeds(self, api_client, db, cross_space_pair):
        r = cross_space_pair["client_a"].get(
            "/api/v1/workspace-console/runtimes",
            params=_params(cross_space_pair),
        )
        assert r.status_code == 200
        assert "runtimes" in r.json()


# ===========================================================================
# Provider catalog endpoints
# ===========================================================================

class TestProviderCatalogAuth:
    def test_litellm_providers_unauthenticated_returns_401(self, api_client):
        r = api_client.get("/api/v1/providers/litellm-providers")
        assert r.status_code == 401

    def test_provider_catalog_unauthenticated_returns_401(self, api_client):
        r = api_client.get("/api/v1/providers/catalog")
        assert r.status_code == 401

    def test_litellm_providers_authenticated_succeeds(self, api_client, db, cross_space_pair):
        r = cross_space_pair["client_a"].get(
            "/api/v1/providers/litellm-providers",
            params=_params(cross_space_pair),
        )
        assert r.status_code == 200

    def test_provider_catalog_authenticated_succeeds(self, api_client, db, cross_space_pair):
        r = cross_space_pair["client_a"].get(
            "/api/v1/providers/catalog",
            params=_params(cross_space_pair),
        )
        assert r.status_code == 200
        data = r.json()
        assert "id" in data
