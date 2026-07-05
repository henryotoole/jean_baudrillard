# Changelog

All notable changes to the **Jean Baudrillard doctrine** — its doctrine prose,
its skills, and the `docex` executor — are documented in this file under one
doctrine-wide version (see [`RELEASING.md`](./RELEASING.md)).

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Before `1.3.0` the doctrine had no unified version and this changelog tracked
`docex` alone; those historical entries (everything `1.2.0` and earlier) are
`docex`-scoped and retained verbatim below. `docex` itself predates the
changelog too: versions `0.1.0` through `0.4.0` were the four build phases,
documented step-by-step in `implementation/phase_1.md` through
`implementation/phase_4.md`. Granular change tracking starts below, from the
first post-`0.4.0` overhaul.

## [Unreleased]

### Fixed

- **`projinfra down production` no longer wedges on `HostedZoneNotEmpty`** (mod
  072, campaign 002). The elastic Route53 child zone is emitted with
  `force_destroy = true`, so `tofu destroy` sweeps records tofu doesn't own —
  the dev `A`-records that NS-delegation forces into the child zone (dev is
  fixed and routed out-of-band), plus stale ACM validation CNAMEs — instead of
  failing the zone delete and orphaning the zone. `projinfra down production`
  now also prints a reminder to remove the parent-zone NS delegation, which is
  the operator's to manage (docex has no scope over the parent zone), mirroring
  the delegation instructions printed on `up`.

## [1.4.3] - 2026-07-02

### Changed

- **`reverse_proxy: ec2_traefik_*` now routes via the traefik ECS
  provider** (mod 070) — closing campaign **bug 6**, the last blocker on
  making EC2-traefik functional. The path booted and served (mods 062–067)
  but returned **502** for every backend: the EC2 instance lives in the
  master VPC but *outside* the ECS mesh, and ECS Service Connect resolution
  is mesh-internal (per-task Envoy) with no VPC-DNS A-records — so the old
  "resolve `<discoveryName>.<namespace>`" premise could never work. The
  instance now runs traefik's built-in `providers.ecs`, which polls the
  project's stage+prod clusters (`refreshSeconds: 15`), reads each `RUNNING`
  Fargate task's ENI private IP directly, and builds routers/services from
  `traefik.*` `dockerLabels` emitted onto each web service's ECS task
  definition. This is the elastic analog of the fixed-foundation project
  traefik's docker provider: routing intent lives on the workloads, and
  **`release` no longer touches traefik**. Removes the release-time SSM
  routing push (mod 064), the on-instance config-sync systemd timer, the
  `aws_ssm_parameter` routing param, and `emit/traefik.py`; adds a
  read-only, cluster-scoped ECS/EC2 discovery grant to the traefik IAM
  role. Also quotes non-identifier HCL object keys in `_hcl_value` (the
  dotted label keys), and fixes a stale mod-062 test that still asserted
  the pre-IMDSv2 metadata-curl form. Doctrine: `ec2_traefik.md`,
  `shape.md`, `transfer_tables.md`, `release.md` corrected to the
  ECS-provider model.

