# Mod 112 — Implementation Steps

**Doctrine-only mod. Touch no code, no tests, no fixtures, no smoke projects.**
Do not run `pytest`. Do not touch `VERSION`, `pyproject.toml`,
`src/docex/__init__.py`, `.claude-plugin/plugin.json`, `upgrades/*`,
`docex/plans/core/*.md`, or `doctrine_excerpts/`. Those belong to later mods.

All paths are relative to `$jb` = `/home/ubuntu/.claude/jean_baudrillard`.

Design record: [`overview.md`](./overview.md). Read it first — it carries the
seven operator/sarge rulings this file implements.

> **This is load-bearing doctrine prose.** Where a step gives literal replacement
> text, **transcribe it**; do not paraphrase or improve it. Where a step says
> "vocabulary only", change only the named words and links and leave sentence
> structure alone. If you find text that a step does not anticipate and that
> cannot be handled by the step's rule, **stop and report it** rather than
> inventing a resolution.

Line numbers are as of commit `4ef5294` and will drift as you edit. Anchor on the
quoted text, not the number.

---

## Step 1 — `cicl.md`: the sample `infra.yml`

File: `doctrine/infrastructure/cicl.md`.

**The file indents YAML with TAB characters. Preserve tabs exactly.**

1.1 — Line 24: `cicl_version: "2"` → `cicl_version: "3"`.

1.2 — In the `api.web` block, replace the two lines

```
					depends_on: [database, cache, bucket]
					consumes: [api.worker]
```

with one:

```
					uses: [database, cache, bucket, api.worker]
```

1.3 — In the `api.worker` block, replace

```
					depends_on: [cache, database]
					consumes: [api.web]
```

with:

```
					uses: [cache, database, api.web]
```

1.4 — Replace the whole `nightly_cleanup` block:

```
				nightly_cleanup:
					role: scheduler
					schedule: "0 3 * * *"
					command: ["python", "-m", "jobs.cleanup"]
					networks: [internal]
					resources:
						cpu: 0.25
						memory: 512MB
					depends_on: [database]
```

with:

```
				clock:
					role: clock
					command: ["python", "-m", "entrypoints.clock"]
					port: 8080
					networks: [internal]
					health_check_path: /health
					resources:
						cpu: 0.25
						memory: 512MB
					uses: [database, api.worker]
					schedules:
						nightly_cleanup: "0 3 * * *"
						hourly_rollup: "0 * * * *"
```

1.5 — The comment above the `api:` key reads `# One codebase, one image, three
core services.` It stays accurate (web, worker, clock). Leave it.

---

## Step 2 — `cicl.md`: § Core Services

2.1 — The naming blockquote. Replace:

> **Naming**: A core service is generally named after its role, unless a codebase declares two on the same role. `role: web` → `web`; `role: worker` → `worker`; `role: scheduler` → the job's name (`nightly_cleanup`), since a codebase commonly has several jobs.

with:

> **Naming**: A core service is generally named after its role, unless a codebase declares two on the same role. `role: web` → `web`; `role: worker` → `worker`; `role: clock` → `clock`.

2.2 — The design record for the `uses` merge cites "the explanatory paragraph at
`cicl.md:107`", whose only job was justifying why a worker's dependency on
`cache` lived in one field and its dependency on `api.web` in another. **Search
for it. It appears to have already been removed during the mod 110–111 rename.**
If it is genuinely absent, do nothing and note that in your report. If you find a
surviving paragraph matching that description, delete it.

---

## Step 3 — `cicl.md`: § Service Fields table

3.1 — Delete these two rows:

```
| depends_on | no | core service, backing | Readiness gate. Names **backing services only**. See [Depends-On Relationships](#depends-on-relationships). |
| consumes | no | core service | Interface edges to other core services, dotted and fully qualified. See [Consumes Relationships](#consumes-relationships). |
```

Replace with one row, in the same table position:

```
| uses | no | core service | What this core service talks to. Names a **backing service** (bare) or a **core service** (dotted and fully qualified). See [Uses Relationships](#uses-relationships). |
```

3.2 — Replace the `replicas` row:

```
| replicas | no | core service | The number of parallel containers to launch in production. Ignored in `dev`, `test`, and `stage`. Defaults to 1. Not permitted on a `scheduler` core service. |
```

with:

```
| replicas | no | core service | The number of parallel containers to launch in production. Ignored in `dev`, `test`, and `stage`. Defaults to 1. Not permitted on a `clock` core service. |
```

3.3 — Add a `schedules` row **immediately after** the `replicas` row:

```
| schedules | sometimes | core service | Map of job name → bare 5-field UTC cron string. Required on a `clock` core service and rejected on every other role. See [clock.md](./specifics/clock.md). |
```

3.4 — Leave the sentence *"`./bin/docex compile` will always fail loudly when a
field is placed in the wrong scope, or if a required field is absent"* untouched.
It is what enforces "a backing service may not declare `uses`", and no numbered
rule is added for that.

---

## Step 4 — `cicl.md`: § CICL Version

Replace the whole section body:

```
The top-level `cicl_version` field declares which generation of the CICL format `infra.yml` is written in. The current version is **`"2"`**.

Previous versions are **rejected**, not shimmed. A compatibility parser accepting both forms would reintroduce the flat, one-service-per-codebase shape that predates nesting core services under a codebase, as a permanent second code path, in exchange for serving a migration that every project performs exactly once. The compiler fails with a message naming the relevant project-upgrade guide.
```

