# Mod 148 — The `job` substrate + `docex test` as its first (container) vessel

**Advance 009 (Test Overhaul), Wave 2 keystone. Implements F3 core + F4's
single-run increment, on the SC3 substrate.** Design intent is authoritative in
[`pre_plan.md` § SC3 "Resolved design" D1–D5](../../advances/009_test_overhaul/pre_plan.md)
and [`advance_plan.md` Wave 2 Mod 3](../../advances/009_test_overhaul/advance_plan.md);
this overview builds to that spec and records the concrete shapes settled while
reading the post-147 codebase.

This is docex-source work (oriented by the `docex-edit` skill). Per
`docex_process.md`, the doctrine is edited **first** and only with operator
(here: `sarge`) sign-off — hence this design pause.

---

## 1. What this mod builds (and what it deliberately does not)

**Builds:**

1. A **general, vessel-polymorphic `job` abstraction**: any long docex command
   can launch detached → an on-disk **handle**; one uniform verb set operates on
   handles (`job ls|status|wait|logs|result`).
2. The **handle = an on-disk run record** under `.docex/runs/<id>/`
   (`meta.json`, `status.json`, `exit`, `log`).
3. **`docex test` becomes a durable job with a CONTAINER vessel**: the blocking
   default is preserved (exit-code contract intact for CI) but the work runs in a
   **detached, deterministically-named sibling container**; `docex test --detach`
   returns the handle in ~<5 s.
4. The **deterministic vessel-container name is the lock** (no flock): a second
   concurrent run on the same `(project, test)` scope loses the `docker run
   --name` create race atomically → refuses.
5. **F4's single-run self-heal reaper**, built on the **same enumeration
   primitive** `job ls` uses (an orphan = a record whose vessel is dead with no
   `exit` file). Reaping clears a hard-killed vessel **and** its leaked compose
   stack, and leaves an authoritative `exit` file.
6. **`.docex/` gitignore** handling (see § 6 — the premise needs a correction).

**Explicitly NOT built (later mods — kept out by design):**

- Host-process vessel for `check`/`merge` → Mod 4 (docex 149). The abstraction is
  built vessel-polymorphic so Mod 4 slots it in; **this mod ships only the
  container vessel.**
- The slot axis / `--slots N` / any slot segment in names → Wave 3. Here the lock
  scope is per-`(project, test)`, implicitly slot 1, **no suffix** — compiled
  output is untouched and byte-identical to today.
- The FLEET / multi-slot reaper → Wave 3 Mod 9. Only the single-run self-heal
  reaper here.
- Recheck-skip / `.docex/checks/` provenance → Mod 5.
- Scoped runs / `docex test unit|integration [subset]` / no-stack fast lane →
  Mod 6. **`docex test` still runs BOTH shims in the stack, totally, exactly as
  Mod 147 left it** — we wrap that body in durable-job machinery, we do not change
  what it runs.
- The healthcheck **tick/staleness** mechanism (wedged-suite detection) — D3
  defers it; a finite job differs from a perpetual loop. We reuse only the
  **exit-file half** of the liveness pattern.

---

## 2. The run record (D2, D4) — the handle

A handle is a directory `.docex/runs/<id>/`. `<id>` is a unique, sortable run id:
`YYYYMMDDThhmmssZ-<6hex>` (UTC timestamp + short random suffix for collision-free
same-second launches; lexicographically sortable so `job ls` orders by recency).

| File | Written by | Content | Consumed by |
| ---- | ---------- | ------- | ----------- |
| `meta.json` | foreground, at launch (immutable) | `{id, kind:"test", scope:"<proj>/test", slot:1, vessel_kind:"container", vessel_name, created_at, docex_version, params:{}}` | every verb; the reaper |
| `status.json` | the vessel (and the reaper on orphan) | `{state, started_at, updated_at, finished_at, exit_code}` — state ∈ `launching\|running\|succeeded\|failed\|orphaned` | `job status`, `job ls` |
| `exit` | the vessel (terminal); OR the reaper (synthetic, on orphan) | the integer exit code, **atomically** (`write tmp + os.replace`) | `job result`; the foreground/`job wait` blocking loop |
| `log` | the vessel (stdout+stderr redirected here) | the run's interleaved output | `job logs`, and the foreground attach-tail |

