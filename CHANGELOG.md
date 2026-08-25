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

Advance 009 ("Test Overhaul") — in progress.

### Added
- **`docex test` is now a durable, re-attachable job (the `job` substrate).** The
  suite runs in a **detached, deterministically-named vessel container** that docex
  launches over the docker socket; the command still **blocks and exits with the
  run's code by default** (the CI exit-code contract is preserved), but the work is
  durable underneath — a **killed foreground monitor no longer orphans the run**, and
  the run is re-attachable. Each run writes an on-disk record under `.docex/runs/<id>/`
  (`meta.json`, `status.json`, an atomically-written `exit` file, `log`); the `exit`
  file is the authoritative terminal signal, reusing the exit-file half of the
  healthcheck liveness pattern (`healthchecks.md`, `internal_dependency_rules.md` rule
  6) — the tick/staleness half is deliberately not used. New surface: `docex test
  --detach` (→ a handle, ~seconds) and `docex job <ls|status|wait|logs|result>` over
  handles (`job ls` is the durable, non-`pgrep` rediscovery path). The vessel's
  deterministic name **is** the per-`(project, test)` lock — a second concurrent run
  refuses rather than contending — and a hard-killed run is reaped by the next
  invocation's preflight (writing an authoritative `exit`, tearing down the leaked
  stack). Built vessel-polymorphic (container for `test`; host-process for
  `check`/`merge` in a later increment) with the slot axis and fleet reaper deferred.
  Doctrine amended in `docex.md` (new § Command Lifecycle + the `job` surface + `test`
  durability), a light `cicd.md` note, and the `testing` skill; `healthchecks.md` /
  `internal_dependency_rules.md` cited as precedent, not edited. `docex`'s own
  `.gitignore` now ignores `.docex/`. (docex mod 148)
  - **Upgrade note (for the release that follows this advance):** the project-upgrade
    guide must add an idempotent step ensuring `.docex/` is in each downstream
    project's `.gitignore`. New projects already get it (inception's default gitignore,
    mod 056) and both smoke seeds carry it, but pre-056 existing installs — which never
    re-ran inception — need it added on upgrade. `docex_install.sh` is deliberately
    **not** widened to write gitignore entries (project-structure scaffolding stays
    inception's job).

### Changed
- **`docex merge` preflights the remote before any expensive work.** A
  `git ls-remote origin` check now runs at the very top of `merge`: a broken /
  unauthenticated / unreachable `origin` fails in seconds, naming the problem,
  **without building an image or running a single test** (previously the auth
  failure only surfaced after the defensive `check`'s full build + suite, ~34 min
  wasted on a real run). Skipped on a repo with no `origin` remote (local-only
  merge). This also closes a latent correctness gap: because `check` tolerates a
  failed fetch and continues against potentially-stale `origin/main`, the
  defensive recheck could validate against a stale base — guaranteeing the remote
  is reachable first means the recheck always sees fresh `main`. (docex mod 146)
- **docex runs its own Python unbuffered** (`PYTHONUNBUFFERED=1` in the image), so
  docex's narration and the live output of the subprocesses it launches (git,
  docker, pytest) interleave in true chronological order when a run's output is
  redirected to a file, instead of docex's block-buffered narration clumping at
  process exit. (docex mod 146)
- **The per-codebase test contract is now two shims** (SC1): every codebase ships
  `test_unit.sh` (the no-infra tier — domain / alogic / adapter-unit) and
  `test_integration.sh` (the stack-backed tier — module-integration, flow, **and
  contract** tests), replacing the single `test.sh`. `docex check` asserts both
  exist and are executable; `docex test` brings up the fresh `test` stack and runs
  both shims (unit tier, then integration tier) within it, fail-fast. The five
  conceptual test tiers are unchanged but now map onto **two execution classes**
  (needs-infra vs not); contract folds into integration. Doctrine amended across
  `tests.md`, `hex_overview.md § Tests`, `cicd.md`, `docex.md`, `infrastructure.md`,
  `healthchecks.md`, `exec_service.md`, `inception.md`, `advance.md`,
  `migrations.md`, and the `testing` skill. **Breaking:** downstream projects must
  split their `test.sh` into the two shims (a project-upgrade guide rides with the
  release that follows this advance). (docex mod 147)

## [2.1.0] - 2026-08-24

Advance 008 ("Housekeeping") — a backlog-clearing advance of small, mostly-independent
fixes. Two new hard compile rejections (a non-DNS-label project name; an `object_store`
without `version`) are breaking *in principle* but enforce rules the doctrine already
stated; see [`upgrades/upgrade_2.1.0.md`](./upgrades/upgrade_2.1.0.md).

### Added
- **`docex compile` rejects an inert `defaults.elastic` key** on the ECS task-definition
  path (`rule_elastic_defaults_unread_key`). That renderer reads a *named, closed* set of
  keys — `{cpu, memory, ephemeral_storage, image, command, healthCheck}` — rather than
  merging the block generically the way the fixed compose path does, so any other key fell
  on the floor unread. That is how mod 127's `healthCheck` near-miss could have shipped a
  fleet with no container probe; the guard turns the silence into a compile error naming the
  engine and stray key. Scoped to the three core roles (`web`/`worker`/`clock`); backing
  engines' rich elastic defaults (RDS instance class, storage, encryption) route to their own
  renderers untouched. (mod 138)
- **A CI guard asserts the two standard pytest invocations *partition* the suite**
  (`tests/unit/test_collection_partition.py`). It collection-only-counts `tests/unit`,
  `tests -m integration`, and all of `tests`, and fails unless `unit + integration == all` —
  so a test invisible to both standard invocations (an unmarked test under
  `tests/integration/`) or double-counted by both (an integration-marked test under
  `tests/unit/`) now fails loudly wherever it lives. This is the durable fix for the
  collection hole that hid twelve red compile tests behind a green report across two advances
  (mod 128). (mod 139)
- **`linkcheck.py` accepts a single `.md` file as a scan root, and honors a per-line
  `linkcheck-ignore` HTML-comment marker** (the line is skipped but counted, never silently).
  Together these let the repo-root markdown files join the default scan while a live line that
  merely *quotes* a dead reference as evidence can be exempted without destroying the evidence.
  (mod 139)
- **A project name must already be a valid DNS label.** `ProjectManifest.name` now rejects a
  non-conforming name at load — lowercase alphanumerics with interior hyphens/underscores
  (underscores are converted to hyphens on emit) — aligning the name to the DNS-label rule of
  record (`cicl.md § Domain`) so it compiles to exactly one spelling of its project segment.
  A mixed-case name that compiled today now errors; no real project carries one. (mod 138)
- **`docex check` gates a contract's declared spec version** against the doctrine floor —
  OpenAPI ≥ 3.2, AsyncAPI ≥ 3.0 (`contracts.md § Standards`). Each floor is what makes a
  promised `api_style` implementable (openapi 3.2 → `itemSchema` for `stream`; asyncapi 3.0
  → `reply` for `rpc`), so a project shipping `openapi: "2.0"` that previously passed green
  now fails. Third contract gate beside the existing two; no second directory walk. (mod 137)
- **A backing service must declare `version:` when its engine pins an image/version from it**
  — now a compile error (`rule_version_required`), aligning the compiler to `cicl.md § Service
  Fields`'s existing "required" claim. Derived from the engine's `fields:` block, so `s3` (no
  image) is exempt structurally while `minio` requires it. (mod 137)
- **`docex why` gained entries for five infrastructural resources** that `shape.md` names but
  the excerpts never covered — `master_network`, `web_demux`, `observability_backend`,
  `telemetry_sidecar`, and `nat_gateway`. (mod 140)
- **The `doctrine_excerpts` artifact got its first automated consumer**
  (`tests/unit/test_doctrine_excerpts_index.py`): a pure unit test asserting every `index.yml`
  key resolves to a `shape.md` resource (or one of the documented exceptions `codebase` /
  `secrets`), that every referenced file exists, and that no excerpt file is orphaned. This is
  the check that catches the `network_web` / `vpc` class of key drift, so this artifact is no
  longer the one aligned artifact with no automated consumer. (mod 140)
- **`docex secrets` value fingerprints** — a `status <env> --fingerprint` column and a new
  `docex secrets fingerprints [--format json]` cross-env matrix let a value-blind caller
  verify a secret propagated (`dev`→`stage`→`prod`) or detect drift without ever reading the
  value. A fingerprint is `hex(sha256(SALT || value))[:8]` under a fixed, project-local,
  non-secret salt derived from the project name — stable and comparable within a project,
  differing across projects. Scoped to the secret category only (config is already
  value-visible), computed from a value `status` already had in hand so no new value-read path
  is opened, and `copy` now prints matching source/destination fingerprints to confirm a
  value-blind transfer landed. Documented honestly as an **equality/drift check, not a
  confidentiality guarantee**: it reveals no value directly, but a low-entropy or placeholder
  secret is inherently guessable from any hash of it. (mod 141)

### Fixed
- **Preinfra dedicated traefiks are now scoped to their own preinfra "project", so they
  stop polluting every other project's ACME.** The doctrine's dedicated traefiks — the
  container registry's `registry-traefik` (`container_registry.md`) and HyperDX's dedicated
  traefik on both foundations (`telemetry_preinfra.md`) — were prescribed with a Docker
  provider carrying **no discovery constraint**. Over the shared docker socket that traefik
  discovered *every* project's `traefik.enable=true` containers and opened ACME orders it
  could never satisfy — spamming `Cannot retrieve the ACME challenge` on every project
  traefik and burning Let's Encrypt failed-authorization rate-limit budget against shared
  registrable domains. `docex` already emits a `docex.project` constraint for **project**
  traefiks; this adds the equivalent to the **preinfra dedicated** traefiks the doctrine
  configures by hand: a `constraints: Label(docex.project, <registry|telemetry>)` on each
  dedicated traefik's docker provider, and a matching `docex.project=` label on every
  container it serves (registry: the registry container; telemetry: the HyperDX UI/app
  service and the otel-collector service). Doctrine-only — these traefiks are not emitted by
  `docex`, so there is no code change. **Verification is DEFERRED / PENDING an
  operator-supervised live preinfra-host walk**: a preinfra dedicated traefik must open ACME
  orders for *only* its own host(s), and the `Cannot retrieve the ACME challenge` spam / LE
  429 burn on project traefiks must stop. The immediate host mitigation (editing the live
  `/opt/docex-preinfra/.../traefik.yml` + labels and restarting) is the operator's, applied
  at that walk — not part of this change. (mod 143)
- **A project's first production release no longer dies in `docex merge`.** On a brand-new
  project `origin/main` did not exist, so merge fell into a seed-trunk path that ran
  `git checkout main && git merge --ff-only <feature>` — and the checkout failed with
  `pathspec 'main' did not match` because there was no `main` to check out, leaving merge to
  exit "Manual recovery needed". The root cause was upstream: `inception.md` never established
  the trunk. PART I now establishes an empty `main` (an empty initial commit pushed so
  `origin/main` exists) *before* branching `inception_and_first_draft`, so the first `docex
  merge` takes the ordinary rebase-onto-`origin/main` path. The broken seed-trunk path in
  `merge.py` was removed as dead code; a missing trunk now fails loudly (pointing at inception)
  rather than trying to invent one. `fast_forward` is retained for the normal rebase path.
  (mod 142)
- **A mixed-case project name no longer compiles to two disagreeing spellings of its own
  project segment.** Four HCL template sites (`project.tf.j2`, `main.tf.j2`) each re-derived
  the segment inline and two omitted `| lower`, so `MyProject` emitted both `MyProject-…` and
  `myproject-…` — *different resources* on case-sensitive AWS names (SG, ASG). All four now
  read a single threaded `project_dns_label`, and the load-time name validation forbids the
  mixed-case input outright, so the DNS-label rule has one expression. The two inert
  `defaults.elastic` keys the near-miss guard now forbids (`launch_type`/`network_mode`) were
  deleted from the three core roles in the same mod — they were read by nothing, as the
  emitter hardcodes FARGATE/awsvpc. (mod 138)
- **`object_store`/`minio` no longer ignores `version:`.** The `minio` engine hardcoded
  `minio/minio:latest` and pinned nothing from `version:` — an unpinned tag on a stateful
  backing service breaks the determinism promise. `version:` now pins the tag
  (`minio/minio:${version}`) and the hardcoded `:latest` is gone; the lone backing engine that
  did not pin its tag is fixed. (mod 137)
- **The env subdomain `<env>.<project>.<apex>` is derived in one place.** Two readers
  (`orchestrate/aggregate.py::_host_for`, `orchestrate/up.py`) re-derived it by hand; both now
  read the compiler-owned `CompiledEnv.subdomain` via `env_subdomain_for`. Reader-only
  duplication, so it failed loudly rather than silently — removed regardless. (mod 137)
- **Sixteen dead relative links in released `CHANGELOG.md` sections repaired** (link targets
  only — no prose or claim altered). Historical residue from before the 1.3.0 versioning move,
  when this file sat at `docex/`: `../doctrine/…` escaped the repo root and `plans/…` resolved
  only from `docex/`. Two links whose targets were retired with no honest replacement were left
  as frozen record rather than falsified. These sections are frozen-skipped by `linkcheck`, so
  the repair is courtesy for human readers. (mod 139)
