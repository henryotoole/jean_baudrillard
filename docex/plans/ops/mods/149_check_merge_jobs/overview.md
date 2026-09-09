# Mod 149 — `check` / `merge` become `--detach`-able jobs on the substrate

**Advance 009 (Test Overhaul), Wave 2, Mod 4.** Converts `docex check` and
`docex merge` into callers of the Mod 148 durable-job substrate, so each can run
`--detach` → a handle and `docex job ls|status|wait|logs|result` operate on them
uniformly (covering test/check/merge). Design intent is authoritative in
[`pre_plan.md` § SC3 "Resolved design" D1–D2](../../advances/009_test_overhaul/pre_plan.md)
and [`advance_plan.md` Wave 2 Mod 4](../../advances/009_test_overhaul/advance_plan.md);
this overview builds to that spec **and formally escalates one amendment to it**
(§ 4 — the "host-process vessel" framing).

This is docex-source work (oriented by the `docex-edit` skill). Per
`docex_process.md`, the doctrine is edited **first** and only with `sarge`'s
sign-off — hence this design pause.

---

## 1. What this mod builds (and what it deliberately does not)

**Builds:**

1. **`docex check` and `docex merge` become durable jobs** on the Mod 148
   substrate: each preflights a per-command lock, creates an on-disk run record,
   launches a vessel, and — unless `--detach` — attaches to tail the log and block
   on the authoritative `exit` file. The blocking default is preserved (exit-code
   contract intact for CI), durable underneath: a killed monitor leaves the run
   **re-attachable** via `docex job wait <h>`, exactly as `test` now is.
2. **Two new job bodies** registered under `_JOB_BODIES` (`check`, `merge`),
   reusing the existing `run_check` / `run_merge` functions **unchanged**.
3. **A generalized reaper**: orphan teardown now keys off the orphaned record's
   `meta` (kind/params) instead of the hardcoded `test` compose stack — a `test`
   orphan → `compose down -v` its stack; a `check`/`merge` orphan → remove its
   ephemeral worktree and tear down its throwaway build stack.
4. **The doctrine text** amending SC3's remaining check/merge surfaces
   (`docex.md`, `cicd.md`) — see § 6.

**Explicitly NOT built (kept out by design):**

- **No change to what `check`/`merge` DO.** The git/version/contract gates, the
  build, the test invocation inside `check`, `merge`'s Mod-146 `ls-remote`
  preflight and its defensive `check` all stay exactly as they are. This mod
  **wraps** the existing bodies in the durable-job machinery; it does not edit
  their logic.
- **No recheck-skip / `.docex/checks/` provenance record** — that is Mod 5
  (docex 150). `merge` still runs its defensive `check` every time.
- **No slot axis** — the lock scope is per-`(project, check)` / `(project,
  merge)`, implicitly slot 1, no suffix. Compiled output is untouched.
- **No new `Vessel` subclass** — see § 4. The container vessel Mod 148 shipped is
  reused as-is; the polymorphism that matters lives in the *body* and the *reaper
  teardown*, not in a vessel class.

---

## 2. The shape of the change (mirrors Mod 148's `run_test_job`)

Mod 148 already established the exact pattern. `check`/`merge` follow it 1:1.

- **Dispatcher (`__main__.py`):** `_cmd_check` / `_cmd_merge` gain a `--detach`
  flag and route through new wrappers `run_check_job` / `run_merge_job` in
  `jobs/commands.py` (replacing the direct `run_check(ctx, docker, git)` /
  `run_merge(ctx, docker, git)` calls). The help text for `check`/`merge` gains
  the "durable job; --detach for a handle" note, matching `test`.
