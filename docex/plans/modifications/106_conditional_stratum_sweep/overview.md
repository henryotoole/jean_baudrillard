# Mod 106 — Conditional-stratum doctrine sweep

**Advance:** 004 — service process types. Doctrine prose only; no code, no
tables, no tests. Mod 107 is the remaining closeout (smoke projects, upgrade
guide, changelog, version artifacts).

## Goal

Make the conditional stratum true again.

Mods 094–105 each deliberately deferred their doctrine consequences here, with
two exceptions: `cicl.md` and `contracts.md` have no downstream owner, so six
mods edited them in flight. Those two are **current and authoritative** and are
this mod's rule of record. Everything else in the conditional stratum has been
reading stale for up to twelve mods — by plan, not by drift.

The deliverable is a conditional stratum in which no sentence describes
pre-advance behavior, and zero links dangle.

## Method: the code is truth

The Mod 106 worklist arrived as accumulated predictions — what each mod
*expected* it would make stale. Every one was checked against the committed code
at `8e44e23` before any prose was written. That found **eight inherited claims
that are wrong or imprecise**, and **five files the worklist omits entirely**.
Those are recorded in the next two sections, because writing prose to match an
inaccurate note is the specific failure this method exists to prevent.

Anchors below are `src/docex/...` at `8e44e23`.

### Inherited claims that are wrong

**1. The health fan-out is `consumes` alone — not the union of `consumes` and
`depends_on`.** The worklist and the implementation plan's Mod 101 bullet both
say the gate asserts against "the union of `consumes` and `depends_on`". The code
reads `consumes` only: `check.py:499` iterates `sorted(proc.consumes_refs())`,
and `depends_on` is never read in `check.py` for this purpose. This is not a code
defect — it is *correct*, and `contracts.md § Fan-out` already explains why in a
parenthetical: rule 24 restricted `depends_on` to backing services, which have no
`<service>/<process>` form, so the union's second arm cannot contribute a target.
`contracts.md` even says it is stated as `consumes` alone "so nobody restores an
arm that cannot fire" — which is precisely what writing "union" into `cicd.md`
would have done. **`cicd.md` gets `consumes`.**

**2. The sidecar arithmetic is a sum, not a product — and this is an error in the
design record, not just in the worklist.** `service_processes_refactor.md` and the
Mod 106 worklist both frame it as "**N × R**". A product is only right when every
process type declares the same `replicas`, and **nothing enforces that**:
`replicas` is per-process-type (`model.py:142`), and `scheduler` process types get
no sidecar at all (`compose.py:648-649`). So the true count on fixed is

> the sum, over the codebase's **non-`scheduler`** process types, of each one's
> *effective* replica count

which collapses to one-per-process-type outside `prod`. Written as a product it
would be wrong for the very configuration the arithmetic exists to explain: `web`
with `replicas: 3` alongside a single `worker` is **4** collectors, not 6.
**Doctrine states the sum.** Recorded here so the design record is not later
treated as authoritative on this point — it assumes a uniform replica count
across a codebase's process types, and that assumption is unenforced and false.

**3. `aliases` and map-form `networks:` are unroll-only.** The worklist lists
`aliases` among § Per-container's universal invariants. It is not universal:
`_replica_networks` (`compose.py:290`) is the only alias-emitting site in the
tree and is called only when the effective count exceeds 1; the `N == 1` path
keeps compose's short-form list byte-for-byte (`compile.py:1145`). Stating
`aliases` as a per-container invariant would describe emission that does not
happen in `dev`, `test`, or fixed `stage`. **It is documented as conditional on
the unroll.**

**4. The `curl` gate is per codebase, not per process type.** `cicd.md` item 3.4
currently reads "Every `health_check_path`-declaring service's image carries
`curl`", which survives the advance better than the worklist implies. The gate
*reads* process types (`check.py:607-610`, `any(...)` over
`svc.processes.values()`) but the qualifying unit, the image build, and the probe
are per core service — "One image per codebase, so one qualifying entry per
codebase" (`check.py:604-606`). So the correction is narrow: the *declaration* is
now per process type while the *subject* stays the codebase's image. Re-keying
the sentence onto process types would have introduced an error.