- **ec2_traefik: ECS clusters moved to the project tier, and the LE cert
  path fixed** (mod 071) — the two follow-on bugs the first real-AWS
  ec2_traefik walk surfaced *after* mod 070 proved routing works (verified:
  `GET /health` returned 200 through traefik → ECS-provider → Fargate).
  - **Bug 8 — traefik built zero routes at a first-release.** traefik's ECS
    provider treats a `ListTasks` error on *any* configured cluster as fatal
    for the whole refresh; the instance lists both stage+prod clusters
    statically, so a stage-first-release (prod cluster absent) produced a
    blanket 404. Fix: provision both `${project}-stage` / `${project}-prod`
    ECS clusters at the **project tier** (empty clusters are free) for all
    elastic projects — both reverse_proxy paths — so the provider's cluster
    list always resolves. Env-tier release attaches services via
    `terraform_remote_state` cluster ARN. First-release detection (and the
    `projinfra down` live-env gate) switch from `ecs_cluster_exists` to a new
    `ecs_cluster_has_services` probe, since the cluster is now always present.
    Doctrine: `shape.md` gains an `ecs_cluster` (project-tier) row;
    `projinfra.md` / `release.md` / `cicd.md` / `migrations.md` reconciled.
  - **Bug 7 — Let's Encrypt cert never issued.** Two stacked causes:
    (1) traefik's route53 DNS-01 provider failed with `Invalid Configuration:
    Missing Region` — fixed by setting `AWS_REGION` / `AWS_DEFAULT_REGION` on
    the `traefik.service` unit; (2) once that cleared, issuance 403'd because
    lego's route53 provider calls `route53:ListHostedZonesByName` (to discover
    the zone) and the traefik IAM policy granted only `ListHostedZones` — the
    missing action is now added.

  **Both elastic reverse-proxy paths verified end-to-end on real AWS**
  (`us-east-1`): `ec2_traefik_eip` — routing 200 through traefik → ECS
  provider → Fargate, plus a real Let's Encrypt cert over HTTPS (no `-k`);
  `alb` — routing 200 through the ALB with a valid ACM cert, target group
  `docex-smoke-elastic-stage-web-tg` at exactly 32 chars. The
  fixed-foundation smoke walk was **not** re-run for this patch (the changes
  are elastic-path-only bug fixes; the sole elastic consumer is the smoke
  project).

### Fixed

- **ALB / target-group / ALB-SG `name` identifiers overflowed AWS's
  32-char cap for realistically-named projects** (mod 069). All three
  route through the `alb` naming policy, whose `max_len: 32` previously
  *hard-errored* on overflow — so `reverse_proxy: alb` (the default
  elastic path) failed to compile for a project like
  `tactical-lifecycle-test` (its target group `tactical-lifecycle-test-stage-web-tg`
  is 36 chars). Naming policies gain an `overflow: error | hash_truncate`
  field (default `error`, unchanged for every other policy); the `alb`
  policy uses `hash_truncate`, which keeps a readable prefix and appends a
  6-hex-char SHA-256 suffix so the identifier always fits 32 and stays
  unique/deterministic. The full descriptive name now lives in the
  resource's `Name` tag — and `aws_lb_target_group`, which previously
  emitted **no** tag block at all, now carries the standard envinfra tags
  (descriptor `ALB-TG`).

## [1.4.2] - 2026-07-02

### Fixed

- **`bin/docex` shim reported exit 1 on success under git-credential
  passthrough.** When `DOCEX_GIT_CREDENTIAL_PASSTHROUGH` is set (as the Periscope
  runner sets it), the shim's credential branch runs an `EXIT INT TERM` cleanup
  trap that `kill`s the responder — then repeats that same `kill` inline before
  `exit "$status"`. The `exit` re-fired the trap, whose now-redundant `kill` hit
  an already-dead process and returned non-zero; under `set -e` that became the
  shell's exit status, so **every** docex command reported failure on success
  (and clobbered genuine non-zero codes to 1 as well). Callers that judge by
  output were unaffected, but exit-code-sensitive consumers — notably the
  Periscope tactical **retire** flow — read the false failure and wedged. Fixed
  by clearing the trap (`trap - EXIT INT TERM`) before the inline cleanup, so it
  cannot re-fire on the explicit `exit`. Adds `tests/unit/test_shim_exit_code.py`
  pinning exit-code propagation on both the fast and credential paths (the shim
  had no prior test coverage — which is how this shipped).

## [1.4.1] - 2026-07-01

### Added

- **Service-level "flow" tests in the test taxonomy.** New doctrine guidance
  (`hexagonal_architecture/hex_overview.md`, `infrastructure/tests.md`) defining
  flow tests — integration tests that drive a whole core service from the
  outside against real driven adapters, asserting *behavior* (not the contract's
  shape) — with the flow-vs-contract distinction, the `flows/`/`contracts/`
  tests-folder layout, and a `testing`-skill update. Backward-compatible.

### Fixed / Changed

- **`reverse_proxy: ec2_traefik_*` — compile + boot chain repaired (mods
  062–067); the path is NOT yet end-to-end functional.** EC2-traefik had never
  been runtime-tested and carried a chain of bugs, surfaced by real-AWS smoke
  walks of the elastic test project:
  - **062** — user_data heredoc `${}`/`%{}` collided with HCL interpolation →
    `tofu` parse failure. Now escaped (`emit/hcl.py`).
  - **063** — user_data apt-installed `awscli`/`amazon-cloudwatch-agent`, absent
    on Ubuntu 24.04 → boot abort. Now AWS CLI v2 bundle + best-effort CW agent.
  - **064** — `release` never pushed the traefik routing config to SSM (stayed
    the empty stub). Now rendered from stage+prod web services and pushed
    (`emit/traefik.py`).
  - **065** — user_data used token-less IMDS under IMDSv2-required → boot abort.
    Now uses IMDSv2 tokens.
  - **066** — the traefik instance lacked `purpose=ec2_traefik_acme`, so the
    `AttachVolume` IAM grant denied the volume attach → boot abort. Now tagged.
  - **067** — user_data ships its bring-up log to CloudWatch (observability;
    the Nitro serial console is unreliable and SSM was SCP-denied).

  Verified on real AWS: the instance now boots fully and traefik serves.
  **Known limitation — do not advertise ec2_traefik as working yet:** backend
  routing returns 502 because ECS **Service Connect** names are not
  VPC-DNS-resolvable from the out-of-mesh EC2 traefik instance (bug 6,
  architectural), and the Let's Encrypt cert path is unconfirmed (bug 7). A
  follow-on campaign will register web services via ECS **Service Discovery**
  (Cloud Map DNS). Until then use `reverse_proxy: alb` on elastic. Full detail:
  `docex/plans/modifications/_campaign_ec2_traefik_functional.md`.

- **`docex`'s opt-in host git-credential passthrough now brokers a *fresh*
  credential per in-container network op** (mod 068, supersedes mod 061's
  resolve-once injection). Previously the shim resolved the `origin` credential
  **once** at invocation and baked a static `store` copy into the container.
  Brokered tokens (GitHub App installation tokens) are hard-capped at ~1h, so a
  `docex` command doing long work before its in-container git op — notably
  `merge`, whose defensive `check` (cold build + service tests) runs for minutes
  before the `fetch`, with the `push` later still — could outlive the baked token,
  and in-container git cannot re-broker: `docex merge` died with
  `fatal: could not read Username … (exit 128)` on every dev box using brokered
  git (lifecycle finding B2). The shim now forwards **each** in-container
  `git credential` request back out to the host's own `git credential fill` over a
  Unix socket (a host-side `responder.py` + an in-container `forward.py` helper,
  both written at runtime into a mode-700 temp dir), so every fetch/push mints a
  fresh short-lived credential. Passthrough mode now also requires `python3` on
  the host (for the responder). Unset signal ⇒ byte-for-byte the prior static
  path; scoped to `https` origins; fails open. Shim-only change — no `docex` image
  rebuild and no `src/` change.

## [1.4.0] - 2026-06-26

### Added

- **Opt-in host-resolved git credential passthrough in the `docex` shim**
  (mod 061). docex runs git inside its container and authenticates via the
  operator's static host credentials (`~/.gitconfig`, `~/.ssh`, ssh-agent) mounted
  in. That cannot cover an environment whose git access is brokered by a
  `credential.helper` backed by host-local state (a helper binary, a socket) — the
  failure mode being `docex merge` dying at its first network op with
  `could not read Username` on such a machine. When the environment sets
  `DOCEX_GIT_CREDENTIAL_PASSTHROUGH`, the shim now resolves the project's `https`
  `origin` credential on the host via `git credential fill` (git's own machinery,
  so docex stays agnostic to the helper) and injects the short-lived result into
  the container as a `store`-helper entry (a mode-600 file in a mode-700 host temp
  dir, mounted read-write — git's `store` helper rewrites it on a successful auth —
  removed when docex exits, kept off the container env; the shim does not `exec`
  when a credential is staged so the cleanup actually runs). Unset ⇒ byte-for-byte the prior
  static behavior; scoped to `https` origins; fails open. Shim-only change — no
  `docex` image rebuild and no `src/` change. Doctrine: generalized
  `credentials.md` § Git Host Credentials and reconciled the shim's
  version-independence wording in `docex.md`.
- **Production-teardown trigger-eval queries** added to the `skill-iteration`
  eval suite (`skill_iter/eval/queries.json`): project-tier production teardown
  routing to `projinfra-setup`, plus the teardown-vs-rollback near-miss that must
  route to `cicd-pipeline`. Preinfra teardown is left uncovered by deliberate
  choice. Eval-data only — no doctrine, skill, or `docex` behavior change.

## [1.3.2] - 2026-06-25

### Added

- **`setup.sh` now pre-registers the Playwright MCP server** used by the
  `browser-investigate` skill, via a new sub-script
  [`setup/claude/mcp.sh`](./setup/claude/mcp.sh). Previously the first use of
  `browser-investigate` had to register the stdio MCP server and then restart
  the session before the `browser_*` tools were live. Because `setup.sh` is run
  through `doctrine-update` — which already ends by telling the operator to
  start a fresh session — the server now boots in that session and the skill
  works on first use, with no extra restart.
- **Canonical pin file** [`setup/claude/playwright_mcp.json`](./setup/claude/playwright_mcp.json)
  is the single source of truth for the digest-pinned Playwright MCP image,
  consumed by `mcp.sh`. The `browser-investigate` SKILL.md no longer embeds a
  second copy of the pin — it points at this file, ending the drift risk of two
  hand-maintained digests.

### Changed

- `mcp.sh` registers at **user scope** (`~/.claude.json` `mcpServers`) with a
  **compare-and-replace** guard: it rewrites the entry only when the desired
  command+args differ from what's registered, which both keeps re-runs
  idempotent and picks up a digest bump automatically. It degrades gracefully
  (warns, never fails `setup.sh`) when the `claude` CLI or Docker is absent, and
  best-effort `docker pull`s the pinned image so the first `browser_navigate`
  isn't a cold pull.

## [1.3.1] - 2026-06-24

### Added

- **Backfilled the missing `1.2.0` upgrade guide** —
  [`upgrades/upgrade_1.2.0.md`](./upgrades/upgrade_1.2.0.md)
  (`kind: incremental`, `scope: [project]`). Covers mod 060's breaking
  master-VPC re-tag (semantic identity tags, with the once-per-account /
  add-before-delete coexistence caveat), the recompile-and-redeploy for the new
  elastic tag standard, and the `preinfra` dev-DNS gate, widened `check` curl
  gate, `scheduler` role, and multi-label-TLD `web_demux` notes from mods 054/
  055/058/059. The `1.2.0` release shipped without it; the tape now chains
  cleanly across the `1.1.0 → 1.2.0 → 1.3.0` span.

## [1.3.0] - 2026-06-24

The release that **unifies versioning across the whole repo**. Before 1.3.0 the
only version was `docex`'s; doctrine prose and skills rode along uncut. From
1.3.0 there is one doctrine-wide version covering doctrine prose, skills, and
`docex` together. No `docex` behavior changed — this is a MINOR, and no project
needs to repin, recompile, or redeploy (see
[`upgrades/upgrade_1.3.0.md`](./upgrades/upgrade_1.3.0.md)).

### Added

- **Doctrine-wide version.** `VERSION` at the repo root is the single source of
  truth; `RELEASING.md` documents the release process (a generalization of the
  former `docex`-only cut). SemVer now tracks the whole repo's observable
  contract — a breaking *doctrine rule* is a MAJOR, not just a `docex` CLI break.
  The four carriers (`VERSION`, `pyproject.toml`, `__init__.py`, `plugin.json`)
  and the `docex:<version>` image tag are synced at every release.
- **Upgrade-guide tape.** `upgrades/` holds one guide per release that needs
  action, named `upgrade_<version>.md`, chained by release order.
  `upgrades/README.md` defines the schema (`version`/`severity`/`kind`/`scope`
  frontmatter) and the chaining rule, including the `kind: rebuild`
  short-circuit for start-point-agnostic rebuilds.
- **Two operator skills.** `doctrine-update` refreshes the operator's machine
  (pull + `setup.sh` + report the delta); `project-upgrade` moves a project onto
  a newer doctrine version by walking the guide chain. Both pass the suite-level
  trigger eval at 100% (recall + precision 1.0, no poaching of existing skills).

### Changed

- **`CHANGELOG.md` moved to the repo root** and made doctrine-wide; all
  historical `docex` entries (`1.2.0` and earlier) were relocated here verbatim.
  `docex/CHANGELOG.md` is now a pointer stub.
- **`.claude-plugin/plugin.json` version synced to the doctrine version**
  (was stranded at `0.1.0`). The Claude plugin cache is keyed on it, so the bump
  is what makes `setup.sh` re-runs reliably land skill changes from now on.
- **Release tags are now `v<version>`** (bare), not `docex-v<version>`;
  `docex_process.md`'s "Cutting a version" section now defers to `RELEASING.md`
  and keeps only `docex`-development specifics. Historical `docex-v*` tags remain.
- **`upgrading_to_1.1.0.md` relocated** to `upgrades/upgrade_1.1.0.md`, stamped
  `kind: rebuild`, with its internal links repointed for the new location.

## [1.2.0] - 2026-06-23

### Added

- **Resource tagging standard** — every elastic resource docex emits now carries
  one of three tag blocks (preinfra / projinfra / envinfra) per the operator's
  `cicl.md § Naming and Tagging`: `managed_by`, `infra_tier`, `shape_name`,
  `descriptor`, and a console-only `Name`, plus `project`/`env`/`service`/`role`
  where the tier defines them. New single-source helper `src/docex/emit/tags.py`
  (`standard_tags` + `render_hcl_tags`, also a Jinja global) feeds every emit site
  (`emit/hcl.py`, `cicl/compile.py`, `templates/{project,main}.tf.j2`) and the
  bootstrap state-backend API path (S3 bucket + DynamoDB table now tagged via
  boto3). Env-scoped resources (ECS cluster, Service Connect namespace, network
  SGs) keep all tag keys with `service=etc`/`role=etc` and a descriptor-based
  `Name` fallback so Names stay unique. **Breaking:** the master-VPC
  data-source/precondition lookup moved off `Name=docex-master-vpc` +
  `managed_by=docex-preinfra` onto the semantic tags `managed_by=doctrine-operator`
  + `infra_tier=prerequisite` + `shape_name=master_network` — existing master
  networks must be re-tagged (see `elastic_master_network.md § Migration`). Drops
  the ACM `env=` tag, the traefik SG `purpose=ec2_traefik` tag, the ECR `service=`
  tag, and the network SG `network=` tag (now the descriptor); keeps the load-
  bearing `purpose=ec2_traefik_acme` on the ACME EBS. Mod 060.

- New bundled **`scheduler` role** — a core service that runs the project's image
  + `command` on a 5-field cron `schedule`, then exits (a cron job in the
  project's image). Fixed: a per-service `mcuadros/ofelia` container launches the
  job as a one-off container (`job-run`, auto-removed) on schedule, configured via
  a rendered INI; non-secret env is inlined while secrets arrive through a mounted
  `.env` sourced by the command. Elastic: an `aws_scheduler_schedule` (EventBridge
  Scheduler) invokes ECS `RunTask` on a reused task definition, with a per-service
  scheduler-invocation IAM role; no `ecs_service`. The compiler translates the
  5-field cron to AWS `cron(...)` (6-field, `?`-day rule, day-of-week 0–6→1–7
  remap) and to ofelia's seconds-prefixed form, validating it at compile time. New
  `src/docex/cicl/cron.py`; new `scheduled_task` emit destination. Scheduler tasks
  carry no OTel sidecar on either foundation (sidecars pair only with long-running
  services); job-level SDK telemetry is deferred. Mod 055.

- `preinfra development` now verifies every `dev` `web`-service hostname
  resolves in public DNS, failing the check (before `envinfra up dev`) when one
  doesn't. Bringing `dev` up fires Let's Encrypt HTTP-01 challenges; unresolved
  hostnames fail every challenge and trip LE's failed-authorization rate limit,
  which then blocks legitimate issuance. Surfacing missing dev DNS as a preinfra
  gap turns a silent rate-limit lockout into an actionable error. Resolution
  uses `dnspython` (new dependency) rather than `getaddrinfo`, so it queries
  real nameservers and ignores `/etc/hosts` — it sees what LE sees. New
  `docex.dns` client seam (`DnsResolver` protocol + `DnspythonResolver`). Mod 054.

### Fixed

- Elastic migrate RunTask now discovers the master VPC by the **mod-060 semantic
  identity tags** (`managed_by=doctrine-operator` + `infra_tier=prerequisite` +
  `shape_name=master_network`), not the retired `Name=docex-master-vpc` /
  `managed_by=docex-preinfra` scheme. Mod 060 migrated the `preinfra.py` and
  `project.tf.j2` VPC filters but missed `orchestrate/migrate.py:_lookup_master_vpc`,
  so `docex migrate`/`release <env>` on elastic failed to find the VPC after a
  master network tagged with the new scheme. The three filters now share one
  imported constant (`_MASTER_VPC_TAGS`) so they can't drift again. Caught by the
  1.2.0 elastic smoke walk. Mod 060.

- `docex check`'s curl gate (`_gate_healthcheck_tooling`) now covers **every**
  core service that declares `health_check_path`, not only those on the `web`
  network. A `role: web` service on a non-`web` network (e.g. `[internal]`) still
  gets a `curl` Docker healthcheck emitted; the old `on_web` filter skipped it,
  so a curl-less such image escaped the gate and would mark itself `unhealthy` at
  runtime (breaking any `depends_on: service_healthy` on it). Now matches
  `infrastructure.md`'s "any core service that declares a `health_check_path`."
  Doctrine was already correct; this is a code-scope fix. Mod 059.

- Fixed-foundation `web_demux` (HAProxy) now routes projects on **multi-label
  TLDs** (`.co.uk`, `.com.au`, …). The SNI/Host → project parse was 3rd-from-last
  label, correct only for single-label TLDs; it is now Public Suffix List-aware
  (loads the PSL, derives the apex as public-suffix + 1 label, takes the label to
  its left), so any TLD parses. Doctrine-side change (the demux is
  operator-managed preinfra in `fixed_master_network.md`: new PSL-aware
  `project_resolver.lua`, a mounted `public_suffix_list.dat`, and a PSL download
  step); `docex` carries only a comment fix in `emit/compose.py`. Mod 058.

### Changed

- `.gitignore` defaults (inception flow) extended with `.docex/`, a Python
  bytecode + tool-cache block, editor/IDE and `*.log` noise, and a note to add
  language-specific patterns per stack; `.terraform.lock.hcl` is documented as
  committed (not ignored), matching the determinism promise. The two smoke-test
  seed `.gitignore`s were reconciled to the new default (dropping a stale comment
  and the elastic seed's erroneous lock-file ignore). Doctrine-side change lives
  in `inception.md`; `docex` carries only the seed reconciliation. Mod 056.

- The `test` env is no longer routed by traefik: its `web`-network services emit
  no traefik discovery labels (no router, no `tls`, no `certresolver`), so the
  project traefik never requests LE certs for `test` hostnames nobody browses
  to. `test` services keep the `docex.project` label and stay on the `-web`
  network. `dev`/`stage`/`prod` are unchanged. Mod 054.

## [1.1.1] - 2026-06-17

### Removed

- Dockerfile: dropped the vestigial `COPY ansible/ /opt/docex/ansible/` line.
  The top-level `ansible/` directory was always empty, nothing in the image
  ever read `/opt/docex/ansible/`, and the fixed-release playbook template
  actually lives at `src/docex/emit/templates/playbook.yml.j2` (bundled via
  the `src/` copy). Removed the now-deleted empty directory.

### Changed

- `plans/core/masterplan.md`: corrected the repo-structure tree (removed the
  `ansible/` entry) and the "Bundled" list so the playbook-template reference
  points at its real home under `src/docex/emit/templates/` rather than a
  separate top-level `ansible/` directory. Resolves the doctrine/code drift
  between the masterplan, the Dockerfile, and `src/`.

## [1.1.0] - 2026-06-11

The post-shape-overhaul polish campaign — mods 049–053. Per-mod narratives
live under `plans/modifications/049_*` … `053_*`. Closes Gaps A–K plus the
pre-cut smoke-walk findings (mod 053, F1–F18); validated by both
test-project smoke walks per `PRE_CUT_CHECKLIST.md`.

### Added

- **`GitClient.remote_exists` (Gap C).** New Protocol method (impl:
  `git remote get-url <remote>` exit code) so `merge` can detect a
  missing `origin`.
- **`DockerClient.compose_ps_status` (Gap K).** New Protocol method
  returning each service's coarse state (`running` / `restarting` /
  `unhealthy` / `exited` / `created`) via `compose ps --all --format
  json`, handling both the JSON-lines and JSON-array shapes compose v2
  emits.
- **`naming.dns_label` helper (Gap J).** Public single-source-of-truth
  for the `underscores → hyphens, lowercased` DNS-label rule. `compile.py`'s
  former module-private `_dns_label` now delegates to it.
- **`SSHClient` (Protocol + subprocess impl) (Gap G).** New three-place
  client (`src/docex/ssh/`) exposing `run(host, key_path, command, *,
  user="deploy") -> int` over `ssh -i <key> -o BatchMode=yes -o
  StrictHostKeyChecking=accept-new -o ConnectTimeout=10`. Surfaces the
  remote command's exit code (or SSH's own `255` on connect failure).
- **Fixed-production registry-credential preinfra probe (Gap G).**
  `run_preinfra` gains a lazy `ssh` param; the `(fixed, production)`
  branch SSHes to both the stage and prod hosts (apex-derived via
  `dns_label`, reusing `infra/deploy_creds/<env>` keys) and verifies the
  registry credential exists at `/home/deploy/.docker/config.json` and
  `/root/.docker/config.json`.
- **`docex check` healthcheck-tooling gate (Gap I, mod 051).** New
  `_gate_healthcheck_tooling` builds each `health_check_path`-declaring
  web service's `prod`-target image and probes for `curl`
  (`command -v curl`); on absence it fails the gate descriptively
  (the Docker healthcheck would otherwise error, the container would be
  marked `unhealthy`, and Traefik would silently drop the route). Turns
  a silent unhealthy-route-death into a loud, early failure.
- **ECS container logs → CloudWatch (Gap E, mod 052).** Elastic ECS task
  definitions now emit an `awslogs` `logConfiguration` on **every**
  container — the application container, the OTel sidecar, and the
  `_migrate` container — pointing at a new per-(env, service)
  `aws_cloudwatch_log_group` (30-day retention, `managed_by` tag). The
  three containers share the group, distinguished by
  `awslogs-stream-prefix` (`app` / `otelcol` / `migrate`). The log-group
  name's `/<project>/<env>/` prefix uses the raw, underscore-preserving
  project form so it falls under the task-execution role's existing
  `log-group:/<project>/<env>/*` IAM scope; `awslogs-create-group` is
  not set (the role lacks `CreateLogGroup` — tofu owns the group).
  Container stdout/stderr (crashes, a failing `migrate.sh`) is now
  captured on elastic.
- **Safe elastic teardown (Gap F, mod 052).** `docex envinfra down` now
  tears down elastic `stage`/`prod` env-tier (`tofu destroy` of the env
  `main.tf`) behind a deletion-protection pre-flight gate that **refuses
  before destroying anything** if any RDS instance in the env is
  deletion-protected (docex never disables a protection itself). `docex
  envinfra up` stays dev/test-only. `docex projinfra down production`
  automates the elastic project-tier teardown (`run_projinfra_elastic_down`,
  the inverse of `run_bootstrap`): refuse-if-envs-up, ECR-emptiness
  pre-flight, project-tier `tofu destroy`, then SSM + state-backend
  (S3 bucket + DynamoDB lock table) cleanup — replacing the manual
  `teardown.sh` path. New `tofu_destroy` runner plus narrow
  `rds_protected_instances` / `ssm_delete_parameters` / `s3_delete_bucket`
  / `ddb_delete_table` / `ecr_repository_image_count` `AWSClient` methods.

### Fixed

- **`docex merge` hard-failed on a repo with no `origin` (Gap C).** The
  unconditional `git fetch origin` / `git push origin` aborted before
  the rebase/tag on remote-less repos (e.g. the test projects). `merge`
  now detects a missing `origin`, skips fetch/push, rebases onto local
  `main` (or seeds `main` when absent), and still tags — matching the
  walker's manual `git merge --ff-only`. The remote feature-branch
  delete is skipped when there's no origin; the local delete still runs.
- **Display strings printed the raw underscored project name for
  hyphenated DNS resources (Gap J).** Swept onto `naming.dns_label`:
  - `src/docex/pipeline/bootstrap.py:181` — the Route53 hosted-zone name
    in `_print_delegation_instructions` (`project_subdomain` at line
    ~178) now prints e.g. `docex-smoke-elastic.luxrnd.tech`, matching
    the emitted zone, instead of `docex_smoke_elastic.luxrnd.tech`.
  - `src/docex/pipeline/stagetest.py:74` — `STAGING_URL` project segment
    routed through `dns_label` instead of an inline `.replace`.
  - `src/docex/orchestrate/up.py:130` — the "Stack up … Domain:" bare-env
    host project segment routed through `dns_label` instead of an inline
    `.replace`.
  - Left raw on purpose: ECR-repo/SSM/IAM/DDB identifiers (e.g.
    `rollback.py`, `release.py`), which legitimately keep underscores,
    and the `project {project!r} fully bootstrapped` machine-name message.
- **`docex envinfra up dev` surfaced no per-service diagnosis on a
  partial bring-up (Gap K).** `run_up` now scans each core service's
  container state after a failed `compose up` or migration and prints a
  one-line diagnostic per `restarting` / `unhealthy` / `exited` service
  (`docker logs` hint, env-var/healthcheck guidance). Diagnosis only —
  no auto-fix, no teardown.
- **First fixed `docex release` failed at image pull with a registry
  `401`, with nothing catching it earlier (Gap G).** `docex preinfra
  production` (fixed) now verifies the target host carries the registry
  credential before release, failing with a `docker login <registry>`
  resolution at the preinfra tier instead of at `docker compose pull`.
- **`docex build` couldn't distinguish a restarting dev container from
  an absent one (Gap D).** When the requested service isn't in the
  running set, `build` now consults `compose_ps_status`; a
  `restarting` / `unhealthy` container yields a targeted diagnostic
  (state + `docker logs` hint) rather than the generic "run 'docex up
  dev' first." (The chicken-and-egg core was already closed by
  `up.py::_ensure_initial_dev_build`.)
- **Fixed-foundation project traefik couldn't issue Let's Encrypt certs
  (Gap A, mod 051).** `emit_project_compose` configured the **DNS-01**
  ACME challenge (`dnschallenge.provider=${TRAEFIK_DNS_PROVIDER:-}`),
  which needs DNS-provider API credentials that never reached the
  traefik container — so routers fell back to traefik's self-signed
  default and stage tests rejected the cert. Switched fixed to
  **HTTP-01** (`httpchallenge=true` + `httpchallenge.entrypoint=web`),
  which proves control by serving a token on `:80` (already forwarded by
  the HAProxy demux) and needs no DNS-provider creds. Per-host certs, no
  wildcards on fixed; elastic keeps its ACM DNS-01 wildcards. The dead
  `TRAEFIK_DNS_PROVIDER` reference is gone; `TRAEFIK_ACME_EMAIL` stays
  (HTTP-01 still registers an LE account).
- **Per-project traefik registered foreign routers / spammed ACME
  failures (Gap B, mod 051).** The traefik docker provider had no
  constraint, so it watched every `traefik.enable=true` container on the
  shared `docex-ingress` bridge (other projects' preinfra and env
  services). `emit_project_compose` now emits
  `--providers.docker.constraints=Label(`docex.project`,`<label>`)`, and
  every container docex emits on fixed — env-tier core + backing
  services, their OTel sidecars, and the project traefik itself — carries
  a matching `docex.project=<label>` label so the project traefik scopes
  to its own project only.
- **Compose project identity was wrong, unscoped, and unstable (mod 053,
  F11/F12).** docex never passed `--project-name`, letting Compose derive
  it from the basename of `--project-directory`; `_resolve_project_dir`'s
  fixed "up 4 levels" was correct for env-tier files but **off-by-one**
  for project-tier files (one level deeper), so every projinfra stack ran
  under the generic name `infra`. Consequences: `projinfra up development`
  aborted on a Docker name conflict when a prior traefik existed (not
  idempotent), and `projinfra down development` left the four `-web`
  networks behind (their project label ≠ `infra`), emitting `not created
  for project` warnings. Fix: `_resolve_project_dir` now walks up to
  `project.yml` (true root for both tiers); `_compose_base` takes an
  explicit `project_name`; every env/project compose call site passes a
  stable, DNS-labeled, project-scoped name — env-tier
  `<dns_label>-<env>`, project-tier `<dns_label>-projinfra-<side>`, and a
  worktree-unique `<dns_label>-check-<sha>` for `check`'s throwaway
  stack. `any_env_compose_up` now DNS-labels the project name so its
  refuse-if-envs-up targets match the real stack names.
- **ACME named volume diverged from the doctrine name (mod 053).**
  `emit_project_compose` declared the volume without an explicit `name:`,
  so Compose prefixed it (e.g. `infra_…-traefik-acme`), diverging from the
  `${project_dns_label}-traefik-acme` name `fixed_reverse_proxy.md`
  prescribes. Now emitted with an explicit `name:` (matching the env-tier
  volume pattern).
- **Fargate-tier rounding notice printed 2–4× per command (mod 053,
  F17).** The "resources rounded to Fargate tier" note printed once per
  elastic env pass (stage + prod) and `run_compile` runs several times per
  command. `run_compile` now threads a per-run dedup set so each unique
  notice prints once.
- **Elastic `projinfra up production` phase-2 failure misdirected
  debugging (mod 053, F13/F14).** On a phase-2 `tofu apply` failure docex
  printed a canned "NS delegation not propagated" cause and told the
  operator to re-run the stale `docex bootstrap`. Now it points at the
  real tofu error (streamed above) as the primary cause, demotes the NS
  hint to a conditional secondary note, and names the current command
  (`./bin/docex projinfra up production`). All operator-facing
  `docex bootstrap` strings replaced.
- **`release` (fixed) warned it couldn't create `~/.ansible` (mod 053,
  F6).** The `bin/docex` shim now `mkdir -p "$HOME/.ansible"` and mounts
  it (mirroring the existing `~/.docker` handling) so ansible's local
  state has a real, writable host source.
- **`preinfra production` (fixed) printed a known_hosts warning (mod 053,
  F3).** docex's SSH probe wrote to the read-only `~/.ssh` mount. The
  `SubprocessSSHClient` now passes `-o UserKnownHostsFile=/dev/null`
  alongside `accept-new`, so the short-lived probe has a throwaway
  writable sink and the noise is gone.

### Test-project seeds (mod 053)

- **Teardown ordering (F18).** `test_projects/{fixed,elastic}/teardown.sh`
  now run `projinfra down development` **before** clearing `infra/output`
  (the down reads the compiled project compose file), so the dev-side
  traefik + four `-web` networks are removed rather than orphaned. With
  the compose-identity fix above, the `-web` networks now actually get
  removed. Both teardowns also clear `infra/output/project`.
- **`verify_clean` underscore coverage (F15).** `elastic/verify_clean.sh`
  now checks both the hyphenated and underscored project-name forms for
  IAM roles, SSM parameters, and DynamoDB tables, so an orphaned
  underscored resource (e.g. `docex_smoke_elastic_task_execution`) is
  reported instead of masked.
- **Stage-test TLS verification (F7).** `fixed/infra/stage/tests/
  test_smoke.py` drops the stale `verify=False` (Gap A made HTTP-01 real
  certs work); the client now verifies the real LE cert, aligning with the
  already-verifying elastic stage test.
- **`PRE_CUT_CHECKLIST.md` (F1/F2/F8).** Removed the `TRAEFIK_DNS_PROVIDER`
  prerequisite and documented `TRAEFIK_ACME_EMAIL` as optional (fixed
  certs use HTTP-01); documented that `check`/`merge` require a feature
  branch and that `compile` must precede `projinfra up`.

## [1.0.3] - 2026-06-09

Patch cut bundling three runtime bugs surfaced during the post-1.0.2
elastic-foundation smoke walk on the test project. Full narrative in
[`plans/modifications/048_elastic_walk_polish/`](plans/modifications/048_elastic_walk_polish/).
Combined with mod 047's fixed-side bug bundle, both smoke walks now
run clean against this cut from D.1/C.1 through D.13/C.11.

### Fixed

- **`projinfra up development` stubbed on elastic projects (mod 048,
  bug 5).** Dispatcher's `(foundation=elastic, side=development)`
  branch printed `(stub): real behavior lands in mods 037-039` and
  exited 0 without standing up the project-tier compose. The
  development side of an elastic project is mechanically identical to
  a fixed dev side (same emit shape — same four `-web` networks + per-
  project traefik); routing the case to the existing
  `run_projinfra_fixed_{up,down}` runners closes the gap. `down
  development` follows. `down production` on elastic still informs the
  operator to run `teardown.sh` manually (no automated path yet).
- **`migrate.py` lookups used pre-mod-041/040 forms (mod 048, bug 6).**
  `_lookup_project_vpc` filtered `describe_vpcs` by `tag:project=<n>`
  (pre-mod-041 per-project-VPC scheme) — renamed to
  `_lookup_master_vpc` and re-filtered against the master VPC tags
  (`Name=docex-master-vpc, managed_by=docex-preinfra`). The env-tier
  SG-name lookup also used the underscored `<project>_<env>_internal`
  form (pre-mod-040); now uses the hyphenated form
  `<project_dns>-<env>-internal` matching what `main.tf.j2` emits.
  Without these fixes, the migration RunTask on the first elastic
  release failed with `no VPC tagged project='<n>'`.
- **Bare-project A-record missing on prod env-tier ALB emit (mod 048,
  bug 7).** The doctrine ([`elastic_route53_zone.md`](../doctrine/infrastructure/specifics/projinfra/elastic_route53_zone.md))
  commits to five A-records on prod — including
  `<project>.<apex_domain>` (bare-project) for `domain_default_service`
  ergonomics. `main.tf.j2`'s env-tier ALB block emitted only the env
  subdomain + wildcard (4 of 5); the bare-project record never landed.
  ALB listener rules already include the bare-project host in their
  `host_header.values` — the gap was purely DNS-side. Template now
  emits a third `aws_route53_record` resource gated on
  `reverse_proxy == "alb" && env == "prod"`; HCL render context picks
  up `bare_project_subdomain` from the compiled env.

### Tests

- `tests/unit/test_dispatcher.py::test_projinfra_elastic_dev_side_routes_fixed_style`
  replaces the old "stubs on elastic dev/down" test. Parametrized over
  `(up, development)`, `(down, development)`, `(down, production)` —
  the first two assert the fixed-style code path is reached, the third
  asserts the "no automated path yet" fall-through message.
- `tests/conftest.py::FakeAWSClient.lookup_master_vpc` replaces the
  prior `.lookup_project_vpc` shim (mirrors the production code's
  function rename).

### Known gaps still open

- **Project traefik AWS-cred propagation** for ACME DNS-01. Open from
  mod 047; smoke project still works around with `verify=False` on
  fixed-side stage tests (elastic side uses real ACM certs, unaffected).
- **ECS task-def `logConfiguration`.** Open from
  `release_flow.md § Common failure modes`. Future mod.

## [1.0.2] - 2026-06-09

Patch cut bundling four runtime bugs surfaced during the post-1.0.1
fixed-foundation smoke walk on the test project. None were caught by
unit tests; they only appeared once the projinfra → envinfra → release
pipeline ran against a real host. The mod docs at
[`docex/plans/modifications/047_smoke_walk_polish/`](plans/modifications/047_smoke_walk_polish/)
carry the full narrative.

### Fixed

- **Traefik 3.3 docker-provider docker-API mismatch (mod 047).**
  `TRAEFIK_IMAGE` was pinned to `traefik:v3.3`, whose docker provider
  negotiates with the host daemon at Docker API v1.24 — a version
  modern (24+) Docker daemons no longer accept. The per-project traefik
  came up but never picked up env-tier service labels; the entire
  doctrine fixed-foundation routing path was unreachable on any host
  running a recent daemon. Bumped to `traefik:v3.6` (digest pinned).
- **`traefik.docker.network` label missing (mod 047).** The
  `_traefik_labels` emit in `src/docex/emit/compose.py` did not include
  `traefik.docker.network=<web-net>`, so traefik 3.x picked the
  container's network non-deterministically when forming the backend
  URL — often the `-internal` network that traefik isn't on, producing
  504 Gateway Timeout on every routed request. Label is now emitted on
  every web-network service. `_traefik_labels` signature grew
  `project_dns_label` and `env` parameters; the single call site at
  `emit_compose` passes them from `compiled`.
- **`docex check` `health_endpoints` gate over-strict (mod 047).** The
  gate required `/health/<dep>` on the provider's contract for *every*
  non-web downstream dep, including backing services. Doctrine
  [`contracts.md § Health Checks`](../doctrine/infrastructure/contracts.md#health-checks)
  is explicit: only CORE-service downstream deps need the endpoint.
  Narrowed `_gate_health_endpoints` to look up `infra.core_services`
  only. Backings don't trip the gate; projects that voluntarily add
  `/health/<backing>` endpoints (mirroring the doctrine pattern for
  reachability they care about) remain free to.

### Known gaps surfaced (not fixed in this cut)

- **Project traefik doesn't get DNS-provider creds.** docex emits
  `--certificatesresolvers.doctrine.acme.dnschallenge.provider=
  ${TRAEFIK_DNS_PROVIDER:-}` on the per-project traefik command line,
  but the emitted compose has no `environment:` block — so AWS_*
  (Route53) or any other provider's creds set on the operator's shell
  never reach the traefik process. ACME fails, traefik serves with its
  self-signed default cert, and downstream stage tests reject the cert.
  The proper fix involves design decisions (which providers' env vars
  to thread through? secret-mounting strategy?) that warrant their
  own mod. Smoke projects work around with
  `httpx.Client(verify=False)` in stage tests.
- **Per-project traefik not constrained to its project.** The traefik
  watches every container with `traefik.enable=true` on `docex-ingress`,
  including other projects' preinfra traefiks (HyperDX, container
  registry). Wrong; should use `--providers.docker.constraints` with a
  per-project label. Future mod.
- **`docex merge` requires `origin`.** Test projects deliberately don't
  carry git remotes; `docex merge` exits non-zero on `git fetch
  origin`. Smoke walker did the rebase + tag by hand. Future mod should
  add a no-origin fallback.
- **Empty-`dist/` chicken-and-egg.** First `docex envinfra up dev`
  against a fresh project tree crash-loops the web container with
  `python: can't open file '/service/dist/root.py'` because the host
  `dist/` bind-mount overlays the in-image artifact, and `docex build`
  refuses to populate while the dev container is crash-looping. Worked
  around by running `build.sh` host-side once. Future mod.

## [1.0.1] - 2026-06-09

Patch mod closing the residual data-plane naming-policy leak sites the
1.0.0 cut shipped. Surfaced by the post-1.0.0 test-project re-inception:
several emit paths interpolated `${project_name}` directly without
passing the project segment through the appropriate naming policy, so an
underscored project name (e.g. `docex_smoke_elastic`) leaked into
Docker container/network names, OTel sidecar names, the project traefik
container, the Route53 zone name, the ACM cert SANs, the EC2-traefik
boot DNS-update script, and the Service Connect namespace. The Route53
and ACM forms produced RFC-invalid DNS names — AWS would reject them at
`projinfra up production` — so no underscored elastic project could be
shipped on 1.0.0. The patch closes every leak site without changing any
joiner or policy semantics; emit code that already produced hyphenated
output is unchanged. (Mod 046.)

### Fixed

- **Naming policy leak across compose + HCL emit (mod 046).** Project
  segment now derives from the DNS-labeled form
  (`project.replace('_', '-').lower()`, equivalent to
  `apply_policy(project, http_host)`) at every data-plane emit site:
  - **Compose env-tier** (`emit_compose`): docker network names
    (`docex-smoke-elastic-dev-{web,internal}` instead of
    `docex_smoke_elastic-dev-{web,internal}`), OTel sidecar container
    names (`docex-smoke-elastic-dev-web-otelcol`).
  - **Compose project-tier** (`emit_project_compose`): four
    `${project_dns_label}-${env}-web` networks, project traefik
    container_name + network attachments, ACME volume name.
  - **HCL project-tier** (`emit_hcl_project` + `project.tf.j2`):
    Route53 zone `name`, both ACM cert `domain_name`s + SANs, all five
    EC2-traefik Route53 A-records.
  - **HCL EC2-traefik user_data** (`ec2_traefik_user_data.sh.j2`): the
    boot DNS-update script's hosted-zone lookup + record-set FQDNs.
  - **HCL env-tier** (`main.tf.j2`): Service Connect namespace `name`
    (Cloud Map private DNS namespaces resolve via Route53; the name
    must be a valid DNS hostname).
- **`CompiledEnv.project_dns_label`** — new field (mod 046) carrying
  the DNS-labeled project segment. Every data-plane emit site that
  previously interpolated `compiled.project` now interpolates
  `compiled.project_dns_label`. Inert AWS record-key identifiers
  (IAM, SSM, DDB) are unaffected — they retain their existing
  underscore-preserving policy.

### Tests

- `tests/unit/test_naming_policy_leak.py` (mod 046): six regression
  tests that construct emits against a project named `my_test_proj`
  and assert every data-plane name renders hyphenated. Closes a
  test-coverage gap that existed because the bundled fixtures use
  `name: sample` (no underscores to leak), making the bug invisible to
  the pre-1.0.0 test suite.

### Out of scope

- Joiner separator changes (settled by mod 030).
- ECR repo name emission (structural per mod 030 — segments
  underscore-preserved by design).
- Inert AWS record-key identifiers (IAM, SSM, DDB) — underscore-
  preserving policies are correct.

## [1.0.0] - 2026-06-09

The **shape-and-tier campaign** cut. Sixteen mods (030–045) bring
docex into alignment with the doctrine restructure that introduced
`preinfra`/`projinfra`/`envinfra` as first-class tiers, unified data-
plane naming on hyphens, refactored the elastic shape around a shared
master VPC + project-tier ALB-or-EC2-traefik reverse proxy, and
reshaped the CICL surface (`apex_domain`, `reverse_proxy:`,
service-name blacklist). Every consumer project needs a recompile +
redeploy after upgrading the `docex_version` pin; old identifier
forms are not preserved.

Each entry below carries a `(mod NNN)` attribution; the campaign list
and per-mod planning docs live at
[`docex/plans/campaigns/shape_overhaul_mod_list.md`](plans/campaigns/shape_overhaul_mod_list.md).

### Added

- **EC2-traefik reverse-proxy variant (mod 044).** Elastic projects can
  now set `reverse_proxy: ec2_traefik_eip` or `ec2_traefik_pip` in
  `infra.yml` to swap the default ALB for a single t3.nano running
  traefik — ~$4–8/month vs the ALB's ~$22. Project-tier emits the
  full traefik resource set (instance + IAM role/policy/profile + SG
  + EBS ACME volume + SSM Parameter for dynamic config + CloudWatch
  log group + five Route53 A-records); ACM and the ALB are omitted.
  EIP variant pins a stable public IP; PIP variant uses an
  auto-assigned IP plus a boot-time systemd unit that rewrites the
  five A-records via a Route53 batch on IP changes. Per
  [`projinfra/ec2_traefik.md`](../doctrine/infrastructure/specifics/projinfra/ec2_traefik.md).
- **`templates/ec2_traefik_user_data.sh.j2`** (~280 lines, mod 044):
  doctrine-managed user_data covering EBS ACME volume tag-attach,
  traefik install + static config (DNS-01 LE via Route53), systemd
  timer for SSM-driven dynamic-config sync, optional PIP-only boot
  DNS-update unit, CloudWatch Logs agent.
- **Polymorphic `reverse_proxy_security_group_id` project-tier output
  (mod 044).** Resolves to the ALB SG or the traefik SG depending on
  variant; env-tier consumers stay variant-agnostic.
- **New commands `preinfra`, `projinfra`, `envinfra` (mod 034).** Per
  [`docex.md`](../doctrine/infrastructure/docex.md) — `preinfra <side>`
  checks prerequisite infrastructure existence (real per-foundation
  checks landed in mod 042); `projinfra <direction> <side>` brings
  project-tier infra up/down (real behavior for fixed in mod 036,
  for elastic in mods 037–044); `envinfra <direction> <env>`
  replaces the old `up`/`down` for dev/test environments.
- **Real `preinfra` per-foundation checks (mod 042).** Fixed/dev-side
  checks the `docex-ingress` docker bridge exists. Elastic/production
  checks the master VPC + 4 subnets + primary-AZ subnet via tag
  discovery (matching mod 041's data-source filter scheme).
  `projinfra up <side>` and `envinfra up <env>` now refuse when
  `preinfra` fails; all failures enumerated in one pass; AWS client
  construction is lazy (fixed-only operators don't need AWS creds
  for `preinfra development`).
- **Per-project traefik + four `-web` networks (mod 036).** Replaces
  the obsolete machine-wide-traefik model with the doctrine's
  per-project traefik per
  [`projinfra/fixed_reverse_proxy.md`](../doctrine/infrastructure/specifics/projinfra/fixed_reverse_proxy.md).
  Container named `${project}-traefik` joined to all four
  `${project}-${env}-web` networks plus `docex-ingress`. DNS-01 LE
  with cert resolver named `doctrine`, project-named acme volume,
  pinned by digest via new `TRAEFIK_IMAGE` constant
  (`traefik:v3.3@sha256:2cd5cc7…`). Operator-supplied
  `${TRAEFIK_ACME_EMAIL}` / `${TRAEFIK_DNS_PROVIDER}` at runtime.
  `projinfra <up|down> <side>` for fixed runs real docker-compose
  with single-machine convergence; `down` refuses while env-tier is
  up; acme volume survives.
- **Fargate tier rounding now surfaces every cause (mod 033).**
  `_resources_to_elastic` prints a one-line notice for project-only
  rounding, sidecar-pushed rounding, or both — not just the
  sidecar-pushed case.

### Changed

- **Naming policy unification (mod 030).** `docker` and `ecs`
  policies flip from `separator: underscore` to `separator: hyphen`
  per the doctrine's new default rule: data-plane resolvable names
  use hyphens; underscores survive only for inert AWS record-key
  identifiers (`iam`, `ssm_path`, `ddb`). Every Docker
  container/network/volume name and every ECS cluster/service/
  task-def family/Service Connect identifier flips from
  `${project}_${env}_${svc}` to `${project}-${env}-${svc}`. ECR repo
  names are emitted via a structural emitter (`${project}/${svc}`
  with per-segment underscores preserved) since the single-separator
  policy machinery cannot express the `/`-joined two-segment shape.
- **CICL surface refresh (mod 031).** `infra.yml`'s top-level
  `domain:` field renamed to `apex_domain:` with narrower semantics
  — the value is the *bare apex* (e.g. `example.com`). Canonical
  service host shape is now
  `<service>.<env>.<project>.<apex_domain>`; project segment is
  derived from `project.yml`'s `name` and DNS-labeled for underscored
  names. Prod's `domain_default_service` answers at three hosts now
  — including the bare-project ergonomic host
  `<project>.<apex_domain>` (replaces the old `www.<apex>`
  convention). New magic vars `${apex_domain}` and
  `${bare_project_subdomain}`; `${env_subdomain}` redefined. New
  elastic-only top-level field `reverse_proxy:` with three accepted
  values. New validation rules 13/14/18 (apex bare, service-name
  blacklist, reverse_proxy elastic-only).
- **Telemetry sidecar rename (mod 032).** All sidecar container and
  service names flip from `<svc>_otelcol` to `<svc>-otelcol`.
  Compose form: `${project}-${env}-${svc}-otelcol`; ECS form:
  `${svc}-otelcol`.
- **Command surface refreshed (mod 034).** Per the doctrine's
  [`docex.md`](../doctrine/infrastructure/docex.md). `--help`
  regrouped from the internal phase scheme to purpose-based
  (Introspection / Infrastructure / Development / Pipeline).
- **Compiler output split by side (mod 035).** Project-tier output
  now lives under `infra/output/project/{development,production}/`.
  Both sides emit on every project; production-side shape switches
  by foundation. Env-tier compose web networks reference the
  project-tier `${project}-${env}-web` as `external: true` (mod
  036), owned by projinfra.
- **Route53 zone + ACM certs aligned with the new doctrine (mod
  037).** Three bug fixes: zone name is now `<project>.<apex>` (was
  the bare apex); single ACM cert replaced with two
  (stage + prod) carrying the doctrine-spec SANs; `certificate_arn`
  output replaced with `stage_cert_arn` + `prod_cert_arn`. Env-tier
  branches on compile-time `env` for per-env cert ARN consumption.
- **ALB moved to project-tier with SNI cert binding (mod 038).** One
  ALB per project serving both stage + prod. Listener-rule
  priorities env-banded (stage 1000–4999, prod 5000–9999) so they
  can never collide on the shared listener. Six new project-tier
  outputs (`alb_arn`, `alb_dns_name`, `alb_zone_id`, both
  `listener_arn`s, `alb_security_group_id`). Env-tier ALB-adjacent
  refs go through `data.terraform_remote_state.project`.
- **Task-execution IAM policy tightened (mod 039).** AWS-managed
  `AmazonECSTaskExecutionRolePolicy` replaced with a single
  doctrine-shaped inline policy: ECR auth on `*`; per-repo ECR pull
  gated on `core_service_names`; SSM split into stage + prod
  statements; CloudWatch logs scoped to per-env log group ARNs. No
  `kms:Decrypt` (the AWS-managed `aws/ssm` key needs no explicit
  grant).
- **Env-tier SG names hyphenated (mod 040).** Closes a data-plane
  naming leak missed by mod 030 — env-tier security-group `name`
  fields now render as `${project-hyphen}-${env}-${short}`.
- **Master VPC consumed as preinfra (mod 041).** `project.tf.j2`
  drops ~100 lines of per-project VPC stack; replaced with tag-based
  data sources for the master VPC + public/private subnets +
  primary-AZ subnet. Per
  [`cicl.md § Simplifications`](../doctrine/infrastructure/cicl.md#simplifications),
  ECS workloads pin to `[primary_private_subnet_id]` (single-AZ);
  RDS/ElastiCache subnet groups and EFS mount targets keep multi-AZ
  per AWS requirements. The `docex-preinfra` skill needs an update
  to document the master VPC tag scheme
  (`Name=docex-master-vpc`, `managed_by=docex-preinfra`, subnet
  `tier=public|private`) — operator action.
- **Service Connect namespace switched to private DNS (mod 043).**
  `aws_service_discovery_private_dns_namespace.env` replaces the
  prior HTTP namespace; new `vpc` field associates with the master
  VPC. Auto-creates a Route53 private hosted zone resolvable
  VPC-wide so EC2-traefik (mod 044) can reach services by name from
  outside any ECS task netns.
- **Env-tier `web` SG ingress source polymorphic (mod 044).** Was
  `outputs.alb_security_group_id`; is now
  `outputs.reverse_proxy_security_group_id`. Variant-agnostic.
- **Env-tier ALB-alias A-records gated on `reverse_proxy == "alb"`
  (mod 044).** EC2-traefik emits the five A-records at project tier
  instead.
- **Env-tier `aws_lb_listener_rule`, `aws_lb_target_group`, and ECS
  service `load_balancer` attachments gated on
  `reverse_proxy == "alb"` (mod 044).** EC2-traefik routes via the
  SSM-driven dynamic config consumed by traefik's file provider.

### Removed

- **`bootstrap` command** — replaced by `projinfra up production` on
  elastic projects (mod 034).
- **`up` and `down` commands** — collapsed into
  `envinfra <direction> <env>` (mod 034).
- **`reverse_proxy` role / CICL backing-service marker** — the
  reverse proxy is project-tier infrastructure now, not a CICL
  service. Projects declaring `role: reverse_proxy` fail validation
  (mod 031).
- **`domain:` top-level field** — renamed `apex_domain:` with
  narrower semantics (mod 031).
- **`ecr_repo` naming policy** — ECR repo names emit structurally
  (mod 030).
- **Machine-wide-traefik model on fixed** — replaced by per-project
  traefik behind HAProxy (mod 036).
- **Per-project AWS VPC stack** (VPC, IGW, NAT, public/private
  subnets ×2, EIPs ×2, route tables, route-table associations) —
  consumed as preinfra via the shared master VPC (mod 041).
- **`AmazonECSTaskExecutionRolePolicy` AWS-managed policy
  attachment** — replaced with an inline project-scoped policy (mod
  039).
- **Per-env ALB** — one shared project-tier ALB serves stage + prod
  via SNI (mod 038).
- **`*.dev`, `*.test`, `*.www` ACM cert SANs** — dev/test certs live
  on the per-project traefik (mod 036); `www` form retired with the
  bare-project routing rule (mod 031).

### Known v1 gaps

- **EC2-traefik release-flow SSM rerender is not implemented.** Mod
  044 emits the SSM Parameter `/<project>/ec2_traefik/config.yml`
  with an empty stub (`http: { routers: {}, services: {} }`) and
  uses `lifecycle.ignore_changes = [value]` so subsequent
  `tofu apply` doesn't fight with manual edits. Operators using
  EC2-traefik manage routing-rule YAML manually via
  `aws ssm put-parameter` until a follow-up mod adds per-release
  SSM push from the merged stage+prod routing surface. The instance
  polls SSM every 30s; manually-pushed config reflects promptly.
  ALB users are unaffected.
- **Multi-machine fixed foundation is deferred.** Single-machine
  fixed only in v1. The `ansible-at-project-tier` artifacts
  documented for "fixed + remote prod host" are not emitted; mods
  036/042 implement single-machine paths. `docker-compose` runs
  against the local daemon for both `projinfra` sides on a
  single-machine fixed project (convergence is implicit because
  both sides emit identical content).

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
  `shape.md` § Elastic-Foundation table. Mod 014.

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
  [`shape.md`](../doctrine/infrastructure/shape.md) and
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
  `cicl.md` (new "Provided Fields" section), `shape.md`, `release_mechanism.md`.
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
  `networks.md`, `shape.md`.
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