- **`jobs/commands.py`:**
  - Two new bodies registered in `_JOB_BODIES`, each constructing its own git
    client (the registry signature is `body(ctx, docker)`, matching Mod 148's
    `_run_test_body`):
    ```python
    def _run_check_body(ctx, docker):
        from docex.pipeline.check import run_check
        from docex.git import SubprocessGitClient
        return run_check(ctx, docker, SubprocessGitClient())

    def _run_merge_body(ctx, docker):
        from docex.pipeline.merge import run_merge
        from docex.git import SubprocessGitClient
        return run_merge(ctx, docker, SubprocessGitClient())

    _JOB_BODIES = {"test": _run_test_body,
                   "check": _run_check_body,
                   "merge": _run_merge_body}
    ```
  - Two new wrappers `run_check_job(ctx, docker, *, detach)` /
    `run_merge_job(ctx, docker, *, detach)` — near-verbatim clones of
    `run_test_job`, differing only in `kind`, `scope`, `vessel_name`, and the
    `meta.params` teardown identities (§ 5). The preflight → create record →
    `ContainerVessel(...).launch()` → attach/detach flow is identical.
- **`jobs/vessel.py`:** **no change.** `ContainerVessel` already runs `docex
  __run-job <id>` in a detached sibling container; `run_in_vessel` dispatches on
  `meta.kind`. A check/merge vessel is the same container running a different
  body.
- **`jobs/record.py`:** **no change** (kind is already a free-form string on
  `RunMeta`; `classify`, `job ls/status/wait/logs/result` are all kind-agnostic).
- **`jobs/reaper.py`:** generalized — § 5.

**Lock scopes / vessel names** (net-new, no collision with compose service
containers or the `test` runner):

| Command | scope | vessel name (the lock) |
| ------- | ----- | ---------------------- |
| `test`  | `<label>/test`  | `<label>-test-runner`  |
| `check` | `<label>/check` | `<label>-check-runner` |
| `merge` | `<label>/merge` | `<label>-merge-runner` |

Per-command scopes: two `check`s can't run at once, two `merge`s can't; a `check`
and a `merge` can. (A concurrent standalone `check` + `merge` on the same feature
HEAD would still collide on the `check-<short_sha>` worktree path — one loses at
`git worktree add`. That is **pre-existing** behavior, not introduced here, and
self-limiting; noted, not fixed, per "don't change what they do." A shared
check∨merge lock would eliminate it — flagged as Q2.)

---

## 3. Why check/merge genuinely need the substrate

Both are long-running: `check` builds and runs the full suite (minutes to tens of
minutes); `merge` runs `check` defensively first, so it is at least as long. The
observed pain (killed-and-relaunched runs) applies to them exactly as to `test`.
The re-attach property — a killed monitor leaves the run alive — is the payoff,
and it is only reachable if the run survives the foreground call's death. That
requirement is the crux of § 4.

---

## 4. ⚠ ESCALATION — the "host-process vessel" (D2) is incoherent under DooD

**Pre-plan D2 says:** the `check`/`merge` vessel is "a detached **host process**
owned by docex." **I recommend amending this**, and per the kickoff this is
`sarge`'s call, not mine to make silently.

**The analysis.** Mod 148 established a hard DooD reality: the foreground `docex`
runs *inside* the `--rm` container the `bin/docex` shim launched, and **that
container dies the moment the operator's shim call is killed**. That is precisely
why Mod 148's durable `test` work runs in a **detached sibling container**, not an
in-container child process.

Apply that to a "host process owned by docex":

- **Literal reading — a child process spawned inside the foreground container.**
  It dies with the foreground container when the shim call is killed. It is
  therefore **not durable** and cannot satisfy SC3's re-attach criterion. Fails.
- **Generous reading — a process on the operator's actual host machine.** Under
  DooD, an in-container docex has *only the docker socket*; it has no mechanism to
  fork a bare process on the host. The only thing it can spawn on the host is a
  **container**. So a true host process is **not even constructible** here. Fails.

Either way, "host-process vessel" cannot deliver durability under the DooD model
Mod 148 committed to. The honest conclusion: **`check`/`merge` must run in a
detached sibling container, the same vessel kind `test` uses.**

**And that vessel is `ContainerVessel`, unchanged — no second vessel class.** The
kickoff frames the alternative as "a vessel kind that differs from
`ContainerVessel` only in the *body* it runs and the *resource it cleans up*." On
reading Mod 148's substrate, neither of those axes lives *in the vessel*:

- The **body** is not part of the vessel. `ContainerVessel.launch` always runs
  `docex __run-job <id>`; `run_in_vessel` dispatches on `meta.kind` →
  `_JOB_BODIES[kind]`. Adding check/merge is a **registry entry**, not a vessel.
- The **owned resource** is not part of the vessel either. It is torn down by the
  **reaper**, which this mod generalizes to key off `meta` (§ 5).

So D2's anticipated vessel polymorphism (`container for test, host process for
check/merge`) **collapses**: every durable job uses the container vessel; the axis
of real variation is the **job kind**, which selects (a) the body and (b) the
reaper's teardown. The `Vessel` protocol Mod 148 defined stays — it is still a
sound seam — but this mod adds no implementation of it, because check/merge need
none.

**Recommended D2 amendment (for `sarge`'s approval).** Replace "the vessel is
polymorphic — container for `test`, host process for `check`/`merge`" with: *"the
vessel is a detached sibling **container** for every durable job; what varies by
job kind is the **body** it runs (dispatched by `meta.kind`) and the **owned
resource** the reaper reclaims on orphan (a `test` compose stack; a `check`/`merge`
ephemeral worktree + throwaway build stack)."* This is a strict simplification of
the taxonomy and, unlike D2 as written, is actually durable.

**A real consequence worth landing in the doctrine as a known limitation.** The
shim's opt-in `DOCEX_GIT_CREDENTIAL_PASSTHROUGH` machinery (a host-side responder
+ socket, set up and torn down by the *shim* around the foreground call) is
**incompatible with a detached or monitor-killed `merge`**: the detached vessel
outlives the foreground shim call, whose cleanup trap kills the responder, so a
later in-vessel `git push` has no broker. It works fine in **blocking** mode
(the shim call stays alive tailing the log, so the responder stays up) and for
**static** SSH-key / token auth (those mounts are cloned into the vessel via
`inspect_self`). This is another face of the same DooD truth in § 4, and I
recommend one sentence documenting it under `merge` (see § 6): *brokered
git-credential passthrough requires blocking `merge`; `merge --detach` needs
static credentials.*

---

## 5. Generalizing the reaper teardown (forward note from Mod 148)

Mod 148 recorded that `reaper._teardown_leaked_stack` **hardcodes the `test`
compose stack** — correct while `test` was the only vessel kind. Now check/merge
arrive, so the reaper must reclaim **whatever the orphaned run owned**, keyed off
its `meta`.

**Mechanism (no edits to `run_check`/`run_merge` bodies).** The reaper already
locates the orphaned record via `_find_record_for_vessel`. It now reads that
record's `meta.kind` and dispatches:

```
_teardown_leaked_resources(ctx, docker, meta):
    kind = meta.kind
    if kind == "test":
        compose_down(-v) the test stack            # today's behavior, unchanged
    elif kind in ("check", "merge"):
        _teardown_worktree_job(ctx, docker, meta)   # new
