# Mod 120 — Advance 005 close-out documents

The document half of the split approved at Mod 117. **No code, no tests, no
`docex` source changes.** Four artifacts:

1. `docex/test_projects/PRE_CUT_CHECKLIST.md` — the operator's walk procedure.
2. `docex/plans/core/test_projects.md` — § Shape becomes one codebase.
3. `upgrades/upgrade_1.7.0.md` — the fragment becomes a shippable guide.
4. `CHANGELOG.md` — `[Unreleased]` rolled into one coherent account.

Plus a link-integrity pass over everything the advance touched.

The brief is
[Mod 117 § Deferred to Mod 120](../117_smoke_project_migration/overview.md);
this overview adds the items an end-to-end operator read of the checklist turned
up that the handoff did not name.

---

## State this lands on

Tree clean at `5dcce68`. Unit 988, integration 20/0. Both smoke projects compile
clean on all four envs and are committed and tagged inward (`fixed` v0.0.17,
`elastic` v0.0.19). Verified against the working tree while designing:

- `api` declares **three** core services — `web`, `worker`, `clock`. (Mod 117's
  overview says "four"; that counted the deleted `reaper.prune` row in its own
  table. The correct number is three, and every count in these documents is
  written from the tree rather than from that table.)
- `fixed/infra/output/` is now **tracked** (16 files), so the advance plan's
  logged-drift row "fixed has no committed `infra/output/`" is stale. Compiled
  output can be grepped from the tree on both foundations.
- The elastic compile emits **five** `aws_ecs_service` blocks (`api-web`,
  `api-worker`, `api-clock`, `probe`, `events`) and **one** `-migrate` family.
  `wait_for_steady_state = true` is on all five; the clock alone carries
  `deployment_minimum_healthy_percent = 0` / `maximum_percent = 100`.
- `DOCEX_SCHEDULES_YAML` is delivered as a **literal env entry on both
  foundations** (compose `environment:` on fixed, task-def env on elastic), and
  `infra/output/<env>/schedules.yml` renders in all four envs of both projects.
  The advance plan's § Goal 3 SC3 wording ("compose top-level `configs:` on
  fixed") describes an earlier design; `clock.md § How the schedule reaches the
  container` and the emitted output agree with each other, so `clock.md` is the
  rule of record and the checklist is written to it.
- No `scheduler` string survives anywhere in either project's `infra/output/`,
  `teardown.sh`, or `verify_clean.sh`.

---

## 1. `PRE_CUT_CHECKLIST.md`

The failure mode of this document is a stale instruction sitting quietly between
correct ones, so it was re-read end to end as an operator rather than diffed.
The brief's items are below as **(B)**; items found in that read are **(F)**.

### Structural rule for this edit

**Append, never renumber.** `C.9` is cited by an in-document anchor
(`#c9-release-prod`) from the § B note and from § E. New audit items land as
`B.16`/`B.17`; new walk assertions land as checkboxes *inside* existing steps.
Nothing shifts a number, for the same reason `cicl.md` tombstones retired
validation rules instead of renumbering.

### § A

| Item | Change |
| --- | --- |
| **A.2** (B) | The candidate image is named: `docex:1.7.0`. Repin moves each project's `docex_version` `1.6.0` → `1.7.0` — the seeds sit at `1.6.0` today because Mod 117 deliberately left repinning to the cut. |
| **A.2 → A.2.1** (F) | **Ordering trap.** The A.2 repin edits `project.yml`, which dirties the inner repo — and A.2.1 then demands a *clean* working tree with `v<version>` at HEAD. Today nothing says to commit in between. A line is added: commit the repin inward per § Commit cadence and re-point the tag before A.2.1 is assessed. |
| **A.4.1** (F) | "No new records are needed for the **CICL-v2** core-service migration" → v3. Gains a clause: `worker` and `clock` core services take no ingress (rule 27) and are not routed, so they need no records on either foundation — the wildcard question does not arise for them at all. |
| Header, line 7 (F) | "the **five**-artifact alignment in `docex_process.md`" → **six**. `docex_process.md` has said six since Mod 111. Same fix at the head of § B. |

### § B — doctrine-conformance audit

