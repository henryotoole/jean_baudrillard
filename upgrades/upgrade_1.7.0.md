---
version: "1.7.0"
severity: minor
kind: incremental
scope: [machine, project]
---

# Upgrading to doctrine 1.7.0

## Summary

This release finishes what CICL v2 started. It carries **five author-visible
changes** to `infra.yml` and **one behavioural change** to how elastic releases
converge.

| # | Change | What it touches |
| --- | --- | --- |
| 1 | **The vocabulary rename.** What 1.6.0 called a *core service* is now a **codebase**; what it called a *process type* is now a **core service**. | Two `infra.yml` keys, magic refs, one top-level field, two emitted key sets |
| 2 | **One relation named `uses`.** `depends_on:` and `consumes:` are merged into a single field and both old names are deleted. | Every service block |
| 3 | **`role: scheduler` is retired for `role: clock`.** A clock is an ordinary long-running singleton core service that fires a cron loop and **enqueues**; the work happens in a `worker`. | Every scheduled workload — **and its application code** |
| 4 | **Service Connect reconcile triggers off durable state**, and every `aws_ecs_service` now carries `wait_for_steady_state = true`. | Elastic releases only; nothing to author |
| 5 | **A core service declares its API boundaries as `surfaces:`.** Contract format follows the styles a surface declares, not the provider's `role`; each surface compiles to one contract file, and the filename gains a surface segment. | Every provider's service block; **every contract filename** |
| 6 | **Health leaves HTTP.** The container probe becomes `./health.sh <service>`; `GET /health` survives only where a load balancer reads it; the `/health/<codebase>/<service>` fan-out is deleted; `docex` reads liveness and version from the orchestrator. | Every core service; every codebase's script set; staging tests |

`cicl_version` moves `"2"` → `"3"`. Earlier generations are **rejected, not
shimmed** — a project that has not made these edits does not compile.

