# Finance Ledger Plugin Plan

Status: active planning document.

This is a target-state implementation plan, not current-state architecture
documentation. Current-state docs remain under `.agent/architecture/` and
`.agent/modules/`. This plan records how to implement the Finance Ledger
official optional module while preserving the existing plugin, proposal,
policy, artifact, and space-isolation boundaries.

## Goal

Build the foundation for an asset-management / finance-ledger plugin whose
ledger core is compatible with Beancount v3 concepts, while keeping PostgreSQL
as the runtime source of truth.

This work is not a full investment system. It must not connect to realtime
market data, broker APIs, portfolio analytics, or yield/performance dashboards.
Investment-specific features will be a separate plugin that reads ledger
accounts, commodities, positions, and prices through explicit boundaries.

## Reference Inputs

- User product requirements for the asset-management / Finance Ledger plugin.
- User Beancount Core Parity supplement.
- `.agent/BOUNDARIES.md`, especially B4, B5, B10, B24, B33-B36, B51-B53.
- `.agent/decisions/0007-plugin-module-architecture.md`.
- `.agent/architecture/OFFICIAL_OPTIONAL_MODULES.md`.
- `.agent/architecture/MODULE_DEVELOPMENT_GUIDE.md`.
- Current `diary` official plugin implementation:
  - `plugins/official/diary/`
  - `server/src/modules/plugins/official/diary.ts`
  - `apps/web/src/plugins/diary/DiaryPageAdapter.tsx`
  - `apps/web/src/modules/registry.ts`
- Beancount upstream audit target:
  - `https://github.com/beancount/beancount`
  - v3 branch core files listed in the user supplement.

Important licensing note: Beancount is GPLv2 only. Use upstream behavior,
tests, and public semantics as references, but do not copy source code into
this repository unless the project explicitly accepts the resulting license
obligations. The implementation should be TypeScript-native.

## Implementation Note

The feature should be an official optional module, not a core `ServerModule`.

Recommended identities:

- Official plugin id: `finance_ledger`.
- Plugin package: `plugins/official/finance_ledger/`.
- Frontend module id: `finance`.
- Frontend path: `/finance`.
- API prefix: `/api/v1/finance`.
- Scope: `space`.
- Category: `household`.
- Static defaults: `default_enabled: false`, `default_visible: true`.

Why `space` scope: finance books are space-owned business data. Every finance
domain row must include `space_id`; most rows also include `book_id`. The plugin
guard must check enablement for the active space, and all repositories must
filter by both `space_id` and `book_id` where applicable.

Current repo facts to follow:

- Database schema is explicit SQL migrations, not Prisma/Drizzle.
- Plugin-owned domain tables belong in
  `plugins/official/finance_ledger/migrations/`, not the core baseline.
- Plugin runtime routes are registered through `PluginHost`, not through
  `server/src/gateway/routeRegistry.ts`.
- Plugin routes must call `ctx.http.pluginGuard(request, reply)` before reading
  or mutating finance data.
- Plugin frontend source lives under
  `plugins/official/finance_ledger/web/src/` and must not import
  `apps/web/src` directly.
- `apps/web/src/plugins/finance_ledger/` should be an app-owned adapter that
  injects the API client, navigation, and plugin-state hook.
- `apps/web/src/modules/registry.ts` remains the only frontend module registry.

## Non-Goals

- No realtime price or quote service.
- No broker synchronization.
- No Fava clone or advanced reporting UI.
- No portfolio performance, IRR, time-weighted return, tax-lot dashboard, or
  investment recommendation engine.
- No arbitrary Python plugin execution.
- No Python Beancount runtime dependency in the server path.
- No second ledger maintained by a future investment plugin.

## Target Architecture

### Plugin Descriptor

Add `server/src/modules/plugins/official/financeLedger.ts` with a serializable
`OfficialPluginDescriptor`:

- `id: "finance_ledger"`
- `name: "Finance Ledger"`
- `scope: "space"`
- `frontend_entries` with module id `finance`, path `/finance`, icon such as
  `wallet-cards` or `landmark`, section `knowledge` or `capture` depending on
  product placement.
- `backend_feature_ids`: `finance_books`, `finance_directives`,
  `finance_import_export`.
- `permissions`:
  - `creates_activity: false` for direct manual ledger editing.
  - `can_propose_memory: false`.
  - `can_contribute_context: "opt_in"` only if future context summaries are
    added.
  - `uses_ai: false` for this base implementation.
  - `uses_scheduler: false` for this base implementation.