```

**What a hard-killed `check`/`merge` vessel leaks, and how it is reclaimed.** A
`check` (and `merge`'s defensive `check`) creates an ephemeral worktree
`.docex/worktrees/check-<short_sha>` + a temp branch, and brings up a throwaway
build/test stack named `<label>-check-<short_sha>`. On SIGKILL the `finally`
cleanup never runs, leaking both. `_teardown_worktree_job`:

1. `compose_down(-v)` the throwaway stack by its recorded project name.
2. Remove the worktree dir + `git worktree prune`.
3. Best-effort sweep of `docex-check/*` / `docex-merge/*` temp branches.

**Where the identities come from.** The `run_check_job` / `run_merge_job`
foreground wrappers compute the two deterministic identities and record them in
`meta.params`:

```
params = {"worktree_slug":  f"check-{short_sha}",
          "compose_project": f"{label}-check-{short_sha}"}
```

`short_sha = git.head_sha(project_root, short=True)` is available in the
foreground; `run_check` inside the vessel independently recomputes the *identical*
values from the same inputs, so no plumbing threads through `run_check`'s
signature and its existing tests stay green. If `meta.params` is absent/unreadable
the reaper falls back to a namespace sweep (remove every `.docex/worktrees/*` +
prune), so teardown degrades safely.

**What the reaper deliberately does NOT do:** it never unwinds `merge`'s *real*
git mutations (an interrupted rebase, a partial ff/tag). `merge`'s own contract
already leaves the branch in its rebased state for the operator to inspect —
auto-unwinding is "more dangerous than instructive" (merge.py docstring). The
reaper reclaims only ephemeral docex-owned scratch, never the operator's tree.

The reaper needs a git client for step 2/3; it constructs `SubprocessGitClient()`
lazily on the check/merge branch (or reuses `pipeline._worktree.cleanup_worktree`).
`jobs → pipeline._worktree` is a clean dependency (no cycle: `pipeline.check`
imports the job wrapper only via `jobs.commands`, lazily).

---

## 6. Doctrine amendments proposed (SC3 remainder — need `sarge` sign-off)

All within the kickoff's named radius. Doctrine is the upstream spec, edited first.

1. **`docex.md § Command Lifecycle`** (line 47): the closing sentence "This
   lifecycle is `test`-only today; `check` and `merge` join it in a later
   increment." → updated to state check/merge are now durable jobs too. One added
   line noting each durable command has its **own per-command lock scope**
   (`test` / `check` / `merge` runners are independent), and that the reaper's
   teardown is **keyed to the job kind** (test stack vs. check/merge worktree).
2. **`docex.md § `test``-style subsections:** the **`### check`** and
   **`### merge`** entries (lines 196–202) each gain the durability/`--detach`/
   re-attach note (a `[durable job](#command-lifecycle)` link + "a killed monitor
   leaves the run re-attachable via `docex job wait`"). The `test` help-table row
   already has this shape; mirror it. **`### merge`** additionally gains the
   one-sentence **brokered-credential limitation** from § 4.
3. **`docex.md` Provided Tools table** (lines 67–68): `check`/`merge` rows gain
   "(durable job; `--detach` returns a handle)", matching the `test` row.
4. **`cicd.md`**: at **§ Check Step** (after line 69) and **§ Merge** (after line
   90), a one-line note mirroring the `test` durable-job line already at cicd.md
   line 150 — check/merge now run as durable jobs; a killed monitor no longer
   orphans the run; `--detach` + `docex job wait` re-attach. **No change to the
   step *logic*** (the numbered Process lists are untouched).
5. **`./bin/docex` shim:** **unchanged** and additive — the check/merge vessels
   are launched by docex over the socket, not by the shim (stated in the lifecycle
   text, same as `test`).
6. **`testing` skill:** touch **only if** it references check/merge
   synchronicity. (I will grep it during implementation; expected: no change, or a
   one-clause note that check/merge are durable jobs. Flagged as Q3.)

**docex's own core-planning-doc diff** (Documentation step of this mod; for your
project map):
- **`masterplan.md`** — Subcommand Surface table: `check`/`merge` rows note
  `--detach` + durable-job behavior; the **§ Durable jobs** subsection's "`check`/
  `merge` join in a later increment" line (masterplan line ~177) updates to "now";
  the **§ Ephemeral Git Worktrees** section gains a note that a hard-killed
  check/merge vessel's worktree is reclaimed by the reaper.
- **`docex_process.md`** — no change expected.
- (Per the advance plan, `project-cohere` reconciles docex's own docs at
  close-out; these per-mod updates are the normal doc step, not a substitute.)

---

## 7. Testing plan (must be fully green; no real 30-min check suite)

Unit-testable with the existing `FakeDockerClient` / `FakeGitClient` fixtures + a
tmp `.docex/`, mirroring `test_jobs_commands.py`:

- **`--detach` returns fast + a handle** for both `check` and `merge`: the wrapper
  creates the record and issues exactly one `run_detached`, then returns without
  polling; the handle prints.
- **Lock refusal**: a *running* `<label>-check-runner` (or a `name_conflict=True`
  from `run_detached`) → the second `check` refuses non-zero, scope-named, and
  launches nothing. Same for `merge`.
- **Killed-monitor re-attach** (headline criterion, *no real suite*): create a
  check record with a "running" fake vessel and no `exit` → `job ls` classifies it
  LIVE; then write an `exit` file (vessel finished after the monitor died) → `job
  wait`/`job result` read the authoritative code. Proves re-attachability for
  kind=check without a real process.
- **Generalized reaper**:
  - a `kind=test` orphan → reaper does `compose down -v` the **test** stack (the
    existing assertion, unchanged).
  - a `kind=check` orphan (record with `meta.params`, no `exit`, vessel
    `container_running → False`) → reaper writes the synthetic `exit`, `compose
    down`s the **check** stack by the recorded project name, removes the worktree
    + prunes, then proceeds; `job result` reads the orphan code.
  - `meta.params` absent → the fallback namespace sweep runs (assert prune issued,
    no crash).
- **`__run-job` dispatches check/merge**: drive `run_in_vessel` with a fake body
  registered for `kind=check`/`merge` returning rc ∈ {0, k} → terminal `status` +
  atomic `exit` written; log populated. (The existing test-kind case stays.)
- **Bodies wired correctly**: `_run_check_body` / `_run_merge_body` call
  `run_check` / `run_merge` with a git client (monkeypatch `run_check`/`run_merge`
  to a recording stub; assert it received `(ctx, docker, <GitClient>)`).
- **check/merge logic unaffected**: `test_pipeline_check.py`,
  `test_pipeline_merge.py`, `test_orchestrate_test.py` stay green **unchanged**
  (they call `run_check`/`run_merge`/`run_test` directly — the bodies — which this
  mod does not touch). This is the verification gate: the gate/build/test logic
  stays green as jobs, *before* Mod 5's recheck-skip lands.

**One real-docker integration test** (`tests/integration/`, `-m integration`),
mirroring Mod 148's `test_job_vessel_real.py` **trivial-body** approach: register
a trivial short-lived body for a `check`-like kind (a ~1 s no-op) and prove the
real detached-container → `exit`-file → `job wait` path for a second kind across
the docker boundary. **Do NOT** run a real check suite. (A full real
`docex check` job is exercised by the close-out manual walk, advance plan step 13,
not here.)

Run with `python -m pytest tests` (canonical) — never bare `pytest`; `-m
integration` **alone** (per `docex_process.md § Running the automated tests`).

---

## 8. Design questions for `sarge` (please review before I write `implementation.md`)

- **Q1 — the D2 vessel-taxonomy amendment (§ 4).** This is the escalation the
  kickoff asked me to bring you: the "host-process vessel" is incoherent under
  DooD; I recommend amending D2 to "container vessel for every durable job; the
  *body* + the *reaper teardown* vary by kind — no second vessel class." **Approve
  the amendment?** (Everything downstream — package shape, the reaper generalization
  — follows from this answer.)
- **Q2 — lock granularity.** Recommend **per-command** scopes (`test`/`check`/
  `merge` independent), accepting the pre-existing, self-limiting concurrent
  check+merge worktree-path collision. Or would you prefer a **shared check∨merge
  lock** so those two are mutually exclusive (eliminates the collision, at the cost
  of serializing an otherwise-legal pair)?
- **Q3 — `merge` brokered-credential limitation (§ 4).** Approve documenting it as
  a one-sentence known limitation under `### merge` (blocking `merge` for
  passthrough; `--detach` needs static creds)? It is a true DooD consequence, not a
  bug I can design away in this mod.
- **Q4 — `testing` skill touch.** Expect **no change** (or a one-clause durable-job
  note). Confirm a light touch / no touch is acceptable, consistent with the
  kickoff's "touch only if it references check/merge synchronicity."