- **A fixed `stage`/`prod` release now pulls images without starting the stack, so migrations
  run before new code goes live.** The emitted playbook's "Pull all images" task used
  `community.docker.docker_compose_v2` with `state: present`, which converges the whole stack
  to *running* — so the real ordering was **up → migrate**, and the doctrine's abort guarantee
  (a failed migration aborts before new code serves) was void: new code went live against the
  unmigrated schema and the later "Bring up the stack" task was a no-op. The task is now a pure
  pull (`community.docker.docker_compose_v2_pull`, `policy: always`, no `state:`), so the stack
  comes up only at "Bring up the stack", after the per-codebase migrate task. `migrations.md`'s
  known-divergence note is softened accordingly. Real-machine verification is **pending** an
  operator-supervised fixed smoke walk (container `StartedAt` vs. migration completion; a first
  release's clock fire raising no `UndefinedTable`) — a green playbook exit code does not prove
  the ordering. Found by advance 006's fixed smoke walk. (mod 144)

### Changed
- **Doctrine prose aligned to what `docex` enforces** (no behavior change). `healthchecks.md`'s
  "a core service needs a `port` only when something addresses it directly" overstated CICL
  rule 32, which scopes the requirement to `uses` targets — softened so a core service nobody
  uses may carry a decorative port without contradiction. `transfer_tables.md`'s `defaults`
  field reference now documents the fixed/elastic asymmetry: the block merges generically on
  fixed, but on elastic's `task_definition` target the renderer reads a named closed set and
  rejects other keys. Rule 32 itself is deliberately left unchanged (won't-fix). (mod 138)
- **`linkcheck` now scans `CHANGELOG.md`, `README.md`, and `RELEASING.md`** as file roots in
  its `DEFAULT_ROOTS`. `CHANGELOG.md`'s released sections stay frozen-skipped, so only its live
  `[Unreleased]` section (and any non-suppressed line) is enforced. (mod 139)
- **The target-vs-claim rule for frozen history is stated once in `RELEASING.md`**
  ("Editing Frozen History: Targets vs. Claims") — a link *target* may be repointed when a
  file moves or is renamed; a *claim* (prose, visible link text, an asserted version) may not.
  `upgrades/README.md` now cites the shared statement rather than only stating it locally.
  (mod 139)
- **The 60 fast, hermetic compile tests moved from `tests/integration/` to `tests/unit/`**,
  leaving only the one genuine `tofu`-shelling integration test in
  `tests/integration/test_compile_tofu.py`. The directory name is now honest; collection
  totals across `pytest tests` and `pytest tests -m integration` are unchanged by the move.
  (mod 139)
- **The `docex why` doctrine excerpts were overhauled to match current doctrine** (prose only;
  `docex why` behavior unchanged). Mod 134's audit found 15 of 18 entries carried defects and
  three actively misinstructed; all were rewritten — `aws_account`'s one-project-per-account
  inversion, the pre-`apex_domain` `www.` subdomain scheme in `dns` / `registrar`, `secrets`'
  deleted-`example.env` restatement, and the ALB-only / single-wildcard-cert elastic claims in
  `reverse_proxy` / `cert_manager` were all corrected. `index.yml`'s `network_web` /
  `network_internal` keys were renamed to `web_network` / `internal_network` to match
  `shape.md`. Every `Doctrine reference:` footer was converted to bounded form (path and `§`
  in one inline-code span), taking the directory to 0 unbounded citations and the repo-wide
  `linkcheck` count from 25 unbounded to 10. (mod 140)

### Removed
- **The `docex why vpc` entry was retired.** `shape.md` has no `[vpc]` resource — the elastic
  private network is the shared `master_network` (a master VPC), not a per-project VPC — and
  the old entry actively misinstructed (per-project VPC, per-AZ NAT). `docex why vpc` now exits
  1; its content lives in the new `master_network` entry. (mod 140)

## [2.0.1] - 2026-08-20

### Fixed
- **The docex shim preserves the git-credential repo path** (`bin/docex`). The per-call
  credential passthrough (`DOCEX_GIT_CREDENTIAL_PASSTHROUGH`) forced
  `credential.useHttpPath=false`, stripping the repository path from the credential
  request; a **path-scoped** host helper (e.g. a per-repo broker) cannot authorize a
  request that names no repo, so `docex merge` died at its first fetch with
  `fatal: could not read Username`. The shim now forces `useHttpPath=true` at both the
  container gate and the host `git credential fill` call, so the path survives and
  path-scoped helpers are supported. Residue of mod 061's retired pathless-`store`
  design, carried across mod 068; it survived 1.4.3 → 2.0.0. (mod 136)
- **`docex check` fails on a git-fetch failure instead of reporting green.** `check` had
  downgraded a failed `git fetch origin` to a warning and then misfired "first-release
  mode", reporting all gates green on a box where `merge` — which runs `check`
  defensively and treats the same failure as fatal — could not proceed. `check` now
  mirrors `merge`: it skips the fetch when there is no `origin` remote and treats a real
  fetch failure as fatal. (mod 136)

## [2.0.0] - 2026-08-11

"Process type solidification" (advance 005, mods 111-124) — finishes what CICL v2
started. The two central nouns trade places (a *core service* becomes a
**codebase**; a *process type* becomes a **core service**), the two service
relations collapse into one named **`uses`**, and `role: scheduler` — a process
type that was not a process — is retired for **`role: clock`**, an ordinary
long-running singleton that defers work onto its own codebase's queue. One
behavioural change rides along: the elastic Service Connect reconcile now
triggers off durable AWS state rather than an in-process snapshot, and every
`aws_ecs_service` carries `wait_for_steady_state = true`. **This is a breaking
format change:** `cicl_version: "3"` is required and `"2"` is rejected rather
than shimmed, and for exactly one release cycle after 2.0.0 prod has no rollback
path (the v2→v3 boundary is refused at pre-flight, with a fix-forward message).
Downstream projects upgrade per
[`upgrades/upgrade_2.0.0.md`](./upgrades/upgrade_2.0.0.md) — a repin plus an
`infra.yml` rewrite, and, for any project with a scheduler, application-code work.

"Surfaces and health" (advance 006, mods 125-133) ships in the same cut. A core
service declares its API boundaries explicitly as `surfaces:` instead of having a
contract format inferred from its `role`, and HTTP stops being the doctrine's
mandated health substrate. Both halves are breaking for `infra.yml`, and both
ride the **same `cicl_version: "3"`** rather than manufacturing a second
rollback-unavailable boundary inside one cut. Two items unrelated to either half
fold in from advance 005's deferrals: `linkcheck.py` scoping its checks
independently (mod 132), and `preinfra development` gaining the registry
manifest-delete probe (mod 133).

### Changed

#### Vocabulary — codebases and core services

- **A codebase is a `codebase`; a process type is a `core service`.** The two
  central nouns of the doctrine's service vocabulary trade places. What 1.6.0
  called a *core service* — one source tree, one build artifact, one image — is
  now a **codebase**; what it called a *process type* — one named,
  independently-scaled deployment of that artifact — is now a **core service**.
  Nothing structural moves: still one image per codebase, still N invocations of
  it, each with its own role, `command`, port, networks, and resources.

  1.6.0 introduced process types because `web` and `worker` needed to share a
  build artifact. That was the right structural move but left the vocabulary a
  notch out of alignment, load-bearingly so: the doctrine's "core service" had no
  port, no command, no replica count, and nothing ever routed to it, so a reader
  who knew what a service *is* had to unlearn it to read `infra.yml`. The
  clearest symptom was already written down — `cicl.md § Magic Refs` had to
  explain that "a **bare** core service name is illegal rather than shorthand",
  which is the doctrine noticing its own noun was wrong. A service you cannot
  address is not a service.

  **Breaking — every `infra.yml` must be rewritten.** Top-level `core_services:`
  → `codebases:`; nested `processes:` → `core_services:`;
  `domain_default_process` → `domain_default_service`; core magic refs go from
  four segments to five (`${codebases.<cb>.core_services.<svc>.<part>}`).
  Backing refs and `schema_owned_by` are unchanged. This rename is one of three
  changes sharing the `cicl_version` `"2"` → `"3"` bump in this cut.

  On the emitted surface, **no name, label, or path changes** — the two elastic
  env-tier tag *keys* move (`service` → `codebase`, `process` → `service`) while
  their values stay put, so OpenTofu updates tags in place rather than recreating
  resources. Two changes do reach consumers: the OTel resource attributes
  `docex.core_service` / `docex.process_type` become `docex.codebase` /
  `docex.service` (**this splits existing telemetry time series** — dashboards
  and alerts need updating), and `docex describe --format llm` renames its
  `core_service` JSON key to `codebase`.

#### One relation: `uses`

- **`depends_on` and `consumes` merge into one relation, `uses`.** An author
  asked one question — *what does this core service talk to?* — and had to answer
  it in two fields with two cycle rules, two halves of one validation rule, and a
  comparison table explaining the split to itself. Now a core service declares
  `uses:`, naming a **backing service** bare (`database`) or a **core service**
  dotted and fully qualified (`api.worker`).

  The merge is sound because the cycle rule keys on **target kind**, which the
  compiler knows for every edge. Better: a backing service may no longer declare
  outbound edges at all, which makes it a graph **sink** — so acyclicity across
  backing-targeted edges falls out structurally rather than needing enforcement.
  The doctrine previously argued the two relations *could not* merge; that
  argument is retired along with the field.

  **Project-level startup ordering is no longer a doctrine feature.** The
  compiler emits no compose `depends_on:` / `condition:` on any core-service
  block — removed, not deprecated. The connection-resilience mandate was always
  the real guarantee, and a silently-emitted gate made `dev` and `test`
  systematically more forgiving than elastic `prod`, sheltering exactly the
  non-resilient boot code the mandate exists to expose. The **per-codebase exec
  block keeps its gate** (derived from that codebase's backing-targeted `uses`
  edges): `migrate.sh` and friends are one-off batch jobs whose whole contract is
  an exit code, and for a batch job "be tolerant" means "wait until ready".

  **Breaking — every `infra.yml` must be rewritten.** `depends_on:` → `uses:`,
  merged with any `consumes:` list on the same core service; `depends_on` deleted
  from backing services. Both old field names are hard errors, not silent
  aliases. `cicl_version` moves `"2"` → `"3"`.

  Rules 6 and 24 retire; rule 7 collapses to a single clause; rule 25 becomes the
  `uses` shape rule. Retired rules keep their numbers and carry a tombstone —
  rule numbers are stable identities cited from other doctrine files, the pre-cut
  checklist, and `docex`'s own validation issue ids.

- **`docex` implements the `uses` merge.** The compiler, validator, emitters,
  `describe` renderers, and CI gates now read the single relation; the exec
  block's health-gated readiness derivation is the only ordering the compiler
  still emits.

#### `role: clock` replaces `role: scheduler`

- **`role: scheduler` retires; the clock is an ordinary core service.** A
  schedule is a property of an *invocation*, not of a deployment, and
  `role: scheduler` was a process type that was not a process — every carve-out
  it forced traced to that one fact. It is replaced by **`role: clock`**: a
  long-running singleton core service, one per codebase with scheduled work,
  whose entrypoint owns a cron loop and reads a compiler-delivered schedule
  table. A compose service on fixed, `task_definition` + `ecs_service` on
  elastic.

  Schedules are declared on the clock as `schedules:` — a map of job name to a
  **bare 5-field UTC cron string**. With EventBridge gone there is **no dialect
  translation anywhere**: no 6-field forms, no `?`-day substitution, no
  provider-specific day-of-week renumbering. The compiled table reaches the
  container as **one literal env var, `DOCEX_SCHEDULES_YAML`, identical on both
  foundations** — a compose `environment:` entry on fixed, a task-definition env
  entry on elastic. No mount, no path, no per-foundation branch.

  **Every carve-out dies.** The clock serves `GET /health` off a monotonic tick
  like any loop-owning service, gets an OTel sidecar so job telemetry stops being
  deferred, and is a normal container with normal bind mounts in `dev` and
  `test`. Gone with the role: the Ofelia trigger container and its INI, the
  EventBridge path and its per-service invocation IAM role, the `test`-env
  suppression, and the "scheduler-only codebase that nothing builds" special
  case.

  Two rules are prose rather than validation, because the compiler cannot see
  what a port method does: **the clock defers, it does not work** (its only job
  is to call a driving port that enqueues — only the codebase owning a schema may
  write it), and **one clock per codebase**, not one per project.

  **Breaking.** Every `role: scheduler` service becomes a `clock` core service
  plus one or more driving-port operations; each job's `command` argv becomes a
  port method. `specifics/scheduler.md` is replaced by `specifics/clock.md`.
  Rule 26 is replaced (`replicas` forbidden on a clock) and rule 27 now covers
  `worker` and `clock`.

  One consequence worth knowing: a clock is consumer-only, so nothing `uses` it
  and no `web` core service fans out to it. Its liveness is enforced by its
  container healthcheck, but **staging tests do not see it**.

#### Surfaces replace role-derived contracts

- **A core service declares `surfaces:`; rules 29-33 join the CICL rule set
  (mod 125).** A surface is a named boundary with one or more `api_styles`, and
  it compiles to exactly one contract file. Format follows the styles the
  surface declares, replacing selection keyed on `role` — a proxy for
  *transport*, not for interaction style. Five new rules: a surface's
  `api_styles` must resolve to exactly one contract format, **derived** from the
  style table rather than tabulated against it, so `[rest, stream, webhook]`
  passes and `[rest, rpc]` fails telling the author to split (29); surface names
  take the codebase/core-service name pattern, because a surface name is one
  segment of a contract filename parsed right-anchored into four fields (30);
  every core-service `uses` target declares at least one surface, since
  declaring one is what makes a core service a provider (31); a `uses` target
  its consumer addresses **directly** declares a `port`, and one reached only
  through a queue or broker declares none (32); and `health_check_path` is
  declared by exactly the `web`-network core services — required on them,
  forbidden off them, keyed on **network membership rather than role** (33).
  `graphql` and `proto` are defined language but unimplemented formats, and a
  surface resolving to either fails at compile with a named "format not yet
  implemented" rather than a silent gap.

  **Rule 28 is retired and its number tombstoned** (as 6 and 24 are). It
  required a `port` beside `health_check_path`; rule 33 confines that field to
  `web`-network core services and rule 15 already requires a port on those, so
  the obligation is *redundant* rather than merely obsolete.

- **`docex check`'s contract gate reads `surfaces:` and nothing else; two health
  gates are deleted (mod 126).** The provider set was
  `(core-targeted uses entries) ∪ (web-network core services)`. Now **a core
  service is a provider iff it declares `surfaces:`**, with one expected contract
  per surface at
  `infra/contracts/<codebase>.<service>.<surface>.<format>.<ext>`, in the format
  that surface's `api_styles` resolve to. The second arm of the old union was
  *wrong*, not merely redundant: a `web`-network core service that declares no
  surface — a frontend serving a browser — now correctly needs **no** contract,
  where before one was forced onto it.

  Contract filenames parse right-anchored on **four** stem segments, and the
  extension is checked against the *resolved format* rather than a list of
  accepted suffixes: `contracts.md § Standards` fixes exactly one extension per
  format, so `api.web.rest.openapi.yml` resolves and both
  `api.web.openapi.yml` (the retired three-segment form) and
  `api.web.rest.openapi.yaml` do not. **A contract file matching no declared
  surface now fails the gate**, naming the four-segment form and saying to rename
  or delete it — including a leftover three-segment name, which an
  existence-only gate cannot see precisely because the new file also exists.

  `_CONTRACT_FORMAT_BY_ROLE`, `_FALLBACK_CONTRACT_FORMAT`, and
  `_contract_format_for_role` are gone, and with them the silent fall back to
  `openapi` for an unrecognized role. An unrecognized `api_style` is now
  `rule_29_unknown_api_style` at compile time, so the gate has nothing left to
  guess at.

  **The `health_endpoints` gate is deleted whole** — the
  `/health/<codebase>/<service>` fan-out with it, and the probeability arm that
  demanded `port` *and* `health_check_path` on every core `uses` target, which
  rules 32 and 33 now respectively make conditional and forbid. **The
  `healthcheck_tooling` (`curl`) gate is deleted rather than narrowed**:
  `infrastructure.md § Codebase Containers` no longer mandates `curl` in a
  codebase image — it mandates that the image can run `./health.sh <service>`,
  and leaves the tool to the project. A gate enforcing a requirement the rule of
  record has withdrawn is worse than no gate.

  **One health assertion survives, narrowed**, as the new `contract_health_path`
  gate: where a `web`-network core service declares an `openapi` surface, one of
  its openapi contracts declares a `GET` on that service's **declared
  `health_check_path`** (not a hardcoded `/health`). *Any one* openapi surface
  satisfies it — requiring the path in every surface would force a `rest_admin`
  contract to document a route outside its own boundary, which is a worse defect
  than an omission. A non-`web` `openapi` provider declares no health route at
  all.

  `health.sh` joins `build.sh` and `test.sh` as an unconditionally required
  codebase shim (`migrate.sh` stays conditional on schema ownership). The gate
  roster goes from ten to nine.

#### Health leaves HTTP

- **The container probe is a command — `./health.sh <service>` — on both
  foundations (mod 127).** Every core service's container health check is now
  `["CMD", "./health.sh", "<service>"]`: a compose `healthcheck:` on fixed, an
  ECS container `healthCheck` on elastic. It is emitted from the `web`, `worker`,
  and `clock` role tables' **`defaults`** rather than from a field translation,
  because it needs nothing from `infra.yml` but the core service's own name — so
  a queue consumer or a cron loop gets a probe while declaring nothing, where
  before it had to declare `health_check_path` (which rule 33 now forbids it) and
  run an HTTP server it needed for nothing else. Cadence is doctrine-fixed and
  uniform, not a project-tunable field.

  `health_check_path` narrows to **one** surviving translation: `elastic` →
  `target_group`, the ALB's own HTTP probe, the one consumer that genuinely
  cannot run a command inside a container. Its fixed translation — the
  `curl -f http://localhost:$PORT$PATH` probe — is deleted; on fixed the field has
  **no consumer at all**, because the compiler emits no health-aware traefik labels
  (only `loadbalancer.server.port`). The field stays *declared* on the
  `web` role so a fixed project may still carry it and stay portable, and is
  removed from `worker` and `clock` entirely, which is how rule 33's negative arm
  is enforced at the table layer by rule 4 with no second rule.

  **Three derivatives deliberately get no probe**, each now pinned by a test with
  a positive control rather than by construction alone: the per-codebase `-exec`
  block and the elastic `_migrate` task definition (a one-off's liveness is the
  exit code it was invoked for — and on ECS, an essential container failing a
  probe gets the task *killed*, the wrong treatment of a job meant to end), and
  the paired `-otelcol` sidecar (a `FROM scratch` image with no probe tool would
  report `starting` forever). The exec block's `depends_on: service_healthy`
  gate is unchanged and reads backing services only; a test asserts no `-exec`
  block's `depends_on` ever names a core service, so "every core service now has
  a probe" cannot leak into that predicate unobserved.

  `startPeriod` is emitted on elastic and has no fixed counterpart, because the
  two orchestrators do different things with a failing probe: **ECS kills and
  replaces the task; Docker only reports.** A start grace prevents a container
  being killed before it has written its first tick; on fixed nothing acts on a
  failing probe at all — Docker reports and restarts nothing of its own accord — so
  there is no wrong consequence for a start grace to prevent.

  Prose that outlived the fan-out is reworded, and the logic behind it does not
  move: the elastic release's Service Connect reconcile still fires on exactly the
  same condition, but its stated symptom is no longer "the fan-out returns 503".
  It is that a consumer cannot resolve a name it `uses` **while both sides report
  healthy** — no external signal at all, the release looking clean, and the work
  silently not arriving. That is strictly worse than a 503, which is why the
  reconcile matters more after this change than before it.

#### The smoke seeds move onto both models

- **Both smoke-test seed projects move onto the new model (mod 129).** Source,
  contracts, and `infra.yml` in `test_projects/{fixed,elastic}` — the two trees
  downstream projects copy from, and the doctrine's reference implementation of
  the entrypoint and liveness rules. `api.web` declares a `rest` surface;
  `api.worker` declares **two** surfaces of one format (`rpc` and `events`,
  distinguished by unrelated consumer sets, which nothing else in the repo
  exercised); `api.clock` declares none, because it is consumer-only and nothing
  may `uses` it. Three contract files per project replace two, four-segment and
  rewritten, with their spec versions raised to the minimums `contracts.md`
  fixes — the seeds were shipping OpenAPI 3.0.3 and AsyncAPI 2.6.0 in violation
  of it, which nothing enforces mechanically
  ([`007_small_edges/contract_spec_version_ungated.md`](./docex/plans/advances/008_housekeeping/references/contract_spec_version_ungated.md)).

  **Health leaves HTTP in the seeds.** A new `core/api/health.sh` — the fourth
  codebase shim — branches on its argv: `web` curls its own route, `worker` and
  `clock` stat a tick file the loop touches from inside itself. Both loop-owning
  entrypoints lose their FastAPI health app, their uvicorn health server, and
  their in-memory tick; `api.clock` loses uvicorn, fastapi, and its listener
  **outright** and now binds no application socket at all, which is the clearest
  evidence in the change that it is not cosmetic. The `/health/api/worker`
  fan-out is deleted from the composition root, and the two backing-service
  reachability probes move from `/health/{probe,events}` to
  `/diagnostics/{probe,events}` — kept, because they are the only exercise either
  seed gives the project-local `sidecar`/`clickhouse` engines, but moved so no
  reader concludes the fan-out survived under a narrower name.

  The 30s staleness **threshold** now lives only in `health.sh`, which is the
  only thing that judges it; the ≤10s tick **cadence** lives only in the
  entrypoint, which is the only thing that can honour it. Each file names the
  other half, because 30 being three times 10 is what the pair means and one
  number alone does not show it.

  **`api.worker` keeps its `port` and gains a real `rpc` boundary** —
  `POST /drain`, which asks the worker to drain the deferred-job queue in its own
  process because the perform side of the queue belongs to it. This replaces the
  fan-out's HTTP edge with an application one, and adds a shape neither seed had:
  a **consumer-side gateway onto a sibling core service** (`GwyJobRunner` +
  `GwyJobRunnerHttp`, injected by the composition root), which is what rule 32's
  positive arm exists to govern. The port survives for a second reason recorded
  in the advance plan: a port-less worker registers no Service Connect name, which
  would have emptied the elastic release's reconcile consumer set and silently
  retired the seeds' only coverage of it.

  Staging tests narrow to what requires being outside. The liveness fan-out test
  is deleted — `docex stagetest` now reads liveness from the orchestrator before
  the tester image is built — and is replaced by a defer-then-drain round trip
  through the real ingress, asserting **no exact count**, because the worker's own
  poll loop legitimately races it.

### Fixed

- **Rule 33's `ec2_traefik` clause was false, and a stale docstring is what made it
  false (mod 134).** The rule said the compiler "still emits a target group carrying
  the path" on the `ec2_traefik_*` variants, "inert" because no ALB attaches. It emits
  none at all: `_destination_applicable` suppresses `target_group` whenever
  `reverse_proxy != "alb"`, and mod 070 is what did that. The false claim was built on
  `render_target_group`'s docstring, which still promised the target group was emitted
  anyway and deferred a cleanup mod 070 had already performed — so two docstrings in one
  file contradicted each other and the stale one was cited as evidence about current
  behavior. The rule is corrected to the stronger, uniform form (consumed on `elastic` +
  `alb` **alone**; no consumer at all everywhere else) and the docstring that misled it
  is gone. Recorded because it is this advance's own defect class reaching the rule of
  record: **a citation is not a measurement.**
- **Three doctrine files restated rules 32 and 33 in their pre-fix, contradictory forms
  (mod 134).** `cicd.md`'s check-step list restated rule 32 without the `web`-network
  exemption — the form that makes rules 15 and 32 contradict each other on the
  `frontend`/`api` topology — and both `cicd.md` and `healthchecks.md` called
  `health_check_path` "what the load balancer probes / reads" with no qualification.
  `cicl_reasoning.md` went further and used `health_check_path` as its canonical example
  of a field that "follows `role`", which rule 33 keys on **network membership**; the
  example is now `schedules`, which really is role-keyed. `ec2_traefik.md` twice called
  the ECS provider's `lastStatus == RUNNING` filter "health-gating" — it is a lifecycle
  state, and a task failing `health.sh` stays `RUNNING` and keeps taking traffic.
- **`transfer_tables.md`'s "always available" variable table was missing two variables
  the bundled tables use (mod 134).** `${service}` is real and load-bearing —
  `web.yml`, `worker.yml` and `clock.yml` all pass it to `./health.sh` — and
  `${codebase_name}` was likewise absent, in a table whose own validation rule 5
  requires every `${...}` to resolve to a known variable. `${networks}` was described as
  a list and is a comma-joined string. Deliberately **not** added: `${project_version}`,
  which is not a compile-time variable at all but a Python parameter the emitter
  interpolates — a row for it would have put a false claim in the one table whose entire
  job is enumerating what resolves. The `OTEL_RESOURCE_ATTRIBUTES` row that uses it is
  now marked compiler-composed rather than rewritten.
- **Two documented test invocations reported success while running nothing (mod 134).**
  `RELEASING.md` gated a cut on "`pytest` (incl. `-m integration`)" — bare `pytest`
  cannot collect this suite, and `pyproject.toml`'s `addopts` already carries
  `-m 'not integration'`, so the combined form matches nothing and exits 0. Running from
  the repo root fails the same way for a third reason (`tests.conftest` is unimportable
  there). Each failure mode reports a deselect count **one short** of the truth, which
  is what makes it believable. `docex_process.md`'s own warning about this carried two
  stale numbers (17 and 18; the real count is 21) and now states the method for
  re-deriving them instead of a figure that goes stale.
- **`PRE_CUT_CHECKLIST` carried seven defects into the two real-AWS walks it gates
  (mod 134).** A.3.1 called `preinfra development` "project-agnostic, run from either
  root" — it resolves the invoking project's own hostnames and its registry probe fires
  only for `fixed` with a `container_registry`, so one run left the other project's dev
  DNS and the whole probe unasserted. A.2 said the seeds "sit at `1.6.0`" when both were
  already at the candidate, risking tag surgery on a correct repo at the front of a
  walk; it now reads the version instead of restating it, having been a full release
  stale twice. A.4.1/A.4.2 required `test` DNS records for an env that is no longer
  routed or TLS'd and whose compiled compose contains no `Host()` rule at all — nine
  standing records become seven. B.11.1 pointed at `/health/events` for a route that
  lives at `/diagnostics/events`. D.9/D.11 expected a verdict on a version two releases
  behind. D.8 cited "the D.3/D.7 ordering" for a claim about D.4. And **no box recorded
  `check`'s `contracts_exist` output**, so the *orphan* arm — the only thing that catches
  a leftover three-segment contract sitting *beside* its replacement, which an existence
  check cannot see because the file it wants is also there — was asserted nowhere,
  despite B.9 promising it would be.
- **Three `doctrine_excerpts` entries showed compiled identities a rename ago (mod
  134).** `service_discovery.md`, `network_web.md` and `network.md` carried underscored,
  three-segment names (`myproject_dev_api`, `{project}_{env}_web`) where compiled
  identities are `${project}-${env}-${codebase}-${service}`. Advance 005's rename left
  **no stale nouns** — it added a *fourth segment*, which is why no vocabulary grep could
  find this. A full audit of the directory found 15 of 18 entries defective and three
  actively misinstructing; it is booked as an overhaul rather than folded in, because
  94% of the defects predate advance 006 and 14 trace to the directory's original
  authoring.
- **Two documents told a reader to delete a live validation check (mod 134b).**
  `compiler.md`'s probe section and `worker.yml`'s `fields: {}` comment both said rule
  33's negative arm is enforced "at the table layer by rule 4, with no second rule".
  There is a second rule and it is load-bearing: rule 4 only ever rejects a field the
  *engine* does not declare, so it cannot see a `role: web` core service sitting off the
  `web` network — which declares `health_check_path` legally as far as the table is
  concerned. `validate.py`'s dedicated `rule_33_health_check_path_off_web` is the only
  thing that catches that case, and
  `test_rule_33_keys_on_network_membership_not_role` is that case. Rule 33 keys on
  network membership, not on role; the table layer and the validator each cover what the
  other structurally cannot. `worker.yml`'s cross-reference to `clock.yml`'s `schedules`
  is corrected in the same edit rather than deleted: `schedules` is declared on no other
  role, so there rule 4 really *is* the whole story, and the asymmetry is the reason the
  two are not one mechanism.
- **`compiler.md` claimed the Jinja templates do no naming translation; four HCL sites
  re-derive the project segment and two of them get it wrong (mod 134b).**
  `project.tf.j2` and `main.tf.j2` render `{{ project | replace('_', '-') }}` at four
  places; two omit `| lower`. `project_dns_label` is never passed into HCL template
  context, and nothing validates `project.yml`'s `name` to lowercase — so a project
  named `MyProject` compiles, in one run, to `MyProject-traefik` and
  `MyProject-<env>-<short>` against `myproject-<env>`, while everything routed through
  `apply_policy` and the whole fixed side get `myproject`. On a case-sensitive AWS name
  those are different resources. No test catches it because no fixture has a capital
  letter, and the doc sentence is what would have stopped an author noticing. Corrected
  to state the divergence; **booked, not fixed** — patching four Jinja sites leaves the
  fifth author to re-derive it, and the real fix (normalize or validate the project name
  where it enters `docex`) is a behavior change.
- **A CLI verb that does not exist was named across eleven code sites (mod 134b).**
  `docex bootstrap` became `docex projinfra up production` in mod 034. Sites naming the
  **verb an operator types** are corrected — `errors.py`, `subprocess_runner.py` ×3,
  `containerize.py`, `bootstrap.py`'s header, and five comments in `main.tf.j2` /
  `project.tf.j2` that are emitted *into the operator's own HCL*, which makes them the
  copies most likely to be read. Sites naming the internal step keep their name, since
  `run_bootstrap` and `pipeline/bootstrap.py` are still called that; `compile.py` already
  modelled the honest form and was left alone. Alongside it, `__main__.py` and
  `projinfra.py` both still said elastic projinfra was "stubbed until mods 037-039".
- **Enumerations across `docex`'s own docs and docstrings had silently lost members
  (mod 134b)** — the defect class a vocabulary grep cannot find, because a grep for the
  new thing cannot find a list that lacks it. `masterplan.md`'s `src/` tree omitted
  `registry/` — the only absent
  package and the only unlisted client seam, in a tree whose `pipeline/` line *had* been
  updated for `orchestrator_health`. `compiler.md § Key types` had no entry for
  `surfaces`, `Surface`, `API_STYLE_FORMATS` or `IMPLEMENTED_CONTRACT_FORMATS` — the
  advance's headline field and its supporting types — its pipeline diagram named
  `emit/secrets.py`, which is not on the compile path, while omitting `schedules.py`,
  `otelcol.py` and `tags.py`, which are; `emit/tags.py` appeared in no core doc at all;
  and `effective_replicas` was credited to "both emitters" against three readers.
  `aws/client.py` described 34 methods as five bullets "Phase 4 needs",
  `opentofu/__init__.py` claimed four operations against five exported, and
  `ssh/client.py` claimed "the single SSH operation" against two. `masterplan.md`'s
  subcommand table understated what `config`, `envinfra` and `migrate` read; its SSH
  credential row omitted `stagetest` (which needs the deploy key **and** passwordless
  sudo); it stopped elastic `projinfra up production` at the state backend, omitting the
  two-phase project-tier apply; and it attributed ephemeral worktrees to `check` alone
  when `rollback` uses the same helpers as the point of the command. The Service Connect
  consumer reconcile — four AWS calls, one of them mutating — was missing from
  `masterplan.md` entirely and from `release_flow.md`'s own four-sequences table, in the
  file whose prose describes it.
- **Six docstrings and one core doc described behavior that no longer exists (mod
  134b).** `core_uses()` named `check.py` as a reader; `check.py` reads neither
  accessor, and the health gate it referred to was deleted this advance.
  `build.py` asserted the doctrine's one image requirement is `curl` backed by a
  `check` gate — both halves withdrawn by mods 126/127, so the argument keeps its shape
  and gains the true gate (`check` verifies the `health.sh` shim's presence).
  `stagetest.py` read an `infra.yml` `domain` field and a two-segment staging URL; the
  code reads `apex_domain` and builds three segments. `rollback.py`'s docstring was a
  CICL generation behind, and its three-example parenthetical was dropped rather than
  renumbered, because two of its examples now read as false against v3 —
  re-deriving that list for v2 would have re-armed the staleness. `EnvNotRunning` named
  `migrate dev/test` as a raiser and described a `compose exec` transport mod 099
  replaced. `MigrationFailed` has no raiser at all: kept, since it is exported, but
  annotated with the channel a migration failure **actually** uses (a propagated
  non-zero rc; `ECSTaskFailed` on elastic), because an unraised error class misleads only
  while a reader believes it is the channel. And `masterplan.md` said `release` migrates
  before applying — false on a first release, where the order inverts, and on rollback,
  which never migrates because the doctrine's migrations are forward-only.
- **A citation that every mechanical check passes and still sends the reader to the
  wrong document (mod 134b).** `compiler.md` cited rule 33 as `[rule 33](#validation)` —
  resolving to `compiler.md`'s *own* `## Validation` heading rather than `cicl.md §
  Validation Rules`, six lines after a correctly-formed citation of the same rule.
  `linkcheck` cannot see it because the anchor *does* resolve; it is the fifth instance
  of this class found in this advance.
- **The smoke seeds contradicted their own code in five places (mod 134b).** Both
  `db_schema.md`s claimed `pings.id` is a `uuid7` "for time-ordered insertion" — the
  domain calls `uuid4()`, so the stated property was false too — and both asserted the
  doctrine requires migrations to be "idempotent and **reversible**" where
  `databases.md` requires **forward-only** and `docex rollback` runs no migration at all.
  Both `processor.md`s called `FOR UPDATE SKIP LOCKED` "out of scope for this seed" while
  the `jobs` module ships it and four sibling docs treat it as load-bearing; the module
  boundary survives, narrowed to the module. Both `test.sh`s enumerated five of seven
  test files. The elastic `masterplan.md` gave per-env hosts without the codebase segment
  (`<service>.dev.…` against a compiled `api-web.dev.…`), disagreeing with the fixed
  companion, which states the canonical form. And `test_projects.md` named both seeds'
  domains as `doctrine-*` where every artifact uses `docex-smoke-*`. Seven dead prose
  citations across the two seeds are repointed — none was a markdown link, which is
  exactly why `linkcheck` never saw them.
- **`linkcheck.py`'s anchor check failed open, silently, on every target outside
  the scanned roots (mod 132).** The guard read `if rp in anchors and ...` against
  a table built only from *scanned* files, so a link into any unscanned tree had
  its anchor skipped with no output at all — under the headline "No broken links,
  bad anchors, or duplicate filenames found." Mod 121's entry below reports this
  same fail-open as addressed by scanning `skills/` as well; that closed the
  *instance* (skill→doctrine pointers) and left the *class* intact, which is why
  it is being fixed a second time. Anchors are now resolved on demand for any
  markdown target, and the count that resolved outside the scanned roots is
  **printed** — measured exposure was one anchor at each scope, both live, so this
  was hiding nothing today. The lesson generalised into the file: **a verifier may
  decline to answer, but it may not decline quietly.** Everything the tool cannot
  check — unverifiable anchors, ambiguous filenames, unbounded citations — is now
  counted and reported in a `Declined` block.
- **A dead prose citation in `PRE_CUT_CHECKLIST.md` that no link check could see
  (mod 132).** `B.1` cited `infrastructure.md § Codebase Structure` while
  anchoring correctly at `#repository-structure`; the file has *Repository
  Structure* and *Codebase Containers* and no *Codebase Structure*. The anchor
  resolved, so the words were nobody's to verify. Found by the new citation arm on
  its first run over the file it was built to reach.
- **The docs describing `check`'s contract and health gates described the deleted
  model (mod 131).** `masterplan.md` still narrated the two-armed provider union,
  format-from-`role`, the openapi fallback, self-health for every openapi provider,
  the `/health/<codebase>/<service>` fan-out, and "a core `uses` target must declare
  both `port` and `health_check_path`" — every sentence false after mods 125-127.
  Rewritten against what shipped. Mod 101's account of `_infer_contract_format`
  having returned `openapi` unconditionally **since the day it was written** — so
  the async-contract path never once executed and the fan-out flaw hid behind it —
  is kept as **history**, because it explains how a real defect survived months of
  green runs.

  Three more instances of one drift class were repaired with it. The pre-cut
  checklist told the walker to assert `GET /health/api/worker` returns 200 on
  **both** walks: a route deleted in mod 129, so a walker following the box
  literally would record a failure **against correct code** and stop the cut — the
  most expensive kind of checklist defect, because it burns a walk to teach you
  something false. `upgrade_2.0.0.md` listed **contract path** under "what does not
  move" while every contract in the release is renamed. And a false claim about
  traefik reading container health — true of no shipped configuration, since the
  compiler emits no health-aware traefik labels — had propagated to **five** sites
  (`tables/roles/web.yml` twice, `compiler.md`, and two of this cut's own changelog
  entries) from a single plausible sentence.

  Also: `doctrine_excerpts/` — the one aligned artifact with **no automated
  consumer** — was found stale in **nine of its eighteen** entries, and only **one**
  of the nine was caused by this advance. A dead prose citation `linkcheck` cannot
  see (it is prose, not a link); a shim list missing `health.sh`; an **inverted**
  fixed-side traefik topology ("machine-wide traefik", the opposite of the
  project-tier traefik the doctrine specifies) propagated across **four** files; a
  subdomain scheme predating `apex_domain` that omits the project segment entirely;
  and `example.env` still described as compile-emitted a full advance after mod 092
  deleted that emit. Five fixed here, four booked at
  [`007_small_edges/doctrine_excerpts_stale_entries.md`](./docex/plans/advances/007_small_edges/doctrine_excerpts_stale_entries.md)
  because each needs a rewrite rather than a corrected clause.

  **The vocabulary grep three mods relied on found exactly one of the nine**, which
  is the finding worth keeping. `docex_process.md` now records the verdict
  (`surface` earns **no** `index.yml` entry, with reasons) and two standing rules for
  sweeping this artifact: **a grep for the new thing cannot find a list that lacks
  it**, so a completeness pass must read every entry naming a *set* and ask whether
  the set is still complete; and an artifact with no automated consumer drifts **at
  the rate nobody looks**, not at the rate its subject changes — so a sweep should
  expect damage from releases other than the one it is sweeping for.

- **The ECS cluster name is one expression instead of five (mod 128).** The
  `<project>-<env>` cluster name — which is *also* the env's Service Connect
  namespace name — was computed verbatim in `release.py`, `orchestrate/migrate.py`,
  `pipeline/projinfra.py`, and `emit/hcl.py`, with `stagetest`'s new read about to
  make a sixth. All now call `naming.ecs_cluster_name`. The emitter/reader pair is
  what made it worth closing: `emit/hcl.py` *creates* the clusters the other three
  address, so a drift between them means a runtime read pointed at a cluster
  nothing created.

- **Twelve tests were red and the suite reported green.**
  `tests/integration/test_compile.py` holds 60-plus fast compile tests of which
  one carries `@pytest.mark.integration`, so the conventional pair of invocations
  — `pytest tests/unit` and `pytest tests -m integration` — has a hole between
  them that neither can see. Ten of the twelve were inline `infra.yml` documents
  invalid under rule 33; two had been red since advance 005 (a `cicl_version: "2"`
  pin and an assertion on the retired `depends_on`). All fixed as CICL
  conformance. The structural cause outlives the fix and is filed at
  `docex/plans/advances/007_small_edges/misfiled_compile_tests.md`, along with the
  measured fact that `pytest -m integration` **must be run alone** — run
  concurrently it produces five convincing false failures in migrate, up/down,
  and build.

- **The pre-cut checklist named the wrong Service Connect consumers** (mod 124).
  `PRE_CUT_CHECKLIST.md` D.9 and D.11 told the walker to record reconcile
  operands for "`api-web` and `api-worker` — they form a `uses` cycle", and the
  prescribed `describe-services` command queried that pair. Neither half was
  true: the elastic seed gives `api.worker` `uses: [appdb]` only, so it is a
  target and never a consumer, and there is no cycle anywhere in the project.
  The actual consumers are **`api-web` and `api-clock`**, both targeting
  `api.worker`, exactly as `release` reported during the 2.0.0 walk. A walker
  following the box literally would have looked for an `api-worker` reconcile
  line, not found one, and read a correct release as a regression.

  **The repair is shaped to detect its own rot.** The defect existed because a
  static claim about `infra.yml` was written into the checklist and drifted
  silently when `infra.yml` moved; correcting the pair alone would leave that
  mechanism fully intact. Both boxes now derive the consumer set from the rule
  (a **core-targeted** `uses` entry) rather than asserting a pair, and add a
  clause keyed on the executor's own output — `release` prints
  `N consumer(s) checked`, and `N ≠ 2` means the box is stale. An assertion
  keyed on what the tool reports cannot drift away from what the tool does.

- **The smoke seeds' cleanup checks could not fail** (mod 122). `verify_clean.sh`
  exited 0 reporting `OK: registry images` while thirty image tags remained in
  the registry, and had done so for several releases. Four stacked causes: the
  registry query sent no `Authorization` header and the 401 was swallowed by
  `|| true`; the digest lookup offered only `manifest.v2+json`, which resolves
  nothing for the OCI index buildx actually pushes; the local-image pattern
  required a trailing `/` and so missed `…-stage-tester:latest`; and the repo
  list was hardcoded to the project's *current* codebases, making repos retired
  by a rename structurally invisible. The **elastic** seed carried a larger form
  of the same defect — 21 swallowing query sites and no credential preflight, so
  expired credentials or one missing IAM permission made all ~20 AWS checks
  report `OK` and the script exit 0, on the gate that certifies an AWS account
  has stopped billing. Both scripts are now built on one stated rule — **a check
  that cannot answer must fail, not report zero** — and both are verified by
  being observed *failing* first, including the withheld-credential and
  unreachable-command cases the previous versions passed.
- **The smoke seeds' `jobs` tests raced the live `api.worker`** (mod 122).
  `docex test` brings the whole `test` environment up before running `test.sh`,
  so a live worker drains the same queue the suite writes to. The tests assumed
  sole agency and so failed intermittently — passing on a cold machine, failing
  once image layers cached, which **hard-blocked `docex check` and therefore the
  whole CI/CD chain**. The concurrency test now counts the live worker as a
  third claimer (identifiable by the "no handler" error it stamps on unrecognized
  job names) and asserts exclusivity across all three, which is stronger than the
  two-thread form it replaced; agency-shaped assertions moved to the alogic tier
  against a stub queue, where the doctrine puts them anyway.
- **The preinfra container registry could not delete images.** `teardown.sh`
  assumed `storage.delete.enabled`, but nothing in the doctrine required it, so
  every manifest `DELETE` returned `405` and
  [`container_registry.md § Garbage Collection`](./doctrine/infrastructure/preinfra/container_registry.md#garbage-collection)
  documented a procedure that could not run against the registry the same file
  specified. `REGISTRY_STORAGE_DELETE_ENABLED: "true"` is now a stated
  requirement of the registry container, with a deletion round-trip added to
  § Verifying Reachability so the setup walk proves it.
- **A clock with a mistyped schedule now fails its deploy** (mod 122). `clock.md`
  claimed the check step "can assert" that every declared job name has a binding;
  nothing implemented it. The assertion now lives in the clock itself: it
  compares its schedule against its dispatch table at startup and exits non-zero
  **before entering the cron loop**, naming both the offending job and the
  implemented set. A bound job with *no* schedule stays legitimate and is
  deliberately unchecked, since the driving port is shared with HTTP and CLI.
- **The canonical `infra.yml` example did not compile** (mod 121). `cicl.md`'s
  reference fence — the one every project author copies first, and the one
  `upgrade_2.0.0.md` sends readers straight to — used `database` as a backing
  service name, which the postgres engine **reserves**; indented with literal
  **tabs**, which YAML forbids; and violated **its own rule 7**, holding a magic
  ref to a `bucket` that two of its three core services never declared. Sibling
  examples in `shape.md`, `transfer_tables.md`, and `config_and_secrets.md`
  carried the same reserved name, and `shape.md`'s fence additionally omitted the
  required `observability_backend_url`, so it failed at parse before validation
  ever ran. All examples now use `appdb` (matching both smoke projects), indent
  with spaces, and compile clean. The `bucket` ref moved from the codebase-level
  `env:` into `web`'s own — fixing the rule-7 violation *and* making the fence
  demonstrate the codebase/core-service `env:` merge it never showed before,
  rather than teaching readers to declare edges they do not have.
- **A doctrine file documented a mechanism the doctrine had retired** (mod 121).
  `reasoning/elastic_release_pattern.md` — written at the head of this advance
  and never revisited — still described a **double-rollout** of every ECS service
  driven by shape-change detection during the release. Mods 119/120 replaced that
  with a per-consumer reconcile keyed on durable state, and `docex` never
  implemented the double-rollout at all. Rewritten rather than deleted: the
  motivation (the ordering problem is real, and cycles make creation-ordering
  impossible) survived the mechanism change, and the file now routes to
  `release.md` for the mechanism instead of restating it, so it cannot drift the
  same way twice.
- **Three conditional-stratum files were unreachable** (mod 121).
  `cicl_reasoning.md`, `elastic_release_pattern.md`, and `healthchecks.md`
  declared `stratum: conditional` but no skill pointed at any of them — and the
  conditional stratum reaches an agent *only* through thread skills. Notably
  `cicl_reasoning.md` holds the codebase-vs-core-service field-scoping heuristic
  this entire advance turns on. Now routed from `infra-compile`, `cicd-pipeline`,
  and `contracts` respectively, as is the orphaned configurable-values chart
  (renamed `charts/configurable_flow.md`, resolving a duplicate filename).
- Assorted corpus repairs (mod 121): the configurable-values chart pointed the
  **config** box at the secrets file — the one artifact an agent reads to learn
  where values live, aiming config at the file agents are forbidden to read; TTE
  records were described as `dev` and `stage` rather than `dev` and `test`; the
  rollback pre-flight named a stale CICL generation; `elastic_alb.md` and
  `ec2_traefik.md` still used one-segment core-service identity in six places;
  and the `chain_of_command.md` escalation ladder had each rank escalating to
  itself.

- **`docex build` leaked disk without bound and could not clear its own
  `dist/`** (mod 119). `orchestrate/build.py` cleared `core/<codebase>/dist/`
  from the host with `shutil.rmtree`, but that tree is container-owned:
  everything in it is written as **root** through the bind mount — the initial
  artifact copy at `up` time, `build.sh` under `compose run`, and the dev core
  service's `__pycache__` on import. Unlink permission comes from the *parent*
  directory, so the host uid could delete a root-owned `dist/app.py` but nothing
  inside a root-owned `dist/__pycache__/`, and the build died with
  `PermissionError`. It was self-regenerating — `up` created the residue its own
  `build` then could not delete — which is why clearing it by hand bought
  exactly one green run. The clear now happens **inside** the exec container,
  where the process that wrote the files can remove them, folded into the same
  one-off run as `build.sh` so the hot iteration loop pays for no extra
  container start. Any checkout already carrying residue self-heals on its next
  `docex build`, with no operator `sudo`.

  The disk consequence was larger than the failing build. Root-owned residue is
  tiny but **unremovable**, and a directory that cannot be emptied makes its
  whole enclosing tree unremovable — so on the development machine it had pinned
  **30 GB** of `/tmp`, mostly downloaded OpenTofu provider binaries that nothing
  could reclaim. It first presented as two unrelated `tofu validate` tests
  failing on `no space left on device`, a signature that looks nothing like its
  cause. Note the shape of it: the residue was never the volume, only the pin.

  Two consequences for the `dev` stage image and for anyone reading `dist/`:
  it must carry `find` as well as `sh` (both are present in any base with a
  build toolchain; a missing `find` fails the build immediately and loudly),
  and a root-owned file in `dist/` after a build is **correct** — the artifact
  is written by a root container by design. What changed is that `docex` no
  longer requires the host uid to delete anything there.

- **An interrupted elastic release could leave a permanently broken env and exit
  0** (mod 114). The Service Connect consumer reconcile diffed the post-apply
  namespace against a snapshot taken *before* any apply in the same release. That
  snapshot lived in one process's memory, so a release that registered a new
  endpoint and was then interrupted — expired credentials, a dropped connection,
  `Ctrl-C` — could never be repaired by re-running: the re-run's own snapshot
  already contained the name, the diff came back empty, and the consumer's tasks,
  which started before that name existed and can therefore *never* resolve it,
  were never replaced. On `stage` the staging tests' `503` caught it. On `prod`
  nothing did; both sides report healthy while every call across the edge fails.

  The trigger's operands are now both durable AWS state read **after** the apply:
  a core service is redeployed iff its **PRIMARY ECS deployment** was created at
  or before the Cloud Map `CreateDate` of a name it `uses`. The step therefore
  describes the env rather than the release that produced it, and every way an
  env can end up broken — an interrupted release, a hand-run `tofu apply`, a
  service created out of band, a rollback — is repaired by the next release. The
  "no-op unless the shape changed" property is not lost but **emergent**: in a
  converged env every consumer's deployment postdates every registration, so
  nothing fires. Ties break toward redeploying; a false positive costs one
  rolling deploy, a false negative costs a broken env that exits 0.

  The consumer-side operand took two attempts (mod 123 corrected mod 114 before
  either shipped). Mod 114 compared task `startedAt`, on the recorded reasoning
  that a Cloud Map name created *before* any of its tasks made the comparison
  strictly more conservative. That inference was inverted: `CreateDate` is
  stamped at ECS *service* creation, so a task of that service always starts
  after it, and `startedAt <= CreateDate` cannot hold whenever consumer and
  target are created by the same apply — every first release, and every release
  that bumps the consumer's image. The 2.0.0 elastic smoke walk found the check
  inert on `prod`: a 503 fan-out for 20+ minutes that two clean `release prod`
  runs printed nothing about and repaired nothing of.

  The margin constant is **60 seconds**, and it is deliberately *not* a
  clock-skew allowance — the genuine uncertainty is a few seconds. It collapses
  the concurrent-creation window into a redeploy, because inside that window the
  boundary is unmeasurable and the two errors are not symmetric: a false negative
  is permanent and silent, a false positive is one rolling deploy. On an ordinary
  code-only release the gap is days or weeks and the step is still a no-op.
  `release` now states its verdict either way — a skip prints what it checked
  rather than saying nothing.

  `aws_ecs_service` now emits `wait_for_steady_state = true`, so the apply does
  not return while its own rollout is still draining tasks the reconcile would
  otherwise misread. A knock-on effect worth knowing before you upgrade: a
  service that cannot converge now fails `tofu apply` rather than letting the
  release proceed, and elastic applies take correspondingly longer.

  The premise underneath the whole mechanism was measured on scratch Fargate
  stacks rather than taken from the AWS docs, twice. The first run established
  that a client cannot resolve a name registered after it launched: 27 probe
  cycles over five minutes with byte-identical `UNRESOLVED` output, and the
  replacement task resolving on its first cycle. The second established *which*
  event freezes the name set — the **deployment**, not the task. Every Envoy
  identifies to the control plane by its task-set ARN (the deployment id) and is
  served a cluster list fixed for that deployment, so a task stopped and replaced
  inside the same PRIMARY deployment probed 47 times over eight minutes and never
  resolved a name created five minutes earlier. Replacing a task does not help
  unless the replacement lands in a new deployment — which is what
  `forceNewDeployment` actually buys.

- **Rename residue in `docex`** (mod 111). The sweep that performed the rename
  substituted the *word* without re-reading the *sentence*, leaving three classes
  of defect behind. A **doubled substitution** produced operator-facing text that
  says nothing — `cicl/model.py`'s migration error read "moved from the core
  service to the core service", the same noun on both sides of a sentence whose
  only job is to distinguish two levels, on the single error every downstream
  project hits exactly once while upgrading. **Terminal output named the wrong
  kind of thing**: `docex build nonexistent` answered "is not a core service;
  known core services: [...]" while listing codebases, and the exec-key failure
  said "not a core service in infra.yml, declares no core service" for a codebase
  declaring core services. And **one emitted key was missed outright** —
  `describe --format llm` still labelled a codebase `core_service`.

  Also corrected: the CICL v1 rejection message, which described 1.6.0's v2
  (top-level `core_services:`, four-segment refs) while the parser enforces
  2.0.0's v2, so an operator who followed it produced a document the compiler
  rejects; it now describes the accepted shape and chains both upgrade guides.
  `validate.py`'s two `_STANDARD_*` field sets were inverted against their own
  contents and are swapped. `CompiledService.service_env` holds the
  codebase-scoped surface and is renamed `codebase_env`. ~100 local identifiers
  that named a codebase `svc` and a core service `proc` now read `cb` and `svc`.
  Dead `service_name` parameters and three impossible `where=` error paths
  (`codebases.<compiled-identity>.resources`, a path rule 22 forbids) are gone.

- **The six-artifact alignment sweep** (mod 118), closing out the advance. Two
  doctrine examples the compiler would have **rejected** are fixed:
  `shape.md`'s otherwise-v3 example still declared `cicl_version: "2"`, and
  `transfer_tables.md`'s two worked examples named an undeclared `appdb` in
  their `uses:` lists. Both are now proven by compiling rather than by reading.
  `doctrine_excerpts/secrets.md` cited
  `specifics/release_mechanism.md § Secrets` — a file and a heading that have
  **never existed**, dangling since the original bulk commit because nothing
  link-checks that artifact; found by a mechanical check that is now
  repeatable. `doctrine_excerpts/service_discovery.md` gained the Service
  Connect task-start name freeze, the property advance 005 made load-bearing
  and measured, which it had described elastic discovery without.
  `release_flow.md` was stale in six places at the v2→v3 bump — including a
  failure-mode row using `cicl_version '3'` as the *rejected* generation when
  it is the only accepted one, teaching the exact inverse of the truth. That
  message is parameterized in `rollback.py::_boundary_message` **specifically
  so it could not go stale**; the doc drifted because it restated the message
  instead of quoting its rendered output, and that lesson is now written into
  the doc. `masterplan.md` documented `bootstrap`, `up`, and `down` as
  commands — none exist — while omitting `preinfra`, `projinfra`, `envinfra`,
  `roles`, and `role`; its repo-structure block named packages (`compile/`,
  `bootstrap/`) that are not there. `skill_iter`'s `infra-compile` outcome eval
  graded a correct answer wrong by hard-coding `depends_on` as expected output
  — invisible to both pytest suites, failing only at the skills release gate.
  Both smoke projects shed prose residue: five stale "four-segment" magic-ref
  descriptions beside correct five-segment refs, and six sentences where a
  blind `service` → `core service` rename had been applied where **codebase**
  was meant, leaving "`web` and `worker` were separate core services until CICL
  v2" self-contradicting a correct sentence twelve lines above it.

- **`doctrine_excerpts/` now records what earns an entry** (mod 118).
  The artifact with no automated consumer had no stated inclusion criterion, so
  every advance re-litigated it and a "no" was indistinguishable from an
  oversight. `docex_process.md § Additional Artifacts` now states the rule — it
  indexes **infrastructural resources**, not CICL fields and not roles — and
  records that `uses` and `clock` were considered and deliberately excluded:
  `uses` is a relation whose two predecessors never had entries, and `clock` is
  a role already served correctly by the generated `docex role` surface.

- **The trigger eval was measuring the harness, not the descriptions** (mod 135).
  `run_suite.py::detect_triggered_skill` called `subprocess.Popen` with no
  `cwd=`, so the child `claude -p` inherited the runner's cwd — this repo, where
  `doctrine/` sits in the working directory. The model under test could
  `grep doctrine/` instead of loading a skill; observed as a first tool call.
  No downstream operator has that shortcut, and a trigger eval is only valid
  when loading the skill is the **only** route to the doctrine. Each query now
  runs in its own `tempfile.mkdtemp()` sandbox. The confound did not add noise:
  it **systematically converted precision failures into recall failures**, since
  a query that would have been mis-routed was instead answered from the
  filesystem and scored ∅, which reads as under-triggering. That is the one
  direction that makes a trigger surface look healthier than it is, and it
  invalidated this advance's skills gate in both directions at once — the gate's
  *"precision 1.00 for every skill, no poaching"* is withdrawn, because on the
  corrected harness `contracts` poaches `infra-compile`'s surfaces-authoring
  query 5/5. Two descriptions had already been edited off the bad numbers; one
  survived re-measurement and one was reverted. `run_eval.py` carries the same
  confound but its `cwd` is load-bearing (it installs the skill under test into
  `<project_root>/.claude/commands`), so that fix is a restructure and is booked
  rather than absorbed. `RELEASING.md`'s skills gate now names which of the two
  runners is trustworthy.

- **A timed-out trigger run scored as "no skill fired"** (mod 135).
  `detect_triggered_skill` fell through to `return None` when its deadline
  expired, and `None` is also how it reports that the model acted and reached for
  no skill — so saturation was recorded as a **recall failure**. Found by
  disbelieving a number: the first full-suite run returned 17% accuracy with
  near-universal ∅, including two queries measured at 5/5 twenty minutes earlier,
  at load average 31 with `--num-workers 8`. The same queries at 2 workers passed
  3/3. This is the cwd confound's twin and worse for being **load-dependent** —
  the same command on the same tree yields different "findings" depending on what
  else the box is doing — and it fails in the same flattering direction, inventing
  holes rather than revealing them. There is now a `TIMEOUT` sentinel distinct
  from `None`, timed-out runs are excluded from the modal vote, a query whose
  every run timed out is reported `unscored` rather than wrong, accuracy reads
  `n/a` instead of a fabricated figure when nothing scored, and a loud warning
  names the remedy. All three of this mod's instrument defects share one shape:
  each reported a condition unrelated to the measurement *as* the measurement,
  and each did so in the direction that looks like an actionable finding rather
  than a broken tool.

- **`infra-compile` was unreachable for the concept advance 006 gave it** (mod 135).
  The advance handed it the surfaces-**authoring** role in its body and never
  touched its `description`, which is the entire trigger interface. Asking where
  the `surfaces:` block goes in `infra.yml` routed to `contracts` every time —
  a sibling that owns contract *contents*, not CICL authoring. The description
  now names the `surfaces:` / `uses:` blocks alongside `secrets:` / `config:`,
  anchored to authoring a block in `infra.yml` so it does not reach back into
  `contracts`' territory. Measured 5/5 to `infra-compile` after, on the
  corrected harness. `contracts`' description is deliberately **unchanged**: its
  reported hole did not reproduce once the confound was removed.

- **Two outcome-eval cases graded a correct answer wrong** (mod 135).
  The same defect class as the `depends_on` case above, and it cost this advance
  twice more. `outcome/contracts/evals.json` drove its delta off the
  `/health/worker` downstream fan-out and a three-segment contract path — both
  doctrine this advance **deleted** — so a correct answer failed both drivers and
  the gate could report only a false negative. `outcome/testing/evals.json`
  asserted as confirmatory that staging tests include liveness probes, which this
  advance reversed. Both are current, and drivers were re-chosen by grepping each
  candidate against the 13 `stratum: resident` files: surfaces, the five-segment
  path, the style→format mapping, `health.sh`'s existence **and** the
  loop-liveness tick are all Resident-supplied and therefore measure leakage
  rather than value — they are demoted to confirmatory, leaving the 10s/30s
  thresholds, `web`-only HTTP health, the `{version}` body shape, the no-fan-out
  rule and staging's liveness exclusion as the real drivers.

### Added

- **`docex preinfra development` probes the container registry's manifest-delete
  capability (mod 133).** On a `fixed` project with a `container_registry`, the
  command now issues one authenticated `DELETE` of a 64-zero digest under a
  nonexistent `preinfra-smoke/` repository — no image is pushed and nothing can
  be deleted, so the probe is side-effect-free against preinfra shared by every
  project on the machine. A `405` carrying the registry's own `UNSUPPORTED` code
  is a **failure** naming `REGISTRY_STORAGE_DELETE_ENABLED`: without that flag
  every `fixed` project's `teardown.sh` leaks one registry tag per release and
  garbage collection cannot start. Previously the requirement was stated in the
  doctrine but never checked, and the misconfiguration survived several releases
  because the cleanup checks downstream of it could not tell a `405` from a clean
  registry.
- **`preinfra` now distinguishes *declining* from *failing*.** Registry
  reachability and auth are outside `preinfra`'s documented scope, and
  `preinfra development` is the gate `envinfra up dev` runs — so no credential,
  an unreachable host, a timeout, a `401`, or any response no verdict can be read
  from is **printed by name with its own resolution** under a new `Declined`
  heading at **exit code 0**, rather than blocking a dev stack that never touches
  a registry. Only in-scope questions answered wrong set exit code 1. A verifier
  may decline to answer but may not decline quietly; what is new is that
  declining an out-of-scope question is not the same act as failing an in-scope
  one. Note when reading a green run: a declination is not a pass.
- **`docex stagetest` reads liveness and version from the orchestrator, and
  fails before it builds the tester (mod 128).** Step 1 of the staging-test
  process is now a foundation-aware pre-step: `docker inspect` **over SSH** to
  the deployed host on fixed (`stage`/`prod` containers do not run on the
  operator's machine), ECS `list_tasks` / `describe_tasks` /
  `describe_task_definition` on elastic. Every core service must be healthy and
  running the image tag matching `project.yml`'s version, or `stagetest` fails
  there — before the stage-tester image is built. **This is the liveness
  assertion; nothing downstream repeats it**, which is what lets staging tests
  narrow to what genuinely requires being outside the stack. Version comes from
  the deployment record rather than a self-report, so a container running last
  week's image cannot misreport it; when the orchestrator and a self-report
  disagree, the orchestrator wins.

  **A probe's output is never parsed.** Docker captures healthcheck stdout and
  ECS surfaces only a status, so anything read from probe output would work on one
  foundation and silently not on the other. Liveness is the orchestrator's
  aggregated state; version is the deployment record.

  Two error classes, deliberately distinct: `DeployedServiceUnhealthy` (the
  orchestrator answered and the answer is bad) and `OrchestratorStateUnreadable`
  (docex could not obtain an answer at all). The split is the structural point of
  the change — it makes "the gate broke" untypeable as "the env is fine." **No
  empty result set reads as healthy** anywhere in the gate: zero core services,
  zero RUNNING tasks, a container with no health state, an unreadable
  task-definition revision, an image ref with no readable tag, and `rc 0` with
  unusable `docker inspect` output all fail loudly and by name. On elastic, a task
  set that shrinks between `list_tasks` and `describe_tasks` gets **one** bounded
  re-read — ECS replaces tasks on its own schedule, so one unlucky replacement
  mid-read is not evidence about the release — then fails; the re-read is scoped
  to a shrinking task set only, never to a task that was returned and reported
  unhealthy, which is what makes it structurally unable to mask an unhealthy
  service. **The gate has no flag that disables it**, deliberately and
  permanently.

  Three new `AWSClient` methods (`ecs_list_service_task_arns`,
  `ecs_describe_tasks`, `ecs_task_definition_images`) whose contract is the
  *inverse* of the neighbouring `ecs_primary_deployment_times`: that one swallows
  a missing cluster because its caller reads absence as "redeploy"; these raise,
  because an unreadable service must never be indistinguishable from a healthy
  one. Both docstrings name each other so the swallow cannot be copied into the
  wrong place.

  One asymmetry is known and accepted: on fixed the version comes from
  `.Config.Image`, which proves the image *ref* and not the bytes — a re-pushed
  tag would pass. No project records an expected digest to compare against, and
  `healthchecks.md` specifies the ref.

- **A job must tolerate a cold schema** (mod 124). `clock.md § Caveats` gains a
  fourth bullet stating an obligation the doctrine had never written down.
  Nothing gates a core service's startup on its backing services, and
  migrations run *after* the stack is up — in `dev`/`test` on both foundations,
  and after `tofu apply` on an elastic env's first release, where a clock is
  **guaranteed** to meet the window. Because a clock fires on its own schedule
  rather than in response to a request, it is the service that reaches a cold
  schema first: the 2.0.0 elastic walk watched `api-clock` fire `heartbeat`
  against a schema that did not exist yet and log
  `relation "jobs" does not exist`. That is the documented ordering working as
  designed, not a fault — it self-heals on the next slot with no operator
  action and no effect on the clock's health probe — but it obliges a job to be
  safe to attempt again after failing before it did anything at all.
  `migrations.md § First-Time Release of an Env` names the clock as the service
  guaranteed to exercise that window, and the elastic walk's D.11 clock group
  now says the stack trace is expected, with the inverse tell stated: a clock
  still failing two ticks after the migration completed *is* a finding.

- **The `cohere` skill checks examples by compiling them** (mod 121). New
  executor `skills/cohere/executor/verify_examples.py` extracts every `yml`
  fence under `doctrine/` + `skills/` and pushes the `infra.yml`-shaped ones
  through docex's real parse-and-validate path, so an example is proven by
  compiling rather than by reading. It classifies each fence, because the class
  decides what "pass" means — and the two classes that are *deliberately not
  standalone documents* (`ILLUSTRATIVE`, `EXCERPT`) are reported on their own
  lines and never counted as passes. Promoted after the same throwaway script
  caught the canonical example broken **twice** across two mods while existing
  only in a scratchpad: a check that is not shipped is not a check.
- **`linkcheck.py` covers `skills/`** (mod 121). `doctrine.md` calls keeping
  thread-skill pointers valid "the one ongoing cost of this structure, and it
  should be checked mechanically" — but the executor walked `doctrine/` only,
  and its anchor check silently *failed open* on any target outside the scanned
  root. Since a section rename is exactly what dangles a router link, and this
  advance renamed three, skill→doctrine links are now scanned and anchors
  resolve across both trees. The duplicate-filename check stays scoped to
  `doctrine/`, where the uniqueness rule was written; `skills/` legitimately
  carries one `SKILL.md` per skill.
- **`docex why codebase`** (mod 111). The doctrine's now-primary noun had no
  excerpt, so the one resource `docex why` could not explain was the unit of code
  itself. `docex_process.md`'s artifact-alignment table gains a sixth row for
  `doctrine_excerpts/` — the only aligned artifact with no automated consumer,
  and therefore the one that drifts silently.

- **`role: clock` compiles** (mod 115). A `clock` core service — the singleton
  cron loop that defers work onto its own codebase's queue — is an **ordinary
  long-running core service** with a sidecar, a health probe, and **no
  exemptions**: a compose service on fixed, `task_definition` + `ecs_service` on
  elastic. Its role table is modelled on `worker`, not on the `scheduler` it will
  replace. `role: scheduler` is untouched by this change and still compiles; it
  is retired separately.

  A clock declares `schedules:`, a map of job name → **bare 5-field UTC cron
  string**, required on a clock and rejected on every other role. There is **no
  cron dialect translation anywhere** — the expression passes through to the
  clock unchanged, which deletes the 6-field / `?`-day / Sunday-is-1 class of
  bug outright. Validation rejects an absent or empty map, a job name that is not
  a valid identifier (job names are dispatch keys), and a malformed expression,
  reporting one issue per offending job.

  The compiler renders `infra/output/<env>/schedules.yml` for **visibility** —
  git-tracked and diff-visible, so a schedule change reviews as an
  infrastructure change — and delivers each clock its own job map through
  **`DOCEX_SCHEDULES_YAML`**, one literal env var, identical on both
  foundations. No mount, no path variable, no per-foundation branch in a project's
  clock entrypoint. The variable is reserved: a project may not declare it.

  On elastic a clock alone is emitted with
  `deployment_minimum_healthy_percent = 0` / `deployment_maximum_percent = 100`,
  forcing stop-then-start so a rolling deploy cannot briefly run two clocks and
  double-fire a tick. This trades a possible double fire for a possible missed
  fire — the right trade, since missed fires are already an accepted caveat and
  jobs must be idempotent regardless.

- **`specifics/clock.md`, and a worked reference implementation of a clock**
  (mods 117, 120). `specifics/clock.md` replaces `specifics/scheduler.md` as the
  one document answering *"how do I schedule work"*, and every inbound pointer
  moved with it — a project author still finds exactly one document. Alongside it,
  the two smoke projects' `api` codebase is now the clock's **reference
  implementation**: `entrypoints/clock.py` → `ContJobsCron` → a driving port →
  a `Queue` driven port, with the **defer-side** dispatch table (job name → the
  port method that enqueues) and the **perform-side** table (job name → the work)
  kept deliberately separate. Collapsing them would couple the clock to the
  worker's implementation and destroy the deferral architecture. Downstream
  projects copy that tree, which is why it is announced rather than left to be
  found.
- **`linkcheck.py` reads citations, and its two checks now scope independently
  (mod 132).** A citation has two halves that drift apart — a machine-readable
  anchor and human-readable words — and only the anchor was ever checked. The tool
  now resolves the words of a `<file>.md § <Heading>` reference against the target's
  real headings, in link text and in inline-code spans alike. Three instances of
  exactly this drift were found *by hand* during advance 006 and a fourth by the
  arm's first run. Two design facts are worth recording because they are what makes
  it shippable rather than noisy. First, **the naive version reports 98 false
  positives**: the dominant form in this corpus is a citation inside markdown link
  text, whose anchor check 1 already resolves, so matching `<file>.md §` on a raw
  line duplicates a working check and fires on a clean tree. Second, a citation
  whose heading text has **no closing delimiter** — bare prose running into the
  sentence — has its file verified and its heading *counted, never guessed*; three
  measured shapes each defeat a different guess about where the text ends, and a
  wrong finding provokes a wrong repair. Bounding a citation in one backtick span
  is what brings its words into checked scope. Alongside, the duplicate-filename
  check becomes an **allowlist of the doctrine corpus** instead of every root minus
  `skills/`: the exemption list had grown twice for one reason (mirrored trees are
  mandated — by the Agent Skills Standard, by audit box B.14, and by
  `doctrine_excerpts/`'s design), and as an allowlist, widening the scan can never
  make the check fire. That is what lets the default scan reach
  `PRE_CUT_CHECKLIST.md` — which gates both smoke walks — and `doctrine_excerpts/`,
  the one aligned artifact with no other automated consumer, while still exiting 0
  on a clean tree. **Released `CHANGELOG.md` sections are excluded from both
  checks**, here and in the seed projects: they are frozen history, and a link
  target may be repointed where a claim may not. The executor gains its own unit
  suite at `skills/cohere/executor/tests/` (21 tests, bare `python3`, no venv),
  whose centrepiece is a positive control — because this advance produced two
  tooling *false* positives, and a checker that reports violations where none exist
  is as corrosive as one that misses them.

### Removed

- **`role: scheduler` and every carve-out it forced are deleted from the
  compiler** (mod 116). Not deprecated — removed. `docex roles` now lists six
  roles and `scheduler` is not among them.

  Gone with it: the **Ofelia** trigger container, its INI renderer and the
  secret-sourcing job-command wrapper on fixed; the **EventBridge** path on
  elastic (`aws_scheduler_schedule`, the per-service
  `scheduler.amazonaws.com` invocation IAM role and its policy); the
  `scheduled_task` emit destination; the `scheduler` role table; and the
  **cron dialect translation** module entirely (`to_aws_cron`,
  `to_ofelia_cron`, the Sunday-is-1 day-of-week remap). A clock reads a plain
  5-field UTC expression, so no dialect-mismatch bug class remains to
  translate for.

  Three quieter removals ride along, each dead once the role went. The
  `-scheduler` **reserved suffix** leaves rule 5's derivative set, which now
  matches the doctrine's list exactly (`-otelcol`, `-exec`, `-migrate`,
  `-1`…`-N`); the rule stays keyed on *collision* rather than on a
  reserved-name list, so nothing is permitted by fiat — a name simply stops
  colliding with a derivative the compiler no longer emits.
  `scheduler_only_services` and `up`'s `_ensure_codebase_image` go with the
  "codebase whose image no compose service builds" shape, which can no longer
  be constructed. And `DOCEX_SECRETS_ENV_FILE` — which existed solely so
  Compose could interpolate a path into the Ofelia INI — leaves along with the
  `extra_env` parameter that carried it, narrowing the docker port.

  **`role: clock` is unaffected and is the replacement.** See the `Added`
  entry above for what it does and the `Changed` entry for the doctrine.

## [1.6.1] - 2026-08-03

### Fixed

- **Services on non-`web` networks regain internet egress** (mod 110). The
  compiler emitted every non-`web` env network with Docker's `internal: true`,
  which strips the bridge's masquerade rule and so denied *all* outbound access
  to any container whose only attachment was such a network. That contradicted
  the rule of record: `networks.md § Egress` states that on fixed "outbound
  requests leave each container via Docker's normal `iptables`-managed NAT
  through the host's default route — nothing project-specific or
  doctrine-emitted is involved." The flag appeared nowhere in the doctrine, the
  transfer tables, or the core docs; it was code drift, and it is now gone. A
  non-`web` network is a plain user-defined bridge with no published ports,
  which already delivers everything the doctrine promises: reachable from
  services on the same network, not from other networks, not from the public
  internet. Measured on Engine 29.4.1, `internal: true` contributed **no**
  ingress protection over a plain bridge — cross-network isolation comes from
  Docker's inter-bridge isolation rules, and the host reaches an internal
  network's containers just as easily since the gateway sits in-subnet — so its
  only effect was the egress loss. Two consequences: **fixed↔elastic parity is
  restored** (the elastic `internal` SG is self-ingress plus allow-all egress,
  so the same `infra.yml` previously reached a third-party API on elastic
  `stage` and failed on fixed `stage`, violating masterplan goal 5), and **a
  latent fixed `stage`/`prod` telemetry break is closed** — the OTel sidecar
  shares its partner's netns via `network_mode: service:<container>`, so a
  `worker`/`scheduler` on `networks: [internal]` had a sidecar with no route to
  `OBSERVABILITY_BACKEND_URL`, silently dropping Class-1 telemetry. That hid in
  `dev`/`test`, where the exporter is `debug`. The bug only ever bit services on
  non-`web` networks *exclusively*: `-web` is a projinfra-owned plain bridge, so
  anything on `[web, internal]` always had egress. Genuinely egress-less
  networks remain deferred per `networks.md § Egress` and
  `infrastructure.md § Deferred`; when they land they must be declared and
  opt-in, with an elastic half, rather than a side effect of a compose flag.

## [1.6.0] - 2026-07-30

"Service process types" (advance 004, mods 094-106) — decouples build artifact
from process type. A core service in `infra.yml` is no longer one service; it is
a **codebase** declaring N *process types*, one image started N ways. The
`depends_on` relation splits in two: a readiness gate over backing services, and
a new interface relation `consumes` between core process types. Everything
downstream of the identity change — emitted names, hostnames, contract paths,
health paths, `OTEL_SERVICE_NAME`, envinfra tags — gains a process segment.
**This is a breaking format change:** `cicl_version: "2"` is required and `"1"`
is rejected rather than shimmed, and for exactly one release cycle after 1.6.0
prod has no rollback path (the v1→v2 boundary is refused at pre-flight, with a
fix-forward message). Downstream projects upgrade per
[`upgrades/upgrade_1.6.0.md`](./upgrades/upgrade_1.6.0.md) — a repin plus an
`infra.yml` restructure and a resource rename, not a rebuild.

### Added

- **`role: worker` as a bundled role** (mod 095) — a long-running,
  non-ingress process type on both foundations. Fixed gets the usual compose
  `healthcheck`; elastic gets an ECS **container-level** `healthCheck`, routed
  through a new `container_definition` emit destination — a *merge target, not a
  resource*, whose renderer returns `""` (registering it is what satisfies the
  dispatch loop and transfer-table rule 12 without emitting a second block, and
  the merge lands ahead of the compiler's own `dockerLabels` / `mountPoints` /
  `dependsOn` so compiler-derived keys win over table-supplied ones). No
  `default_port`: an implicit health port would silently oblige the app to bind
  it, and a missed binding would surface as an ECS kill loop rather than a
  compile error. That container healthCheck earns its keep twice — it probes the
  consume loop, and it is the only thing gating a worker's rolling deploy, since
  with no target group ECS would call a task healthy the instant it reached
  RUNNING and roll a broken deploy through every replica.
- **`consumes:` on a process type** (mod 098) — the interface half of what
  `depends_on` used to conflate. Targets are dotted and fully qualified
  (`api.worker`); a bare core name is **illegal, not shorthand**, because a
  codebase has no single boundary. Cycles are **legal** — `web ↔ worker` is the
  most common topology there is — where a `depends_on` cycle stays fatal (rule
  6), which is why no single field could have carried both rules. Rule 7 is now
  kind-aware (a backing ref must be matched by `depends_on`, a core ref by
  `consumes`) and one-directional by construction: ref ⇒ edge, never edge ⇒ ref,
  since `api.web` declares an edge to its worker for the contract and the health
  fan-out while holding no ref to it. `consumes` is CI/view-only — contracts, the
  health gates, rule 7 and `describe` read it, nothing is emitted from it, and a
  test pins that it *cannot* be.
- **Four-segment core magic refs** — `${core_services.<svc>.<proc>.<part>}`
  (mod 097). Backing refs stay three-segment, because a backing service has no
  process types and there is nothing to qualify. The pattern is now
  kind-prefixed and body-agnostic, so anything beginning `${core_services.` /
  `${backing_services.` is *claimed* whatever its shape and then arity-checked
  against its kind by one shared checker; self-references are rejected in both
  the resolver and the validator, with the reason (`provides.host` is the
  *internal* discovery name, so an absolute URL to oneself would not return what
  the author expects — use `localhost`).
- **A per-codebase `exec` service** (mod 099) — `{project}-{env}-{codebase}-exec`,
  `profiles: [exec]` so `up` never starts it and `run` implicitly enables it,
  carrying the codebase's image, **service-level `env:` only**, the sorted union
  of the codebase's non-`web` networks, and its `depends_on` rewritten to
  `condition: service_healthy`. Emitted in all four fixed envs — including for a
  scheduler-only codebase, which previously produced *zero* compose services in
  `test`. It is the container that *is* the codebase, and routing the fixed
  stage/prod playbook through it too is what makes *"`migrate.sh` may depend only
  on codebase-scoped env"* a rule with teeth rather than a convention.
- **`replicas` is finally read by an emitter** (mod 100). The field had been
  declared, range-checked, allow-listed, documented in `cicl.md` and `shape.md`,
  and carried onto the compiled model since mod 096 — and read by *nothing*;
  `hcl.py`'s `desired_count` was the literal `1`, so "two web, four workers", the
  advance's motivating capability, did not work even with nesting landed. Elastic
  now emits `desired_count`; fixed **unrolls into N distinct compose services**
  rather than using `deploy.replicas`, which cannot work — the OTel collector
  pairs by netns (`network_mode: service:<key>`) and Compose has no
  replica-to-replica pairing, and it refuses `deploy.replicas` alongside
  `container_name`. Each replica keeps a real `container_name` (`…-api-web-3`)
  and carries a **shared network alias** on every network it joins, so Docker DNS
  round-robins and `provides.host` still means "the process type"; traefik
  aggregates because its labels key on the *unqualified* name, giving one router
  and one service with N servers. One clamp rule in one place: `replicas` applies
  in `prod` only, and `dev`/`test`/`stage` compose output is byte-identical to a
  compile with no `replicas` declared. The unroll deliberately lives in the
  emitter, not the compiler — a replica is an emission detail, not a topology
  node, and unrolling the compiled model would have made `describe` render four
  worker nodes, the contract gate see four providers, and four exec services per
  codebase.
- **Two OTel resource attributes** — `docex.core_service` and
  `docex.process_type`, appended to the unchanged `service.namespace` /
  `service.version` / `deployment.environment.name` triple (mod 102). Both axes
  have to be queryable: against a fused `service.name` the only way to ask "every
  process type of `api`" or "every `worker` across codebases" is a prefix or
  suffix match on a string whose *both* segments may contain hyphens, so
  `api-web-v2` does not decompose. Values are the raw authoring names, matching
  the split the elastic tag block already uses. `docex.process_type`'s presence
  is itself load-bearing: it appears if and only if the emitter is a declared
  process type, so a per-codebase artifact is queryable as "the `api` codebase,
  no process type".
- **The health model is specified end to end** (mod 094, `contracts.md § Health
  Checks`) — every long-running process type serves `GET /health` on its declared
  port, with liveness sourced from the entrypoint's own loop via a monotonic
  tick, doctrine-fixed at a **10 s tick and a 30 s staleness threshold** (30 s is
  3× the tick, so a healthy loop misses two consecutive ticks before the handler
  calls it stale — enough slack for ordinary jitter and one slow iteration
  without flapping, while still failing a wedged loop inside the window an ECS or
  compose healthcheck acts on). Fan-out is one hop only, over `consumes`, at
  `/health/<service>/<process>`, which is what keeps the legal `web ↔ worker`
  cycle from recursing; `scheduler` process types are exempt. Because AsyncAPI has
  no natural place for an HTTP path, a `worker`'s health is **declared by
  fields** — `port` + `health_check_path` *are* the declaration, and `docex
  check` now asserts them on every `consumes` target.
- **Validation rules 21-28**, appended rather than interleaved so no existing
  rule number moves under the code and tests that cite them: `cicl_version` is
  `"2"` (21); every core service declares a non-empty `processes:` and nothing
  outside `{processes, secrets, config, env}` at the service level (22); every
  process type declares a `command` (23); `depends_on` names only backing
  services (24); `consumes` names only core process types, fully qualified, never
  itself and never a `scheduler` (25); no `replicas` on a `scheduler` (26); no
  `web` in a `worker`'s or `scheduler`'s `networks` (27); `health_check_path`
  obliges a `port` (28).
- **`describe` renders both relations** (mod 104) — node ids in the doctrine's
  dotted reference form (`api.web`, bare for backing services) with the emitted
  hyphenated name alongside, and two labeled edge groups under distinct glyphs:
  `->` for readiness, `..>` for interface, mermaid's solid/dashed rendered in
  ASCII. The distinction is carried twice, glyph and heading, because the output
  is as often grepped as read. `--format llm` gains `"kind": "consumes"`, a
  per-node `consumes` list, and `core_service` / `process` beside `short`; the
  duplicated edge-derivation loop is deleted in favour of one shared derivation
  with two renderings.
- **`GitClient.show(cwd, ref, path)`** on the client protocol (mod 105), so a
  pre-flight check can read a blob out of a tag through the injected client and
  be unit-tested through the fake; `check.py`'s `_git_show` now delegates to it,
  collapsing two read-a-blob mechanisms into one and dropping a private-access
  `noqa`. Plus `CURRENT_CICL_VERSION` in `cicl/model.py`, so the compiler's
  accepted generation and rollback's precondition are one fact rather than two
  literals.
- **Doctrine: `entrypoints/`** (mod 094) — a folder beside `root.py`, one
  entrypoint per process type, calling `build()` and never a concrete adapter
  constructor; never `root_web.py` / `root_worker.py`; the runtime host is not an
  adapter; inverted-control registration (Celery-style decorators) belongs in the
  entrypoint, not the adapter; and an entrypoint that owns a loop must expose that
  loop's liveness. Entrypoints are too thin to test — one that needs its own test
  is doing too much. Also a `Queue` row in the controller-mechanism table
  (`ContBrokerQueue`), resolving a live cross-stratum contradiction: the driven
  table already carried `Queue` for the producer side, while a queue consumer is a
  driving adapter on the same driving port as the HTTP controller.

### Changed

- **A core service is a codebase declaring N process types** (mod 096).
  `processes:` is **required and non-empty** on every core service; there is no
  flat form and no single-process shorthand. `role`, `command`, `networks`,
  `resources`, `port`, `depends_on` and `replicas` move onto the process type;
  the service level accepts only `{processes, secrets, config, env}` and anything
  else is a hard error with a message naming the fix. One principle generates the
  whole split — *a field belongs to the codebase iff its value is determined by
  the source code, and to the process type iff it is determined by the
  invocation* — so role-specific fields follow `role` and are process-scoped by
  derivation, and `env:` is the one field valid at both levels (process merging
  over service). `command` is required even on a lone `web`: with several process
  types sharing one image, at most one could inherit the Dockerfile `CMD`, and
  "which one" is an ambiguity worth deleting rather than answering. Each process
  type compiles to its own container / ECS service named `<service>-<process>`,
  and the image stays keyed on the **codebase** — one build, one tag, N ways to
  start it. **Breaking:** every emitted core identity gains a segment — compose
  keys and `container_name` (`${project}-${env}-${service}-${process}`), ECS
  service and task-definition family, Service Connect names, CloudWatch log
  groups, target groups, traefik router keys, and the paired sidecar
  (`<svc>-<proc>-otelcol`). Existing target groups whose names previously fit the
  `alb` policy's 32-char ceiling are hash-truncated and therefore
  destroyed/recreated on first apply; envinfra tag *values* churn.
- **Hostnames gain the process segment** — `<service>-<process>.<env>.<project>.<apex_domain>`,
  e.g. `api-web.dev.myproject.example.com`. The two segments share **one** label,
  hyphen-joined, for three independent reasons: TLS wildcards cover exactly one
  label; the domain parse is positional; and the bare-env and bare-project routes
  are defined relative to that four-part form. Nothing ever reverse-parses the
  label back into `(service, process)` — it is a rendered output, never an input
  to be decomposed — which is what dissolves the apparent ambiguity of `api-web`
  and why rule 5 instead requires *rendered* identities to be unique.
  **Breaking:** per-host DNS records and anything hard-coding a service hostname
  must be updated. `domain_default_service` becomes **`domain_default_process`**
  and takes a dotted ref (`api.web`).
- **The `http_host` naming policy gains `max_len: 63, overflow: error` and is
  actually wired** (mod 096). DNS labels hard-cap at 63 octets; until now the
  service label was built by a bare `_dns_label()` that consulted no policy, so
  the cap would have been decoration — and a cap nothing applies is worse than no
  cap, because it reads as enforcement. Byte-identical to the old output for
  every input of 63 characters or fewer; the only new behavior is a compile error
  above it. Relatedly, the pre-existing `iam` policy (64 chars, error on
  overflow) can now **hard-fail a scheduler compile**, since its role name is
  `{project}_{env}_{service}_{process}_scheduler` — a clean failure at the
  earliest layer, which is the doctrine's stated preference, but new.
- **Contracts are per process type.** The path is
  `infra/contracts/${service}.${process}.${format}.yml` unconditionally
  (**Breaking:** existing contracts must be renamed), because format alone
  cannot disambiguate one codebase running two genuine HTTP boundaries. The
  provider set becomes (`consumes` targets) ∪ (`web`-network process types) minus
  schedulers — both arms load-bearing, since driving it off `consumes` alone
  would silently switch the health gate off for a public boundary nothing
  internal consumes. The format now derives from the **provider's `role`**
  (`web` → openapi, `worker` → asyncapi) rather than from graph shape, and an
  unrecognized role falls back to openapi *and says so in the gate's detail
  line*, because a provider quietly treated as openapi is a debugging trap. Self
  `GET /health` is required of every OpenAPI provider, widened from web-network
  only — an internal-only `web`-role process reached via `consumes` genuinely
  should be probeable one hop away.
- **`depends_on` is a readiness gate over backing services only** (mod 096, rule
  24); a core→core edge is a hard error pointing at `consumes:`. **Breaking.**
  The doctrine now also writes the corollary in explicitly: *startup ordering is
  not a substitute for connection resilience.* Cycle detection consequently runs
  over the backing-service graph alone, and `consumes` cycles are legal *by
  construction* there.
- **`migrate`, `test` and `build` run `compose run --rm <codebase>-exec` instead
  of `compose exec` into a running app container** (mod 099). Process expansion
  had left all three picking one process type's container through a heuristic
  duplicated three times and wrong at least once; they now stop picking. Three
  operator-visible consequences: a one-off **starts the codebase's backing
  services** and gates on `service_healthy`, so `docex migrate dev` against a
  torn-down stack brings the database up instead of failing; there is ~1 s of
  container-start latency instead of an exec into a warm container; and
  **`docex build` no longer requires the target codebase's container to be
  running**. **Breaking:** a *process-level* `env:` key is no longer visible to
  `migrate.sh`, `test.sh` or `build.sh` — the intended break, and the point of
  the env-scoping rule.
- **The elastic migrate task definition is a per-codebase pass** — one block per
  schema-owning codebase, family `{project}-{env}-{codebase}-migrate`, address
  unchanged so `release`'s targeted pre-migrate apply stays valid. Its env is
  service-level only, and its resources are the **per-dimension max** across the
  codebase's process types. Max rather than "pick one" because a pick is not
  stable under edits that have nothing to do with migration — renaming a process
  type resized the migration, and adding a modest sibling silently shrank it.
  Max is order-independent and rename-stable, never under-provisions (so the
  `scheduler` carve-out disappears), and is a no-op for a single-process
  codebase, whose emitted HCL is byte-identical.
- **`OTEL_SERVICE_NAME` is the two-segment compiled identity** (`api-web`), and
  a **per-codebase artifact reports the codebase** — the exec container and the
  migrate task definition carry `service.name=api` with `docex.process_type`
  absent. Envinfra tags gain a `process` key and `Name` becomes
  `${project}_${env}_${service}_${process}`; for a backing service the key is
  omitted entirely rather than emitted empty, so backing tag blocks stay
  byte-identical to their pre-expansion form. The dev telemetry-watching command
  is now `docker compose logs -f <svc>-<proc>-otelcol`.
- **A `scheduler` is a process type whose trigger is cron** (mod 103), not its
  own species of service. Its job image is the **codebase's** image, shared with
  every sibling process type; the Ofelia container key and the INI job name are
  both two-segment. In `dev` the codebase tag is the Dockerfile **`dev`** stage
  for every process type including a cron job — any other answer means two
  consumers of one tag disagree about what is inside it. `up dev` therefore
  builds only *scheduler-only* codebases' tags (a codebase with a long-running
  process type is built by `compose up --build`), and no `prod`-stage build
  happens during `up dev` any more. Worth knowing: a dev job runs the artifact
  the `dev` stage baked, refreshed on `up dev`, not the host's live `dist/`.
- **`test`-env one-offs build first.** `compose run` builds only when the image
  is *absent* and silently reuses a stale one when the context has changed, so
  `docex test`, `up test` and `migrate test` now pass `--build` — in `test` the
  image *is* the artifact under test. Deliberately **not** in `dev`, where source
  arrives by bind mount and the `dev` stage exists precisely so `build.sh` can be
  re-invoked without an image rebuild.
- **A `${…}` containing a hyphen is now a compile error.** The compile-time
  variable pattern gains `-` to its charset (mod 097), so a mistyped
  `${env-name}` raises the honest undefined-variable error instead of surviving
  into the emitted compose/HCL as literal text. **Breaking, with no workaround:**
  the substitution grammar has exactly `${var}`, `$[var]` and `@expr` and **no
  escape form** — the `$$` doubling in the tree is applied by emitters after
  substitution to escape Compose's and HCL's own interpolators, and never reaches
  the compile-time resolver. A genuinely literal `${a-b}` has nowhere to go;
  adding an escape would be a grammar change and therefore a doctrine change.
- **`${name}` in a transfer table** is the two-segment compiled identity for a
  core process type (still the simple name for a backing service), and
  `describe --format dag` renders a *directed* graph which may legally contain
  cycles — the flag name is unchanged, since a format name is a label rather than
  a claim, but `docex.md`'s "directed acyclic graph" was the sentence asserting
  the property and it is corrected.
- **Fixed no longer publishes host ports for non-`web` core process types.** The
  health port is probed from inside the netns by the container healthcheck and
  from a sibling over the internal network, and elastic never published, so
  removing it *improves* dev/prod parity — and it closes a day-one `dev`
  collision between the workers of two different codebases.
- **Doctrine: "core services never share code" is re-scoped to core service
  *sources*.** Sibling process types are one codebase, so nothing is shared and
  the rule's intent survives intact; when only the *invocation* differs, the
  answer is a process type, not a second core service. Composition-root
  responsibility (4), *"registering every HTTP controller's router with the
  application"* — the one place a runtime host got baked into `root.py` — is
  deleted and moves to the entrypoint; the root instantiates every driving
  adapter for every mechanism regardless of which process type is running, which
  is free because controller construction captures a port reference and performs
  no I/O.

### Removed

- **The CICL v1 flat form.** `cicl_version: "1"` is rejected with a message
  naming the upgrade guide, not shimmed: a compatibility parser accepting both
  forms would reintroduce the pre-`processes:` shape as a permanent second code
  path, to serve a migration every project performs exactly once. The
  `domain_default_service` field and core→core `depends_on` go with it.
- **The codebase-to-container bridges** planted by mod 096 for this moment
  (mod 099): `primary_process()`, `compose_service_key()`, and both copies of the
  suffix heuristic in `build.py`. Net line count is negative. Also
  `_build_one`'s per-service "is this container running" gate and its crash-loop
  diagnostic — retired deliberately, not merely mechanically: it refused to run
  `docex build` when the dev container was `restarting`/`unhealthy`, and the most
  common cause of that is an empty `dist/`, which is exactly what `docex build`
  fills. The guard blocked the one command that resolves the state it detected.
- **Mod 074's self-contained scheduler job image** and `docex test`'s scheduler
  carve-out (mod 103) — `_run_scheduler_tests` and `scheduler_services()` are
  gone, and a scheduler-only codebase takes the identical
  `compose run --rm <codebase>-exec ./test.sh` path as every other codebase,
  gaining that codebase's `depends_on` readiness gate and networks where the bare
  one-off had neither. `specifics/scheduler.md`'s `test.sh` caveat — whose entire
  justification was "there is no `test`-stack container to `exec` into" — is
  deleted with it.
- `validate`'s private `consumes` parser, promoted onto the model as
  `ProcessType.consumes_refs()` so the dots-for-reference rule lives in exactly
  one place with three readers (mod 101), and the zero-byte
  `tests/unit/test_roles.py`, which read as "roles are tested" to anyone grepping
  (mod 095).

### Fixed

- **The `consumes` fan-out died on a first-time elastic release** (mod 109, found
  by the pre-cut smoke walk at `PRE_CUT_CHECKLIST § D.11`). ECS Service Connect
  fixes a client task's set of resolvable endpoint names **at task start** — AWS:
  *"New endpoints that are added to the namespace after the most recent deployment
  won't be added to the task configuration"* — and `docex` emitted the consumer's
  and the consumed's `aws_ecs_service` with no ordering, so tofu created them
  concurrently. On the walk `api-web` started 15 s before its worker and returned
  `503 … Name or service not known` for the rest of that task's life, with both
  workers HEALTHY and 2 instances registered. Forcing a new deployment of
  `api-web` alone fixed it instantly.

  This is a hole in the model, not just a bug: `cicl.md § Depends-On
  Relationships` prescribes *"reconnect, back off, and fail requests cleanly"*,
  which presumes **transient** absence. A name that never resolves for a task's
  whole life is not something backoff converges on. The doctrine treated elastic
  dependency failure as a *reachability* problem; Service Connect adds a
  *resolvability* one.

  Fixed by a **post-apply consumer reconcile**: diff the env namespace's endpoint
  set against a snapshot taken before any apply, and force a new deployment of
  every core process type declaring a `consumes` target whose endpoint is new in
  that diff, then wait bounded for steady state. Notably this is *not* the
  deploy-time ordering emulation the same doctrine section rejects — an endpoint
  registration is **durable state owned by the service, not by task liveness**, so
  holding once is permanently sufficient; every later task replacement starts into
  a namespace that already contains the name. Ordering could not have worked
  regardless, since a `consumes` cycle (`web ↔ worker`) has no valid creation
  order. The diff is per-target rather than per-namespace, and a release that adds
  no process type registers nothing, so ordinary image-tag releases pay one extra
  `list_services` call and nothing more. `consumes` gains a fourth job and stays
  emit-free. Verified on a rebuilt-from-nothing elastic prod release: the fan-out
  answered 200 on the **first** probe.

- **The elastic HCL emitter never emitted a process type's `command`** (mod 108,
  found by the pre-cut smoke walk at `PRE_CUT_CHECKLIST § D.9`). Every
  `aws_ecs_task_definition` shipped `command = null`, so every ECS task ran
  whatever the image's Dockerfile `CMD` happened to be — and since one image
  serves N process types, at most one could be correct. This inverted
  [`infrastructure.md § Core Service Containers`](./doctrine/infrastructure/infrastructure.md#codebase-containers),
  which says the `CMD` "is not used" and each process type's `command` is "what
  the compiler emits": on elastic the `CMD` was the *only* thing used, making
  1.6.0's headline feature inert on that foundation.

  The data was present and correct all along — `cicl/compile.py` sets
  `body["command"]` on both branches — but `render_task_definition` builds its
  container definition key-by-key and never read it, where
  `emit/compose.py::_service_block` gets the body by whole-body pass-through and
  so had always been right. Three things hid it: the seed's Dockerfile `CMD`s
  happen to match each codebase's *first* process type, so only a **second**
  process type is visibly wrong (and before CICL v2 there were none); no HCL test
  asserted `command` in rendered output; and the integration tests are dev/fixed
  only. Observed live as `api-worker` running `entrypoints/web.py`, failing its
  `:8081/health` probe, going `UNHEALTHY`, and being dropped from Service
  Connect — surfacing as a `503` on the `/health/api/worker` fan-out. Fixed by
  reading `command` off the compiled body (normalizing `str` via `shlex.split`,
  as the fixed side's scheduler wrapper does) and merging it **after**
  `target_extras`, so no transfer table can override which process type a
  container is. Guarded by four new tests, all against a **two**-process
  codebase, since a single-process one cannot detect the defect.

- **Process expansion's four silent-failure sites, found by audit rather than by
  test** (mod 096). Each would have shipped as a success-reporting failure:
  `emit/ansible.py` compared a backing service's `schema_owned_by` — an
  *authoring* key — against the compiled service name, so under the rename the
  comparison never matches, the schema-owner set goes empty, and the **fixed
  stage/prod playbook emits no migrate tasks at all while reporting success**;
  `_image_ref` fed the compiled identity would have produced `<proj>/api-web:<v>`
  where `containerize` pushed `<proj>/api:<v>`, so build and push succeed and
  **release fails at pull time**; the migrate task definition, emitted inside the
  per-process pass, would have produced N `…-migrate` families matching neither
  `release`'s targeted pre-migrate apply nor `migrate`'s independent
  reconstruction, so the apply silently no-ops and **the migration runs against
  the previous release's task definition**; and `migrate.py`'s `tables.role()`
  lookup was a hard `AttributeError` on every elastic migrate, hence every
  elastic release.
- **`docex check`'s curl gate was a no-op** (mod 096). `_gate_healthcheck_tooling`
  read `health_check_path` off the core-service model with a `getattr` default, so
  once the field became process-scoped it was permanently `None` and the gate
  **passed while checking nothing** — defeating mod 051's guard entirely. Same
  class as `_common.py::scheduler_services`, whose `getattr(svc, "role", …)`
  silently returned `[]` for *every* project, sending `docex up` and `docex test`
  down the wrong branch with no error.
- **`_infer_contract_format` could never return `asyncapi`** (mod 101). Its
  asyncapi branch was provably unreachable: the sole call site passes a **core**
  service name and the function then looked it up in `backing_services`, which by
  model rule can never hold that name. Every provider got `openapi`. That
  unreachability is *why* the `depends_on` flaw below went unnoticed for so long
  — no code path could produce an AsyncAPI provider for a test to exercise. The
  heuristic is deleted rather than repaired; the role is the honest source.
- **The health-endpoint gate reasoned at codebase granularity** (mod 101). It
  parsed a contract filename with `split(".", 1)[0]`, which yields `api` from
  `api.web.openapi.yml` purely by the accident that the codebase is the first
  segment, and then discarded the process entirely — so on a two-web-process
  codebase it checked `api.web`'s contract against `api.admin`'s dependencies and
  never noticed. Replaced with a right-anchored parser requiring exactly three
  segments. The fan-out's `depends_on` arm is also dropped, having become
  unfireable when rule 24 restricted `depends_on` to backing services (which have
  no `<service>/<process>` form): a `depends_on`-keyed gate now requires
  *nothing* of a `web → worker` edge, which is the silent switch-off the doctrine
  names — requests keep returning 200 while work piles up behind a dead consumer.
- **A hyphenated four-segment magic ref was emitted into infrastructure config
  as literal text** (mod 097). `${core_services.my-api.web.host}` matched
  *neither* the magic-ref pattern (whose part group forbade `.`) nor the
  compile-time pattern (which forbade `-`), so it was written verbatim into the
  emitted `docker-compose.yml` / `.tf`: silent corruption that looks valid,
  applies cleanly, and carries a `${…}` string where a hostname belongs. A hyphen
  decided whether a ref was *seen at all*. Kind-prefixed generic capture removes
  that structurally — whether a string *is* a magic ref is now decided
  independently of whether it is well-formed.
- **`docex build`/`migrate`/`test` could resolve the wrong container** (mod 099).
  The codebase → container heuristic suffix-matched the emitted compose file, so
  a project with a codebase literally named `web` resolved to a *sibling*
  codebase's `…-api-web`, silently and with no error. `exec_service_key`
  construct-then-verifies instead: it derives the key from the same helper the
  compiler emits, then asserts its presence and raises a "run `docex compile`"
  error if absent — no suffix match to mis-resolve, no silent fallback to the
  bare name.
- **Three pre-existing rendered-identity collisions, unguarded on both
  foundations** (mods 099, 100). A process type named `otelcol` renders
  byte-identically to a sibling's collector sidecar, one named `scheduler` to a
  sibling's Ofelia trigger, and one named `migrate` to the migration task
  definition's own HCL address — one compose key or resource address, one
  silently clobbering the other. Rule 5's uniqueness domain now covers every
  suffix the compiler appends (`-otelcol`, `-scheduler`, `-exec`, `-migrate`, and
  the prod-fixed replica index), keyed on **collision rather than a forbidden-name
  list**, so it covers future suffixes without a further edit and does not forbid
  a name that is harmless where nothing collides with it.
- **`docex up`'s unhealthy-stack diagnostic was blind to backing services**
  (mod 099). It derived keys per *core* codebase, so an unhealthy postgres — the
  single most likely reason `up` fails — was invisible to it. It now reports every
  entry in the compose status map in a diagnosable state.
- **`docex build dev` was broken for any project with a scheduler-only codebase**
  (mod 103) — a regression introduced within this advance by mod 099 and caught by
  empirical verification rather than by any test. Mod 074's self-contained job
  image built the Dockerfile **`prod`** stage under the codebase's dev-local tag,
  while the new exec service builds the **`dev`** stage against the *same* tag;
  because `compose run` builds only when the image is *absent*, the exec run
  reused the prod-stage image, which carries no `build.sh` and no `test.sh`. No
  unit test could have caught it: no integration test covers a scheduler at all.
- **`OTEL_SERVICE_NAME` leaked a process segment onto per-codebase artifacts**
  (mod 102). It was stamped in the shared env tail *before* the per-process /
  per-codebase split, so the migrate task definition and the exec container both
  reported whichever process type sorted lowest — for a codebase with `web`,
  `worker` and `nightly_cleanup`, a **migration reporting
  `OTEL_SERVICE_NAME=api-nightly_cleanup`**: the name of a cron job. It was also
  unstable under rename, and it falsified the comment the exec service's
  correctness leans on (that the codebase-scoped env surface is identical across
  process types by construction). The identity now de-qualifies to the codebase
  and the process attribute is omitted.
- **`health_check_path` without a `port` emitted a malformed probe** (mod 095,
  rule 28). `${port}` resolves to the empty string when a service omits `port:`,
  so the probe became `http://localhost:/health` on both foundations, surfacing as
  a container that never becomes healthy rather than as a compile error. Nothing
  caught it: the existing rule requires a `port` only for *web-network* services,
  and a worker is not on `web`.
- **Rollback discovered the CICL boundary mid-rollback** (mod 105). `cicl.md
  § CICL Version` had promised since mod 094 that rollback across the v1→v2
  boundary "aborts at pre-flight, before anything is applied, with a fix-forward
  message"; the code aborted inside `run_compile`, i.e. after a worktree had been
  created and after the registry probe had run — during the outage, at the point
  of maximum cost per second. The check now sits in the cheap pre-flight band,
  ordered ahead of the image probe by decisiveness as well as cost (a missing
  image can be rebuilt from the tag; a boundary crossing cannot be resolved by
  anything but fixing forward, so the image list would be noise). It reads the
  target's `cicl_version` with a single `git show` and a one-key YAML read rather
  than full model validation, because a pre-v2 `infra.yml` fails validation for
  several unrelated reasons at once and pydantic's ordering would decide what the
  operator sees. The message states that nothing has been touched, names the
  concrete next commands, and bounds the window.
- **The conditional stratum described pre-advance behavior in twelve files**
  (mod 106), and eight of the inherited predictions about it were themselves
  wrong. `shape.md` claimed the reverse proxy load-balances *worker* replicas and
  illustrated it with the one case the sentence does not describe: the proxy
  balances `web` replicas, while **internal** replicas are balanced by Docker DNS
  round-robin on fixed and Service Connect on elastic, with no proxy in the path.
  The sidecar count is a **sum** over a codebase's non-`scheduler` process types
  of each one's effective replica count, not the design record's `N × R` product —
  written as a product it is wrong for the very configuration it exists to
  explain (`web` at `replicas: 3` beside one `worker` is 4 collectors, not 6).
  `telemetry_infra.md` described sidecar pairing as "sharing a network" when it is
  by netns; `migrations.md` gave the absolute `/service/migrate.sh` for dev/test
  where the code uses the relative form; and `domain_default_service` survived in
  five files including four `projinfra` specifics the worklist omitted — the worst
  class of staleness in the sweep, since it is not a renamed concept but **a field
  the compiler now rejects**, so those documents instructed a reader to write
  something that hard-errors with nothing signalling it until compile fails.

## [1.5.0] - 2026-07-11

"Envmageddon" (campaign 003, mods 076-086) — splits the single per-environment
`<env>.env` into three provenance-based categories, re-merged at deploy time by
an aggregation step, plus value-blind tooling to manage them. Application code
and the container-facing env are unchanged; only the source layout and
release-time materialization move. Downstream projects upgrade per
[`upgrades/upgrade_1.5.0.md`](./upgrades/upgrade_1.5.0.md) — an `incremental`
repin + file-reorg (not a rebuild), whose one load-bearing step is preserving
the live engine credential so a mint can't lock out a running database.

### Added

- **The three configurable-value categories** (`config_and_secrets.md`): **TTE**
  (transfer-table `kind: minted` engine vars, minted by `docex`, stored in
  `infra/tte/`), **secret** (core `secrets:` + backing `kind: secret` +
  doctrine-injected, in `infra/secrets/`), **config** (new core `config:` block,
  non-secret per-env values, in `infra/config/`). Categories are disjoint by
  source key — enforced at compile (rule 20).
- **Engine `env:` `kind` schema** (mod 076) — each engine env var declares
  `kind: fixed | minted | secret` (default secret); a new top-level
  `generation_policies:` section (`{length, alphabet}`) + a CSPRNG generator
  (`cicl/generate.py`, `url_safe`/`alnum`). Postgres now mints only
  `POSTGRES_PASSWORD`; `POSTGRES_USER` is a `fixed` literal (`appuser`).
- **`config:` block on core services** (mod 078) + `cicl/categories.py`, the
  pure source-key classifier (`classify_source_keys`) + `secret_manifest` /
  `config_manifest` / `minted_policies` used across validation, aggregation, and
  tooling.
- **Aggregation** (`orchestrate/aggregate.py`, mods 080-082) — `aggregate()`
  merges the categories just before bring-up: dev/test → `.docex/agg/<env>.env`
  fed to compose; fixed stage/prod → host `.env` (aggregate) + host `tte.env`
  (authoritative store, read over SSH) rendered by ansible; elastic stage/prod →
  the SSM prefix itself, TTE minted put-if-absent (`SecureString`), secrets
  overwrite (`SecureString`), config overwrite (`String`). `ensure_tte`
  generates a minted value only when its authoritative store lacks it.
- **Required-secret guard on release** (mod 091, `config_and_secrets.md §
  Required-Secret Guard`) — a stage/prod `docex release` aborts before any side
  effect if a required secret (secret manifest: core `secrets:` + backing
  `kind: secret` + doctrine-injected) is unset in `infra/secrets/<env>.env`,
  naming each unset key + its `docex secrets set` remediation. Secrets-only (TTE
  is minted, config is non-secret) and stage/prod-only (rollback bypasses it).
  `pipeline/release.py:_require_secrets_present`.
- **`docex secrets`** (mod 083) — `scaffold` / `status` / `set` / `copy`,
  value-blind: `set` takes its value only from a no-echo tty prompt or
  `--from-file`; `status` is redacted `SET`/`UNSET`; there is no `get`; `copy`
  refuses TTE keys and warns cross-side.
- **`docex config`** (mod 084) — `scaffold` / `status` / `set` / `get` / `copy`,
  permissions inverted (values visible, positional `set` OK, `get` prints).
- **`envfile.py`** — the standard flat `KEY=value` read/write (first-`=` split,
  raw-literal values) shared by every store and the aggregate.

### Changed

- **Compiler inlines `kind: fixed` `$[VAR]` refs** to their literal at compile
  (mod 077) — `POSTGRES_USER`→`appuser` everywhere; the elastic SSM data-source
  / ECS `secrets[]` machinery now fires only for the surviving minted/secret
  refs, with no emitter change.
- **Elastic release SSM push** replaced `_push_secrets` with the three-category
  `aggregate_elastic` (mod 082); the **fixed** release playbook renders `.env`
  from the aggregate and a host `tte.env` from the authoritative store (mod 081).
- **The shim allocates `-t -i`** only on an interactive terminal (mod 083), for
  `docex secrets set`'s no-echo prompt — additive + backward-compatible.
- **Validation** (mod 079) — rule 16 broadened to a three-way env/secrets/config
  per-service overlap check; rule 20 added for project-wide cross-category
  disjointness; doctrine-injected keys reserved in every category.

### Removed

- **`infra/secrets/example.env`** (mod 092) — the committed, keys-only secrets
  manifest `docex compile` used to emit is gone. It was a derived cache checked
  into git and asymmetric with config (which never had one). The required-secret
  key set is fully derivable on demand from committed sources (`infra.yml` +
  transfer tables + doctrine-injected keys) via `secret_manifest`, so `docex
  secrets scaffold`/`status` obsolete it. `compile` now writes nothing under
  `infra/secrets/`; `emit/secrets.py` keeps only the shared `render_manifest_env`
  used by scaffold.

### Fixed

- **Fixed projinfra single-host convergence** (mod 087) — the project-tier
  Compose `--project-name` was per-side (`<project>-projinfra-<side>`), so on a
  single-machine fixed host `docex projinfra up production` after `up
  development` collided on the shared traefik `container_name` instead of being
  the idempotent no-op the doctrine requires (`projinfra.md` §35/§96). The name
  is now side-independent (`<project>-projinfra`); split-machine fixed is
  unaffected. Pre-existing since mod 053; surfaced by the 1.5.0 pre-cut fixed
  smoke walk.
- **`docex test` runs a scheduler service's `test.sh`** (mod 088) — a
  `scheduler`-role core service has no exec-able container in the `test` stack
  (the compiler emits no Ofelia container for `test`), so `docex test` now
  builds its `test`-stage image and runs `test.sh` as a one-off container
  instead of `compose exec` (which failed with "service not running"). Doctrine:
  a clarifying sentence in `scheduler.md`. Pre-existing since mod 055; surfaced
  by the 1.5.0 pre-cut fixed smoke walk.
- **Fixed-foundation TTE store is read via `sudo`** (mod 089) — on fixed
  stage/prod, `ensure_tte_fixed` SSH-read the host-authoritative `tte.env` (which
  the playbook renders `root:root 0600`) as the unprivileged `deploy` user, so
  the read hit "Permission denied", was masked into an empty result, and made
  docex **re-mint the engine credential on every release**, locking the live
  database out of its own password on the second release. The read now uses
  `sudo cat` (deploy has passwordless sudo per doctrine). Elastic (SSM) and
  dev/test (local file) were unaffected. Pre-existing in the envmageddon
  campaign; surfaced by the 1.5.0 pre-cut fixed smoke walk.
- **Fixed release Compose stacks are project-scoped** (mod 090) — the release
  playbook's compose invocations (pull, bring-up, migrate) derived the unscoped
  `<env>` project name from the host deploy-dir basename, so two fixed projects
  on one host would collide. All three now pass an explicit
  `<dns_label>-<env>` (matching docex's `env_compose_project`, mod 053).
  Existing fixed deployments need a one-time old-stack teardown on the first
  1.5.0 release — see [`upgrades/upgrade_1.5.0.md`](./upgrades/upgrade_1.5.0.md).
  Pre-existing; surfaced by the 1.5.0 pre-cut fixed smoke walk.
- **`docex rollback --dry-run` on fixed no longer aborts on an undefined
  extra-var** (mod 093) — the release playbook's "Render TTE store" / "Render
  .env" tasks templated `tte_store_file` / `agg_env_file` unconditionally, but a
  dry-run runs `ansible --check` with no extra-vars (aggregation is skipped to
  stay side-effect-free), so ansible failed resolving the undefined variable.
  Both tasks are now gated `when: <var> is defined` — the real release still
  renders them; dry-run skips them and previews the compose diff against the
  host's existing files. Envmageddon regression; surfaced by the 1.5.0 pre-cut
  fixed smoke walk.

## [1.4.4] - 2026-07-05

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
[`plans/modifications/048_elastic_walk_polish/`](docex/plans/modifications/048_elastic_walk_polish/).
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
  bug 7).** The doctrine ([`elastic_route53_zone.md`](./doctrine/infrastructure/specifics/projinfra/elastic_route53_zone.md))
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
[`docex/plans/modifications/047_smoke_walk_polish/`](docex/plans/modifications/047_smoke_walk_polish/)
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
  [`contracts.md § Health Checks`](./doctrine/infrastructure/contracts.md#health-checks)
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
  [`projinfra/ec2_traefik.md`](./doctrine/infrastructure/specifics/projinfra/ec2_traefik.md).
- **`templates/ec2_traefik_user_data.sh.j2`** (~280 lines, mod 044):
  doctrine-managed user_data covering EBS ACME volume tag-attach,
  traefik install + static config (DNS-01 LE via Route53), systemd
  timer for SSM-driven dynamic-config sync, optional PIP-only boot
  DNS-update unit, CloudWatch Logs agent.
- **Polymorphic `reverse_proxy_security_group_id` project-tier output
  (mod 044).** Resolves to the ALB SG or the traefik SG depending on
  variant; env-tier consumers stay variant-agnostic.
- **New commands `preinfra`, `projinfra`, `envinfra` (mod 034).** Per
  [`docex.md`](./doctrine/infrastructure/docex.md) — `preinfra <side>`
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
  [`projinfra/fixed_reverse_proxy.md`](./doctrine/infrastructure/specifics/projinfra/fixed_reverse_proxy.md).
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
  [`docex.md`](./doctrine/infrastructure/docex.md). `--help`
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
  [`cicl.md § Simplifications`](./doctrine/infrastructure/cicl.md#simplifications),
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
the doctrine's [`cicd.md § Rollback`](./doctrine/infrastructure/cicd.md#rollback)
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
  [`cicd.md § Rollback`](./doctrine/infrastructure/cicd.md#rollback).
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
  [`shape.md`](./doctrine/infrastructure/shape.md) and
  [`elastic_bootstrap.md`](./doctrine/infrastructure/specifics/projinfra/elastic_route53_zone.md):
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