| Item | Change |
| --- | --- |
| **The "two things only this walk covers" note** (B) | Arm 1 (the scheduler) is deleted outright — there is no scheduler. It is **not** replaced by a symmetric clock arm, because that would be false: `test_clock_smoke.py` and `test_jobs_concurrency.py` cover the dispatch and the queue in the `test` env. What the walk uniquely covers is narrower and is stated as such: a real clock **container** reading a compiler-delivered `DOCEX_SCHEDULES_YAML`, firing on its own cron loop, and having its `/health` enforced by the container healthcheck — the one enforcement path a clock has, and one no stage test can reach. Arm 2 (the fixed replica unroll) stands verbatim; it is still the only thing anywhere that exercises the unroll. |
| **B.3** (B) | `cicl_version: "2"` → `"3"`. |
| **B.3.1** (B, F) | Field list drops `depends_on` / `consumes` and gains `uses`. The role-specific example `schedule` (singular — a field that no longer exists under any role) becomes `schedules`. |
| **B.3.2** (B, F) | Rewritten as a `uses` item: one relation, backing services bare, core services dotted and fully qualified, a bare codebase name an error, and a core service may not use itself (rule 25). Rule 24 is cited as **retired**, with its tombstone. **Two live defects fixed here:** the dangling `cicl.md#consumes-relationships` anchor (→ `#uses-relationships`), and the text "Core magic refs are **four-segment**" printed directly above a **five**-segment example — internally contradictory since the rename, and the exact shape of stale instruction this re-read was for. |
| **B.6** (F) | "every **core service** has a Dockerfile" → **codebase**. A Dockerfile is per codebase; three core services share one image. Link text "§ Core Service Containers" → "§ Codebase Containers" (the anchor already resolves; only the label was stale). |
| **B.9** (B) | The `scheduler` exemption sentence is deleted. The provider set is restated on `uses`: (**core-targeted `uses`** entries) ∪ (`web`-network core services). The clock is then explained as **not exempt but not a provider** — nothing `uses` it and it is not on `web`, so it falls outside the set by the ordinary rule and correctly carries no contract. Stated that way round deliberately: "exempt" is what the doctrine just spent an advance deleting. |
| **B.10** (B) | "`scheduler` core services are **exempt throughout**" is deleted and replaced with what a clock *is* subject to: it serves `GET /health` on its own `port`; it is a loop-owner, so the 10 s tick / 30 s staleness rule applies unchanged; `docex check`'s curl gate covers it because it declares `health_check_path`; and its probe is enforced by the **container** healthcheck. The one thing that genuinely does not reach it — fan-out and therefore staging tests — is stated as a *consequence of consumer-only-ness*, with `clock.md § Caveats` cited, not as a carve-out. Fan-out sourcing "from `consumes`, never `depends_on`" becomes "from **core-targeted** `uses` entries; a backing-targeted entry never produces a fan-out route". Probeability likewise. The reference-implementation pointer gains `entrypoints/clock.py`. |
| **B.11** (F) | "each **core service** contains exactly one `src/root.py`" → **codebase**. Rename residue: one composition root per codebase is the whole point of the sentence, and the current wording asks the operator to find three. |
| **B.16** (new, F) | **No compiled `docker-compose.yml` carries `depends_on:` on a core-service block.** The per-codebase `-exec` block still carries `condition: service_healthy` over its backing-targeted `uses` edges, and that is the only ordering emission left in existence. Goal 2 SC4 requires this verified and nothing in the checklist looks for it. Greppable from the tracked output on both foundations. |
| **B.17** (new, F) | **`infra/output/<env>/schedules.yml` renders in all four envs**, and each clock's compose/task-def block carries `DOCEX_SCHEDULES_YAML` as a **literal YAML value, not a path**. Goal 3 SC3. Also a grep-guard: no `schedules.yml` is *mounted* anywhere — a mount would mean the delivery seam regressed to a file. |

### § C — fixed walk

| Item | Change |
| --- | --- |
| **C.2** (F) | Expected-output list gains `infra/output/{dev,test,stage,prod}/schedules.yml`. |
| **C.4** (F) | Gains a pointer to D.6's `docex build` ordering note. The stale-`dist/` bind-mount trap is a property of the **dev compose stack**, not of elastic, so a note living only in the elastic walk is misfiled — the fixed walk hits it identically and first. |
| **C.5** (B) | "One test run per **codebase** (`api`, `reaper`)" → one codebase, one run, covering `pings`, `processor`, `jobs`, and `retention`. |
| **C.6** (B) | One image, `…/docex_smoke_fixed/api:<v>`. The `reaper` repo line goes; "confirm no third repo appears" becomes "confirm no **second** repo appears" and now also guards against a resurrected `reaper`. |
| **C.9** (B) | Gains a **Clock** checkbox group (below). |
| **C.10** (F) | One sentence of coverage accounting: both versions in this rollback are created *after* the `cicl_version` bump, so the v2→v3 rollback trap the upgrade guide documents is **not** exercised by the walk. A reader must not infer from a green C.10 that the trap is gone. |

