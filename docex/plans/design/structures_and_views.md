# Building-Block View

`docex` is delivered as **a container image + a project-local shim**. The system-context
picture (operator → docex → host docker / credentials / external targets) is
[`project_diagram.mmd`](./project_diagram.mmd); the delivery model and its determinism
rationale are in [`concepts_and_decisions.md § Distribution`](./concepts_and_decisions.md#distribution)
and [ADR 0001](./adrs/0001_single_bundled_docex_image.md).

```
┌─────────────────────────────────────────────────────────────────┐
│  Project repository                                             │
│  ├── project.yml          (pins docex_version: "1.2.3")         │
│  ├── infra/infra.yml      (CICL source)                         │
│  ├── infra/...            (output, secrets, deploy_creds, etc.) │
│  ├── core/...             (project code)                        │
│  └── bin/docex            (~10-line shim, checked into git)     │
└────────────────────┬────────────────────────────────────────────┘
                     │  reads version, builds mount set, invokes docker run
                     ▼
┌─────────────────────────────────────────────────────────────────┐
│  docex container (docex:1.2.3)                                  │
│  - Python CLI (compiler + command dispatcher + orchestration)   │
│  - Bundled transfer tables (canonical)                          │
│  - CLI deps: docker, tofu, ansible, aws, git, jq                │
│  - Project + HOME mirrored at their host paths inside container │
└────────┬──────────────────┬───────────────────────┬─────────────┘
         │ docker.sock      │ ~/.aws, ~/.docker     │ network egress
         ▼                  ▼                       ▼
   Host docker daemon   Operator credentials   Registries, AWS, SSH targets
```

## Repository Structure

`docex` lives in `jean_baudrillard/docex/`:

```
jean_baudrillard/docex/
├── CHANGELOG.md             (pointer stub → the doctrine-wide ../CHANGELOG.md; version is doctrine-wide as of 1.3.0)
├── pyproject.toml
├── Dockerfile
├── plans/                   (doctrine-shaped planning tree — see specifics/docex_process.md for the divergences)
│   ├── design/              (arc42 L1 state docs + ADRs + a flat specifics/; no per-module layer since docex isn't hexagonal)
│   │   ├── boundary_conditions.md
│   │   ├── concepts_and_decisions.md
│   │   ├── structures_and_views.md   (this file)
│   │   ├── lexicon.md
│   │   ├── project_diagram.mmd
│   │   ├── adrs/  adr_index.md  adr_active.md
│   │   └── specifics/       (compiler, release_flow, test_projects, the_shim, subcommand_surface, docex_process)
│   ├── modifications/       (one folder per mod; same shape as the doctrine prescribes)
│   └── references/          (external API / spec docs the project relies on)
├── src/
│   └── docex/               (Python package; CLI entrypoint + all subcommands)
│       ├── __main__.py      (argparse dispatcher)
│       ├── cicl/            (CICL parse, validate, expand, magic refs)
│       ├── emit/            (compose / HCL rendering from compiled objects)
│       ├── orchestrate/     (up, down, build, test, migrate, aggregate)
│       ├── jobs/            (durable-job substrate: run records, the container
│       │                     vessel, the reaper, the job verbs)
│       ├── pipeline/        (preinfra, projinfra, bootstrap, check, merge,
│       │                     containerize, release, stagetest, rollback,
│       │                     orchestrator_health — stagetest's pre-step)
│       ├── describe/  why/  roles/         (describe; why → doctrine_excerpts/; roles + role)
│       ├── aws/  docker/  git/  ssh/  dns/  ansible/  opentofu/   (external-CLI / API adapters)
│       ├── secretsmgmt/     (SSM / .env secret backends)
│       ├── registry/        (container-registry HTTP adapter)
│       ├── context.py  naming.py  errors.py  envfile.py
│       └── docs/            (standard_set, adr, linkmap — the docs command family)
├── tables/                  (canonical transfer tables, copied to /opt/docex/tables/)
├── doctrine_excerpts/       (data feeding `docex why`)
├── bin/                     (the project-installed shim, sourced from here)
└── tests/
```

## Subcommand surface

`docex` exposes one cohesive command-line surface; the authoritative behavior of each
command lives in [`docex.md`](../../../doctrine/infrastructure/docex.md). The full
command table (reads / writes / foundation behavior per command), the `preinfra`
fail-vs-decline distinction, the durable-job substrate, and the contract/shim gate roster
are in [`specifics/subcommand_surface.md`](./specifics/subcommand_surface.md). The two
heaviest command families have their own detail docs:
[`specifics/compiler.md`](./specifics/compiler.md) (the CICL compiler) and
[`specifics/release_flow.md`](./specifics/release_flow.md) (release + rollback).

# Runtime View

## Cross-command orchestration

A few commands compose others rather than duplicate logic:

- `check` invokes `compile` (to verify it succeeds), `build` (via `docker build` during
  test), and `test`. It also runs `docs check`'s three gates (missing-standard-file + doc
  reachability + ADR-index freshness) against the worktree, all blocking; they skip when
  the project has no `plans/design`.
- `up` and `test` cause `docker build` to run as needed, which runs each codebase's
  `build.sh` inside the `build` stage. Two subtleties, both because **`compose up --build`
  does not build a `profiles:`-gated service** and `compose run` builds only when an image
  is *absent*: `test`-env one-offs pass `--build` (in `test` the image *is* the artifact
  under test), while `up dev` deliberately does not (source arrives by bind mount and the
  `dev` stage exists precisely so `build.sh` can be re-invoked without an image rebuild);
  and `up dev` pre-populates each codebase's host `dist/` before bringing the stack up,
  since the bind mount shadows the `dev` stage's in-image `dist/`.
