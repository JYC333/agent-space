"""Unit tests for the M4 runtime credential resolver."""
from __future__ import annotations

import pytest

from app.models import AgentVersion, ModelProvider, RuntimeAdapter
from app.runtimes.credentials import (
    CredentialResolutionError,
    assert_no_inline_secret_config,
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
# assert_no_inline_secret_config
# ---------------------------------------------------------------------------

class TestAssertNoInlineSecretConfig:
    def test_raises_on_api_key_in_config(self, db, cross_space_pair):
        a = cross_space_pair["space_a_id"]
        ra = factories.create_test_runtime_adapter(db, space_id=a, commit=False)
        ra.config_json = {"api_key": "sk-raw-secret", "model": "gpt-4"}
        db.flush()

        with pytest.raises(CredentialResolutionError) as exc_info:
            assert_no_inline_secret_config(ra)
        assert "inline secret" in str(exc_info.value).lower()
        assert "api_key" in str(exc_info.value)

    def test_raises_on_secret_key_in_config(self, db, cross_space_pair):
        a = cross_space_pair["space_a_id"]
        ra = factories.create_test_runtime_adapter(db, space_id=a, commit=False)
        ra.config_json = {"secret_key": "raw-secret"}
        db.flush()

        with pytest.raises(CredentialResolutionError):
            assert_no_inline_secret_config(ra)

    def test_passes_for_clean_config(self, db, cross_space_pair):
        a = cross_space_pair["space_a_id"]
        ra = factories.create_test_runtime_adapter(db, space_id=a, commit=False)
        ra.config_json = {"model": "claude-3", "max_tokens": 256}
        db.flush()
        # Must not raise
        assert_no_inline_secret_config(ra)

    def test_passes_for_empty_config(self, db, cross_space_pair):
        a = cross_space_pair["space_a_id"]
        ra = factories.create_test_runtime_adapter(db, space_id=a, commit=False)
        ra.config_json = {}
        db.flush()
        assert_no_inline_secret_config(ra)


# ---------------------------------------------------------------------------
# resolve_runtime_credentials — echo adapter (no credentials)
# ---------------------------------------------------------------------------

class TestResolveCredentialsEchoAdapter:
    def test_echo_adapter_without_provider_returns_empty(self, db, cross_space_pair):
        a = cross_space_pair["space_a_id"]
        ra = factories.create_test_runtime_adapter(
            db, space_id=a, adapter_type="echo", commit=False
        )
        db.flush()
        result = resolve_runtime_credentials(db, runtime_adapter_row=ra)
        assert result == {}

    def test_no_adapter_row_returns_empty(self, db):
        result = resolve_runtime_credentials(db, runtime_adapter_row=None)
        assert result == {}

    def test_no_adapter_no_version_returns_empty(self, db):
        result = resolve_runtime_credentials(
            db, runtime_adapter_row=None, version=None
        )
        assert result == {}


# ---------------------------------------------------------------------------
# resolve_runtime_credentials — provider-backed path
# ---------------------------------------------------------------------------

class TestResolveCredentialsProviderPath:
    def test_resolves_from_runtime_adapter_provider_id(self, db, cross_space_pair):
        a = cross_space_pair["space_a_id"]
        plaintext = "sk-test-provider-key-xyz"
        mp = _create_model_provider_with_key(db, space_id=a, plaintext_key=plaintext)
        ra = factories.create_test_runtime_adapter(
            db, space_id=a, adapter_type="echo",
            provider_id=mp.id, commit=False,
        )
        db.flush()

        result = resolve_runtime_credentials(db, runtime_adapter_row=ra)
        assert result.get("api_key") == plaintext

    def test_resolves_from_agent_version_model_provider_id(
        self, db, cross_space_pair
    ):
        a = cross_space_pair["space_a_id"]
        ua = cross_space_pair["user_a"]
        plaintext = "sk-test-version-key-abc"
        mp = _create_model_provider_with_key(db, space_id=a, plaintext_key=plaintext)
        agent = factories.create_test_agent(
            db, space_id=a, owner_user_id=ua.id, commit=False
        )
        version = db.query(AgentVersion).filter(
            AgentVersion.id == agent.current_version_id
        ).one()
        version.model_provider_id = mp.id
        db.flush()

        # No RuntimeAdapter row; version provides the provider link
        result = resolve_runtime_credentials(
            db, runtime_adapter_row=None, version=version
        )
        assert result.get("api_key") == plaintext

    def test_runtime_adapter_provider_takes_priority_over_version_provider(
        self, db, cross_space_pair
    ):
        a = cross_space_pair["space_a_id"]
        ua = cross_space_pair["user_a"]
        key_ra = "sk-adapter-provider-key"
        key_ver = "sk-version-provider-key"
        mp_ra = _create_model_provider_with_key(db, space_id=a, plaintext_key=key_ra)
        mp_ver = _create_model_provider_with_key(db, space_id=a, plaintext_key=key_ver)
        agent = factories.create_test_agent(
            db, space_id=a, owner_user_id=ua.id, commit=False
        )
        version = db.query(AgentVersion).filter(
            AgentVersion.id == agent.current_version_id
        ).one()
        version.model_provider_id = mp_ver.id
        ra = factories.create_test_runtime_adapter(
            db, space_id=a, adapter_type="echo",
            provider_id=mp_ra.id, commit=False,
        )
        db.flush()

        result = resolve_runtime_credentials(db, runtime_adapter_row=ra, version=version)
        # RuntimeAdapter.provider_id takes priority
        assert result.get("api_key") == key_ra

    def test_run_model_provider_id_takes_priority_over_adapter_and_version(
        self, db, cross_space_pair
    ):
        a = cross_space_pair["space_a_id"]
        ua = cross_space_pair["user_a"]
        key_run = "sk-run-provider-key"
        key_ra = "sk-adapter-provider-key"
        key_ver = "sk-version-provider-key"
        mp_run = _create_model_provider_with_key(db, space_id=a, plaintext_key=key_run)
        mp_ra = _create_model_provider_with_key(db, space_id=a, plaintext_key=key_ra)
        mp_ver = _create_model_provider_with_key(db, space_id=a, plaintext_key=key_ver)
        agent = factories.create_test_agent(
            db, space_id=a, owner_user_id=ua.id, commit=False
        )
        version = db.query(AgentVersion).filter(
            AgentVersion.id == agent.current_version_id
        ).one()
        version.model_provider_id = mp_ver.id
        ra = factories.create_test_runtime_adapter(
            db, space_id=a, adapter_type="echo",
            provider_id=mp_ra.id, commit=False,
        )
        db.flush()

        result = resolve_runtime_credentials(
            db,
            runtime_adapter_row=ra,
            version=version,
            run_model_provider_id=mp_run.id,
        )
        assert result.get("api_key") == key_run

    def test_missing_provider_raises_credential_resolution_error(self, db):
        from ulid import ULID
        # Test via resolve_provider_api_key — no FK constraint on the function call
        with pytest.raises(CredentialResolutionError) as exc_info:
            resolve_provider_api_key(db, str(ULID()))
        assert "not found" in str(exc_info.value).lower()
        # The error message must not contain a raw API key
        assert "sk-" not in str(exc_info.value)

    def test_disabled_provider_raises_credential_resolution_error(
        self, db, cross_space_pair
    ):
        a = cross_space_pair["space_a_id"]
        plaintext = "sk-disabled-provider-key"
        mp = _create_model_provider_with_key(db, space_id=a, plaintext_key=plaintext)
        mp.enabled = False
        db.flush()
        ra = factories.create_test_runtime_adapter(
            db, space_id=a, adapter_type="echo",
            provider_id=mp.id, commit=False,
        )
        db.flush()

        with pytest.raises(CredentialResolutionError) as exc_info:
            resolve_runtime_credentials(db, runtime_adapter_row=ra)
        assert "disabled" in str(exc_info.value).lower()

    def test_provider_with_no_credential_raises(self, db, cross_space_pair):
        a = cross_space_pair["space_a_id"]
        mp = factories.create_test_model_provider(db, space_id=a, commit=False)
        mp.credential_id = None
        mp.config_json = {}
        mp.enabled = True
        db.flush()
        ra = factories.create_test_runtime_adapter(
            db, space_id=a, adapter_type="echo",
            provider_id=mp.id, commit=False,
        )
        db.flush()

        with pytest.raises(CredentialResolutionError) as exc_info:
            resolve_runtime_credentials(db, runtime_adapter_row=ra)
        assert "no credential configured" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# resolve_provider_api_key
# ---------------------------------------------------------------------------

class TestResolveProviderApiKey:
    def test_decrypts_and_returns_key(self, db, cross_space_pair):
        a = cross_space_pair["space_a_id"]
        plaintext = "sk-test-direct-key-789"
        mp = _create_model_provider_with_key(db, space_id=a, plaintext_key=plaintext)
        db.flush()

        result = resolve_provider_api_key(db, mp.id)
        assert result == plaintext

    def test_raises_for_missing_provider(self, db):
        from ulid import ULID
        with pytest.raises(CredentialResolutionError):
            resolve_provider_api_key(db, str(ULID()))


class TestProviderCredentialSecretRef:
    def test_provider_create_stores_credential_secret_ref(
        self, db, cross_space_pair, tmp_path, monkeypatch
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

        a = cross_space_pair["space_a_id"]
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

        resolved = resolve_provider_api_key(db, row.id)
        assert resolved == "sk-cred-test-key"

    def test_broken_secret_ref_fails_resolution(self, db, cross_space_pair):
        a = cross_space_pair["space_a_id"]
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

        with pytest.raises(CredentialResolutionError) as exc_info:
            resolve_provider_api_key(db, mp.id)
        assert "could not be resolved" in str(exc_info.value).lower()
        assert "sk-" not in str(exc_info.value)


# ---------------------------------------------------------------------------
# Adapter metadata declarations
# ---------------------------------------------------------------------------

class TestAdapterMetadataDeclarations:
    def test_echo_does_not_require_credentials(self):
        from app.runtimes.adapters.echo import EchoRuntimeAdapter
        assert EchoRuntimeAdapter.requires_credentials is False
        assert EchoRuntimeAdapter.uses_model_config is False
        assert EchoRuntimeAdapter.model_config_behavior == "not_applicable"
        assert EchoRuntimeAdapter.requires_file_access is False
        assert EchoRuntimeAdapter.supports_sandboxed_execution is False

    def test_anthropic_direct_api_adapters_not_in_registry(self):
        """Guard test: anthropic_messages and anthropic_api must not appear in the canonical registry.

        Product policy: Anthropic/Claude execution goes through CLI integrations only.
        This test prevents reintroduction.
        """
        from app.runtimes.registry import is_adapter_type_implemented
        assert not is_adapter_type_implemented("anthropic_messages"), (
            "anthropic_messages must not be in canonical runtime registry (policy: CLI-only)"
        )
        assert not is_adapter_type_implemented("anthropic_api"), (
            "anthropic_api must not be in canonical runtime registry (policy: CLI-only)"
        )

    def test_anthropic_messages_file_deleted(self):
        """Guard test: anthropic_messages.py must not exist in app.runtimes.adapters."""
        import importlib
        import importlib.util
        spec = importlib.util.find_spec("app.runtimes.adapters.anthropic_messages")
        assert spec is None, (
            "app.runtimes.adapters.anthropic_messages must not exist "
            "(policy: Anthropic direct API adapter is not supported)"
        )