### § D — elastic walk

| Item | Change |
| --- | --- |
| **D.4** (F) | Expected-output list gains `schedules.yml`. |
| **D.6** (B, F) | The `sudo find … -exec rm -rf __pycache__` paragraph is **deleted**. Mod 119 fixed the defect — the clear now happens inside the container — and leaving the workaround teaches operators to keep performing a `sudo rm -rf` for a bug that no longer exists. The *other* `docex build` note (the `envinfra up dev` → `build` → `up dev` ordering) was checked against `orchestrate/build.py` and **still holds**: `run_build` still raises `EnvNotRunning` on an empty running set, so the whole-stack precondition is real. It stays, with `./core/<svc>/dist` corrected to `./core/<codebase>/dist`. |
| **D.8** (B) | One ECR repo, one image: `…/docex_smoke_elastic/api:<v>`. "Confirm D.3 phase 2 provisioned exactly **two** ECR repos" → **one**. |
| **D.9** (B) | **The scheduled-task check inverts completely.** The old item asserted `reaper-prune` came up as an `aws_ecs_task_definition` + `aws_scheduler_schedule` + a scheduler-invocation IAM role and **no** `aws_ecs_service`. It becomes: `api-clock` is an ordinary `aws_ecs_service` with a task definition, a log group, a paired otelcol sidecar, and a container-level `healthCheck`; and **no `aws_scheduler_schedule` and no `scheduler.amazonaws.com` invocation role exist anywhere** — asserted twice, once by grepping the compiled `main.tf` (proves the emitter) and once by `aws scheduler list-schedules` + an IAM role scan (proves nothing leaked or orphaned). `aws ecs list-services` count **four → five**. The `-migrate` item drops its "and none for `reaper`" clause. |
| **D.11** (B) | Gains the same **Clock** checkbox group, plus `aws ecs describe-services` showing the clock at `desired_count = 1` — it declares no `replicas` and rule 26 forbids it, so a 2 here is a double-fire. |
| **D.12** (F) | Same coverage-accounting sentence as C.10. |

### The Clock checkbox group (C.9 and D.11)

Goal 3 SC6 requires both walks to *show* a clock firing a job, deferring it, and
`api.worker` picking it up. The minutely `heartbeat` job exists precisely so this
is observable inside a walk window, so the checklist must send the operator to
look, and say what at. Same four assertions on both foundations, differing only
in how logs and the database are reached:

1. **The clock is running and its schedule arrived.** Its startup line names both
   scheduled jobs and the jobs the image implements —
   `clock: 2 scheduled job(s): heartbeat, prune_pings; image implements: …`.
   A mismatch here is the binding-coverage gap nothing asserts yet, visible by
   eye. *(fixed: `docker logs`; elastic: the `/…/api-clock` CloudWatch group.)*
2. **A fire deferred.** Within ~65 s: `jobs: 'heartbeat' fired` followed by
   `jobs: 'heartbeat' deferred as job <uuid>`. Two lines, not one — "fired"
   without "deferred" is the clock reaching the queue and failing.
3. **The worker drained it.** `jobs: 'heartbeat' performed (job <uuid> …)` in the
   worker's logs, with the **same uuid**. Matching the uuid is what makes this a
   proof of the deferral path rather than of two unrelated log lines. Confirmed
   against the database: the `jobs` row has non-NULL `finished_at` and NULL
   `error`. This rides on the postgres/RDS access the ping check in the same step
   already establishes.
4. **The clock answers its own probe.** Its container health is `healthy` —
   `docker inspect --format '{{.State.Health.Status}}'` on fixed, the ECS
   container health status on elastic. Stated with the reason: this is the
   **only** enforcement a clock gets, because no fan-out and no stage test can
   reach it, so an operator who skips it has verified nothing about the clock's
   liveness surface.

