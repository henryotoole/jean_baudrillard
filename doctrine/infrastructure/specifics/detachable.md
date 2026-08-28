---
stratum: conditional
---

# Detachable Jobs

This file describes the deep mechanics behind `docex`'s asynchronous command surface — the "vessel" containers, the on-disk run records under `.docex/runs/`, the deterministic-name lock, and the preflight reaper. The user-facing surface (the `--detach` flag, `docex job <verb> <handle>`, and how to wait on a run) lives in [`docex.md § Asynchronous Usage`](../docex.md#asynchronous-usage); this file is the "how it works" for a reader who needs it.

Most `docex` commands are **synchronous**: they run, block, and exit with a status code. A few long-running commands are instead **durable jobs** — the work outlives the invoking call.

`docex test` is the first. It still **blocks and exits with the run's code by default** (the exit-code contract CI relies on is preserved), but the suite runs in a **detached, deterministically-named "vessel" container** that docex launches over the docker socket. Because the work lives in the vessel and not in the foreground call, a foreground monitor that is **killed does not kill the run** — the run stays alive and re-attachable.

Every durable job writes an **on-disk run record** under `.docex/runs/<id>/` (`meta.json`, `status.json`, an atomically-written `exit` file, and a `log`). The `exit` file is the **authoritative terminal signal**: it survives vessel teardown and a killed monitor, and is what `docex job result` and `docex job wait` read.

Two additions make the durability usable:

- **`--detach`** on a durable command launches the vessel and returns the run **handle** immediately instead of blocking.
- **`docex job <verb> <handle>`** operates on a handle after the fact — `ls` / `status` / `wait` / `logs` / `result`. `job ls` is the durable, non-fragile way to **rediscover** an in-flight run: a killed or freshly-spawned agent recovers the handle here rather than via a `docker ps` / `pgrep` proxy.

Concurrency is bounded by the vessel's **deterministic name, which is the lock**: a second run against the same scope loses the `docker run --name` create race and **refuses** rather than contending over the shared stack. Each durable command has its **own per-command lock scope** — `test`, `check`, and `merge` runners are independent, so two `test`s (or two `check`s, or two `merge`s) refuse each other while a `check` alongside a `merge` is allowed. `docex test --slots N` does **not** change this: the `N` slot stacks are internal parallelism inside one `test` vessel, not `N` lock scopes, so a slots-`N` run and a plain `docex test` still refuse each other. The three commands that *can* co-occur (distinct locks) are kept name-disjoint by a **reserved slot band**: `test` uses slots `1..MAX_TEST_SLOTS`, while `check` and `merge` each run their defensive `test` stack at a reserved slot just above the band (`CHECK_SLOT` / `MERGE_SLOT`) — so a `check`, a `merge`, and a `docex test` all running at once never collide on an explicit `container_name:` or the DB volume `name:` (the closure of the `--project-name` collision; see [§ `check`](#check) below). A vessel that was hard-killed leaves an orphaned record and a leaked resource; the next run's **preflight reaper** clears both (writing an authoritative `exit`, then reclaiming what that run owned) and proceeds. The `./bin/docex` shim is **unchanged** — the vessel is launched by docex itself over the socket, so no shim update is required.

`test`, `check`, and `merge` are all durable jobs. **One vessel kind serves every durable job — a detached sibling container.** There is no second vessel kind (a "host process" cannot be durable under docex's Docker-outside-of-Docker model: the foreground `docex` runs inside the `--rm` container the shim launched, so a child process spawned there dies with it when the call is killed, and an in-container docex can spawn only a *container* over the socket, never a bare host process). What varies by job **kind** is instead two things: the **body** the vessel runs (the suite for `test`; the gate/build/test sequence for `check`; the rebase/tag/push for `merge`), and the **resource the reaper reclaims** on orphan — a `test` run's throwaway compose stack (under `--slots N`, the **fleet** teardown: all `N` deterministic slot stacks the run leaked, `N` read from the run record), or a `check`/`merge` run's ephemeral [worktree](../docex.md#check) and the throwaway build/test stack its defensive run brought up. The reaper never unwinds `merge`'s real git mutations (an interrupted rebase, a partial fast-forward/tag); those are left for the operator, as `merge` already specifies. One `test`-specific property follows from sharding: a slot whose shard **fails** is deliberately **left up** for debugging (the passing slots are torn down), and is reclaimed by the next run that touches that slot number — either its per-slot pre-up teardown or the fleet reaper — so a failed **higher-numbered** slot can persist across a subsequent **smaller-`N`** run until an `N ≥ k` run touches slot `k`, or the operator tears it down by hand.

## Per-command specifics

The behavior above holds for every durable job. `check` and `merge` add detachment specifics of their own; the functional descriptions of both commands live in [`docex.md`](../docex.md#check).

### `check`

`check`'s defensive build + test compile and run the worktree's `test` env at a **reserved slot (`CHECK_SLOT`) above the `docex test --slots N` band**, so the throwaway stack's compiled physical names — especially the DB volume `name:` — are name-disjoint from any `docex test` run. **This closes the `--project-name` DB-volume collision:** Compose's `--project-name` does **not** namespace an explicit `container_name:` or a top-level volume `name:`, so two stacks compiling `test` at the same slot would collide on the DB volume; the slot segment (`_s{k}`) does namespace them, so a `check` running beside a `docex test` no longer shares a database volume. A hard-killed `check` vessel's ephemeral worktree and throwaway stack are reclaimed by the next run's preflight reaper.

### `merge`

`merge`'s defensive recheck is an **in-process** call — it does **not** take the `check`-runner lock — so it can co-occur with a standalone `docex check`; it therefore runs at a **reserved `MERGE_SLOT`, distinct from `check`'s `CHECK_SLOT`**, keeping the two defensive stacks name-disjoint too.

**One caveat is specific to `merge`:** brokered git-credential passthrough (`DOCEX_GIT_CREDENTIAL_PASSTHROUGH`, see [credentials.md § Git Host Credentials](../credentials.md#git-host-credentials)) does **not** survive `--detach` or a killed monitor — the shim's host-side credential responder is scoped to the foreground call, so a detached vessel's later `push` cannot re-broker. `merge --detach` therefore **refuses up front** when passthrough is active; run `merge` attached (blocking), or use a static credential (SSH key / `gitconfig` / file-based token), which is cloned into the vessel and does survive.
