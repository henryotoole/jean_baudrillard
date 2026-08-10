# Mod 130 — seed projects: recompile, docs, git cadence

Sixth mod of [advance 006](../../advances/006_surfaces_and_health/advance_plan.md),
and the one that lands what [mod 129](../129_seed_source_contracts_infra/overview.md)
deliberately left half-done: the compiled output, the projects' own planning docs,
and the three-step git cadence.

**Territory.** `test_projects/{fixed,elastic}/infra/output/**`,
`test_projects/*/plans/core/*`, `test_projects/*/CHANGELOG.md`, and the **inner
repos' git state**. Mod 129's source, contracts, and `infra.yml` are reviewed here
but not revised — except to fix a defect the output diff exposes, and § 2 records
that no such defect was found. `docex`'s own `plans/core/*`,
`doctrine_excerpts/`, `PRE_CUT_CHECKLIST.md` and `upgrades/` are mod 131's.

---

## 1. The completion criterion, corrected

Sarge's kickoff for mod 129 promised that full `./bin/docex check` green would be
this mod's criterion. **It is not, and cannot be.** `check` refuses to run on
`main` or against a dirty tree, and `test_projects.md` A.2.1 requires both inner
repos to *stay* on `main`, clean, with `v<version>` at HEAD — with an explicit
carve-out naming only walk boxes C.6/D.8 as permitted to break that. Reaching
`check` needs the walk's feature-branch restructure, so it is a **walk** activity
(boxes C.7 / D.7).

This is the fourth mis-specified completion signal in this advance and the second
time this particular one has been raised — mod 129's Q2 raised it, and sarge
recorded the correction in the kickoff rather than letting this mod rediscover it.
Recorded here so a B-audit reading "check green" in the advance plan's phase-3
prose finds the ruling instead of a missing gate.

**The criteria actually used, all three met (§ 2, § 3):**

1. `./bin/docex compile` is byte-for-byte idempotent in each project.
2. Every hunk of the output diff attributes to a named cause.
3. `python -m pytest tests` still 1174 passed / 18 deselected.

---

## 2. The output diff, cause by cause

**29 hunks across 8 files.** Enumerated mechanically (`git diff -U0 | grep -c '^@@'`),
then attributed. Every hunk attributes; nothing resisted. The causes were written
down from the mods 125–129 change set *before* the diff was read, per the upgrade
guides' discipline.

### 2.1 The causes

| # | Cause | Origin | Visible? |
| - | ----- | ------ | -------- |
| **A** | The container probe moved into `defaults` on all three core roles, as `["CMD", "./health.sh", "${service}"]` on both foundations. | mod 127 (`tables/roles/{web,worker,clock}.yml`) | yes — 23 hunks |
| **B** | `api.clock` lost its `port`. | mod 129 (`infra.yml`) | yes — 4 hunks |
| **C** | On elastic, `web` gains a **container** probe it never had: pre-127 the `web` role's `health_check_path` routed to `target_group` *only*, so `api-web`'s task definition carried no `healthCheck` at all. A `defaults` probe lands on the engine's default target — the task definition — and `render_task_definition` lifts it explicitly (`hcl.py:395`). | mods 127 (table) + 127 (`emit/hcl.py`) | yes — 2 hunks |
| **D** | `health_check_path` was deleted from `worker`/`clock` in both the tables and both `infra.yml`s. | mods 127, 129 | **no independent hunk** — see § 2.3 |
| **E** | `surfaces:` was added to `api.web` and `api.worker`. | mod 129 | **no hunk** — see § 2.3 |
| **F** | The four contract files were renamed to four segments and a fifth added. | mod 129 | **no hunk** — see § 2.3 |

### 2.2 Attribution, hunk by hunk

| File | Hunks | Attribution |
| ---- | ----- | ----------- |
| `fixed/…/dev/docker-compose.yml` | 3 | **A** ×3 — `clock`, `web`, `worker` |
| `fixed/…/test/docker-compose.yml` | 3 | **A** ×3 |
| `fixed/…/stage/docker-compose.yml` | 3 | **A** ×3 |
| `fixed/…/prod/docker-compose.yml` | 4 | **A** ×4 — `clock`, `web`, `worker-1`, `worker-2` (`replicas: 2` is honoured in `prod` only, so prod has one extra worker compose service) |
| `elastic/…/dev/docker-compose.yml` | 3 | **A** ×3 |
| `elastic/…/test/docker-compose.yml` | 3 | **A** ×3 |
| `elastic/…/stage/main.tf` | 5 | **A** ×2 (`api-clock`, `api-worker` `healthCheck.command`); **B** ×2 (`api-clock`'s `portMappings` block deleted; `api-clock`'s Service Connect `service {}` block deleted); **C** ×1 (`api-web` gains `healthCheck`) |
| `elastic/…/prod/main.tf` | 5 | identical to stage |
| **total** | **29** | **A** 23 (19 compose + 4 HCL), **B** 4, **C** 2 → 23 + 4 + 2 = **29** ✓ |

