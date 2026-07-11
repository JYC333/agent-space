# Hardening Plan — Blind-Spot Remediation, Priority-Ordered

Date: 2026-07-11
Status: P0 complete; P1/P2 scheduled as described below
Source: repo-wide blind-spot pass (2026-07-11) — engineering inventory +
ops/security sweep + prior execution/evolution audits.
Relationship: companion to
[orchestration-and-self-evolution-plan.md](orchestration-and-self-evolution-plan.md)
(the "main plan"). This document owns the remediation ordering; items marked
FOLD-IN are implemented inside main-plan tracks and only tracked here.

Verified baseline facts this plan reacts to: ~300k LOC across server/web/
protocol, 177 tables, 534 routes, 41 frontend modules; zero CI / lint /
coverage / E2E; egress control is proxy-env only; deployer container mounts
docker.sock + repo rw; master key ships inside backup archives on the same
disk; no metrics/alerting, static /health; append-only tables have no
pruning; frontend uses a hand-written 7.5k-line API contract copy; no cost
caps. Commits are owner-squashed by design (not a process gap).

---

## P0 — Do BEFORE starting main-plan implementation (~1 week total)

These either protect all subsequent work or close doors that must not stay
open while code churn increases.

**P0-1. Minimal CI.** (~0.5–1 day)
GitHub Actions (or equivalent): on push/PR to master run protocol build,
`tsc` for server+web, `vitest run` for server (testcontainers Postgres) and
web. No lint/coverage yet — just make "master is green" a mechanism instead
of a habit. This is the single highest-leverage item: the main plan will
generate months of large diffs and currently nothing guards them.

**P0-2. Deployer authorization audit + invariants.** (~1 day)
The deployer container holds docker.sock + repo rw = host-equivalent power.
Verify the actual trigger chain in code (who/what can invoke a deploy; is it
really host-deployer-only + proposal-gated as documented). Write the result
into `BOUNDARIES.md` as explicit invariants: (a) enumerated deployer
triggers, (b) nothing on the evolution/code_patch/capability path may reach
deployer input without human approval, (c) **the instance must never be
directly exposed to the public internet** (no TLS/rate-limit/CSRF-token
hardening exists — L2 below records the trigger to revisit). Add a test if
the trigger chain is testable.

**P0-3. Backup integrity fixes.** (~1 day)
(a) `BACKUP_DATABASE_URL` unset currently skips the DB dump silently
(warning in manifest only) — make it fail loud. (b) Separate the credential
master key from the data archive: exclude `secrets/` from the default
bundle, back it up via a separate, explicitly-handled path, and document a
manual encrypted offsite copy procedure for both. (c) Note in ops docs that
current backups protect against deletion, not host loss, until offsite
exists.

**P0-4. Minimal failure alerting.** (~1–2 days)
(a) `/health` checks DB connectivity instead of returning static ok.
(b) Wire job exhaustion (`max_attempts` reached), automation fire failure,
and scheduler task exceptions into the existing notifications module
(currently user-facing only, never connected to failures). A system meant to
run unattended overnight must be able to say "I am broken".

**P0-D. Direction decisions (no code, ~1 hour of owner honesty).**
(a) **Primary product identity**: personal memory OS vs agent orchestration
platform vs self-evolving system — pick the one the next two quarters serve;
the other two become supporting casts. (b) **Dogfooding checkpoint**: a
falsifiable criterion (e.g. 30 consecutive days of real daily use, ≥1
friction-driven fix per week) reviewed monthly, so platform building cannot
indefinitely self-justify. (c) **CLI-first vs managed-API-first** stance,
including an explicit look at vendor CLI ToS for programmatic driving —
decides which path is primary and which is fallback when a vendor breaks or
forbids automation.

**Decision (accepted 2026-07-11):** the primary product is a server-authoritative
Agent Workbench for individuals, households, and small teams, carrying substantial daily
research, writing, project, automation, knowledge, and code work. Memory/context are core
substrate; orchestration is an execution capability; self-evolution is supporting cast.
Dogfooding uses the falsifiable 30-day checkpoint in ADR 0010. Runtime posture keeps CLI
subscriptions and managed APIs as dual primary resources. OpenCode joins Claude Code and
Codex as the third optional CLI runtime; it is not a universal runtime and receives no global
Router preference. Claude Pro/Max stays on native Claude Code while OpenCode's provider
documentation records that Anthropic prohibits routing that subscription through OpenCode.
See ADR 0010 for the vendor terms checkpoint and full consequences.

---

## P1 — FOLD-IN: implemented inside main-plan tracks

Tracked here, built there. Requires edits already reflected in the main plan
or to be made when the track starts.