**5. `shape.md`'s example is wholly v1, not merely mis-versioned.** The worklist
flags `:101`'s `cicl_version: "1"`. That understates it: the entire example
(`:100-129`) is the flat pre-`processes:` form — `domain_default_service`, a
service-level `role: web`/`port`/`networks`/`env`/`resources`, no `command`. Six
things in it are now hard compile errors. The three compiled-output descriptions
that follow (`:142`, `:156-166`, `:175`) all name a bare `api` service and
`api.dev.…` hostnames. **The whole example and its compiled walk-through are
converted**; see [§ shape.md](#shapemd) for why not just the version string.

**6. `fixed_master_network.md` has two stale sites, not one.** The worklist names
the Lua comment at `:105-108`. The same three-form enumeration appears in prose
at `:20` and is stale identically. Fixing only the comment would leave the file
self-inconsistent.

**7. The reserved-env-key rule is enforced against declared blocks, not the
effective merge.** The Mod 096 plan bullet says `_RESERVED_CORE_ENV_KEYS`
"evaluates against each process type's **effective** env". It does not:
`validate.py:1235-1245` collects the service-level `env:`/`secrets:`/`config:`
and each process-level `env:` as *separate* declared surfaces; `_effective_env`
exists but this rule does not call it. Outcome-equivalent (the union of declared
keys is the merge's key set) but not the same statement. No doctrine sentence
currently claims otherwise, so **this mod writes nothing new here** — it is
recorded so the word "effective" is not imported into the wrong rule. `cicl.md`
rule 16's own use of "effective" is correct for rule 16 and stays.

**8. Two smaller precision points.** The dev/test migrate invocation uses the
**relative** `./migrate.sh` (`migrate.py:116`, under the image's
`WORKDIR /service`) while the fixed stage/prod playbook uses absolute
`/service/migrate.sh` (`playbook.yml.j2:51-58`) — `migrations.md` currently shows
the absolute form for dev/test, so it is wrong in two ways at once, not one. And
a `scheduler` task definition carries **no** sidecar overhead in Fargate tiering
(`compile.py:851-857` passes `has_sidecar` into the `is_core` parameter), which
`telemetry_infra.md § Task-Level Resource Allocation` does not currently allow
for.

### Files the worklist omits

Renaming `domain_default_service` → `domain_default_process` (Mod 096) left the
old name in **five** files. The worklist covers one (`transfer_tables.md:733`).
The other four are `projinfra/` specifics:

| File | Site | What is stale |
| ---- | ---- | ------------- |
| `specifics/projinfra/fixed_reverse_proxy.md` | `:112` | `domain_default_service`; the per-cert domain given as `<service>.<env>.<project>.<apex_domain>` |
| `specifics/projinfra/elastic_alb.md` | `:64` | `domain_default_service`; "services that are not the default get only the full `<service>.<env>.<project>.<apex>` host" |
| `specifics/projinfra/ec2_traefik.md` | `:61`, `:70` | `domain_default_service` ×2; the same 3-label host form; and "port-less workers … are never exposed", which no longer describes a `worker` (the role provides `port`, and rule 28 *requires* one alongside `health_check_path`) |
| `specifics/projinfra/elastic_acm_certs.md` | `:21` | `domain_default_service` |

This matters more than ordinary staleness: `domain_default_service` is not a
renamed concept, it is a **field the compiler now rejects**
(`model.py:288` declares only `domain_default_process`). A reader who follows
`elastic_acm_certs.md` and writes `domain_default_service:` into `infra.yml` gets
a hard error from a document that told them to. See [design question 1](#design-questions).

`preinfra/fixed_master_network.md:20` (finding 6 above) is the fifth omitted
site, in a file the worklist does name.

## Design

Governing constraints, applied to every edit below:

- **Surgical over rewrite.** Voice, heading structure, and link style are
  preserved. No heading is renamed, so no anchor into these files can break.
- **`cicl.md` and `contracts.md` are the rule of record.** They are not
  re-swept. The single exception is rule 7's scope clarification, which the plan
  assigns here explicitly.
- **No invented doctrine.** Where a correction needs a decision the advance never
  settled, it is raised rather than taken.
- **Zero dangling links.** A mechanical audit of `doctrine/` + `skills/` runs
  before and after. Baseline is 3 reported items, all benign: one genuine dangler
  in `doctrine/chain/chain_of_command.md` (`#use-of-agents`) which is **untracked
  operator work and left strictly alone**, and two `path/to/file.md` strings that
  are documentation *of* the link convention, not links.

### `cicd.md`

Four edits, all inside § Check Step and § Build Step and § Rollback.

1. **Item 3.2** — contracts match `consumes`, not `depends_on`. The contract
   filename gains the process segment.
2. **Item 3.3** — health endpoints are per process type. Rewritten to name the
   `web`-network *process type* as the carrier and `consumes` as the fan-out
   source (per correction 1), and to note the self-`/health` assertion applies to
   OpenAPI providers (`check.py:492`) — a worker's `/health` is declared by
   fields, not by its AsyncAPI contract, exactly as `contracts.md` prescribes.
3. **A new item 3.5** for the `consumes`-target assertion: a target must declare
   both `port` and `health_check_path`. Placed after the existing `curl` item
   rather than folded into 3.3, because the doctrine's numbered items are
   *assertions*, and this is a distinct one — even though the code happens to
   carry all three health sub-assertions in one gate (`check.py:426`).
   Item 3.4 (`curl`) gets the narrow per-codebase clarification from correction 4.
4. **§ Build Step, Process (dev iteration)** — `compose exec` into a running
   dev container becomes `compose run --rm` against the codebase's **exec
   service** (`build.py:146`). This changes the shape of the numbered list: step 1
   ("Ensure a dev-stage container … is available") is *deleted*, because the exec
   service needs no running stack — that is the whole point of `profiles: [exec]`.
   Also worth stating, because it is the operator-visible consequence: `build`
   passes no `--build` (`build.py:139-145`), so dev stays the hot loop.
5. **§ Rollback, precondition 1** — the `cicl_version` check is inserted as
   **1.4** (between "no more than one minor behind" and the registry image
   probe), matching the code's order (`rollback.py:135-149`, after
   `validate_one_minor_back` at `:121`, before `_missing_images` at `:154`) and
   the fact that it must follow the tag-exists check because it reads a blob out
   of that tag. Existing 1.4 renumbers to 1.5. The amendment is to the
   *precondition list only*: `cicl.md § CICL Version` already promises this
   behavior, so the doctrine gains no new rule here, it gains an accurate
   enumeration.

### `docex.md`

Three blurbs plus one factual correction.

1. **§ describe** — "directed acyclic graph" → "directed graph", and a sentence
   giving the reason: the rendered union of `depends_on` and `consumes` may
   legally contain cycles, because `consumes` is a cyclic digraph by doctrine.
   Only the readiness relation alone is acyclic. The `dag.py` module docstring
   already says exactly this (`dag.py:6-8`), so the doctrine is the lagging
   artifact. **The `--format dag` flag name is unchanged and the prose says
   nothing implying otherwise** — a format name is a label, not a claim, and
   renaming it would be a gratuitous CLI break. The blurb also gains the two
   edge kinds (solid readiness / dashed interface) since `describe` now renders
   both.
2. **§ describe → `preinfra` blurb** (`:88`) — "each `dev` `web`-service
   hostname" is per-process-type since Mod 096. The replacement must also stay
   true to a detail the worklist does not mention: `web_hostnames_for_env`
   (`compile.py:417-442`) enumerates web-network **backing** services as well as
   process types, so the honest phrasing is "every `dev` `web`-network hostname —
   one per `web` process type, plus any `web`-network backing service".
3. **§ check blurb** (`:159`) — "`depends_on`-to-contract alignment checks" →
   `consumes`.
4. **§ build blurb** (`:149`) — "inside its running `dev`-stage container" →
   the exec service, no running stack required.
5. **§ migrate blurb** (`:171`) — "via `docker compose exec`" → `compose run`
   against the exec service. Not on the worklist; it is the same sentence-level
   error as § build and § Build Step, and leaving one of three would be worse
   than fixing none.
6. **§ role blurb** — the magic-ref example given is
   `${backing_services.<svc>.<part>}`, which is still correct for backing
   services. It gains the four-segment core form alongside it, since `role` is
   the doctrine's designated discovery path for "what can a magic ref
   reference" and core roles (`web`, `worker`) now provide parts too.

### `shape.md`

1. **Both Runtime Shape replica claims are factually wrong as illustrated**, and
   the § General paragraph shares the error, so **three** paragraphs are
   corrected, not two. § General says the proxy "doubles as a load balancer";
   § Fixed says "there might be multiple of the same [service] (**e.g. multiple
   workers**) per environment - [reverse_proxy] load balances in this case";
   § Elastic says "[core_service]s can have multiple replicas; the
   [reverse_proxy] load-balances across them". The truth is split by network:
   - the reverse proxy balances **`web`** replicas — on fixed because
     `_traefik_labels` keys on the unqualified `global_name` so N containers
     register as N servers behind one router (`compose.py:173-184`); on elastic
     because the ALB target group holds N tasks;
   - **internal** replicas are balanced by **Docker DNS round-robin** over the
     shared network alias on fixed (`compose.py:290`) and by **Service Connect**
     on elastic, with no proxy in the path at all.

   The `e.g. multiple workers` illustration picks the one case the sentence does
   not describe, which is why this is a correctness fix and not a polish pass.
2. **The `core_service` rows** (fixed `:47`, elastic `:77`) — the unit is now a
   process type, one per `command`, all sharing the codebase's image.
3. **The `telemetry_sidecar` rows** — fixed `:51` says "distinct compose
   container for each [service] sharing at least one of its networks", which is
   wrong on both halves: pairing is by **netns** (`network_mode: service:<key>`),
   not by shared network, and the unit is each **emitted app container** —
   per non-`scheduler` process type, per replica. Elastic `:81` becomes per
   process type that emits `ecs_service`.
4. **§ Shape and Environment** `:85` — "only one container per role, per
   environment" → per **process type**.
5. **§ Concrete Example** — converted to `cicl_version: "2"` with a `processes:`
   block, per correction 5. The conversion is deliberately **minimal**: the same
   single `api` codebase with a single `web` process type, so the compiled
   walk-through keeps its shape and only the identities move
   (`api` → `api-web`, `api.dev.…` → `api-web.dev.…`, `domain_default_service` →
   `domain_default_process: api.web`, `role`/`port`/`networks`/`resources` nested,
   `command` added). Rejected alternative: adding a `worker` to showcase the new
   capability — it would double the length of every bullet in the two compiled
   sections and turn a shape illustration into a process-types tutorial, which is
   `cicl.md`'s job and already done there.

### `tests.md`

§ Staging Tests, the Liveness bullet: "Each core service responds to its
health-check endpoint" is now impossible as written — a non-`web` process type is
not reachable from the stage tester, which runs outside the env over HTTPS.
Replaced with the two-part shape the health model actually provides: each `web`
process type answers `/health` at its own hostname, and everything it `consumes`
that is not itself on `web` is reached through that process type's
`/health/<service>/<process>` fan-out. This is a restatement of
`contracts.md § Fan-out` at the altitude `tests.md` works at, and it links there
rather than duplicating the thresholds.

### `telemetry.md`

Three sites, as flagged.

1. `:84` — "there is one per core service container" → one per **emitted core
   service container**, i.e. per non-`scheduler` process type (and per replica on
   fixed). Adds the `scheduler` exclusion, which the current sentence cannot
   express and which `scheduler.md` already states from the other side.
2. `:114` — `OTEL_SERVICE_NAME` is "Simply the name of the service in
   `infra.yml`" → the two-segment compiled identity `<service>-<process>`. Adds
   the OTel-correctness reason (semconv requires `service.name` identical across
   horizontally-scaled instances, so per-process-type is the right granularity
   and per-replica would be wrong).
3. `:117` — `OTEL_RESOURCE_ATTRIBUTES` gains `docex.core_service=${service}` and
   `docex.process_type=${process}`, in the code's order (`compile.py:957-969`:
   after the unchanged `service.namespace` / `service.version` /
   `deployment.environment.name` triple).