`prune_pings` is explicitly *not* waited on — `0 3 * * *` will not fire inside a
walk, and saying so stops an operator waiting for it.

---

## 2. `test_projects.md`

### The hard dependency

Both smoke projects' masterplans point at `test_projects.md § Shape`:

- `fixed/plans/core/masterplan.md:91` and `:125` — the latter carrying
  *"This is not drift and it must not be 'restored'."*
- `elastic/plans/core/masterplan.md:95`

Verified: these are **prose references** (`` `docex/plans/core/test_projects.md § Shape` ``),
not hyperlinks, and both inner `CHANGELOG.md`s carry a fourth. So what must hold
is that a heading spelled exactly **`## Shape`** survives in this file and
carries the record those four pointers promise. The heading name is therefore
**frozen by this mod** — renaming it to "Shape and coverage" or anything else
silently dangles four pointers in two repos I am not allowed to edit. It also
keeps `#shape` resolving for any future link.

### § Shape rewrite

- Opening becomes: **one codebase, three core services** — `api.web`,
  `api.worker`, `api.clock` — one image, one ECR repo, one `-exec` container,
  one `-migrate` task definition, three sidecars.
- The `reaper` bullet is replaced by an `api.clock` bullet: `role: clock`,
  `schedules: {prune_pings, heartbeat}`, `uses: [appdb, api.worker]` with **no
  magic ref** (the edge is the queue, not the mesh), the retired reaper's prune
  now a job on `api`'s driving port.
- **Line 17's claim is deleted, not softened.** *"the only end-to-end coverage of
  the scheduler path anywhere"* describes a path that no longer exists.
- **New subsection `### Coverage given up when `reaper` was deleted`** — the
  record the four pointers resolve to. It states, in this order:
  1. *Why the codebase could not survive.* A clock defers onto its own
     codebase's queue and only the schema-owning codebase may enqueue.
     `reaper` owned no schema — it reached into `api`'s `pings` table — and had
     no worker and no queue, so `reaper.clock` would have had to *do* the work
     inside the singleton, which is the one thing the rule forbids.
  2. *What the walk stopped exercising*, named individually so a future reader
     finds an accounting rather than a gap: **one image per codebase** (the
     multi-codebase build fan-out), **two registry repos** on fixed (C.6),
     **two ECR repos** on elastic (D.8 checked the count explicitly), and the
     **per-codebase `migrate.sh` / `test.sh` fan-out** — with the sharpest edge
     named: a codebase that owns *no* schema and therefore has no `migrate.sh`
     is a shape the walk no longer contains at all.
  3. *What was gained*, so the trade is legible: a real clock container, a
     compiler-delivered schedule table, and a fire → defer → drain path
     end-to-end.
  4. The explicit instruction: **this is not drift, and restoring a second
     codebase is not the fix.** If the fan-out coverage is wanted back it needs a
     second codebase with a genuine reason to exist, not a resurrected `reaper`.
- Line 21's reference-implementation paragraph gains `clock.py` and points at the
  two new hex modules, including the standing warning that the defer-side and
  perform-side dispatch tables are **not** duplication — because downstream
  projects copy this tree and inherit whatever it fails to explain.
- The tree diagram's `core/{api,reaper}/` → `core/api/`.

---

## 3. `upgrades/upgrade_1.7.0.md`

Every box in its own "Before this ships" checklist is worked, then the banner
and the `status:` frontmatter field are deleted.

**Audience rule for this rewrite:** the guide must be readable start-to-finish by
someone who has never heard of advance 005, and must not require reading a design
record. All eight existing links into `docex/plans/advances/005_*` are therefore
demoted — the guide states what to do and why in its own words, and cites a
design record only as optional further reading, never as a step's prerequisite.

### New shape

One release, three author-visible changes plus one behavioural one:

| § | Step | Source |
| --- | --- | --- |
| — | Summary — all three changes, and an up-front warning that the scheduler migration needs **application code**, not just `infra.yml` | new |
| 1 | Repin + sync the shim | kept |
| 2 | Rename the two `infra.yml` keys | kept |
| 3 | **Merge `depends_on` + `consumes` into `uses`** | **new** |
| 4 | **`role: scheduler` → `role: clock`** | **new** |
| 5 | Qualify core magic refs — five segments | was 3 |
| 6 | `domain_default_process` → `domain_default_service` | was 4 |
| 7 | Bump `cicl_version` to `"3"` | was 5 |
| 8 | Recompile and diff | was 6, **table rewritten** |
| 9 | Redeploy | was 7 |
| 10 | ⚠ REQUIRED — telemetry keys | was 8 |