**The `exit` file is the authoritative terminal signal (D3).** It survives vessel
teardown AND a killed foreground monitor, and is what `job result` and every
blocking `wait` key on. This is the **exit-file half of the healthcheck liveness
pattern** — cited, not reinvented, from
[`healthchecks.md § What the probe must actually check`](../../../../doctrine/infrastructure/healthchecks.md#what-the-probe-must-actually-check)
and [`internal_dependency_rules.md § Entrypoints rule 6`](../../../../doctrine/hexagonal_architecture/internal_dependency_rules.md#entrypoints).
`status.json` (progress/timestamps) **plus** vessel-liveness
(`docker inspect -f '{{.State.Running}}' <vessel_name>`) drives `job status`.

`.docex/` is docex's machine-local, gitignored scratch dir — the single home for
local state (this mod adds `.docex/runs/`; Mod 5's `.docex/checks/` joins it). It
is **not** `infra/output/` (git-tracked compiled output). A missing/unreadable
record degrades safely to "not found" rather than erroring.

---

## 3. The job command surface

Additive to the dispatcher. `docex test` gains `--detach`; a new top-level `job`
command groups the verbs; one hidden internal verb runs inside the vessel.

```
docex test              # blocks, attaches (tails log), exits with the run's code — durable underneath
docex test --detach     # creates the run + launches the vessel, prints <id>, returns (~<5 s)
docex job ls            # enumerate all runs: id, kind, scope, state, started, exit
docex job status <h>    # status.json reconciled against vessel liveness
docex job wait <h> [--timeout S]   # block until the exit file appears (or timeout); exit with its code
docex job logs <h> [-f] # print (or follow) .docex/runs/<h>/log
docex job result <h>    # print + exit with the authoritative `exit` file's code
docex __run-job <id>    # HIDDEN internal entrypoint — runs inside the vessel only (not in help/table)
```

`job ls` is the **durable, non-fragile discovery path** — a killed/compacted agent
recovers a run here, never via a `pgrep`/`docker ps` proxy. It reads
`.docex/runs/` and reconciles each record against its vessel's liveness — the
**same enumeration the reaper performs**, so `ls` and the reaper share one
primitive (§ 5).

---

## 4. The container vessel & its lifecycle (the escalated fork)

### 4.1 Why the vessel is a separate detached docex container

Under DooD the foreground `docex test` runs *inside* the docex container the shim
launched with `docker run --rm` (foreground, blocking). When the operator's shim
call is killed, **that** container dies. So the durable work cannot live in the
foreground process — it must run in a **separate `-d` sibling container** the
foreground spawns via the docker socket. That sibling is the **vessel**. It runs
the existing `run_test` loop (compose up → migrate → both shims → `finally`
compose down) end-to-end, then records.

### 4.2 How the vessel is launched — **self-inspection clone** (recommended)

The vessel needs the *same* mount/uid/image context the shim gave the foreground
(project root at host path, docker.sock, HOME, `/etc/passwd|group`, `~/.docker`,
`--user`, `--group-add`, `-w`). Rather than **re-derive** the shim's mount set in
Python (which would drift from the bash shim — a real hazard), the foreground
process **inspects its own container** (`docker inspect $HOSTNAME`) and clones:
`.Config.Image`, `.Mounts`/`.HostConfig.Binds`, `.Config.User`, `.Config.Env`
(HOME), `.Config.WorkingDir`, `.HostConfig.GroupAdd`. It then:

```
docker run -d --name <vessel_name> <cloned binds/user/env/workdir/group-add> \
    <image> docex __run-job <id>
```

This guarantees zero drift from the shim (the vessel is a faithful clone of the
foreground container) and needs **no shim change** — the shim stays additive and
backward-compatible, exactly as its own rule requires. Fallback if self-inspect is
undesirable: reconstruct from `ctx.project.docex_version` + the documented shim
mount contract. **Recommended: self-inspect clone.** (Escalated — see § 9 Q3.)

### 4.3 The vessel ≠ the compose stack; who owns teardown

The vessel is the **orchestrator**; the `test` compose stack is what it brings up.
Names are distinct:

- **Vessel container name (the LOCK):** `<dns_label(project)>-test-runner`
  (net-new; no collision with compose's `<proj>-<svc>-<n>` service containers; no
  slot suffix → slot-1 scope).
- **Compose stack project name:** unchanged — `<dns_label(project)>-test`
  (`env_compose_project`). **Byte-identical to today.**

The vessel runs `run_test`, whose `finally` tears the stack down. On a **clean**
finish the stack is already down; the vessel records and exits. On a **hard-kill**
of the vessel (SIGKILL), the `finally` never runs → the compose stack is orphaned
(left up). **The reaper therefore owns teardown-of-last-resort** (§ 5): reaping an
orphaned vessel also `compose down -v`'s that scope's stack. This is the answer to
"how the detached container relates to its compose stack's lifecycle": the vessel
owns the stack within its lifetime; the reaper assumes ownership if the vessel dies
without completing.

**Vessel is NOT `--rm`.** The deterministic name must persist after exit so the
preflight can classify it (completed vs. orphaned) and reap deterministically. At
most one dead vessel per scope accumulates; it is reaped on the next run.

### 4.4 `run_test` and `check` are unchanged

`run_test` stays a **plain synchronous function returning an exit code — the "job
body."** The vessel's `__run-job` calls it; the foreground never does. **`check`
keeps calling `run_test` directly** (synchronous, against its ephemeral worktree
with its worktree-unique `project_name`) — no vessel, no nesting. This keeps
check/merge green and holds the blast radius to: the new `jobs/` package, the
`docex test` handler, the `job`/`__run-job` dispatch, and the doctrine text.
`orchestrate/test.py` itself needs **no change** (its existing tests stay green).

### 4.5 Foreground flow (blocking default) — exit-code contract preserved

1. Preflight the scope: inspect `<vessel_name>`. **Running → REFUSE** (lock held).
   Dead → reap (§ 5). Absent → proceed.
2. Create `.docex/runs/<id>/` + `meta.json` + `status.json{state:launching}`.
3. Self-inspect clone → `docker run -d --name <vessel_name> … docex __run-job <id>`.
   **If create fails on a name conflict (raced) → REFUSE.** (The `docker run
   --name` create is the atomic arbiter, per D5.)
4. Attach: tail `log`, poll for `exit`. When `exit` appears → exit with its code.
   *If the foreground is killed here, the vessel is unaffected and the run stays
   re-attachable via `job wait <id>`.*

`--detach` stops after step 3 and prints `<id>`.

---

## 5. The shared enumeration primitive: `job ls` = the reaper (F4)

One function reconciles a record against reality:

```
classify(record):
  if `exit` file present            -> TERMINAL (succeeded/failed, per the code)
  else if vessel running            -> LIVE (in progress)
  else                              -> ORPHAN (vessel dead/absent, no exit file)
```

- **`job ls`** runs `classify` over every record and renders the table.
- **The reaper** runs `classify` for the one scope about to launch:
  - LIVE → the lock is held → **refuse** (do not touch it).
  - TERMINAL → a prior completed run holds the name → `docker rm` the dead vessel
    (frees the name) and proceed.
  - ORPHAN → **self-heal**: write a synthetic authoritative `exit` (a distinct
    non-zero orphan code) + `status{state:orphaned}` into the record, `compose
    down -v` the scope's leaked stack, `docker rm` the dead vessel, then proceed.

Because both share `classify`, `ls` and the reaper can never disagree about what an
orphan is. Reaping only ever `rm`s a **non-running** container (never force-kills a
live one), so it can't harm a legitimate concurrent run.

---

## 6. `.docex/` gitignore — a correction to the stated premise

The kickoff states `.docex/` "is currently in NO gitignore … does not exist on
disk — genuinely net-new (the masterplan's 'existing `.docex/`' phrasing was
aspirational)." **Reading the tree, that premise is inaccurate in three ways, and
it changes what item 6 needs to do:**

1. `.docex/` is an **established, already-created** scratch dir: `check` creates
   `.docex/worktrees/`, `aggregate` writes `.docex/agg/<env>.env`. The
   masterplan's "existing `.docex/`" is real, not aspirational.
2. **Downstream projects already gitignore `.docex/`**: mod 056 added `.docex/` to
   `inception.md`'s canonical `.gitignore` default block, and **both** smoke seeds
   (`test_projects/{fixed,elastic}/.gitignore`) already carry it (`# docex
   ephemeral git worktrees` / `.docex/`).
3. **`docex_install.sh` writes no gitignore entries at all** — by explicit design
   (its header and the masterplan say project-structure scaffolding, gitignores
   included, is `inception.md`'s job, not the installer's).

So the true gap is narrow: **`docex`'s own repo** — `docex/.gitignore` — does not
list `.docex/`. That's the one net-new fix strictly required (docex's own
smoke/test paths can create `.docex/`).

**Proposed handling (confirm at § 9 Q4):**
- **(b) docex's own repo:** add `.docex/` to `docex/.gitignore`. Required, trivial.
- **(a) downstream projects:** already covered by the inception default for new
  projects. For **existing pre-056 installs**, add an **idempotent gitignore-ensure
  step to `docex_install.sh`** (append `.docex/` only if absent) — this honors the
  kickoff's "existing installs pick it up on re-run" and the advance-plan blocker,
  at the cost of the installer taking on one gitignore write (a small, deliberate
  widening of its remit, which I'll note in the masterplan). If `sarge` prefers to
  keep the installer scaffolding-free and rely on the inception default + a
  project-upgrade guide, I'll drop the installer change — flagged as Q4.

---

## 7. Package structure (escalated fork — § 9 Q1)

New top-level package `src/docex/jobs/` (the substrate is a genuinely new concern
spanning `test` today and `check`/`merge` next mod; it should not live under
`orchestrate/` or `pipeline/`):

| Module | Responsibility |
| ------ | -------------- |
| `jobs/record.py` | run-id minting, `.docex/runs/<id>/` layout, atomic `exit` write, `meta`/`status` read+write, `classify()` |
| `jobs/vessel.py` | `Vessel` protocol (polymorphic) + `ContainerVessel` (self-inspect clone launch, liveness, rm). Mod 4 adds `HostProcessVessel`. |
| `jobs/reaper.py` | preflight reap for a scope, reusing `record.classify` + `ContainerVessel` + a `compose down -v` of the leaked stack |
| `jobs/commands.py` | `job ls\|status\|wait\|logs\|result`, the `--detach`/launch/attach wrapper, and the `__run-job` in-vessel entrypoint (dispatches on `meta.kind` → the job body) |

`jobs/` depends on the existing `docker` client protocol (extended with the few
new verbs below) and, for the `test` body, on `orchestrate.test.run_test`.

**DockerClient protocol additions** (thin, all through the one subprocess
chokepoint): `run_detached(name, image, command, binds, user, env, workdir,
group_add) -> (rc, name_conflict:bool)`, `inspect_self() -> ContainerSpec`,
`container_running(name) -> bool | None` (None = absent), `container_rm(name)`.
The name-conflict signal is what makes the lock refusal detectable.

---

## 8. Testing plan (must be fully green; no real 6-min suite)

Each layer is separable and unit-testable with the fake docker client + a tmp
`.docex/`:

- **Record IO** (`tmp_path`): id monotonicity/sortability, atomic `exit` write,
  `meta`/`status` round-trip, `classify` for all three outcomes.
- **`--detach` returns fast + a handle**: assert the handler creates the record and
  issues exactly one `run_detached` and returns without polling.
- **Lock refusal**: fake `run_detached` returns `name_conflict=True` (or preflight
  sees a *running* vessel) → assert the second run refuses with a non-zero,
  scope-naming message and launches nothing.
- **Killed-monitor re-attach** (the headline criterion, *no real 6-min suite*):
  create a record with a "running" fake vessel and no `exit` → `job ls` classifies
  it LIVE and lists it; then write an `exit` file (simulating the vessel finishing
  after the monitor died) → `job wait <id>` returns the real code, `job result`
  reads it. Proves re-attachability without a real process.
- **Orphan reaping**: record with no `exit`, vessel `container_running → False` →
  reaper writes the synthetic `exit`, issues `compose down -v` + `container_rm`,
  then the fresh launch proceeds; `job result` reads the authoritative synthetic
  code.
- **`__run-job` records**: drive it with a fake docker where `run_test` returns rc
  ∈ {0, k} → assert terminal `status` + atomic `exit` written with rc, log
  populated.
- **Dispatcher**: `job` subcommands parse; `__run-job` is hidden from usage/help.
- **check/merge unaffected**: existing `test_orchestrate_test.py`,
  `test_pipeline_check.py`, `test_pipeline_merge.py` stay green unchanged.

**One real-docker integration test** (`tests/integration/`, `-m integration`): a
**trivial short-lived job body** (a vessel that runs a ~1 s no-op container and
exits 0 — *not* the real suite) to prove the real detached-container → `exit`-file
→ `job wait` path across the actual docker boundary, per `docex_process.md`'s
"add an integration test when behavior crosses a real boundary."

Run with `python -m pytest tests` (canonical) — never bare `pytest`; `-m
integration` alone (per `docex_process.md § Running the automated tests`).

---

## 9. Doctrine amendments proposed (SC3 — need `sarge` sign-off before impl)

Per the advance's per-mod handling rule, this mod lands SC3's doctrine text. All
are in the SC3 named radius. **Doctrine is the upstream spec; edited first, with
your approval:**

1. **`docex.md`** (primary):
   - New **`## Command Lifecycle`** section retraining the blocking-only mental
     model: most commands are synchronous, but a command may be a **durable job** —
     it launches a vessel whose run outlives the invocation; `--detach` returns a
     handle; the `job` verbs operate on handles; the blocking default is preserved
     (exit-code contract intact) but durable underneath. Cites `healthchecks.md` /
     `internal_dependency_rules.md rule 6` as the exit-file liveness precedent.
   - Add **`job`** to the Provided Tools table + a **`### job`** subsection
     (`ls|status|wait|logs|result`).
   - Amend **`### test`**: document durability + `--detach`; note a killed monitor
     leaves the run re-attachable; note the per-`(project, test)` deterministic-name
     lock and self-heal reaper. Keep "runs both shims in a fresh `test` env" — Mod 6
     changes *what* it runs, not this mod.
   - Note the `./bin/docex` shim stays **unchanged** and additive (the vessel is
     launched by docex over the socket, not by the shim).
2. **`cicd.md`** (light): at the build-test-step / check surface, one line noting
   `test` is now a durable job (a killed monitor no longer orphans the run); no
   change to the step's *logic*.
3. **`healthchecks.md` + `internal_dependency_rules.md`**: **cite-only, no edits**
   — reused as precedent for the exit-file signal; the tick/staleness half is
   explicitly deferred (D3), so adding a back-reference risks implying the deferred
   mechanism exists. (Confirm cite-only vs. a one-line back-reference — Q2.)
4. **`docex_install.sh` / gitignore**: per § 6 (pending Q4).
5. **`testing` skill**: light async retrain — a sentence that `docex test` is a
   durable, re-attachable job and `--detach` + `job wait` exist; fuller retrain in
   Mods 4/6. (Flagged: is a light touch acceptable here?)

**docex's own core-planning-doc diff** (Documentation step of this mod; noted for
your project map): `masterplan.md` — Subcommand Surface table (+`job`, `test
--detach`), Filesystem Surface (+`.docex/runs/<id>/{meta,status,exit,log}`),
Repository Structure (+`jobs/` package), and a short **Command Lifecycle / job
substrate** subsection mirroring the doctrine's. `docex_process.md` — no change
expected. (Per the advance plan, docex's own docs get a `project-cohere`
reconciliation at close-out; these per-mod updates are the normal mod-process doc
step, not a substitute.)

---

## Design questions for `sarge` (please review before I write `implementation.md`)

- **Q1 — package location.** Recommend a new top-level `src/docex/jobs/` (§ 7)
  over folding into `orchestrate/`/`pipeline/`, because the substrate is
  vessel-polymorphic and spans callers. Confirm?
- **Q2 — liveness citation.** Recommend **cite-only** for `healthchecks.md` /
  `internal_dependency_rules.md` (reuse the exit-file half; the tick/staleness half
  is deferred). Or do you want a one-line back-reference added there?
- **Q3 — vessel launch mechanism.** Recommend the **self-inspection clone**
  (§ 4.2) so the vessel's mounts/uid/image can't drift from the shim, with no shim
  change. Acceptable, or prefer reconstruct-from-`docex_version`?
- **Q4 — `.docex/` gitignore (premise correction, § 6).** `.docex/` is already
  gitignored downstream (inception default + both smoke seeds) and already exists
  on disk (worktrees/agg). Proposed: **(b)** add `.docex/` to `docex/.gitignore`
  (required); **(a)** add an idempotent `.docex/`-ensure to `docex_install.sh` for
  pre-056 existing installs (a small widening of the installer's remit). Approve
  both, or keep the installer scaffolding-free and rely on the inception default?
- **Q5 — orphan exit code.** The reaper's synthetic `exit` for a hard-killed
  vessel: propose a distinct docex-reserved code (e.g. `137`, matching
  SIGKILL/128+9, so it reads as "killed") so `job result` reports something
  honest. Any preference?