with:

```
The top-level `cicl_version` field declares which generation of the CICL format `infra.yml` is written in. The current version is **`"3"`**.

Previous generations are **rejected**, not shimmed. A compatibility parser accepting an older form would keep that generation's shape alive as a permanent second code path — the flat, one-service-per-codebase layout that predates nesting core services under a codebase, or the split `depends_on` / `consumes` relation that predates `uses` — in exchange for serving a migration that every project performs exactly once. The compiler fails with a message naming the relevant project-upgrade guide.
```

---

## Step 5 — `cicl.md`: the relation sections (the core of Part A)

This step replaces **everything** from the `### Depends-On Relationships` heading
through the end of `#### Three clarifications` — i.e. the current
§ Depends-On Relationships, § Resilience covers reachability not resolvability,
§ Consumes Relationships, § The graph may contain cycles, and
§ Three clarifications — with the block below. It sits in the same file position
(between § Resources and § Reverse Proxy).

**Preserve `§ Resilience covers reachability, not resolvability` verbatim except
for the two vocabulary substitutions marked inline.** Mod 114 owns that section's
substance; this mod only renames the field.

Replacement block:

````markdown
### Uses Relationships

`uses` is the single relation between services. It says *"I speak to this boundary"* — nothing more.

```yml
codebases:
	api:
		core_services:
			web:
				uses: [database, cache, bucket, api.worker]
```

A `uses` entry names either a **backing service**, bare (`database`), or a **core service**, dotted and fully qualified (`api.worker`). A bare codebase name is illegal, not shorthand for "all its core services": an interface edge points at a specific boundary, and a codebase does not have one contract.

**Only core services declare `uses`.** A backing service has no outbound edges at all. Where an engine genuinely needs another container beneath it, which containers an engine requires is an *engine* concern and belongs in its transfer table's `defaults` block, not in `infra.yml`. The consequence is structural and load-bearing: a backing service is a **sink** in the relation graph. See [The graph may contain cycles](#the-graph-may-contain-cycles).

Provider and consumer survive as **derived** vocabulary rather than as field names: a core service that is used by another is a provider, and the one doing the using is a consumer. See [contracts.md](./contracts.md).

`uses` **emits nothing onto a core service's own block** — no compose key, no HCL resource, on either foundation. It is read by the compiler's exec-block gate, by CI, by validation, and by the elastic release, where it does five jobs:

1. It declares the [provider / consumer](./infrastructure.md#contracts) relationships that determine which core services must carry a contract, and in which format.
2. It drives the health-check fan-out — see [contracts.md § Health Checks](./contracts.md#health-checks).
3. It satisfies [validation rule 7](#validation-rules) for magic refs.
4. Its **backing-targeted** edges are unioned per codebase into the readiness gate on that codebase's exec block — the compiler's one remaining ordering emission. See [Startup ordering is not a doctrine feature](#startup-ordering-is-not-a-doctrine-feature).
5. On elastic, it identifies which consumers must be redeployed after a release that registers a new Service Connect endpoint — see [§ Resilience covers reachability, not resolvability](#resilience-covers-reachability-not-resolvability).

Jobs 1–3 and 5 are validation, CI, and *release-time orchestration* reads; nothing derived from them reaches the compiled output. Job 4 is the sole emission, and it lands on a block no project authors.

#### Startup ordering is not a doctrine feature

> **Startup ordering is not a substitute for connection resilience.**

Every service must tolerate its dependencies being absent at any moment — not only at startup. Reconnect, back off, and fail requests cleanly; do not assume a dependency that was reachable a second ago still is.

This is an unqualified requirement, not a warning attached to a gate you might lean on. **The compiler emits no ordering onto any core service's block.** On `elastic` it could not be honoured in any case: ECS has no cross-service ordering primitive, and even a deploy-time emulation would hold exactly once and then be silently violated forever after, as ECS independently replaces tasks for scaling, AZ rebalance, failed health checks, and platform updates. But the reason it is gone from `fixed` too is sharper. A gate that `dev` and `test` honour while the doctrine says nothing makes those envs systematically **more forgiving** than elastic `prod`: a service that connects at boot with no retry works in `dev`, works in `test`, and breaks the first time the project goes elastic. The protection would be real but invisible, so nobody would know to distrust it. `dev` should *expose* non-resilient boot code, not shelter it.

The accepted cost is a burst of connection-refused lines on `envinfra up` while backing services initialize. That is acceptable and arguably good signal — you can watch backoff working — and per [logging.md](../practices/logging.md) stdout is already the home for that class of diagnostic. A service that crashes rather than retries fails the bring-up, which is the correct outcome.

**The per-codebase exec block is the one place ordering survives, and it is not a carve-out.** `migrate.sh`, `test.sh`, and `build.sh` are one-off batch jobs whose entire contract is an exit code. Disposability says a long-running process must tolerate a dependency vanishing; nothing in it makes a one-shot script succeed against a database not yet accepting connections. For a batch job, "be tolerant" *means* "wait until ready". So the exec block carries the union of its codebase's backing-targeted `uses` edges, rewritten to `condition: service_healthy` — see [migrations.md](./specifics/migrations.md#dev-and-test-mechanism). Ordering has stopped being a property of the project's services and become a property of one compiler-owned block: no project declares it, and no project can rely on it.

#### Resilience covers reachability, not resolvability

The rule above answers *reachability*: a dependency that is down, restarting, or briefly unroutable. It does **not** answer a second failure mode that elastic adds, and which no amount of application-level retrying can escape.

ECS Service Connect fixes a client task's set of **resolvable endpoint names at task start**. An endpoint registered in the namespace *after* a client task started is not merely unreachable from that task — it is unresolvable, for the entire remaining life of the task. The name does not exist. Backing off and retrying never converges, because there is nothing to converge on.

So a core service created alongside a [`uses`](#uses-relationships) target it has never seen registered can be permanently unable to reach it, with both sides healthy. The externally visible symptom is a `503` on the [health fan-out](./contracts.md#fan-out); the invisible one is that every real call across that edge fails too.

**`docex` closes this at release time**, by redeploying any consumer whose `uses` target registered during that release. Note carefully that this is *not* the deploy-time ordering emulation rejected above, and the distinction is what makes it sound: an endpoint **registration is durable state**, owned by the service rather than by task liveness, and it survives every task replacement. Holding once is therefore permanently sufficient — after the first registration, every later task (scaling, AZ rebalance, failed health check, platform update) starts into a namespace that already contains the name. A readiness gate decays because liveness changes; a registration does not.

Ordering could not have solved it in any case: the `uses` graph may legally [contain cycles](#the-graph-may-contain-cycles), and in a cycle some member must be created first.

#### The graph may contain cycles

`api.web` enqueues a job; `api.worker` posts the result back to `api.web`'s internal API. So `web` uses `api.worker` *and* `worker` uses `api.web`. That is a cycle, it is the most common web/worker topology in existence, and it is entirely fine — interfaces may be mutually referential.

One field carries the whole relation because the cycle rule keys on **target kind**, which the compiler knows for every edge: a cycle among core-service targets is legal, and a cycle through a backing-service target would be a startup deadlock. The second case cannot arise. A backing service declares no `uses` edges at all, so no path leaves one — it is a graph **sink**, and a sink cannot sit in a cycle. Acyclicity across backing-targeted edges therefore falls out of the shape of the graph rather than being enforced against it.

#### Three clarifications

- **One-directional: a ref implies an edge, never the reverse.** A magic ref to another service obliges a matching `uses` entry. A `uses` entry does *not* oblige a magic ref — in the cycle above, `api.web` declares `uses: [api.worker]` for the contract and the health fan-out but holds no ref to the worker, because it reaches it through the broker.
- **Same-codebase is not exempt.** `api.worker` referencing `${codebases.api.core_services.web.host}` still declares `uses: [api.web]`. Sharing source does not make it not a boundary.
- **A codebase-level `env:` ref obliges every core service** to declare the edge. If every core service receives `WEB_HOST`, every core service talks to `api.web`.
````

**Deleted outright by this step, with nothing carried forward:** the
`depends_on` vs. `consumes` comparison table; the sentence *"A core service may
**not** appear in a `depends_on` list…"*; the paragraph beginning *"Furthermore,
if a core service references a backing service's information via magic ref…"*
(its content is now rule 7 plus the first clarification); the paragraph beginning
*"**`depends_on` is a convenience, never a correctness guarantee.**"* (folded
into § Startup ordering is not a doctrine feature); and the sentence *"This is
why the two relations cannot merge."* together with the DAG-vs-digraph argument
that followed it.

---

## Step 6 — `cicl.md`: § Validation Rules

6.1 — After the line `The following rules apply to whether or not an `infra.yml`
file is valid.`, insert this paragraph before the numbered list:

```
Rule numbers are **stable identities**. They are cited from other doctrine files, from `docex`'s validation issue ids, and from the pre-cut checklist, so a retired rule keeps its number and is marked below rather than removed — the rules that follow it are never renumbered.
```

6.2 — **Rule 5.** In the parenthetical list of compiler-appended derivatives,
delete `` `-scheduler` (the Ofelia trigger), ``. The rest of the rule, including
the `api-exec` and `web-1` worked examples and the closing "keyed on collision,
not on a list of forbidden names" sentence, is unchanged.

6.3 — **Rule 6.** Replace entirely with the tombstone:

```
6. *(Retired in 1.7.0.)* Formerly forbade cycles in `depends_on`. With one relation, and backing services declaring no outbound edges, a backing service is a graph **sink** — acyclicity across backing-targeted edges is a property of the graph's shape rather than a rule enforced against it. See [The graph may contain cycles](#the-graph-may-contain-cycles).
```

6.4 — **Rule 7.** Replace entirely with:

```
7. Magic refs which imply a dependency must be matched by a corresponding `uses` entry on the referencing core service. This rule governs **core-service referencers**, since a core service is the only thing that can hold a `uses` edge. A backing service that embeds a core service's part — an `object_store` holding `${codebases.api.core_services.web.host}` as a CORS origin, say — cannot satisfy it at all, because backing services declare no edges. That is rule 7 correctly **not applying** rather than a gap: a backing service embedding a core hostname is not *calling* it, so there is no interface implication for the relation to express. See [Uses Relationships](#uses-relationships) for the one-directional, same-codebase, and codebase-level-`env:` clarifications.
```

6.5 — **Rule 21.** `` 21. `cicl_version` is `"2"`. Earlier generations of the
format are rejected, not translated. `` → `` 21. `cicl_version` is `"3"`. Earlier
generations of the format are rejected, not translated. ``

6.6 — **Rule 24.** Replace entirely with the tombstone:

```
24. *(Retired in 1.7.0.)* Formerly restricted `depends_on` to backing services. There is one relation now, and its shape rule is rule 25.
```

6.7 — **Rule 25.** Replace entirely with:

```
25. `uses` names either a backing service, bare, or a core service, fully qualified as `<codebase>.<service>`. A bare codebase name is an error, and a core service may not use itself.
```

6.8 — **Rule 26.** → `` 26. `replicas` is not declared on a `clock` core service. ``

6.9 — **Rule 27.** → `` 27. `worker` and `clock` core services do not declare `web` in `networks`. ``

6.10 — Verify the list still runs 1 … 28 with no item added or removed.

---

## Step 7 — Delete `scheduler.md`; write `clock.md`

7.1 — `git rm doctrine/infrastructure/specifics/scheduler.md` (all 286 lines go).

7.2 — Create `doctrine/infrastructure/specifics/clock.md` with **exactly** this
content:

````markdown
---
stratum: conditional
---

# Clock

This file answers one question: **how does the doctrine expect a project to schedule recurring work?**

The answer is a `clock` core service. It is an ordinary long-running singleton core service — a compose service on fixed, a `task_definition` + `ecs_service` on elastic — whose `command` invokes a clock entrypoint. That entrypoint reads a compiler-delivered schedule table and, when a job is due, calls a driving port that **enqueues**. The work itself happens in a `worker`.

There is no separate scheduling primitive. A schedule is a property of an *invocation*, not of a deployment, and a clock is simply the invocation that owns the cron loop.

## What a clock core service is

```yml
codebases:
	api:
		core_services:
			clock:
				role: clock
				command: ["python", "-m", "entrypoints.clock"]
				port: 8080
				networks: [internal]
				health_check_path: /health
				resources: { cpu: 0.25, memory: 512MB }
				uses: [appdb, api.worker]
				schedules:
					nightly_cleanup: "0 3 * * *"
					hourly_rollup: "0 * * * *"
```

`schedules:` is a map of **job name → cron expression**. It is required on a `clock` and rejected on every other role.

A clock is subject to every ordinary [core service](../cicl.md#core-services) rule, with **no exemptions**:

- **Health.** It serves `GET /health` like any core service. Because it owns a loop, [contracts.md § Self health](../contracts.md#self-health) already prescribes the tick-based liveness rule — bump a monotonic tick each iteration, 503 when stale, tick at least every 10 s even when idle, 30 s staleness threshold. A cron loop with a bounded ≤10 s wait is the natural way to write one, so the existing rule fits without amendment. A wedged clock fails its own probe.
- **Telemetry.** It gets a paired OTel collector sidecar like any other core service, so job telemetry is ordinary telemetry and the trace originates in the process that fired the job.
- **Contract.** It is consumer-only, so it needs none. The provider set is (core-service `uses` targets) ∪ (`web`-network core services), and a clock is neither.
- **Networks.** It may not declare `web` ([rule 27](../cicl.md#validation-rules)). It serves no public boundary.
- **Replicas.** It may not declare `replicas` ([rule 26](../cicl.md#validation-rules)) — see [Deployment](#deployment).
- **`dev` and `test`.** A normal container with the normal bind mounts, in every environment. Nothing about a clock is suppressed anywhere.

## The clock defers; it does not work

**A clock's only job is to call a driving port that enqueues.** It performs no work itself.

The reason is that **only the codebase that owns a schema may write to it.** The doctrine's queue pattern is a library-backed queue whose tables are created by the schema-owning codebase's `migrate.sh` and declared by [`schema_owned_by`](../cicl.md#service-fields). Anything else writing to those tables is a non-owner writing an owned schema, hand-rolling SQL against a library's internal structures — the coupling [hex_overview.md § Shared Clients](../../hexagonal_architecture/hex_overview.md#shared-clients) forbids of an adapter, hoisted into infrastructure where no adapter can absorb the break. The library bumps its schema and the clock silently stops enqueueing.

So enqueueing must be an in-process call by code in the codebase that owns the schema, which is exactly what a core service of that codebase can do.

The rule earns its keep beyond that, too. A clock is a singleton with no replicas and no queue-level retry; heavy work run inside it has no retry story and no horizontal headroom. Deferring puts the work where retry and concurrency already exist.

The consequence — **a codebase with no queue cannot have scheduled work** — is correct pressure rather than a gap. It is also why "run an arbitrary argv on a schedule" is no longer available: scheduled work must be an operation on a driving port, which forces it into the composed, observable, tested application instead of a side door. Argv-against-the-image survives where it belongs, in the per-codebase exec container and `migrate.sh`.

## One clock per codebase with scheduled work

Not one per project. Codebases never share code, so a clock can only enqueue into its own codebase's queue. **Cross-codebase scheduling is out**: a codebase that needs scheduled work declares its own clock.

For most projects exactly one codebase has scheduled work, so this is largely theoretical — but it is a genuine narrowing, and it is stated here rather than left to be discovered.

## Architecture

Every element below is already doctrine; a clock is a composition of existing pieces, not a new pattern.

```
entrypoints/clock.py        runtime host — the cron loop
  → ContJobsCron            driving adapter: job name → port method
    → ContJobs              driving port (shared with ContJobsHttp, ContJobsCli)
      → alogic
        → QueueJobs         driven port — canonical `Queue` pattern
          → QueueJobsProcrastinate
```

The cron loop belongs to the **entrypoint**, not to an adapter: per [internal_dependency_rules.md § Entrypoints](../../hexagonal_architecture/internal_dependency_rules.md#entrypoints) the runtime host is the entrypoint's job, and a cron loop is the same species as a broker's consume loop. `ContJobsCron` is a real driving adapter rather than ceremony — it owns the job-name → port-method dispatch table and the fired/succeeded/failed translation, which keeps the entrypoint thin enough to satisfy the standing rule that an entrypoint needing its own test is doing too much. `QueueJobs` is the canonical [`Queue`](../../hexagonal_architecture/hex_overview.md#driven-port--adapter-patterns) driven pattern, and `Cron` is a canonical [controller mechanism](../../hexagonal_architecture/hex_overview.md#controller-mechanism).

**Side effect worth having.** Because the driving port is shared with the HTTP and CLI controllers, every scheduled job is also reachable over HTTP and on the command line. Firing a scheduled job by hand in `dev` stops being a special path.

## Cron format

`schedules:` values are **bare 5-field cron expressions** — `minute hour day-of-month month day-of-week` — in **UTC**.

There is **no dialect translation anywhere**. The compiler passes the expression through to the schedule table unchanged; whatever cron library the codebase uses parses it directly. This is a consequence of the clock being project code rather than a cloud primitive, and it removes an entire class of bug: no 6-field forms, no `?`-day substitution, no provider-specific day-of-week renumbering.

Job names are identifiers and must be valid as such — they are the dispatch keys the clock's controller looks up.

## How the schedule reaches the container

The compiler renders `infra/output/<env>/schedules.yml` from the `schedules:` blocks. Being compiler output, it is git-tracked and diff-visible per [cicl.md § Compiler Output](../cicl.md#compiler-output), so a schedule change shows up in review as an infrastructure change. Cron expressions never enter application code.

Delivery reuses the OTel sidecar's already-proven config-delivery paths (see [telemetry_infra.md § Config Delivery](./telemetry_infra.md#config-delivery)) — this is the third user of that mechanism, not a new one:

- **fixed** — the rendered file is mounted into the container via the compose top-level `configs:` block.
- **elastic** — the rendered content is embedded as a literal string in a task-definition env entry and read from there at startup.

The [check step](../cicd.md#check-step) can assert that every declared job name has a binding in the clock's dispatch table, catching a schedule that names a job nobody implements.

## Deployment

On **elastic**, a `clock` service is emitted with `deployment_minimum_healthy_percent = 0` and `deployment_maximum_percent = 100`, forcing **stop-then-start**.

This is deliberate and applies to `role: clock` alone. ECS rolling-deploy defaults (minimum healthy 100%, maximum 200%) briefly run two tasks, and a tick landing in that window fires twice. Stop-then-start trades a possible **double fire** for a possible **missed fire** during a deploy. That is the right trade: missed fires are already an accepted caveat below, and jobs are required to be idempotent regardless.

`replicas` is forbidden on a clock for the same reason. A clock is a singleton.

## Caveats

- **No backfill or catch-up.** A missed fire — host down, task replacement, a deploy window — is not retroactively run. The clock fires forward-only.
- **No per-job concurrency guard.** If a job's runtime exceeds its interval, a second fire can occur before the first completes. Since a clock only enqueues, this means a duplicate *enqueue*, which is why jobs must be idempotent. Guard at the queue if a job genuinely cannot overlap.
- **A clock is invisible to staging tests.** It is consumer-only, so nothing `uses` it and no `web` core service fans out to it, and it is not on `web` itself — so the stage tester cannot reach it by any route. Its `/health` is enforced by the container healthcheck (docker `healthcheck:` on fixed, ECS container health on elastic), which restarts a wedged clock. That is real enforcement, but it is local: a clock's liveness is not asserted by [staging tests](../tests.md#staging-tests).
````

---

## Step 8 — `contracts.md`

File: `doctrine/infrastructure/contracts.md`.

8.1 — Line 9. `` the usage relationships declared by `infra.yml`'s [consumes](./cicl.md#consumes-relationships) field ``
→ `` the usage relationships declared by `infra.yml`'s [uses](./cicl.md#uses-relationships) field ``.

8.2 — Line 21. `` **The provider set is (`consumes` targets) ∪ (`web`-network core services).** ``
→ `` **The provider set is (core-service `uses` targets) ∪ (`web`-network core services).** ``
The two sentences that follow ("Both arms are load-bearing…") are unchanged.

8.3 — **Line 59: delete the scheduler exemption paragraph entirely.** No
replacement:

```
`scheduler` core services are **exempt**. There is no long-running container to probe, and a scheduler is never a `consumes` target — cron invokes it and nobody else does. "Did last night's job run" is a telemetry question, not a health-check one.
```

8.4 — Line 67. `` The fan-out set is **`consumes`**, restricted to targets not themselves on the `web` network. ``
→ `` The fan-out set is a core service's **core-service `uses` targets**, restricted to those not themselves on the `web` network. ``
The rest of that paragraph is unchanged.

8.5 — **Line 69: replace the whole paragraph with one sentence** (ruling Q7).
Delete:

```
`consumes` is the source rather than [`depends_on`](./cicl.md#depends-on-relationships) because a web edge does not `depends_on` its worker: it needs the *broker* up, not the consumer. Keying off `depends_on` would silently stop requiring `/health/api/worker`, and a dead consumer is invisible from outside because requests keep returning 200 while work piles up behind them. (This rule was once written as the *union* of the two, from a time when `depends_on` could still name a core service. [Rule 24](./cicl.md#validation-rules) has since restricted `depends_on` to backing services, which have no `<codebase>/<service>` form at all, so the union's second arm can no longer contribute a target. It is stated as `consumes` alone so nobody restores an arm that cannot fire.)
```

Replace with:

```
Backing-targeted edges cannot contribute — a backing service has no `<codebase>/<service>` form to proxy — and the core-service targets are exactly the ones that need proxying, because a dead consumer is invisible from outside: requests keep returning 200 while work piles up behind them.
```

8.6 — Line 71. `` the legal `web ↔ worker` cycle in [`consumes`](./cicl.md#consumes-relationships) recurses ``
→ `` the legal `web ↔ worker` cycle in [`uses`](./cicl.md#uses-relationships) recurses ``.

8.7 — Line 75. `` A `consumes` target must declare both `port` and `health_check_path`. ``
→ `` A core-service `uses` target must declare both `port` and `health_check_path`. ``

---

## Step 9 — `release.md`

File: `doctrine/infrastructure/specifics/release.md`.

9.1 — Line 100. `` a consumer and the [`consumes`](../cicl.md#consumes-relationships) target ``
→ `` a consumer and the [`uses`](../cicl.md#uses-relationships) target ``.

9.2 — Item 2 of the numbered list: `` every core service declaring a `consumes` target ``
→ `` every core service declaring a `uses` target ``.

9.3 — The third bullet: `` A `consumes` graph may legally contain cycles ``
→ `` The `uses` graph may legally contain cycles ``.

9.4 — **Line 114 (the one the brief calls out).** Replace:

```
**Fixed foundations need none of this.** Compose has real `depends_on` ordering, and docker network DNS resolves a sibling container whenever it exists, with no per-task snapshot.
```

with:

```
**Fixed foundations need none of this.** Docker network DNS resolves a sibling container whenever it exists, with no per-task snapshot.
```

The first clause becomes false under this mod — the compiler no longer emits
compose ordering — while the conclusion still stands on the second. Dynamic
sibling DNS was always the real reason.

9.5 — Do **not** otherwise alter § Service Connect Consumer Reconcile. Mod 114
owns its substance.

---

## Step 10 — `migrations.md`

File: `doctrine/infrastructure/specifics/migrations.md`.

10.1 — Line 48. `` and the union of its `depends_on` rewritten to `condition: service_healthy` ``
→ `` and the union of its `uses` edges whose target is a backing service, rewritten to `condition: service_healthy` ``.

10.2 — Line 71. `` The container inherits the exec service's networks and `depends_on` gates ``
→ `` The container inherits the exec service's networks and readiness gates ``.

---

## Step 11 — `transfer_tables.md`

File: `doctrine/infrastructure/specifics/transfer_tables.md`.

11.1 — Line 287. In the emit-destination examples, delete the whole clause
`` `scheduled_task` → the `aws_scheduler_schedule` + invocation role for a cron
job, see [scheduler.md](./scheduler.md); `` including its trailing semicolon and
space. The surrounding list (`compose_service`, `rds_instance`, `target_group`,
`container_definition`) is unchanged.

11.2 — Line 320 and line 331. The comments `# Port, env, and depends_on come from
the project's infra.yml.` and `# Port, env, and depends_on come from infra.yml.
…` → replace `depends_on` with `uses` in both.

11.3 — Line 438. `` `scheduler/container` (cron-triggered jobs — see [scheduler.md](./scheduler.md)) ``
→ `` `clock/container` (the scheduled-work singleton — see [clock.md](./clock.md)) ``.

11.4 — Lines ~615 and ~687. `depends_on: [probe, appdb]` → `uses: [probe, appdb]`;
`depends_on: [events, appdb]` → `uses: [events, appdb]`.

> These two example blocks are **also** still in the pre-`processes:` flat form,
> which `cicl_version: "2"` already rejects. **That defect is Mod 118's**, not
> yours. Change only the field name; leave the block structure alone, and note in
> your report that you saw it.

11.5 — Line 818. Replace:

```
Compose `depends_on` is always emitted in long-form (a map), never short-form.
```

with:

```
Compose `depends_on` is emitted on **one block only** — the per-codebase exec service, whose gate is the union of the codebase's backing-targeted `uses` edges (see [migrations.md](./migrations.md#dev-and-test-mechanism)). No core-service block carries it. Where it is emitted it is always long-form (a map), never short-form.
```

The remainder of that paragraph (the `service_healthy` / `service_started`
derivation and its justification) is unchanged, as is the YAML sample that
follows at line 821.

11.6 — Line 897. Delete the clause `` — which applies only to core services that
actually get a sidecar, so a `scheduler` (no `ecs_service`, no sidecar) pays
none ``. Every core service now gets a sidecar, so the qualifier is false. Keep
the sentence's arithmetic intact.

---

## Step 12 — `telemetry_infra.md`

File: `doctrine/infrastructure/specifics/telemetry_infra.md`.

12.1 — **Line 188: delete the paragraph entirely.**

```
A `scheduler` core service gets **no** sidecar: there is no long-running container to pair with. So a codebase with a `web` core service and a nightly job emits one sidecar, for the `web` core service — something the older per-codebase phrasing could not express.
```

Replace it with:

```
Every core service gets a sidecar, and the pairing is per core service rather than per codebase: a codebase with a `web` core service and a `clock` emits two, one each — something the older per-codebase phrasing could not express.
```

12.2 — Line 245. `` The core service does **not** declare a `depends_on`
healthcheck on `<cb>-<svc>-otelcol`. `` → `` The core service declares no
readiness gate on `<cb>-<svc>-otelcol`. `` The rest of the paragraph — about
compose's *implicit* opposite-direction dependency under `network_mode` — is
correct and unchanged.

12.3 — Line 261. Replace:

```
Two task definitions carry no sidecar: a `scheduler` core service's (it emits no `ecs_service` — nothing runs continuously) and the per-codebase migration task definition.
```

with:

```
One task definition carries no sidecar: the per-codebase migration task definition.
```

12.4 — Line 350. Delete the sentence `` A `scheduler` core service pays it
**zero** times, since it emits no [sidecar]. `` (match on the real text — it wraps
across lines).

12.5 — Line 354. `` the **sum**, over each non-`scheduler` core service, of … ``
→ `` the **sum**, over each core service, of … ``.

---

## Step 13 — `shape.md`

File: `doctrine/infrastructure/shape.md`.

13.1 — Line 51. `` one distinct compose container per *emitted* [core_service]
container — i.e. per non-`scheduler` [core_service], and per replica ``
→ `` one distinct compose container per *emitted* [core_service] container — i.e.
one per [core_service], and per replica ``.

13.2 — Line 81. `` one container inside each task definition that also runs an ECS
service — so one per non-`scheduler` [core_service], and one per running replica ``
→ `` one container inside each task definition that also runs an ECS service — so
one per [core_service], and one per running replica ``.

13.3 — Line 121. `depends_on: [database]` → `uses: [database]`.

---

## Step 14 — `telemetry.md`

File: `doctrine/infrastructure/telemetry.md`, line 84. Delete the sentence:

```
`scheduler` core services are the exception and get none: a cron job is short-lived and has no long-running container to pair with.
```

The sentences on either side ("there is one per *emitted* core service container
— that is, one per replica." and "The sidecar runs in a special subgroup…") join
up and are otherwise unchanged.

---

## Step 15 — `networks.md`

File: `doctrine/infrastructure/specifics/networks.md`, line 44.
`` A `worker` or `scheduler` core service may not declare `web` at all (rule 27) ``
→ `` A `worker` or `clock` core service may not declare `web` at all (rule 27) ``.

---

## Step 16 — `ec2_traefik.md`

File: `doctrine/infrastructure/specifics/projinfra/ec2_traefik.md`, line 61.
`` so a `worker` or `scheduler` core service and every backing service are never exposed ``
→ `` so a `worker` or `clock` core service and every backing service are never exposed ``.

---

## Step 17 — `tests.md`

File: `doctrine/infrastructure/tests.md`.

17.1 — Line 71. `` even though [`consumes`](./cicl.md#consumes-relationships) is declared per core service ``
→ `` even though [`uses`](./cicl.md#uses-relationships) is declared per core service ``.

17.2 — Line 80. Replace:

```
their liveness is asserted through the `/health/<codebase>/<service>` [fan-out](./contracts.md#fan-out) on the `web` core service that `consumes` them. `scheduler` core services are exempt — they have no long-running container to probe.
```

with (ruling Q5 — state the blind spot; invent no obligation):

```
their liveness is asserted through the `/health/<codebase>/<service>` [fan-out](./contracts.md#fan-out) on the `web` core service that `uses` them. A core service that nothing `uses` — a [clock](./specifics/clock.md), which is consumer-only by rule — has no fan-out to appear in and is not reachable from the stage tester at all. Its liveness is enforced by its container healthcheck rather than asserted here; the staging walk does not see it.
```

---

## Step 18 — `docex.md`

File: `doctrine/infrastructure/docex.md`.

18.1 — Line 67, the `dag` description. Replace:

```
`dag` - Describe the infrastructure shape with a directed graph. It renders both service relations with the edge kind distinguished: solid for [`depends_on`](./cicl.md#depends-on-relationships) (readiness), dashed for [`consumes`](./cicl.md#consumes-relationships) (interface). The graph is *directed*, not acyclic — `consumes` is a cyclic digraph by doctrine, so the rendered union may legally contain cycles; only the readiness relation on its own is acyclic. Node ids use the dotted reference form (`api.web`).
```

with:

```
`dag` - Describe the infrastructure shape with a directed graph. It renders the [`uses`](./cicl.md#uses-relationships) relation with the edge kind distinguished by **target kind**: solid to a backing service, dashed to a core service. The graph is *directed*, not acyclic — `uses` may legally contain cycles among core services, so the rendered graph may too; the backing-targeted edges alone are acyclic, since a backing service is a sink. Node ids use the dotted reference form (`api.web`).
```

18.2 — Line 159. `` `consumes`-to-contract alignment checks `` → `` `uses`-to-contract alignment checks ``.

---

## Step 19 — `cicd.md`

File: `doctrine/infrastructure/cicd.md`.

19.1 — Line 58. `` match `infra.yml`'s [consumes](./cicl.md#consumes-relationships) relationships ``
→ `` match `infra.yml`'s [uses](./cicl.md#uses-relationships) relationships ``.

19.2 — Line 59. `` a `/health/<codebase>/<service>` for each core service it `consumes` that is not itself on `web` ``
→ `` a `/health/<codebase>/<service>` for each core service it `uses` that is not itself on `web` ``.

19.3 — Line 61. `` Every `consumes` target declares both `port` and `health_check_path`. ``
→ `` Every core-service `uses` target declares both `port` and `health_check_path`. ``

---

## Step 20 — `infrastructure.md` (RESIDENT stratum — care)

File: `doctrine/infrastructure/infrastructure.md`, line 258.
`` In practice, these relationships are declared by `infra.yml`'s [consumes](./cicl.md#consumes-relationships) field. ``
→ `` In practice, these relationships are declared by `infra.yml`'s [uses](./cicl.md#uses-relationships) field. ``

The provider/consumer worked example above it (lines 253–256) is **unchanged** —
that vocabulary is now derived rather than a field name, and the example remains
correct as written.

---

## Step 21 — `cicl_reasoning.md`

File: `doctrine/infrastructure/reasoning/cicl_reasoning.md`, the field-scoping table.

21.1 — Line 20, right-hand cell: `` `depends_on`, `consumes` `` → `` `uses` ``.

21.2 — Line 22, right-hand cell: `` every role-specific field (`health_check_path`, `schedule`, …) ``
→ `` every role-specific field (`health_check_path`, `schedules`, …) ``.

---

## Step 22 — `hex_overview.md` (RESIDENT stratum — care)

File: `doctrine/hexagonal_architecture/hex_overview.md`, § Controller Mechanism table.

Add one row, after the `Cli` row:

```
| `Cron` | Fires the module's operations on a schedule, driven by a clock core service's job table. | `ContJobsCron` |
```

Change nothing else in that file.

---

## Step 23 — Skills

23.1 — `skills/contracts/SKILL.md`, line 20. Replace:

```
- Provider/consumer relationships are declared via `consumes` in `infra.yml` — author that in `infra-compile`. `depends_on` is a separate relation (backing-service readiness) and does not define a contract edge.
```

with:

```
- Provider/consumer relationships are declared via `uses` in `infra.yml` — author that in `infra-compile`. Only the **core-service** targets of a `uses` list define contract edges; a backing-service target does not.
```

Line 21 (`` the check step enforces contract-to-`consumes` alignment ``) →
`` contract-to-`uses` alignment ``.

23.2 — `skills/infra-compile/SKILL.md`, line 28. Replace the `scheduler.md`
router entry with:

```
[`clock.md`](../../doctrine/infrastructure/specifics/clock.md) — the `clock` role: how the doctrine schedules recurring work. Bare 5-field UTC cron authoring in `schedules:`, the defer-don't-work rule, one clock per codebase, and how the compiled schedule table reaches the container on each foundation. Read when a project needs anything to run on a schedule.
```

Keep it in the same position in the § Specific Information list. Do not touch
the skill's frontmatter `description` — the trigger interface is unchanged.

---

## Step 24 — Verification sweep

Run each of these from `$jb` and confirm the stated result. **These are the
acceptance criteria.** Report any hit you cannot resolve rather than forcing it.

24.1 — No stale relation fields:

```
grep -rn "depends_on\|consumes:" doctrine/ skills/ --include=*.md
```

Expected surviving hits, and **only** these:
- `transfer_tables.md` line ~818 and the YAML sample below it — the compose
  keyword the exec block still emits.
- `migrations.md` — only if a step above left the compose keyword named as such.

Any hit naming a *CICL field* is a miss. Fix it.

24.2 — No scheduler:

```
grep -rni "scheduler\|ofelia\|eventbridge\|scheduled_task" doctrine/ skills/ --include=*.md
```

Expected: **zero hits.**

24.3 — No dangling anchors:

```
grep -rn "depends-on-relationships\|consumes-relationships\|specifics/scheduler.md\|(./scheduler.md" doctrine/ skills/ --include=*.md
```

Expected: **zero hits.**

24.4 — The impossibility argument is gone, not merely surrounded:

```
grep -rn "cannot merge\|one DAG\|cyclic digraph" doctrine/
```

Expected: **zero hits.**

24.5 — `clock.md` exists, `scheduler.md` does not:

```
ls doctrine/infrastructure/specifics/clock.md doctrine/infrastructure/specifics/scheduler.md
```

Expected: the first exists, the second is absent.

24.6 — Every relative link in the two files that changed most resolves. For
`doctrine/infrastructure/specifics/clock.md` and
`doctrine/infrastructure/cicl.md`, extract each `](...)` target and confirm the
file exists on disk and, where the target carries a `#fragment`, that a heading
in that file slugifies to it. Report any that do not.

24.7 — Rule list integrity: `cicl.md` § Validation Rules contains exactly 28
numbered items, items 6 and 24 are tombstones, and no other item's number moved.

24.8 — Confirm nothing outside `doctrine/` and `skills/` was modified:

```
git status --short
```

Expected: changes confined to `doctrine/**`, `skills/**`, and this mod folder.
**No file under `docex/src/`, `docex/tests/`, `docex/tables/`,
`docex/test_projects/`, `docex/plans/core/`, or `upgrades/` may appear.**

---

## Out of scope — do not do these

- Do not run or modify the test suite. This mod changes no code.
- Do not update `docex/plans/core/*.md` or `doctrine_excerpts/` + `index.yml`.
  Mod 118 owns the artifact-alignment sweep.
- Do not touch `upgrades/upgrade_1.7.0.md`. Mod 117 owns the guide.
- Do not restructure the flat-form `infra.yml` examples in `transfer_tables.md`
  (~615, ~687) beyond the field rename. Mod 118.
- Do not rewrite § Resilience covers reachability, not resolvability beyond the
  `consumes` → `uses` rename. Mod 114.
- Do not add a validation rule that neither design record specifies. If you
  believe one is required, stop and report.
- No contracts under `infra/contracts/` change: this mod alters no core service
  boundary.
