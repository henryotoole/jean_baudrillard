# Mod 112 — Doctrine: the `uses` relation and the clock core service

**Advance:** 005 — Process Type Solidification. **Phase 1 — the rule of record.**
**Scope:** doctrine prose and thread skills only. **No code. No tests. No version artifacts. No upgrade guide.**

This mod writes the rule of record for the two remaining breaking CICL changes of
advance 005. Mods 113–117 are checked against what lands here. Both changes share
territory in `cicl.md` — the sample `infra.yml`, the Service Fields table, the
role/naming note, and the validation-rule list (rules 5, 6, 7, 21, 24, 25, 26,
27) — so they are written in one pass rather than two, per the Mod 094 precedent.

Design sources:
[`uses_relation_merge.md`](../../advances/005_process_type_solidification/uses_relation_merge.md)
(settled, no open questions) and
[`clock_core_service.md`](../../advances/005_process_type_solidification/clock_core_service.md)
(both open questions closed by the operator at plan review). Where the records
lag the tree — they predate the codebase / core-service rename of mods 110–111 —
the current text wins and the record's *intent* is carried across.

---

## Part A — one relation, named `uses`

### A.1 What changes in the language

`depends_on` and `consumes` collapse into a single field, `uses`, declarable
**only on core services**. A `uses` entry names either:

- a **backing service**, bare (`database`), or
- a **core service**, dotted and fully qualified (`api.worker`).

Backing services lose the field entirely. They declare no outbound edges, which
makes a backing service a **graph sink** — the structural fact the merged cycle
rule rests on. Where an engine genuinely needs another container beneath it, that
belongs in the engine's `defaults.fixed` block in its transfer table: which
containers an engine requires is an engine concern, not a project one.

Project-level startup ordering stops being a doctrine feature. The compiler emits
no compose `depends_on:` / `condition:` on a core-service block at all. The
**per-codebase exec block keeps its gate**, derived from the union of the
codebase's *backing-targeted* `uses` edges — the same derivation as today, a
different source word. That is not a carve-out; it is the last remaining emission
site, and no project declares it or can rely on it.

### A.2 `cicl.md` — the bulk

