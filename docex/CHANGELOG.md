# Changelog

All notable changes to `docex` will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

`docex` predates this changelog: versions `0.1.0` through `0.4.0` were the four
build phases, documented step-by-step in `implementation/phase_1.md` through
`implementation/phase_4.md`. Granular change tracking starts below, from the
first post-`0.4.0` overhaul.

## [Unreleased]

### Added

- `PROJECT_VERSION` env var, doctrine-injected on every core service
  container at compile time AND on the stage tester at
  `./bin/docex stagetest` time. Sourced from `project.yml`'s `version:`
  field; emitted as a compose `environment:` entry on fixed and as an
  ECS `environment[]` entry on elastic (not an SSM secret — versions
  are not sensitive). One canonical env var name; one source of truth;
  no drift possible. Backing services are excluded — they run
  third-party software with no application code that would consume
  the var. New validation rule `rule_project_version_reserved`: a
  project that declares `PROJECT_VERSION` under
  `core_services.<svc>.env` or `.secrets` fails compile (doctrine
  owns the name). Mod 011.

- `emits:` + `target:` schema for cross-resource field routing. Engines
  now declare an ordered per-foundation list of emit destinations; the
  first entry is the default target (where `defaults:` and any field
  translation without an explicit `target:` lands). A field translation
  may declare `target: <name>` from that list to land on a non-default
  destination — letting a single field configure something other than
  the engine's primary emitted resource. The destination-name set is
  closed and lives in docex source as `EMIT_DESTINATIONS` in
  `cicl/transfer.py`. Compile-time validation catches unknown emit
  destinations, undeclared `target:` refs, and `target: target_group`
  on services not on the `web` network. New validation issue codes:
  `EMITS_MISSING`, `EMITS_UNKNOWN_DESTINATION`, `FIELD_TARGET_UNDECLARED`,
  `FIELD_TARGET_NOT_APPLICABLE`. Mod 010.

### Fixed