> **All six changes ride the same `cicl_version: "3"`.** Changes 5 and 6 are as
> breaking as 1–3, and it would be reasonable to expect a `"4"`. They do not get
> one, on purpose: generation 3 was introduced by this same unreleased cut and has
> never shipped, so folding `surfaces:` into it costs nothing — while a `"4"` would
> manufacture a **second** rollback-unavailable boundary
> ([below](#rollback-is-unavailable-across-the-boundary)) inside one release. Do not
> author `cicl_version: "4"`; it is not a recognized generation and will be
> rejected.

> **⚠ If your project has a `role: scheduler`, budget application-code work.**
> Change 3 is not an `infra.yml` edit. A clock's scheduled jobs must be
> **operations on a driving port**, dispatched by name — "run an arbitrary argv
> on a schedule" no longer exists. There is also a **precondition** the migration
> can fail on outright: the codebase must own a queue. Read
> [step 4](#4-role-scheduler--role-clock) before you begin, not when you reach it.

> **⚠ Every contract file is renamed and every codebase gains a `health.sh`.**
> Changes 5 and 6 are not confined to `infra.yml`. Budget: one contract rename per
> provider surface, one new shim script per codebase, and the deletion of every
> fan-out route and every staging-test liveness assertion. Read
> [steps 7–11](#7-declare-surfaces-on-every-provider) before you begin.

> **Read [§ Rollback is unavailable across the boundary](#rollback-is-unavailable-across-the-boundary)
> before you cut.** For exactly one release cycle, prod has no rollback path.

**Why the rename.** After 1.6.0 the doctrine's "core service" had no port, no
command, no replica count, and nothing routed to it — so it was not a service,
and the things that *were* deployed had no noun of their own. 1.6.0's own prose
never absorbed the "process type" vocabulary; the runtime-facing documents kept
saying "core service" for the running thing, because that is what it is. This
release makes the names match what the doctrine already said.

See [`cicl.md § Core Services`](../doctrine/infrastructure/cicl.md#core-services)
for the model, [`cicl.md § Uses Relationships`](../doctrine/infrastructure/cicl.md#uses-relationships)
for the relation, and [`clock.md`](../doctrine/infrastructure/specifics/clock.md)
for scheduled work.

## Machine sync

`git pull` + `setup.sh` handle the resident stratum, the skills, and the `docex`
image. No manual machine-side step.

## Project upgrade

### What does not move

Worth stating plainly, because the blast radius *sounds* larger than it is:

- **`$pr/core/`** — the source directory keeps its name. A codebase root is still
  `$pr/core/<name>/`.
- **`/service`** — the in-container working directory is unchanged, as is the
  `migrate.sh` contract path `/service/migrate.sh`.
- **Emitted *names*.** No container name, hostname, image ref, `Name` tag, or
  ECS/task-definition name changes. (Emitted *output* does change — see
  [step 13](#13-recompile-and-diff-before-deploying) — but nothing is renamed and
  nothing is replaced on that account.) **Contract *paths* are the exception and do
  change** — they gain a surface segment; see [step 8](#8-rename-every-contract-file).
- **The dotted `<codebase>.<service>` target spelling.** A `consumes:` list's
  **contents** transplant into `uses:` verbatim; only the field name changes.
- **`shape_name` tag values** (`core_service`, `backing_service`) — these name a
  *deployed* resource, so `core_service` is already correct under the new
  vocabulary.
- **`schema_owned_by`** — same key, same value. It named a codebase before and
  still does; only the doctrine's wording for it changed.
- **The four Dockerfile stages**, and `/service` above. `health.sh` is a new file in
  an existing place — not a new stage and not a new working directory.
- **A `web` core service's `GET /health` and its `{version: "x.x.x"}` body.** It
  survives, and staging tests may still assert it against the injected
  `PROJECT_VERSION`. What changed is that it stopped being *universal*.
- **`health_check_path` on `web`-network core services**, and the ALB target-group
  probe it feeds. Same field, same value, same one consumer.
- **Cron expressions and `schedules:`.** Untouched by changes 5 and 6 — as are
  `schema_owned_by` and the `shape_name` tag values above.

### 1. Repin + sync the shim

Standard: bump `docex_version` in `project.yml` to `1.7.0` and re-run the shim
install. `cicl_version` is bumped in step 12 — **not yet**, or every compile fails
until the rest of the edits land.

### 2. Rename the two `infra.yml` keys

Top-level `core_services:` → `codebases:`. The nested `processes:` → `core_services:`.

```yml
# BEFORE (cicl_version 2)
core_services:
  api:
    secrets: { ... }
    env:     { ... }
    processes:
      web:
        role: web
        command: [...]

# AFTER (cicl_version 3)
codebases:
  api:
    secrets: { ... }
    env:     { ... }
    core_services:
      web:
        role: web
        command: [...]
```

Nesting, indentation, and every field inside are unchanged. The codebase-level
block still accepts exactly `{core_services, secrets, config, env}`.

> **Do not do this with a single `s/core_services/codebases/`.** The old top-level
> key and the new *nested* key share the spelling `core_services`, so an
> order-independent replace produces `codebases: api: codebases:`. Rename the
> **nested** `processes:` first, or anchor the top-level replace to column 0.

> **Do this rename before steps 3 and 4.** Step 3 authors `uses` targets spelled
> `<codebase>.<service>` — vocabulary this step establishes. Merging `uses` first
> means writing every target twice.

### 3. Merge `depends_on` + `consumes` into `uses`

`uses` is now the **single** relation between services. It says *"I speak to this
boundary"* — nothing more. A `uses` entry names either a **backing service**,
bare, or a **core service**, dotted and fully qualified.

Mechanically: rename `depends_on:` → `uses:`, and merge any `consumes:` list on
the same core service into that one list.

```yml
# BEFORE — as your file stands after step 2
codebases:
  api:
    core_services:
      web:
        depends_on: [appdb, cache]
        consumes:   [api.worker]

backing_services:
  cache:
    role: cache
    depends_on: [appdb]      # ← delete outright

# AFTER — this step
codebases:
  api:
    core_services:
      web:
        uses: [appdb, cache, api.worker]

backing_services:
  cache:
    role: cache
```

**`depends_on:` is deleted from backing services entirely.** A backing service
now declares no outbound edges at all and is a **sink** in the relation graph.
Where an engine genuinely needs another container beneath it, that is an *engine*
concern and belongs in its transfer table's `defaults` block, not in `infra.yml`.

**Both old names are hard errors, not silent aliases.** A `depends_on:` or
`consumes:` you miss fails loudly at compile rather than being quietly accepted.

> **The consequence that will surprise people: project-level startup ordering is
> gone.** The compiler emits **no** compose `depends_on:` / `condition:` on any
> core-service block, on either foundation. Removed, not deprecated.
>
> For a real project this means boot code that was leaning on the compose gate —
> which `dev` and `test` were silently supplying and elastic `prod` never was —
> will now fail on a cold start. That is the connection-resilience mandate
> becoming *visible*, not a regression: a service that connects at boot with no
> retry used to work in `dev`, work in `test`, and break the first time the
> project went elastic. `dev` should *expose* non-resilient boot code, not
> shelter it.
>
> Expect a burst of connection-refused lines on `envinfra up` while backing
> services initialize. That is correct signal — you can watch backoff working. A
> service that *crashes* rather than retries fails the bring-up, which is the
> right outcome.

**The exec block keeps its gate, and it is not a carve-out.** `migrate.sh`,
`test.sh`, and `build.sh` are one-off batch jobs whose entire contract is an exit
code, and for a batch job "be tolerant of a missing dependency" *means* "wait
until it is ready". So the per-codebase `-exec` block still carries
`condition: service_healthy` over the union of that codebase's
**backing-targeted** `uses` edges. `migrate.sh` still waits for its database.
Nothing an author writes.

Rule changes, briefly: rules 6 and 24 are **retired** and carry tombstones at
their original numbers; rule 7 collapses to a single clause; rule 25 is now the
`uses` shape rule.

Per [`cicl.md § Uses Relationships`](../doctrine/infrastructure/cicl.md#uses-relationships)
— the same section carries the connection-resilience mandate that replaced the
retired startup gate.

### 4. `role: scheduler` → `role: clock`

**Skip this step entirely if your project declares no `role: scheduler`.**

> **Precondition — read this before editing anything.** A clock **defers**; it
> does not work. Its only job is to call a driving port that *enqueues*, and the
> work happens in a `worker`. The reason is that **only the codebase that owns a
> schema may write to it**, and the doctrine's queue is a library-backed queue
> whose tables are created by the schema-owning codebase's `migrate.sh`.
>
> Therefore: **the codebase hosting a clock must own a queue.** A codebase with
> scheduled work but no queue and no worker *cannot host a clock*. The honest
> answer in that case is that the schedule moves to a codebase that can — or the
> codebase grows a queue and a worker.
>
> This is the single most likely place a downstream upgrade stalls. Establish it
> first, before you restructure any `infra.yml`.

Then:

- Each `role: scheduler` core service becomes **one** `role: clock` core service
  — a long-running singleton, not an invocation. It gets a paired otelcol sidecar
  and a container probe like any other core service. It does **not** get a `port` or
  a `health_check_path`: nothing addresses a clock and nothing routes to it, so
  rules 32 and 33 respectively make the first unnecessary and the second an error.
  See [step 10](#10-move-health_check_path-drop-decorative-ports).
- `schedule:` becomes **`schedules:`**, a map of *job name* → **bare 5-field UTC
  cron string**. Job names are identifiers, because they are the dispatch keys the
  clock's controller looks up.
- Each old job's `command` argv becomes a **driving-port method**, dispatched by
  name in a `Cron`-mechanism controller. *"Run an arbitrary argv on a schedule"*
  is no longer available — scheduled work must be an operation on a driving port,
  which forces it into the composed, observable, tested application instead of a
  side door. Argv-against-the-image survives where it belongs: the per-codebase
  exec container and `migrate.sh`.

```yml
# BEFORE — as your file stands after step 2
codebases:
  reaper:
    core_services:
      prune:
        role: scheduler
        schedule: "0 3 * * *"
        command: ["python", "/service/dist/prune.py", "--older-than", "30d"]

# AFTER — this step
codebases:
  api:                                   # the codebase that owns the schema
    core_services:
      clock:
        role: clock
        command: ["python", "/service/dist/entrypoints/clock.py"]
        # No `port` and no `health_check_path` — see step 10. Its liveness is the
        # container probe `./health.sh clock`, which stats the cron loop's tick file.
        networks: [internal]
        uses: [appdb, api.worker]
        schedules:
          prune_pings: "0 3 * * *"
        resources: { cpu: 0.25, memory: 512MB }
```

The architecture chain the entrypoint implements:

```
entrypoints/clock.py        runtime host — the cron loop
  → ContJobsCron            driving adapter: job name → port method
    → ContJobs              driving port (shared with the HTTP and CLI controllers)
      → alogic
        → QueueJobs         driven port — canonical `Queue` pattern
          → QueueJobsProcrastinate
```

Every element is already doctrine; a clock is a composition of existing pieces,
not a new pattern. A useful side effect: because the driving port is shared with
the HTTP and CLI controllers, every scheduled job is also reachable over HTTP and
on the command line, so firing one by hand in `dev` stops being a special path.

> **⚠ No cron dialect translation anywhere.** The compiler passes each expression
> through unchanged. Any 6-field expression, `?`-day substitution, or
> provider-numbered day-of-week inherited from EventBridge **must be rewritten by
> hand** to plain 5-field UTC. Nothing translates it and nothing warns.

Other behaviour changes worth knowing before you are bitten by one:

- **One clock per codebase**, not per project. Codebases never share code, so a
  clock can only enqueue into its own codebase's queue; cross-codebase scheduling
  is out.
- **`replicas` is forbidden** on a clock (rule 26). It is a singleton — N replicas
  would mean N ticks and N enqueues per fire.
- **`web` is forbidden** in its `networks` (rule 27). A clock serves no public
  boundary.
- **On elastic the clock deploys stop-then-start**
  (`deployment_minimum_healthy_percent = 0`), trading a possible **missed fire**
  for a possible **double fire**. ECS rolling defaults briefly run two tasks, and
  a tick landing in that window fires twice.
- **No backfill.** A fire missed during a deploy or an outage is not retroactively
  run. The clock fires forward-only, and jobs must be idempotent regardless.
- **A clock is invisible to staging tests.** Nothing routes to it, so the stage
  tester cannot reach it by any route. A clock has **no `/health`** — it binds no
  application socket at all; its liveness is the **container probe**
  (`./health.sh clock`), which on elastic gets a wedged clock killed and replaced.
  Real enforcement, but local. This is now true of **every** non-`web` core service,
  the worker included — the clock is the first case of the general rule rather than
  a special case.

[`clock.md`](../doctrine/infrastructure/specifics/clock.md) is the rule of record.
A **worked reference implementation** — entrypoint, controller, ports, queue
adapter, and the jobs the clock defers — ships in the doctrine's smoke projects at
`docex/test_projects/*/core/api`. It is a real tree, and reading it is faster than
reading this section twice.

### 5. Qualify core magic refs — five segments

Core refs gain the literal `core_services` collection segment, making a ref an
exact path walk through the document:

```
# BEFORE — four segments
${core_services.api.worker.host}

# AFTER — five segments
${codebases.api.core_services.worker.host}
```

Backing refs are **unchanged** at three segments: `${backing_services.appdb.host}`.

The compiler rejects the old form with a message naming the exact replacement,
and rejects `processes` in the collection slot specifically — which is the
mistake a hand-migration makes:

```
${codebases.api.worker.host}
  -> This looks like the pre-1.7.0 four-segment form.
     Did you mean ${codebases.api.core_services.worker.host}?

${codebases.api.processes.worker.host}
  -> Body segment 2 must be the literal `core_services`, not 'processes'
     — a core ref is a path walk through the document.
```

### 6. `domain_default_process` → `domain_default_service`

Same value (`api.web`), same meaning (the core service answering the bare
`<env>.<project>.<apex>` host).

> **A trap for anyone reading old configs.** 1.6.0 renamed this field the *other*
> direction — `domain_default_service` → `domain_default_process` — so the 1.7.0
> name is the **pre-1.6.0 spelling with a different value shape**:
>
> | Version | Field | Value |
> | ------- | ----- | ----- |
> | < 1.6.0 | `domain_default_service` | `web` — **bare** |
> | 1.6.0 | `domain_default_process` | `api.web` — dotted |
> | ≥ 1.7.0 | `domain_default_service` | `api.web` — dotted |
>
> So the *name* round-trips but the *value* does not. A pre-1.6.0 config carrying
> `domain_default_service: web` is **not** valid 1.7.0 config, and it will not
> look wrong at a glance. Rule 12 rejects the bare form, so the error is loud —
> but do not assume a `domain_default_service` in an old file means what it means
> now.

### 7. Declare `surfaces:` on every provider

A core service is a **provider iff it declares `surfaces:`** — a map of named
boundaries, each with `api_styles:`.

- `api_styles` → format: `rest` / `stream` / `webhook` → **openapi**;
  `rpc` / `events` / `socket` → **asyncapi**. `graphql` and `proto` are **defined
  language that is not implemented** and compile-fail with a named "format not yet
  implemented".
- **One format per surface**, or compile fails (rule 29) telling you to split.
  `[rest, stream, webhook]` is one surface; `[rest, rpc]` is two.
- Name a surface after its primary style unless a core service declares two on the
  same style. Surface names take the codebase/core-service pattern (rule 30) — no
  dots, because a dot would make the four-segment filename parse ambiguous.
- **A `uses` edge onto a core service that declares no surface is a compile error**
  (rule 31). Conversely a core service nothing uses and that describes no boundary
  — a `frontend.web` serving a browser, a `clock` — declares **none**, and needs no
  contract.

The seeds' worked shape, which is also the only instance of **two surfaces of one
format** in the doctrine's own trees:

```yml
codebases:
  api:
    core_services:
      web:
        surfaces:
          rest:
            api_styles: [rest]        # → api.web.rest.openapi.yml
      worker:
        # TWO surfaces, ONE format. What makes them two rather than one is the
        # CONSUMERS: `api.web` calls the rpc boundary synchronously and waits for
        # a count; the queues are produced onto by `api.web` and `api.clock` and
        # consumed here, asynchronously and with no reply.
        surfaces:
          rpc:
            api_styles: [rpc]         # → api.worker.rpc.asyncapi.yml
          events:
            api_styles: [events]      # → api.worker.events.asyncapi.yml
      clock:
        # No `surfaces:` at all — nothing addresses it and nothing may `uses` it,
        # so it has no boundary to describe and carries no contract.
```

### 8. Rename every contract file

`$pr/infra/contracts/<codebase>.<service>.<format>.<ext>` →
`<codebase>.<service>.<surface>.<format>.<ext>`. Worked example:
`api.web.openapi.yml` → `api.web.rest.openapi.yml`.

> **⚠ Move the file; do not copy it.** A leftover three-segment name sitting
> **beside** its four-segment replacement satisfies every "the contract exists"
> check and is caught only by `_gate_contracts`' **orphan** arm. `git mv`, then
> confirm with the grep in [Verification](#verification) item 8.

**Exactly one extension per format** — `openapi`/`asyncapi` → `.yml`. A `.yaml`
that used to be accepted no longer is. And a core service with two surfaces gets
**two** files.

### 9. Write `health.sh`

The **fourth codebase shim**, at `$pr/core/<codebase>/health.sh`, alongside
`build.sh` / `test.sh` / `migrate.sh`. Required for **every** codebase.

- **The exit code is the entire contract.** 0 means this core service is working.
  **Nothing reads stdout** — Docker captures probe output and ECS does not, so it can
  never be a cross-foundation channel.
- **Invoked per core service**, as `./health.sh <service>` — the compiler emits the
  argv. Branch on `$1`, and make the fall-through case **fail loudly**: an arm that
  exits 0 reports every core service healthy forever.
- **A request-cycle service** (`web`) may curl its own route — that is now the
  project's choice inside the shim, not infrastructure the doctrine mandates.
- **A loop-owning service** (`worker`, `clock`) reports the **loop's** liveness: the
  loop touches a tick path each iteration **from inside itself** and the shim `stat`s
  its mtime. An **absent** tick file must **fail**. Do **not** implement this with a
  liveness thread — it answers healthy forever while no work moves.
- Thresholds are doctrine-fixed: ≤**10 s** tick cadence even when idle, **30 s**
  staleness. Cadence in the entrypoint, threshold in the shim.
- Copy the script into the `dev` **and** `prod` Dockerfile stages. Whatever it needs
  (a shell, `curl`, `stat`) is the project's to install — **`curl` is no longer
  doctrine-mandated**, so an image that dropped it must add it back only if its own
  shim uses it.
- The worked implementation ships at `docex/test_projects/*/core/api/health.sh`.
  It is a real script and reading it is faster than reading this list twice.

### 10. Move `health_check_path`; drop decorative `port`s

- **`health_check_path` is keyed on network membership, not role** (rule 33).
  Required on **every** `web`-network core service; **forbidden** on every core
  service off it. Delete it from every `worker` and `clock`. A `role: web` core
  service off the `web` network declares **none**.
- **Rule 28 is retired** and its number tombstoned: it required a `port` beside
  `health_check_path`, and rule 33 now confines that field to `web`-network services
  where rule 15 already requires a port — so the obligation is *redundant*, not
  merely obsolete.
- **Drop `port` from any core service nothing addresses directly** (rule 32). A
  target reached only over a queue or broker needs none. "Directly addressed" means
  **the consumer holds a magic ref to one of the target's provided parts**, and it is
  keyed on the **edge**, not the target — one consumer may call an `rpc` surface
  while another enqueues, and only the first implies a port. `web`-network targets
  are exempt: rule 15 requires a port there regardless.

  > **⚠ On elastic, dropping a `port` also drops a Service Connect name.** A core
  > service registers a resolvable name only where it declares a `port`. That is
  > correct by construction — a target nothing addresses is a target nothing needs
  > to resolve — but if a consumer *does* reach it and you removed the port anyway,
  > the failure is a resolution error **while both services report healthy**. Check
  > your magic refs before deleting a port.

### 11. Delete the fan-out and the staging-test liveness assertions

- **Delete every `GET /health/<codebase>/<service>` route** and the handler behind
  it. The one-hop recursion rule goes with it — it existed solely to stop the
  fan-out looping on the legal `web ↔ worker` cycle.
- **Remove liveness assertions from staging tests.** Staging tests narrow to what
  **requires being outside**: TLS, DNS, reverse-proxy routing, and critical-path
  smoke tests through the real edge. They **may not assert anything about a
  non-`web` core service** — they cannot reach one at all now. A project wanting an
  end-to-end assertion through a worker drives the public edge and observes the
  effect.
- **`docex stagetest` asserts liveness instead, before it builds the tester image**,
  reading the orchestrator (`docker inspect` over SSH on fixed, `describe_tasks` on
  elastic). This is *more* truthful: version comes from the deployment record rather
  than from a self-report a stale container will happily falsify. **When the
  orchestrator and a self-report disagree, the orchestrator wins.**
- If a `web` route was serving *only* the fan-out, delete it. If it also served
  backing-service reachability diagnostics worth keeping, **move them to a path that
  is not `/health/...`** so no reader concludes the fan-out survived under a
  narrower name (the seeds moved theirs to `/diagnostics/{probe,events}`).

### 12. Bump `cicl_version` to `"3"`

Last, after steps 2–11. Previous generations are **rejected, not shimmed**.

### 13. Recompile and diff before deploying

```sh
./bin/docex compile
git diff infra/output/
```

**Every difference must attribute to one of the causes below.** Anything that
does not is a defect.

| Cause | Expected difference |
| --- | --- |
| The rename | The two elastic env-tier tag **keys** (`service` → `codebase`, `process` → `service`) and the two OTel resource attribute keys (`docex.core_service` → `docex.codebase`, `docex.process_type` → `docex.service`). **Values unchanged in all four.** |
| The `uses` merge | `depends_on:` and `condition:` **disappear** from every core-service compose block. The per-codebase `-exec` block's gate stays. |
| The reconcile fix | `wait_for_steady_state = true` appears on **every** `aws_ecs_service`. |
| `clock` *(only if the project had a scheduler)* | `aws_scheduler_schedule`, the `scheduler.amazonaws.com` invocation role and its policy, and the Ofelia container + INI all **disappear**. A task definition, an `aws_ecs_service`, a log group, and a sidecar appear. The clock alone carries `deployment_minimum_healthy_percent = 0` / `deployment_maximum_percent = 100` and `DOCEX_SCHEDULES_YAML` in its env. A **new output file** appears: `infra/output/<env>/schedules.yml`. |
| The command probe (change 6) | Every core-service block's probe becomes `["CMD", "./health.sh", "<svc>"]` — a compose `healthcheck:` on fixed, a container `healthCheck` on elastic. The `curl -f http://localhost:$PORT$PATH` form **disappears everywhere**. `startPeriod: 10` **appears on elastic only.** The `-exec` block, the elastic `_migrate` task definition, and every `-otelcol` sidecar carry **no** probe — as before. |
| `health_check_path` off non-`web` (change 6) | Those core services lose their path-derived fixed `healthcheck:` and receive the command probe from the role table's `defaults` instead. They never had ALB target groups, so nothing changes ALB-side. `web` services' `target_group` health check is **unchanged**. |
| `surfaces:` (change 5) | **Nothing.** `surfaces:` drives CI and contract-file resolution and reaches **no** emitted artifact. |

> **Contract renames produce no diff in `infra/output/`, and that is expected.**
> Contracts live in `infra/contracts/` and are never compiled into anything. If you
> are looking for the rename in the recompile diff to confirm you did step 8, look
> at `git status` on `infra/contracts/` instead — and at
> [Verification](#verification) item 8, which is the check that actually catches a
> half-done rename.

Any change to a container name, hostname, image ref, `Name` tag, or `role` value
is a **defect** — stop and investigate rather than deploying. That guard survives
every cause above and is the one actually worth having. (**A contract path is not
in that guard**: contract paths *do* change in this release, and they never appear
in emitted output — see step 8.)

Two harmless artifacts to expect:

- **Tag blocks reorder** in `main.tf`. Tags render alphabetically, and `codebase`
  sorts before `descriptor` where `service` sorted after `role`. HCL `tags` is a
  map, compared order-insensitively — no churn.
- `tofu plan` shows **tag updates in place**, not replacements, because tag
  *values* are unchanged.

> **`wait_for_steady_state` changes what an apply means.** An elastic apply now
> **blocks on rollout** and **fails** if a service cannot converge, rather than
> returning immediately and letting the release proceed. Applies take longer, and
> a broken image now fails the apply instead of surfacing later as a health-check
> problem. That is the intent — but budget the wall-clock time.

### 14. Redeploy

Nothing special. No teardown, no state surgery.

### 15. ⚠ REQUIRED — update saved telemetry queries, dashboards, and alerts

**This is a manual action, not a note.** It cannot be automated and it fails
silently if skipped.

The OTel resource attribute keys change:

```
docex.core_service  ->  docex.codebase
docex.process_type  ->  docex.service
```

Consequences:

- **Every existing time series splits at the upgrade boundary.** Signals emitted
  before carry the old keys; signals after carry the new. Nothing reconciles them.
- **Saved HyperDX queries, dashboards, and alerts filtering on the old keys stop
  matching new data without erroring.** They return an empty or truncated result
  set, which reads as *"no traffic"* rather than *"wrong key"*.
- **An alert built on an old key therefore fails silent and green** — it stops
  firing, and nothing announces that it stopped.

Go through every saved query, dashboard panel, and alert rule that filters or
groups on `docex.core_service` or `docex.process_type` and move it to the new
key. Do this **at the same time** as the deploy, not after.

Dual-writing both key sets for one release was considered and rejected: it
doubles the attribute payload on every signal and defers this same work rather
than removing it.

## Doctrine / behavior notes

- **`docex` error messages now use the new nouns.** Several messages previously
  said "core service" where they meant the codebase — e.g. *"core service 'api'
  declares no process type 'nope'"* is now *"codebase 'api' declares no core
  service 'nope'"*. If you grep logs or CI output for message text, update the
  patterns.
- **Error messages now name `uses`.** Anything grepping CI output for the words
  `depends_on` or `consumes` needs updating for the same reason.
- **`docex build <name>`** now names a **codebase** in its help text and usage
  string. Positional, so no invocation breaks.
- **`docex describe --format llm`** emits `"codebase"` where it emitted
  `"core_service"`, and `"service"` where it emitted `"process"`. The `"kind"`
  value stays `core_service` / `backing_service` (a shape name).
- **`docex roles` lists six roles, and `scheduler` is not among them.**
- **`docex dag` derives solid and dashed edges from the *target kind*** of each
  `uses` entry, rather than from which field an edge happened to be declared in.
- **The `/health` fan-out is deleted, not respelled.** The route, the one-hop
  recursion rule that existed solely to stop it looping on the legal `web ↔ worker`
  cycle, and the `docex check` gate that enforced the path spelling are all gone.
  `docex` never called the endpoint it mandated; the only runtime consumer was
  developer-written stage-test code, which step 11 tells you to delete.
- **`docex check`'s gate roster goes ten → nine.** `_gate_health_endpoints` went
  whole (fan-out, one-hop rule, and the arm demanding both `port` and
  `health_check_path` on every core `uses` target). `_gate_healthcheck_tooling` —
  the `curl`-in-the-image gate — was **deleted rather than narrowed**, because
  `infrastructure.md § Codebase Containers` withdrew the `curl` mandate: a gate
  enforcing a requirement the rule of record has withdrawn is worse than no gate.
- **One health assertion survives, as `contract_health_path`.** Where a
  `web`-network core service also declares an `openapi` surface, one of its openapi
  contracts must declare a `GET` on that core service's **declared**
  `health_check_path` — read from the field, never hardcoded to `/health`. **Any
  one** openapi surface satisfies it: requiring it in every surface would force a
  `rest_admin` contract to document a route outside its own boundary.
- **`codebase_scripts` now requires `health.sh`** for every codebase,
  unconditionally, beside `build.sh` and `test.sh`. `migrate.sh` stays conditional
  on schema ownership.
- **`docex stagetest` fails before it builds the tester image** if the orchestrator
  reports any core service unhealthy or on the wrong version — `DeployedServiceUnhealthy`
  — or if it cannot get an answer at all — `OrchestratorStateUnreadable`. **There is
  no flag to disable it.** An empty result set never reads as healthy.
- **Lexicon:** it gains **Surface**. `api_styles` and "probe" get **no** entries,
  because the lexicon defines concepts rather than CICL fields.
- **`specifics/scheduler.md` is replaced by
  [`specifics/clock.md`](../doctrine/infrastructure/specifics/clock.md)**, and
  every inbound pointer moved with it — a project author looking for *"how do I
  schedule work"* still finds exactly one document.
- **Lexicon:** the `Process Type` entry is **deleted**. `Codebase` is promoted to
  the primary noun; `Core Service` is redefined as the deployment unit. The
  old→new mapping lives here, in this guide, and nowhere else.
- **Historical records keep the old vocabulary on purpose** — mod docs, prior
  upgrade guides, and past `CHANGELOG` entries were true when written and are not
  rewritten.

### Rollback is unavailable across the boundary

For exactly **one release cycle** after adopting 1.7.0, prod has no rollback
path. `docex rollback` refuses at cheap pre-flight — before any worktree is
created and before any apply — because rollback recompiles the *target* version's
`infra.yml` with the *current* docex (`cicd.md § Rollback` step 3), and every
existing tagged release declares `cicl_version: "2"`.

Verbatim:

```
rollback aborted — cannot roll back across the CICL v2→v3 boundary.
Nothing has been touched.

Target v0.4.1's infra/infra.yml declares cicl_version "2". This docex compiles
only cicl_version "3", and rollback recompiles the target's infra.yml with the
*current* docex (cicd.md § Rollback step 3) — so no rollback to this target can
succeed.

Fix forward instead:
  1. On main, fix the defect and bump project.yml past the broken version.
  2. ./bin/docex check  →  merge  →  containerize  →  release <env>

Once a second cicl_version "3" release exists, rollback works normally.
```

This is the same trap the 1.6.0 upgrade carried at its own v1→v2 boundary, so the
shape should be familiar rather than new breakage — and there is no mitigation
beyond **keeping the window short**: get a second `cicl_version: "3"` release out
promptly, and prefer not to schedule this upgrade immediately before a period you
cannot supervise. The refusal is cheap and early by design — an operator
mid-outage learns it before anything is touched, rather than from a compile error
inside a worktree.

## Verification

1. `./bin/docex compile` succeeds and every line of `git diff infra/output/`
   attributes to a cause in [step 13](#13-recompile-and-diff-before-deploying).
2. `./bin/docex check` passes.
3. Grep your `infra.yml` for **zero** occurrences of: `processes:`,
   `domain_default_process`, `${core_services.`, `depends_on:`, `consumes:`,
   `role: scheduler`, and `schedule:` (singular).
4. If the project has a clock: `infra/output/<env>/schedules.yml` rendered for
   every env, and each clock's block carries `DOCEX_SCHEDULES_YAML` as a literal
   YAML value rather than a path.
5. After deploying, confirm a **new** signal in the observability backend carries
   `docex.codebase` and `docex.service`, and that at least one dashboard you
   migrated in step 15 is populating.
6. If the project has a clock: its container health is green, and a scheduled job
   has visibly fired and been drained by the worker.
7. On elastic, confirm `tofu plan` is clean after apply (no pending replacements).
8. **No three-segment contract filename survives.** This is the likeliest mistake
   in this upgrade and **an existence-only check cannot see it** — a leftover
   `api.web.openapi.yml` beside a correct `api.web.rest.openapi.yml` satisfies every
   "the contract exists" assertion, because the file the gate wants is also present.
   The thing that catches it is **`_gate_contracts`' orphan arm**, which fails on a
   contract file matching no declared surface and names the four-segment form.
   Confirm by eye first, then let the gate confirm:
   ```sh
   ls infra/contracts/
   # every name must have FOUR dot-separated stem segments before the extension:
   ls infra/contracts/ | awk -F. 'NF!=5 {print "SUSPECT: "$0}'
   ./bin/docex check          # `contracts_exist` must pass
   ```
   `NF != 5` because the extension is the fifth field. A hit is either a leftover
   three-segment file or a surface you failed to declare.
9. **Zero `health_check_path` off the `web` network.** For every core service whose
   `networks:` omits `web`, the field is absent. Rule 33 rejects it, so a miss is a
   loud compile failure rather than a silent one — but check before you compile, so
   you fix them all at once.
10. **Zero fan-out routes.** `grep -rn '/health/' core/` returns only a `web`
    service's own `health_check_path` route. No `<codebase>/<service>` form anywhere.
11. **`docex check` passes `codebase_scripts` and `contracts_exist`**, and the roster
    reports **nine** gates.
12. **Every core service's container probe reports healthy on both foundations you
    run** — `docker inspect --format '{{.State.Health.Status}}'` on fixed, container
    `healthStatus` on elastic.
13. **A loop-owning core service observed FAILING with a stale tick.** Wedge the loop
    and confirm the probe goes unhealthy; then un-wedge and confirm it recovers.
    Green-only is not evidence: the most likely subtle error in step 9 is a tick
    written by a liveness *thread* rather than by the loop, which passes every
    positive test and answers healthy forever while no work moves. **Wedge from the
    host against `docker inspect --format '{{.State.Pid}}'` — `kill -STOP 1` inside
    a container is a no-op**, because PID 1 is immune to `SIGSTOP` in its own
    namespace.

---

*Optional further reading.* The design records behind this release —
the [rename](../docex/plans/advances/005_process_type_solidification/codebase_core_service_rename.md),
the [`uses` merge](../docex/plans/advances/005_process_type_solidification/uses_relation_merge.md),
and the [clock](../docex/plans/advances/005_process_type_solidification/clock_core_service.md)
from advance 005, and
[surfaces and health](../docex/plans/advances/006_surfaces_and_health/surfaces_and_health.md)
from advance 006, which covers steps 7–11 — carry the reasoning behind each
decision. Nothing in this guide requires them.
