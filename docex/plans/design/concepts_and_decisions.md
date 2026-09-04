# Cross-Cutting Concepts

`docex` is delivered as **a container image + a project-local shim**. The concepts below
cut across every command; the reasoning behind the load-bearing ones is captured in the
ADRs (see [`adr_index.md`](./adr_index.md)) so this state doc stays a snapshot rather
than an argument.

## Distribution

- The image is built from the `docex/` subtree of the `jean_baudrillard` repo. For now
  this happens **locally** on the developer's machine; the resulting image lives in the
  host's Docker image store and projects reference it from there. Publishing to a public
  registry is deferred until cross-machine sharing is needed.
- Tags are **patch-level only**: `docex:1.2.3`. No floating tags (`docex:1`,
  `docex:1.2`, `docex:latest`). Floating tags silently re-point on every release, which
  directly undermines doctrine's promise of deterministic execution.
- The base image is pinned **by digest** (`FROM python:3.12-slim@sha256:...`), not tag,
  to immunize old releases against upstream base-layer churn.

The determinism rationale is [ADR 0002](./adrs/0002_patch_only_tags_digest_pinned_base.md);
that a single image bundles *all* doctrine tooling behind one version pin is
[ADR 0001](./adrs/0001_single_bundled_docex_image.md).

## The Shim