4. `:125` — `docker compose logs <svc>-otelcol` → `<svc>-<proc>-otelcol`.
   `practices/logging.md:30` was already corrected in Mod 094 and is the form to
   match.

### `specifics/scheduler.md`

The most thoroughly stale file in the sweep — it is written end-to-end around a
scheduler being a *core service* with a service-level `role: scheduler`.

1. **Framing** (`:7-16`, `:18-46`) — a scheduler is a **process type**, not a
   core service. The `infra.yml` example is renested under a codebase. Per the
   naming convention in `cicl.md`, the example names the codebase `jobs` and the
   process `nightly_cleanup`, which also demonstrates why the convention exists.
2. **Ofelia identities** — the compose service is
   `{project}-{env}-{svc}-{proc}-scheduler` (`compose.py:445`) and the INI
   section is `[job-run "<svc>-<proc>"]` (`compose.py:420`), both two-segment.
   The rendered INI sample at `:101-111` is updated, including its
   `OTEL_SERVICE_NAME=nightly_cleanup` line, which is now `jobs-nightly_cleanup`.
3. **The image** — keys on the **codebase** (`compose.py:379-381`), shared with
   every sibling process type. This **retires mod 074's self-contained job
   image**, and the file should say so rather than silently drop it: the note
   explains that two consumers of one tag have to agree about what is inside it.
