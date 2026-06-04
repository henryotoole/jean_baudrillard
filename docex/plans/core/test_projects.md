# Doctrine Smoke-Test Projects

Two minimal, doctrine-faithful projects (`fixed/` and `elastic/`) that live inside the `docex/` tree. They exist for one purpose: before cutting a `docex` minor or major version, drive each one end-to-end through `compile → containerize → release stage → stagetest → release prod → teardown` to surface bugs that unit tests structurally can't reach.

## Why two

The doctrine commits to two foundations. Bugs hit each foundation differently — first-time release on elastic exposed eight bugs in v0.7.0 that `fixed`-only testing would have missed. Each project exercises its own foundation's full release path:

- [`fixed/`](../../test_projects/fixed/README.md) — `foundation: fixed`. Runs entirely on the dev machine via docker-compose + Traefik + Let's Encrypt. Domain: `doctrine-fixed.luxrnd.tech`.
- [`elastic/`](../../test_projects/elastic/README.md) — `foundation: elastic`. Runs against real AWS in `us-east-1`. Domain: `doctrine-elastic.luxrnd.tech` (Route53 zone created by `docex bootstrap`).

## Shape

Both projects share the **same code** under `core/`. The two cores (`web`, `worker`) talk through a single postgres backing service (`db`) and the `pings` table. `web` exposes `POST /pings` + `GET /health`; `worker` polls the `pings` table and marks rows processed. Total: two cores + one backing service.

Code identity between fixed and elastic is intentional. Per the doctrine's parts-only env model, application code shouldn't know which foundation it's running on; the smoke test's audit step diffs the two trees and fails if real divergence appears.

