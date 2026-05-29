# Changelog

All notable changes to `docex` will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

`docex` predates this changelog: versions `0.1.0` through `0.4.0` were the four
build phases, documented step-by-step in `implementation/phase_1.md` through
`implementation/phase_4.md`. Granular change tracking starts below, from the
first post-`0.4.0` overhaul.

## [Unreleased]

### Fixed

- Compose `depends_on` is now emitted in long-form with
  `condition: service_healthy` when the target service declares a
  healthcheck, and `service_started` otherwise. Previously emitted as
  short-form (a flat list), which only waits for the target to start —
  so `docex up dev` and `docex test` would race postgres's
  initialization and fail `migrate.sh` with `connection refused`.
  Surfaced by the new `test_projects/` walks.

### Changed

- `tests/integration/test_up_down_real.py` and
  `tests/integration/test_migrate_real.py` now reference the sample
  fixture's backing service by its current name (`db`) instead of the
  stale `database`. Stale `POSTGRES_DB` / `POSTGRES_HOST` lines in
  `tests/fixtures/sample_project/infra/secrets/dev.env` removed.

## [0.7.0] - 2026-05-29

The first-real-release shake-out: eight bugs surfaced by maptrack's
PART V (first production release of a brand-new elastic project)
that v0.6.0 couldn't reach. The campaign closes out `docex check` /
`merge` / `release` for first-time use, fixes the DooD
permission/path model end-to-end, and adds project-tier IAM +
engine-reserved-name validation that AWS would otherwise flag at
apply time.

### Changed

- **The docex container now runs as the host's uid:gid, with the
  project tree and the operator's HOME mirrored at the same path
  inside the container.** Previously docex bind-mounted the project
  at `/project` and ran as root. v0.7.0 mirrors host paths instead —
  bind-mounts the project at `$PROJECT_ROOT:$PROJECT_ROOT`,
  bind-mounts credentials (`~/.aws`, `~/.docker`, `~/.gitconfig`,
  `~/.ssh`) at the same host path inside the container, mounts
  `/etc/passwd` + `/etc/group` so `getpwuid()` resolves the running
  uid, passes `--user "$(id -u):$(id -g)"` so writes land
  operator-owned on the host, and sets `-w "$PROJECT_ROOT"`. The
  Dockerfile bakes `git config --system safe.directory '*'` for
  defense in depth.
  - Fixes the "dubious ownership in repository at '/project'" failure
    that blocked `docex check`/`merge`/`containerize` whenever the
    host project files were owned by a non-root uid.
  - Fixes the "every file docex writes ends up root-owned" papercut
    that forced operators to `sudo chown -R` after every compile.
  - Fixes the impedance mismatch that made compose's
    `--project-directory` need either an in-container path (works for
    build contexts, breaks bind-mount sources) or a host path (vice
    versa). With paths mirrored, the same value works for both.
  - Migration: projects that already have root-owned files left over
    from pre-fix runs need a one-time
    `sudo chown -R $(id -u):$(id -g) .` in the project root. The shim
    itself is overwritten by `bash docex_install.sh <project>`.
- **The shim now forwards `SSH_AUTH_SOCK`.** When the operator's SSH
  key is held in ssh-agent (no key file on disk), the shim
  bind-mounts the host's agent socket to `/ssh-agent.sock` inside the
  container and sets `SSH_AUTH_SOCK` to that path. Skipped silently
  when `SSH_AUTH_SOCK` is unset on the host. Fixes the
  `Permission denied (publickey)` failure on `docex check`/`merge`
  for agent-only authentication setups.

### Added

