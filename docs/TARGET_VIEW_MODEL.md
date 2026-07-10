# Content Ownership, Scope, And Visibility

Persisted content authorization is modeled with independent ownership, scope,
visibility, and disclosure dimensions.

## Owner

`owner_user_id` is the user who owns the content. Provenance fields such as
`created_by_user_id`, `instructed_by_user_id`, and `created_by_run_id` do not
replace ownership. Private and selected-user content requires an owner.

## Scope

Every resource belongs to one Space through `space_id`. A resource may also be
scoped to a Workspace and/or Project. Scope is checked after active Space
membership and before visibility. Workspace or Project placement never widens a
resource to the entire Space.

## Visibility

Visibility has exactly three values:

- `private`: owner base access; grants are never consulted
- `space_shared`: scope-eligible active members of the resource's Space
- `selected_users`: owner plus active same-Space users in
  `content_access_grants`

Space owner/admin roles do not automatically read content. The sole exception
is the Space's creation-time immutable oversight mode, which can widen reads for
an active owner/admin within that same Space but never widens writes,
publication, grant management, or cross-Space access. `restricted` and related
values are sensitivity levels, not visibility.

## Disclosure

`access_level` is `full` or `summary`. It controls how much visible content a
non-owner receives and is independent from visibility and scope. The effective
level is widest-wins: `space_shared` grants can upgrade a named reader from
summary to full, and a `selected_users` grant's level is authoritative for that
reader. Grants never apply to `private` rows.

## Unified Enforcement

The static resource registry, policy evaluator, SQL predicate builder, detail
assertions, policy update service, and grants API live under
`server/src/modules/access/` and `server/src/modules/contentAccess/`. Lists,
details, search, retrieval, context injection, and exports use the canonical
read rule. Mutations add their own ownership/action gates; read-only oversight
is never mutation authority.

## Cross-Space Transfer

General content is never read directly across Spaces and grants cannot cross a
Space boundary. Explicit target-Space publication stores an immutable snapshot;
import creates an independent private copy with a new owner and records
publication/version provenance. See `docs/CONTENT_PUBLICATIONS.md`.

Personal Memory Grant remains a separate, run-scoped reasoning-context exception
and does not change content visibility.