On the two `main.tf` files, cause **B** produces exactly two hunks each because the
clock's `port` fed two separate emissions, in two separate resources:

- `aws_ecs_task_definition.api-clock` → the container's `portMappings`.
- `aws_ecs_service.api-clock` → the `service_connect_configuration`'s inner
  `service {}` block.

The second is the SC 2.6 amendment's mechanism made visible. `hcl.py:788` is
explicit — *"Every service participates so it can resolve peers. Services with a
port also register a `service {}` block so peers can resolve them."* The clock's
config survives with `enabled = true` + `namespace` and no `service {}`: a
**client-only** Service Connect membership. It still resolves `api-worker` and the
sidecars; nothing can resolve *it*, which is correct because nothing addresses a
clock. This is the shape a port-less worker would have taken, and the amendment's
whole point was to keep `api.worker` out of it so the reconcile consumer set stays
non-empty.

### 2.3 The three causes with no visible hunk

These are the ones worth stating, because "no diff" is where a silently-dropped
emission would hide.

- **D — `health_check_path` off `worker`/`clock`.** It produces no hunk of its own
  because it is the *source* half of cause A for those two services, not an
  independent change. Pre-127 the fixed probe came from the field's `fixed:`
  translation and the elastic probe from the field routed to
  `container_definition`; post-127 both come from `defaults`. The emitted probe
  therefore *changed content* (one hunk, cause A) rather than appearing or
  disappearing. Its cadence keys — `interval: 30s`, `timeout: 5s`, `retries: 3`,
  and elastic's `startPeriod: 10` — are byte-identical across the move, which is
  why the hunks are three lines wide instead of ten.
- **E — `surfaces:`.** Zero output hunks, and this was verified rather than
  assumed: `surfaces` is read only by `cicl/model.py`, `cicl/validate.py`, and
  `pipeline/check.py`. `grep -rl surfaces src/docex/emit/ src/docex/compile.py`
  returns nothing. A surface is a *validation and contract* concept; it emits no
  infrastructure. Had a hunk appeared here it would have been a defect.
- **F — contract renames.** Contracts are not compiled; `infra/contracts/` has no
  emitter. Zero hunks expected and zero found.

### 2.4 The negative assertions, tested rather than eyeballed

Success criterion 2.1 has a negative half — the probe must land on core-service
blocks **only**. Read out of the compiled artifacts by a census that walks all
eight, rather than by scrolling the diff:

- **All six compose files**: `./health.sh <svc>` on exactly the three (four in
  fixed prod) core services. Nothing on any `*-otelcol` sidecar or on the
  `*-api-exec` block — the latter is what
  [`exec_service.md`](../../../../doctrine/infrastructure/specifics/exec_service.md)
  requires. `appdb` keeps `pg_isready` (the postgres engine's own probe,
  untouched); `events` and `probe` have none, as before.
- **Both `main.tf` files**: `healthCheck` present on `api-clock`, `api-web`,
  `api-worker`; **absent** on all three `*-otelcol` container definitions and on
  the migrate task's `api` container.

**Result: `CONTAINERS 80`, `VIOLATIONS 0`, exit 0.**

#### The census command, verbatim

Recorded in full so **mod 131 can lift it into a `PRE_CUT_CHECKLIST.md` box
rather than re-deriving it**, and so a future walk can re-run the negative half of
SC 2.1 mechanically. Per `test_projects.md`'s own lesson, key the box on **what
the command prints**: the assertion is `VIOLATIONS 0` and exit 0. The
`CONTAINERS` line is a corroborating census and is deliberately **not** a hard
number — hard-coding `80` is precisely the mistake D.9/D.11's "if N is not 2"
made, and it becomes wrong the moment a seed gains an environment or a replica.

Run from `docex/`:

```python
"""Probe census over both seeds' compiled artifacts. Run from docex/.

Prints one PROBE/BARE/ENGINE line per container in every compiled artifact, then
a VIOLATIONS count. Expected: VIOLATIONS 0, exit 0.

Rules asserted (healthchecks.md, exec_service.md):
  * a core-service container carries exactly ["CMD", "./health.sh", "<service>"]
  * an `-otelcol` sidecar, an `-exec` block, and a migrate task carry NO probe
  * a backing service's own engine probe (CMD-SHELL) is not this check's business
"""

import glob
import json
import re
import sys

import yaml

CORE = {"web", "worker", "clock"}
viol: list[str] = []
lines: list[str] = []


def judge(artifact: str, name: str, probe: list[str] | None) -> None:
    core = re.search(r"-api-(web|worker|clock)(-\d+)?$", name) or name in {
        f"api-{s}" for s in CORE
    }
    forbidden = name.endswith("-otelcol") or "-api-exec" in name or name == "api"
    if probe is None:
        lines.append(f"BARE  {artifact} {name}")
        if core:
            viol.append(f"MISSING   {artifact} {name}")
        return
    lines.append(f"PROBE {artifact} {name} {json.dumps(probe)}")
    if forbidden or not core:
        viol.append(f"FORBIDDEN {artifact} {name} {json.dumps(probe)}")
    elif probe[:2] != ["CMD", "./health.sh"] or len(probe) != 3 or probe[2] not in CORE:
        viol.append(f"MALFORMED {artifact} {name} {json.dumps(probe)}")


for path in sorted(glob.glob("test_projects/*/infra/output/*/docker-compose.yml")):
    for name, svc in sorted(yaml.safe_load(open(path)).get("services", {}).items()):
        test = (svc.get("healthcheck") or {}).get("test")
        if test and test[0] == "CMD-SHELL":
            lines.append(f"ENGINE {path} {name} {json.dumps(test)}")
            continue
        judge(path, name, test)

for path in sorted(glob.glob("test_projects/elastic/infra/output/*/main.tf")):
    name: str | None = None
    probe: list[str] | None = None
    for raw in open(path):
        if raw.rstrip("\n") == "    {":
            name, probe = None, None
        elif m := re.match(r'^      name = "([^"]+)"$', raw.rstrip("\n")):
            name = m.group(1)
        elif m := re.match(r"^        command = (\[\"CMD.*\])$", raw.rstrip("\n")):
            probe = json.loads(m.group(1))
        elif raw.rstrip("\n") in ("    },", "    }") and name:
            judge(path, name, probe)
            name, probe = None, None

print("\n".join(lines))
print(f"CONTAINERS {len(lines)}")
for v in viol:
    print(v)
print(f"VIOLATIONS {len(viol)}")
sys.exit(1 if viol else 0)
```

Two notes for whoever lifts it. The HCL arm is a **line-oriented block walk**, not
a regex over the whole file: a first attempt used a single regex per container name
and reported four false `FORBIDDEN`s per `main.tf`, because the pattern matched the
file's *first* `healthCheck` for every name. A checker that reports violations
where none exist is the mirror image of this advance's recurring defect and would
have condemned a correct emitter. And `judge`'s `forbidden` / `not core` arms are
**both** checked, so the census catches a probe appearing on something new and
unclassified — not only on the three shapes known today.

Whether this lands as a checked-in file beside `PRE_CUT_CHECKLIST.md` or stays a
pasted block in the box is mod 131's call; this mod records it and claims neither.

### 2.5 What did *not* move, and should not have

- `api-web`'s ALB `target_group` health check still reads `path = "/health"`.
  `api.web` keeps `health_check_path` — rule 33's positive arm requires it on a
  `web`-network core service, and this is the one consumer the field still has.
- `api-web` and `api-worker` keep their `portMappings` and their Service Connect
  `service {}` blocks. `WORKER_HOST` / `WORKER_PORT` still resolve.
- Every non-core resource: RDS, EFS, SGs, ALB listener rules, traefik labels, the
  otelcol config, `schedules.yml`, the project tier. Untouched in both trees.
- **Reconcile consumer count is unchanged at 2.** `_reconcile_candidates` filters
  consumers by whether their *targets* are registered; both `api.web` and
  `api.clock` `uses: api.worker`, which still registers. The clock going
  unregistered removes it as a *target*, and nothing targets it. So no walk box
  keyed on that number moves — checked because D.9/D.11 are keyed on it, and mod
  131 owns them.

