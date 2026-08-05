# Advance 005 — Process Type Solidification

The advance that finishes what CICL v2 started. 1.6.0 split a deployment from
its source tree but left three residues: the two nouns were wrong (fixed), the
relation between services was split across two fields, a "process type" that is
not a process still exists, and the elastic release's consumer reconcile is
triggered off a value that does not survive its own process.

**Target cut: `1.7.0`.** Breaking (`cicl_version` 2 → 3), shipping as a minor
per the 1.6.0 precedent. The codebase / core-service rename
([design record](./codebase_core_service_rename.md),
[plan](./codebase_core_service_rename_plan.md)) is **already landed** — mods
110–111, commit `0d937bb`. This plan covers the remaining three changes plus
close-out.

## Operator decisions (settled up front)

| Decision | Choice |
| -------- | ------ |
| Escalation mechanism | **Field radio.** Decisions exceeding a corporal's authority ripple to sarge; sarge escalates to the operator over `field_radio` and waits on a tokenless background poll. |
| Version level | **MINOR → 1.7.0.** One cut, one upgrade guide (`upgrades/upgrade_1.7.0.md` already exists as a fragment and must be completed, not replaced). |
| Service Connect empirical claim | **Verified first**, by a dedicated recon step against real AWS, before Mod C is designed. See [Step 0](#step-0--recon-the-service-connect-name-freeze). |
| `schedules:` value shape | **Bare cron strings** (`nightly_cleanup: "0 3 * * *"`). Clock record open question 1 — closed. |
| "The clock defers only" | **Doctrine prose, not a validation rule.** The compiler cannot see what a port method does; a rule it cannot enforce is a lie in the rule list. Clock record open question 2 — closed. |
| The `reaper` smoke codebase | **Deleted; the clock folds into `api` as `api.clock`.** Losing the walk's two-codebase coverage is accepted knowingly — see [Settled decisions](#settled-decisions). |
| `scheduler.md` | **Deleted and replaced by `specifics/clock.md`.** The file and its contents go, but scheduled work must remain *discoverable*: a project author needs one document that says how the doctrine expects tasks to be scheduled. |
| Execution | Full doctrine mod cycles via `mod-developer` (corporal) → `mod-implementor` (private), per `docex_process.md` step 2. |
| Doctrine edits | **Fix small, flag large** — mechanical edits the design records already specify land autonomously; anything semantic or newly-invented is escalated before it is written. |
| Manual test phase | None, per `docex_process.md` step 2.3. |
| Close-out | **STOP at ready-to-cut.** All mods + cohere + both smoke walks green, guide and changelog written, version artifacts staged. The operator performs the `RELEASING.md` cut. |

# Goals

## Goal 1: The elastic consumer reconcile is triggered off durable state

The [Service Connect Consumer Reconcile](./service_connect_reconcile_trigger.md)
step compares the post-apply namespace against a snapshot taken before the
apply. That snapshot lives in one process's memory, which makes an interrupted
release leave a permanently broken env **and exit 0**. Replace the trigger's
operands with two durable AWS facts: consumer task age and endpoint registration
age.

### Success Criteria

1. The pre-apply snapshot, and all cross-step state in `_release_elastic`, is
   deleted. `release`'s reconcile step reads only post-apply AWS state.
2. A core service is redeployed iff one of its running tasks started before the
   Cloud Map `CreateDate` of a name it `uses`. Unit tests cover: converged env
   (no redeploy), new target (redeploy), **aborted-release re-run** (redeploy —
   the case today's code gets wrong), legal `uses` cycle, and clock skew ties
   broken toward redeploying.
3. `wait_for_steady_state = true` is emitted on `aws_ecs_service`, so the
   reconcile does not read tasks that are already draining.
4. The empirical claim underneath the whole subsection — that a running Service
   Connect client cannot resolve a name registered after its task started — is
   **observed on a real stack** and the observation is recorded in the design
   record.
5. `release.md § Service Connect Consumer Reconcile` and `cicl.md § Resilience
   covers reachability, not resolvability` describe the new trigger; the "no-op
   unless the shape changed" property is restated as emergent rather than
   claimed.

## Goal 2: One relation, named `uses`; project-level startup ordering retired

`depends_on` and `consumes` collapse into a single field
([design record](./uses_relation_merge.md)). The compiler stops emitting compose
`depends_on:` / `condition:` on core-service blocks entirely — not deprecated,
removed — leaving the exec block as the single remaining emission site.

### Success Criteria

1. `infra.yml` accepts `uses:` on core services only, naming either a backing
   service (bare) or a core service (dotted, fully qualified). `depends_on:` and
   `consumes:` are hard errors, not silently-accepted aliases.
2. A backing service cannot declare outbound edges at all; it is a graph sink.
3. Rule 24 is deleted; rule 7 collapses to a single clause; rule 6 narrows to
   backing-targeted edges. The `depends_on` vs. `consumes` comparison table, and
   the explanatory paragraph that exists only to justify the split, are gone.
4. No compiled `docker-compose.yml` contains `depends_on:` on a core-service
   block. The exec block still carries `condition: service_healthy` for the
   union of its codebase's backing-service `uses` edges, and `docex migrate`
   still gates correctly on a cold stack.
5. Everything derived from the old two fields is derived from target kind
   instead: the health fan-out set, the provider set, `docex dag`'s solid/dashed
   edges, and the elastic Service Connect emission.
6. Both smoke projects' `infra.yml` carry `uses:` and `cicl_version: "3"`, and
   both compile and release green.

## Goal 3: `role: scheduler` is retired; the clock is a core service

A schedule is a property of an invocation, not of a deployment
([design record](./clock_core_service.md)). `role: scheduler` and every
carve-out it forced are deleted; `role: clock` — an ordinary long-running
singleton core service reading a compiler-delivered schedule table — replaces it.

### Success Criteria

1. `role: scheduler`, the `scheduled_task` emit destination, the Ofelia emitter
   and INI renderer, the per-service scheduler-invocation IAM role, the
   EventBridge path, and the cron-dialect translation code are **deleted**, not
   deprecated.
2. `role: clock` compiles to a compose service on fixed and to
   `task_definition` + `ecs_service` on elastic, with
   `deployment_minimum_healthy_percent = 0` / `deployment_maximum_percent = 100`
   so a rolling deploy cannot double-fire.
3. `schedules:` on a clock core service renders `infra/output/<env>/schedules.yml`
   and is delivered by the OTel sidecar's two existing paths — compose top-level
   `configs:` on fixed, a literal task-definition env entry on elastic.
4. Rules 25/26/27 lose their scheduler clauses; rule 26 is *replaced* by "a
   `clock` may not declare `replicas`" rather than added to. The `contracts.md`
   scheduler health exemption deletes.
5. The clock is subject to every ordinary core-service rule with **no
   exemptions**: it serves `GET /health` off a monotonic tick (10 s tick / 30 s
   staleness), it gets an OTel sidecar, and job telemetry stops being deferred.
6. The `reaper` codebase is deleted from both smoke projects and `api` gains
   `api.clock`, built on the clock architecture — `entrypoints/clock.py` →
   `ContJobsCron` → driving port → `Queue` port. The fixed *and* elastic walks
   show a running clock container that fires a job, defers it onto the queue,
   sees `api.worker` pick it up, and answers its own health probe.
7. `hex_overview.md`'s controller-mechanism table gains a `Cron` row.
8. `specifics/scheduler.md` is deleted and `specifics/clock.md` takes its place:
   a project author looking for "how do I schedule work" finds one document,
   and the `infra-compile` thread skill points at it.

## Goal 4: The release is coherent and proven on both foundations

### Success Criteria

1. All six `docex` artifacts are aligned — including `doctrine_excerpts/` +
   `index.yml`, the one with no automated consumer, which drifted at mod 110.
2. `cohere` passes: no dangling links, every thread-skill pointer resolves
   (three section renames in this advance are exactly what dangles a router
   link), no contradictions between the changed doctrine files.
3. `pytest tests/unit` and `pytest -m integration` are green.
4. Both smoke walks complete per `PRE_CUT_CHECKLIST.md` — **through prod release
   and teardown**, not stopping at stagetest — and both `verify_clean.sh` runs
   exit 0.
5. `upgrades/upgrade_1.7.0.md` is a complete, shippable guide: the fragment
   banner and `status:` frontmatter are gone, and every box in its own "Before
   this ships" checklist is ticked.

# Current-State Anchors

Verified against the working tree before planning. These are what each mod
lands on.

**`uses` merge**

- `CURRENT_CICL_VERSION = "2"` — `cicl/model.py:30`, one constant. The `"1"`
  rejection message (`model.py:322-329`) names `consumes` and tells the operator
  to end at `"2"`; it goes stale the moment the constant moves.
- `rollback.py` imports the constant (`:31`), aborts when a target release's
  `cicl_version` differs (`:135-146`), and hardcodes `"1"`/`"2"` prose at
  `:296-316`. **Consequence to state in the upgrade guide:** every existing
  tagged release declares `"2"`, so rollback aborts until a second v3 release
  exists — the same trap `upgrade_1.6.0.md:463-484` already documents.
- `validate.py` is the dense one: 67 hits. Rules live at `_validate_depends_on`
  (`:518-582`, rules 6 + 24), `_validate_consumes` (`:589-681`, rule 25), and
  the kind-aware `scan()` inside `_validate_magic_refs` (`:276-511`, rule 7 —
  which already branches on target kind at `:362-401` / `:447-457`, so the
  merged rule is a *collapse* of existing structure, not new machinery).
- Compose is the only emission path: `compile.py:1150-1151` writes `depends_on`
  into the body; `compose.py:756-782` rewrites it to long-form `condition:`.
  The exec gate is `compose.py:741-743`, deliberately sequenced before that
  second pass. **Delete the second pass, keep `:741-743`.**
- Elastic already discards `depends_on` (`hcl.py:845,879,915`) and enrolls every
  service in the Service Connect namespace unconditionally (`hcl.py:696-742`).
- `consumes` readers: `check.py:352-380` (provider set), `:445-460` + `:503-542`
  (fan-out + probeability), `release.py:217-259` (reconcile), `dag.py:95-100`
  + `:153-159` (edge kind → solid/dashed), `llm.py:51-54`.
- **Transfer tables: zero mentions.** Both fields are handled outside the table
  mechanism, so no role table changes.
- **`doctrine_excerpts/index.yml`: zero entries** for either relation. A `uses`
  entry is an *addition* to consider, not an edit — and this is the artifact
  that drifted at mod 110.
- Scope: 11 source files (~147 mentions), 22 test modules + 5 fixtures
  (~90–110 test functions), 13 doctrine files (~62 mentions), 1 skill
  (`skills/contracts/SKILL.md:20-21`).

**Service Connect reconcile**

- The snapshot is `release.py:452-454`, taken before *any* apply and before the
  first-release ordering swap. The diff is `_reconcile_service_connect_consumers`
  (`:264-341`, diff at `:287-290`); the predicate is `_consumer_reconcile_set`
  (`:217-261`, matching `target.global_name in new_endpoints` at `:257-259`);
  redeploy at `:305-325`; the bounded wait at `:327-340`
  (`_RECONCILE_STABLE_TIMEOUT_S = 600`, `:214`). Two call sites: `:474-479`
  (rollback path) and `:575-582`.
- `render_ecs_service` (`hcl.py:693-758`) emits **no** `wait_for_steady_state`
  and no `deployment_configuration` block — a comment at `:710-714` explains it
  relies on ECS defaults. Both this mod and the clock mod land here.
- boto3 clients are lazily constructed and cached by service name
  (`boto3_client.py:67-78`), so no new plumbing is needed. `servicediscovery
  ListServices` is already used (`:503-514`) — it returns `CreateDate`.
  `ecs DescribeTasks` is already used (`:359`); **`ecs ListTasks` is not used
  anywhere** and is the one genuinely new call.
- Tests: `tests/unit/test_service_connect_reconcile.py`, 6 tests, no markers,
  driving `_release_elastic` end-to-end against `FakeAWSClient`
  (`conftest.py:509`). **No integration coverage of this step exists.**

**Clock / scheduler retirement**

- Deletes outright: `cicl/cron.py` (211 lines, scheduler-only),
  `emit/compose.py:322-473` + the emission block at `:807-866` (Ofelia INI,
  wrapped job command, ofelia container, `test`-env suppression),
  `emit/hcl.py:976-1085` (`render_scheduled_task` + the
  `scheduler.amazonaws.com` IAM role + `aws_scheduler_schedule`),
  `orchestrate/_common.py:110-140` (`scheduler_only_services`) and its two uses
  in `up.py:214,229`, `tables/roles/scheduler.yml`, `"scheduled_task"` from
  `EMIT_DESTINATIONS` (`transfer.py:93`), and the `OFELIA_IMAGE` pin
  (`__init__.py:37-46`).
- Validation to rewrite: `_validate_scheduler_services` (`validate.py:1443-1490`),
  `rule_25_consumes_scheduler` (`:666-675`), `rule_26_replicas_on_scheduler`
  (`:1493-1525`), `_NON_WEB_ROLES` (rule 27), and the reserved `-scheduler`
  suffix in the identity-collision logic (`:789-875`).
- Tests: `test_scheduler.py` (26 tests) and `test_cron.py` (15 tests) delete
  wholesale; ~13 further modules carry scheduler assertions; two fixture
  projects (`sample_project_scheduler_{fixed,elastic}`) delete or convert.
- **The delivery mechanism the schedule table reuses already exists twice.**
  Renderer pattern: `emit/otelcol.py` (one function returning a string). Fixed:
  `compose.py:793-866` writes `configs["otelcol_config"] = {"content": ...}`
  with a `$` → `$$` escape, mounted by `_sidecar_block` (`:222-285`) — and the
  Ofelia INI already proves the same path for a *second* config
  (`configs[f"ofelia_{svc.name}"]`, `:863`). Elastic: `hcl.py:469`, a literal
  string in a task-definition env entry read via `--config=env:...`.
  **The clock's schedule table is the third user of a proven pattern.**
- Doctrine: `specifics/scheduler.md` is 286 lines and mostly deletes. Plus
  `cicl.md` (7 hits), `contracts.md:59`, `shape.md:51,81`, `networks.md:44`,
  `telemetry_infra.md:188,261,350,354`, `telemetry.md:84`,
  `transfer_tables.md:287,438,897`, `tests.md:80`,
  `projinfra/ec2_traefik.md:61`, `skills/infra-compile/SKILL.md:28`.
- **`doctrine_excerpts/`: zero scheduler entries** — nothing to delete, but a
  `clock` resource entry is a candidate addition.
- Smoke projects: `core/reaper` is 45 files / ~286 lines, byte-identical across
  both foundations, plus `masterplan.md` sections, both `CHANGELOG.md`s,
  `elastic/verify_clean.sh:206` (`aws scheduler list-schedules` leak check),
  and 8 `PRE_CUT_CHECKLIST.md` references.

# Tactical Plan

Mods are numbered from **112** (last shipped: 111). Every mod is a full doctrine
cycle — overview → `implementation.md` → `mod-implementor` execution → drift
review → tests — driven by the `mod-developer` corporal, with **no manual test
phase** per `docex_process.md` step 2.3.

Ordering rule for the whole plan: **the suite is green at every mod boundary.**

---

## Step 0 — Recon: the Service Connect name freeze ✅ COMPLETE

> **Result: the premise holds.** Measured us-east-1, 2026-08-05. A client task
> ran 27 probe cycles over five minutes after the name existed and three after
> it was backed by a healthy instance, with byte-identical `UNRESOLVED` output
> and an unchanged `/etc/hosts`; the replacement task resolved it on its *first*
> cycle. The reachability half was confirmed in the same run (scaling a provider
> 0→1 flipped a running client from 503 to 200 with no task replacement), so
> both halves of the doctrine's resolvability/reachability split are now
> observed rather than asserted. Three corrections folded into the design
> record: the name is created with the **ECS service**, not the first task
> (which makes the fix strictly *more* conservative); the `desiredCount: 0`
> alternative is refuted-but-still-rejected, now on cost rather than
> impossibility; and `ListServices` returns client bookkeeping entries that
> **must** be filtered. Full evidence in the record's § Verified.


**One-shot `private` subagent, real AWS.** Runs first and in parallel with Mod
112, because it gates Mod 114's design and nothing else.

The premise the entire reconcile subsection rests on — current design *and*
proposed — has never been observed on our own stack. Stand a minimal Service
Connect namespace with one client task; **after** that task is running, create a
second ECS service registering a new discovery name; attempt to resolve that
name from inside the already-running client. Then tear down and
`verify_clean`-style check.

Two questions, not one:

1. Does the running client fail to resolve the later-registered name? (The
   premise.)
2. Is the client's name set keyed on **task** launch or merely on the ECS
   service's Service Connect config existing in the namespace? If the latter,
   cheaper arrangements open up — though per the design record the doctrine
   should not rest on it.

Record the observation — including the loopback address range actually used —
in `service_connect_reconcile_trigger.md § Verify first`, replacing the
"untested" status line.

→ **GATE.** If the premise is *false*, the whole reconcile step is unnecessary
and Mod 114 becomes a deletion rather than a rewrite. Escalate before designing.

---

## Phase 1 — the rule of record

Per `docex_process.md` step 1, doctrine changes first. Both breaking CICL
changes share territory in `cicl.md` — the field table, the role table, the
validation-rule list, and rule 25 specifically — so they are written in **one
pass over the doctrine** rather than two. This is the Mod 094 precedent from
advance 004.

### Mod 112 — Doctrine: the `uses` relation and the clock core service
`mod-developer`. **No code. No tests.**

**Touches:** `doctrine/infrastructure/cicl.md` (the bulk),
`contracts.md`, `shape.md`, `docex.md`, `cicd.md`, `tests.md`,
`reasoning/cicl_reasoning.md`, `specifics/{migrations,transfer_tables,scheduler,telemetry_infra,networks,release}.md`,
`telemetry.md`, `specifics/projinfra/ec2_traefik.md`,
`hexagonal_architecture/hex_overview.md`, `skills/{contracts,infra-compile}/SKILL.md`.

*`uses`:* § Depends-On Relationships and § Consumes Relationships collapse into
one § Uses Relationships; the comparison table and the paragraph at `cicl.md:107`
go; rule 24 is deleted, rule 7 collapses to a single clause, rule 6 narrows to
backing-targeted edges. `cicl.md:428` — *"this is why the two relations cannot
merge"* — is the sentence this mod must directly overturn, and the replacement
argument is the design record's: the cycle rule keys on **target kind**, and a
backing service that can declare no outbound edges is structurally a sink.
The resilience clause stops being a warning attached to a feature and becomes an
unqualified requirement. `release.md:114` keeps its second clause (dynamic
sibling DNS) and drops the first (compose ordering), which becomes false.

*Clock:* new `role: clock` and `schedules:` field (bare cron strings, 5-field
UTC); rules 25/26/27 lose their scheduler clauses and rule 26 is *replaced* by
the clock singleton rule; the `contracts.md:59` health exemption deletes;
**`specifics/scheduler.md` is deleted and `specifics/clock.md` written in its
place** — short, and scoped to what a project author needs in order to schedule
work: the role, the `schedules:` field, the 5-field UTC cron format with no
dialect translation, the defer-don't-work rule, one-clock-per-codebase, and how
the schedule table reaches the container on each foundation. Deleting the old
file without a successor would leave "how do I schedule a task?" with no
discoverable answer, so every pointer moves rather than dies —
`skills/infra-compile/SKILL.md:28` most importantly.
`hex_overview.md` gains a `Cron` row in the controller-mechanism table;
"the clock defers, it does not work" and "one clock per codebase-with-schedules"
are written as prose rules, not validation rules.

→ **DECISION (operator, at design):** doctrine wording is load-bearing and
`docex_process.md` step 1.1 requires asking before altering it. The corporal
drafts, sarge reviews, and anything semantic — especially the replacement of the
`cicl.md:428` impossibility argument and the fate of `scheduler.md` — goes over
the radio before it lands.

→ Why doctrine-only, and why one mod: it is the rule the next four mods are
checked against, it is the one artifact the operator must approve by hand, and
splitting it would mean two agents editing the same three tables in `cicl.md`.

---

## Phase 2 — the `uses` merge

### Mod 113 — `uses` in the compiler; `cicl_version: "3"`
`mod-developer`. **Breaking.**

**Touches:** `cicl/{model,validate,compile}.py`, `emit/compose.py`,
`describe/{dag,llm}.py`, `pipeline/{check,release,rollback}.py`, ~22 test
modules, 5 fixture `infra.yml`s, both smoke projects' `infra.yml`.

- One `uses` field on core services only; backing services lose the field
  entirely (graph sink). `depends_on:` and `consumes:` become hard errors with
  a message pointing at `upgrade_1.7.0.md` — not silent aliases.
- Rule 7 collapses to one clause keyed on target kind, reusing the branch
  structure already at `validate.py:362-457`. Rule 24 deleted. Rule 6 narrowed.
- **Delete `compose.py:756-782` outright** — no core-service block carries
  `depends_on:` or `condition:` after this mod. **Keep `compose.py:741-743`**,
  re-derived as the union of the codebase's *backing-targeted* `uses` edges.
- `dag.py` derives solid/dashed from target kind rather than source field.
- `CURRENT_CICL_VERSION = "3"`, plus the two stale-message consequences the
  anchors call out: `model.py:322-329` and `rollback.py:296-316`.
- Both smoke projects' `infra.yml` move to `uses:` + `cicl_version: "3"` here,
  so nothing in the tree is left uncompilable between mods.

→ **GATE:** a `docex migrate` against a cold `dev` stack must still succeed.
The exec gate is now the *only* ordering emission in existence; if it regresses,
every project's first migration races its database and the failure looks like a
flaky migration rather than a compiler bug.

→ Split from Mod 114 because this is CICL territory and 114 is elastic
release-orchestration territory; and because 114 is gated on Step 0, which may
not have returned yet.

### Mod 114 — Service Connect reconcile on durable operands
`mod-developer`. Gated on **Step 0**.

**Touches:** `pipeline/release.py`, `emit/hcl.py`, `aws/{client,boto3_client}.py`,
`tests/unit/test_service_connect_reconcile.py`, `tests/conftest.py`,
`doctrine/infrastructure/specifics/release.md`, `doctrine/infrastructure/cicl.md`
(§ Resilience covers reachability, not resolvability).

- Delete the snapshot (`release.py:452-454`) and every cross-step value. Step 4
  becomes self-contained: read state, act, verify.
- New predicate: redeploy `P` iff `min(startedAt)` across `P`'s running tasks
  precedes the Cloud Map `CreateDate` of any name `P` uses. Two new port
  methods on `AWSClient` (`ecs ListTasks` is the one genuinely new API call;
  `ListServices` already returns `CreateDate`).
- **Break ties toward redeploying.** A false positive costs one rolling deploy;
  a false negative costs a permanently broken env that exits 0. Any grace
  margin favours acting.
- **Filter `aws-ecs-sc.client.<uuid>.<service>` out of `ListServices`.** Found
  by Step 0: every client-only participant gets a bookkeeping entry in the
  namespace even with an empty `services[]`. These are not endpoints, nothing
  can `uses` them, and unfiltered they make any consumer older than an
  unrelated client's entry redeploy for nothing. **Write the test for this
  before the code** — it is invisible to a fixture that only models real
  endpoints, which is exactly how it would reach the elastic walk.
- Emit `wait_for_steady_state = true` on `aws_ecs_service` so the read does not
  see draining tasks.
- The aborted-release test is the one that fails against today's code and is
  the reason this mod exists — write it first.
- The doctrine's three "properties" become two: *no-op unless the shape
  changed* is restated as **emergent**, not claimed.

→ Runs after 113 so the predicate is written against `uses` from the start
rather than written against `consumes` and immediately rewritten.

---

## Phase 3 — the clock

Additive first, break second — the same shape advance 004 used, so the suite is
green at both boundaries and the deletion mod is a pure deletion.

### Mod 115 — `role: clock` (additive; `scheduler` still present)
`mod-developer`.

**Touches:** new `tables/roles/clock.yml`, `cicl/{model,validate,compile}.py`,
new `emit/schedules.py`, `emit/{compose,hcl}.py`, tests.

- `role: clock` compiles to a compose service on fixed and
  `task_definition` + `ecs_service` on elastic — an ordinary long-running core
  service with a sidecar, a health probe, and no exemptions.
- `schedules:` (bare cron strings) renders `infra/output/<env>/schedules.yml`
  and is delivered by **the two existing sidecar paths** — the compose
  top-level `configs:` block (mind the `$` → `$$` escape at `compose.py:810`)
  and the literal task-def env entry (`hcl.py:469`).
- `deployment_minimum_healthy_percent = 0` / `deployment_maximum_percent = 100`
  on `role: clock` only, forcing stop-then-start so a rolling deploy cannot
  double-fire. Note in the code *why*: a missed fire is the accepted trade
  against a double fire, and jobs are required to be idempotent anyway.
- Validation: `replicas` forbidden on a clock; every declared job name is a
  valid identifier; cron is plain 5-field UTC with **no dialect translation**.
- The `check` step asserts every declared job name has a binding — deferred to
  Mod 117 if it needs the smoke project to have a dispatch table to read.

### Mod 116 — Retire `role: scheduler`
`mod-developer`. **Breaking. Mostly deletion.**

**Touches:** delete `cicl/cron.py`, `tables/roles/scheduler.yml`,
`tests/unit/{test_scheduler,test_cron}.py`, both `sample_project_scheduler_*`
fixtures; edit `emit/{compose,hcl}.py`, `cicl/{validate,transfer,compile}.py`,
`orchestrate/{_common,up}.py`, `docker/{client,subprocess_client}.py`,
`pipeline/{check,release}.py`, `__init__.py`, ~13 test modules.

Everything in the anchors' delete list goes. Two things to watch:

1. **`DOCEX_SECRETS_ENV_FILE`** (`up.py:236-245`, `subprocess_client.py:143-146`)
   exists solely so Compose could interpolate a path into the Ofelia INI. It
   dies with Ofelia — check nothing else grew a dependency on it.
2. **The reserved `-scheduler` suffix** in the identity-collision logic
   (`validate.py:789-875`) is a *namespace* rule, not a scheduler feature.
   Removing the role does not automatically make the suffix safe to un-reserve;
   decide deliberately.

→ Split from 115 so that at the 115 boundary the clock is proven green while the
old path still works, which makes any breakage at 116 unambiguously a deletion
error rather than a new-feature error.

---

## Phase 4 — the smoke projects

### Mod 117 — Migrate both smoke projects; complete the upgrade guide
`mod-developer`.

**Touches:** `test_projects/{fixed,elastic}/**` (core code, `infra.yml`,
contracts, `plans/core/masterplan.md`, `CHANGELOG.md`, `verify_clean.sh`,
compiled `infra/output/`), `test_projects/PRE_CUT_CHECKLIST.md`,
`docex/plans/core/test_projects.md`, `upgrades/upgrade_1.7.0.md`,
root `CHANGELOG.md`.

- **`reaper` is deleted; `api` gains `api.clock`.** The whole `core/reaper`
  tree goes from both projects (45 files each), along with its `infra.yml`
  block, its masterplan section, and its `build.sh`/`test.sh`. The nightly
  prune becomes a job on `api`'s driving port that **enqueues**, and
  `api.worker` — which already polls — performs it. This is the deferral
  contract exercised end-to-end against a schema the enqueueing codebase
  actually owns.
- **Coverage consciously dropped, and it must be written down where the walk
  will look for it.** With one codebase left, the walk stops covering the
  two-codebase shape: one image *per codebase*, two ECR repos (D.8 checks the
  count explicitly and must move to **one**), two registry repos on fixed
  (C.6), and the per-codebase `migrate.sh` / `test.sh` fan-out (C.5's "one test
  run per codebase" becomes a single run). `test_projects.md § Shape` and
  `PRE_CUT_CHECKLIST.md` both state today that `reaper` exists deliberately as
  the only scheduler coverage — both must say instead that the second codebase
  is gone and what went with it, so that a future reader does not restore it by
  accident or mistake the gap for drift.
- The clock architecture is written as the doctrine's **reference
  implementation**, since downstream projects copy this tree:
  `entrypoints/clock.py` (runtime host, bounded ≤10 s wait so the liveness tick
  is natural) → `ContJobsCron` (job name → port method dispatch) → the shared
  driving port → alogic → a `Queue` driven port. The side effect is worth
  calling out in the project's own docs: the same job is now reachable over
  HTTP and CLI, so firing a scheduled job by hand in `dev` stops being a
  special path.
- `PRE_CUT_CHECKLIST.md` updates: `cicl_version: "3"` (B.3), the core-service
  field list and the `depends_on`-names-backings item (B.3.1/B.3.2 → `uses`),
  the scheduler exemptions in B.9/B.10, the "no integration test covers a
  `scheduler`" note (now a *clock* note — and the clock **is** integration- and
  health-probeable, which is a genuine coverage gain to state), C.5/C.6/C.9 and
  D.9's "came up as a scheduled task, not a service" check, which inverts.
- `elastic/verify_clean.sh:206` drops the `aws scheduler list-schedules` leak
  check and gains nothing — one fewer AWS resource type to leak.
- **The upgrade guide becomes shippable**: fold in the `uses` migration
  interleaved with the rename's step 2 (rename first, so `uses` is authored in
  the new vocabulary), rewrite step 6's "expect exactly four differences" table
  — the byte-identical-output guarantee is the *rename's* property alone and
  `uses` breaks it by removing the compose `depends_on` emission — add the
  `scheduler` → `clock` migration, resolve the 6 dangling anchors, and delete
  the fragment banner and `status:` frontmatter.

---

## Close-out

### 1. Artifact alignment sweep
`mod-developer`, small mod (**118**) or folded into 117 at the corporal's
discretion.

All six artifacts, with deliberate attention to the sixth —
`doctrine_excerpts/` + `index.yml` — which has **no automated consumer**, drifted
at mod 110, and currently has **zero entries** for either the relation fields or
the scheduler. Decide explicitly whether `uses` and `clock` earn entries; a
decision recorded is fine, silence is not. Also fold in the two coherence items
the design records noticed in passing: the `transfer_tables.md:600-685` examples
still in the pre-`processes:` flat form that `cicl_version: "2"` already
rejects, and `docex`'s own core planning docs (`compiler.md`, `masterplan.md`,
`release_flow.md`) which four mods will have drifted.

