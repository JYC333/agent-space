# Graph View Benchmarks

Date: 2026-07-04
Status: Phase 6 automated baseline report

This report records the initial scale thresholds for the shared GraphView
core. It is a temporary report, not source of truth; the source-of-truth
thresholds live in `apps/web/src/components/graph/core/graphLayouts.ts`.

## Scale Policy

| Projection size | Layout path | Notes |
|---|---|---|
| 100/300 | in-thread force | Default canvas path. Full labels remain semantic-zoom gated. |
| 1k/3k | in-thread force | `IN_THREAD_FORCE_ITERATIONS = 220`. |
| 1,501-3,000 nodes | G6 worker force | `enableWorker = true`, `WORKER_FORCE_ITERATIONS = 80`. |
| >3,000 nodes | degraded grid | Headless browser measurements showed worker-force interaction lag above this point. |
| >5k nodes | client node budget exceeded | Treated as a producer bug except dev synthetic benchmarks. |
| >15k edges | edge-budget warning | Producer should cap or aggregate edges before rendering. |

## Synthetic Baselines

The dev-only `?debug=synthetic:n` path now allows up to 10,000 synthetic
domain nodes so local stress checks can cover the planned 10k/30k case. The
generator adds six cluster nodes; `syntheticProjection(10000)` produces
10,006 nodes and 29,988 edges.

Automated pure-helper measurements were collected on 2026-07-04 with a
temporary `vite-node` runner importing the production graph helpers.

The runner measured pure JS preprocessing only: synthetic projection creation,
scale-policy selection, layout-option resolution, and
`mapProjectionToRenderData`. It did not instantiate G6 or a browser canvas.

| Input | Projection nodes | Edges | Layout path | Worker | Median map time |
|---|---:|---:|---|---|---:|
| `syntheticProjection(100)` | 106 | 288 | force | no | 0.27 ms |
| `syntheticProjection(1000)` | 1,006 | 2,988 | force | no | 3.47 ms |
| `syntheticProjection(3000)` | 3,006 | 8,988 | grid | no | 5.93 ms |
| `syntheticProjection(5000)` | 5,006 | 14,988 | grid | no | 8.70 ms |
| `syntheticProjection(10000)` | 10,006 | 29,988 | grid | no | 24.97 ms |

`syntheticProjection(3000)` is over the 3k worker layout ceiling because the
generator adds cluster nodes. `syntheticProjection(5000)` is over the 5k client
node budget for the same reason. Unit tests cover exact boundary projections.

## Browser Smoke Benchmark

A second run used a temporary Vite entry rendering the real `GraphView` in
Playwright Chromium 140 (`headless`, 1440x900, canvas renderer). The page used
the final scale policy and waited for the G6 canvas, then sampled pan/zoom and
hover by dispatching wheel/mouse events and waiting for animation frames.

The `first canvas` number includes Vite dev-server module loading and should
not be read as production bundle TTI. The frame samples are more useful for
relative layout-policy tuning.

| Input | Projection nodes | Edges | Layout tier | Layout | First canvas | Pan/zoom avg frame | Pan/zoom max frame | Hover frame | JS heap |
|---|---:|---:|---|---|---:|---:|---:|---:|---:|
| `syntheticProjection(100)` | 106 | 288 | in-thread | force | 1,914.6 ms | 15.8 ms | 16.9 ms | 16.5 ms | 40.1 MB |
| `syntheticProjection(1000)` | 1,006 | 2,988 | in-thread | force | 7,014.1 ms | 16.2 ms | 19.9 ms | 16.4 ms | 124.9 MB |
| `syntheticProjection(3000)` | 3,006 | 8,988 | degraded | grid | 9,524.2 ms | 38.0 ms | 39.2 ms | 37.8 ms | 391.0 MB |
| `syntheticProjection(5000)` | 5,006 | 14,988 | degraded | grid | 15,175.5 ms | 15.6 ms | 17.1 ms | 16.5 ms | 670.4 MB |
| `syntheticProjection(10000)` | 10,006 | 29,988 | degraded | grid | 29,043.7 ms | 16.5 ms | 17.4 ms | 16.8 ms | 496.9 MB |

An initial pre-tuning browser run let `syntheticProjection(3000)` use worker
force layout and produced roughly 96 ms pan/zoom frames and 99 ms hover frames.
The final threshold therefore degrades projections above 3,000 total nodes to
grid layout. The 5k/15k case is usable for pan/zoom and hover in degraded grid,
but initial render is slow enough that producers should still prefer capping or
aggregation for ordinary product flows.

## Verification

- Pure scale policy is covered by `graphCore.test.ts`.
- G6 construction/update/destroy paths remain covered by the existing mocked
  `GraphView` tests.
- Real browser smoke measurements were collected with Playwright Chromium
  against a temporary Vite benchmark entry.
- Vite production build confirms G6 is split into the lazy `GraphView` chunk
  (`GraphView-*.js`, about 1.44 MB minified / 420 KB gzip in this run).

## Limits

The browser run is a headless Chromium smoke benchmark, not a visual UX study.
It does not verify readability, visual overlap, GPU memory, or WebGL behavior.
Manual browser sampling should repeat the checkpoints above before raising the
worker ceiling or changing the degraded-layout threshold.