4. **Mod 103's invariant is carried:** *in `dev`, the codebase tag is the
   Dockerfile `dev` stage — for every process type, including a cron job.* With
   its accepted consequence stated plainly, because it will surprise someone: a
   `dev` job runs the artifact the `dev` stage baked, refreshed on `up dev`, not
   the host's live `dist/`. (This is flagged item 9, still open; the doctrine
   documents current behavior and does not pre-empt the decision.)
5. **§ Caveats — the `test.sh` carve-out is deleted.** Its entire justification
   was "there is no `test`-stack container to `exec` into", which Mod 099's exec
   service dissolved; `test.py:118-121` now runs a scheduler-only codebase
   through the identical path with no role filter, and `_run_scheduler_tests` no
   longer exists. The surrounding `test`-suppression caveat stays (the *trigger*
   is still dropped in `test`) and gains the precise consequence from
   `compiler.md`: in `test`, a scheduler process type contributes nothing, so a
   scheduler-only codebase's only compose block is its exec service.
6. **The one genuinely new fact** the file needs: a scheduler-only codebase's
   image is built by no compose service (`up --build` skips the profile-gated
   exec service), so `up dev` builds that tag itself. Sourced from
   `compiler.md § The scheduler trigger`; without it, item 4's invariant has no
   mechanism.

