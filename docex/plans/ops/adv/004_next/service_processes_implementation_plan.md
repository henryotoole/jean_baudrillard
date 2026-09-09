# Service Process Types — Implementation Plan

Sequencing plan for the **service process types** advance. The design is settled
in [`service_processes_refactor.md`](./service_processes_refactor.md); this
document turns it into an ordered sequence of mod cycles grounded in the current
`docex` source and doctrine text.

Mods are numbered from **094** (last shipped: 093). Target cut: **1.6.0**.

## Operator decisions (settled up front)

| Decision | Choice |
| -------- | ------ |
| Version level | **MINOR → 1.6.0**, with `upgrades/upgrade_1.6.0.md`. Old-pinned projects keep working via their image pin, so no break reaches an un-upgraded project; the CICL format break is gated by `cicl_version: "2"` and surfaced at upgrade time. |
| Execution | Full doctrine mod cycles driven through `mod-developer` / `mod-implementor` subagents, per `docex_process.md` step 2. |
| Doctrine edits | **Fix small, flag large** — mechanical edits the design record already specifies land autonomously; anything semantic or newly-invented is collected in [Flagged for operator](#flagged-for-operator). |
| Autonomy scope | Implement every mod, keep the five artifacts aligned, run unit + `pytest -m integration`, migrate both smoke projects, write the upgrade guide and changelog. **STOP at ready-to-cut** — no real-infra smoke walk, no `RELEASING.md` tag/image build. |
| Manual test phase | None, per `docex_process.md` step 2.3. |

## The backbone: process expansion

The one abstraction the whole advance hangs off. Today `compile.py` maps one
`infra.yml` service key to exactly one `CompiledService`. After this advance a
core service key maps to **N** compiled services, one per process type:

```
CoreService(api) × {web, worker, nightly_cleanup}
    -> CompiledService(name="api-web",             core_service="api", process="web")
    -> CompiledService(name="api-worker",          core_service="api", process="worker")
    -> CompiledService(name="api-nightly_cleanup", core_service="api", process="nightly_cleanup")
```

The governing principle, straight from the design record:

> **`CompiledService.name` carries the two-segment compiled identity (`api-web`);
> the authoring models keep the authoring names.**

This is what keeps the emitters largely unchanged. Every one of these already
derives from `svc.name` / `svc.global_name` and therefore becomes correct for
free: traefik router and service keys (`compose.py:149`), ECS container names
(`hcl.py:328`), the paired sidecar (`compose.py:559`, `hcl.py:416`), Service
Connect `portMappings[].name` / `discovery_name` (`hcl.py:345,577-578`), the
CloudWatch log group (`hcl.py:454`), every HCL resource address
(`hcl.py:453,462,553,625,657`), and the envinfra tag block
(`compile.py:866-896`).

A second, smaller value type carries the **dots-for-reference / hyphens-for-emission**
rule so it is expressed in one place rather than at every read site:

```python
@dataclass(frozen=True)
class ProcessRef:
    service: str
    process: str
    @classmethod
    def parse(cls, raw: str) -> "ProcessRef": ...   # "api.web"; bare name is an error
    @property
    def dotted(self) -> str: ...                    # "api.web"
    @property
    def compiled(self) -> str: ...                  # "api-web"  == CompiledService.name
```

Consumers: `consumes:` targets, four-segment magic refs, `domain_default_process`,
contract filenames, `describe` node ids, and the rendered-identity uniqueness
check (rule 5).

Introduced in **Mod 096**; consumed from 097 onward.

## Current-state anchors

Where each change lands, verified against source.

- **`CompiledService`** — `cicl/compile.py:398-442`. No `process`, no `core_service`, no `replicas`. `name` set at `:744` from the `all_services()` dict key; `global_name` at `:749` from `ctx["global_service_name"]`.
- **`_global_service_name`** — `compile.py:276-280`, a three-part `f"{project}_{env}_{service}"` then `apply_policy`. Becomes four-part; the `alb` policy's 32-char `hash_truncate` (`naming.py:161-174`) starts biting.
- **Per-service loop** — `compile.py:570-785`, iterating `sorted(doc.all_services())` — core *and* backing together. `compiled_services[name]` at `:743` is the single-slot assumption.
- **`engines_by_service`** (`:507-531`) and **`contexts`** (`:534-551`) are both keyed by service name and both assume one `role` per key. Since `role` moves to the process type, both key domains must become the compiled two-segment identity.
- **`replicas`** — declared `model.py:96`, allow-listed `validate.py:43`, **read by nothing**. `hcl.py:560` hardcodes `desired_count = 1`; `compile.py:840` sets `container_name` unconditionally.
- **`cicl_version`** — `model.py:117`, parsed and never used. No comparison anywhere in `src/`.
- **`_MAGIC_RE`** — `magic_refs.py:41-43`, exactly three segments; the part group excludes `.`, so a four-segment ref does not match at all. It then matches `substitute.py:38`'s `_COMPILE_RE` (which *does* permit dots) and dies as *"undefined compile-time variable"*. Because `find_magic_refs` shares `_MAGIC_RE`, validation rules 3 and 7 skip four-segment refs silently.
- **`depends_on`** — one field on the shared base (`model.py:74`), validated only against the merged name space (`validate.py:313-349`). Core→core is not just tolerated, it is load-bearing at `validate.py:294-304` (rule 7), `check.py:313-330`, `check.py:403-418`, `compose.py:567-593`. Elastic drops it entirely (`hcl.py:689,723,759`).
- **`_infer_contract_format`** — `check.py:109-131`. Confirmed unreachable asyncapi branch: the only call site (`:333`) passes a **core** name; line `:123` looks it up in `backing_services`; `model.py:163-168` forbids the overlap. Always returns `openapi`.
- **`_gate_health_endpoints`** — `check.py:374` derives the service via `path.name.split(".", 1)[0]`, which yields `api` from `api.web.openapi.yml` and silently `continue`s on an unknown name (`:377`).
- **The curl gate** — `_gate_healthcheck_tooling`, `check.py:465-520`. Keys off `getattr(svc, "health_check_path", None) is not None`, no network filter. Becomes correct automatically once the field is process-scoped. **Do not re-key off `role`.**
- **`compose_service_key`** — `orchestrate/_common.py:142-166`. Returns the first key ending in `-<name>`/`_<name>`; falls back silently to the bare name. Callers: `migrate.py:102`, `test.py:121,144`, `up.py:158,238`. `build.py:109,122-126` carries **two** more copies of the same heuristic and picks `matching[0]` off a `set` — non-deterministic when more than one key matches.
- **`compose run` is never used.** `compose_run_one_off` exists (`docker/client.py:81-99`) with zero call sites. There is **no `profiles:` key anywhere** in the codebase.
- **Sidecars** — `compose.py:545-565` pairs one per core non-scheduler service via `network_mode: service:{global_name}` (`:220`); `hcl.py:391-438` adds one container per task def gated on `"ecs_service" in emits`.
- **`container_definition` does not exist.** `EMIT_DESTINATIONS` is `transfer.py:83-95`; the renderer table is `hcl.py:927-936`. There is **no `healthCheck` key anywhere in `src/`**. `render_task_definition` (`hcl.py:311-540`) builds `container_def` procedurally and reads only four task-level keys off `svc.body` (`:321-324,330`).
- **Migration identity** — the elastic migrate task def is emitted *inside* `render_task_definition` (`hcl.py:497-538`) as `f"{svc.global_name}-migrate"` with resource address `{svc.name}_migrate`, and that address string is independently reconstructed at `migrate.py:351` and `release.py:401`.

## Mod sequence

Each is a full mod cycle (overview → `implementation.md` → sub-agent execution →
drift review → tests). Ordering keeps the suite green at every boundary.

---

### Phase 0 — the rule of record

Per `docex_process.md` step 1, doctrine changes first. Only the *rule of record*
goes here; the specifics files that document emitted mechanics are written after
the code exists (Mod 106), which is how envmageddon handled the same split.

#### Mod 094 — Doctrine: process types, `consumes`, and the rule restatements
**Touches:** `doctrine/lexicon.md`, `hexagonal_architecture/{hex_overview,internal_dependency_rules}.md`, `infrastructure/{infrastructure,cicl,contracts}.md`, `practices/logging.md`.

- **Resident:** lexicon gains **Process Type** and **Entrypoint**; **Core Service** clarified as codebase + build artifact. `internal_dependency_rules.md` composition-root responsibility (4) rewritten — the root *constructs* every driving adapter, entrypoints *bind* them to a runtime host. `hex_overview.md` gains `entrypoints/` in the `src/` tree and a `Queue` row in the controller-mechanism table. `infrastructure.md` re-scopes "core services never share code" to core service **sources**, and § Contracts moves provider/consumer inference from `depends_on` to `consumes`. `logging.md`'s dev telemetry command becomes `docker compose logs -f <svc>-<proc>-otelcol`.
- **`cicl.md`:** the mandatory `processes:` block and worked example; field scoping table; the service level accepting only `{processes, secrets, config, env}`; `command` required everywhere; `consumes:` and the `depends_on`-is-backing-only restriction (§ Depends-On Relationships roles 2 and 3 move out); four-segment core magic refs; `domain_default_service` → `domain_default_process`; the two-segment hyphen-joined hostname label plus the note that **nothing reverse-parses it**; the process-type naming convention; `cicl_version: "2"`; rule restatements 5/7/10/12/14/15/16.
- **`contracts.md`:** the `${service}.${process}.${format}.yml` path, the provider set as (`consumes` targets) ∪ (web-network process types), role-derived format, and the health-declared-by-fields rule.
- **`contracts.md § Health Checks` carries the *whole* health model** — the in-process monotonic tick, the doctrine-fixed 10 s tick / 30 s staleness thresholds, the `consumes` ∪ `depends_on` fan-out union, `/health/<svc>/<proc>`, the one-hop rule, the `port` + `health_check_path` requirement on `consumes` targets, and the `scheduler` exemption. *Amended during Mod 094:* the first draft of this plan assigned `contracts.md` only the declared-by-fields rule and left the rest of the design record's § Health Checks with no doctrine home at all — Mod 106's file list omits `contracts.md` and Mod 101 is `check.py` only. Mod 094 owns it; Mod 101 implements against it; Mod 106 does not revisit it.
- **Also write the corollary explicitly** (design record § Two Relations rule 4): *startup ordering is not a substitute for connection resilience.*
- **No code changes.** No tests.

---

### Phase 1 — additive groundwork

Lands before the break, stays green, and is independently useful.

#### Mod 095 — The `worker` role + the `container_definition` destination
**Touches:** new `tables/roles/worker.yml`, `cicl/transfer.py`, `emit/hcl.py`, `cicl/validate.py`, tests.

- New bundled role table, verbatim from the design record § The `worker` Role: `emits.fixed: [compose_service]`, `emits.elastic: [task_definition, ecs_service, container_definition]`, `health_check_path` routing to `container_definition` on elastic, `provides: {host, port}`, `naming: ecs`.
- Add `container_definition` to `EMIT_DESTINATIONS["elastic"]` (`transfer.py:83-95`).
- Register it in `_DESTINATION_RENDERERS` (`hcl.py:927-936`) as a **no-op renderer returning `""`**. It is a *merge target*, not a resource: registering it satisfies the dispatch loop (`hcl.py:979-991`) and transfer-table rule 12 (`validate.py:586-610`, a field's `target:` must appear in `emits.<foundation>`) without emitting a second resource.
- `render_task_definition` merges `svc.target_extras.get("container_definition", {})` into `container_def` **after** `environment`/`secrets` are set (`hcl.py:351`) and **before** the `dockerLabels` / `mountPoints` / `dependsOn` whole-key assignments at `:357,380,412`, which would otherwise clobber it. Mirrors how `render_target_group` reads `target_extras` at `:631`.
- **Green today:** a flat `role: worker` core service compiles on both foundations before nesting exists. That is the point — it makes this diff separately reviewable.
- **Tests:** role table loads and validates; worker compiles to a compose service on fixed; worker compiles to task_definition + ecs_service with a container-level `healthCheck` and **no** target group on elastic; `container_definition` on a role that does not declare it is rejected.

---

### Phase 2 — the break

#### Mod 096 — Process nesting
The large one. Everything here must land together or the suite is red.

**Touches:** `cicl/model.py`, `cicl/validate.py`, `cicl/compile.py`, `tables/naming_policies.yml`, all four fixtures, most of `tests/unit`.

- **Model.** New `ProcessType` (`role`, `command` **required**, `port`, `networks`, `resources`, `replicas`, `depends_on`, `consumes`, `env`, `extra="allow"` for role fields). `CoreService` becomes `{processes, secrets, config, env}` with `extra="forbid"` — a stray `resources:` at service level is a hard error. `processes` required and non-empty. New `ProcessRef` ([backbone](#the-backbone-process-expansion)). `domain_default_service` → `domain_default_process`, taking a dotted ref. `cicl_version` validated: `"2"` accepted, `"1"` rejected with a message naming `upgrades/upgrade_1.6.0.md`.
- **Validate.** Rules 10/12/14/15/16 **and 28** re-scoped per process type — rule 28 (*declaring `health_check_path` requires `port`*) was added in Mod 095 against flat services and must move onto the process type here. Rule 5 becomes *rendered data-plane identity unique after naming-policy normalization, across core process types **and** backing services* — this catches core `api` + process `db` colliding with a backing service named `api-db`, which today's rule cannot. (14's reserved-name list now applies to process names too.) `_RESERVED_CORE_ENV_KEYS` (`validate.py:690-739`) evaluates against each process type's **effective** env (service ∪ process). `replicas` on a `scheduler` → error. `web` in `networks` on `worker`/`scheduler` → error (replaces the prose-only, unenforced check in `_validate_scheduler_services`, `validate.py:880-923`). `_STANDARD_CORE_FIELDS` (`validate.py:42-45`) splits into service-level and process-level allowlists.
- **Compile.** The per-service loop (`:570-785`) expands core services into N compiled entries. `engines_by_service` and `contexts` re-key to the compiled identity, since `role` — and therefore the engine — is per-process. `_global_service_name` takes a fourth segment. `CompiledService` gains `core_service`, `process`, `replicas`.
- **Keyed on the codebase, NOT the process** (getting this wrong is the main hazard): `_image_ref` (`:287-322`) and the ECR repo list handed to `emit_hcl_project` (`:1013`) — one image and one repo per codebase, which is the whole point of the advance. Also `schema_owned_by` / `schema_owned_by_db` (`:562-568,772`) and the source folder `core/<service>/`.
- **Web hosts.** `_web_hosts` (`:344-369`) and `web_hostnames_for_env` (`:372-390`) walk process types; `per_service` becomes the two-segment label. `domain_default_process` compares against the compiled identity.
- **Naming.** `http_host` gains `max_len: 63, overflow: error` in `tables/naming_policies.yml` — DNS labels hard-cap at 63 and a silently-overlong label would otherwise fail at cert issuance rather than at compile.
- **Error paths.** `_resources_to_elastic`'s `where=` strings (`compile.py:255,264`, `fargate.py:105,134,159`) become `core_services.<svc>.processes.<proc>.resources.disk`.
- **Fixtures.** All four (`sample_project`, `sample_project_elastic`, `sample_project_scheduler_{fixed,elastic}`) rewritten to `cicl_version: "2"` with `processes:`; `infra/contracts/api.openapi.yml` → `api.web.openapi.yml`.
- **Tests:** expect broad mechanical churn — every assertion naming `sample-dev-api` becomes `sample-dev-api-web`. New: `processes:` absent/empty rejected; service-level `resources:` rejected; `command` missing rejected; `cicl_version: "1"` rejected; rendered-identity collision (both the two-pair form and the core-vs-backing form); one core service with three process types emits three compose services and three ECS services all referencing one image.

#### Mod 097 — Four-segment magic refs
**Touches:** `cicl/magic_refs.py`, `cicl/substitute.py`, `cicl/validate.py`.

- `${core_services.<svc>.<proc>.<part>}` (4 segments) and `${backing_services.<svc>.<part>}` (3). **Parse generically, then arity-check by kind** rather than widening the regex — the current fall-through to `_COMPILE_RE` (`substitute.py:38`) produces *"undefined compile-time variable ${core_services.api} … available: [apex_domain, env_name, …]"*, which sends the reader hunting through compile-time variables for something that was never one. Segment-split first and emit: *"`core_services` refs take `<service>.<process>.<part>`; got `api.host` — did you mean `api.web.host`?"*
- `MagicRefDependency` (`magic_refs.py:49-56`) gains `target_process`; `consumer` becomes the compiled process identity. Cycle-guard key (`:75,102`) becomes `(kind, target, process, part)`.
- Self-references rejected, with a hint pointing at `localhost` — `provides.host` is the *internal* discovery name, so the one plausible motive (building absolute URLs) would not get what the author expects anyway.
- A ref to a `scheduler` process type already fails with no new code: `scheduler/container` declares `provides: {}` and rule 7 of transfer-table validation requires the part to exist. Add a test pinning that.
- **Tests:** 4-segment resolves; 3-segment core ref gives the arity message; hyphenated service names round-trip (today `_MAGIC_RE` permits `-` but `_COMPILE_RE` does not — pin the asymmetry closed); self-ref rejected; cycle through two processes of one codebase detected.

#### Mod 098 — The `consumes` relation
**Touches:** `cicl/model.py`, `cicl/validate.py`, `cicl/compile.py`.

- `consumes: list[str]` on `ProcessType`, dotted and fully qualified. A bare service name is **illegal, not shorthand** — an interface edge points at a specific boundary and a codebase does not have one contract.
- `depends_on` restricted to **backing services only** — *rule 24 was pulled forward into Mod 096.* Expansion makes a core→core `depends_on` genuinely unrepresentable: `compose.py:445`'s `simple_to_global` map cannot resolve a bare core name to one of N process types, and `compose.py:585` would silently pass the unresolved name through to a compose file that then fails at `up` time. Deferring it would have meant shipping a silent wrong mapping for two mods. Rule 6 (cycles) retained and now *more* important, since `service_healthy` gates are emitted. Compiler-emitted edges (sidecars, Ofelia, migration, the exec service) are unconstrained — the rule governs author-written `infra.yml` only.
- **Rule 7 splits by kind:** a backing-service ref must be matched by `depends_on`; a core process-type ref must be matched by `consumes`. Three clarifications the rule needs, all of which need tests: it is **one-directional** (ref ⇒ edge, never edge ⇒ ref — otherwise the ubiquitous web/worker topology, where `web consumes worker` for contracts and health but holds no magic ref, is rejected); **same-codebase is not exempt**; and a **service-level `env:` ref obliges every process type**.
- The `consumes` graph is a **cyclic digraph**, deliberately. `web ↔ worker` is legal and must be tested as legal.
- **A process type may not consume itself.** *Added in Mod 094* (`cicl.md` rule 25) beyond the design record's literal scope, which settles self-reference rejection for magic refs only. Accepted and carried here: a self-consume edge makes both derivations that `consumes` feeds nonsensical — a process type would be its own contract provider, and its fan-out would proxy its own `/health` at `/health/<self>`. Symmetric with the magic-ref self-ref rule in Mod 097.
- **Tests:** bare target rejected; core→core `depends_on` rejected; `consumes` cycle accepted while `depends_on` cycle still fatal; rule 7 both directions; service-level env ref obliging all processes.

---

### Phase 3 — consequences

#### Mod 099 — Per-codebase operations: the exec service
**Touches:** `emit/compose.py`, `emit/hcl.py`, `orchestrate/{_common,build,test,migrate,up}.py`, `emit/templates/playbook.yml.j2`, `pipeline/release.py`.

- Emit one `{project}-{env}-{svc}-exec` compose service per codebase, `profiles: [exec]` so `up` never starts it, with the same `build:` context and stage target (so Docker's cache makes it free), the dev bind mounts, the union of the codebase's non-`web` networks, and `depends_on` with `condition: service_healthy` on its backing services. Invoked via `docker compose run --rm …-exec ./migrate.sh`; `compose run` implicitly enables the target's profiles, so the guard costs nothing at the call site.
- It carries **service-level `env:` only**. That turns a trap into a rule with teeth: *`migrate.sh`, `test.sh`, and `build.sh` may depend only on codebase-scoped env* — correct on its own merits, since a migration has no business reading a worker's concurrency knob.
- Delete `compose_service_key` (`_common.py:142-166`) and **both** copies of the suffix heuristic in `build.py` (`:109`, `:122-126`); add `exec_service_key`. This also kills a live bug: today a codebase named `web` resolves to `sample-dev-api-web` — wrong container, no error.
- Wire `compose_run_one_off` (`docker/client.py:81-99`), which has existed with zero call sites since Phase 3 planning.
- **Emit the exec service in all four fixed envs, not just dev/test.** Found in Mod 099's design: `playbook.yml.j2` runs `compose run --rm <carrier-app-service> /service/migrate.sh`, so fixed **production** migration reads the carrier process type's `env:` overlay — the exact trap justification #2 exists to close, lapsing at the place it costs most. Routing the playbook through the exec service closes it and removes `schema_owned_by_db`'s last carrier consumer.
- **Migration sizing = per-dimension max across the codebase's process types** (settles flagged item #5). Chosen over the Mod 096 bridge because the bridge's real defect is *instability* — renaming `api.web` → `api.zweb` silently resizes the migration. Max is order-independent, byte-identical for single-process codebases, dissolves the scheduler carve-out, and provably lands on a valid Fargate pair (max memory came from a process with cpu ≤ max cpu and the allowed range widens with cpu; max cpu's own process cleared that tier's floor with memory ≤ max). Doctrine-fixed sizing was rejected as colliding with settled convention #4 — there is nowhere to put an override, and a non-overridable constant is a hard ceiling on a large backfill.
- **Rule 5's domain extends to compiler-emitted derivatives** (`-otelcol`, `-scheduler`, `-migrate`, and the new `-exec`). A process type named `exec` renders `{p}-{e}-api-exec` and silently clobbers codebase `api`'s exec service. This is a pre-existing class — `otelcol` and `scheduler` collide the same way today, unguarded — so closing it is worth more than the one suffix this mod adds. Chosen over growing rule 14's reserved-name list because rule 5 is collision-based rather than name-based: it covers future suffixes with no further edits and continues exactly the widening Mod 096 performed. Mod 099 updates rule 5's text in `cicl.md` (Mod 106 does not own that file) and implements the validator.
- **Elastic migration identity is codebase-keyed.** Move the migrate task def (`hcl.py:497-538`) out of the per-process `render_task_definition` into a per-codebase pass so one codebase yields one `…-migrate` family, not N. Keep the resource address `{codebase}_migrate` so `migrate.py:351` and `release.py:401` stay valid. See [Flagged for operator](#flagged-for-operator) #1.
- `up.py:158`'s `_diagnose_unhealthy` and `:238`'s post-up migrate loop follow.
- **Tests:** exec service emitted once per codebase with service-level env only; not started by `up`; migrate/test/build route through it; a codebase named `web` no longer mis-resolves; one migrate task def per codebase on elastic.

#### Mod 100 — Replicas
**Touches:** `cicl/compile.py`, `emit/compose.py`, `emit/hcl.py`, `cicl/validate.py`.

- **Elastic:** `desired_count = replicas` at `hcl.py:560`, clamped to 1 outside `prod` per `shape.md`. No deployment-config work — nothing is emitted today, so ECS's defaults (min 100% / max 200%) apply and are correct for a static count. Synergy with Mod 095: a worker ECS service has no target group, so without the container `healthCheck` ECS would call a task healthy the instant it reaches RUNNING and roll a broken deploy through all four replicas.
- **Fixed: unroll, do not scale.** `deploy.replicas` cannot work — Compose has no replica-to-replica pairing semantics, so one netns-paired sidecar cannot serve N replicas, and Compose refuses `deploy.replicas` alongside `container_name`. So the compiler emits N distinct compose services `{global}-1..N`, each with `container_name`, each carrying the **shared network alias `{global}`** (which is what keeps `provides.host` working, via Docker DNS round-robin), each with its own 1:1 sidecar on loopback. This requires converting the compose `networks:` list form to map form — there is **no `aliases` handling anywhere in the emitter today**.
- **Traefik labels must stay keyed on the unqualified `{global_name}`** so the docker provider sees N containers declaring one router and one service and loads them as N servers. A constraint to write down and test, not leave to chance.
- **Blast radius is small:** `replicas` applies only in `prod`, so `dev`, `test`, and fixed `stage` unroll to exactly one and emit output byte-identical to today.
- `replicas` on a `scheduler` → compile error (Ofelia fires one job; a count is meaningless).
- ~~**Host-port collision.**~~ Resolved in Mod 096 — see flagged item #2.
- **The unroll lives in `emit/compose.py`, NOT `cicl/compile.py`** — correcting this plan's own § docex Work bullet, which said otherwise. `CompiledEnv.services` is the *topology* model that `describe`, the `check.py` gates, and `group_by_codebase` (exec service, migrate task def, ansible) all read; unrolling there would yield four worker nodes in the DAG, four contract providers, and four exec services per codebase. **A replica is an emission detail, not a topology node.**
- **Rule 5's collision domain seeds `{compiled}-{i}`** when `replicas > 1`: codebase `api` with process types `web` (`replicas: 3`) and `web-1` renders `api-web-1` twice, one container silently clobbering another. Prod-fixed only, which makes it *more* worth catching at compile — it is the configuration nobody rehearses. Rule 5's text is updated here, per the Mod 095 / Mod 099 precedent that `cicl.md` has no downstream owner.
- **This mod ships essentially unexercised against real infrastructure**: every integration test runs against `dev`, which clamps to 1. Mod 107 should declare `replicas: 2` on the elastic smoke project's worker so a real `desired_count = 2` goes through `tofu validate` and the pre-cut walk.
- **Tests:** `replicas: 4` in prod-fixed emits 4 services + 4 sidecars + 1 shared alias + 1 traefik router; dev/test/stage emit exactly one and match the pre-mod snapshot; elastic sets `desired_count`; scheduler rejection.

#### Mod 101 — Contracts and health gates
**Touches:** `pipeline/check.py`. The rule of record is `contracts.md § Health Checks` as written in Mod 094 — implement against it, do not re-derive it from the design record.

- Replace `_infer_contract_format` (`check.py:109-131`) with **role-derived** format driven off `consumes:` — `web` → openapi, `worker` → asyncapi. A fix, not a refactor: the asyncapi branch has been unreachable since it was written, which is why the async-contract path was never exercised and the `depends_on` flaw went unnoticed.
- Provider set = (`consumes` targets) ∪ (web-network process types). **Both** arms are needed: `_gate_contracts:328` deliberately treats any web-network service as a provider so the health-endpoint gate has something to validate, and driving the set purely off `consumes:` would silently switch that off.
- Contract filenames parsed **right-anchored** (count segments from the right), replacing `path.name.split(".", 1)[0]` at `:374` — which today yields `api` from `api.web.openapi.yml` and then silently `continue`s.
- `_gate_health_endpoints` asserts `GET /health/<svc>/<proc>` against **`consumes` alone**. ⚠ *Corrected during Mod 101 and re-corrected in Mod 106:* the design record and this plan's first draft both said "the union of `consumes` and `depends_on`". Rule 24 (Mod 096) restricted `depends_on` to backing services, which have no `<service>/<process>` form, so the second arm **cannot fire** — the union collapsed as a side effect of a later mod. `contracts.md § Fan-out` now states `consumes` alone *specifically so nobody restores an arm that cannot fire*, and re-introducing "union" into any doctrine file is that restoration. The original motive still holds and is worth keeping: keying off `depends_on` alone would silently stop requiring the probe — and a dead consumer is invisible from outside, since requests keep returning 200 while work piles up.
- New assertion: a `consumes` target must declare `port` **and** `health_check_path`. On elastic the `port` is also exactly what makes it Service-Connect-discoverable.
- `scheduler` process types exempt — no long-running container to probe, and a scheduler is never a `consumes` target.
- **Leave the curl gate keyed off `health_check_path`.** It becomes correct automatically once the field is process-scoped; re-keying it off `role` would be strictly worse.
- **Tests:** worker provider gets `asyncapi`; two HTTP process types on one codebase each get their own contract; right-anchored parse; missing `/health/api/worker` fails; `consumes` target without `port` fails.

#### Mod 102 — Telemetry identity
**Touches:** `cicl/compile.py`, `cicl/validate.py`.

- `OTEL_SERVICE_NAME = {service}-{process}` — exactly `CompiledService.name`, so this largely corrects itself once Mod 096 lands. OTel-correct rather than merely convenient: the semantic convention requires `service.name` to be identical across horizontally-scaled *instances*, and this value is per process type, not per replica.
- Two resource attributes appended to `OTEL_RESOURCE_ATTRIBUTES` (`compile.py:735-739`) so both axes are queryable rather than recoverable only by a brittle prefix match on a hyphenated name: `docex.core_service=${service}`, `docex.process_type=${process}`. The `docex.` prefix matches the `docex.project` docker label precedent.
- `service.version` stays `${project_version}` — that is what makes a persistent web/worker version mismatch a real signal (a stuck rollout, not a config difference).
- **Inherited from Mod 099:** `OTEL_SERVICE_NAME` inside `service_env` is stamped by the compiler *before* the surface split, so a compiled identity (`api-web`) leaks a process segment into both the **exec container** and the **migrate task definition** — neither of which is that process type. Pre-existing (the old carrier leaked it too; only *which* process it named changed), and left deliberately unfixed for this mod since 102 owns telemetry identity and already touches `compile.py`.
- **`service.instance.id` is deliberately not set.**
- **Tests:** both process types of one codebase get distinct `OTEL_SERVICE_NAME`; both new attributes present; process-level env cannot shadow a reserved key.

#### Mod 103 — Scheduler as a process type
**Touches:** `emit/compose.py`, `cicl/compile.py`, `orchestrate/test.py`.

- Ofelia job name and image key off the **codebase** image, retiring mod 074's self-contained job image. Job INI name becomes the two-segment identity.
- **Do not assume the exec image exists.** `compose up --build` does **not** build profile-gated services, so the exec image is free only because its tag is byte-identical to a non-gated app service's. A scheduler-only codebase in `test` has no non-gated service building that tag, so `compose run` builds it. Mod 099 left `_ensure_scheduler_image` and its branch untouched with a `MOD 103 DELETES THIS BRANCH` marker — verify the image path before deleting it.
- Delete `_run_scheduler_tests` (`test.py:40-63`) — the scheduler-only `test.sh` carve-out exists solely because "there is no `test`-stack container to `exec` into", which Mod 099's exec service dissolves. A scheduler-only codebase now takes the identical path.
- No sidecar for `scheduler` process types — already true per-service, now strictly better per-process: a codebase with `web` + `nightly_cleanup` gets one sidecar for the web process and none for the job, which the service-level phrasing could not express.
- **Tests:** scheduler-only codebase runs `test.sh` through the exec service; mixed web+scheduler codebase emits exactly one sidecar; ofelia job uses the codebase image.

#### Mod 104 — `describe` and preinfra
**Touches:** `describe/{dag,llm}.py`, `pipeline/preinfra.py`.

- Render **both** edge kinds with the process dimension in node identity — solid for readiness (`depends_on`), dashed for interface (`consumes`). This is the single graph the merged form was reaching for, available as a *view*: one DAG for understanding, two relations for enforcement.
- `llm.py`'s edge `kind` gains `"consumes"` alongside `"depends_on"`.
- `_check_dev_dns` (`preinfra.py:165-196`) goes per web **process type** — it already delegates to `web_hostnames_for_env`, so this mostly follows from Mod 096; add the test that pins it.

#### Mod 105 — Rollback `cicl_version` precondition
**Touches:** `pipeline/rollback.py`.

- `cicd.md § Rollback` step 3 recompiles the target version's `infra.yml` **using the current docex**, and precondition 1.3 permits any target within one minor. So after this ships, `rollback prod <pre-1.6.0>` checks out a flat `cicl_version: "1"` tree and hits a compile error. It fails *safely* — the recompile precedes any apply — but during an outage, which is the one moment you cannot afford to discover it.
- Add the check to the **cheap pre-flight band** (`rollback.py:108-118`, before the worktree is created at `:139`), reading the target tag's `infra.yml` via a `git show`-style read; `check.py:241-254`'s `_git_show` is the existing precedent. Abort with *"cannot roll back across the CICL v1→v2 boundary — fix forward"*.
- A precondition, not a capability. For exactly one release cycle after 1.6.0 ships, prod has no rollback path; that window is accepted and documented rather than served by a read-only flat-form parser.

---

### Phase 4 — closeout

#### Mod 106 — Conditional-stratum doctrine sweep
Written after the code so it describes what is actually emitted.

`infrastructure/cicd.md` (check item 3.2; **also item 3.3**, since health endpoints are now per process type; **and a new item** for the `port` + `health_check_path` assertion on `consumes` targets — both gaps found in Mod 101; § Build Step's dev iteration; § Rollback's new precondition) · `docex.md` (the `check`, `build`, and `role` blurbs; **and § describe's "directed acyclic graph" → "directed graph"** — found in Mod 104, and *false* rather than merely stale, because the rendered union of `depends_on` and `consumes` may legally contain cycles. The `--format dag` flag itself is deliberately unchanged: a format name is a label, not a claim, and renaming it would be a user-facing CLI break in an advance already spending a large breaking-change budget on things that had to break. **Also in that section**: the `preinfra` blurb still says "each `dev` `web`-**service** hostname" for what has been per-process-type behavior since Mod 096 and is now pinned by a test) · `shape.md` (**`:101`'s example still reads `cicl_version: "1"`** — found in Mod 105, and the highest-embarrassment staleness in the sweep, since it is the one place the doctrine *displays* the value and it displays the rejected one; `core_service` and `telemetry_sidecar` rows; **both** Runtime Shape paragraphs, whose replica load-balancing claim is wrong as illustrated — the proxy balances *web* replicas; internal replicas are balanced by Docker DNS and Service Connect with no proxy involved) · `tests.md` (staging liveness per process type) · `telemetry.md` (:84, :113, :125) · `specifics/scheduler.md` (scheduler as a process type; delete the § Caveats `test.sh` carve-out) · `specifics/transfer_tables.md` (per-process emission; the new `container_definition` destination; § Per-container's `container_name` + `aliases` + unqualified-traefik-label rules; § Per-core-service env's `OTEL_SERVICE_NAME` row and two new attributes — **and note there are now *two* identity forms** where the doctrine states one: Mod 102 de-qualifies the identity on the per-codebase emitters (exec container, migrate task definition) to `OTEL_SERVICE_NAME=api` / `docex.core_service=api` with `docex.process_type` **absent**, so the attribute's presence means "this emitter is a declared process type". Precision the wording needs: the codebase surface carries the **authoring** name (`api`), not `codebase_global_name` — matching the migrate container `name` and the CloudWatch log group, both codebase-keyed since Mod 099, and parallel to the process surface carrying the compiled two-segment name rather than the global one. The envinfra tag block's `process` tag; the `worker` role in the bundled-engine list) · `specifics/migrations.md` (§ Dev and Test Mechanism, `compose exec` → `compose run`) · `specifics/telemetry_infra.md` (four sections, incl. the **N × R** sidecar arithmetic and its Fargate tier interaction) · `specifics/networks.md` (per-process attachment) · `preinfra/fixed_master_network.md` (the Lua comment's "three canonical doctrine forms" is stale — behavior unchanged, comment wrong).

**One doctrine clarification owed, from Mod 098:** state rule 7's **scope** explicitly — it governs *process-type* referencers. A backing service holding `${core_services.api.web.host}` (e.g. an `object_store` with a CORS origin) cannot satisfy it at all: backing services have no `consumes:` and rule 24 forbids them `depends_on` to a core service. That is rule 7 correctly not applying rather than a hole — a backing service embedding a core hostname is not calling it, so there is no readiness or interface implication for either relation to express. Mod 098 skips and pins it; the doctrine should say so rather than leave it inferred from the wording.

Also verify the `infra-compile`, `contracts`, and `testing` skill pointers still resolve, per `doctrine.md`'s "the one ongoing cost of this structure".

#### Mod 107 — Smoke projects, upgrade guide, changelog
- Migrate both `docex/test_projects/` projects to `cicl_version: "2"`, adding a genuine `worker` process type to at least one so the advance's motivating capability is actually exercised in the pre-cut walk.
- **Hidden step, found in Mod 096:** because a service-level `env:` magic ref obliges *every* process type to declare the matching `depends_on`, adding a `worker` to a smoke project also requires adding `depends_on: [<backing>]` to that new process. It bit the test fixtures; it will bite the smoke projects the same way.
- **Declare `replicas: 2` on both smoke projects' workers.** Mod 100 ships essentially unexercised against real infrastructure — every integration test runs against `dev`, where the clamp applies. The **elastic** side puts a real `desired_count = 2` through `tofu validate`; the **fixed unroll** has no equivalent short of a prod walk, so if the pre-cut walk reaches prod-fixed, that is the only thing that will ever have exercised it.
- **Upgrade-guide note, found in Mod 096:** a scheduler-only codebase named after its job compiles to `nightly_cleanup-nightly_cleanup`. Ugly but correct — it is what a mandatory `processes:` block produces, and inventing a collapse rule is precisely what that block exists to prevent. The guidance is to name the *codebase* after the codebase (`jobs`) and the process after the job (`nightly_cleanup`).
- **Fix `compose_exec`'s docstring; do NOT delete the method.** Found in Mod 106: `docker/client.py` `compose_exec` has zero production call sites after Mod 099, but its docstring still claims it is "the primary mechanism used by `docex build`, `docex migrate`, and the build-test step of `docex test`" — all three moved to `compose_run_one_off`. Deleting the method is a real change (protocol, implementation, the fake, and three tests asserting its absence from call lists) and the last mod of a large advance is the wrong place to take one. A protocol method with no current caller is unremarkable; a docstring naming three callers it no longer has is actively misleading.
- **Breaking change with no workaround, from Mod 097:** `_COMPILE_RE` was widened to admit `-`, so a `${a-b}` that previously passed through as literal text now fails as an undefined compile-time variable. The CICL grammar has exactly `${var}`, `$[var]`, `@expr` and **no escape form**, so a project genuinely wanting a literal `${a-b}` has nowhere to go. Document the change and the absence of an escape.
- **The changelog covers mods 094-106 in one entry.** Every mod in this advance deferred it here by design, so 107's author must walk each mod's `overview.md` rather than reading the final diff — 096 alone is 58 files and its intent is not recoverable from the diff.
- Write `upgrades/upgrade_1.6.0.md`. Its spine is the design record's [not-process-qualified table](./service_processes_refactor.md#what-is-not-process-qualified) — the inventory of what *doesn't* move — plus the nine numbered migration steps. Call out explicitly: **on fixed, add public DNS records for every new web hostname before `envinfra up dev`**, or Let's Encrypt's failed-authorization rate limit trips; and **rollback is unavailable across the boundary**.
- `CHANGELOG.md`, `VERSION`, `docex/pyproject.toml`, `docex/src/docex/__init__.py` per `RELEASING.md`.

---

## After the mods

Per `docex_process.md` steps 3-4, outside the mod cycles and **not** in this
plan's autonomy scope:

1. `pytest -m integration`.
2. The two-foundation smoke walk per `docex/test_projects/PRE_CUT_CHECKLIST.md`. **Required** — 1.6.0 is a minor. **Its role has grown.** Two areas of this advance have no automated coverage at all and are provable *only* by this walk: (a) **no integration test covers a scheduler** — `tests/integration/conftest.py:19` points every one at `sample_project` — so Mod 103's ofelia and exec-path work rests entirely on `test_projects/fixed`'s `reaper`; and (b) **the fixed replica unroll** is unit-tested only, since every integration test runs against `dev` where `replicas` clamps to 1. Treat the walk as a gate on those two specifically, not just as a smoke test.
3. Cut per `RELEASING.md`.

## Flagged for operator

Semantic questions the design record does not settle. None block starting; all
need an answer before the mod that owns them.

1. **Migration task-definition identity (Mod 099).** `schema_owned_by: api` names a codebase, and the design record lists the `schema_owned_by` target as *not* process-qualified. But the elastic migrate task def is emitted inside the per-process `render_task_definition` (`hcl.py:497-538`), so under expansion one codebase would produce N identical `…-migrate` families. My recommendation: hoist it to a per-codebase pass, family `{project}-{env}-{svc}-migrate` with **no** process segment, preserving the `{codebase}_migrate` resource address that `migrate.py:351` and `release.py:401` reconstruct. This is consistent with the image and ECR repo staying codebase-keyed, but it is a shape the design record never draws.

2. **~~Host-port publishing for non-web process types~~ — RESOLVED in Mod 096.** Folded forward once Mod 096's design showed the collision is reachable between workers of two different *codebases* in `dev`, not just between replicas. Non-`web` core process types no longer publish host ports; the health port is reached from inside the netns by the container healthcheck and from siblings over the internal network, and since elastic never published, removing it improves dev/prod parity. Backing-service publishing is unchanged. Original text:  `compile.py:647-648` publishes `{port}:{port}` on fixed for a core service with a port not on the `web` network. The design record asserts "no host-port collisions, because web services never publish host ports" — true for `web`, but a `worker` declaring the now-required health `port` lands squarely in this branch, and unrolled replicas would collide on the host port. My recommendation: stop publishing host ports for non-`web` core process types entirely (the health probe runs *inside* the netns via the container healthcheck, and a sibling reaches it over the internal network), and keep the publish only where it exists for backing services.

3. **The `alb` naming policy's 32-char truncation.** The design record calls this "an upgrade-guide note", but with a fourth segment it will bite common names — `myproject_prod_api_worker_tg` is already 28. Worth deciding whether target-group names silently gaining hash suffixes is acceptable (the descriptive name does survive in the `Name` tag) or whether the policy should change. I lean toward accepting it and documenting, per the record.

4. **No `queue` backing role ships.** `tables/roles/` has only `cache`, `object_store`, `relational_db`, `scheduler`, `web`. So the advance's own motivating example — a real queued task — can be expressed only as redis under the `cache` role, which is what Mod 094's worked `infra.yml` example now does explicitly. That works (redis is a legitimate broker) but it means `depends_on: [taskqueue]` from the design record names a role that does not exist, and a project author reaching for a queue finds no doctrine-blessed one. Adding a `queue` role is **not** in this advance's scope as planned; flagging it because the advance makes the gap much more visible than it was.

5. **What resources should a migration get? (raised in Mod 096, open.)** The migrate task definition's **env** is settled — service-level only, since the design record's rule is *"`migrate.sh`, `test.sh`, and `build.sh` may depend only on codebase-scoped env"*, which must hold on elastic too or it is not true. Its **resources** are not: `resources` is process-scoped, so a codebase-keyed migration has no natural source. Mod 096 uses the lowest-sorted non-`scheduler` process type's block as an explicitly temporary bridge. A doctrine-fixed migration sizing is probably the real answer but inventing one is above the mods' authority.

6. **Should the `iam` naming policy hash-truncate like `alb` does? (raised in Mod 096, open.)** `apply_policy(f"{global_name}_scheduler", iam)` at `hcl.py:850-853` has `max_len: 64, overflow: error`. A fourth segment can push a realistic project+env+service+process over it, turning a project that compiles today into a compile error. Mod 096 accepts the clean failure — the doctrine prefers loud failure to silent truncation — and pins it with a test plus an upgrade-guide note. But `alb` and `iam` now disagree on overflow behavior for the same underlying cause, and reconciling them is a naming-policy (i.e. doctrine) change.

7. **Is `env:` a legal authoring surface on a backing service? (found in Mod 098, pre-existing, out of scope.)** A backing service's `env:` block is scanned twice by `_validate_magic_refs` — once via `getattr(svc, "env", …)` and again through `walk_strings` over `model_extra`, because `env` is not a declared field on `BackingService`. Every magic ref in one therefore emits two identical rule-7 issues. Severity is low: such a document is *already* a compile error (`tt_rule_4_undeclared_field`), so the duplicate is noise on a failing compile rather than a wrong result. But the obvious three-line dedupe is not obviously right, because the first diagnostic asks the prior question — should a backing service be able to declare `env:` at all? That is a doctrine question, not a validator patch. Mod 098 deliberately left it and routed its fixture around it. Decide whether to close it inside 1.6.0 or file it as a follow-on.

8. **`stage` never rehearses the replica shape. (Raised in Mod 100, open.)** `shape.md` clamps `replicas` to 1 outside `prod`, so a process type that does not tolerate siblings — the exact failure § Validation and caveats warns the doctrine cannot catch — first surfaces **in production**. That is a dev/prod-parity hole in a doctrine that cites 12-factor for parity. Mod 100 implements the existing rule as written and does not touch it. Worth deciding whether `stage` should honour `replicas` too, since `stage` exists precisely to be production-equivalent.

9. **A dev Ofelia job runs image-baked code while its siblings run host code. (Raised in Mod 103, open.)** Sibling process types get the codebase's `src/` and `dist/` bind mounts in `dev`; an Ofelia-launched job runs the image as built. So editing a job's source and re-firing it shows no effect until the image is rebuilt, which will surprise someone. Giving dev jobs the bind mounts is mechanically small (Ofelia takes repeatable `volume =` lines, and mod 075's `${DOCEX_…}` pattern already solves the absolute-path problem) but is a new interpolation contract the design record does not draw. Deferred out of Mod 103 deliberately.

10. **Nothing guarantees a codebase's `dev` stage is job-runnable. (Raised in Mod 103, filed as follow-on.)** An Ofelia job in `dev` runs the `dev` stage, which every doctrinal Dockerfile bakes an artifact into but `infrastructure.md` does not *require* to. A `check` gate would close it, but that is a new doctrine surface needing both code and a rule of record in `cicd.md`. Weak priority: the failure is visible at the job's first fire, not silent.

11. **Doctrine-level: `env:` at two levels is the one exception** to the field-scoping principle. The record justifies it well, but it is the only field valid at both levels and it interacts with rule 16, rule 7's "service-level ref obliges every process", and the exec service's service-level-only rule. Confirming you want to keep that exception rather than forcing all `env:` to one level would settle three rules at once.

## Deferred

Recorded so they are not re-litigated mid-advance.

- A container-level `healthCheck` for the `web` role as well. Changes existing behavior for a marginal gain (ECS-level replacement atop ALB deregistration).
- `service.instance.id` — runtime-only values; the OTel ECS resource detector supplies them if the app opts in. A project-side option, not doctrine.
- Per-replica instance *counts* from health checks. Correct by design: health checks answer "is the boundary alive", telemetry answers "how many and how fast".
- A read-only flat-form parser to preserve rollback across the v1→v2 boundary.