| Location | Change |
| --- | --- |
| Sample `infra.yml` (lines 60–82) | Three `depends_on:` blocks and two `consumes:` blocks become `uses:` lists; the `nightly_cleanup` scheduler block is rewritten by Part B. |
| § Core Services field-scoping snippet | unchanged structurally; vocabulary only. |
| § Service Fields table, rows `depends_on` + `consumes` | Two rows → one `uses` row. Scope narrows to **core service**. Description: names a backing service (bare) or a core service (dotted). Link → `#uses-relationships`. |
| § Depends-On Relationships | **Collapses into** § Uses Relationships. Its readiness prose reduces to one line about the exec block. |
| § Consumes Relationships | **Becomes** § Uses Relationships (the surviving section, in the Depends-On section's file position). |
| The `depends_on` vs. `consumes` comparison table (line 419) | **Deleted** — one field has nothing to compare against. |
| The explanatory paragraph at line 107 / § Core Services adjacent prose | **Deleted** where it exists only to justify the split. |
| #### The graph may contain cycles (line 428) | **Rewritten.** See [A.3](#a3-overturning-the-impossibility-argument). |
| #### Three clarifications | Survives verbatim in substance; `consumes` → `uses` throughout. |
| § Resilience covers reachability, not resolvability | Vocabulary only in this mod. Mod 114 rewrites the trigger prose; Mod 112 does not touch it beyond the field name. |
| § Magic Refs / implied-edge sentence | Vocabulary. |
| § CICL Version | `"2"` → `"3"` (ruling Q6); the v1-rejection rationale generalizes to "previous generations". |
| Validation rules | See below. |

**Validation-rule ledger** (the table Mods 113–117 are checked against):

| Rule | Fate |
| --- | --- |
| 5 (identity collision) | The illustrative derivative list loses `-scheduler` (ruling Q4). |
| 6 (no `depends_on` cycles) | **Retired** (ruling Q1). Once backing services declare no outbound edges they are structurally sinks, so acyclicity across backing-targeted edges is a consequence of the graph's shape and no rule states it. Tombstoned, not removed — see [Rule numbering](#a21-rule-numbers-are-stable-identities). |
| 7 (magic refs imply an edge) | **Collapses** from a bifurcation ("an edge of the kind the target calls for") to one clause: a magic ref must be matched by a `uses` entry on the referencing core service. The *not-applying* case for a backing-service referencer survives and gets simpler: backing services declare no edges at all. Its reference to rule 24 goes with rule 24. |
| 21 (`cicl_version` is `"2"`) | → `"3"` (ruling Q6). |
| 24 (`depends_on` names only backing services) | **Retired.** Tombstoned. |
| 25 (`consumes` names only core services…) | **Rewritten** as the `uses` shape rule: a target is either a bare backing-service name or a dotted `<codebase>.<service>`; a bare codebase name is an error; a core service may not use itself. Its scheduler clause deletes (Part B). |
| 26 (`replicas` not on a `scheduler`) | **Replaced** by Part B. |
| 27 (`worker`/`scheduler` not on `web`) | → *"`worker` and `clock` core services do not declare `web` in `networks`."* (ruling Q3). |

#### A.2.1 Rule numbers are stable identities

Two rules retire in this mod. The validation rules are a markdown **ordered
list**, so removing items 6 and 24 from the source silently renumbers all 28 —
and rule numbers are load-bearing well outside this file: doctrine
cross-references, `PRE_CUT_CHECKLIST.md`, `docex`'s `ValidationIssue.rule` ids
(`rule_7_…`, `rule_25_…`), and the tests asserting on those ids.

The doctrine has no existing convention for a retired rule (checked: no
"retired" / "deprecated" / "no longer applies" language anywhere in `doctrine/`).
This mod establishes one. A short note above the list states that rule numbers
are stable identities and a retired rule keeps its number, and each retirement
leaves a **one-line tombstone** in place recording that it was retired in 1.7.0
and why. Numbering stays stable and the retirement is documented rather than
inferred from a gap.

Backing services being unable to declare `uses` is carried by the Service Fields
table's **scope column** plus the standing sentence *"`./bin/docex compile` will
always fail loudly when a field is placed in the wrong scope"* — no new numbered
rule. This is the same way every other core-service-only field is enforced, and
adding a rule would be inventing one the records do not specify.

### A.3 Overturning the impossibility argument

`cicl.md:428` currently argues the merge is impossible:

> There is one DAG (`depends_on`) and one cyclic digraph (`consumes`); no single
> field could carry a cycle rule that is simultaneously fatal and fine.

This mod must directly overturn it — leaving the old argument standing beside the
new field is the worst outcome. **Approved replacement** (ruling Q1; the argument
ends on the structural claim, with no appeal to a surviving rule 6):

> #### The graph may contain cycles
>
> `api.web` enqueues a job; `api.worker` posts the result back to `api.web`'s
> internal API. So `web` uses `api.worker` *and* `worker` uses `api.web`. That is
> a cycle, it is the most common web/worker topology in existence, and it is
> entirely fine — interfaces may be mutually referential.
>
> One field carries the whole relation because the cycle rule keys on **target
> kind**, which the compiler knows for every edge: a cycle among core-service
> targets is legal, and a cycle through a backing-service target would be a
> startup deadlock. The second case cannot arise. A backing service declares no
> `uses` edges at all, so no path leaves one — it is a graph **sink**, and a sink
> cannot sit in a cycle. Acyclicity across backing-targeted edges therefore falls
> out of the shape of the graph rather than being enforced against it.

### A.4 The resilience clause gets stronger

Today the mandate reads as a warning attached to a feature — *here is a readiness
gate, do not trust it*. With the gate out of project scope entirely it becomes an
unqualified requirement, and the 12-factor grounding is stated directly: a
silently-emitted gate would make `dev` and `test` systematically **more
forgiving** than elastic `prod`, concealing exactly the bug class the mandate
exists to catch. The accepted cost — a burst of connection-refused lines on
`envinfra up` while backing services initialize — is named as acceptable signal,
with a pointer to [`logging.md`](../../../../doctrine/practices/logging.md) for
where that class of output belongs.

The exec block's retention is justified in place: `migrate.sh` / `test.sh` /
`build.sh` are one-off batch jobs whose entire contract is an exit code, and for
a batch job "be tolerant" *means* "wait until ready". Relocating that into
`docex` or into every project's shim costs more than the emission it replaces.

### A.5 Peripheral `uses` edits

| File | Change |
| --- | --- |
| `contracts.md:9,21` | Provider set → `(core-service `uses` targets) ∪ (`web`-network core services)`. Vocabulary + anchor. |
| `contracts.md:63–69` | Fan-out set → core-service-targeted `uses` edges, restricted to targets not on `web`. The paragraph at 69 is **cut to one sentence** (ruling Q7) preserving the surviving observation — a dead consumer is invisible from outside because requests keep returning 200 while work piles up behind them — and dropping the archaeology of the split and the rule-24 parenthetical. |
| `contracts.md:71` | Anchor + vocabulary (the legal `web ↔ worker` cycle). |
| `release.md:100` | Vocabulary + anchor. |
| `release.md:114` | **First clause dropped**, second kept: "Fixed foundations need none of this. Docker network DNS resolves a sibling container whenever it exists, with no per-task snapshot." Compose ordering is no longer emitted, so the first clause becomes false; dynamic sibling DNS was always the real reason. |
| `migrations.md:48,71` | Exec gate derivation → "the union of the codebase's `uses` edges whose target is a backing service, rewritten to `condition: service_healthy`"; at 71, "readiness gates" rather than "`depends_on` gates". |
| `transfer_tables.md:320,331` | `# depends_on comes from infra.yml` comments → `uses`. |
| `transfer_tables.md:615,687` | `depends_on:` → `uses:` in the walking examples. (These blocks are *also* still in the pre-`processes:` flat form; that defect is **Mod 118's**, per the advance plan close-out. Renaming the field here does not fix or worsen it — flagged so it is not lost.) |
| `transfer_tables.md:818` | The compose-`depends_on` emission rule is **scoped to the exec block alone**. The long-form / `service_healthy` derivation survives verbatim; only its applicability narrows. |
| `docex.md:67` (`dag`) | Solid/dashed edge kinds derived from **target kind** rather than from which field the edge came from. Anchors repoint. |
| `docex.md:159` (`check`) | `consumes`-to-contract alignment → `uses`. |
| `cicd.md:58,59,61` | Vocabulary + anchors. |
| `shape.md:121` | Example `depends_on: [database]` → `uses: [database]`. |
| `cicl_reasoning.md:20` | Field-scoping table cell `` `depends_on`, `consumes` `` → `` `uses` ``. |
| `tests.md:71,80` | Vocabulary + anchors. Line 80 is also touched by Part B — see [B.7](#b7-the-clocks-stagetest-blind-spot). |
| `infrastructure.md:253–258` | **Resident stratum.** Vocabulary + anchor only; the provider/consumer example survives intact, now as *derived* vocabulary rather than a field name. |
| `skills/contracts/SKILL.md:20–21` | Rewritten: relationships are declared via `uses`; the "`depends_on` is a separate relation" sentence deletes. |

Every `#depends-on-relationships` and `#consumes-relationships` anchor in the
tree repoints to `#uses-relationships`. There are 13 such links across 8 files;
they are enumerated in `implementation.md`, not left for the `cohere` pass.

---

## Part B — the clock core service

### B.1 What changes in the language

`role: scheduler` is deleted — not deprecated. `role: clock` replaces it: an
**ordinary long-running singleton core service**, one per codebase that has
scheduled work, whose `command` invokes a clock entrypoint. It is a container on
both foundations: a compose service on fixed, `task_definition` + `ecs_service`
on elastic.

`schedule:` (singular, a cron string on a scheduler service) is replaced by
`schedules:` — a map of job name → **bare 5-field UTC cron string**, declared on
a clock core service:

```yml
clock:
  role: clock
  command: ["python", "-m", "entrypoints.clock"]
  port: 8080
  health_check_path: /health
  networks: [internal]
  uses: [appdb, api.worker]
  resources: { cpu: 0.25, memory: 512MB }
  schedules:
    nightly_cleanup: "0 3 * * *"
    hourly_rollup:   "0 * * * *"
```

There is **no dialect translation**. With EventBridge gone, both hazards the old
doctrine documented — the 6-field `?`-day form and EventBridge's Sunday-is-1
renumbering — disappear. The clock is project code reading a plain expression.

The compiler renders `infra/output/<env>/schedules.yml` and delivers it by the
OTel sidecar's two already-proven paths: the compose top-level `configs:` block
on fixed, a literal string in a task-definition env entry on elastic.

### B.2 Every carve-out dies

The clock is genuinely long-running and loop-owning, so it falls under existing
doctrine with **no exemptions**:

- **Health.** It serves `GET /health` like any core service. Because it owns a
  loop, `contracts.md § Self health` already prescribes the tick rule (monotonic
  tick each iteration, 503 when stale, tick at least every 10 s, 30 s staleness
  threshold). A cron loop with a bounded ≤10 s wait satisfies it without
  amendment. The exemption paragraph at `contracts.md:59` **deletes**.
- **Telemetry.** It gets a sidecar like any other core service. Job telemetry
  stops being deferred and the trace originates in the process that fired it.
- **Contract.** Consumer-only, so it needs none — same status the doctrine
  already gives `frontend.web`.
- **`dev` / `test`.** A normal container with normal bind mounts. The stale-`dist/`
  behaviour, the "scheduler-only codebase nothing builds" special case, and the
  `test`-env trigger suppression all vanish.

### B.3 Two prose rules, deliberately not validation rules

Both are written as doctrine prose in `clock.md`, **not** added to the numbered
rule list. The compiler cannot see what a port method does, and a rule it cannot
enforce is a lie in the rule list.

1. **The clock defers; it does not work.** Its only job is to call a driving port
   that enqueues; the work happens in a `worker`. Otherwise heavy jobs run inside
   a singleton with no replicas and no queue-level retry. The consequence — a
   codebase with no queue cannot have scheduled work — is correct pressure, not a
   gap.
2. **One clock per codebase-with-schedules, not one per project.** Codebases
   never share code, so a clock can only enqueue into its own. Cross-codebase
   scheduling is out. Largely theoretical for most projects, but a genuine
   narrowing versus a project-wide scheduler, and it should be stated rather than
   discovered.

The decisive constraint behind both — **only the codebase that owns the schema
may enqueue** — is stated once, in `clock.md`, with the schema-ownership and
external-types-as-truth reasoning from the design record.

### B.4 One validation rule changes hands

Rule 26 is **replaced**, not extended: `replicas` is not declared on a `clock`
core service. Rule 25 loses its scheduler clause. Rule 27 becomes *"`worker` and
`clock` core services do not declare `web` in `networks`"* (ruling Q3) — rule 27
is a constraint *on* a non-serving process, not a carve-out *for* the scheduler,
so a clock inherits it.

The elastic stop-then-start deployment percentages
(`deployment_minimum_healthy_percent = 0` / `deployment_maximum_percent = 100`)
are a **compiler behaviour**, not a validation rule. They trade a possible
double-fire on rolling deploy for a possible missed fire — the right trade, since
missed fires are already an accepted caveat and jobs are required to be
idempotent. Documented in `clock.md § Deployment`.

### B.5 `scheduler.md` is deleted; `clock.md` takes its place

All 286 lines go. The successor is short and scoped to what a project author
needs in order to schedule work — because "how do I schedule a task?" must stay
discoverable. **Approved outline** (ruling Q2):

```
doctrine/infrastructure/specifics/clock.md   (stratum: conditional)

# Clock
  opening — the question this file answers
§ What a clock core service is        role, singleton, no exemptions; the infra.yml block
§ The clock defers; it does not work  the rule, the schema-ownership reason, the consequence
§ One clock per codebase              and why cross-codebase scheduling is out
§ Architecture                        the chain, as a ROUTER into resident doctrine
§ Cron format                         bare 5-field UTC, no dialect translation
§ How the schedule reaches the container
    fixed    — infra/output/<env>/schedules.yml via compose top-level `configs:`
    elastic  — literal string in a task-definition env entry
    (both → telemetry_infra.md § Config Delivery, the proven pattern)
§ Deployment                          elastic stop-then-start percentages, and why
§ Caveats                             no backfill / catch-up; no per-job concurrency guard;
                                      the stagetest blind spot (see B.7)
```

**§ Architecture is a router, not a restatement.** One code block for the chain
plus a few sentences pointing into
[`internal_dependency_rules.md § Entrypoints`](../../../../doctrine/hexagonal_architecture/internal_dependency_rules.md#entrypoints)
(the runtime host belongs to the entrypoint and is not an adapter — a cron loop is
the same species as a broker's consume loop) and the canonical `Queue` driven
pattern. Every element is already doctrine; the section's job is to say which
existing pieces compose into a clock, and that `ContJobsCron` owns the job-name →
port-method dispatch so the entrypoint stays thin enough to need no test of its own.

```
entrypoints/clock.py        runtime host — the cron loop
  → ContJobsCron            driving adapter: job name → port method
    → ContJobs              driving port (shared with ContJobsHttp, ContJobsCli)
      → alogic
        → QueueJobs         driven port — canonical `Queue` pattern
```

Worth one sentence: because the driving port is shared, the same job is reachable
over HTTP and CLI, so firing a scheduled job by hand in `dev` stops being a
special path.

Every inbound pointer moves rather than dies:

| Pointer | New form |
| --- | --- |
| `skills/infra-compile/SKILL.md:28` | → `clock.md`; description rewritten to the clock role, bare-cron authoring, and schedule delivery. |
| `transfer_tables.md:287` | `scheduled_task` removed from the recognized emit-destination examples; its `scheduler.md` link goes with it. |
| `transfer_tables.md:438` | `scheduler/container` → `clock/container`, link → `clock.md`. |

### B.6 Peripheral clock edits

| File | Change |
| --- | --- |
| `cicl.md` sample `infra.yml` | `nightly_cleanup` scheduler block → a `clock` core service with `schedules:`. |
| `cicl.md:128` naming note | `role: scheduler` → the job's name → `role: clock` → `clock`. |
| `cicl.md` § Service Fields | New `schedules:` row (scope: core service; required on `clock`, rejected elsewhere). `replicas` row drops its scheduler sentence, gains the clock one. |
| `contracts.md:59` | Exemption paragraph **deleted**. |
| `shape.md:51,81` | The `non-`scheduler`` qualifier on the sidecar rows drops — a clock is an emitted core-service container and gets one. |
| `telemetry_infra.md:188` | Paragraph deletes (no role is sidecar-exempt). |
| `telemetry_infra.md:261` | Two task definitions → **one**: the per-codebase migration task definition. |
| `telemetry_infra.md:350,354` | Collector arithmetic drops its `non-scheduler` qualifier. |
| `telemetry.md:84` | Scheduler-exception sentence deletes. **Resident-adjacent care.** |
| `networks.md:44` | `worker` or `scheduler` → `worker` or `clock` (ruling Q3). |
| `ec2_traefik.md:61` | Same. |
| `tests.md:80` | Scheduler exemption sentence replaced — see [B.7](#b7-the-clocks-stagetest-blind-spot). |
| `transfer_tables.md:897` | The "a `scheduler` pays no sidecar overhead" note deletes; a clock pays the standard allowance. |
| `cicl_reasoning.md:22` | Role-specific field example `schedule` → `schedules`. |
| `hex_overview.md` § Controller Mechanism | **Resident stratum.** New row: `Cron` — "Fires the module's operations on a schedule." Example: `ContJobsCron`. |

### B.7 The clock's stagetest blind spot

Stated plainly rather than closed (ruling Q5). A clock is **consumer-only by
rule**, so nothing `uses` it and no `web` core service fans out to it; it is not
on `web` itself, so the stage tester cannot reach it directly either. Its
`/health` is enforced by the container healthcheck — docker `healthcheck:` on
fixed, ECS container health on elastic — which restarts a wedged clock. That is
real enforcement, and it is a strict improvement over today, where nothing probed
a scheduler at all. But it is **invisible to stagetest**, and the doctrine says so
in both places rather than implying otherwise:

- `tests.md:80` becomes an accurate statement of what the staging walk does and
  does not see. It is no longer an *exemption* — a clock is probeable; it is
  simply not reachable from the tester.
- `clock.md § Caveats` carries the same fact from the authoring side.

**No fan-out obligation is invented** to close the gap. That would be a new rule
neither design record specifies.

---

## What this mod does not touch

- `docex` source, tables, tests, fixtures, and both smoke projects (Mods 113–117).
- `upgrades/upgrade_1.7.0.md` (Mod 117) and the version artifacts (close-out).
- `docex/plans/core/*.md` and `doctrine_excerpts/` + `index.yml` (Mod 118, the
  artifact-alignment sweep). Drift this mod knowingly creates there is listed in
  the final report rather than fixed here.
- `cicl.md § Resilience covers reachability, not resolvability` beyond the field
  rename — Mod 114 owns its substance.

## Verification

There is no code and no test to run; the suite is untouched and remains green.
The mod is verified by:

1. No `depends_on:` or `consumes:` survives in `doctrine/` or `skills/` except
   where it names the compose keyword the exec block still emits.
2. No `scheduler` survives in `doctrine/` or `skills/`.
3. Every `#depends-on-relationships` / `#consumes-relationships` /
   `specifics/scheduler.md` link resolves to its successor. Checked mechanically,
   not left for `cohere`.
4. `cicl.md:428`'s impossibility argument is gone, not merely surrounded.

---


# Design questions — resolved

All seven questions raised at design review were ruled on before implementation
steps were written. Recorded here so the reasoning is not lost to the radio.

| # | Question | Ruling |
| --- | --- | --- |
| Q1 | The replacement for the `cicl.md:428` impossibility argument | Approved as drafted, **minus** its closing sentence. **Rule 6 is deleted entirely**, not narrowed — once backing services are structurally sinks the acyclicity property is a consequence of the graph's shape and no rule states it. The argument ends on the structural claim. Rule 7's reference to rule 24 goes with rule 24. *(Operator.)* |
| Q2 | The shape and scope of `clock.md` | Both additions approved. **§ Architecture is included** — the chain is written down in doctrine rather than existing only in Mod 117's smoke project, because "the clock defers; it does not work" is close to meaningless without saying what it defers *to*. Kept short: a **router** into resident doctrine, not a restatement of it. § Deployment also approved. *(Operator.)* |
| Q3 | May a `clock` declare the `web` network? | **No.** Rule 27 → *"`worker` and `clock` core services do not declare `web` in `networks`."* Rule 27 is a constraint *on* a non-serving process, not a carve-out *for* the scheduler. Settles `networks.md:44` and `ec2_traefik.md:61` the same way. *(Sarge.)* |
| Q4 | Rule 5's `-scheduler` derivative | **Dropped in this mod.** Rule 5 is keyed on collision, not a name list, so a derivative the compiler will no longer emit does not belong in it. Mod 116 still owns the code side. *(Sarge.)* |
| Q5 | Stage-test liveness for a clock | **State the blind spot plainly; invent nothing.** See [B.7](#b7-the-clocks-stagetest-blind-spot). `tests.md:80` becomes an accurate statement of what the walk does and does not see, not an exemption. *(Sarge.)* |
| Q6 | `cicl_version` in the rule of record | **Moves to `"3"`** in rule 21 and § CICL Version. *(Sarge.)* |
| Q7 | The `contracts.md:69` justification paragraph | **Cut to one sentence** preserving the surviving observation (a dead consumer is invisible because requests keep returning 200); drop the archaeology of the split. *(Sarge.)* |

## Consequences of the Q1 delete ruling

Two follow-on items, both introduced with the ruling:

1. **Tombstones, and no renumbering.** See
   [A.2.1](#a21-rule-numbers-are-stable-identities). Retiring items 6 and 24 from
   a markdown ordered list would silently renumber all 28 rules, and rule numbers
   are referenced from other doctrine files, `PRE_CUT_CHECKLIST.md`, `docex`'s
   `ValidationIssue.rule` ids, and the tests asserting on them. Each retired rule
   keeps its number and carries a one-line tombstone.

2. **A warning that must reach Mod 113 — not fixed here.** `validate.py:526`
   names an issue `rule_6_unknown_depends_on`, but doctrine rule 6 is *only* the
   acyclicity rule. That unknown-target check is a **live and necessary**
   validation — a typo'd `uses` target must fail loudly — and it must survive the
   merge under a new issue id. An implementer following rule numbers mechanically
   would delete it alongside rule 6 and leave typos to surface later as an
   unresolvable magic ref, or silently. Carried in this mod's final report; this
   mod touches no code.
