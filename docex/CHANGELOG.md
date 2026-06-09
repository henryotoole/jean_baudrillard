# Changelog

All notable changes to `docex` will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

`docex` predates this changelog: versions `0.1.0` through `0.4.0` were the four
build phases, documented step-by-step in `implementation/phase_1.md` through
`implementation/phase_4.md`. Granular change tracking starts below, from the
first post-`0.4.0` overhaul.

## [Unreleased]

### Changed

- **ALB moved to project-tier with SNI (BREAKING).** Per
  [`projinfra/elastic_alb.md`](../doctrine/infrastructure/specifics/projinfra/elastic_alb.md),
  the project ALB is now project-tier — one ALB per project, serving
  both stage and prod through SNI cert binding. `project.tf.j2`
  gains `aws_security_group.project_alb`, `aws_lb.project`,
  `aws_lb_listener.project_https` (prod cert as the listener default),
  `aws_lb_listener_certificate.project_stage` (stage cert via SNI),
  `aws_lb_listener.project_http` (80→443 redirect), plus six outputs
  (`alb_arn`, `alb_dns_name`, `alb_zone_id`, both `listener_arn`s,
  `alb_security_group_id`). Env-tier `main.tf.j2` no longer defines
  the ALB; the per-network SG ingress source, the Route53 alias DNS+
  zone references, and the per-web-service listener-rule
  `listener_arn` all read from `data.terraform_remote_state.project`.
  Listener-rule priorities are now env-banded — stage in
  `[1000, 4999]`, prod in `[5000, 9999]` — so they can never collide
  on the shared listener. Mod 038 of the shape-and-tier campaign.

- **Route53 zone + ACM certs aligned with new doctrine (BREAKING).**
  Three real bugs in the existing project-tier HCL fixed:
  (1) `aws_route53_zone.project.name` now `<project>.<apex>` (was the
  bare apex) so the zone is the project subdomain delegated from the
  parent zone, matching
  [`projinfra/elastic_route53_zone.md`](../doctrine/infrastructure/specifics/projinfra/elastic_route53_zone.md).
  (2) Single ACM cert with `*.dev`/`*.test`/`*.www` SANs replaced with
  two ACM certs (stage + prod) carrying the doctrine-spec SANs:
  stage cert covers `*.stage.<p>.<a>` + `stage.<p>.<a>`; prod cert
  covers `*.prod.<p>.<a>` + `prod.<p>.<a>` + `<p>.<a>` (the bare-
  project ergonomic). Dev/test certs live on the per-project traefik,
  not ACM. (3) Single `certificate_arn` output replaced with
  `stage_cert_arn` and `prod_cert_arn`. Env-tier `main.tf` branches
  on the compile-time `env` to consume the right per-env cert ARN.
  `pipeline/bootstrap.py` delegation-instructions print updated to
  reference the project subdomain and the parent-zone delegation
  requirement. Two-phase apply logic itself unchanged. Mod 037 of
  the shape-and-tier campaign.

- **Per-project traefik on per-project `-web` networks (BREAKING).**
  Replaces the obsolete machine-wide-traefik model with the doctrine's
  per-project traefik (per
  [`projinfra/fixed_reverse_proxy.md`](../doctrine/infrastructure/specifics/projinfra/fixed_reverse_proxy.md)).
  `emit_project_compose` now emits a `${project}-traefik` container
  joined to all four `${project}-${env}-web` networks plus
  `docex-ingress`, with the doctrine cert resolver named `doctrine`,
  DNS-01 challenge config sourcing `${TRAEFIK_ACME_EMAIL:-}` and
  `${TRAEFIK_DNS_PROVIDER:-}` from the operator's env, and a
  project-named acme named volume for cert persistence. Traefik image
  pinned by digest via new `TRAEFIK_IMAGE` constant
  (`traefik:v3.3@sha256:2cd5cc7...`). Env-tier compose now references
  the project-tier `${project}-${env}-web` network as `external: true`
  (was the bare host-wide `web` external network).
  `docex projinfra <up|down> <side>` for fixed projects now runs real
  docker-compose against `infra/output/project/<side>/docker-compose.yml`
  via a new `pipeline/projinfra.py` module — single-machine
  convergence means the two sides emit identical content and the
  second `up` is a docker-compose no-op. `down` refuses when any
  env-tier compose stack for the project is still up; the acme volume
  survives `down`. `DockerClient` gains `compose_up`, `compose_down`,
  `any_env_compose_up`. Multi-machine fixed (ansible-at-project-tier)
  stays deferred; mod 042 adds real preinfra preconditions; mod 044
  adds the EC2-traefik elastic alternative. Mod 036 of the
  shape-and-tier campaign.