- **`docex check` and `docex merge` handle an empty `origin/main`.**
  Brand-new projects (the first PART V release after inception) have
  no `origin/main` yet because the remote was just created and nothing
  has been pushed. `check` now detects this via a new
  `GitClient.ref_exists` probe and skips the trunk-comparing gates
  (`no_merge_conflicts`, `worktree_clean`, `latest_main`,
  `version_bumped`, `version_not_released`) with a clear
  "first-release mode" banner; other gates still run against the
  worktree. `merge` skips rebase entirely on an empty remote and
  instead seeds `main` by fast-forwarding it to the feature branch
  tip, tags `v<version>`, and pushes — publishing `origin/main` for
  the first time. The remote-feature-branch delete is also skipped
  on this path (there's nothing to delete).
- **`docex release` handles the first-time release of an elastic env.**
  Doctrine steady-state order on elastic is `SSM push → migrate →
  tofu apply`, but on the very first release of an env the ECS
  cluster and RDS the migrate step targets don't exist yet — they
  are created by `tofu apply`. The release pipeline now probes the
  env's ECS cluster via a new `AWSClient.ecs_cluster_exists` method;
  when absent, the flow swaps to `SSM push → tofu apply → migrate`,
  so the migration runs against the now-live cluster and RDS.
  Subsequent releases find the cluster present and follow the
  doctrine order. Doctrine: `cicd.md` § Release Step,
  `release_mechanism.md` § First-time release of an env.
- **Reserved-name validation per engine.** Transfer-table engine
  entries now carry an optional `reserved_names:` list. The compiler
  matches each backing-service name against it (case-insensitive) at
  validate time and fails with `rule_engine_reserved_name` if the
  service is named after a reserved engine identifier. The bundled
  `relational_db.postgres` entry lists postgres SQL-reserved keywords
  plus common RDS DBName collisions (`database`, `user`, `admin`,
  `master`, `postgres`, `public`, …). Catches the
  `InvalidParameterValue: DBName database cannot be used` failure at
  `tofu apply` time and gives the operator a fix-now error message
  pointing at the offending service.
- **Project-tier ECS task execution role.** The project-tier HCL now
  provisions an `aws_iam_role` named `<project>-task-execution` with
  the AWS-managed `AmazonECSTaskExecutionRolePolicy` attached (ECR
  pulls + CloudWatch Logs) plus an inline policy granting
  `ssm:GetParameters`/`kms:Decrypt` scoped to the project's SSM
  prefix (so a leaked role can't reach other projects' secrets). The
  role ARN is exposed as the `task_execution_role_arn` output and
  every env-tier `aws_ecs_task_definition` (both the main service
  and migration variants) now sets `execution_role_arn` from it.
  Fixes the `Fargate requires task definition to have execution
  role ARN to support ECR images` failure at `tofu apply` time.

### Fixed

- **`docex check`'s worktree build resolves correctly.** The 0.6.0
  attempt to fix compose path resolution leaned on `COMPOSE_PROJECT_DIR`
  as an env var; compose v2 v5.1.3 does not honor that. v0.7.0 always
  passes `--project-directory` on the CLI and threads a `project_dir`
  override through the `DockerClient` compose methods so `docex check`
  can point compose at the ephemeral worktree's path while the regular
  `up`/`test`/`migrate` paths use the project root. The check pipeline
  also now passes the main project's `infra/secrets/test.env` to the
  worktree build so compose's `${VAR}` substitution warnings don't
  drown the real build output.
- **`docex check` worktree cleanup goes straight to
  `git worktree remove --force`**, with `shutil.rmtree` + `git worktree
  prune` as the fallback. The earlier "try without force first" pass
  was guaranteed to fail when the build left untracked
  `.terraform/`/`dist/` artifacts in the worktree.

## [0.6.0] - 2026-05-28

### Added

- **Project-tier elastic infrastructure.** `docex compile` now emits
  `infra/output/project/main.tf` for elastic-foundation projects,
  describing the VPC, public/private subnets across two AZs, NAT
  gateways, Route53 hosted zone for the project's `domain:`, ACM
  certificate (multi-SAN, with DNS validation records emitted into the
  project zone), and one ECR repository per core service. Each env's
  `main.tf` reads these via `data "terraform_remote_state" "project"`
  (replacing the v0.5.0 tag-based `data.aws_vpc` / `data.aws_subnets` /
  `data.aws_route53_zone` / `data.aws_acm_certificate` lookups, which
  expected resources that nothing in docex actually created).
- **Two-phase `docex bootstrap`.** Bootstrap now creates the state
  backend (existing) and then applies the project-tier HCL in two
  phases: phase 1 runs a targeted `tofu apply` against just
  `aws_route53_zone.project`, prints the zone's NS records, and exits
  so the operator can NS-delegate from the parent (registrar or parent
  hosted zone). Phase 2 (on a subsequent `docex bootstrap` run, once
  the zone is in tofu state) runs an untargeted `tofu apply` for the
  rest of the project-tier resources; ACM cert validation succeeds iff
  delegation has propagated. Phase detection is observed from
  `tofu state list` — same command both times.

### Changed

- **`docex` creates the project's Route53 hosted zone.** Previously
  ambiguous in the doctrine; now explicit per
  [`shape2.md`](../doctrine/infrastructure/shape2.md) and
  [`elastic_bootstrap.md`](../doctrine/infrastructure/specifics/elastic_bootstrap.md):
  the zone is project-tier, `docex` provisions it, and the operator
  performs the NS delegation between the two bootstrap phases.
- **ECR repositories are project-tier.** `docex containerize` no
  longer calls `ecr_ensure_repository` ad-hoc — repos are provisioned
  by `docex bootstrap` alongside the rest of the project-tier infra
  and looked up by the env-tier image ref via
  `data.terraform_remote_state.project.outputs.ecr_repository_<svc>_url`
  instead of the prior `data.aws_caller_identity` interpolation.
- Elastic env-tier `main.tf` now imports project-tier outputs through
  `terraform_remote_state` (state key `project/terraform.tfstate` in
  the same S3 backend) rather than discovering resources by tag.

### Fixed

- `CICLDocument` rejected the documented top-level `repo_url` field (per
  `cicl.md` § Git Repo URL) as extra input, failing compile. It is now
  accepted; the field stays documentary — docex doesn't act on it.
- `SubprocessDockerClient._compose_base` passed `--project-directory`
  computed from the in-container compose-file location, which under
  DooD overrode the shim's `COMPOSE_PROJECT_DIR` (the host project
  root) and made the host's docker daemon try to resolve bind-mounts
  against `/project`. The flag is removed; relative bind-mounts now
  resolve through `COMPOSE_PROJECT_DIR`, which the shim sets to the
  host path and `_compose_env` derives from the compose-file location
  for direct (non-shim) use.