`./bin/docex` is a small, version-independent bash script checked into every project. It
reads `docex_version` from `project.yml`, constructs the `docker run` invocation with the
full mount set (mirroring host paths inside the container so DooD path resolution agrees
in both directions), and passes through the CLI args. One shim serves every `docex`
version; changes to it are kept additive and backward-compatible, so it is not pinned per
version. It also implements **opt-in host-resolved git credentials** (per-operation
brokering through the host's `git credential fill`) for environments whose git auth is a
credential helper rather than a static key — see
[ADR 0006](./adrs/0006_host_brokered_git_credentials.md).

The full mount set, flag rationale, and the credential-passthrough mechanism are detailed
in [`specifics/the_shim.md`](./specifics/the_shim.md).

## Version Pinning

The single version pin lives in `project.yml` (`docex_version: "1.2.3"`). When the shim
runs, it reads this field and uses it as the image tag. Bumping `docex` for a project is
a one-line change. One pin governs all bundled tooling — that lockstep is the
**coherence** requirement, argued in
[ADR 0001](./adrs/0001_single_bundled_docex_image.md).

## What `docex` Bundles vs. What It Doesn't

**Bundled (lives in the image):** the Python CLI (command dispatcher, CICL compiler, all
orchestration code); the canonical
[transfer tables](../../../doctrine/infrastructure/specifics/transfer_tables.md); the
Ansible playbook template used by fixed-foundation releases (rendered per project by
`compile`); the CLI dependencies `docker`, `tofu`, `ansible`, `aws`, `git`, `jq` plus the
Python runtime; and the doctrine prose excerpts that back `docex why`.

**Not bundled (lives in the project):** per-codebase `build.sh` / `test.sh` / `health.sh`
/ `migrate.sh`; per-codebase `Dockerfile`s; language runtimes and toolchains for project
code; project-local transfer-table extensions at `infra/transfer_tables/` (deep-merged
at compile time); and the stage-tester image definition and stage tests.

**Principle:** `docex` orchestrates; per-codebase containers do language-specific work.
The `docex` image never needs Node, Go, or a codebase-specific build environment — it
just invokes `docker` and friends correctly.

## Docker-outside-of-Docker

`docex` needs to build, tag, push, and run containers on behalf of the project. It does
this via the **DooD** pattern: the `docex` container runs the `docker` CLI, but the CLI
talks to the **host's** docker daemon over a mounted socket. No nested daemon, no
`--privileged`, no special VM tricks. DinD is rejected as slower, more dangerous
(requires `--privileged`), and unnecessary here — the full trade-off, and the
host-path-mirror consequence below, are
[ADR 0003](./adrs/0003_docker_outside_of_docker.md).

Four consequences worth being explicit about:

1. **Containers `docex` spawns are siblings, not children.** When `docex envinfra up dev`
   runs `docker compose up`, the resulting containers attach to the host's docker, not to
   docex. They outlive the docex invocation — `docex envinfra up` returns immediately and
   the dev stack keeps running.
2. **Paths are host-relative for spawned containers.** The compose files reference project
   paths (build contexts, bind-mount sources for `src/` and `dist/`) that must resolve to
   something the host's docker daemon can find. The shim mirrors the host project path
   inside the container — `$PROJECT_ROOT` is mounted at `$PROJECT_ROOT` (not at a fixed
   `/project`) — so any path docex emits is simultaneously a valid in-container path (for
   compose's client-side reads) and a valid host path (for the daemon's bind-mount
   resolution). Compose receives the project directory via `--project-directory` on the
   CLI, because docker compose v2 does not honor `COMPOSE_PROJECT_DIR`.
3. **The in-container user matches the host user.** The shim passes
   `--user "$(id -u):$(id -g)"`, mounts `/etc/passwd`/`/etc/group` from the host, and
   mirrors `$HOME` inside the container. Files docex writes to the project tree are
   operator-owned on the host (no `sudo chown -R` after every compile), `git` doesn't trip
   on dubious-ownership, and tools that resolve the running user via `getpwuid()` (ssh)
   find a coherent home directory matching the credential mounts.
4. **The compose project name is pinned explicitly, not derived.** `--project-directory`
   governs *path resolution* only; it does not decide the Compose **project name** (the
   `com.docker.compose.project` label). docex passes an explicit `--project-name` on every
   compose invocation — `<project_dns_label>-<env>` for env stacks,
   `<project_dns_label>-projinfra` for the project tier — rather than letting Compose
   derive one from the directory basename. The project-tier name is deliberately
   side-independent so that on a single-machine fixed host the dev and prod sides converge
   on one Compose project: `up production` after `up development` adopts the existing
   resources and reconciles to a no-op instead of colliding on the shared traefik
   container. A path-derived name was project-unscoped (every project's projinfra stack
   resolved to the literal `infra`) and unstable across docex versions, which broke
   idempotent re-runs and left `-web` networks unremoved on `down`; pinning the name makes
   Compose's adopt-on-rerun and teardown deterministic and project-scoped.

## Credentials & Ambient Host State

`docex` consumes credentials and host state from well-known locations; it does **not**
manage credential storage itself. Container-registry auth comes from
`~/.docker/config.json`; AWS API access from `~/.aws/credentials` (or env/OIDC); SSH to
fixed hosts from `infra/deploy_creds/<env>` plus `~/.ssh/known_hosts`; git identity from
`~/.gitconfig` and `~/.ssh/`; the docker daemon from `/var/run/docker.sock`. An opt-in
path brokers git remote auth through a host credential helper per-operation (see The Shim
above). If a required credential is missing, `docex` fails loudly with a message pointing
at the conventional location, never with a silent fallback. The per-command source/consumer
matrix is in [`specifics/the_shim.md`](./specifics/the_shim.md).

## Foundation Parity

Several commands branch internally on `foundation:` from `infra.yml`, but the shim and
command surface stay symmetric — the divergence is internal, never exposed to the
developer. The `dev` and `test` environments are always fixed regardless of declared
foundation, per
[shape.md § Shape and Environment](../../../doctrine/infrastructure/shape.md#shape-and-environment).
The full fixed-vs-elastic behavior table is in the
[Deployment View](./structures_and_views.md#deployment-view).

## Ephemeral Git Worktrees

`docex check` (and defensively, `docex merge`) performs git operations against a merged
state without disturbing the developer's working tree; `docex rollback` uses the same
helpers to check out `v<target_version>` and recompile that version's `infra.yml` with the
*current* `docex`. A temporary worktree is created under `.docex/worktrees/<command>-<discriminator>/`
(gitignored), the feature tip is rebased onto a fresh `origin/main`, the gates + compile +
build + test run there, and the worktree is removed on success or failure alike — the
developer's branch and main are untouched either way. Because `check`/`merge` run as
durable jobs in a detached vessel, a hard-killed vessel's leaked worktree is reclaimed by
the next run's preflight reaper. Detail in
[`specifics/release_flow.md § Worktree mechanism`](./specifics/release_flow.md#worktree-mechanism)
and the durable-job design, [ADR 0005](./adrs/0005_durable_job_substrate.md).

## The contract and shim gates

`docex check` runs a roster of gates that read a project's declared boundaries and codebase
layout — the provider set is exactly the core services declaring `surfaces:`; contract
format follows the surface's `api_styles`; contract paths parse right-anchored on four
segments; an orphan arm fails a contract file matching no declared surface; and
`health.sh` is a required per-codebase shim. The rule of record is
[`contracts.md`](../../../doctrine/infrastructure/contracts.md) and
[`healthchecks.md`](../../../doctrine/infrastructure/healthchecks.md); the full gate roster
and the defects each guards against are in
[`specifics/subcommand_surface.md § The contract and shim gates`](./specifics/subcommand_surface.md#the-contract-and-shim-gates).

# Solution Strategy

- **Deliver as one versioned image + a thin shim.** All deterministic tooling lives in the
  image behind a single version pin ([ADR 0001](./adrs/0001_single_bundled_docex_image.md));
  the shim is version-independent and additive-only.
- **Act on the host via DooD**, mirroring host paths and the host user into the container
  ([ADR 0003](./adrs/0003_docker_outside_of_docker.md)).
- **Hide foundation behind the command surface.** Commands branch internally on
  `foundation:`; the developer drives the same verbs on both.
- **Make long-running commands durable jobs.** `test`, `check`, and `merge` run in a
  detached sibling vessel with an on-disk run record and a self-healing reaper
  ([ADR 0005](./adrs/0005_durable_job_substrate.md)).
- **Gate the pipeline, keep it hand-drivable.** `check` → `merge` → `containerize` →
  `release` → `stagetest` is an explicit documented sequence, not a megacommand.

# Risk, Unknowns, and Tech Debt

## Escape hatches for project edge cases

Rigidity is the doctrine's promise; total flexibility would undermine it. Three layers of
escape hatch, in order of preference:

1. **Project-local transfer tables.** `infra/transfer_tables/` is deep-merged with the
   bundled tables at compile time — the primary valve for project-specific quirks (adding
   an engine, overriding a default, declaring a new role).
2. **Upstream the fix.** If a project hits a genuine doctrine gap, the right answer is
   usually to fix it in `docex` itself, cut a new version, and let other projects benefit.
3. **Fork and pin.** A project that genuinely needs different compiler or orchestration
   behavior can fork the image, build their own, and pin to that. Painful by design —
   friction forces honest answers to "is my project really that special?"

## Upstream tool drift

The container model contains this risk: `docex:1.2.3` bakes in specific versions of
`tofu`, `ansible`, the docker CLI, the AWS CLI, and the Python runtime, so projects pinned
to a version keep working even if an upstream releases a breaking change. The doctrine
maintainer absorbs testing new upstream versions and cutting new releases; downstream
projects opt in at their own pace. Real risks to plan for:

- **Base layer rot** — mitigated by pinning the base image by digest and (optionally)
  mirroring published images to a registry under our own control.
- **Catastrophic upstream changes** — unlikely for OpenTofu (Linux Foundation) or Ansible
  (Red Hat), but a new backend would be needed if either happened; existing projects on
  old `docex` versions are unaffected.
- **AWS API churn** — the elastic foundation depends on the AWS API surface (SSM, ECS, S3,
  DynamoDB, ECR, RDS); a breaking change would force a docex release, and existing projects
  upgrade only if they need the changed API.

## Compatibility matrix

`docex` publishes an explicit compatibility matrix in the doctrine repo — which OpenTofu,
Docker, Ansible, AWS CLI, and Python versions each `docex` minor supports. This makes the
dependency surface visible, gives users a deprecation story, and lets old-version users
know what they are locked into.