- **Compiler output split by side (BREAKING).** Project-tier output is
  now organized under `infra/output/project/{development,production}/`
  instead of a single `infra/output/project/`. Both sides emit on every
  project: development side always emits a compose file declaring the
  four `${project}-${env}-web` external networks plus the
  `docex-ingress` preinfra reference; production side switches by
  foundation — compose for fixed projects, `main.tf` for elastic
  projects (relocated from `infra/output/project/main.tf` to
  `infra/output/project/production/main.tf`). `pipeline/bootstrap.py`
  reads from the new path. Env-tier compose is unchanged in this mod;
  the `external: true` flip and per-project traefik addition land in
  mod 036. Pure structural/path mod with no runtime behavior change.
  Mod 035 of the shape-and-tier campaign.

- **Command surface refreshed (BREAKING).** Per the doctrine's
  [`docex.md`](../doctrine/infrastructure/docex.md) command table:
  `bootstrap` is removed; `up` and `down` are collapsed into
  `envinfra <direction> <env>` (dev/test only — stage/prod still
  route via `release`); two new commands `preinfra <side>` and
  `projinfra <direction> <side>` are added with `side` being
  `development` or `production`. `--help` regrouped from the
  internal phase scheme (`Phase 1`/`Phase 2`/…) to purpose-based
  (Introspection / Infrastructure / Development / Pipeline).
  In mod 034 the new commands are mostly stubs that return 0 with
  an explicit `(stub)` notice — the one real branch is
  `projinfra up production` on elastic projects, which runs the
  existing state-backend setup that `bootstrap` used to do.
  Real `preinfra` checks land in mod 042; real `projinfra` behavior
  in mod 036 (fixed) and mods 037–039 (elastic). Internal modules
  `orchestrate/{up,down}.py` and `pipeline/bootstrap.py` keep their
  names. Mod 034 of the shape-and-tier campaign.

