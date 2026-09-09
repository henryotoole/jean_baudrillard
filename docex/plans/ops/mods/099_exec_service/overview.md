# Mod 099 — Per-codebase operations: the exec service

Phase 3 of the **service process types** advance
([plan](../../advances/004_next/service_processes_implementation_plan.md),
[design record](../../advances/004_next/service_processes_refactor.md)).
The rule of record is the design record's
[§ Per-Codebase Operations](../../advances/004_next/service_processes_refactor.md#per-codebase-operations);
its five numbered justifications are the acceptance criteria.

**One doctrine edit lands here: rule 5's text in `cicl.md`, and nothing else in
that file** — same precedent as Mod 095 adding rule 28, since Mod 106's file
list does not include `cicl.md`. Every *other* doctrine file is untouched;
`migrations.md § Dev and Test Mechanism` and `cicd.md § Build Step` both describe
`compose exec` and will read stale after this mod. That is Mod 106's, and it is
planned, not drift.

Baseline verified before design: **869 passed** (`pytest tests/unit`),
**933 passed / 17 deselected** (`pytest tests/`), **17 collected**
(`pytest -m integration --collect-only`).

## Goal

`migrate`, `test`, and `build` are per-**codebase** operations that must land in
a container. Process expansion left them picking one process type's container to
`compose exec` into, through a heuristic that is duplicated three times and
wrong at least once. This mod stops picking. The compiler emits a container that
*is* the codebase, and the three operations run one-off inside it.

Everything Mod 096 planted as a bridge for this moment comes out:
`primary_process`, `compose_service_key`, and both copies of the suffix
heuristic in `build.py`. Net line count is negative.

## What lands

### 1. One exec service per codebase, in every fixed env

`emit/compose.py` gains a per-codebase pass, keyed off `CompiledService.
core_service`, that emits exactly one block per codebase:

```yml
  myproject-dev-api-exec:
    profiles: [exec]
    image: myproject/api:0.1.0                      # codebase-keyed, == the app services'
    build: {context: ./core/api, dockerfile: Dockerfile, target: dev}   # dev/test only
    environment: {...service-level env only...}
    volumes: [./core/api/src:/service/src, ./core/api/dist:/service/dist]  # dev only
    networks: [internal]                            # union of the codebase's non-web nets
    depends_on: {myproject-dev-appdb: {condition: service_healthy}}
    labels: ["docex.project=myproject"]
```

| Field | Rule | Why |
| ----- | ---- | --- |
| key | `f"{svc.codebase_global_name}-exec"` | Reuses the compiled per-codebase name Mod 096 already computes. Same suffix precedent as `-otelcol` / `-scheduler`. |
| `profiles` | always `["exec"]` | `up` never starts it; `run` implicitly enables it. **First `profiles:` key in the codebase.** |
| `image` | the codebase's image ref | Identical to every app service of the codebase (`_image_ref` takes `svc_name`, not the compiled identity). One tag, one build. |
| `build` | `dev`/`test` only, `target: <env>` | Byte-identical to the app services' block, so Docker's cache makes the image free. `stage`/`prod` pull, exactly as their app services do. |
| `environment` | **service-level `env:` only** — `CompiledService.service_env`, `$[VAR]`→`${VAR}` translated | The rule with teeth. |
| `volumes` | `dev` only, the two doctrinal bind mounts | Mirrors the app-service rule exactly (`test` bakes artifacts in). |
| `networks` | sorted union of the codebase's non-`web` networks; key omitted when empty | The exec container is never publicly routed. |
| `depends_on` | sorted union of the codebase's `depends_on`, emitted short-form | The existing second pass rewrites it to `condition: service_healthy`. |
| `labels` | `docex.project=<label>` | Mod 051 stamps every emitted container, uniformly. |
| `container_name` | **not set** | `compose run` generates its own (`<project>-<svc>-run-<hash>`); a fixed name would be either ignored or a collision. |
| `logging` | **not set** | The container is `--rm`; there is no post-hoc log to rotate. |
| `command` | **not set** | Supplied at the call site. The core-service Dockerfiles declare no `ENTRYPOINT`, so `run --rm …-exec ./migrate.sh` executes the script directly under `WORKDIR /service`. |

Emitted for **every** codebase, including a scheduler-only one — which today
produces *zero* compose services in `test` and will now produce exactly one.

Emitted in **all four** fixed envs, not just `dev`/`test`. See
[§ Why stage/prod too](#why-stageprod-too).

### 2. The three operations route through it

`DockerClient.compose_run_one_off` (`docker/client.py:81-99`) has existed with
zero call sites since Phase 3 planning; its docstring says it was built for this.
Wire it, and add `-T` to the subprocess implementation to match `compose_exec`'s
non-interactive contract (`run` allocates a TTY by default; `exec` already
passes `-T`).

| Call site | Was | Becomes |
| --------- | --- | ------- |
| `migrate.py:102` (dev/test) | `compose_exec(key, ./migrate.sh)` | `compose_run_one_off(exec_key, ./migrate.sh)` |
| `test.py:121` (test migrate) | `compose_exec` | `compose_run_one_off` |
| `test.py:144` (test.sh) | `compose_exec` | `compose_run_one_off` |
| `up.py:238` (post-up migrate) | `compose_exec` | `compose_run_one_off` |
| `build.py:150` (build.sh) | `compose_exec` | `compose_run_one_off` |
| `playbook.yml.j2:53` (fixed stage/prod migrate) | `run --rm <app-svc> /service/migrate.sh` | `run --rm <exec-svc> /service/migrate.sh` |
| `up.py:158` (`_diagnose_unhealthy`) | `compose_service_key` per codebase | iterate the status map — see below |

### 3. Deletions

- **`primary_process`** (`cicl/model.py:214-242`) and its three consumers:
  `_common.py:196`, `migrate.py:350`, `compile.py:921`.
- **`compose_service_key`** (`_common.py:142-166`), replaced by
  `exec_service_key`.
- **Both** copies of the suffix heuristic in `build.py` (`:109` via the shared
  function, `:122-126` the `matching[0]`-off-a-`set` copy).
- **`_build_one`'s per-service "is this container running" gate and its
  crash-loop diagnostic** (`build.py:113-134`).

  **Mod 050 Gap D's intent is deliberately retired here — this is a decision,
  not an oversight.** Recorded for whoever bisects to this commit: the gate had
  to go mechanically, because the exec service is never in `running` by
  construction and keeping the gate would break `build` outright. But it should
  go on its own merits too. The diagnostic refused to run `docex build` when the
  dev container was `restarting`/`unhealthy`, and the most common cause of a
  crash-looping dev container is an empty `dist/` — which is exactly what
  `docex build` fills. The guard was pointed the wrong way: it blocked the one
  command that resolves the state it was detecting. Under `compose run` the
  dev container's health is simply irrelevant to refreshing `dist/`, so there is
  nothing left to diagnose at this call site. If a future reader wants the
  diagnostic back, the place for it is `_diagnose_unhealthy` (which this mod
  improves), not a precondition on `build`.

  The whole-stack `if not running: raise EnvNotRunning` at `build.py:69` stays,
  because `cicd.md § Build Step` step 1 still says "verify dev is running" and
  that text is Mod 106's to revisit.

`exec_service_key(ctx, env, codebase)` **constructs** the key rather than
scanning for it: `codebase_global_name(project, env, codebase, policy)` plus
`-exec`, then asserts the key is present in the emitted compose file and raises
a clear "run `docex compile`" error if not. Construct-then-verify, so there is
no suffix match to mis-resolve and no silent fallback to the bare name. The
naming derivation is exported from `cicl/compile.py` and shared with
`migrate.py::_migration_task_family`, which is how `primary_process` leaves that
file: the policy is resolved from the codebase's process types with an
agreement check, not by picking one.

`_diagnose_unhealthy` stops deriving keys at all and instead reports every entry
in the `compose_ps_status` map whose state is in `_DIAGNOSTICS`. Strictly better
than today: it currently iterates *core* codebases only, so an unhealthy
postgres — the single most likely reason `up` fails — was invisible to it.

### 4. Elastic: the migrate task definition becomes a per-codebase pass

Mod 096 kept one migrate family per codebase by setting `schema_owned_by_db` on
a single **carrier** process type chosen by `primary_process`, and emitting the
`_migrate` block inside the per-process `render_task_definition`
(`hcl.py:519-580`). With `primary_process` gone, the carrier goes with it:

- `schema_owned_by_db` becomes an honest codebase property — set on **every**
  process type of a schema-owning codebase.
- The `_migrate` block moves out of `render_task_definition` into a new
  `render_migration_task_definitions(compiled, ctx)` that groups
  `compiled.services` by `core_service` and emits one block per schema-owning
  codebase. Rendered into `main.tf.j2` after the per-service loop.
- Family `{codebase_global_name}-migrate` and resource address
  `{core_service}_migrate` are **unchanged**, so `migrate.py:351` and
  `release.py:401` stay valid and `release.py` needs no edit.
- `emit/ansible.py` groups by codebase the same way and hands the playbook
  `(codebase, exec_service_key)` pairs instead of carrier `CompiledService`s.

A shared `group_by_codebase(compiled)` helper serves all three emitters
(`compose.py`, `hcl.py`, `ansible.py`) so the grouping rule exists once.

### 5. Rule 5's uniqueness domain grows to cover compiler-emitted derivatives

`cicl.md` rule 5 text plus `_validate_rendered_identity`. Argued under
[§ Decisions taken](#decisions-taken) — it closes three pre-existing holes as
well as the one this mod would otherwise open.

## The open design question: what resources should the migration get?

**Recommendation: the per-dimension maximum across the codebase's process
types**, taken over the already-Fargate-tiered `body["cpu"]` / `body["memory"]`
values, applied to the migrate task definition only. On fixed there is no
question to answer at all (below).

### Why max, and not the bridge

Mod 096's bridge — lowest-sorted non-`scheduler` — has a defect that is worse
than arbitrariness: **it is not stable under edits that have nothing to do with
migration.** Rename `api.web` to `api.zweb` and the migration resizes. Add an
`api.admin` process type with modest resources and the migration silently
shrinks. Both are silent, both are action-at-a-distance, and neither is
detectable from the migration's own declaration, because it has none. A sizing
rule that changes when an unrelated process type is renamed is not a rule.

Max fixes exactly that and nothing else:

- **Order-independent and rename-stable.** `max` is commutative; sort order is
  irrelevant, so the whole class of defects above disappears.
- **Never under-provisions.** The migration gets at least what the largest
  sibling gets, so the OOM risk that motivated "non-scheduler first" cannot
  occur — which in turn lets the rule drop the `scheduler` carve-out and become
  "max over *all* process types", one clause with no exceptions.
- **Zero diff for the common case.** A single-process codebase's max is that
  process's value, i.e. exactly what is emitted today. Only a multi-process
  schema-owning codebase moves, which is a shape that does not exist yet.
- **The pair is always valid — and here is why, because a later refactor can
  break this by taking the max of a *pair* instead of per-dimension.** Fargate
  admits a discrete set of `(cpu, memory)` tiers in which both the floor and the
  ceiling of the allowed memory range are monotone non-decreasing in cpu
  (256 → 512..2048; 512 → 1024..4096; 1024 → 2048..8192; 2048 → 4096..16384;
  4096 → 8192..30720; and so on). Each input pair is already a valid tier. Take
  the maxima per dimension:

  - *Ceiling.* `max_mem` came from some process whose cpu was ≤ `max_cpu`, and
    it was within that process's allowed range, so it is ≤ that cpu's ceiling
    ≤ `max_cpu`'s ceiling (monotone).
  - *Floor.* The process that supplied `max_cpu` had memory ≥ `max_cpu`'s floor,
    and `max_mem` ≥ that memory, so `max_mem` ≥ `max_cpu`'s floor.
  - *Granularity.* Above 256 cpu units, memory steps in 1 GiB increments and
    every input is already a multiple; at exactly 256 every process has cpu ≤ 256
    so `max_mem ∈ {512, 1024, 2048}`, which is that tier's whole allowed set.

  So `(max_cpu, max_mem)` is an allowed tier. **This argument depends on the max
  being taken per dimension** — max over pairs under any single ordering does not
  give it. Passing the result back through `fargate_pair_from_units` costs one
  line and converts the argument into an enforced guarantee, which is the point:
  the proof is why the assertion never fires, not a substitute for it.
- **Cost is not an objection.** A migration is one task, for seconds to minutes,
  once per release. 4 vCPU / 8 GB for the 1-minute Fargate minimum is under a
  cent. Over-provisioning a short-lived one-shot is the cheap direction to err.

Taking the max over the **tiered** values rather than recomputing from the raw
`Resources` blocks is deliberate: it keeps the single-process case byte-identical
and avoids a second resource-resolution path. It inherits the app container's
0.1 vCPU / 128 MiB sidecar padding, which the migrate task does not actually
run — a small over-allocation in the same direction as max itself.

### The two alternatives, and why not

**A doctrine-fixed migration sizing** is the cleanest *semantically* — a
migration is its own workload and its sizing has nothing to do with any process
type — but it collides with a settled convention. Settled convention #4 fixes
the service level at `{processes, secrets, config, env}`, so there is nowhere to
put an override, and a non-overridable constant is a hard ceiling on data
backfills. It is also the invention of a number, which is doctrine. **If the
operator prefers this, it is theirs to take, not mine** — and it should be taken
together with whether `migration_resources:` earns an exception to #4.

**Keeping the bridge for elastic only** is the status quo with a new name. It
preserves the rename instability for the sole benefit of not writing five lines.

Max, by contrast, is a *derivation* over declared fields — the same kind of
thing the design record already settles for image refs and hostnames — so it is
inside a mod's authority. Flagged-for-operator #5 can be closed by it.

## What the exec service does and does not replace {#which-half}

The C.O. asked which half of "the exec service replaces the bridge" is true.
Precisely:

| Half | Replaced? |
| ---- | --------- |
| **Container selection** — "which container stands in for this codebase" | **Fully.** On fixed, in all four envs, the answer is the exec service. `compose_service_key` and `primary_process`'s second consumer die outright. |
| **Migration sizing** — "what `cpu`/`memory` does the migration get" | **Not at all.** The exec service is a compose service and Compose imposes no required sizing, so on fixed the question is not answered, it is *dissolved*. The elastic migrate task definition is a Fargate task; `cpu` and `memory` are mandatory, the exec service does not exist on elastic, and nothing about it bears on the number. That half needs a real rule, which is the section above. |
| **Naming-policy resolution** — `_migration_task_family`'s third use of `primary_process` | **Neither; it evaporates.** It was only ever an artifact of the carrier design. Once the migrate task def is a per-codebase pass, the policy is a codebase property with an agreement check across its process types. |

## Why stage/prod too

The design record cites fixed stage/prod migrate — already a one-off container
via ansible — as *precedent* for the exec service rather than as something to
change. But justification #2, the one that makes the env-scoping boundary
enforceable, does not survive being applied to `dev`/`test` only. The playbook
today runs `compose run --rm <carrier-app-service> /service/migrate.sh`, so
fixed production migration reads the carrier process type's `env:` overlay —
the exact trap the exec service exists to close, left open in the one
environment where it costs the most. Routing the playbook through the exec
service makes *`migrate.sh` may depend only on codebase-scoped env* true
everywhere on fixed, and deletes the carrier's last consumer in `ansible.py`.

The cost is one inert service block in the stage/prod compose files. It carries
`image:` and no `build:`, exactly like the app services beside it.

## The seam Mod 103 needs

Mod 103 deletes `_run_scheduler_tests` (`test.py:40-63`) on the grounds that the
exec service dissolves the scheduler carve-out. This mod does **not** delete it
— that is 103's — but it must leave the seam clean, which means:

1. **The exec service is emitted for a scheduler-only codebase**, in `test`,
   with `build: {target: test}`. Because the emission pass groups
   `compiled.services` by `core_service` — *before* `compose.py`'s
   `if svc.role == "scheduler": continue` skip — a scheduler-only codebase gets
   its block even though it contributes no app container. This mod pins that
   with a test.
2. **`services_with_schema` + `run_migrate` already work for one**, because the
   exec service's `depends_on` union and network union are computed from the
   codebase's process types regardless of role.
3. The only thing left for 103 is to delete the branch at `test.py:141-146` and
   `_run_scheduler_tests` with it, and to let the loop take the same path. The
   scheduler-only branch stays untouched here so the two diffs stay separable.

`_ensure_scheduler_image` and the mod-074 self-contained job image are
untouched; retiring them is also 103's.

## Behavior changes worth naming

1. **`compose run` starts dependencies.** `migrate`/`test`/`build` now gate on
   `condition: service_healthy` for the codebase's backing services, and will
   start them if they are down. This is the design record's "free side benefit"
   — dev/test migrate stops assuming the stack is already up — but it is a real
   change: `docex migrate dev` against a torn-down stack now brings the database
   up instead of failing.
2. **~1 s container-start latency** per operation instead of `exec` into a warm
   container. Accepted in the design record.
3. **`docex build` no longer requires the target codebase's container to be
   running** (only that *something* in the dev stack is). See deletion 3.
4. **A process-level `env:` key is no longer visible** to `migrate.sh`,
   `test.sh`, or `build.sh`. This can break a project that relied on it — it is
   the intended break, and it is upgrade-guide material for Mod 107.
5. **The elastic migrate task definition's resources change** for a
   multi-process schema-owning codebase (see above). Single-process codebases
   are byte-identical.

## Test plan

Minimum set, per the C.O.'s list plus what the design demands:

**Emission** (`tests/unit/`, new `test_exec_service.py`):
1. Exactly one exec service per codebase, key `{project}-{env}-{cb}-exec`, for a
   three-process codebase.
2. `profiles: ["exec"]` present; no other emitted service `depends_on` it.
3. Carries service-level env. **Plant a process-level `env:` key** on one
   process type and assert it is absent from the exec block while present on
   that process's own block — the same proof shape Mod 096 used for migrate.
4. `build.context`/`target` in `dev` and `test`; `image` and **no** `build` in
   `stage`/`prod`; `image` equals the app services' image in all four.
5. Bind mounts in `dev`, absent in `test`.
6. `networks` is the union of non-`web` nets and never contains `web`.
7. `depends_on` rewritten long-form to `condition: service_healthy` on the
   codebase's backing services.
8. Scheduler-only codebase: exec service emitted in `dev` and `test`, and is the
   *only* service that codebase contributes to `test`.

**Resolution** (`tests/unit/test_orchestrate_common.py` or new):
9. **The wrong-container bug is gone.** A project with a codebase literally
   named `web` (process `web`) alongside `api` (process `web`): assert
   `exec_service_key(ctx, "dev", "web") == "{p}-dev-web-exec"` and that nothing
   resolves to `{p}-dev-api-web`. This is the live bug being retired.
10. `exec_service_key` raises a clear error when the compose file lacks the key
    (never silently returns the bare name).

**Routing** (fake `DockerClient`, `tests/conftest.py` already records
`compose_run_one_off` calls):
11. `run_migrate` dev/test issues `compose_run_one_off(exec_key, ["./migrate.sh"])`
    and **zero** `compose_exec` calls.
12. `run_test` issues both `./migrate.sh` and `./test.sh` through the exec key.
13. `run_build` issues `./build.sh` through the exec key and still clears + asserts
    host `dist/`.
14. `run_up`'s post-up migrate goes through the exec key.

**Elastic** (`tests/unit/test_hcl_emitter.py`, `test_process_expansion_emit.py`):
15. Exactly one `aws_ecs_task_definition."<cb>_migrate"` for a three-process
    schema-owning codebase; family is `{codebase_global_name}-migrate`.
16. Resources are the max across the codebase's process types; a single-process
    codebase's emitted HCL is unchanged from the pre-mod snapshot.
17. Migrate container env is `service_env` (the planted process-level key is
    absent) — Mod 096's test survives the hoist.

**Fixed stage/prod** (`tests/unit/test_ansible_emit.py`):
18. Playbook emits one migrate task per schema-owning codebase, targeting the
    exec service key.

**Rule 5** (`tests/unit/test_validate*.py`):
19. A process type named `exec` on codebase `api` collides with `api`'s exec
    service and is rejected; likewise `otelcol` (sidecar), `scheduler` (Ofelia),
    and `migrate` (task definition) — the three pre-existing holes.
20. A codebase named `api-exec` with a process named `x` does **not** collide
    with codebase `api`'s exec service (`api-exec-x` vs `api-exec`), so the rule
    is not over-eager.
21. All four fixtures and both `test_projects` still compile.

**Deletion pins:**
22. `primary_process` and `compose_service_key` are gone (import fails / not in
    `dir()`), so nothing quietly grows a fourth consumer.

**Collection:** `pytest -m integration --collect-only` must still collect 17.

### Integration tests that will exercise stale paths

Cannot be run here (they need docker/AWS), but they hit the changed code and
should be re-run before the cut:

| Test | Why |
| ---- | --- |
| `test_migrate_real.py::test_migrate_dev_creates_health_table` | The headline path: `exec` → `run` against a new service. |
| `test_build_real.py::test_build_refreshes_dist_after_src_edit` | Depends on the exec service carrying the dev bind mounts, and on the deleted per-service running gate. |
| `test_test_real.py::test_docex_test_passes_and_tears_down` | Both `migrate.sh` and `test.sh` reroute; also the first real check that `up` does not start a `profiles:`-gated service. |
| `test_up_down_real.py::test_up_then_down_dev` | Post-up migrate reroute; `down` must not be confused by the never-started exec service. |
| `test_check_real.py` (both) | `run_test` under a worktree `project_dir` — `compose run` must resolve the `build:` context relative to `--project-directory` the same way `up` does. |
| `test_stagetest_real.py::test_stagetest_against_local_dev` | Runs against a dev stack brought up with the new compose output. |

`test_containerize_real.py`, `test_merge_real.py`, `test_hcl_validate_real.py`
and `test_check_hcgate_real.py` are unaffected in mechanism, though
`test_hcl_validate_real` will validate the relocated migrate blocks.

## Out of scope

Replica emission (100) · `check.py` gates (101) · telemetry (102) · ofelia
rework and `_run_scheduler_tests` (103) · `describe`/preinfra (104) · rollback
(105) · **any doctrine file** (106) · any version artifact (107).

`describe` needs nothing: the exec service is emitter-only and never becomes a
`CompiledService`, so it does not appear in the DAG. That is correct — it is
tooling, not topology.

## Decisions taken

Both questions raised at design time were resolved by the C.O. before
implementation. Recorded here so the mod reads as settled.

1. **Migration sizing — per-dimension max.** Approved as recommended. The
   Fargate-validity property is now argued above rather than asserted, because
   it is precisely the kind of invariant a later refactor breaks by taking the
   max of a pair instead of per dimension.
2. **Rule 5's domain is extended; rule 14's reserved list is not grown.**
   Approved, and it lands **here**, both halves — doctrine text first, then the
   validator. See below.

### Rule 5 grows to cover compiler-emitted derivatives

Rule 5 requires the rendered data-plane identity of every emitted service to be
unique across core process types and backing services. It does not cover the
suffixes the *compiler* appends. A core service `api` with a process type named
`exec` renders `api-exec`, byte-identical to the exec container emitted for the
`api` codebase — same compose key, one silently clobbering the other.

**The value here is larger than the one suffix this mod adds, because the hole
is pre-existing.** A process named `otelcol` collides with a sibling's collector
sidecar, and one named `scheduler` collides with a sibling's Ofelia trigger,
*today*, unguarded, on both foundations. `-migrate` is exposed too: a process
named `migrate` on codebase `api` renders `api-migrate`, whose HCL resource
address `aws_ecs_task_definition.api_migrate` is the migration task definition's
own address. This mod is the occasion, not the cause.

Rule 5 rather than rule 14 for three reasons: it is **collision-based, not
name-based**, so it covers every current suffix *and* every future one with no
further edit; it continues exactly the widening Mod 096 already performed (core
process types **and** backing services); and it does not forbid a name that
happens to be harmless in a project where nothing collides with it. Growing a
reserved list means re-growing it every time the compiler learns a suffix.

Two halves, both here:

- **Doctrine.** `cicl.md` validation rule 5's text, and nothing else in that
  file.
- **Implementation.** `_validate_rendered_identity` (`validate.py:778-816`) is
  already bucket-shaped, so this is additive: seed the buckets with
  `{compiled}-otelcol` / `{compiled}-scheduler` per process type and
  `{codebase}-exec` / `{codebase}-migrate` per codebase, labelled as
  compiler-emitted so the error message says *which* derivative collided rather
  than naming a service the author never wrote.

**Collision sweep run before implementation**, per the C.O.'s condition — the
four fixtures (all already CICL v2) and both `test_projects` are clean:

| Project | Shape | Identities | Collisions |
| ------- | ----- | ---------- | ---------- |
| `sample_project`, `sample_project_elastic` | v2, `api.web` + `appdb` | 5 | none |
| `sample_project_scheduler_{fixed,elastic}` | v2, `api.web` + `nightly_cleanup.*` + `appdb` | 9 | none |
| `test_projects/{fixed,elastic}` | **still v1** (Mod 107 migrates them); `web` / `worker` / `reaper` + `appdb` / `probe` / `events` | 9 | none |

The smoke projects were also checked against their *prospective* v2 shape
(`web.web`, `worker.worker`, `reaper.<job>`), which is likewise collision-free.
Nothing needs renaming out from under Mod 107, so there is nothing to stop and
raise.
