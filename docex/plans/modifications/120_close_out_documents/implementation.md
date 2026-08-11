# Mod 120 — Implementation

Close-out documents for advance 005. **No code. No tests. No `docex` source
changes.** Four documents plus a link-integrity pass.

Design: [`overview.md`](./overview.md). All four design questions are settled;
their rulings are folded into the steps below, so this file is self-contained.

---

## Ground rules — read before touching anything

1. **Never edit inside `docex/test_projects/fixed/` or
   `docex/test_projects/elastic/`.** Those are nested git repos, already
   committed and tagged by Mod 117. `PRE_CUT_CHECKLIST.md` lives in
   `test_projects/` itself (the outer repo) and **is** in scope; everything one
   directory deeper is not. If a step seems to require editing a masterplan, a
   project `CHANGELOG.md`, an `infra.yml`, or any file under those two
   directories — **stop and report**. Verify at the end with
   `git -C docex/test_projects/fixed status --short` (must be empty) and the
   elastic equivalent.
2. **Never edit `docex/plans/advances/005_process_type_solidification/advance_plan.md`.**
   Sarge is editing it concurrently. Its one dangling anchor is reported, not
   fixed. See [Step 5](#step-5--link-and-anchor-integrity).
3. **Append, never renumber**, in `PRE_CUT_CHECKLIST.md`. `#c9-release-prod` is
   an in-document anchor cited from § B and § E. New audit items are `B.16` /
   `B.17`; new walk assertions are checkboxes *inside* existing steps.
4. **`## Shape` in `test_projects.md` is a frozen heading name.** Four pointers
   in two nested repos name it as prose. Do not rename it, do not split it.
5. Everything below is **prose quality work**, not mechanical substitution. Where
   this file gives verbatim text, use it verbatim. Where it gives a content
   spec, write to the spec and to the surrounding document's voice.

### Process note

`docex/plans/core/test_projects.md` is a core planning doc, which
`modifications.md` normally keeps out of `implementation.md`. It is included
here deliberately: for a document mod the documents **are** the change, and this
one carries a hard dependency (four inbound pointers). Writing it here and
reviewing it is better than writing it unreviewed at the documentation step.

---

## Step 0 — Tooling

Recreate the anchor checker (it lives in scratch, not in the repo). It applies
GitHub slug rules including `-N` suffixes for duplicate headings, and skips
fenced code blocks:

```python
# save as /tmp/anchors.py
import os, re, subprocess
ROOT = "/home/ubuntu/.claude/jean_baudrillard"
files = subprocess.check_output(["git","-C",ROOT,"ls-files","*.md"],text=True).split()

def slug(h):
    h = re.sub(r'`','',h.strip())
    h = re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', h)
    h = re.sub(r'[^\w\s-]','',h.lower())
    return h.replace(' ','-')

heads = {}
for f in files:
    try: txt = open(os.path.join(ROOT,f),encoding='utf-8').read()
    except Exception: continue
    s=set(); counts={}; infence=False
    for line in txt.splitlines():
        if line.strip().startswith('```'): infence = not infence; continue
        if infence: continue
        m = re.match(r'^(#{1,6})\s+(.*)$', line)
        if m:
            sl=slug(m.group(2)); n=counts.get(sl,0); counts[sl]=n+1
            s.add(sl if n==0 else '%s-%d'%(sl,n))
        m2 = re.search(r'<a\s+(?:id|name)="([^"]+)"', line)
        if m2: s.add(m2.group(1))
    heads[f]=s

link = re.compile(r'\[[^\]]*\]\(([^)\s]+)\)')
bad=[]
for f in files:
    try: txt=open(os.path.join(ROOT,f),encoding='utf-8').read()
    except Exception: continue
    for i,line in enumerate(txt.splitlines(),1):
        for tgt in link.findall(line):
            if tgt.startswith(('http','mailto:')) or '#' not in tgt: continue
            path,anc = tgt.split('#',1)
            if not anc: continue
            rel = f if path=='' else os.path.normpath(os.path.join(os.path.dirname(f),path))
            if rel not in heads:
                if not os.path.exists(os.path.join(ROOT,rel)):
                    bad.append((f,i,tgt,"NO SUCH FILE"))
                continue
            if anc not in heads[rel]: bad.append((f,i,tgt,"NO SUCH ANCHOR"))
for b in bad: print("%s:%d  %s  -> %s" % b)
print("TOTAL", len(bad))
```

Run it now and keep the output — it is the **before** baseline:

```sh
python3 /tmp/anchors.py | grep -vE "^docex/plans/(modifications|advances/00[34])"
```

Expect exactly these live-file hits before your edits (plus four
`../doctrine/...` path escapes in released `CHANGELOG.md` sections, which are
frozen history and stay):

```
docex/plans/advances/005_.../advance_plan.md:22                 (NOT YOURS — report only)
docex/plans/advances/005_.../service_connect_reconcile_trigger.md:411
docex/plans/advances/005_.../uses_relation_merge.md:41
docex/plans/advances/005_.../uses_relation_merge.md:78
docex/test_projects/PRE_CUT_CHECKLIST.md:170
upgrades/upgrade_1.1.0.md:24                                    (pre-existing — leave)
upgrades/upgrade_1.6.0.md:22
```

---

## Step 1 — `docex/test_projects/PRE_CUT_CHECKLIST.md`

The failure mode of this document is a **stale instruction sitting quietly
between correct ones**. Work the list, then re-read the whole file top to bottom
as an operator before declaring it done.

### 1.1 Header and § B lead-in — artifact count

Two occurrences of "five-artifact alignment" (line ~7 and line ~157). Both →
**six-artifact**. `docex/plans/core/docex_process.md` has said six since Mod 111
(the sixth is `doctrine_excerpts/`, the one with no automated consumer).

### 1.2 A.2 — the candidate image

Name the version. Replace the bullet:

```
- [ ] The candidate `docex` image is built locally: `docker images docex:<v>` shows the tag.
```

with one that says the candidate is **`docex:1.7.0`** (`docker images docex:1.7.0`
shows the tag), and extend the repin bullet to state that the repin moves each
project's `docex_version` from `1.6.0` to `1.7.0` — the seeds sit at `1.6.0`
today because Mod 117 deliberately left repinning to the cut.

### 1.3 A.2 → A.2.1 — the intervening commit *(new; ordering trap)*

**This is the highest-value fix in the file** — it fails *during* a walk, after
real time and possibly real AWS spend are committed.

The A.2 repin edits `project.yml`, which dirties the inner repo. A.2.1 then
demands a clean working tree with `v<version>` at HEAD. Nothing currently says
to commit in between. Add a new checkbox at the **end of A.2**, before the A.2.1
heading:

- [ ] **Commit the repin inward before assessing A.2.1.** The repin edits
  `project.yml`, which dirties both repos; A.2.1 requires a **clean** inner tree
  with the version tag at HEAD. Commit in the inner repo per
  [`test_projects.md § Commit cadence`](../plans/core/test_projects.md#commit-cadence)
  and force-move `v<version>` to the new HEAD. Skipping this does not fail here
  — it fails at A.2.1, or worse, silently leaves `containerize` pointed at a
  commit that predates the repin.

### 1.4 A.4.1 — CICL version and the non-routed core services

In the bolded note beginning "**No new records are needed for the CICL-v2
core-service migration.**":

- `CICL-v2` → `CICL-v3`.
- Append a sentence: `worker` and `clock` core services take no ingress
  (rule 27) and are never routed, so **no** DNS record of any kind is needed for
  them on either foundation — the wildcard question does not arise. This is
  stated because the tree now contains a third core service and a reader
  counting hostnames will look for `api-clock.<env>.…`.

### 1.5 § B lead-in note — "Two things only this walk covers"

Replace the whole blockquote. Arm 1 (scheduler) is deleted outright. It is
**not** replaced by a symmetric clock arm, which would be false —
`test_clock_smoke.py` and `test_jobs_concurrency.py` cover the dispatch and the
queue in the `test` env. Write it as:

> **Two things only this walk covers.** Both are stated here so a decision to
> shorten the walk is made knowingly, not by accident.
>
> 1. **No test anywhere runs a real clock container.** The codebase suite covers
>    the dispatch table and the queue, and unit tests cover the emit — but a
>    clock **process** reading a compiler-delivered `DOCEX_SCHEDULES_YAML`,
>    firing on its own cron loop, and having its `/health` enforced by the
>    container healthcheck exists only in a walk. That probe is the clock's
>    **only** enforcement: nothing `uses` it and it is not on the `web` network,
>    so no health fan-out and no stage test can reach it
>    ([`clock.md § Caveats`](../../doctrine/infrastructure/specifics/clock.md#caveats)).
>    The clock steps in [C.9](#c9-release-prod) and [D.11](#d11-release-prod)
>    are where that is checked.
> 2. **No test of any kind covers the fixed replica unroll.** See the note at the
>    top of [C.9](#c9-release-prod).

Verify `#d11-release-prod` resolves against the actual D.11 heading; if the
heading text differs, match it rather than changing the heading.

### 1.6 B.3 — `cicl_version`

`declares `cicl_version: "2"`` → `` `cicl_version: "3"` ``. Leave the rest of the
item (apex, `domain_default_service`, `reverse_proxy`) alone.

### 1.7 B.3.1 — field list

In the sentence listing core-service fields: drop `depends_on` and `consumes`,
add `uses`; change the role-specific example `schedule` (singular — a field that
exists under no role) to **`schedules`**. Result reads:

> `role`, `command`, `networks`, `resources`, `port`, `uses`, `replicas`, and
> every role-specific field (`health_check_path`, `schedules`) live on a **core
> service**.

Leave the `{core_services, secrets, config, env}` clause and both citations.

### 1.8 B.3.2 — rewrite as a `uses` item

Replace the entire item. It currently carries **two live defects**: a dangling
`cicl.md#consumes-relationships` anchor, and the words "Core magic refs are
**four-segment**" printed directly above a **five**-segment example. New text:

- [ ] **B.3.2 `uses` is one relation, keyed on target kind** — a `uses` entry
  names either a **backing service**, bare (`appdb`), or a **core service**,
  dotted and fully qualified (`api.worker`). A bare codebase name is an error,
  not shorthand, and a core service may not use itself (rule 25). **Only core
  services declare `uses`**; a backing service has no outbound edges at all and
  is a graph sink. `depends_on:` and `consumes:` are hard errors, not silent
  aliases — rules 6 and 24 are retired and carry tombstones at their original
  numbers. Core magic refs are **five-segment**
  (`${codebases.api.core_services.worker.host}`); backing refs stay at three.
  Per [`cicl.md § Uses Relationships`](../../doctrine/infrastructure/cicl.md#uses-relationships)
  and [§ Magic Refs](../../doctrine/infrastructure/cicl.md#magic-refs).

### 1.9 B.6 — Dockerfile is per codebase

"every **core service** has a Dockerfile" → "every **codebase** has a
Dockerfile". Three core services share one image; asking the operator to find
three Dockerfiles is wrong. Also change the link *text* "§ Core Service
Containers" → "§ Codebase Containers" (the anchor `#codebase-containers` already
resolves; only the label was stale).

### 1.10 B.9 — provider contracts

Delete the sentence "`scheduler` core services are exempt (cron invokes them and
nobody else does)." Restate the provider set on `uses` and explain the clock as
*not a provider* rather than *exempt* — "exempt" is the vocabulary this advance
spent itself deleting. The item's provider-set sentence becomes:

> **The provider set is (core-targeted `uses` entries) ∪ (`web`-network core
> services)** — both arms load-bearing, so a non-web `worker` that another core
> service uses needs a contract even though nothing routes to it. A
> **backing**-targeted `uses` entry never makes anything a provider.

Then append:

> A `clock` is **not exempt from this rule; it falls outside the set by it.**
> Nothing `uses` a clock and it is not on the `web` network, so it is
> consumer-only and correctly carries no contract — the same way any other
> consumer-only core service would.

Keep the role → format mapping (`web` → openapi, `worker` → asyncapi).

### 1.11 B.10 — health endpoints

Three edits.

**(a) Fan-out sourcing.** "once per `consumes` target that is not itself on the
`web` network. Sourced from `consumes`, **never** `depends_on`." becomes: once
per **core-targeted `uses` entry** that is not itself on the `web` network;
a **backing**-targeted entry never produces a fan-out route. "the `consumes`
graph may legally cycle" → "the `uses` graph may legally cycle".

**(b) Probeability.** "Every `consumes` target declares both `port` and
`health_check_path`" → "Every **core-targeted `uses`** target declares both
`port` and `health_check_path`".

**(c) The exemption paragraph inverts.** Delete:

> `scheduler` core services are **exempt throughout** — there is no long-running
> container to probe.

Replace with a statement of what a clock **is** subject to:

> A `clock` is subject to all three parts with **no exemption**, and the walk
> must treat it that way. It serves `GET /health` on its own `port`; it owns a
> loop, so the monotonic-tick rule below applies to it unchanged; and because it
> declares `health_check_path`, `docex check`'s curl gate covers its image like
> any other. What does *not* reach it is a consequence of its being
> consumer-only rather than a carve-out: nothing `uses` it and it is not on
> `web`, so no fan-out route exists and no stage test can call it. Its probe is
> enforced by the **container healthcheck** alone — docker `healthcheck:` on
> fixed, ECS container health on elastic — which restarts a wedged clock. That
> is real enforcement, but it is local
> ([`clock.md § Caveats`](../../doctrine/infrastructure/specifics/clock.md#caveats)),
> and it is why [C.9](#c9-release-prod) and [D.11](#d11-release-prod) check it
> by hand.

In the loop-liveness paragraph, extend the reference-implementation pointer to
`test_projects/*/core/api/src/entrypoints/{worker,clock}.py`.

### 1.12 B.11 — composition root is per codebase

"each **core service** contains **exactly one** `src/root.py`" → "each
**codebase** contains **exactly one** `src/root.py`". Rename residue: one
composition root per codebase is the sentence's own point.

### 1.13 B.16 — new audit item

Append after B.15:

- [ ] **B.16 No compiled compose gates a core service** —
  `grep -n 'depends_on' infra/output/*/docker-compose.yml` returns hits **only**
  inside the per-codebase `-exec` block. The compiler emits no `depends_on:` /
  `condition:` on any core-service block; the exec block still carries
  `condition: service_healthy` over the union of that codebase's
  **backing-targeted** `uses` edges, and it is the one remaining ordering
  emission in existence. Per
  [`cicl.md § Startup ordering is not a doctrine feature`](../../doctrine/infrastructure/cicl.md#startup-ordering-is-not-a-doctrine-feature).
  Both projects' `infra/output/` are git-tracked, so this is a grep, not a
  compile.

### 1.14 B.17 — new audit item

- [ ] **B.17 The schedule table renders and is delivered as a literal** —
  `infra/output/{dev,test,stage,prod}/schedules.yml` exists (the git-tracked,
  diff-visible aggregate an operator reads), and each clock's compose
  `environment:` / task-definition env carries **`DOCEX_SCHEDULES_YAML` holding
  the rendered YAML itself, not a path**. Grep for a mount or a `configs:` entry
  naming `schedules` and confirm there is **none** — a mount would mean the
  single-variable delivery seam regressed to a file, which is precisely what the
  design deleted. Per
  [`clock.md § How the schedule reaches the container`](../../doctrine/infrastructure/specifics/clock.md#how-the-schedule-reaches-the-container).

### 1.15 C.2 and D.4 — compile output lists

Both steps enumerate what `compile` produces. Add
`infra/output/{dev,test,stage,prod}/schedules.yml` to each list.

### 1.16 C.4 — cross-reference the `docex build` note

C.4 (fixed dev sanity) has no build note, but the stale-`dist/` bind-mount trap
is a property of the **dev compose stack**, not of elastic — the fixed walk hits
it identically and *first*. Add a one-line pointer:

> The `docex build` ordering note at [D.6](#d6-dev-sanity-optional-but-recommended)
> applies here too — the trap is a dev-compose property, not an elastic one.

Match the real D.6 anchor.

### 1.17 C.5 — one codebase, one test run

Replace: "One test run per **codebase** (`api`, `reaper`), each covering every
module that codebase's core services drive — so `api`'s run exercises both
`pings` (api.web) and `processor` (api.worker)."

with: one codebase, therefore **one** run, covering every module the codebase's
three core services drive — `pings` (api.web), `processor` (api.worker), and
`jobs` + `retention` (api.clock's deferrals and api.worker's draining of them).

### 1.18 C.6 — one image

In the `containerize` checkbox: one image per codebase, and there is one
codebase, so exactly **one** repo — `registry.luxrnd.tech/docex_smoke_fixed/api:<v>`.
Delete the `…/reaper` push. "Confirm no third repo appears" → "Confirm no
**second** repo appears" (this also guards against a resurrected `reaper`). Keep
the note that `api-web` / `api-worker` / `api-clock` all share the `api` tag and
differ only by `command`, and the mod-030 underscore note.

### 1.19 C.9 — the Clock group

Keep the existing prod-release note and checkboxes verbatim. Append the group
below **after** the existing `processed_at` checkbox, under a bolded lead-in.
This is the fixed half of Goal 3 SC6.

> **Clock — fire → defer → drain.** The minutely `heartbeat` job exists solely so
> this path is observable inside a walk window; `prune_pings` is `0 3 * * *` and
> will **not** fire during the walk, so do not wait for it.

- [ ] The clock started and its schedule arrived. `docker logs …-prod-api-clock`
  shows `clock: 2 scheduled job(s): heartbeat, prune_pings; image implements: …`.
  **Compare the two lists by eye** — a scheduled name absent from the implemented
  set is a job nobody has written, and nothing currently asserts this
  automatically.
- [ ] A fire deferred. Within ~65 s the same log shows `jobs: 'heartbeat' fired`
  followed by `jobs: 'heartbeat' deferred as job <uuid>`. **Both lines, not one**
  — "fired" without "deferred" is the clock reaching the queue and failing.
- [ ] The worker drained it. `docker logs …-prod-api-worker-1` (or `-2`) shows
  `jobs: 'heartbeat' performed (job <uuid> …)` carrying the **same uuid**.
  Matching the uuid is what makes this a proof of the deferral path rather than
  of two unrelated log lines.
- [ ] Confirmed in the database: the `jobs` row for that uuid has non-NULL
  `finished_at` and NULL `error`. Use the same prod postgres access the ping
  check above already established.
- [ ] The clock answers its own probe:
  `docker inspect --format '{{.State.Health.Status}}' …-prod-api-clock` is
  `healthy`. **This is the only enforcement a clock gets** — no fan-out and no
  stage test can reach it — so an operator who skips this box has verified
  nothing about the clock's liveness surface.

### 1.20 C.10 and D.12 — rollback coverage accounting

Add one sentence to each rollback step (a note line, not a checkbox):

> **Coverage note.** Both versions in this rollback are created *after* the
> `cicl_version` `"2"` → `"3"` bump, so the cross-generation rollback refusal
> documented in [`upgrade_2.0.0.md`](../../upgrades/upgrade_2.0.0.md) is **not**
> exercised here. A green rollback walk is not evidence that the trap is gone.

### 1.21 D.6 — delete the workaround, keep the ordering note

**Delete** the final paragraph of the blockquote:

> If `build` dies with `PermissionError: … dist/**/__pycache__`, a container
> running as root wrote those directories and the shim (running as the host uid)
> can never delete them:
> `sudo find core -name __pycache__ -type d -prune -exec rm -rf {} +`

Mod 119 fixed the defect — the clear now happens inside the container, and any
checkout carrying residue self-heals on its next `docex build`. Leaving the
workaround teaches operators to keep running a `sudo rm -rf` for a bug that no
longer exists.

**Keep** the two preceding paragraphs — the ordering trap is still live
(`orchestrate/build.py::run_build` still raises `EnvNotRunning` on an empty
running set, so the whole-stack precondition is real). Two corrections inside
them:

- `./core/<svc>/dist:/service/dist` → `./core/<codebase>/dist:/service/dist`.
- `'/service/dist/entrypoints/<proc>.py'` → `'/service/dist/entrypoints/<service>.py'`.

### 1.22 D.8 — one ECR repo

`{api,reaper}` → `api`. "Confirm D.3 phase 2 provisioned exactly **two** ECR
repos, not three or four" → exactly **one**, and note that a second appearing
means a codebase was reintroduced. Keep the `{web,worker}`-are-gone note and the
ECR auth line.

### 1.23 D.9 — the inversion

**This item inverts completely.** Replace the `reaper-prune` checkbox:

```
- [ ] `reaper-prune` came up as a **scheduled task**, not a service: an
  `aws_ecs_task_definition` plus an `aws_scheduler_schedule` and a per-service
  scheduler-invocation IAM role, and **no** `aws_ecs_service`. Confirm
  `aws ecs list-services` shows exactly four (`api-web`, `api-worker`, `probe`,
  `events`).
```

with two checkboxes:

- [ ] `api-clock` came up as an **ordinary ECS service** — an
  `aws_ecs_task_definition` **and** an `aws_ecs_service`, its own CloudWatch log
  group, a paired otelcol sidecar, and a container-level `healthCheck`. It is a
  long-running singleton, not an invocation. Confirm `aws ecs list-services`
  shows exactly **five**: `api-web`, `api-worker`, `api-clock`, `probe`,
  `events`.
- [ ] **Nothing scheduler-shaped exists anywhere.** Assert twice, because the two
  assertions catch different failures. **Emission:**
  `grep -nE 'aws_scheduler_schedule|scheduler\.amazonaws\.com' infra/output/*/main.tf`
  returns nothing. **Leak:** `aws scheduler list-schedules` returns no schedule
  carrying the project prefix, and no IAM role matching
  `docex-smoke-elastic-*-scheduler*` survives. The first proves the compiler
  stopped emitting; the second proves nothing was orphaned by a teardown filter
  that no longer matches — the silent failure mode the upgrade guide flags.

Also in D.9's first checkbox, the ECS-services list gains `api-clock`. And in
the `-migrate` checkbox, delete "and none for `reaper` (it owns no schema)";
keep "exactly **one** `…-migrate` task-definition family exists for the `api`
codebase — not one per core service".

### 1.24 D.11 — the Clock group, elastic

Append the same five-assertion group as [1.19](#119-c9--the-clock-group),
translated to elastic, plus one extra box. Logs come from the
`/docex_smoke_elastic/prod/api-clock` and `…/api-worker` CloudWatch log groups;
the database is the prod RDS the ping check already reaches; container health is
the ECS container health status rather than `docker inspect`. The extra box:

- [ ] `aws ecs describe-services` reports `desired_count = 1` for `api-clock`.
  A clock declares no `replicas` and rule 26 forbids it — a 2 here means two
  cron loops and a double fire on every tick.

### 1.25 Final read

Re-read the file **end to end, as an operator following it**, not as a diff.
Then confirm mechanically:

```sh
grep -niE 'reaper|scheduler|depends_on|consumes|five-artifact|cicl_version: "2"|four-segment' \
  docex/test_projects/PRE_CUT_CHECKLIST.md
```

The only acceptable survivors are `depends_on` inside B.16 (where it is the
thing being grepped for) and any `scheduler` inside D.9's leak assertion (where
it is the thing being proven absent). Anything else is a miss.

---

## Step 2 — `docex/plans/core/test_projects.md`

### 2.1 The hard dependency — verify first, verify last

Four pointers name `test_projects.md § Shape` as prose (not hyperlinks):

```sh
grep -rn "test_projects.md § Shape" docex/test_projects/*/plans/core/masterplan.md \
                                    docex/test_projects/*/CHANGELOG.md
```

Expect four hits (fixed masterplan ×2, elastic masterplan ×1, both project
changelogs — count them yourself and record the number). **The heading must stay
spelled exactly `## Shape`.** Re-run this grep at the end and confirm the
heading still exists and now carries what those pointers promise.

### 2.2 § Shape — rewrite

Replace the opening sentence "There are **two codebases carrying three core
services** between them" with **one codebase carrying three core services**.

Rewrite the `api` bullet to cover all three core services: `api.web`
(`role: web`, `POST /pings` + `GET /health` + the `/health/api/worker` fan-out),
`api.worker` (`role: worker`, `replicas: 2`, polls `pings`, drains `jobs`,
serves its own tick-based `/health`), and `api.clock` (`role: clock`, singleton,
`schedules: {prune_pings: "0 3 * * *", heartbeat: "* * * * *"}`,
`uses: [appdb, api.worker]` with **no magic ref** — the edge is the queue, not
the mesh). Update the expansion tally to what the tree actually produces: one
build, one ECR repo, one `-exec` container, one `-migrate` task definition,
**three** sidecars.

**Delete the `reaper` bullet entirely**, including the claim that it is *"the
only end-to-end coverage of the scheduler path anywhere"* — that path does not
exist. Do not soften it; delete it.

### 2.3 New subsection: `### Coverage given up when `reaper` was deleted`

Inside § Shape, so `#shape` still reaches it. This is the record the four
pointers resolve to. Four things, in this order:

1. **Why the codebase could not survive.** A clock defers onto its own
   codebase's queue, and only the schema-owning codebase may enqueue
   ([`clock.md § The clock defers; it does not work`](../../../doctrine/infrastructure/specifics/clock.md#the-clock-defers-it-does-not-work)).
   `reaper` owned no schema — it reached into `api`'s `pings` table through its
   own repo adapter — and had no worker and no queue. `reaper.clock` would
   therefore have had to *perform* the prune inside the singleton, which is the
   one thing the rule forbids. `api` owns the schema, owns a polling worker, and
   can own a queue, so the clock folded into `api`.
2. **What the walk stopped exercising**, named individually so a future reader
   finds an accounting rather than a gap:
   - one image **per codebase** — the multi-codebase build fan-out;
   - two registry repos on fixed (checked at C.6) and two ECR repos on elastic
     (D.8 checked the count explicitly); both are now one;
   - the per-codebase `migrate.sh` / `test.sh` fan-out — and the sharpest edge:
     a codebase that owns **no** schema, and therefore has no `migrate.sh` at
     all, is a shape the walk no longer contains.
3. **What was gained**, so the trade is legible rather than only a loss: a real
   clock container, a compiler-delivered schedule table, and a fire → defer →
   drain path exercised end-to-end on both foundations.
4. **The instruction.** Say plainly: this is **not drift**, and restoring a
   second codebase is not the fix. If the fan-out coverage is wanted back it
   needs a second codebase with a genuine reason to exist — not a resurrected
   `reaper`, whose reason for existing was retired with `role: scheduler`.

### 2.4 Reference-implementation paragraph and tree

- The `api` reference-implementation paragraph (currently naming
  `src/entrypoints/{web,worker}.py`) gains `clock.py`, and gains a pointer to
  the two new hex modules (`hex/jobs`, `hex/retention`) with the standing
  warning that the **defer-side table in `ContJobsCron` and the perform-side
  table in `JobRunnerService` are not duplication** — collapsing them would
  couple the clock to the worker's implementation and destroy the deferral
  architecture. Downstream projects copy this tree and inherit whatever it fails
  to explain, which is why it is said here and not only in a mod doc.
- Tree diagram: `core/{api,reaper}/` → `core/api/`.

Leave §§ Why two, Inception-flow divergences, Git structure, Commit cadence,
Resource cleanup, Safety overrides, and Lifecycle untouched. ("Why two" is about
two **foundations**, not two codebases — do not edit it.)

---

## Step 3 — `upgrades/upgrade_2.0.0.md`

The fragment becomes the shippable guide. **Audience rule:** it must be readable
start-to-finish by someone who has never heard of advance 005 and must not
require reading a design record. Every link into
`docex/plans/advances/005_*` is therefore demoted to optional further reading or
removed; no *step* may depend on one.

### 3.1 Frontmatter and banner

- Delete the `status:` line.
- Keep `version: "1.7.0"`, `kind: incremental`, `scope: [machine, project]`.
- **Keep `severity: minor`** — the advance's settled decision, matching how
  1.6.0 shipped a breaking change as a minor. The "Decide the severity" box is
  ticked with that answer.
- **Delete the entire `> # ⚠ THIS GUIDE IS AN INCOMPLETE FRAGMENT` blockquote**,
  including its status table.
- **Delete the whole `## Before this ships` section** at the end.

### 3.2 Summary — rewrite

Currently describes the rename alone. It must cover the release: three
author-visible changes (the noun rename, the `uses` merge, `scheduler` → `clock`)
and one behavioural one (the Service Connect reconcile now triggering off durable
state, with `wait_for_steady_state = true`). Include, in the summary and not
buried later:

- `cicl_version` moves `"2"` → `"3"`; earlier generations are rejected, not
  shimmed.
- **A warning that the scheduler migration needs application code**, not just an
  `infra.yml` edit — so a reader budgets for it before starting.
- A pointer to the rollback-window subsection.

Keep the "why the rename" paragraph; it is good and it explains the vocabulary
the rest of the guide is written in.

**Delete** the "Why this is `incremental` and unusually cheap" paragraph — its
byte-identical-output claim is no longer true (see [3.7](#37-step-8--recompile-and-diff)).

### 3.3 "What does not move"

- **Delete the `consumes:` row.** It moved.
- Add a row recording what genuinely survived the merge: the dotted
  `<codebase>.<service>` target spelling is unchanged, so a `consumes:` list's
  **contents** transplant into `uses:` verbatim — only the field name changes.
- Delete "**Every emitted name.** See above." or rewrite it to the narrower
  truth: no container name, hostname, image ref, contract path, or `Name` tag
  changes. (Emitted *output* does change; emitted *names* do not.)
- Keep `$pr/core/`, `/service`, `shape_name`, and `schema_owned_by`.

### 3.4 Step order

Renumber the Project-upgrade steps to:

| # | Step | Provenance |
| --- | --- | --- |
| 1 | Repin + sync the shim | kept |
| 2 | Rename the two `infra.yml` keys | kept |
| 3 | **Merge `depends_on` + `consumes` into `uses`** | new |
| 4 | **`role: scheduler` → `role: clock`** | new |
| 5 | Qualify core magic refs — five segments | was 3 |
| 6 | `domain_default_process` → `domain_default_service` | was 4 |
| 7 | Bump `cicl_version` to `"3"` | was 5 |
| 8 | Recompile and diff before deploying | was 6 |
| 9 | Redeploy | was 7 |
| 10 | ⚠ REQUIRED — telemetry queries/dashboards/alerts | was 8 |

State the **rename-first** reason where a reader will hit it (end of step 2 or
start of step 3): step 3 authors `uses` targets spelled
`<codebase>.<service>`, which is vocabulary step 2 establishes — doing `uses`
first means writing every target twice. Step 7's existing "Last, after steps
2–4" line becomes "after steps 2–6".

Keep steps 2, 5, 6, 9, 10 substantially as written (including the
`s/core_services/codebases/` trap warning, the five-segment error messages, and
the `domain_default_service` round-trip table — all still correct).

### 3.5 Step 3 — the `uses` merge

Content spec:

- **Mechanics.** `depends_on:` → `uses:`, merged with any `consumes:` list on
  the same core service into one list. `depends_on:` deleted from **backing
  services entirely** — a backing service now declares no outbound edges and is
  a graph sink; where an engine genuinely needs another container, that belongs
  in the engine's transfer table, not `infra.yml`.
- A before/after YAML pair showing a `web` core service with both old fields
  collapsing into one `uses:`, and a backing service losing its `depends_on:`.
- **Both old names are hard errors, not silent aliases** — a missed one fails
  loudly at compile rather than being quietly accepted.
- **The bolded consequence — project-level startup ordering is gone.** The
  compiler emits no compose `depends_on:` / `condition:` on any core-service
  block. Removed, not deprecated. Say what this means for a real project: boot
  code that was leaning on the compose gate — which `dev` and `test` were
  silently supplying and elastic `prod` never was — will now fail on a cold
  start. That is the connection-resilience mandate becoming *visible*, not a
  regression; `dev` should expose non-resilient boot code, not shelter it.
  Expect a burst of connection-refused lines on `envinfra up` while backings
  initialize; that is correct signal.
- **The exec block keeps its gate.** `migrate.sh`, `test.sh`, `build.sh` are
  one-off batch jobs whose whole contract is an exit code, so the per-codebase
  `-exec` block still carries `condition: service_healthy` over the union of
  that codebase's **backing-targeted** `uses` edges. Nothing an author writes.
- Rule changes, briefly: 6 and 24 retired with tombstones at their original
  numbers; 7 collapsed to one clause; 25 is now the `uses` shape rule.
- Cite [`cicl.md § Uses Relationships`](../doctrine/infrastructure/cicl.md#uses-relationships)
  and [§ Startup ordering is not a doctrine feature](../doctrine/infrastructure/cicl.md#startup-ordering-is-not-a-doctrine-feature).

### 3.6 Step 4 — `scheduler` → `clock`

**The precondition goes first, before any step.** A clock defers and does not
work; only the schema-owning codebase may enqueue; therefore **the codebase must
own a queue**. A codebase with scheduled work but no queue and no worker cannot
host a clock — the schedule moves to a codebase that can, or the codebase grows a
queue. This is the single most likely place a downstream upgrade stalls, and
burying it inside the steps lets a project restructure half its `infra.yml`
before finding out. State it plainly and first.

Then:

- Each `role: scheduler` core service becomes **one** `role: clock` core
  service — a long-running singleton, not an invocation.
- `schedule:` becomes **`schedules:`**, a map of *job name* → **bare 5-field UTC
  cron string**. Job names are identifiers; they are dispatch keys.
- Each old job's `command` argv becomes a **driving-port method**, dispatched by
  name in a `Cron`-mechanism controller. "Run an arbitrary argv on a schedule"
  is no longer available — scheduled work must be an operation on a driving
  port. Argv-against-the-image survives in the `-exec` container and
  `migrate.sh`, where it belongs.
- A before/after `infra.yml` pair, and the architecture chain
  (`entrypoints/clock.py` → `ContJobsCron` → `ContJobs` → alogic → `Queue` port).
- **⚠ No cron dialect translation anywhere.** Any 6-field expression, `?`-day
  substitution, or provider-numbered day-of-week inherited from EventBridge must
  be rewritten by hand to plain 5-field UTC. Nothing translates it and nothing
  warns.
- Other behaviour changes an operator can be bitten by: one clock **per
  codebase** (not per project); `replicas` forbidden (rule 26); `web` forbidden
  in `networks` (rule 27); on elastic the clock deploys **stop-then-start**
  (`deployment_minimum_healthy_percent = 0`), trading a possible missed fire for
  a possible double fire; **no backfill** — a fire missed during a deploy or an
  outage is not retroactively run; and a clock is **invisible to staging tests**,
  its liveness enforced only by its container healthcheck.
- Point at [`clock.md`](../doctrine/infrastructure/specifics/clock.md) as the
  rule of record, and at the worked reference implementation in
  `docex/test_projects/*/core/api` — a real tree a project can read.

### 3.7 Step 8 — recompile and diff

**Replace** the "Expect differences in exactly four places, and nothing else"
table. The byte-identical guarantee was the rename's property alone. The
contract changes from *"exactly four rows"* to *"every difference must attribute
to one of these causes"*:

| Cause | Expected difference |
| --- | --- |
| The rename | The two elastic env-tier tag **keys** (`service` → `codebase`, `process` → `service`) and the two OTel resource attribute keys (`docex.core_service` → `docex.codebase`, `docex.process_type` → `docex.service`). **Values unchanged in all four.** |
| The `uses` merge | `depends_on:` and `condition:` **disappear** from every core-service compose block. The per-codebase `-exec` block's gate stays. |
| The reconcile fix | `wait_for_steady_state = true` appears on **every** `aws_ecs_service`. |
| `clock` *(only if the project had a scheduler)* | `aws_scheduler_schedule`, the `scheduler.amazonaws.com` invocation role and its policy, and the Ofelia container + INI all **disappear**. A task definition, an `aws_ecs_service`, a log group, and a sidecar appear. The clock alone carries `deployment_minimum_healthy_percent = 0` / `deployment_maximum_percent = 100` and `DOCEX_SCHEDULES_YAML` in its env. A **new output file** appears: `infra/output/<env>/schedules.yml`. |

**Keep** the guard sentence — any change to a container name, hostname, image
ref, contract path, `Name` tag, or `role` value is a **defect**; stop and
investigate rather than deploying. It survives all four causes and is the guard
actually worth having. Keep both "harmless artifacts" bullets (tag reordering;
in-place tag updates).

Add a consequence note for `wait_for_steady_state`: an elastic apply now blocks
on rollout and **fails** if a service cannot converge, rather than returning and
letting the release proceed. Applies take longer, and a broken image now fails
the apply instead of surfacing later.

### 3.8 Doctrine / behavior notes

Keep the existing bullets (error-message wording, `docex build <name>`,
`describe --format llm`, `/health` fan-out path, lexicon, historical records).
Add:

- **`docex roles` lists six roles and `scheduler` is not among them.**
- **`docex dag` derives solid/dashed edges from target kind** rather than from
  which field an edge was declared in.
- **`specifics/scheduler.md` is replaced by `specifics/clock.md`**, and every
  inbound pointer moved — a project author looking for "how do I schedule work"
  still finds exactly one document.
- Error messages now name `uses`; anything grepping CI output for
  `depends_on`/`consumes` text needs updating.

Then a new subsection, modelled on
[`upgrade_1.6.0.md`'s](./upgrade_1.6.0.md) v1→v2 treatment:

#### Rollback is unavailable across the boundary

For exactly **one release cycle**, `docex rollback` refuses at cheap pre-flight —
before any worktree is created and before any apply — because rollback
recompiles the **target** version's `infra.yml` with the **current** docex, and
every existing tagged release declares `cicl_version: "2"`. Fix forward: bump
past the broken version and re-run `check → merge → containerize → release`.
Once a second `"3"` release exists, rollback works normally. Note that this is
the same trap the 1.6.0 upgrade carried at its own boundary, so a reader
recognises the shape rather than reading it as new breakage. There is no
mitigation beyond keeping the window short.

### 3.9 Verification section

Extend the existing five items:

- greps for zero occurrences of `processes:`, `domain_default_process`,
  `${core_services.`, **`depends_on:`**, **`consumes:`**, **`role: scheduler`**,
  and **`schedule:`** (singular) in `infra.yml`;
- `infra/output/<env>/schedules.yml` rendered, if the project has a clock;
- post-deploy, the clock's container health is green and a scheduled job has
  fired and been drained;
- keep the existing telemetry-attribute and `tofu plan`-clean items.

---

## Step 4 — `upgrades/README.md`

One sentence, converting a judgement call into a narrow rule. In
**§ One Guide Per Release**, after "It is written once, when that release is cut,
then never revised.", add:

> **One narrow exception:** a guide's **link targets** may be repointed when a
> later release renames the doctrine section a link addresses. Nothing else may
> change — no prose, no instruction, and no version claim. A guide's words are
> the historical artifact; its links are pointers into living doctrine, and a
> dangling one preserves nothing while making the guide unusable.

Do not restructure the section around it — one sentence, in place.

---

## Step 5 — Link and anchor integrity

Five repoints. **All are target-only; change no prose** (this is the exception
Step 4 just wrote down).

| File:line | Current target | New target | Note |
| --- | --- | --- | --- |
| `upgrades/upgrade_1.6.0.md:22` | `../doctrine/infrastructure/cicl.md#process-types` | `#core-services` | Leave the visible text `cicl.md § Process Types` **exactly as is** — it names the section as it was called at 1.6.0, which is the historical record. |
| `docex/plans/advances/005_.../uses_relation_merge.md:41` | `cicl.md#depends-on-relationships` | `cicl.md#startup-ordering-is-not-a-doctrine-feature` | The quoted resilience mandate now lives there. Update the visible `§ Depends-On Relationships` label too — this file is live input, not history, per the rename plan's freeze list. |
| `docex/plans/advances/005_.../uses_relation_merge.md:78` | `cicl.md#depends-on-relationships` | `cicl.md#startup-ordering-is-not-a-doctrine-feature` | Target only. |
| `docex/plans/advances/005_.../service_connect_reconcile_trigger.md:411` | `#two-implementation-details-that-matter` | `#three-implementation-details-that-matter` | The heading gained a third item. |
| `docex/test_projects/PRE_CUT_CHECKLIST.md:170` | `cicl.md#consumes-relationships` | — | Already handled by the B.3.2 rewrite in [1.8](#18-b32--rewrite-as-a-uses-item). Confirm it is gone. |

**Not yours, report only:**

- `advance_plan.md:22` → `#step-0--recon-the-service-connect-name-freeze`. The
  heading gained `✅ COMPLETE`, changing its slug. Sarge is editing that file
  concurrently; **do not touch it.** Note it in your report so he can fix it in
  the same pass (the cleanest fix is moving `✅ COMPLETE` out of the heading and
  into the blockquote below, which restores the original anchor).
- `upgrades/upgrade_1.1.0.md:24` — predates this advance. Leave.
- Four `../doctrine/...` path escapes in released `CHANGELOG.md` sections —
  frozen history. Leave.

Re-run the checker. **Gate:** the live-file set must contain only
`advance_plan.md:22`, `upgrade_1.1.0.md:24`, and the four `CHANGELOG.md`
escapes. Anything else you introduced must be fixed before finishing.

---

## Step 6 — `CHANGELOG.md`

`[Unreleased]` (lines 18–294) already carries good per-mod prose. The work is
making it read as **one release** rather than six mods. Do **not** rewrite the
existing entries wholesale — they are well-written and dense; edit surgically.

### 6.1 Lead paragraph

Add one immediately under `## [Unreleased]`, before `### Changed`, matching the
shape of the `## [1.6.0]` entry's lead. It must say: what the release is
(advance 005 — finishing what CICL v2 started: the vocabulary rename, one
relation named `uses`, and the retirement of a process type that was not a
process); that it is **breaking**, `cicl_version` `"2"` → `"3"`, rejected rather
than shimmed; that **rollback is unavailable for one release cycle** across that
boundary; and that downstream projects upgrade per
[`upgrades/upgrade_2.0.0.md`](./upgrades/upgrade_2.0.0.md).

### 6.2 Two stale intra-release statements — the important fix

In the rename entry (currently ~lines 118–124), the closing paragraph tells a
reader of the **shipped release**:

- "Backing refs, `consumes:`, and `schema_owned_by` are unchanged." — `consumes:`
  is **gone**. Remove it from that list; `schema_owned_by` and backing refs
  genuinely are unchanged and stay.
- "`cicl_version` stays `"2"` — the 2 → 3 bump ships with the `uses` relation
  merge in the same cut." — it **is** `"3"`. Replace with a plain statement that
  the rename is one of three changes sharing the `"2"` → `"3"` bump in this cut.

Both were true when written mid-advance and are false at the cut. This is the
single thing most likely to mislead a downstream reader, because it appears in
the entry that *looks* the most authoritative about `infra.yml` edits.

### 6.3 Ordering within `### Changed`

Reorder so the account builds rather than arriving in mod order:

1. the vocabulary rename (it is the vocabulary every other entry is written in),
2. the `uses` merge,
3. `role: scheduler` → the clock.

Keep the "**`docex` implements the `uses` merge**" entry immediately after the
`uses` doctrine entry it belongs to. Move whole blocks; do not re-word them.

### 6.4 One `### Added` line

Append to the existing `### Added` section a short entry for the doctrine
surface this release ships and nothing currently announces:
`specifics/clock.md` replaces `specifics/scheduler.md` as the one document
answering "how do I schedule work", and the two smoke projects' `api` codebase is
the clock's **reference implementation** — `entrypoints/clock.py` →
`ContJobsCron` → driving port → `Queue` port, with the defer-side and
perform-side dispatch tables kept deliberately separate. Downstream projects copy
that tree, which is why it is announced rather than left to be found.

Mod-number citations (`(mod 119)`) **stay** — 113 exist across released
sections, so it is established form here.

---

## Step 7 — Verification

Run all of it. Every item is a gate.

1. **Anchors.** `python3 /tmp/anchors.py | grep -vE "^docex/plans/(modifications|advances/00[34])"`
   contains only the three not-yours entries from [Step 5](#step-5--link-and-anchor-integrity).
2. **The § Shape dependency.**
   `grep -rn "test_projects.md § Shape" docex/test_projects/*/plans/core/masterplan.md docex/test_projects/*/CHANGELOG.md`
   returns the same count as before, and
   `grep -n "^## Shape" docex/plans/core/test_projects.md` returns exactly one
   line. Read the new subsection and confirm it actually answers what those
   pointers promise ("what the second codebase used to cover, and what its loss
   costs the smoke walk").
3. **Checklist residue.** The grep in [1.25](#125-final-read), with only the two
   permitted survivors.
4. **Checklist numbering unchanged.** `grep -n "^### [A-E]\." docex/test_projects/PRE_CUT_CHECKLIST.md`
   — every existing step keeps its number; only `B.16` and `B.17` are new.
5. **Guide is shippable.** `upgrade_2.0.0.md` has no `status:` field, no
   `FRAGMENT` banner, no `## Before this ships` section, and no unticked
   checkbox. `grep -c "advances/005" upgrades/upgrade_2.0.0.md` — any survivor
   must be optional further reading, never a step's prerequisite.
6. **Guide reads cold.** Read `upgrade_2.0.0.md` start to finish as someone who
   has never seen this advance. Every step must be actionable without opening a
   design record.
7. **Inner repos untouched.**
   `git -C docex/test_projects/fixed status --short` and
   `git -C docex/test_projects/elastic status --short` are both **empty**.
8. **Path scope.** `git status --short` shows changes only under
   `docex/plans/modifications/120_close_out_documents/`,
   `docex/plans/core/test_projects.md`,
   `docex/plans/advances/005_process_type_solidification/{uses_relation_merge,service_connect_reconcile_trigger}.md`,
   `docex/test_projects/PRE_CUT_CHECKLIST.md`, `upgrades/upgrade_1.6.0.md`,
   `upgrades/upgrade_2.0.0.md`, `upgrades/README.md`, and `CHANGELOG.md`.
   **`advance_plan.md` must NOT appear.**
9. **No regression.** No `docex` source changed, so the suites are untouched;
   run them once as a no-regression check: `pytest tests/unit` ≥ 988 and
   `pytest -m integration` 20 passed / 0 failed.

## Report

On finishing, report: the four documents' state, the before/after dangling-anchor
counts, the `§ Shape` pointer count, anything in the checklist re-read that this
file did not anticipate, and confirmation that both inner repos are clean.