### 2. `cohere` — doctrine coherence audit
`corporal`, one pass, **after every mod has landed** (the token-cost heuristic:
once per advance).

This advance renames three doctrine sections (§ Depends-On/§ Consumes → § Uses;
possibly deleting `scheduler.md` entirely) and a section rename is exactly what
dangles a thread-skill router link. Specifically check: `skills/contracts`,
`skills/infra-compile`, and every pointer into `specifics/scheduler.md`.

Run `project-cohere` scoped to `docex` as a second, separate pass if the
artifact sweep suggests the core planning docs drifted more than the sweep
caught — sarge's call, weighed against context cost.

### 2a. Logged drift — collected as the mods surface it

Items found mid-mod that belong to a later step. Recorded here the moment they
are found, because the mod that finds them is never the mod that owns them.

| Item | Found by | Owner |
| ---- | -------- | ----- |
| `skill_iter/eval/outcome/infra-compile/evals.json` hard-codes *"adds `cache` to web's `depends_on`"* as expected output. **Invisible to both pytest suites** — it fails only at the skills release gate, or never. | Mod 113 | Close-out, before the trigger/outcome eval question is settled |
| `transfer_tables.md` ~615/~687 still carry pre-`processes:` flat-form examples that `cicl_version: "3"` rejects. Field renamed only, per Mod 112's scope. | Mod 112 | Mod 118 |
| `doctrine_excerpts/index.yml` still has **zero entries** for either relation field or the scheduler. Whether `uses` and `clock` earn entries is an explicit decision, not an omission. | Mod 112 | Mod 118 |
| `test_projects/fixed` has no committed `infra/output/`, so "grep the compiled output" needs a fresh compile there rather than a grep of the tree. | Mod 113 | Both smoke walks |
| **`docex build` is broken by its own dev container.** `orchestrate/build.py:131` clears `dist/` host-side with `shutil.rmtree`; the dev container runs as **root** and writes `dist/__pycache__/*.pyc` owned by root on import, which the host uid cannot unlink → `PermissionError`. **Self-regenerating within a single run** — `run_up` creates the residue its own `run_build` then cannot delete, which is why clearing it by hand buys exactly one green run. Affects every doctrine project, not just the smoke seeds; `PRE_CUT_CHECKLIST.md` D.6 already documents a `sudo rm -rf` workaround, which is the tell that this has been a product bug hiding as an environment quirk. Currently the **only** integration failure (17/18). | Mod 114 | **Mod 119** — see below |