### Removed

- `AWSClient.ecr_ensure_repository` and its boto3 implementation —
  ECR repositories are now provisioned by the project-tier tofu apply,
  and no path in docex still calls this method.

## [0.5.0] - 2026-05-28

The post-`0.4.0` overhaul, driven by first-real-project use: parts-only
backing-service connection info, dev/test + elastic-ECR image refs, the
`docex roles`/`role` reference commands, per-service subdomains with no host
ports, and core-service `secrets:`.

### Changed

- **Backing-service connection info is now parts-only and symmetric across
  foundations.** Engines expose discrete connection parts (`host`, `port`,
  `db`, `user`, `password`); a consuming service references the parts it needs
  and composes its own connection handle at startup. The same `infra.yml` now
  resolves to an identical container env surface on fixed and elastic,
  restoring fixed↔elastic portability. Doctrine: `transfer_tables.md`,
  `cicl.md` (new "Provided Fields" section), `shape2.md`, `release_mechanism.md`.
- Elastic ECS `secrets[]` entries are now named after the **consumer's** env
  key (e.g. `DATABASE_USER`), with `valueFrom` pointing at the underlying
  secret's SSM path (e.g. `/<project>/<env>/POSTGRES_USER`). Previously elastic
  named the container env var after the SSM key, so an app reading
  `DATABASE_USER` worked on fixed but broke on elastic.
- **`dev`/`test` images are now registry-less local tags**
  (`<project>/<service>:<version>`), independent of `container_registry` —
  those envs build locally from the Dockerfile and never pull from a registry,
  so the registry host was meaningless noise. `stage`/`prod` images are
  unchanged (full `<registry>/...` ref).
- `docex describe` now takes the output format as `--format dag|llm` (was a
  trailing positional `<format>` arg), for consistency with `docex roles` /
  `docex role`.
- **`web`-network services no longer publish host ports.** They're reached only
  through the reverse proxy over the project network (Traefik on fixed, ALB on
  elastic), so there's no host-port binding to collide — a web service may use
  any port, including 80/443. Non-web core services are unchanged.