### `specifics/transfer_tables.md`

1. **§ Available compile-time variables** — `${name}` is documented as "the
   simple service name from `infra.yml`". For a core **process type** it is the
   compiled two-segment identity (`compile.py:689`, `"name": key`, where `key` is
   `ProcessRef(...).compiled`); it remains the simple name for a backing service.
   Not on the worklist; found while checking `${global_service_name}`. Left
   ambiguous, an engine author writing `${name}` into a core role's `provides:`
   gets `api-web` while the table promised `api`.
2. **§ Per-container (fixed)** — `container_name` and `networks:` are per process
   type. `aliases` and the list→map conversion are documented as **conditional
   on the replica unroll** (correction 3), placed as a short note under the
   invariant block rather than inside it, so the invariant stays an invariant.
   The traefik label block gains the **unqualified-`global_name`** rule as an
   explicit constraint with its reason (N containers → one router, one service,
   N servers; qualifying per replica would give N routers fighting over one
   `Host()` rule). `${host_rule}`'s trailing `domain_default_service` →
   `domain_default_process`, and the host form gains the process segment.
3. **§ Per-core-service env** — `OTEL_SERVICE_NAME`'s row becomes the compiled
   identity; two rows are added for the `docex.*` attributes. Then the section
   gains the point the worklist correctly insists on: **there are now two
   identity forms where the file states one.** The per-codebase emitters (the
   exec container, the elastic migrate task definition) carry
   `OTEL_SERVICE_NAME=api` with `docex.process_type` **absent** — and the
   worklist's precision note is right and is honoured: the value is the
   **authoring** name `api`, *not* `codebase_global_name`
   (`compile.py:1001-1005`), matching the migrate container's `name`
   (`hcl.py:571`) and the CloudWatch log group, both codebase-keyed since Mod
   099, and parallel to the process surface carrying the compiled two-segment
   name rather than the global one. The load-bearing consequence is stated as a
   rule: **`docex.process_type`'s presence is what marks an emitter as a declared
   process type; its absence marks a per-codebase artifact.**
