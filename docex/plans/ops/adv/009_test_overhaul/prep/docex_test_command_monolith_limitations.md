# `docex test` / suite-runner monolith — boundary conditions

**Purpose.** A portable summary of research done against the `nasmyth` project's agent
transcripts, to serve as a fixed "boundary condition" input to a doctrine / `docex` test-infra
refactor. It captures *what any solution must satisfy*, grounded in observed agent behavior.

**Research basis.** ~485 session transcripts (~640 MB) for the `nasmyth` project, plus a focused
look at the pipeline session run on 2026-08-21.

**Note.** The `nasmyth` project is one of the first very large projects built with the doctrine, resulting in full-suite test times of up to 30 minutes.

---

## Problem, in one line

The doctrine's suite-running commands — `docex test`, and `docex check` / `docex merge` which
embed the full suite — execute **synchronously in the foreground and block for 6–26 minutes**.
That structurally collides with an interactive agent's per-call wall-clock limit, so agents route
around the blessed path with ad-hoc, inconsistent, and sometimes racy backgrounding.

---

## Observed facts (evidence base)

- **Suite wall-times, from completed runs:** ~380 s to ~1550 s (≈6–26 min). Measured from real
  completions (e.g. `4909 passed … in 381.08s`, `6071 passed … in 1549.34s`). The default
  foreground Bash cap is 2 min; even the 10-min maximum is not enough for the large gate runs.
- **Timeout-driven rework across the corpus:**
  - **25** test-run attempts were killed mid-run by a machinery timeout and had to be re-launched.
  - **11** monitor / poll loops (watching a still-running suite) were killed and had to be re-issued.
  - **108** further commands were auto-backgrounded by the harness's own 600 s "moved to the
    background" rescue (not killed — process survived; a different, benign mechanism).
- **Orphaning:** killed foreground `docker run` clients frequently left the test container alive,
  costing extra turns to detect and reap orphans before re-launching.
- **Concurrency hazard (observed):** two `docex test` runs launched ~2 min apart raced against one
  shared `test` stack, producing a green run that nobody had reason to distrust.
- **Today's pipeline run (2026-08-21, session `ec23d9c1`):** *every* real invocation of
  `docex check` and `docex merge` was **pre-emptively** wrapped in the workaround —
  `run_in_background: true` (or `& > log`), writing a log + a `.done` sentinel, then watched with
  `for i in $(seq …); do pgrep -f "docex check"; sleep …` poll loops carrying hand-tuned 320–380 s
  timeouts, re-issued ~6 times as the run ground through image build → test-stack up → `[31%]…` →
  teardown. **Zero** naive blocking foreground calls; **zero** kills — because the agent paid the
  workaround tax up front.

### What this means
- The problem is **not `docex test`-specific**. It is structural to *anything that runs the full
  suite and blocks*: `test`, `check`, and `merge`. `check`/`merge` are worse — they also build
  images and bring the throwaway `test` stack up/down inside the same blocking call.
- The workaround is now the agent's **default reflex**, applied pre-emptively. The wasted
  time/usage did not disappear; it moved from "re-run after a kill" to "hand-roll durable launch +
  polling every single time."
- **The winning method does not use the blessed command at all.** For iteration, agents dropped to
  raw `docker run --rm --name <run> --network nasmyth-dev-internal -v nasmyth-dev-market:/data/market:ro
  … nasmyth/engine:lint python -m pytest <subset>` — a **named, durable** container, against the
  **warm `dev` stack**, running a **subset**. That is precisely what `docex test` does not offer.
- **Drift.** One deterministic task ("run the suite and know when it finished") has accreted **≥5
  improvised idioms**: `run_in_background:true`, `nohup … &`, `docker run -d`, `--name` +
  `docker wait`, and `& > log` + `.done` sentinel + `pgrep`. `pgrep -f "docex check"` as a liveness
  proxy is fragile — it breaks under exactly the concurrent-run race observed above.

---

## Boundary conditions (invariants any solution must satisfy)

1. **Decouple run lifetime from call lifetime.** A single blocking invocation can never hold the
   suite. Launch must return a durable handle immediately; completion is polled/waited separately.
   *(Non-negotiable — everything else follows from this.)*
2. **A killed monitor must never kill the run.** The run survives in a named/durable form and is
   re-attachable (`status` / `wait` / `result` against the handle), so a timed-out poll costs one
   cheap re-poll — not a whole re-run.
3. **Liveness / progress observable from outside the process.** A real signal (exit-file,
   structured status, % progress), not a fragile `pgrep` / `docker ps --filter` proxy. This mirrors
   the existing doctrine principle for long-running loops (`internal_dependency_rules.md`
   §Entrypoints rule 6, `healthchecks.md`) — reuse it rather than invent a parallel notion.
4. **Scoping is required, or the blessed path gets bypassed.** Agents need to run a subset
   (`tests/hex/broker`, `tests/flows`, a marker) for iteration. Forcing the whole multi-day-gate
   suite on every run is *the* reason they drop to raw `docker run`.
5. **Two honest modes, both first-class:** fast iteration against a warm stack (what agents
   hand-roll against the `dev` DB / market volume) **vs.** the formal fresh-throwaway-`test`-env
   isolation guarantee. If only the slow/pure mode exists, iteration leaves the path.
6. **Cover every suite-runner, not just `test`.** `check` and `merge` embed the same blocking suite
   (plus build + stack up/down). The async/handle model must be the substrate they call, not a
   `test`-only bolt-on.
7. **Concurrency safety.** Two suite runs against one shared `test` stack race and can yield a
   false-trusted green run. The runner must refuse or isolate a second concurrent run.
8. **Canonical-way is the doctrinal stake.** Success is measured by agents *ceasing to hand-roll*.
   One deterministic task currently has ≥5 execution idioms — the exact drift the doctrine exists
   to eliminate. If the new command is right, the improvisation stops.

---

## Design directions implied (not prescriptive — the final design is a composite of all needs)

- A **launch / poll / wait** split, e.g. `docex test start [scope]` → handle; `docex test status`
  (running / passed / failed + progress); `docex test wait [--timeout]`; `docex test logs` /
  `result`. The tool *owns* the durability (fixed container name, log path, exit-file) that agents
  currently hand-roll.
- `check` and `merge` **call that runner** rather than re-embedding a blocking suite.
- Keep the exit-code `test.sh` contract for CI, but make blocking-until-done a *caller* choice
  (`wait`), not the only shape on offer.
- Doctrine prose (`tests.md`, the testing skill, `infrastructure.md`) should state the async /
  observable / re-attachable contract explicitly and forbid blocking on the suite in a single
  foreground call.