### 2b. Mod 119 — `docex build` bytecode residue (unplanned, required)
`mod-developer`, small. Runs after 116, before the walks.

Not in the original plan, and admitted deliberately rather than absorbed
silently: Goal 4 SC3 requires `pytest -m integration` green, and this is the one
failure standing in its way. It is also a real defect in shipped product code
that every downstream project inherits — the `sudo rm -rf` in
`PRE_CUT_CHECKLIST.md` D.6 has been treating the symptom.

**Preferred fix: clear `dist/` from inside the container**, where the process
that created the root-owned files can delete them. This changes `docex`
internals only. The alternatives both cost more: `PYTHONDONTWRITEBYTECODE=1` on
the dev service changes emitted output for every project, and running the dev
container as the host uid is a far larger change with its own failure modes.
Whichever lands, D.6's workaround note comes out with it.

### 3. Automated gates
`pytest tests/unit` and `pytest -m integration`, both green, before either walk.
Per `RELEASING.md § What Gates a Release`, the skills changed here
(`contracts`, `infra-compile`) also nominally call for a `skill-iteration`
trigger eval; this was waived at the 1.6.0 cut and sarge will offer the same
choice rather than assume it.

### 4. Smoke walk — `docex_smoke_fixed`
Per `PRE_CUT_CHECKLIST.md` §§ A, B, C. **Through C.9 prod release, C.10
rollback, and C.11 teardown** — not stopping at stagetest.

