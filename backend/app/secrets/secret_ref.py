"""Resolve Credential.secret_ref values through approved server-side schemes."""

from __future__ import annotations

_MODEL_PROVIDER_API_KEY_PREFIX = "model_provider_api_key:v1:"


class SecretRefResolutionError(Exception):
    """Raised when a secret_ref cannot be resolved. Message is sanitized."""


def encode_model_provider_api_key_secret_ref(
    encrypted_key_b64: str,
    key_nonce_b64: str,
) -> str:
    """Build a Credential.secret_ref for an encrypted ModelProvider API key."""
    return f"{_MODEL_PROVIDER_API_KEY_PREFIX}{encrypted_key_b64}:{key_nonce_b64}"


def resolve_api_key_from_secret_ref(secret_ref: str) -> str:
    """Decrypt and return an API key from a supported secret_ref scheme."""
    if not secret_ref or not isinstance(secret_ref, str):
        raise SecretRefResolutionError("secret_ref is empty or invalid")

    if secret_ref.startswith(_MODEL_PROVIDER_API_KEY_PREFIX):
        payload = secret_ref[len(_MODEL_PROVIDER_API_KEY_PREFIX):]
        parts = payload.split(":", 1)
        if len(parts) != 2 or not parts[0] or not parts[1]:
            raise SecretRefResolutionError(
                "model_provider_api_key secret_ref payload is malformed"
            )
        encrypted_key, key_nonce = parts
        try:
            from ..crypto import decrypt_from_base64

            api_key = decrypt_from_base64(encrypted_key, key_nonce)
        except Exception as exc:
            raise SecretRefResolutionError(
                f"model_provider_api_key decryption failed: {type(exc).__name__}"
            ) from exc
        if not api_key or not api_key.strip():
            raise SecretRefResolutionError(
                "model_provider_api_key decrypted to an empty value"
            )
        return api_key.strip()

    scheme = secret_ref.split(":", 1)[0]
    raise SecretRefResolutionError(
        f"unsupported secret_ref scheme '{scheme}'"
    )