- `settings_defaults`:
  - `default_operating_currency: "USD"` or unset until book creation.
  - `proposal_required_for_imports: true`.
  - `include_in_context: false`.
  - `allow_document_paths: false`.

Register it in `server/src/modules/plugins/registry.ts` next to `diary`.

### Plugin Package

Create this package shape:

```text
plugins/official/finance_ledger/
  plugin.json
  migrations/
    0001_create_finance_ledger_tables.sql
  server/
    tsconfig.json
    src/
      index.ts
      manifest.ts
      schema.ts
      routes.ts
      proposalAppliers.ts
      domain/
        amount.ts
        booking.ts
        directives.ts
        inventory.ts
        repository.ts
        service.ts
        validation.ts
      beancount/
        tokenizer.ts
        importer.ts
        exporter.ts
        formatter.ts
        sort.ts
  web/
    src/
      FinancePage.tsx
      host.ts
```

The plugin runtime should export `financeLedgerPlugin: AgentSpacePlugin`.
`activate(ctx)` should synchronously register routes and proposal appliers, then
return `{ activated: true }`.

### Frontend Adapter

Add:

```text
apps/web/src/plugins/finance_ledger/FinancePageAdapter.tsx
```

The adapter should inject:

- `financeApi` from `apps/web/src/api/client.ts`.
- `SpaceLink`.
- `useEffectivePlugins()`.

Then add a lazy `official_plugin` entry in `apps/web/src/modules/registry.ts`:

- `id: "finance"`
- `pluginId: "finance_ledger"`
- `source: "official_plugin"`
- `enabled: false`
- `visible: true`
- `perspectiveType: "space-scoped"`
- `component: lazy(() => import("../plugins/finance_ledger/FinancePageAdapter"))`

## Beancount Core Parity Strategy

The Beancount supplement requests core parity, not a transaction-only MVP. Treat
the implementation as a ledger engine with a full directive stream. If a concept
is not executable in the first code slice, it still needs storage, import/export
representation, validation status, and an explicit `deferred` entry in the
parity matrix.

### Phase 0: Upstream Audit

Before implementation, audit the Beancount v3 branch and create:

```text
docs/finance/beancount-core-parity-matrix.md
```

The audit must cover at least:

- `beancount/core/data.py`
- `beancount/parser/grammar.y`
- `beancount/parser/options.py`
- `beancount/loader.py`
- `beancount/core/amount.py`
- `beancount/core/position.py`
- `beancount/core/inventory.py`
- `beancount/ops/validation.py`
- `beancount/parser/printer.py`

The matrix columns should be:

| Beancount concept | Source file | Agent Space domain model | PostgreSQL storage | API/export support | Tests | Status |
|---|---|---|---|---|---|---|

Use statuses:

- `implemented`
- `partial`
- `stored_export_only`
- `deferred`
- `not_applicable`

Do not omit unsupported concepts.

### Phase 1: Core Value Objects

Implement immutable TypeScript value objects:

- `Amount(number, currency)`
- `Cost(number, currency, date, label)`
- `CostSpec(numberPer, numberTotal, currency, date, label, merge)`
- `Position(units, cost?)`
- `Inventory`
- `Booking`

Money and quantities must not use JS `number`. Use PostgreSQL `numeric` at rest
and represent decimal values in TypeScript as canonical strings plus scale, with
deterministic string/BigInt arithmetic for add, negate, compare, and zero
checks. Adding a decimal library can be considered, but it should be a deliberate
dependency decision rather than incidental parsing through `number`.

Preserve original input scale where relevant:

- `amount_text`
- `amount_scale`
- `cost_number_text`
- `price_number_text`

The exporter should prefer original text when semantically unchanged.

### Phase 2: Schema For Full Directive Stream

Create plugin-owned SQL migration:

```text
plugins/official/finance_ledger/migrations/0001_create_finance_ledger_tables.sql
```

Required tables:

- `finance_books`
- `finance_ledger_options`
- `finance_directives`
- `finance_accounts`
- `finance_account_groups`
- `finance_commodities`
- `finance_transactions`
- `finance_postings`
- `finance_posting_metadata`
- `finance_directive_metadata`
- `finance_prices`
- `finance_balance_assertions`
- `finance_pad_directives`
- `finance_notes`
- `finance_events`
- `finance_queries`
- `finance_documents`
- `finance_custom_directives`
- `finance_custom_directive_values`
- `finance_includes`
- `finance_plugin_directives`
- `finance_tag_stack_events`
- `finance_meta_stack_events`
- `finance_import_sources`
- `finance_exports`

Schema rules:

- Every table has `space_id`; every ledger-domain child table also has
  `book_id`.
- Primary keys are UUID strings, following repository convention.
- `finance_directives` is the durable directive stream:
  - `directive_type`
  - `date`
  - `sequence`
  - `status`: `draft`, `proposed`, `posted`, `voided`
  - `source_activity_id`
  - `proposal_id`
  - `import_source_id`
  - source location: `source_filename`, `source_lineno`, `source_hash`
  - `metadata_json`
  - `created_by_user_id`
  - timestamps
- Directive-specific tables use `directive_id` as a one-to-one key where
  appropriate.
- `finance_postings` stores incomplete postings by allowing `amount_numeric`
  and `commodity_id` to be null while preserving raw parsed fields.
- Tags and links can be normalized into directive/posting metadata tables, or
  stored in `metadata_json` for the first slice if the matrix marks the
  normalization gap.
- Source of truth is directive + posting state, not balance caches.
- Materialized balances or summaries may be added later but must be rebuildable
  from posted directives.

### Phase 3: Domain Service And Repository

Implement a repository that accepts `Queryable` only. Do not import server
internals from the plugin.

Service methods:

- `createFinanceBook(spaceId, userId, input)`
- `listFinanceBooks(spaceId)`
- `createLedgerOption(spaceId, bookId, input)`
- `createCommodity(spaceId, bookId, input)`
- `openAccount(spaceId, bookId, input)`
- `closeAccount(spaceId, bookId, accountId, date)`
- `createDirectiveDraft(spaceId, bookId, input)`
- `createTransactionDraft(spaceId, bookId, input)`
- `proposeDirective(spaceId, bookId, directiveId, userId)`
- `postDirective(spaceId, bookId, directiveId, userId)`
- `voidDirective(spaceId, bookId, directiveId, userId)`
- `listAccounts(spaceId, bookId)`
- `listDirectives(spaceId, bookId, filters)`
- `listTransactions(spaceId, bookId, filters)`
- `getAccountLedger(spaceId, bookId, accountId, filters)`
- `computeBalances(spaceId, bookId, filters)`
- `validateBook(spaceId, bookId)`
- `importBeancount(spaceId, bookId, input)`
- `exportBeancount(spaceId, bookId, options)`

Repository methods must always include `space_id = $spaceId`; book-specific
queries must also include `book_id = $bookId`.

### Phase 4: Engine Pipeline

Implement a TypeScript ledger engine:

1. Read directive stream from DB, or parse Beancount text into internal AST.
2. Normalize into domain objects.
3. Sort by date, directive order, sequence, and source line.
4. Apply booking/interpolation for incomplete postings.
5. Apply built-in transformations:
   - pad directives
   - balance checks
   - document compatibility metadata
6. Validate.
7. Return `entries`, `errors`, `options`, and warnings.
8. Export Beancount text from the normalized directive stream.

Directive order should mirror Beancount semantics: open and balance-like checks
occur before same-day transactions; close occurs after same-day activity.
Document ordering should match the upstream audit result.

Plugin directives are persisted and exported, but arbitrary Python plugin code
is not executed. Include directives are persisted and exported; resolving
external include paths must require an explicit import bundle or future safe file
policy, not arbitrary host file access.

### Phase 5: Validation Rules

Minimum required validations:

- Duplicate open.
- Duplicate close.
- Close before open.
- Close unopened account.
- Unknown account reference.
- Inactive account reference.
- Account currency constraints.
- Duplicate balance assertion with different amount.
- Duplicate commodity declaration.
- Document path / attachment validity.
- Transaction balanced check.
- Tolerance inference.
- Posting data type sanity.
- Date-level ordering semantics.

Validation behavior:

- `draft` and `proposed` directives may be incomplete or invalid, but must carry
  structured validation errors.
- `posted` directives must satisfy committed-ledger validation.
- An unbalanced transaction must never silently enter the committed ledger.
- MVP balancing may first require postings to balance by commodity. If advanced
  cost/price balancing is incomplete, mark it `partial` in the parity matrix and
  return explicit unsupported/validation errors.

