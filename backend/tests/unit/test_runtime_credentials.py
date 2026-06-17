"""Unit tests for the M4 runtime credential resolver."""
from __future__ import annotations
import uuid

import pytest

from app.models import AgentVersion, ModelProvider
from app.runtimes.credentials import (
    CredentialResolutionError,
    resolve_runtime_credentials,
    resolve_provider_api_key,
    sanitize_runtime_config,
)
from tests.support import factories


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_model_provider_with_key(
    db,
    *,
    space_id: str,
    plaintext_key: str = "sk-test-key-abc123",
) -> ModelProvider:
    """Create a ModelProvider with an API key stored via Credential.secret_ref."""
    from app.crypto import encrypt_to_base64
    from app.models import Credential
    from app.secrets.secret_ref import encode_model_provider_api_key_secret_ref
    from tests.support.factories import _new_id

    encrypted_key, key_nonce = encrypt_to_base64(plaintext_key)
    secret_ref = encode_model_provider_api_key_secret_ref(encrypted_key, key_nonce)
    mp = factories.create_test_model_provider(db, space_id=space_id, commit=False)
    cred = Credential(
        id=_new_id(),
        space_id=space_id,
        name="test-cred",
        credential_type="api_key",
        secret_ref=secret_ref,
        scopes_json=[],
    )
    db.add(cred)
    db.flush()
    mp.credential_id = cred.id
    mp.enabled = True
    db.flush()
    return mp


# ---------------------------------------------------------------------------
# sanitize_runtime_config
# ---------------------------------------------------------------------------

class TestSanitizeRuntimeConfig:
    def test_strips_api_key(self):
        result = sanitize_runtime_config({"api_key": "sk-secret", "model": "gpt-4"})
        assert "api_key" not in result
        assert result["model"] == "gpt-4"

    def test_strips_anthropic_api_key(self):
        result = sanitize_runtime_config({
            "anthropic_api_key": "sk-ant-xxx", "max_tokens": 256
        })
        assert "anthropic_api_key" not in result
        assert result["max_tokens"] == 256

    def test_strips_openai_api_key(self):
        result = sanitize_runtime_config({"openai_api_key": "sk-xxx", "model": "gpt-4"})
        assert "openai_api_key" not in result

    def test_strips_token_field(self):
        result = sanitize_runtime_config({"api_token": "tok", "system_prompt": "be helpful"})
        assert "api_token" not in result
        assert result["system_prompt"] == "be helpful"

    def test_passthrough_non_secret_fields(self):
        cfg = {"model": "claude-3", "max_tokens": 512, "system_prompt": "hello"}
        result = sanitize_runtime_config(cfg)
        assert result == cfg

    def test_empty_config_returns_empty(self):
        assert sanitize_runtime_config({}) == {}

    def test_none_config_returns_empty(self):
        assert sanitize_runtime_config(None) == {}  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# resolve_runtime_credentials — no-credential adapter
# ---------------------------------------------------------------------------

class TestResolveCredentialsNoCredentialAdapter:
    def test_capability_adapter_without_provider_returns_empty(self, db):
        result = resolve_runtime_credentials(db, adapter_type="capability")
        assert result == {}

    def test_no_adapter_type_returns_empty(self, db):
        result = resolve_runtime_credentials(db, adapter_type=None)
        assert result == {}

    def test_no_adapter_type_no_version_returns_empty(self, db):
        result = resolve_runtime_credentials(
            db, adapter_type=None, version=None
        )
        assert result == {}


# ---------------------------------------------------------------------------
# resolve_runtime_credentials — provider-backed path
# ---------------------------------------------------------------------------