```
docex/test_projects/
├── README.md                    (stub pointing back at this doc)
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

These projects were created by walking [`doctrine/practices/inception.md`](../../../doctrine/practices/inception.md) PARTs I–IV, with two carve-outs:

1. **PART I steps 3–5 skipped** — no `gh repo create` and no `git clone`. Each test project is initialized as its own git repo in place (`git init -b main`) inside the `docex/` tree, so `docex` commands that introspect a real repo state from inside the docex container (`check`, `merge`, `containerize`) see one. The outer `jean_baudrillard` repo also tracks the same files as a directory snapshot at each of its commit boundaries; an edit dirties both repos. See [§ Git structure](#git-structure) below for the full layout and the commit cadence between the two.
2. **PART III steps 6–7 skipped** — bringing up `dev` and tearing it down is the operator's smoke-test work (driven by [`PRE_CUT_CHECKLIST.md`](../../test_projects/PRE_CUT_CHECKLIST.md)), not part of the seed-creation work.

These carve-outs are flagged for possible doctrine-level codification — "the inception flow needs a bundled-test-project mode." See [`docex_process.md`](./docex_process.md) § Test Project Tests for the surrounding workflow.

## Git structure

Each test project under `test_projects/` is its own git repo, nested inside the outer `jean_baudrillard` repo. A file like `test_projects/elastic/core/web/migrate.sh` is therefore tracked by both:

- The **inner repo** at `test_projects/<foundation>/.git/` — branch `main`, with the current `project.yml` version tagged at HEAD (e.g., `v0.0.2`). This is the project's authoritative history and the one `docex check` / `merge` / `containerize` introspect when running from inside the docex container.
- The **outer repo** at `jean_baudrillard/.git/` — tracks the same files as a directory snapshot. The outer history records the test-project state at each doctrine/docex commit boundary.

The two histories evolve independently. The inner repo's log shows project-level commits (`Bump 0.0.2: migrate.sh sslmode default`, `Repin to docex 0.8.3`); the outer repo's log shows doctrine/docex commits, with periodic catchup entries that sync the outer-tracked snapshot to the current inner-repo HEAD.

[`PRE_CUT_CHECKLIST.md`](../../test_projects/PRE_CUT_CHECKLIST.md) § A.2.1 is the pre-walk audit for this structure — confirm each inner repo exists, is on `main`, has the right `v<version>` tag at HEAD, and has a clean working tree before starting any smoke walk.

### Why the test projects are their own git repos

The doctrine assumes a project IS its own git repository (per [`inception.md`](../../../doctrine/practices/inception.md)). Several `docex` commands rely on that:

- `docex check` introspects the feature branch, fetches latest `main`, runs gate checks against an ephemeral worktree.
- `docex merge` rebases onto `main`, tags the new HEAD with `v<project.yml version>`, pushes both.
- `docex containerize` requires a clean tree on `main` with the current `project.yml` version tagged at HEAD; image tags are 1:1 with that version.

If the test projects existed only as subtrees of the outer repo, none of those introspections would work — the docex container would see the outer repo's state (commits about doctrine evolution, not about the test project) and reject every release-path command.

### Commit cadence

Edits inside `test_projects/{fixed,elastic}/` show as dirty in both repos. The convention used throughout the docex history:

1. Commit in the **inner** repo first, with a project-shaped message (e.g., `Repin to docex 0.8.3; recompile`).
2. If the change crosses a project release boundary, force-move the version tag (`git tag -f v<version>`) to the new HEAD. The tag must point at the current `project.yml` version for `docex containerize` to find a real version-tagged commit.
3. Commit the same files in the **outer** repo as a separate catchup, with a message that names what the snapshot now reflects (e.g., `Sync test_projects/elastic catchup to inner-repo state (mods 005-008)`).

Inner-first matters because the inner repo is the authoritative history — forgetting it leaves the outer repo dirty but the project's release pipeline still won't see the change.

## Resource cleanup discipline

The elastic project provisions real AWS resources. Tag discipline matters for cleanup:

- Every doctrine-emitted AWS resource is named with the project name as a prefix (e.g. `docex-smoke-elastic-prod-alb`, `docex-smoke-elastic-prod-appdb`). Naming alone is sufficient to identify project resources in v1.
- [`verify_clean.sh`](#) in each project queries for any lingering resource by that prefix and exits non-zero if anything remains.
- A future doctrine improvement: first-class `managed_by` tagging on every emitted resource — would let `verify_clean.sh` filter by tag and not rely on naming. Tracked as a follow-up; not blocking.

## Smoke-project safety overrides

The doctrine's transfer-table defaults for stateful resources (RDS `deletion_protection: true`, the terraform-aws-provider default `skip_final_snapshot: false`, etc.) are correct for real projects — they prevent accidental destruction of production data. Smoke projects always retire, so those same defaults block teardown unless something overrides them at retirement time.

The override lives in `test_projects/<foundation>/teardown.sh`, not in the transfer table. Concretely on elastic:

1. `aws rds modify-db-instance --no-deletion-protection` per project RDS, polled until the flag actually lands.
2. `aws rds delete-db-instance --skip-final-snapshot --delete-automated-backups` per project RDS, polled until each instance is fully gone. This bypasses tofu entirely for the RDS — tofu destroy then reconciles state on its next pass.
3. Tofu destroy runs against each env-tier + project-tier HCL with the RDS already absent, so no `skip_final_snapshot` battle and no ENI-detach race.

This script-side override pattern keeps the safety nets intact for prod projects while letting smoke walks retire cleanly. Mod 028 added the direct-delete step after the 0.11.0 walk demonstrated that disabling `deletion_protection` alone wasn't sufficient.

## Lifecycle

| Cut type | Run the smoke test? |
| -------- | ------------------- |
| Patch (e.g. 0.7.0 → 0.7.1) | No — patch bugs are caught by unit tests. |
| Minor (e.g. 0.7.x → 0.8.0) | Yes — audit + walk both projects per `PRE_CUT_CHECKLIST.md`. |
| Major (e.g. 0.x → 1.0) | Yes, plus a full re-inception (a successor agent re-walks PARTs I–IV from scratch against the current doctrine, replacing this seed). |

See [`PRE_CUT_CHECKLIST.md`](../../test_projects/PRE_CUT_CHECKLIST.md) for the actual procedure.
