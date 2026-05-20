"""Unit tests for model provider validation rules."""

from __future__ import annotations

import pytest

from app.providers.models import ModelProviderCreate
from app.providers.validation import (
    ModelProviderValidationError,
    validate_create_fields,
    validate_provider_type,
)


def test_validate_provider_type_rejects_unknown():
    with pytest.raises(ModelProviderValidationError):
        validate_provider_type("unknown-vendor")


def test_cloud_provider_requires_api_key_on_create():
    with pytest.raises(ModelProviderValidationError):
        validate_create_fields(provider_type="openai", base_url=None, api_key=None)


def test_ollama_requires_base_url_on_create():
    with pytest.raises(ModelProviderValidationError):
        validate_create_fields(provider_type="ollama", base_url=None, api_key=None)


def test_ollama_allows_missing_api_key():
    validate_create_fields(provider_type="ollama", base_url="http://localhost:11434", api_key=None)


def test_model_provider_create_schema_accepts_canonical_fields():
    body = ModelProviderCreate(
        name="Test",
        provider_type="openai",
        api_key="sk-test",
        default_model="gpt-4o-mini",
        available_models=["gpt-4o-mini"],
    )
    assert body.provider_type == "openai"
    assert body.available_models == ["gpt-4o-mini"]