- **Routing is now network-driven, not role-static.** Traefik labels (fixed)
  and the ALB target group + listener rule (elastic) are generated by the
  compiler for any `web`-network service — including backing *containers* on
  fixed — rather than carried as static labels in the `web` role's transfer
  table. ALB listener rules now get unique priorities (was a hardcoded `100`).
- **Elastic ACM cert is now multi-SAN.** The operator-provisioned project cert
  must cover `*.<domain>` plus the per-env wildcards (`*.dev.<domain>`,
  `*.test.<domain>`, `*.stage.<domain>`, `*.www.<domain>`). The compiler emits a
  wildcard `*.<env-subdomain>` Route53 record per env alongside the bare one.

### Added

- Compile-time guard (`rule_composed_secret_forbidden`): embedding a secret
  inside a composed env value (e.g. `DATABASE_URL: "...${...user}..."`) now
  fails compile on every foundation, enforcing the parts-only rule.
- **End-to-end elastic ECR default.** When an elastic project omits
  `container_registry`, `stage`/`prod` image refs resolve to the project ECR
  (`<account>.dkr.ecr.us-east-1.amazonaws.com/...`) via a
  `data.aws_caller_identity` interpolation (account ID resolved at
  `tofu apply`, keeping compile offline-pure), and `docex containerize`
  authenticates to ECR and idempotently ensures each service's repository
  before pushing. New `AWSClient.ecr_authorization_token` /
  `ecr_ensure_repository` and `DockerClient.login`.
- **`default_port` engine field** in the transfer tables. A backing service
  that omits `port:` now resolves its `.port` magic ref from the engine's
  default (postgres → 5432, redis → 6379) instead of resolving to empty.
  Documented in `transfer_tables.md` § Field reference.
- **`docex roles` and `docex role <name>` commands** — the role/parts
  reference. `roles` lists every service role with a description; `role <name>`
  describes a role's engines, provided parts (the magic-ref targets, with
  secret flags), required env vars, and role-specific fields. Both support
  `--format llm` (JSON) for tooling. Backed by a new optional role-level
  `description:` field in the transfer tables; resolves the `cicl.md`
  "how to find provided fields" gap.
- **Per-service subdomains + `domain_default_service`.** Every `web`-network
  service is reachable at `<service>.<env>.<domain>`; the optional top-level
  `domain_default_service` names the one web service that additionally answers
  at the bare `<env>.<domain>` (so `www.<domain>` → the frontend). New
  validation: `domain_default_service` must name a web service, and every
  web-network service must declare a `port`. Doctrine: `cicl.md` § Domain,
  `networks.md`, `shape2.md`.
- **Core-service `secrets:` block.** A core service can declare bespoke,
  operator-supplied secrets (`KEY: "description"`) — API keys, tokens — that
  have no in-project source. They surface in `example.env` (grouped under the
  service) and are wired into the container under the same key on both
  foundations (compose `${KEY}` / ECS `secrets[]`), and pushed to SSM by
  `release`. New validation (`rule_env_secrets_overlap`): a key may not appear
  in both `env:` and `secrets:`.

### Fixed

- The `<project-ecr>/...` placeholder (illegal `<`/`>` in a docker reference)
  that the compiler emitted whenever `container_registry` was absent. It broke
  `docex up`/`test` (dev compose) and produced invalid ECS image refs in
  elastic `stage`/`prod` HCL. Replaced by the dev/test local tag and the ECR
  interpolation above.
- A magic ref that resolved to an empty value (e.g. `.port` on a backing
  service with no declared port and no engine default) silently emitted
  nothing; it is now a compile error.
- Multi-`web`-service routing collision: with two web services, both claimed
  the same `Host(<env>.<domain>)` rule on fixed and the same `host_header` plus
  hardcoded ALB priority on elastic, so neither could be disambiguated.
  Per-service subdomains + unique priorities fix it.

### Removed

- The `url` provided-part from the `relational_db`/postgres and `cache`/redis
  transfer tables.
- The "bare runtime-ref propagation" step in the compose and HCL emitters, and
  the now-dead `CompiledService.runtime_refs` field — a referenced secret
  reaches the consumer under its chosen key, so the engine's canonical var name
  is no longer leaked into the container.
