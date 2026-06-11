"""Public facade for the ``providers`` module — the in-process model channel.

Re-exports the symbols other modules import from ``providers`` today. Per ADR
0010 ``providers.invocation`` is *the* sanctioned in-process model channel
(credential-channel isolation: no Anthropic key in a CLI subprocess env; the
API channel may serve any provider). Callers should depend on ``app.providers``
rather than reaching into ``providers.invocation`` / ``providers.service``.

Eager re-export is safe here: ``providers`` submodules own provider credential
resolution and do not import ``runtimes`` or run execution internals.
"""

from __future__ import annotations

from .credentials import CredentialResolutionError, resolve_provider_api_key
from .invocation import (
    CompletionResult,
    ProviderUnavailableError,
    UnsupportedProviderError,
    complete_text,
)
from .service import ModelService, _mp_is_default

__all__ = [
    "CompletionResult",
    "CredentialResolutionError",
    "ProviderUnavailableError",
    "UnsupportedProviderError",
    "complete_text",
    "resolve_provider_api_key",
    "ModelService",
    "_mp_is_default",
]