4. **§ Per-resource (elastic)** — the envinfra tag block gains `process`, and
   `Name` becomes `${project}_${env}_${service}_${process}`. Both must record
   what happens for a backing service: the `process` key is **omitted entirely**,
   not emitted empty (`tags.py:43`, `compile.py:1197-1198`), which is what keeps
   backing tag blocks byte-identical to their pre-expansion form. `cicl.md`
   already carries this correctly; `transfer_tables.md` is the lagging copy.
5. **§ Authoring Project-Local Transfer Tables** (`:436`) — the bundled-engine
   list gains `worker/container`. Verified against `tables/roles/`, which holds
   exactly six role files: `cache`, `object_store`, `relational_db`, `scheduler`,
   `web`, `worker`.
6. **§ Anatomy → `emits`** (`:285`) — the destination-name examples gain
   `container_definition`, described as what it is: a **merge target, not a
   resource**. Its renderer returns `""` (`hcl.py:1057-1076`); registering it is
   what satisfies the dispatch loop and rule 12 without emitting a second
   resource. The `worker` walking reference notes it is the sole bundled user, for
   an ECS container-level `healthCheck` (`worker.yml:41-47`) — `web` still routes
   `health_check_path` to `target_group`, so the existing § Walking example:
   `web`/`container` narrative stays correct and is left alone.
7. **§ Resources Translation** — "For each core service" → per process type
   (twice), and the sidecar-overhead step gains the `scheduler` exception: a
   scheduler emits no `ecs_service`, gets no sidecar, and therefore pays no
   overhead (`compile.py:851-857`).

### `specifics/migrations.md`

§ Dev and Test Mechanism, rewritten for the exec service. Both halves of
correction 8 land here:

- `docker compose exec <service> /service/migrate.sh` becomes
  `docker compose run --rm <project>-<env>-<codebase>-exec ./migrate.sh`
  (relative path, `WORKDIR /service`), with `--build` only in `test`.
- The three paragraphs justifying `exec` — "the container is already up",
  "reuses all of that", "runs in the service's dev-stage container", "the
  application process keeps running while the exec is in flight" — are all now
  false and are replaced with the exec service's actual properties: no running
  app container required, `depends_on … service_healthy` on the codebase's
  backing services so the one-off gates on the database rather than assuming the
  stack is up, and **service-level `env:` only**, which is what makes
  *"`migrate.sh` may depend only on codebase-scoped env"* a rule with teeth
  rather than a convention.
- The retry paragraph stays true in substance (re-invoke, no teardown) and is
  adjusted only where it says "just another exec".
- § Stage and Prod on Fixed Foundation's pseudo-playbook is updated to the
  `compose run --rm <codebase>-exec /service/migrate.sh` form
  (`playbook.yml.j2:51-58`) — the absolute path is correct *there*, and the file
  must show both forms rather than one, or it is wrong for half its own scope.
  The old `docker_container` one-off block no longer resembles what is emitted.
- § Stage and Prod on Elastic: one migrate task definition **per codebase**,
  family `{project}-{env}-{codebase}-migrate`, sized by the per-dimension max
  across the codebase's process types.

### `specifics/telemetry_infra.md`

1. **§ Sidecar as Paired Compose Service** — "For each core service `<svc>`" →
   for each **emitted core service container**; `<svc>-otelcol` →
   `<svc>-<proc>-otelcol`; `network_mode: "service:<svc>"` → the paired app
   container's compose key. The `scheduler` exclusion and the replica-unroll
   pairing (`{global}-{i}-otelcol` on `service:{global}-{i}`) are stated here,
   since this is the section that owns fixed-side pairing.
