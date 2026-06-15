# Credential Storage

The system stores secrets in **two distinct channels**. Do not conflate them.

| Channel | What | Where stored | Doc |
|---|---|---|---|
| **ModelProvider API key** | API keys for in-process LLM calls (OpenAI, Anthropic, …) | AES-256-GCM ciphertext in a DB `Credential` row | this doc |
| **CLI login state** | Claude Code / Codex CLI login profiles for sandboxed runs | files under `instance/secrets/cli-credentials/…`, brokered per run | [modules/credentials.md](../modules/credentials.md) |

This doc covers the **ModelProvider API key** channel — the keys a user configures on the
Providers page, used by the `model_api` runtime adapter, the reflector, and `/providers/chat`.

## At-rest encryption

- **Cipher:** AES-256-GCM (`app/crypto.py`). Plaintext → `(ciphertext, nonce)`, both base64.
- **Master key:** a 32-byte random key in a file on disk at
  `AGENT_SPACE_HOME/secrets/provider_keys.key` (auto-generated on first use, `chmod 0600`).
  **The master key is NOT in the database.** A database-only compromise does not reveal keys —
  the on-disk key file is also required.

## Database layout

The plaintext API key is **never** stored. The encrypted material lives in:

| Table | Field | Holds |
|---|---|---|
| `model_providers` | `credential_id` (FK) | pointer to the **primary** Credential row. `config_json` does **not** contain the key (any `encrypted_key` is popped before persist). |
| `credentials` | `secret_ref` | `model_provider_api_key:v1:<ciphertext_b64>:<nonce_b64>`; `credential_type="api_key"`. |
| `model_provider_credentials` | pool membership | 1→N credential **pool** per provider (Hermes H1): position, enabled, rotation health (`healthy`, `cooldown_until`, `last_failure_class`, request/failure counters). Holds **no secret material** — only FKs to `credentials`. The primary credential is lazily enrolled as the position-0 member. |
| `provider_task_policies` | per-task chains | one ordered provider/model chain per (space, task) for auxiliary tasks (reflector, condenser, …) — Hermes H2. No secret material. |

`secret_ref` scheme is defined in `app/secrets/secret_ref.py`
(`encode_model_provider_api_key_secret_ref` / `resolve_api_key_from_secret_ref`); the
TypeScript side reads/writes the identical format in
`control-plane/src/modules/providers/secretRefCrypto.ts`.

Rotation strategy (`fill_first` | `round_robin` | `least_used` | `random`) and the
provider fallback chain (`fallback_provider_ids`) are provider-level configuration in
`model_providers.config_json` — same pattern as `is_default`.

CLI login state is a distinct credential class: it is **never pooled or rotated**, and
the pool tables never reference it.

## Save flow

Providers page → `POST /api/v1/providers` with `api_key` → `app/providers/service.py`
`_attach_api_key_credential`: `encrypt_to_base64(api_key)` → encode `secret_ref` → create/replace a
`Credential` row → set `ModelProvider.credential_id`.

## Runtime resolution

`app/runtimes/credentials.py::resolve_provider_api_key(db, provider_id)` is the canonical resolver:
loads the `Credential` → `resolve_api_key_from_secret_ref` → AES-GCM decrypt with the on-disk master
key → returns plaintext. The decrypted key is passed to litellm **as a parameter** and is never
written to `os.environ` — per [ADR 0010](../decisions/0010-credential-channel-isolation.md) it cannot
leak into a Claude Code CLI subprocess environment. The shared call site is
`app/providers/invocation.py::complete_text` (it may also accept a pre-resolved key from the execution
service's `ctx.resolved_credentials`).

Under `CONTROL_PLANE_PROVIDERS_CREDENTIALS_AUTHORITY=ts`, Python facades keep
their signatures but resolve through the control plane's internal
service-authenticated ports; the TS store draws keys from the credential pool
with rotation/cooldown state and the same master-key file. Exactly one side
decides credential release at any moment.

## Invariants

- Plaintext key exists only transiently in memory at decrypt time; never in the DB, `config_json`,
  environment variables, or logs (`app/runs/redaction.py` redacts RunStep/artifact content).
- The API never returns the key. `ModelProviderOut` exposes only `has_api_key: bool`; editing supports
  *replacing* the key, not reading it.
- Guarded by `tests/unit/test_anthropic_policy.py` (adapters must not read ambient `ANTHROPIC_API_KEY`)
  and runtime governance redaction tests.

## Current limitation

The master key is a **local-file symmetric key**, not KMS/HSM-managed. Consequences:

- Whoever can read both `AGENT_SPACE_HOME/secrets/provider_keys.key` and the database can decrypt all
  keys — keep the `secrets/` directory and DB backups protected; a backup that includes `secrets/`
  carries decryptable material.
- This is appropriate for a single self-hosted instance. Stronger setups (multi-tenant, compliance)
  would move to envelope encryption with a KMS (KMS-wrapped master key, per-space derived subkeys).
  Not implemented today.