class TestResolveCredentialsProviderPath:
    def test_control_plane_authority_resolves_provider_key(self, db, cross_space_pair_db, monkeypatch):
        a = cross_space_pair_db["space_a_id"]
        mp = factories.create_test_model_provider(
            db,
            space_id=a,
            provider_type="openai",
            with_api_key=False,
            enabled=True,
            commit=False,
        )
        calls = []

        def _fake_resolve(*, space_id: str, provider_id: str) -> str:
            calls.append((space_id, provider_id))
            return "sk-from-ts"

        monkeypatch.setattr(
            "app.providers.credentials.resolve_model_provider_api_key_via_control_plane",
            _fake_resolve,
        )

        result = resolve_runtime_credentials(
            db,
            adapter_type="model_api",
            run_model_provider_id=mp.id,
        )

        assert result == {"api_key": "sk-from-ts"}
        assert calls == [(a, mp.id)]

    def test_resolves_from_agent_version_model_provider_id(
        self, db, cross_space_pair_db, monkeypatch
    ):
        a = cross_space_pair_db["space_a_id"]
        ua = cross_space_pair_db["user_a"]
        mp = factories.create_test_model_provider(db, space_id=a, enabled=True, commit=False)
        agent = factories.create_test_agent(
            db, space_id=a, owner_user_id=ua.id, commit=False
        )
        version = db.query(AgentVersion).filter(
            AgentVersion.id == agent.current_version_id
        ).one()
        version.model_provider_id = mp.id
        db.flush()
        calls = []

        def _fake_resolve(*, space_id: str, provider_id: str) -> str:
            calls.append((space_id, provider_id))
            return "sk-from-ts-version"

        monkeypatch.setattr(
            "app.providers.credentials.resolve_model_provider_api_key_via_control_plane",
            _fake_resolve,
        )

        result = resolve_runtime_credentials(
            db, adapter_type="model_api", version=version
        )
        assert result.get("api_key") == "sk-from-ts-version"
        assert calls == [(a, mp.id)]

    def test_run_model_provider_id_takes_priority_over_version(
        self, db, cross_space_pair_db, monkeypatch
    ):
        a = cross_space_pair_db["space_a_id"]
        ua = cross_space_pair_db["user_a"]
        key_run = "sk-run-provider-key"
        key_ver = "sk-version-provider-key"
        mp_run = factories.create_test_model_provider(db, space_id=a, enabled=True, commit=False)
        mp_ver = factories.create_test_model_provider(db, space_id=a, enabled=True, commit=False)
        agent = factories.create_test_agent(
            db, space_id=a, owner_user_id=ua.id, commit=False
        )
        version = db.query(AgentVersion).filter(
            AgentVersion.id == agent.current_version_id
        ).one()
        version.model_provider_id = mp_ver.id
        db.flush()
        calls = []

        def _fake_resolve(*, space_id: str, provider_id: str) -> str:
            calls.append((space_id, provider_id))
            return {mp_run.id: key_run, mp_ver.id: key_ver}[provider_id]

        monkeypatch.setattr(
            "app.providers.credentials.resolve_model_provider_api_key_via_control_plane",
            _fake_resolve,
        )

        result = resolve_runtime_credentials(
            db,
            adapter_type="model_api",
            version=version,
            run_model_provider_id=mp_run.id,
        )
        assert result.get("api_key") == key_run
        assert calls == [(a, mp_run.id)]

    def test_missing_provider_raises_credential_resolution_error(self, db):
        # Test via resolve_provider_api_key — no FK constraint on the function call
        with pytest.raises(CredentialResolutionError) as exc_info:
            resolve_provider_api_key(db, str(uuid.uuid4()))
        assert "not found" in str(exc_info.value).lower()
        # The error message must not contain a raw API key
        assert "sk-" not in str(exc_info.value)

    def test_control_plane_error_raises_credential_resolution_error(
        self, db, cross_space_pair_db, monkeypatch
    ):
        from app.providers.control_plane_client import ControlPlaneProviderError

        a = cross_space_pair_db["space_a_id"]
        mp = factories.create_test_model_provider(db, space_id=a, enabled=True, commit=False)
        db.flush()

        def _fake_resolve(*, space_id: str, provider_id: str) -> str:
            raise ControlPlaneProviderError("Provider disabled")

        monkeypatch.setattr(
            "app.providers.credentials.resolve_model_provider_api_key_via_control_plane",
            _fake_resolve,
        )

        with pytest.raises(CredentialResolutionError) as exc_info:
            resolve_runtime_credentials(db, adapter_type="model_api", run_model_provider_id=mp.id)
        assert "disabled" in str(exc_info.value).lower()

    def test_control_plane_no_credential_error_raises(self, db, cross_space_pair_db, monkeypatch):
        from app.providers.control_plane_client import ControlPlaneProviderError

        a = cross_space_pair_db["space_a_id"]
        mp = factories.create_test_model_provider(db, space_id=a, enabled=True, commit=False)
        db.flush()

        def _fake_resolve(*, space_id: str, provider_id: str) -> str:
            raise ControlPlaneProviderError("No credential configured")

        monkeypatch.setattr(
            "app.providers.credentials.resolve_model_provider_api_key_via_control_plane",
            _fake_resolve,
        )

        with pytest.raises(CredentialResolutionError) as exc_info:
            resolve_runtime_credentials(db, adapter_type="model_api", run_model_provider_id=mp.id)
        assert "no credential configured" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# resolve_provider_api_key
