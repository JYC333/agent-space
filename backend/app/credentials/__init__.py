"""Public facade for the ``credentials`` module.

Re-exports the CLI credential broker entrypoints other modules import today
(``runs`` and ``runtimes``). ``CredentialBroker`` is the single intended
entrypoint (B45-B49). New callers should depend on ``app.credentials`` rather
than ``credentials.broker``.

**Note:** existing call sites that obtain ``CredentialBroker`` via a *deferred*
(function-level) import were intentionally **not** migrated to this facade. The
test suite monkeypatches ``app.credentials.broker.CredentialBroker`` directly,
and a deferred import resolved through the facade would read the unpatched
re-export — so collapsing those imports is not behavior-preserving. They remain
``from app.credentials.broker import CredentialBroker`` on purpose.
"""

from __future__ import annotations

from .broker import CredentialBroker, CredentialGrant

__all__ = ["CredentialBroker", "CredentialGrant"]