2. **§ Sidecar as Paired Task Container** — per process type that emits
   `ecs_service`; the sidecar container name is `<svc>-<proc>-otelcol`
   (`hcl.py:432`). Notes there is no sidecar in a `scheduler`'s task definition
   or in the migrate task definition (`hcl.py:526-528`).
3. **§ Task-Level Resource Allocation** — the count arithmetic (correction 2,
   stated as a sum) and its Fargate interaction. The existing per-task
   arithmetic (`1024 + 102`, `2048 + 128`, rounding up to a tier) is **correct
   and stays**; what is added is that the overhead is paid **once per task
   definition**, so a codebase with three process types pays it three times and
   each rounds independently — and that a `scheduler` pays it zero times. This
   documents correct behavior; Mod 102 verified the code gets it right.
4. **§ Env Vars Injected on Core Services** — the same three rows as
   `telemetry.md` (`OTEL_SERVICE_NAME`, `OTEL_RESOURCE_ATTRIBUTES` ×2 new
   attributes), kept verbatim-consistent with `transfer_tables.md`'s table,
   which it explicitly defers to.
5. **The four remaining `<svc>-otelcol` literals** — `:57`, `:163`, `:234`,
   `:258`/`:262`/`:317` — updated for consistency. A reader who copies
   `docker compose logs -f <svc>-otelcol` gets nothing back.

### `specifics/networks.md`

Per-service attachment becomes per-process attachment: the file's own framing
sentence (`:7`, "env-tier per-service network attachment"), the tier table's
third row, `:19`, and the two `§ Per-Service Attachment` subsection bodies.
Headings are **not** renamed (`#networks-web` and `#networks-internal-and-any-other-non-special-name`
are linked from `infra-compile`, `transfer_tables.md:735`, and `network-design`),
so the section titles stay and only the prose inside changes. `:60`'s "reach it
by container name, which equals `${global_service_name}`" stays true and gains
the replica case: after an unroll the unqualified name is a **shared alias**
resolving to all N, and belongs to no single container.

### Rule 7's scope — the one `cicl.md` edit

The plan assigns exactly one `cicl.md` change here, owed from Mod 098: state that
rule 7 governs **process-type** referencers. A backing service holding
`${core_services.api.web.host}` — an `object_store` with a CORS origin, say —
cannot satisfy it: backing services have no `consumes:`, and rule 24 forbids them
a `depends_on` to a core service. That is rule 7 correctly **not applying**, not
a hole, because a backing service embedding a core hostname is not *calling* it,
so neither relation has anything to express. Mod 098 skipped and pinned it; the
doctrine should say so rather than leave it inferred.

Written as a short sentence appended to rule 7 plus a clause in
§ Consumes Relationships § Three clarifications, where the other three
one-directional/same-codebase/service-level clarifications already live. No new
rule number, no heading change.

### Skills

Pointers verified: all five `infra-compile` targets, `contracts`'s single target,
and `testing`'s single target resolve, and every anchor in `doctrine/` and
`skills/` resolves (mechanical audit, above). Mod 094 already fixed
`browser-investigate` and `contracts`. So this is a no-defect result rather than
a no-op — but two one-line body nudges keep the *routing* honest, since a thread
skill's body is a router and a stale router sends the agent to the right file
with the wrong expectation:

- `infra-compile`'s `scheduler.md` blurb says "Read when adding a cron-style
  scheduled **service**" → process type.
- `infra-compile`'s `networks.md` blurb says "how a **service's** `networks:`
  list becomes …" → a process type's.

`skills/chain-of-command/`, `skills/project-cohere/`, `skills/transcript-summary/`
and `skills/skill-iteration/references/evaluation.md` are untracked or dirty
operator work and are **not touched**.

## Verification

- `pytest tests/unit` must report exactly **982**, unchanged. This mod edits no
  code and no test; the number is the proof.
- The mechanical link audit must report the same 3 benign items as the baseline
  and no others.
- `grep` sweeps for the retired vocabulary must come back empty across
  `doctrine/` and `skills/`: `domain_default_service`, `<svc>-otelcol`,
  `<service>.<env>.<project>`, `compose exec` in a migrate/test/build context,
  "directed acyclic graph", `cicl_version: "1"`.