# ---------------------------------------------------------------------------

class TestResolveProviderApiKey:
    def test_delegates_to_control_plane(self, db, cross_space_pair_db, monkeypatch):
        a = cross_space_pair_db["space_a_id"]
        mp = factories.create_test_model_provider(db, space_id=a, enabled=True, commit=False)
        db.flush()
        calls = []

        def _fake_resolve(*, space_id: str, provider_id: str) -> str:
            calls.append((space_id, provider_id))
            return "sk-from-ts-direct"

        monkeypatch.setattr(
            "app.providers.credentials.resolve_model_provider_api_key_via_control_plane",
            _fake_resolve,
        )

        result = resolve_provider_api_key(db, mp.id)
        assert result == "sk-from-ts-direct"
        assert calls == [(a, mp.id)]

    def test_raises_for_missing_provider(self, db):
        with pytest.raises(CredentialResolutionError):
            resolve_provider_api_key(db, str(uuid.uuid4()))


class TestProviderCredentialSecretRef:
    def test_provider_create_stores_credential_secret_ref(
        self, db, cross_space_pair_db, tmp_path, monkeypatch
    ):
        from app.config import paths
        from app.models import Credential, ModelProvider
        from app.providers.models import ModelProviderCreate
        from app.providers.service import ModelService
        import app.crypto as crypto

        monkeypatch.setattr(crypto, "_KEY", None)
        home = tmp_path / "crypto_home_cred"
        monkeypatch.setattr(paths, "home", home)
        paths.init_dirs()

        a = cross_space_pair_db["space_a_id"]
        out = ModelService().create_config(
            db,
            a,
            ModelProviderCreate(
                name="Cred Prov",
                provider_type="openai",
                api_key="sk-cred-test-key",
                available_models=["gpt-4o-mini"],
                default_model="gpt-4o-mini",
            ),
        )
        assert out.has_api_key is True

        row = db.query(ModelProvider).filter(ModelProvider.id == out.id).one()
        assert row.credential_id is not None
        cred = db.query(Credential).filter(Credential.id == row.credential_id).one()
        assert "sk-cred-test-key" not in cred.secret_ref
        assert cred.secret_ref.startswith("model_provider_api_key:v1:")

        # Runtime credential resolution is now owned by the TS control-plane
        # provider store; this test only asserts Python create still writes a
        # non-plaintext secret_ref for migration-period compatibility.

    def test_control_plane_resolution_error_is_wrapped(self, db, cross_space_pair_db, monkeypatch):
        from app.providers.control_plane_client import ControlPlaneProviderError

        a = cross_space_pair_db["space_a_id"]
        cred = factories.create_test_credential_stub(
            db,
            space_id=a,
            secret_ref="model_provider_api_key:v1:bad",
            commit=False,
        )
        mp = factories.create_test_model_provider(db, space_id=a, commit=False)
        mp.credential_id = cred.id
        mp.config_json = {}
        db.flush()

        def _fake_resolve(*, space_id: str, provider_id: str) -> str:
            raise ControlPlaneProviderError("Credential could not be resolved")

        monkeypatch.setattr(
            "app.providers.credentials.resolve_model_provider_api_key_via_control_plane",
            _fake_resolve,
        )

        with pytest.raises(CredentialResolutionError) as exc_info:
            resolve_provider_api_key(db, mp.id)
        assert "could not be resolved" in str(exc_info.value).lower()
        assert "sk-" not in str(exc_info.value)


# ---------------------------------------------------------------------------
# Adapter metadata declarations
# ---------------------------------------------------------------------------

class TestAdapterMetadataDeclarations:
    def test_capability_does_not_require_credentials(self):
        from app.runtimes.adapters.capability import CapabilityRuntimeAdapter
        assert CapabilityRuntimeAdapter.requires_credentials is False
        assert CapabilityRuntimeAdapter.uses_model_config is False
        assert CapabilityRuntimeAdapter.model_config_behavior == "not_applicable"
        assert CapabilityRuntimeAdapter.requires_file_access is False
        assert CapabilityRuntimeAdapter.supports_sandboxed_execution is False