### 2.6 Verdict

**No defect in mods 125–129 is exposed by the output diff.** One observation, not
a defect and not fixed here: mod 129's overview § 3.4 said `root.py` would gain
`build_job_drain_http()`, and the implementation instead constructs
`ContJobDrainHttp` inline in `build_app()` alongside `ContPingsHttp` and
`ContJobsHttp`, keeping `build_job_runner_http()` as the one standalone
constructor. That matches the file's existing style — the web app's own routers
are built in `build_app`; the worker's is not, because no web-side caller mounts
it — and it is in already-reviewed territory. This mod's docs describe the code as
written, not as the overview forecast it.

---

## 3. Idempotence, per project

The criterion as sarge stated it (`compile` then `git diff --exit-code infra/output`
clean) only becomes true *after* the inner commit, since the inner repos' HEADs
still predate mod 129. So it is checked twice, in both forms:

**Now, against mod 129's on-disk state** — md5 every file under `infra/output`,
`./bin/docex compile`, md5 again, diff the manifests:

| Project | Files under `infra/output` | Result |
| ------- | ------------------------- | ------ |
| `fixed` | 16 | recompile is a **byte-for-byte no-op** |
| `elastic` | 13 | recompile is a **byte-for-byte no-op** |

So the eight modified artifacts are exactly what the current compiler produces;
mod 129 left no partial or hand-touched output. `elastic`'s compile emits its two
usual Fargate-tiering notes for `api-web` / `api-worker` and exits 0.

**After the inner commit** — the implementation re-runs `compile` and asserts
`git diff --exit-code infra/output` inside each inner repo, which is the form that
proves *committed* output equals compiler output. This is a step of § 6, not a
separate check.

Both runs go **through the real shim** (`./bin/docex`), against the local
`docex:1.7.0` image mod 129 rebuilt at `7804c88`. Verified current for this
mod: `git diff 7804c88..HEAD -- docex/{src,tables,bin,pyproject.toml,Dockerfile}`
is empty, so the image matches the working tree's compiler. The cut rebuilds it
again per `RELEASING.md` step 7.

**Test suite: 1174 passed, 18 deselected** (`.venv/bin/python -m pytest tests`),
matching baseline exactly. Nothing this mod does can move it — no `pytest`-visible
path references `test_projects/` — and confirming the number is how we know
nothing reached outside territory.

---

## 4. Docs — what the seeds must now say

Four files per tree. `plans/core/api/hex/{pings,processor,retention}.md` and
`db_schema.md` were grepped and are clean of the retired model; they are not
touched. `hex/jobs.md` is byte-identical across the two trees and stays so; the
other three differ legitimately by foundation and are edited per-tree.

These are the *projects'* core planning docs, and downstream readers copy them, so
they are held to the standard the doctrine holds any project's docs to.

### 4.1 A silent-drift class found while planning this

Three citations in the seeds' docs point at **doctrine anchors that no longer
exist**: `contracts.md § Declared by fields`, `contracts.md § Health Checks`, and
`contracts.md § Fan-out`. Post-edit, `contracts.md` has exactly one heading:
`## Standards`.

They are written as *prose* citations rather than markdown links, so `linkcheck`
cannot see them — the identical failure mode sarge logged against
`doctrine_excerpts/service_discovery.md` in the advance plan's *Defects* section.

**Two independent instances in one advance is sufficient evidence, and sarge has
ruled: [mod 132](../../advances/006_surfaces_and_health/advance_plan.md) OWNS the
mechanical arm.** `linkcheck.py` already carries the anchor-resolution machinery
for markdown links; extending it to flag `<file>.md § <Heading>` written as prose
is a small addition to an existing tool, and it closes the one drift channel this
advance has repeatedly found by hand. This is a requirement on 132, not a
suggestion to it. This mod repoints the citations on the *citing* side, which is
all its territory permits, and the arm is what stops the next instance being found
by hand as well.

Repointed here to live anchors:

| Dead citation | Repointed to |
| ------------- | ------------ |
| `contracts.md § Declared by fields` | `cicl.md § Surfaces` (a surface, not a field, is what makes a provider) |
| `contracts.md § Health Checks` | `healthchecks.md § What the probe must actually check` |
| `contracts.md § Fan-out` | *deleted with the fan-out* |