- **Fargate tier rounding made visible.** Per the doctrine's now-formal
  "rounding is uniform across all core services" rule
  ([cicl.md § Resources](../doctrine/infrastructure/cicl.md#resources)),
  `_resources_to_elastic` surfaces a one-line notice whenever a core
  service's request rounds to a Fargate tier — not only when the
  sidecar overhead specifically pushed the bump. The notice names the
  cause: project values not landing on a tier, sidecar overhead, or
  both. Pre-existing overflow handling and the 0.1 vCPU + 128 MiB
  sidecar overhead math are unchanged. Mod 033 of the shape-and-tier
  campaign.

- **Telemetry sidecar rename (BREAKING).** All container/service names
  for the OTel sidecar flip from `<svc>_otelcol` to `<svc>-otelcol` per
  the doctrine's data-plane naming unification. Compose form on fixed:
  `${project}-${env}-${svc}-otelcol` (was
  `${project}_${env}_${svc}_otelcol`); ECS form: `${svc}-otelcol`
  (was `${svc}_otelcol`). Mod 030's partial flip left the suffix on
  underscores pending this mod; mod 032 closes that. Doctrine-injected
  OTEL_* env vars on every core service were already wired by prior
  work (mods 011 + 017); no compile.py changes were required to
  satisfy the doctrine bullet about OTEL_SERVICE_NAME,
  OTEL_EXPORTER_OTLP_ENDPOINT, OTEL_EXPORTER_OTLP_PROTOCOL,
  OTEL_RESOURCE_ATTRIBUTES. Mod 032 of the shape-and-tier campaign.

- **CICL surface refresh (BREAKING).** `infra.yml`'s top-level
  `domain:` field is renamed `apex_domain:` and its semantics narrowed:
  the value is now the *bare apex* (e.g. `example.com`,
  `example.co.uk`), not the per-project domain. The canonical service
  host shape is now `<service>.<env>.<project>.<apex_domain>` (e.g.
  `api.dev.myproject.example.com`); the project segment is derived
  automatically from `project.yml`'s `name` and DNS-labeled for
  underscored names. Prod's `domain_default_service` answers at three
  hosts now — `<svc>.prod.<project>.<apex>`, `prod.<project>.<apex>`,
  and `<project>.<apex>` (the bare-project host, replacing the
  old `www.<apex>` convention).
  New compile-time magic vars: `${apex_domain}`,
  `${bare_project_subdomain}`; `${env_subdomain}` redefined to the
  new shape. New elastic-only top-level field
  `reverse_proxy: alb | ec2_traefik_eip | ec2_traefik_pip` (default
  `alb`); fixed-foundation projects rejecting it. New validation rules:
  apex must be bare (rule 13), service-name blacklist
  `{dev, test, stage, prod, www}` (rule 14), `reverse_proxy:`
  elastic-only (rule 18). The `reverse_proxy` role is removed entirely
  — services declaring `role: reverse_proxy` now fail validation
  pointing at mod 031; the reverse proxy is project-tier infra
  (see [projinfra/](../doctrine/infrastructure/specifics/projinfra/)).
  Mod 031 of the shape-and-tier campaign.

- **Naming policy unification (BREAKING).** The `docker` and `ecs` policies
  flip from `separator: underscore` to `separator: hyphen` per the doctrine's
  new default rule: anything name-resolvable on the data plane uses hyphens;
  underscores survive only for inert AWS record-key identifiers (`iam`,
  `ssm_path`, `ddb`). Every Docker container/network/volume name and every
  ECS cluster/service/task-def family/Service Connect identifier flips from
  `${project}_${env}_${svc}` to `${project}-${env}-${svc}`. ECR repo names
  are the same string today (`${project}/${svc}`) but the *mechanism* changes:
  the `ecr_repo` policy is deleted and ECR joins the small set of structural
  emit sites whose names bypass the policy table — required because the
  single-separator policy machinery cannot express the `/`-joined
  two-segment shape with per-segment underscores preserved. Mod 030 of the
  shape-and-tier campaign tracked at
  `docex/plans/campaigns/shape_overhaul_mod_list.md`. Consumer projects
  pinned to a prior `docex_version` keep their existing names; the next
  pinned upgrade after the campaign-completing cut will require a recompile
  and redeploy with new identifier forms.

## [0.12.1] - 2026-06-04

Single-fix patch following the 0.12.0 PRE_CUT walks.

### Fixed

- `docex rollback` now tolerates uncommitted changes under `infra/output/`
  in the operator's working tree. `docex release` rewrites that directory
  implicitly via its compile step, so an emergency operator who just
  released will legitimately have output drift versus HEAD; forcing them
  to commit it before rolling back was friction caught in both the
  fixed and elastic 0.12.0 PRE_CUT walks. Source dirt elsewhere
  (`core/`, contracts, etc.) is still refused. New
  `GitClient.is_clean_excluding(cwd, excludes)` helper backs the check.
- Stale URL assertion in `test_compose_sidecar` (residual from the
  0.12.0 fixture URL update).

## [0.12.0] - 2026-06-04

The rollback campaign. Mod 029 ships the `docex rollback` command per
the doctrine's [`cicd.md § Rollback`](../doctrine/infrastructure/cicd.md#rollback)
narrow-window thesis — emergency-only, code-only (no reverse migrations),
at most one minor version behind, explicit target version. The command
is a thin shell over existing release machinery: an ephemeral worktree
at the target tag, recompile with the current `docex`, mirror the
gitignored credential and secret paths into the worktree, then dispatch
to `_release_fixed` / `_release_elastic` with the new `skip_migrations`
toggle. `--dry-run` previews the apply on both foundations.
Image-presence probes (`docker manifest inspect` for fixed,
`describe_images` for elastic) front-load the precondition gauntlet so
the operator sees the full list of missing images in one shot before
any state is touched.

The mirror step is a post-mod fix surfaced by the 0.12.0 PRE_CUT_CHECKLIST
fixed walk: `git worktree add` does not carry gitignored files, so the
release functions' reads of `infra/deploy_creds/<env>` and
`infra/secrets/<env>.env` would otherwise fail every doctrine-compliant
rollback. Two small fixture fixes also landed during the cut prep — the
sample test fixture's `observability_backend_url` (was `example.com`,
unreachable), and the CHANGELOG-only changes that document the new shape.

### Added

- `./bin/docex rollback <env> <target_version>` — emergency reversion to
  a prior version, code-only, at most one minor back. Per doctrine
  [`cicd.md § Rollback`](../doctrine/infrastructure/cicd.md#rollback).
  Resolves the `v<target_version>` tag in an ephemeral worktree,
  recompiles that version's `infra.yml` with the current `docex`, and
  applies via the standard release machinery with the migrate step
  skipped. Rejects targets more than one minor behind or whose images
  are missing from the registry. `--dry-run` previews the apply on both
  foundations (`ansible --check` on fixed, `tofu plan` on elastic;
  elastic dry-run also skips the SSM push).
- `DockerClient.manifest_inspect(ref)` for registry image-existence
  probes (fixed foundation).
- `AWSClient.ecr_image_exists(repository, tag)` for ECR image probes
  (elastic foundation).
- `run_playbook` learns `skip_tags=` and `check_mode=` so rollback can
  reuse the existing fixed-foundation playbook without template changes.

### Changed

- Extracted ephemeral-worktree helpers (`worktree_path_for`,
  `make_temp_branch`, `cleanup_worktree`) and the SemVer-ish
  `parse_version` from `pipeline/check.py` into a new
  `pipeline/_worktree.py` so `pipeline/rollback.py` can share them.
  Call sites in `check.py` updated; no behavioural change for `check`.

### Fixed

- `docex rollback` now mirrors `infra/deploy_creds/<env>` and
  `infra/secrets/<env>.env` from the operator's project tree into the
  ephemeral worktree before dispatching to `_release_fixed` /
  `_release_elastic`. `git worktree add` does not carry gitignored
  files, and both paths are gitignored by doctrine bootstrap defaults,
  so without this the release functions would always fail on a fresh
  rollback. Caught by the 0.12.0 PRE_CUT_CHECKLIST fixed walk.
- Sample test fixture's `observability_backend_url` updated from
  `hyperdx.example.com` (unreachable) to `hyperdx.luxrnd.tech`,
  fixing `test_check_real_happy_path` which had been broken since
  mod 019 added the reachability gate.

## [0.11.0] - 2026-06-03

The telemetry campaign. Three core mods (017–019) turn the doctrine's
application-telemetry flow from prose into working infrastructure: every
core service gets a paired OTel Collector sidecar exporting to the
project's observability backend, with compile-time validation and a
reachability gate in `docex check` to catch backend misconfigurations
before merge. Mods 020–027 are post-walk hotfixes surfaced during the
0.11.0 PRE_CUT_CHECKLIST walk: otelcol config delivery (file → inline
content with proper `$` escaping), config-vs-secret separation of
`OBSERVABILITY_BACKEND_URL`/`TELEMETRY_API_KEY` on fixed, dropping the
unrealizable wget-based healthcheck (the collector image carries no
probe tool), two `_hcl_value` escape fixes that the multi-line
OTEL_CONFIG_YAML revealed, and a `describe_tasks` eventual-consistency
retry that surfaced during the elastic prod walk.

### Fixed

- Compose `configs.otelcol_config.file` now points at
  `./infra/output/<env>/otelcol-config.yaml` instead of
  `./otelcol-config.yaml`. The latter resolved against compose's
  `--project-directory` (= project root) rather than the compose file's
  directory, so docker tried to bind-mount a non-existent file at the
  project root and `docex test` failed at sidecar startup. Surfaced by
  the 0.11.0 PRE_CUT_CHECKLIST walk. Mod 020.
- Compose `configs.otelcol_config` now uses inline `content:` instead of
  a file mount, so the compose file is self-contained and the otelcol
  config arrives on the deploy host alongside everything else compose
  needs. The previous mod-020 file-mount path resolved correctly under
  local `--project-directory` (= project root) but failed on the
  ansible-rendered deploy host where `--project-directory` is the
  compose file's parent directory and no `infra/output/<env>/` tree
  exists. Symmetric with elastic, which already embeds the config inline
  via `OTEL_CONFIG_YAML`. Surfaced by the 0.11.0 PRE_CUT_CHECKLIST
  fixed-stage release walk. Mod 021.
- Otelcol config's `${env:...}` references in compose's `configs.content`
  are now escaped to `$${env:...}` so docker compose passes them through
  verbatim — without this, compose interprets them as its own variable
  references and aborts with "invalid interpolation format". Elastic
  delivery (via the `OTEL_CONFIG_YAML` env var on the sidecar) is
  unaffected. Surfaced by the 0.11.0 PRE_CUT_CHECKLIST fixed-stage
  release walk after mod 021. Mod 022.
- Fixed sidecar's `OBSERVABILITY_BACKEND_URL` env var is now emitted as
  a literal value from `infra.yml`'s top-level field, not as a
  `${OBSERVABILITY_BACKEND_URL:-}` reference. The previous form looked
  the var up in compose's `.env`, but that file only carries secrets;
  the URL was always empty at runtime, and otelcol crashed at startup
  with "exporters::otlphttp: at least one endpoint must be specified".
  Symmetric with elastic, which already embedded the literal URL on
  the sidecar's ECS `environment[]`. `TELEMETRY_API_KEY` continues to
  flow through compose's `.env` (it IS a secret). Surfaced by the
  0.11.0 PRE_CUT_CHECKLIST fixed-stage release walk. Mod 023.
- `_hcl_value` now escapes `\n`, `\r`, `\t` (in addition to `\\` and
  `"`) when emitting strings. HCL's quoted-string grammar rejects
  literal newlines; the OTEL_CONFIG_YAML value (a multi-line YAML
  literal embedded as an HCL string, added in mod 018) tripped this
  with `Error: Invalid multi-line string` on `tofu init`. Until mod
  018, no emit path produced a multi-line string so the gap stayed
  invisible. Surfaced by the 0.11.0 PRE_CUT_CHECKLIST elastic-stage
  release walk. Mod 025.
- `_hcl_value` now also escapes `$` to `$$` when emitting strings.
  HCL parses `${expr}` as its own template interpolation inside string
  literals (including inside `jsonencode(...)`); the OTEL_CONFIG_YAML
  value carries otelcol's `${env:OBSERVABILITY_BACKEND_URL}` and
  `${env:TELEMETRY_API_KEY}`, which HCL choked on with "Extra
  characters after interpolation expression" because of the embedded
  colon. HCL converts `$${expr}` back to a literal `${expr}` in the
  string value at apply time, so otelcol sees exactly what it expects.
  `HCLLiteral`-wrapped values (legitimate HCL refs like
  `${aws_db_instance.appdb.address}`) bypass this branch and remain
  un-escaped. Symmetric with mod 022's compose-side escape.
  Surfaced by the 0.11.0 PRE_CUT_CHECKLIST elastic-stage release walk
  after mod 025. Mod 026.
- `ecs_wait_for_task` tolerates a brief eventual-consistency window
  after `RunTask`. The poll previously raised `ECSTaskFailed` on the
  very first empty `describe_tasks` response, but ECS sometimes takes
  a second or two to make a fresh task visible. The wait now retries
  for up to 30 s of polling before raising; once the task has been
  observed at least once, an empty response is sharp again (signals
  a vanished task). Surfaced by the 0.11.0 PRE_CUT_CHECKLIST
  elastic-prod release walk: the migration task ran to completion
  (exit 0) but docex bailed on the very first poll before it was
  visible. Mod 027.
- Sidecar healthcheck dropped on both foundations. The
  `otel/opentelemetry-collector` image is built `FROM scratch` and
  carries no `wget`/`curl`/shell — the doctrine-prescribed
  `wget --spider http://localhost:13133` could never succeed. On
  fixed the failing healthcheck was cosmetic (sidecar stayed
  `health: starting` forever but functioned correctly); on elastic
  the core container's `dependsOn HEALTHY` would have blocked startup
  indefinitely. Elastic `dependsOn` now uses `START` instead. Otelcol's
  `health_check` extension still listens on 127.0.0.1:13133 inside the
  shared netns for in-band probes. Mod 024.

### Added

- Compile-time telemetry foundations: `observability_backend_url` toplevel
  field in `infra.yml` (required; https-only, validated); `OTEL_SERVICE_NAME`,
  `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_EXPORTER_OTLP_PROTOCOL`, and
  `OTEL_RESOURCE_ATTRIBUTES` injected on every core service's env block;
  `TELEMETRY_API_KEY` documented as a doctrine-injected required secret in
  `infra/secrets/example.env`. Mod 017. Sidecar emit and reachability probe
  follow in mods 018/019.
- OTel Collector sidecar emitted alongside every core service on both
  foundations. Fixed: paired `<svc>_otelcol` compose service via
  `network_mode: service:<core>`, config rendered to
  `infra/output/<env>/otelcol-config.yaml` and mounted via compose
  `configs:`. Elastic: second container in the same ECS task definition,
  config embedded in `OTEL_CONFIG_YAML` env var, `TELEMETRY_API_KEY`
  delivered via ECS `secrets[]`, core container `dependsOn HEALTHY`.
  Exporter is `debug` on dev/test (stdout), `otlphttp` on stage/prod.
  Mod 018.
- Elastic Fargate task totals now include the sidecar's 0.1 vCPU / 128 MiB
  overhead, tier-rounded; compiler prints a one-line notice when the
  overhead bumps a service into a higher tier than its declared resources
  alone would. Mod 018.
- `docex check` now probes `observability_backend_url` for reachability
  before allowing a merge. Any HTTP response (including 4xx) confirms the
  host is up and TLS works; DNS failure, TLS failure, connection refusal,
  or timeout fails the gate. Mod 019.

### Changed

- `_validate_no_project_version_conflict` generalized to
  `_validate_reserved_env_keys` covering PROJECT_VERSION + the four
  doctrine-injected OTEL_* keys. Failure rule code renamed from
  `rule_project_version_reserved` to `rule_reserved_env_key`.

## [0.10.0] - 2026-06-02

The container-backing campaign. Five mods (012–016) turn project-local
transfer tables into a load-bearing extension surface: strict, source-
attributed loader; destination-keyed elastic dispatch; ECS Service
Connect for intra-env discovery; EFS-backed persistent storage for
stateful container backings on Fargate; and a consolidated authoring
guide. Containerized backing services that aren't first-party project
code (ClickHouse, OpenTelemetry collectors, sidecars of all shapes)
are now first-class on both foundations — same magic-ref shape across
fixed and elastic, foundation-specific machinery hidden behind the
existing `provides:` model.

### Fixed

- **`CompiledService.port` falls back to `engine.default_port` for
  backing services that omit `port:` in `infra.yml`.** Surfaced during
  the docex 0.10.0 elastic smoke walk: a project-local sidecar engine
  declaring `default_port: 80` was loaded correctly and resolved the
  `${port}` substitution variable correctly (line 379 of `compile.py`
  has had the fallback since long ago), but `CompiledService.port`
  itself was set to `svc.port` directly — which is None when the
  project omits `port:`. Downstream emitters (the task definition's
  `portMappings`, the ECS Service Connect `service {}` sub-block)
  read `CompiledService.port` and silently skipped emission when None.
  Bundled engines never exposed this gap because they either are core
  services (always declare `port:` in `infra.yml`) or don't emit port
  mappings at all (RDS, ElastiCache, S3). The fix is a one-line
  fallback in `compile_env`'s `CompiledService(...)` construction.

### Documentation

- **Authoring guide for project-local transfer tables.** New section in
  `transfer_tables.md` consolidating the authoring perspective scattered
  across Mods 012–015: file layout and discovery (flat or nested under
  `roles/`), deep-merge semantics for both engines and naming policies
  (project values override at every leaf; lists/scalars replaced
  wholesale, dicts merged key-by-key), guidance on when to add a new
  engine to an existing role vs. when to define a wholly new role, and
  two complete worked examples — a stateless container backing
  (sidecar/nginx) and a stateful one (analytics_db/clickhouse with
  `persistent_storage` and the project-opt-in `backups` field). Closes
  the campaign-goal "document deep-merge nature of naming policies"
  item and gives project authors a single section to read when standing
  up their first project-local engine. Mod 016.

### Added

- **EFS support for stateful container-backing services on Fargate.**
  New optional engine field `persistent_storage: { mount_path: ... }`
  declares a container needs a durable data directory. New emit
  destination `efs_file_system` (added to `EMIT_DESTINATIONS["elastic"]`).
  Engines that need EFS declare both — bidirectional validation at
  load time catches either declared alone. The compiler emits, per
  such service: `aws_efs_file_system` (encrypted at rest using the
  AWS-managed KMS key), `aws_efs_mount_target` per private subnet
  (attached to the service's non-`web` SGs; NFS port 2049 covered by
  the existing `internal` SG self-ingress), a `volume` block on the
  `aws_ecs_task_definition` referencing the EFS by ID with
  `transit_encryption = "ENABLED"`, and a `mountPoints` entry on the
  container definition linking the volume to the declared
  `mount_path`. Volume name is the doctrine-fixed handle `"data"` —
  one EFS per stateful service, mounted at one path. Backups are
  **project-opt-in**: an engine that emits `efs_file_system` may
  declare a `backups` field with `target: efs_file_system` (Mod 010's
  field-routing mechanism); the project sets `backups: true` on the
  backing service in `infra.yml` to enable. When enabled,
  `aws_efs_backup_policy` ties the filesystem to the AWS Backup
  default plan. Default disabled — only the project knows whether
  the data is replaceable cache or irreplaceable user state. EFS
  access points, lifecycle policies, and throughput tuning are out
  of scope for v1. On fixed, `persistent_storage` is informational
  only — engines manage their own docker named volume via
  `defaults.fixed.volumes`. Doctrine: `transfer_tables.md` § Persistent
  storage on Fargate. Mod 015. This is what makes ClickHouse-on-elastic
  structurally viable.

- **ECS Service Connect over a Cloud Map HTTP namespace for intra-env
  service discovery on elastic.** One
  `aws_service_discovery_http_namespace` per env (named
  `<project>_<env>`), declared at the env tier alongside the ALB and
  ECS cluster. Every `aws_ecs_service` carries a
  `service_connect_configuration` block with `enabled = true`; services
  with a declared port additionally register a `service {}` sub-block
  exposing the port as discoverable (`discovery_name` = the service's
  global name, `client_alias.dns_name` = the same). Services without a
  port (e.g., a port-less worker) participate as clients only — they
  can resolve peers but aren't themselves discoverable. Container
  `portMappings` entries gain a `name = "<short_service_name>"` field
  so Service Connect's `port_name` reference resolves. Discovery name
  equals the engine's `provides.host.elastic` template output
  (`${global_service_name}`), so the same magic-ref value works on both
  foundations — Docker network DNS on fixed, Service Connect on
  elastic. Closes the structural gap where consumer-of-container-
  backing magic refs (`SIDECAR_HOST: ${backing_services.sidecar.host}`)
  evaluated to a name that didn't resolve to anything. Doctrine:
  `shape2.md` § Elastic-Foundation table. Mod 014.

### Changed

- **Elastic HCL emit is now dispatched by emit destination, not by
  engine name or `is_core`.** The old hardcoded
  `_ENGINE_TO_RESOURCE = {"postgres": "aws_db_instance", "redis": ..., "s3": ...}`
  map is gone; the dispatch reads each engine's own `emits.elastic`
  list (the existing transfer-table field) and routes to a
  per-destination renderer. The render layer is now six independent
  functions — `render_task_definition`, `render_ecs_service`,
  `render_target_group`, `render_rds_instance`,
  `render_elasticache_cluster`, `render_s3_bucket` — wired through a
  `_DESTINATION_RENDERERS` dispatch table. `render_task_definition` is
  shared between core services and container-backing services;
  `is_core` is consulted only for the migration task-def sub-emission
  on schema-owning core services. Bundled engines (postgres, redis,
  s3, web/container) produce equivalent HCL — same resources, same
  fields, identical SSM data sources. The new capability: a
  project-local backing-service engine declaring
  `emits.elastic: [task_definition, ecs_service]` (the canonical
  pattern for a containerized backing service like ClickHouse,
  OpenTelemetry collector, or any non-bespoke sidecar) now renders
  as an ECS Fargate task instead of producing an
  `# unknown engine` comment. Doctrine: `transfer_tables.md` §
  Container-backing services on elastic, plus the clarified `emits:`
  paragraph in § Anatomy of a Role Definition. Mod 013.

- **Transfer-table loading is now strict and source-attributed.** Unknown
  top-level keys, unknown engine sub-keys, unknown naming-policy
  sub-keys, and unknown `emits:` destinations are hard errors at load
  time. Every error names the source YAML file (relative path:
  `tables/...` for bundled, `infra/transfer_tables/...` for
  project-local) and the position within it (top-level key, role,
  engine, policy name). Plausible typos within Levenshtein distance 2
  of a known key get a "did you mean X?" suggestion; otherwise the
  full allowed-key list is shown. Identical strictness for bundled and
  project-local tables — a bug in a bundled table fails the same way a
  bug in a project-local table does. Doctrine: `transfer_tables.md` §
  Failure-mode contract, `cicl.md` § Validation Rules (rules 11 and 15
  enforced at load time). Mod 012.

- `test_validate_emits_unknown_destination` rewritten to assert against
  the new load-time error site instead of the old downstream
  `EMITS_UNKNOWN_DESTINATION` issue rule — the failure now surfaces
  earlier and with source attribution.

## [0.9.0] - 2026-06-02

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

- `tests/integration/test_stagetest_real.py` references corrected:
  was passing `network_override=f"{project}_dev_web"` (mod 002's
  fixed-`web` exception means the compiled network name is just
  `web`, not project-scoped) and a hyphenated container hostname
  (mod 005's `docker`/`ecs` naming policy is underscore-preserving).
  Latent test failure since v0.6.0; surfaced by the campaign-end
  integration sweep — a sweep that the now-clearer
  `docex_process.md § Run expensive tests` makes part of every
  future pre-cut routine.

### Changed

- `docex_process.md § Run expensive tests` clarified — explicitly
  names the design LLM agent as the responsible party for running
  both integration tests (`pytest -m integration`) and the
  PRE_CUT_CHECKLIST walks, replacing an ambiguous `(you)` that
  could read as either the operator or the agent. Also tightened
  the cost asymmetry: integration tests run unconditionally; the
  smoke-walk step pauses for operator authorization because it
  creates real cloud resources.

- `EngineEntry.field_translation()` return type changed from
  `dict[str, Any] | None` to `tuple[str, dict[str, Any]] | None` — the
  string is the resolved target destination, the dict is the
  translation body minus the `target:` key. Internal API only; no
  callers outside docex's own source tree.

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