- `release` invokes `migrate` against the target env **before** applying new application
  state in the steady state (which preserves zero-downtime). Two exceptions: on a **first
  release** the order inverts to apply-then-migrate (migrate needs the env's services and
  database to exist), and **`rollback` never migrates at all** (doctrine migrations are
  forward-only). Both are in
  [`specifics/release_flow.md § The four sequences`](./specifics/release_flow.md#the-four-sequences).
- `release` on elastic ends with a **Service Connect consumer reconcile** — the only step
  that reads AWS state written by its own apply. It runs on every elastic branch including
  rollback (see
  [`specifics/release_flow.md § Elastic-foundation flow`](./specifics/release_flow.md#elastic-foundation-flow)).
- The manual CI/CD chain —
  `docex merge && docex containerize && docex release stage && docex stagetest && docex release prod` —
  is a documented sequence, not a megacommand, preserving the doctrine's "developer can
  drive the pipeline by hand" property.

Long-running commands (`test`, `check`, `merge`) run as **durable jobs** in a detached
sibling vessel; the run outlives the invoking call. The substrate, the deterministic
per-command vessel lock, and the self-healing reaper are in
[`specifics/subcommand_surface.md § Durable jobs`](./specifics/subcommand_surface.md#durable-jobs-the-job-substrate)
and [ADR 0005](./adrs/0005_durable_job_substrate.md).

# Deployment View

The deployment shape is governed almost entirely by the doctrine and by each project's
`infra.yml`; `docex` itself is a single container image invoked on the operator's machine.
Two `docex`-specific views matter: what it touches on disk, and how commands branch per
foundation.

**No `service_diagram.mmd`.** The standard corpus includes a C4 service (container)
diagram derived from `infra.yml`. `docex` has **no `infra.yml`** and no backing
services — it is one image with one process family — so a service diagram would be a
single box and is deliberately omitted. The
[`project_diagram.mmd`](./project_diagram.mmd) system-context view is the only standard
diagram `docex` carries.

## Filesystem Surface

Every path `docex` reads or writes lives inside the project tree. The shim bind-mounts the
project root at the same path inside the container as on the host, so reported paths match
what the operator sees and DooD path resolution agrees in both directions. In brief —
**reads**: `project.yml`, `infra/infra.yml`, `infra/transfer_tables/` (optional),
`infra/contracts/…`, `infra/secrets/<env>.env`, `infra/config/<env>.env`,
`infra/tte/<env>.env`, `infra/deploy_creds/<env>`, `infra/stage/…`, `core/<codebase>/…`,
and `.git/`. **Writes**: `infra/output/<env>/…` (compile), `core/<codebase>/dist/` (dev
build), `infra/tte/<env>.env` (mint-if-absent), `.docex/agg/<env>.env` (aggregate),
`.docex/runs/<id>/…` (durable job records), `.docex/checks/latest.json` (green-check
provenance), and ephemeral worktrees under `.docex/worktrees/`. **Conspicuously not
touched:** anything outside the project tree — the container is sandboxed to the project
root plus the explicitly-mounted credential paths under the operator's HOME.

## Foundation-Aware Behavior

Several commands branch internally on `foundation:`; the command surface stays symmetric.
The `dev` and `test` environments are always fixed regardless of declared foundation, per
[shape.md § Shape and Environment](../../../doctrine/infrastructure/shape.md#shape-and-environment).

| Command | Fixed | Elastic |
| ------- | ----- | ------- |
| `projinfra` | brings the project-tier compose stack (three `-web` networks — `dev`/`stage`/`prod`; `test`'s web network is env-tier — + per-project traefik) up or down | `up production` creates the `<project>-tofu-state` S3 bucket + `<project>-tofu-locks` DynamoDB table, then applies the project tier in two phases (Route53 zone alone → full tier), pausing between them for NS delegation; all idempotent. `down production` tears the project tier down |
| `compile` | emits `docker-compose.yml` per env, plus `playbook.yml` / `inventory.yml` / `ansible.cfg` for stage/prod | emits `main.tf` per env (stage/prod); `dev`/`test` still get compose |
| `containerize` | pushes to project-configured `container_registry` | pushes to project's auto-provisioned ECR (or override) |
| `release` | `ansible-playbook` over SSH using `infra/deploy_creds/<env>` | SSM push → `RunTask` migration → `tofu apply` → Service Connect consumer reconcile |
| `migrate` (during release) | `compose run --rm` of the codebase's exec service on the host, in the existing internal docker network | ECS `RunTask` against the per-codebase migration task definition |
| `stagetest` (the pre-step only) | `docker inspect` **over SSH** to the deployed host | ECS `list_tasks` / `describe_tasks` / `describe_task_definition` |

Before it builds the stage-tester image, `stagetest` runs an **orchestrator
liveness/version gate** that fails if any core service is unhealthy, on the wrong version,
or unreadable. Three properties of that gate are design commitments (probe output is never
parsed; the "bad answer" and "can't-get-an-answer" error classes are deliberately
distinct; there is deliberately no flag that disables it) — detailed in
[`specifics/subcommand_surface.md § The orchestrator liveness/version gate`](./specifics/subcommand_surface.md#the-orchestrator-livenessversion-gate).