**Rename first.** Step 3 authors `uses` entries whose dotted targets are
`<codebase>.<service>` — vocabulary step 2 establishes. Doing `uses` first means
writing every target twice.

### Step 3 — the `uses` merge

- Mechanically: `depends_on:` → `uses:`, merged with any `consumes:` list on the
  same core service; `depends_on:` deleted from **backing services entirely** —
  a backing service is now a graph sink and may declare no outbound edges.
- Both old names are **hard errors, not silent aliases**, so a missed one fails
  loudly at compile.
- The consequence that will surprise people, stated as its own bolded note:
  **project-level startup ordering is gone.** The compiler emits no compose
  `depends_on:` / `condition:` on any core-service block. A project whose boot
  code was relying on the compose gate — which `dev` and `test` were silently
  supplying and elastic `prod` never was — will now fail on a cold start, and
  that is the connection-resilience mandate becoming visible rather than a
  regression. The **per-codebase `-exec` block keeps its gate**, so `migrate.sh`
  still waits for its database.

### Step 4 — `scheduler` → `clock`

Written as a migration with a **precondition stated plainly before the steps**:
the codebase must own a queue. A clock defers and does not work; only the
schema-owning codebase may enqueue; so *a codebase with scheduled work but no
queue and no worker cannot host a clock*, and the honest answer is that the
schedule moves to a codebase that can — or the codebase grows a queue. This is
the single most likely place a downstream upgrade stalls, and burying it inside
the steps would let a project restructure half its `infra.yml` before finding
out.

Then: each `role: scheduler` service becomes **one** `clock` core service;
`schedule:` becomes `schedules:`, a map of job name → **bare 5-field UTC cron**;
each old job's `command` argv becomes a **driving-port method**, dispatched by
name in a `Cron`-mechanism controller. A short before/after `infra.yml` pair, the
architecture chain, a pointer to
[`clock.md`](../doctrine/infrastructure/specifics/clock.md) as the rule of record,
and — since it exists and is the point of a reference implementation — a pointer
to the worked example in `docex/test_projects/*/core/api`.

Also flagged, because each is a behaviour change an operator can be bitten by:
one clock per codebase, `replicas` forbidden (rule 26), no `web` network
(rule 27), **no cron dialect translation** (any 6-field or `?`-day expression
inherited from EventBridge must be rewritten by hand), no backfill on a missed
fire, and the clock's invisibility to staging tests.

### Step 8 — the diff table, rewritten

The "expect exactly four differences" table is **replaced, not extended**. The
byte-identical-output guarantee was the rename's property alone and it no longer
holds, so the table's contract changes from *"exactly four rows"* to *"every
difference must attribute to one of these causes"*:

| Cause | What moves |
| --- | --- |
| Rename | the two elastic env-tier tag **keys**, the two OTel resource attribute keys (values unchanged in all four) |
| `uses` | `depends_on:` / `condition:` **disappear** from every core-service compose block; the `-exec` block's gate stays |
| Reconcile fix (mod 114) | `wait_for_steady_state = true` appears on **every** `aws_ecs_service` |
| `clock` (only if the project had a scheduler) | `aws_scheduler_schedule`, the invocation IAM role and its policy, and the Ofelia container + INI all **disappear**; a task definition + `ecs_service` + log group + sidecar appear; `deployment_minimum_healthy_percent = 0` / `maximum = 100` on the clock; `DOCEX_SCHEDULES_YAML` in its env; a **new output file** `infra/output/<env>/schedules.yml` |

The "any change to a container name, hostname, image ref, contract path or
`Name` tag is a defect" guard is **kept** — it survives all four causes and is
the guard actually worth having.

`wait_for_steady_state` gets its own consequence note: an elastic apply now
blocks on rollout and **fails** if a service cannot converge, rather than
returning and letting the release proceed. Applies take longer; a broken image
now fails the apply instead of the health check afterwards.

### The `cicl_version` rollback trap