- `health_check_path: /health` on a `web`-network core service now
  reaches the compiled HCL's `aws_lb_target_group` as a nested
  `health_check { path = "/health" ... }` block. Previously the field's
  elastic translation was deep-merged into the ECS task-definition body
  (where its `target_group_health_check:` wrapper was meaningless and
  silently dropped) while the target group resource was emitted with
  hardcoded fields only. ALB fell back to checking `/`, which the
  application didn't serve, and the rolling deploy cycled tasks
  indefinitely on 404s. Fixed by routing the translation via
  `target: target_group` (mod 010's new machinery). The maptrack smoke
  release tripped on this; manual patching the live target group via
  `elbv2 modify-target-group --health-check-path` was the workaround.

### Changed

- `EngineEntry.field_translation()` return type changed from
  `dict[str, Any] | None` to `tuple[str, dict[str, Any]] | None` — the
  string is the resolved target destination, the dict is the
  translation body minus the `target:` key. Internal API only; no
  callers outside docex's own source tree.

- `sslmode` provided part on `relational_db`/`postgres` — compile-time
  constant, `"disable"` on fixed and `"require"` on elastic. Closes the
  one fixed↔elastic difference the parts-only model wasn't hiding:
  local postgres containers accept plaintext while AWS RDS rejects
  non-SSL connections under its default `pg_hba.conf`. Without this
  part, projects' `migrate.sh` and DSN-composing code had to encode
  if/else-on-hostname logic — exactly the cross-foundation coupling
  `provides:` exists to eliminate. The two smoke projects' `migrate.sh`
  files are now byte-identical; both web and worker root.py modules
  consume the new env var. Mod 009.

## [0.8.3] - 2026-06-01

### Fixed

- `pipeline/release.py` steady-state path now runs a targeted
  `tofu apply -target=aws_ecs_task_definition.<svc>_migrate` for each
  schema-owning service before invoking `run_migrate`. Previously the
  migrate step used the LATEST registered task-definition revision —
  which on a steady-state release is whatever was pushed by the
  PREVIOUS release, so any current-release change to a migration
  task-def's body (image tag, env vars, secret refs) was invisible
  to migrate. Implements `release_mechanism.md § Elastic-foundation
  mechanism` step 2, which was prescribed but not implemented. Main
  service task defs are still rolled only after migrations succeed,
  preserving the doctrine's zero-downtime backward-compat window.

## [0.8.2] - 2026-06-01

### Fixed

- Postgres `host` provided part on elastic now resolves to
  `aws_db_instance.<name>.address` (hostname only) instead of
  `aws_db_instance.<name>.endpoint` (which is `host:port` already
  concatenated). The old value made consumers composing `host:port`
  produce `host:port:port` DSNs — DNS lookup fails. Aligns with
  `cicl.md § Provided Fields`'s parts-only contract.
- `pipeline/release.py`'s first-time-release cluster-existence
  probe now applies the `ecs` naming policy to `<project>_<env>`
  instead of literally hyphen-joining them. After mod 005, the live
  cluster name is underscore-form; the literal hyphen-joined probe
  was always missing the cluster and falsely triggering the
  first-time-release branch on steady-state releases (harmless —
  tofu apply is idempotent — but the log message lied).

## [0.8.1] - 2026-06-01

### Fixed

- Every per-network `aws_security_group` emitted in the env-tier
  `main.tf` now carries an explicit allow-all egress block. Terraform's
  `aws_security_group` resource denies all egress when no `egress`
  clause is given — overriding AWS's default — which prevented Fargate
  tasks from reaching SSM, ECR, and other AWS service endpoints.
  Defense-in-depth egress restriction is deferred (see
  `infrastructure.md § Deferred`).
- Postgres `reserved_names` extended with `db`, `template0`,
  `template1`. The doctrine's compile-time `reserved_names` check now
  catches these RDS-rejected DBName values instead of failing at
  `tofu apply` time. Doctrine intent (per `transfer_tables.md`) was
  already to catch reserved-name collisions at compile; this fills in
  the missed entries.

## [0.8.0] - 2026-06-01

### Fixed

- Compose `depends_on` is now emitted in long-form with
  `condition: service_healthy` when the target service declares a
  healthcheck, and `service_started` otherwise. Previously emitted as
  short-form (a flat list), which only waits for the target to start —
  so `docex up dev` and `docex test` would race postgres's
  initialization and fail `migrate.sh` with `connection refused`.
  Surfaced by the new `test_projects/` walks.
- Fixed-foundation `web` network now compiles to a bare external Docker
  network named `web` rather than `${project}_${env}_web`. The
  machine-wide Traefik can only attach to one network and can't reach
  project-scoped ones; the project-scoped form silently broke HTTPS
  routing for every service. `internal` and any other CICL-defined
  networks keep their project-scoped naming (true isolation plane).
  Elastic security groups untouched. Surfaced by C.4 of the fixed
  test_projects walk.
- Compose Traefik discovery labels now include
  `tls.certresolver=doctrine` for each web-routed service. Traefik v3
  doesn't propagate an entrypoint-default cert resolver into a router
  with explicit `tls={}` from labels, so the previous output never
  triggered ACME and served Traefik's self-signed default cert. The
  doctrine prescribes the literal handle `doctrine` as the name of the
  single machine-wide cert resolver.
- Dockerfile installs the `community.docker` ansible collection at
  `/usr/share/ansible/collections` (system-wide), not the build-time
  `$HOME/.ansible/collections`. The runtime in-container user is the
  operator's uid (not root); the previous install path was unreachable
  to it and modules like `community.docker.docker_compose_v2`
  silently failed to resolve.
- Dockerfile sets `ANSIBLE_LOCAL_TEMP=/tmp/.ansible-tmp` and
  `ANSIBLE_PERSISTENT_CONTROL_PATH_DIR=/tmp/.ansible-cp` so ansible's
  runtime scratch dirs don't try to write under `$HOME` (which the
  image doesn't provide as a writable path for the operator uid).
- Emitted `ansible.cfg` uses `stdout_callback = default` +
  `result_format = yaml` (ansible-core 2.13+) instead of the
  deprecated `stdout_callback = yaml` plugin from `community.general`
  (removed in v12).
- Migration tasks in the emitted playbook now use `docker compose run
  --rm <svc> /service/migrate.sh` via `ansible.builtin.command`
  instead of `community.docker.docker_container`. The one-off
  migration container now inherits the application service's full
  environment by definition (image, compile-time-resolved
  `DATABASE_*` env vars, runtime `env_file` secrets, networks,
  depends_on). Side effect: `auto_remove: true` is gone, so when
  migration fails the exit code and logs are captured normally.
- Dockerfile also sets `ANSIBLE_SSH_CONTROL_PATH_DIR=/tmp/.ansible-ssh-cp`.
  The SSH connection plugin's ControlPath directory is separate from
  `ANSIBLE_LOCAL_TEMP` and `ANSIBLE_PERSISTENT_CONTROL_PATH_DIR`, and
  still defaulted to `$HOME/.ansible/cp` — same EACCES failure mode.
- Emitter's playbook migration task now references services by their
  project-scoped global name (`docex-smoke-fixed-stage-web`), not the
  CICL short name (`web`). The compose file's service keys are the
  global form, so `docker compose run --rm <short_name>` failed with
  "no such service".
- `test_projects/fixed/teardown.sh` now loops over both underscore
  and hyphen forms of the project name when sweeping stray docker
  resources by `--filter name=`. Docker's substring match never
  found the actual runtime names (which use hyphens) under the
  underscore project name, leaving stage/prod stacks orphaned after
  teardown.

### Removed

- `_image_for` helper in `src/docex/emit/ansible.py`. Was registered
  as a Jinja variable for the legacy migration playbook task's
  explicit `image:` field; mod 003's switch to `docker compose run`
  made it unreferenced.

### Changed

- `tests/integration/test_up_down_real.py` and
  `tests/integration/test_migrate_real.py` now reference the sample
  fixture's backing service by its current name (`db`) instead of the
  stale `database`. Stale `POSTGRES_DB` / `POSTGRES_HOST` lines in
  `tests/fixtures/sample_project/infra/secrets/dev.env` removed.
- **BREAKING (transfer tables)** — the per-engine inline `naming:`
  struct is replaced by a string reference into a new top-level
  `naming_policies:` table. Project-local transfer tables must
  migrate: e.g. `naming: { separator: hyphen, case: lower, max_len:
  63 }` becomes `naming: rds`. See
  `doctrine/infrastructure/specifics/transfer_tables.md` § Naming
  Policies for the canonical policy set.
- ECS cluster, service, task-definition family, and migration task
  names now use underscore form (matching the project-name
  convention) instead of the previous hyphen form. Existing
  deployments will see tofu plan a recreation of those resources on
  next apply; ECS is stateless and the recreate is safe.
- The OpenTofu state-backend S3 bucket name is now hyphen-translated
  so projects with underscore-bearing names (e.g.
  `docex_smoke_elastic`) pass S3 bucket-name validation. Existing
  buckets retain their old name; new bootstraps create the hyphen
  form. The DDB lock table preserves underscores (DynamoDB accepts
  both, doctrine prefers the project-name form).
- Project-tier ECR repository names, IAM role/policy names, and SSM
  path prefix now route through `ecr_repo`, `iam`, and `ssm_path`
  policies respectively. For projects with underscored names, all
  three now preserve underscores rather than mixing forms.

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