### 4.2 `plans/core/masterplan.md` (both trees)

- **Core Services table.** The `Port` column loses its two `(health only)`
  parentheticals: `worker` `8081` is now the address of a real `rpc` boundary, and
  `clock` declares **no port**. On elastic, `worker`'s cell keeps
  "Service-Connect-discoverable" and `clock`'s loses it — that is now literally
  true of the compiled HCL (§ 2.2).
- **Contracts bullet.** Three files per project, four-segment paths, keyed on
  **surface** and not on role: `api.web.rest.openapi.yml`,
  `api.worker.rpc.asyncapi.yml`, `api.worker.events.asyncapi.yml`. Say that
  declaring a surface is what makes a core service a provider, which retires the
  `(uses targets) ∪ (web-network services)` union the elastic tree still states.
- **The `api.worker` paragraph.** Rewritten: it carries a `port` because
  `api.web` addresses its `rpc` surface (rule 32's positive arm), *not* because a
  `uses` target must be probeable. Its liveness is a **tick file** read by
  `./health.sh worker`; it serves no `/health`.
- **The `api.web` exposes… paragraph.** `/health/api/worker` is gone;
  `/health/probe` and `/health/events` are now `/diagnostics/probe` and
  `/diagnostics/events`, and the sentence must say *why they were renamed* — they
  probe **backing** services, and leaving them under `/health/*` would invite a
  reader to conclude the fan-out survived, against `healthchecks.md`'s "No service
  reports on another." `POST /jobs/drain` is added.
- **The `api.clock` section.** Its "No exemptions" bullet says it serves `/health`
  off its loop tick; it now serves nothing and **binds no application socket**
  (mod 129 verified this against `/proc/net/tcp`, not by assertion). Its "no
  exemptions" claim survives intact, restated on the true basis: it gets a
  container probe like every other core service, via `./health.sh clock`. Its
  **Contract** bullet's provider-set formula is replaced by "it declares no
  surface".
- **Flows.** This is the largest edit and the reason flows 3/4/5/8 were flagged:
  - Flow 3 *Self health* → rewritten. `GET /health` survives on `api.web` only,
    because an ALB reads it (`healthchecks.md § web services also serve GET /health`).
    Worker and clock liveness becomes flow 3's second half: the loop touches
    `/tmp/<svc>.tick` on each successful iteration and `./health.sh` stats it from
    a separate process — with the 30 s threshold in `health.sh` and the ≤10 s
    cadence in the entrypoint, and **the reason they are only meaningful as a
    pair** stated once here as it is in both source files.
  - Flow 4 *Health fan-out* → **deleted**, and replaced by *Deferred-job drain*:
    `POST /jobs/drain` on `api.web` → `ContJobDrainHttp` → `JobDrainService` →
    `GwyJobRunnerHttp` → HTTP to `api.worker`'s `rpc` surface → `ContJobRunnerHttp`
    → `ContJobRunner.run_once()` → `{performed: N}` back out through the edge.
    This is the only flow that crosses a process boundary between two core
    services, so it carries the `uses` edge, the magic refs, and rule 32.
  - Flow 5 → the two endpoints are renamed; the substance (Service Connect / docker
    DNS / SG / EFS-mount coverage) is unchanged.
  - Flow 8 *Clock self health* → rewritten as the clock's half of the tick
    mechanism. Its honest point survives and gets stronger: nothing external
    reaches the clock, and the enforcement is the orchestrator acting on
    `./health.sh clock`.
  - A ninth flow is **not** added. Draining is flow 4's subject and job
    *performance* is already flow 7's.
- **Hard Boundaries.** The `api.worker.asyncapi.yml` citation becomes
  `api.worker.events.asyncapi.yml`. Add a boundary: **no core service reports on
  another's health** — this project had a fan-out and deliberately does not any
  more, which is exactly the kind of thing a copying project needs told rather
  than left to infer from an absence.

### 4.3 `plans/core/api/api.md` (both trees)

- **Core-service table** — as § 4.2; `clock`'s `Port` cell becomes `—`.
- **The `api.worker` / `api.clock` paragraphs (≈ L15–17)** — both rewritten off
  the surfaces-and-tick model. The clock paragraph's *shape* is preserved
  deliberately: it is the doc's best passage, and its argument ("no exemptions,
  and the consequence — nothing external can reach it — is easy to misread as an
  oversight") is still exactly right with `./health.sh clock` substituted for
  `/health`.
- **Composition root (L44)** — `build_app()`'s inventory becomes `/health`,
  `/diagnostics/probe`, `/diagnostics/events`, plus `ContPingsHttp`,
  `ContJobsHttp` and **`ContJobDrainHttp`** routers. `/health/api/worker` goes.
  Add `build_job_runner_http() -> ContJobRunnerHttp` to the build-function list,
  and note that the root constructs it even in `api.web`'s process where nothing
  mounts it — the same `internal_dependency_rules.md § Composition Root` item 3
  argument `build_jobs_cli` already carries, now with a second instance.
- **Entrypoints (L60, L70)** — "the **liveness surface**" is the wrong noun now
  and is replaced by "the **liveness tick**" in both: a file touch, not a served
  route, with no port. `worker.py` keeps a uvicorn daemon thread and the doc must
  say **why** — it serves the `rpc` surface, not health — because that block is
  the diff's most misreadable line (mod 129 Q5). `clock.py`'s entry states it
  loses uvicorn, fastapi and its listener outright.
- **Contracts (L80–81)** — three entries, four-segment paths, keyed on surface.
  State the two-surfaces-one-format case explicitly: `rpc` and `events` both
  resolve to `asyncapi` and are two surfaces because their *consumer sets* are
  unrelated — `api.web` calls the first synchronously; the second is produced onto
  by `api.web` and `api.clock` and consumed here. Both channels the worker
  consumes stay in the one `events` document. `api.clock` still has no contract,
  now on the plain ground that it declares no surface. Note the spec-version floor
  (OpenAPI 3.2, AsyncAPI 3.0) that mod 129's Q4 conformed to, since nothing
  enforces it mechanically.
- **Add a `## Health` section.** `health.sh` is the codebase's **fourth shim** and
  api.md documents the other three's neighbours nowhere else. Cover: the exit code
  is the whole contract; three arms (`web` curls its own `/health`, `worker` and
  `clock` stat a tick file, unknown argv exits 2 loudly); POSIX `sh` because the
  slim image ships dash; and where the 30 s / 10 s pair lives and why it is a
  pair. Also: `curl` is in the image **for the `web` arm** and for nothing else.
- **Hard boundaries (L95–96)** — the `/health/api/worker` one-hop bullet is
  deleted; the backing-probe bullet is renamed to `/diagnostics/*` and gains the
  reason for the rename. Add a bullet on `POST /jobs/drain`'s concurrency: it is
  safe against the worker's own loop draining simultaneously because
  `QueueJobsPostgres` opens a connection per call and `claim`'s
  `FOR UPDATE SKIP LOCKED` is the same guarantee that makes `replicas: 2` safe —
  the second consumer of a guarantee whose first justification is already written
  down in `jobs.md`.

### 4.4 `plans/core/api/hex/jobs.md` (identical in both trees)

Pure **addition**; nothing here is stale. The module grew a cross-process boundary
and the doc does not know about it.

- **Driving Ports** — add `ContJobDrain` (`drain_now() -> int`, driven by
  `api.web` over HTTP).
- **Driven Ports** — add `GwyJobRunner` (`Gateway`, `drain_now() -> int`).
- **Adapters Included** — add `ContJobRunnerHttp` (driving, `Http`, provider side,
  mounted by `entrypoints/worker.py`), `ContJobDrainHttp` (driving, `Http`,
  consumer side, mounted on `api.web`'s app), `GwyJobRunnerHttp` (driven,
  `Gateway`, calls the worker using the injected `WORKER_HOST`/`WORKER_PORT`).
- **A new section: one module, two processes.** The most interesting and most
  misreadable thing about the new shape, and the reason it needs its own heading:
  `jobs` now spans a process boundary. `api.worker`'s process holds the perform
  half; `api.web`'s process holds a consumer half that reaches it through a
  **driven gateway** — the worker is an external system from the consumer's point
  of view, even though both run the same image. Must state:
  - **Why five consumer-side files** (port, adapter, driving port, service,
    controller) rather than one HTTP call: the alternative is application HTTP in
    `root.py`, which is precisely what the deleted fan-out was. The five files are
    the doctrine's tax for a clean hexagon and the seeds' only demonstration of a
    consumer-side gateway onto a sibling core service.
  - **Why `drain_now()` is not a method on `ContJobs`** — the port the *clock*
    holds. Giving `ContJobs` a drain method hands the clock the ability to trigger
    performance, which is the deferral architecture this document spends its
    longest section protecting. The separate port is the cheaper mistake to avoid.
    This belongs beside "the two dispatch tables are not duplication", because it
    is the same argument arriving at a third place.
  - **Why it is not a health check**, in one line: the reply is a count of work
    performed, carries no liveness verdict, and cannot be mistaken for the thing
    this advance deleted.
- **Concurrency** — add the third-claimer note's sibling: `POST /drain` is a
  fourth concurrent claimer against the same queue, safe by the same
  `FOR UPDATE SKIP LOCKED`, and this is why the stage test asserts an integer
  `performed` and **not a count**. An order-dependent count would pass locally and
  burn a walk.
- **Hard Boundaries** — add: the drain boundary commands *performance*, never
  deferral; and the reply's integer is not a promise about which rows moved.

### 4.5 `CHANGELOG.md` (both trees)

One entry under the existing `## [Unreleased]` heading. **`project.yml`'s version
is not bumped** (§ 6), so no new version heading is opened and no dated release
line is written — the walk's `merge` step does that, and bumping now would fail
its version-not-yet-released gate.

Historical entries are **not** revised. Several past-version sections describe the
fan-out, `health_check_path` on the worker, and three-segment contract paths; that
is what those versions did, and keepachangelog history is a record rather than a
description of the present. This is worth stating because a grep for the retired
spellings will hit them and a future reader may mistake them for drift.

Keepachangelog sections, ordered as the file already orders them:

- **Changed** — the container probe is `./health.sh <service>` on both foundations;
  worker and clock liveness is a tick file, not an HTTP route; `api.web`'s two
  backing probes are renamed to `/diagnostics/*`; contract filenames gain a
  surface segment; spec floors raised to OpenAPI 3.2 / AsyncAPI 3.0; `api.clock`
  drops its `port` and both non-`web` core services drop `health_check_path`.
- **Added** — `core/api/health.sh`, the fourth codebase shim; `api.worker`'s `rpc`
  surface (`POST /drain`) and `api.web`'s consumer-side gateway onto it, exposed as
  `POST /jobs/drain`; `api.worker.rpc.asyncapi.yml`; the defer-then-drain stage
  test; three codebase tests.
- **Removed** — `GET /health/api/worker` and the fan-out; `GET /health` on
  `api.worker` and `api.clock`; the clock's uvicorn/fastapi listener; the stage
  suite's fan-out test.

Each tree's entry states its own foundation's consequence, because they differ and
a shared wording would be false for one of them: on **fixed**, the probe is the
only enforcement and docker merely *reports* `unhealthy`; on **elastic**, ECS
**kills and replaces** a task whose essential container fails, which is why
`startPeriod: 10` exists and is elastic-only. The elastic entry also notes that
`api-web`'s task definition gains a container `healthCheck` it never had, and that
`api-clock` leaves the Service Connect registry as a client-only member.

---

## 5. What this mod does not do

- **No `docex check`.** § 1.
- **No live stack.** Mod 129 already proved the probe red-then-green on the fixed
  `dev` stack, both arms and both loop-owning core services, with `docker inspect`
  corroborating at `failing_streak=3`. Re-proving it would cost a stack bring-up
  and add nothing; the walk exercises it again on real infrastructure.
- **No `project.yml` version bump.** § 6 step 2.
- **No doctrine edits.** The two dead-anchor citations in § 4.1 are repaired on the
  *citing* side, inside seed docs, which is this mod's territory. Nothing in
  `doctrine/` moves.

---

## 6. The git cadence — three steps, inner first

Per [`test_projects.md § Commit cadence`](../../core/test_projects.md), and run
**per project**, `fixed` then `elastic`.

1. **Inner-repo commit, first.** On `main`, in a project-shaped message — this is
   the project's own history, written as its maintainer would, not as a `docex`
   mod note. It must not mention mod numbers, advances, or `docex`'s branch. Both
   repos have a bare `origin` at `.docex/origin.git` from a prior walk; nothing is
   pushed, and both stay on `main`.
2. **`git tag -f v<version>`** onto the new HEAD — `v0.0.19` on fixed, `v0.0.23` on
   elastic. This **re-points an existing tag; it is not a version bump.**
   `containerize` needs a real version-tagged commit and A.2.1 wants the tag at
   HEAD. `project.yml` is untouched.
3. **Verify**, still inside the inner repo: `./bin/docex compile` then
   `git diff --exit-code infra/output` → clean. This is criterion 1 in the form
   sarge specified, which only becomes reachable after step 1.
4. **Outer catchup commit**, as its own commit, in the existing history's form:
   `Sync test_projects/<foundation> catchup to …`, naming what the snapshot now
   reflects.

### 6.1 This mod's commit count departs from the process, on purpose

`modifications.md` prescribes two commits per cycle. This mod makes **six**: the
two outer `docex` commits (`mod 130 design done, impl. steps written` and
`mod 130 complete; …`), two inner-repo commits, and two outer catchups. Two of the
three git actions the cadence requires are *inside a different repository*, and the
catchups exist because the outer repo vendors the inner trees as plain files.
Stated here so a reader counting commits against the process finds the reason
rather than a violation — the same courtesy `test_projects.md` extends by
documenting the cadence at all.

Tag `-f` is the one destructive operation in this mod. It is safe here and only
here: these seeds are disposable smoke projects whose tags exist to give
`containerize` a version-tagged commit, and the prior `v0.0.19` / `v0.0.23`
commits remain reachable from `main`.

---

## 7. Execution order, and who does what

`implementation.md` covers **the docs only**. The git cadence is mine and is run
*after* the drift review, because a review that runs against already-committed work
is not a gate — and because two of its three steps act on a different repository
and one of them force-moves a tag.

| Step | Owner |
| ---- | ----- |
| 1. Docs: `masterplan.md`, `api.md`, `hex/jobs.md`, `CHANGELOG.md` — fixed tree, then elastic. `hex/jobs.md` is written once and copied, then `diff` asserts the two are byte-identical (the trees' `core/` parity discipline extends to this file because it is *already* identical, and a silent divergence here would be invisible). | `private` implementor, per `implementation.md` |
| 2. Grep both trees' `plans/` + `CHANGELOG.md` for the retired spellings, with the changelog-history carve-out § 4.5 names. | `private` implementor |
| 3. Drift review against § 4. | me |
| 4. Per project: inner commit → `git tag -f v<version>` → `compile` + `git diff --exit-code infra/output` → outer catchup commit. | me |
| 5. `python -m pytest tests` → 1174. | me |

**Mod-process step 8 (update core planning docs) is a deliberate no-op.** The core
docs this mod's changes are reflected in are the *seeds'*, and they are the mod's
subject matter rather than its trailing paperwork — so they land in step 1.
`docex`'s own `plans/core/*` are mod 131's territory and this mod must not touch
them. Stated because a reader checking the process off box by box will look for
step 8 and should find the reason, not a gap.

---

## Design questions

**None blocking.** The one criterion question this mod would have raised — full
`docex check` — sarge answered in the kickoff before I could ask it (§ 1), and the
output diff produced no defect to escalate (§ 2.6).

Three items for the record, none needing a ruling:

1. **A second instance of a named drift class — now a firm requirement on mod
   132.** § 4.1's three dead `contracts.md §` citations are prose-not-link
   references into doctrine, the same class as the `service_discovery.md` defect
   already logged in the advance plan. Raised as a candidate; **sarge upgraded it
   to a requirement**, so mod 132 owns the `linkcheck` arm that flags
   `<file>.md § <Heading>` in prose. Recorded in § 4.1 as ownership rather than a
   suggestion.
2. **`build_job_drain_http()` was not written** (§ 2.6). Recorded rather than
   escalated, and sarge confirmed that was the right call: a mod overview records
   design intent at a point in time, not a spec the tree gets retrofitted to, so
   intent/implementation drift is *recorded* rather than erased. Mod 129's overview
   is left alone and sarge carries the deviation into the advance report.
3. **The seeds' `plans/core` docs are not link-checked today.** `linkcheck`'s
   duplicate-filename check is why the seed trees are excluded, and mod 132's
   independent-roots fix would let check 1 reach them. Not requested, and not
   this mod's to decide.
4. **The reconcile-count check was promoted.** § 2.5's finding that the consumer
   set is still 2 settles a question sarge had booked to mod 131 as a probable
   checklist edit: **`PRE_CUT_CHECKLIST.md` D.9 and D.11 do not move.** Recorded
   here because 131 will read this file and would otherwise make a wrong edit to a
   box whose number is still right.