**P1-1. Egress control — elevate within C3.** The open exfiltration chain
(untrusted ingested content → agent context → CLI with unrestricted network)
is a governance-model gap, not a nice-to-have sandbox feature: the policy
system guards durable writes but not outbound reads/comms. Until real
enforcement (network namespace / proxy-enforced) lands in C3: document the
gap in `SECURITY_AND_ACCESS_BOUNDARIES.md`, and prefer `http_proxy` network
profiles for runs whose context includes low-trust sources. C3 acceptance
must include: high-risk runs get deny-by-default egress.

**P1-2. Budget/cost caps → A1 + A3.** Contract snapshot carries budget
(A1); enforcement across attempts (A3). Quick win allowed earlier: a daily
token-spend threshold notification via P0-4's alerting (usage data already
exists; only the alert is missing).

**P1-3. Approval value-density metrics → D1.** Add reviewer-behavior
signals (per-proposal-type approve rate, median review latency) to the D1
emitter set. If a proposal type is ~always approved instantly, it is not a
control — automate it or redesign it. This instruments the rubber-stamping
failure mode the whole governance story depends on avoiding.

**P1-4. Scheduler catch-up semantics → B3.** Missed schedules silently
collapse/skip and failed fires still advance `next_run_at`. When automations
move to workflow targets (B3), add an explicit per-automation missed-run
policy (`skip` | `fire_once` | `backfill_n`) and surface fire failures via
P0-4 alerting. Until then the current behavior is documented, not fixed.

---

## P2 — Scheduled, not blocking (slot alongside main-plan phases)

**P2-1. Retention & pruning design.** Append-only tables (run_events,
run_steps, evolution_signals, token_usage_events, activity, …) and artifact
storage grow unbounded; backups compound the cost daily. Needs a real
design (audit semantics, per-table policy, artifact GC) — schedule as its
own slice after A-track lands (RunAttempt changes evidence shape; design
retention after, not before). Watch trigger: DB > a few GB or backup > 15
min.

**P2-2. Frontend contract generation.** Replace the hand-maintained
`types/api.ts` (5.2k lines) + `client.ts` (2.3k lines) with types generated
from `packages/protocol` zod schemas. Structural fix for permanent drift
risk; natural slot = start of D4 (frontend consolidation), or earlier if
contract drift causes a second real bug. Until then: no new hand-written
type additions without a matching protocol schema.

**P2-3. Toolchain de-risking.** Pin node via `engines` + `.nvmrc`; fix
react 18 / @types/react 19 mismatch; either adopt a real pnpm workspace
(one lockfile) or remove the `packageManager` claim; write down a TS-version
policy (currently `^7.0.0` native-preview — decide whether to ride the
preview or pin). Half a day, do it right after P0-1 so CI locks it in.

**P2-4. Ops runbook consolidation.** One page: what runs where, how to
tell it's healthy (post P0-4), how to restore (verify-restore exists),
what to do on host loss (post P0-3). Mostly assembling existing pieces.

---

## P3 — Watch items: record trigger, do nothing now

| Item | Trigger to act |
|---|---|
| E2E/browser tests (41-module PWA + Tauri, zero today) | Second real user, OR a frontend regression that loses/corrupts data |
| TLS, rate limiting, CSRF tokens | Any step toward public/internet exposure (currently forbidden by P0-2 invariant) |
| Multi-user/space-sharing regression pass | A second member actually joins a space |
| Offline queue (docs claim it; frontend has none) | Real mobile/offline usage need; until then fix the doc claim (main-plan Phase 0) |
| Large-file splits (knowledge/sources repos ~2.5k lines; web api.ts/client.ts) | Next substantive edit touching those files (per CLAUDE.md split rule) |
| Master-key rotation | Any suspected key exposure, or before any multi-instance future |
| commercialization posture | Explicitly settled (personal-first, no enterprise prebuild) — revisit only on a real external-user decision |

---

## Recommendation on ordering vs the main plan

**Do NOT finish this whole document before starting the main plan.** Run:

1. **P0 first — one focused week** (P0-1..4 + the P0-D decisions). These
   are cheap, they protect everything after, and two of them (CI, deployer
   invariants) get *more* expensive the longer the main plan runs without
   them.
2. **Then start the main plan** (Phase 0 → A1+B1+C1+D1). P1 items ride
   inside its tracks — they are cheaper there than as standalone work.
3. **P2 slots opportunistically** (P2-3 immediately after CI; P2-1 after
   A-track; P2-2 at D4). **P3 waits for triggers.**

Rationale: most hardening items are either force-multipliers for the main
plan (CI, alerting) or already coupled to its tracks (egress→C3,
budget→A1/A3, scheduler→B3, metrics→D1). Deferring the main plan by 1–2
months to "finish hardening" would mean doing P1 items twice and losing the
forcing function that the main plan's phases provide. The only
non-negotiable sequencing is: **no main-plan implementation commits before
P0-1 (CI) exists.**