### Phase 6: Beancount Importer And Exporter

Importer:

- Parse options, includes, plugin directives, tag/meta stack events, directives,
  metadata, tags, links, costs, prices, balance tolerances, incomplete postings,
  and source locations.
- Store imports in `finance_import_sources`.
- Deduplicate by `external_id` or content/import hash where supplied.
- For user uploads/imports, default to `proposed` unless the caller explicitly
  has permission to post directly.

Exporter:

- Read posted directives from DB.
- Sort deterministically.
- Export option/title/operating currency.
- Export all core directives:
  - `open`
  - `close`
  - `commodity`
  - `pad`
  - `balance`
  - `transaction`
  - `note`
  - `event`
  - `query`
  - `price`
  - `document`
  - `custom`
  - include/plugin/tag/meta stack directives where stored
- Preserve decimal text and UTF-8 output.
- Create a `finance_exports` row with content hash and validation summary.

Artifact integration:

- The existing `PluginHostContext` does not currently expose an artifact port.
- Do not deep-import artifact internals from the plugin.
- If v1 must save exports as artifacts, first add a narrow host-provided
  artifact port to `packages/protocol/src/plugins.ts` and
  `server/src/modules/plugins/host/context.ts`, backed by the server artifact
  module.
- Until that port exists, exports can return text and record `artifact_id = null`
  with a documented parity gap.

### Phase 7: Proposal Flow

Manual user entry can write plugin domain tables directly when authorized, but
agent-created, AI-derived, or imported ledger changes should default to
proposal review.

Add plugin proposal appliers through `ctx.proposals.register()`:

- `finance_ledger.post_directive`
- `finance_ledger.post_import_batch`
- Optional later: `finance_ledger.void_directive`

Appliers must:

- Fail closed when the plugin is disabled.
- Re-run validation at apply time.
- Check `space_id`, `book_id`, and directive status.
- Post only valid directives.
- Leave failed proposals without partial side effects.

Do not route ledger extraction into Memory, Knowledge, ContextBuilder, or
FlashCards without the existing proposal/intake boundaries.

### Phase 8: REST API

Routes live in:

```text
plugins/official/finance_ledger/server/src/routes.ts
```

Minimum route surface:

- `GET /api/v1/finance/books`
- `POST /api/v1/finance/books`
- `GET /api/v1/finance/books/:bookId/options`
- `PUT /api/v1/finance/books/:bookId/options/:name`
- `GET /api/v1/finance/books/:bookId/accounts`
- `POST /api/v1/finance/books/:bookId/accounts`
- `POST /api/v1/finance/books/:bookId/accounts/:accountId/close`
- `GET /api/v1/finance/books/:bookId/commodities`
- `POST /api/v1/finance/books/:bookId/commodities`
- `GET /api/v1/finance/books/:bookId/directives`
- `GET /api/v1/finance/books/:bookId/transactions`
- `POST /api/v1/finance/books/:bookId/transactions`
- `GET /api/v1/finance/books/:bookId/accounts/:accountId/ledger`
- `GET /api/v1/finance/books/:bookId/balances`
- `POST /api/v1/finance/books/:bookId/validate`
- `POST /api/v1/finance/books/:bookId/import/beancount`
- `POST /api/v1/finance/books/:bookId/export/beancount`

All routes must:

- Call `ctx.http.pluginGuard()`.
- Use `identity.spaceId`.
- Return structured validation errors.
- Avoid exposing rows from another space or book.

## Frontend MVP

The first screen should be the working finance ledger, not a marketing page.

Minimum views:

- Book selector and create-book action.
- Account tree/list.
- Commodities list.
- Transactions/directives table.
- Transaction editor with multiple postings.
- Balance summary.
- Validation panel.
- Import Beancount text/file action.
- Export Beancount action.

Design constraints:

- Quiet operational UI; no investment dashboard styling.
- Dense but readable tables.
- Use icons for toolbar actions where available through `lucide-react`.
- Do not display realtime market values.
- Keep disabled-plugin state consistent with the `diary` adapter pattern:
  disabled route shows a clear enable/install action via `/plugins`.

## Documentation Deliverables

Create during implementation:

- `docs/finance/beancount-core-parity-matrix.md`
- `docs/finance/beancount-export-format.md`
- `docs/finance/postgres-ledger-schema.md`

