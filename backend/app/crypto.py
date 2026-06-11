"""
AES-256-GCM encryption for provider API keys at rest.

Key material is stored in AGENT_SPACE_HOME/secrets/provider_keys.key.
A new key is generated automatically on first use.
"""

import os
import secrets
import base64
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .config import paths


def _load_or_create_key() -> bytes:
    """Load the master key from disk, creating it if absent."""
    key_path = paths.provider_keys_key
    if key_path.exists():
        return key_path.read_bytes()
    key = os.urandom(32)
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.write_bytes(key)
    key_path.chmod(0o600)
    return key


_KEY: bytes | None = None


def _get_key() -> bytes:
    global _KEY
    if _KEY is None:
        _KEY = _load_or_create_key()
    return _KEY


def encrypt(plaintext: str) -> tuple[bytes, bytes]:
    """Encrypt plaintext with AES-256-GCM. Returns (ciphertext, nonce)."""
    nonce = secrets.token_bytes(12)
    aesgcm = AESGCM(_get_key())
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
    return ciphertext, nonce


def decrypt(ciphertext: bytes, nonce: bytes) -> str:
    """Decrypt ciphertext using AES-256-GCM with the given nonce."""
    aesgcm = AESGCM(_get_key())
    return aesgcm.decrypt(nonce, ciphertext, None).decode("utf-8")


def encrypt_to_base64(plaintext: str) -> tuple[str, str]:
    """Encrypt and return base64-encoded ciphertext and nonce for string storage."""
    ciphertext, nonce = encrypt(plaintext)
    return base64.b64encode(ciphertext).decode("ascii"), base64.b64encode(nonce).decode("ascii")


def decrypt_from_base64(ciphertext_b64: str, nonce_b64: str) -> str:
    """Decode base64-encoded ciphertext and nonce, then decrypt."""
    ciphertext = base64.b64decode(ciphertext_b64.encode("ascii"))
    nonce = base64.b64decode(nonce_b64.encode("ascii"))
    return decrypt(ciphertext, nonce)