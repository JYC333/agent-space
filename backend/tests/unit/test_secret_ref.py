"""Unit tests for Credential.secret_ref resolution."""

from __future__ import annotations

import pytest

import app.crypto as crypto
from app.crypto import encrypt_to_base64
from app.secrets.secret_ref import (
    SecretRefResolutionError,
    encode_model_provider_api_key_secret_ref,
    resolve_api_key_from_secret_ref,
)


def test_encode_and_resolve_model_provider_api_key():
    plaintext = "sk-secret-ref-test"
    ek, kn = encrypt_to_base64(plaintext)
    ref = encode_model_provider_api_key_secret_ref(ek, kn)
    assert plaintext not in ref
    assert resolve_api_key_from_secret_ref(ref) == plaintext


def test_resolves_model_provider_secret_ref_aes_gcm_fixture(monkeypatch):
    """Pins the ciphertext||tag layout for TS/Python secret_ref compatibility."""
    monkeypatch.setattr(crypto, "_KEY", bytes(range(32)))
    ref = (
        "model_provider_api_key:v1:"
        "oVGLAwn7aGtuUTCrpzWXlr05jeiq6waXBB8NaziyEau+8NEkDLy0ww==:"
        "ICEiIyQlJicoKSor"
    )
    assert resolve_api_key_from_secret_ref(ref) == "sk-secret-ref-compat-key"


def test_unsupported_secret_ref_raises():
    with pytest.raises(SecretRefResolutionError) as exc_info:
        resolve_api_key_from_secret_ref("stub://no-secret")
    assert "unsupported" in str(exc_info.value).lower()


def test_malformed_model_provider_secret_ref_raises():
    with pytest.raises(SecretRefResolutionError):
        resolve_api_key_from_secret_ref("model_provider_api_key:v1:only-one-part")