For the durable architecture decision, follow this repo's current ADR convention
instead of creating a separate `docs/adr/` tree:

- `.agent/decisions/<next>-finance-beancount-core-parity.md`

The ADR should state:

- PostgreSQL is source of truth.
- Beancount text is import/export compatibility format.
- The implementation is Beancount-compatible, not a vendored Beancount runtime.
- GPLv2-only source is reference material only.
- The future investment plugin reads finance ledger data but does not own a
  second ledger.

Update current-state architecture docs only after the implementation lands:

- `.agent/architecture/OFFICIAL_OPTIONAL_MODULES.md`
- `.agent/decisions/0007-plugin-module-architecture.md` only if plugin framework
  boundaries change, such as adding an artifact host port.

## Testing Plan

Backend unit tests:

- Decimal parsing and arithmetic without JS number.
- Account name validation.
- Commodity symbol validation.
- Directive sort order.
- Amount, cost, position, inventory behavior.
- Transaction balancing.
- Validation error shapes.
- Export formatting.
- Import parser fixtures.

Backend integration tests:

- Plugin descriptor appears in registry and is disabled by default.
- Installer runs `finance_ledger` plugin migrations.
- Disabled plugin routes fail closed.
- Enabled plugin routes pass.
- Cross-space finance books are hidden.
- Create book/account/commodity.
- Open and close account.
- Balanced transaction can post.
- Unbalanced transaction cannot post.
- Closed account cannot receive postings.
- Currency constraints are enforced.
- Balance assertion pass/fail.
- Export creates `finance_exports`.
- Proposal applier posts a valid directive and rejects an invalid one.

Import/export fixtures:

- open/close
- commodity
- transaction with metadata/tags/links
- posting with cost
- posting with price
- balance with tolerance
- pad
- note
- event
- query
- price
- document
- custom
- option/include/plugin/pushtag/pushmeta
- incomplete posting interpolation
- cost-lot inventory
- FIFO/LIFO/AVERAGE status fixtures, implemented or explicitly deferred

Roundtrip tests:

- `text -> import -> DB -> export -> parse -> normalized AST comparison`.
- Export snapshot for representative ledger.
- Optional `bean-check` compatibility test gated by local tool availability, not
  required for the canonical suite unless the test environment installs
  Beancount.

Frontend tests:

- Registry overlay handles `finance_ledger` effective state.
- Disabled finance module shows enable/install path.
- Book/account/transaction UI renders with host API fakes.
- Posting editor prevents obvious invalid submission.
- Validation panel renders structured errors.

Focused verification commands:

```bash
cd packages/protocol
npm run typecheck
npm test
npm run build

cd ../server
npm run typecheck
npx vitest run test/plugins.test.ts test/boundaries.test.ts test/financeLedger*.test.ts
npm run build

cd ../apps/web
npm run typecheck
npm test
npm run build
```

If plugin build artifacts are needed before tests:

```bash
cd server
npm run build:official-plugins
```

## Suggested Implementation Phases

1. Upstream audit and parity matrix.
2. Descriptor, plugin package skeleton, frontend registry entry, app adapter,
   disabled-state page.
3. Plugin migration with full directive-stream schema.
4. Value objects and validation core.
5. Repository/service and book/account/commodity routes.
6. Transaction/directive routes and proposal appliers.
7. Exporter for all stored directives.
8. Importer and roundtrip fixtures.
9. Frontend ledger MVP.
10. Artifact-port decision and export artifact persistence.
11. Current-state architecture doc and ADR updates.

## Acceptance Criteria

- `finance_ledger` is installable and enableable through the existing official
  plugin control plane.
- Routes are mounted only through `PluginHost`.
- Disabled routes return plugin-disabled errors.
- All finance domain data is scoped by `space_id`; book-specific reads are
  scoped by `book_id`.
- PostgreSQL directive stream can represent every Beancount v3 core directive,
  even where execution is marked `partial` or `deferred`.
- Posted transactions cannot be unbalanced.
- Beancount export covers all stored core directives.
- Import/export parity gaps are listed in
  `docs/finance/beancount-core-parity-matrix.md`.
- Manual ledger data does not become Activity, Memory, Knowledge, or Context
  content unless a future proposal/intake path explicitly does that.
- Future investment plugin integration has a single source of truth: this
  finance ledger.