## Out of scope

Not taken, per the brief. `docex/test_projects/`, `upgrades/upgrade_1.6.0.md`,
`CHANGELOG.md`, and every version artifact are Mod 107's. `src/` and `tests/`
are untouched.

**Raised, not taken — one code finding.** `docker/client.py`'s `compose_exec`
protocol method has **zero production call sites** after Mod 099, and its
docstring (`client.py:122-126`) still claims it is "the primary mechanism used by
`docex build`, `docex migrate`, and the build-test step of `docex test`" — all
three of which now use `compose_run_one_off`. The method itself is still
reachable through the fake in `tests/conftest.py:131` and three unit tests assert
its *absence* from call lists, so deleting it is a real (if small) decision, not
a comment fix. This is a code change and this mod takes none.

**Routed to Mod 107 with the decision already made, so it does not arrive open:
fix the docstring, do not delete the method.** The asymmetry is the whole
justification. A protocol method with no current production caller is
unremarkable and costs nothing; a docstring asserting it is "the primary
mechanism used by `docex build`, `docex migrate`, and the build-test step" when
all three moved to `compose_run_one_off` is actively misleading. Deletion would
touch the protocol, the implementation, the test fake, and three tests that
assert its absence from call lists — a real change, and the last mod of a large
advance is the wrong place to take one.

## Design questions — all resolved

**Resolved by the C.O. before implementation.** Answers recorded inline below.

| # | Question | Ruling |
| - | -------- | ------ |
| 1 | Do the four `projinfra/` specifics come into scope? | **Yes.** `domain_default_service` is a field the compiler rejects, so the doctrine currently instructs a reader to write something that hard-errors with nothing signalling it until compile fails — strictly worse than a stale example. Step 15 stays separable regardless. |
| 2 | Minimal or expanded `shape.md` example? | **Minimal.** `shape.md`'s job is topology; the division of labour with `cicl.md § Process Types` is the reason, not economy. |
| 3 | How much to say about `dev` job code freshness (flagged item 9)? | **As designed** — factual, brief, no editorializing toward a fix. Item 9 is open on the operator's desk, and a short paragraph is cheaper to rewrite if it closes in 1.6.0. |

**1. Do the four `projinfra/` specifics come into scope?** — **RESOLVED: yes.** They are not on the worklist, but they name `domain_default_service` — a
field the compiler rejects — and give the pre-advance 3-label hostname form. The
edits are mechanical and small (one field rename, one host-form correction, and
in `ec2_traefik.md` the "port-less workers" clause). The argument for taking them
is that this mod's stated job is "make the conditional stratum true again", and a
document that tells a reader to write a rejected field is the worst class of
staleness in the sweep — worse than the `cicl_version: "1"` example, because a
reader can't tell it's wrong until compile fails. The argument against is scope:
they belong to the `projinfra-setup` thread skill, which this advance otherwise
never touched. **`implementation.md` stages them as a clearly-marked final step
so they can be struck without disturbing anything else** — retained as a separate
step even though approved, since separability costs nothing and keeps the
projinfra edits reviewable on their own.

**2. Is the minimal `shape.md` example conversion the right call?** — **RESOLVED:
minimal.** I convert the
existing single-`web`-process example rather than adding a `worker` to showcase
the advance. Rationale in [§ shape.md](#shapemd): `shape.md` illustrates
*topology*, and a second process type inflates every bullet of two compiled
walk-throughs to teach something `cicl.md § Process Types` already teaches with a
three-process example. If you would rather the doctrine's one end-to-end
worked example exercise the new capability, say so — it roughly doubles the
diff in that file and nothing else changes.

**3. Flagged item 9 (dev Ofelia job runs image-baked code) is still open, and
`scheduler.md` now has to say something about `dev` job code freshness.** —
**RESOLVED: as designed.** Document *current* behavior and its surprise, factually
and briefly, explicitly not pre-empting the decision and not editorializing
toward a fix. Item 9 remains open on the operator's desk; if it closes inside
1.6.0 that paragraph gets rewritten, and a shorter paragraph is cheaper to
rewrite.