A dedicated subsection under Doctrine / behavior notes, mirroring
[`upgrade_1.6.0.md`'s framing](./upgrade_1.6.0.md) at its v1→v2 boundary: for
exactly one release cycle, `docex rollback` refuses at cheap pre-flight, because
rollback recompiles the **target** version's `infra.yml` with the **current**
docex and every existing tagged release declares `cicl_version: "2"`. Fix
forward; get a second v3 release out promptly; the refusal is early and touches
nothing. Precedent is cited so a reader recognises the shape rather than reading
it as new breakage.

### Other guide edits

- **"What does not move":** the `consumes:` row is deleted (it moved). Replaced
  by a row recording what *did* survive the merge — the dotted
  `<codebase>.<service>` target spelling is unchanged, so a `consumes:` list's
  contents transplant into `uses:` verbatim.
- **Verification:** greps extended to `depends_on:`, `consumes:`,
  `role: scheduler`, and `schedule:`; a check that `schedules.yml` rendered; a
  post-deploy check that the clock's container health is green and a job fired.
- **Doctrine / behavior notes:** `docex roles` now lists six roles and
  `scheduler` is not among them; `docex dag` derives solid/dashed edges from
  **target kind** rather than from which field an edge was declared in;
  `specifics/scheduler.md` is replaced by `specifics/clock.md` and every inbound
  pointer moved.
- **`severity: minor` is confirmed, not re-opened** — the advance's settled
  decision, matching how 1.6.0 shipped a breaking change as a minor. The
  "Decide the severity" box is ticked with that recorded.

---

## 4. `CHANGELOG.md`

`[Unreleased]` already carries good per-mod prose. The work is making it read as
one release rather than six mods:

1. **A lead paragraph**, matching the 1.6.0 entry's shape: what the release is,
   that it is breaking on `cicl_version` 2 → 3, that the rollback window applies
   for one cycle, and a pointer to `upgrades/upgrade_1.7.0.md`.
2. **Two stale intra-release statements repaired** in the rename entry — it
   currently tells a reader of the *shipped release* that "`consumes:` … are
   unchanged" (it is gone) and that "`cicl_version` stays `"2"`" (it is `"3"`).
   Both were true when written mid-advance and are false at the cut. This is the
   single thing most likely to mislead a downstream reader.
3. **Ordering within `### Changed`** so the account builds: the vocabulary
   rename first (it is the vocabulary the other entries are written in), then
   `uses`, then the clock.
4. **One `### Added` line for the doctrine surface** the release ships —
   `specifics/clock.md` replacing `specifics/scheduler.md`, and the smoke
   projects as the clock's reference implementation — because that is what a
   downstream project copies and nothing currently announces it.

Mod-number citations (`(mod 119)`) stay: 113 of them exist across released
sections, so it is established form here.

---

## 5. Link and anchor integrity

A slug-accurate checker was written and run over all 774+ markdown links in the
repo (`scratchpad/anchors2.py`; GitHub slug rules including `-1` duplicate
suffixes). Live files outside frozen mod/advance records currently carry these
dangling anchors — the guide's "6 dangling anchors" box, located:

| File | Anchor | Disposition |
| --- | --- | --- |
| `PRE_CUT_CHECKLIST.md:170` | `cicl.md#consumes-relationships` | fixed by the B.3.2 rewrite |
| `upgrade_1.6.0.md:22` | `cicl.md#process-types` | **target-only** repoint → `#core-services`; see design question 2 |
| `uses_relation_merge.md:41,78` | `cicl.md#depends-on-relationships` | repointed → `#uses-relationships` / `#startup-ordering-is-not-a-doctrine-feature` |
| `advance_plan.md:22` | `#step-0--recon-the-service-connect-name-freeze` | the heading gained "✅ COMPLETE"; link updated |
| `service_connect_reconcile_trigger.md:411` | `#two-implementation-details-that-matter` | heading renamed; link updated |

The checker is re-run after the edits; **zero** dangling anchors outside frozen
records is the gate. Two pre-existing ones are explicitly **not** mine and are
reported rather than fixed: `upgrade_1.1.0.md:24` (predates this advance) and
four `../doctrine/...` paths in released `CHANGELOG.md` sections that escape the
repo root (historical entries, frozen).

---

## 6. The held seam — binding coverage

`clock.md:96` reads:

> The [check step](../cicd.md#check-step) **can** assert that every declared job
> name has a binding in the clock's dispatch table, catching a schedule that
> names a job nobody implements.

The operator's ruling is outstanding. Two of the three live outcomes require
editing that sentence, so **it is left exactly as written** and no marker is
added to the doctrine file — a `<!-- pending -->` comment in a rule-of-record
document would ship an open question into 1.7.0.

The seam is instead marked where it is looked for: this section, and a **HELD**
row added to `advance_plan.md § Close-out`. The pending action, per outcome:

| Outcome | Action after the ruling |
| --- | --- |
| (a) `docex check` gate reading `--list-jobs` | one-line `clock.md` edit (`can` → asserts) **+ a separate mod** to build the gate and a `cicd.md § Check Step` line — not this mod |
| (b) clock-side startup validation | one-line `clock.md` edit + a `docex` mod; the smoke `clock.py` already exposes `ContJobsCron.job_names()` instance-free for it |
| (c) drop it | one-line `clock.md` edit softening "can assert" to a note that the gap is known and unasserted |

Everything else in this mod is independent of the ruling. The checklist's Clock
group step 1 already sends the operator to the clock's startup line, which prints
scheduled names beside implemented names — so the gap is visible by eye in the
walk regardless of which way the ruling goes, and that is stated in the checklist
without predicting the outcome.

---

## Verification

1. The anchor checker reports **zero** dangling anchors in live files.
2. `## Shape` exists in `test_projects.md` and carries the coverage record; all
   four inbound pointers (two masterplans, two inner changelogs) verified by
   grep to name that exact heading.
3. `PRE_CUT_CHECKLIST.md` re-read end to end, top to bottom, after editing:
   zero occurrences of `reaper`, `scheduler`, `depends_on`, `consumes`,
   `cicl_version: "2"`, or "five-artifact"; every count (repos, images, ECS
   services, test runs) checked against the tracked compiled output rather than
   against prose.
4. `upgrade_1.7.0.md` has no `status:` field, no banner, no unticked box, and no
   link whose resolution is required to follow a step.
5. `git status` shows changes **only** under `docex/plans/`,
   `docex/test_projects/PRE_CUT_CHECKLIST.md`, `upgrades/`, and `CHANGELOG.md`.
   Nothing inside `test_projects/{fixed,elastic}/` — verified with
   `git -C test_projects/fixed status` and the elastic equivalent both clean.
6. No `docex` source change, so the suites are untouched; they are re-run once as
   a no-regression check (988 / 20).

## Commits

Path-scoped, on `005_process_type_solidification`, per the mod cycle: one
`mod 120 design done, impl. steps written` after `implementation.md`, one
`mod 120 complete; designed, implemented, and documented.` at the end. No inner
repo is touched, so there is no inner commit and no tag move.

---

## Design questions

1. **The held seam — confirm the marker.** Proposal above: `clock.md:96`
   untouched, seam recorded here and as a HELD row in the advance plan, nothing
   pending shipped into the doctrine. Confirm, and relay the ruling when you have
   it — outcomes (b) and (c) are then a one-line edit I can land inside this mod;
   outcome (a) needs a follow-on mod for the gate.

2. **`upgrade_1.6.0.md:22` — repoint an anchor in a shipped guide?**
   `README.md § One Guide Per Release` says a guide is authored once and never
   revised, and the rename plan freezes 1.6.0's guide against re-wording. But its
   link to `cicl.md § Process Types` now 404s because *this* advance renamed the
   heading. Proposal: change the **link target only** to `#core-services`,
   leaving every word of prose — the smallest edit that keeps the guide usable.
   The alternative is knowingly shipping a broken link in a document downstream
   projects are told to follow. Ruling wanted, since it is a precedent about what
   "never revised" covers.

3. **Two new audit items (B.16, B.17) beyond the brief.** They cover Goal 2 SC4
   ("no compiled compose contains `depends_on:` on a core-service block") and
   Goal 3 SC3 (`schedules.yml` renders; delivery is a literal, not a path). Both
   goals are stated as success criteria of this advance and nothing in the
   checklist currently looks for either. Adding them lengthens the audit by two
   greps. Assumed **yes** unless you say otherwise.

4. **Counting note, for the record rather than a decision.** Mod 117's overview
   says the target shape is "one codebase, **four** core services"; the tree has
   **three** (`web`, `worker`, `clock`). Every count in these documents is
   written from the tree. Flagging it because the same figure may have been
   carried into the advance report.