What this walk uniquely proves for this advance: the fixed replica unroll (as
always — nothing else exercises it); that no core-service block carries a
`depends_on` gate and the stack still converges; that `docex migrate` still gates
on a cold database through the exec block alone; and the clock's compose
`configs:` schedule delivery, its firing, and its `/health` tick.

### 5. Smoke walk — `docex_smoke_elastic`
Per `PRE_CUT_CHECKLIST.md` §§ A, B, D. **Through D.11 prod release, D.12
rollback, and D.13 teardown.**

What this walk uniquely proves: the new reconcile predicate against real ECS and
Cloud Map timestamps — including, if the walk can be arranged to allow it, the
**aborted-release re-run**, which is the failure mode the whole mod exists to
fix and which no unit test can prove against real AWS; the clock as a real
`ecs_service` with a sidecar, a task-def-delivered schedule table, and
stop-then-start deployment percentages; and that the `aws_scheduler_schedule` /
invocation-IAM-role resources are genuinely gone rather than orphaned.

→ **GATE:** `verify_clean.sh` green on both. A teardown filter left keyed on a
removed role or a renamed tag matches zero resources and fails **silently** —
the exact failure class `upgrade_1.7.0.md` already flags for the rename.

### 6. Ready-to-cut handoff
Version artifacts staged (`VERSION`, `docex/pyproject.toml`,
`docex/src/docex/__init__.py`, `.claude-plugin/plugin.json`), changelog rolled,
guide complete, `report.md` written. Sarge ends the advance and hands the
`RELEASING.md` cut — tag, image build, push — to the operator.

