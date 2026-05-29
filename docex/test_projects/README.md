# Doctrine Smoke-Test Projects

Two minimal, doctrine-faithful projects (`fixed/` and `elastic/`) that live inside the `docex/` tree. They exist for one purpose: before cutting a `docex` minor or major version, drive each one end-to-end through `compile → containerize → release stage → stagetest → release prod → teardown` to surface bugs that unit tests structurally can't reach.

## Why two

The doctrine commits to two foundations. Bugs hit each foundation differently — first-time release on elastic exposed eight bugs in v0.7.0 that `fixed`-only testing would have missed. Each project exercises its own foundation's full release path:

- [`fixed/`](./fixed/README.md) — `foundation: fixed`. Runs entirely on the dev machine via docker-compose + Traefik + Let's Encrypt. Domain: `doctrine-fixed.luxrnd.tech`.
- [`elastic/`](./elastic/README.md) — `foundation: elastic`. Runs against real AWS in `us-east-1`. Domain: `doctrine-elastic.luxrnd.tech` (Route53 zone created by `docex bootstrap`).

## Shape

Both projects share the **same code** under `core/`. The two cores (`web`, `worker`) talk through a single postgres backing service (`db`) and the `pings` table. `web` exposes `POST /pings` + `GET /health`; `worker` polls the `pings` table and marks rows processed. Total: two cores + one backing service.

Code identity between fixed and elastic is intentional. Per the doctrine's parts-only env model, application code shouldn't know which foundation it's running on; the smoke test's audit step diffs the two trees and fails if real divergence appears.

```
docex/test_projects/
├── README.md                    (this file)
├── PRE_CUT_CHECKLIST.md         (the operator's pre-cut walk)
├── fixed/                       (foundation: fixed)
│   ├── project.yml, README.md, CHANGELOG.md, .gitignore
│   ├── bin/docex                (shim, installed by docex_install.sh)
│   ├── core/{web,worker}/       (full hex structure, identical to elastic's)
│   ├── infra/{infra.yml, contracts/, stage/, secrets/, deploy_creds/, output/}
│   ├── plans/core/              (masterplan + service docs)
│   ├── teardown.sh
│   └── verify_clean.sh
└── elastic/                     (same shape, foundation: elastic)
```

## Inception-flow divergences

These projects were created by walking [`doctrine/practices/inception.md`](../../doctrine/practices/inception.md) PARTs I–IV, with two carve-outs:

1. **PART I steps 3–5 skipped** — no `gh repo create` and no `git clone`. These projects live inside the `docex/` tree, not as standalone repos. The "project root" is the test-project subfolder; git operations happen against the parent `jean_baudrillard` repo.
2. **PART III steps 6–7 skipped** — bringing up `dev` and tearing it down is the operator's smoke-test work (driven by [`PRE_CUT_CHECKLIST.md`](./PRE_CUT_CHECKLIST.md)), not part of the seed-creation work.

These carve-outs are flagged for possible doctrine-level codification — "the inception flow needs a bundled-test-project mode." See [`../plans/core/docex_process.md`](../plans/core/docex_process.md) § Test Project Tests for the surrounding workflow.

## Resource cleanup discipline

The elastic project provisions real AWS resources. Tag discipline matters for cleanup:

- Every doctrine-emitted AWS resource is named with the project name as a prefix (e.g. `docex_smoke_elastic-prod-alb`, `docex-smoke-elastic-prod-database`). Naming alone is sufficient to identify project resources in v1.
- [`verify_clean.sh`](#) in each project queries for any lingering resource by that prefix and exits non-zero if anything remains.
- A future doctrine improvement: first-class `managed_by` tagging on every emitted resource — would let `verify_clean.sh` filter by tag and not rely on naming. Tracked as a follow-up; not blocking.

## Lifecycle

| Cut type | Run the smoke test? |
| -------- | ------------------- |
| Patch (e.g. 0.7.0 → 0.7.1) | No — patch bugs are caught by unit tests. |
| Minor (e.g. 0.7.x → 0.8.0) | Yes — audit + walk both projects per `PRE_CUT_CHECKLIST.md`. |
| Major (e.g. 0.x → 1.0) | Yes, plus a full re-inception (a successor agent re-walks PARTs I–IV from scratch against the current doctrine, replacing this seed). |

See [`PRE_CUT_CHECKLIST.md`](./PRE_CUT_CHECKLIST.md) for the actual procedure.