# Settled Decisions

**1. The `reaper` smoke-project codebase is deleted; the clock folds into `api`.**
*Operator, at plan review.*

The clock rule is that a clock **defers** onto its own codebase's queue, and
only the codebase that owns the schema may enqueue. `reaper` owns no schema — it
reaches into `api`'s `pings` table through a repo adapter — and has no worker and
no queue, so `reaper.prune` could not simply become `reaper.clock`. `api.clock`
fires a job that enqueues; `api.worker` already polls. No new backing service,
and the deferral contract is exercised against a schema its enqueueing codebase
genuinely owns.

**The two-codebase coverage is lost, knowingly.** One image per codebase, the
two-ECR-repo count check, the two-registry-repo check on fixed, and the
per-codebase `migrate.sh`/`test.sh` fan-out all stop being exercised by the
walk. Mod 117 must record this in `test_projects.md` and `PRE_CUT_CHECKLIST.md`
rather than let it read as drift — both currently say `reaper` exists
deliberately, and a future reader who finds one codebase where the doc promises
two will either restore it or distrust the doc.

**2. `scheduler.md` is deleted and replaced by `clock.md`.** *Operator, at plan
review.* The old file's contents go entirely, but the *question it answers* —
how does the doctrine expect me to schedule work? — must stay discoverable, so a
short successor document takes its place in `specifics/` and inherits its
inbound pointers. Written in Mod 112; the `cohere` pass is told to expect the
rename rather than discover it as a dangling link.

**3. `cicl_version` "3" and rollback.** Once the constant moves, every existing
tagged release declares `"2"` and `rollback` aborts until a second v3 release
exists. This is known, documented at `upgrade_1.6.0.md:463-484` for the previous
bump, and must be restated in the 1.7.0 guide. Not a blocker — a disclosure.

