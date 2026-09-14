# docex: test/check network orphans → address-pool exhaustion

**Found:** 2026-09-11, during advance 012 close-out (`docex check --slots 4`).
**Symptom:** a `check`/`test` run dies mid-`compose up` with
`Error response from daemon: all predefined address pools have been fully subnetted`.

## What you see

`check --slots 4` (or `test --slots N`) brings up N test stacks at once. One or more slots fail to
come up:

```
failed to create network nasmyth-test-s10-internal: Error response from daemon:
  all predefined address pools have been fully subnetted
error: 'compose up' for test slot 10 exited 1.
...
error: ./test.sh for 'frontend' slot 12 exited 1.
error: sharded 'docex test' against worktree exited 1.
```

The tests that *do* run pass — this is not a test or code failure. It is Docker running out of
subnets to hand to new networks. At the time of the incident there were **31** docker networks
(`docker network ls | wc -l`), which is right at the default ceiling.

## Root cause (three layers)

### 1. The real bug — docex compiles an exec service with no network membership

The CICL compiler emits the per-codebase **exec** services inconsistently:

- `nasmyth-test-engine-exec` → **has** `networks: [internal]`
- `nasmyth-test-frontend-exec` → **has neither `networks:` nor `network_mode:`** (only
  build/env/image/labels/profiles)

Docker Compose's rule: a service that declares **neither** `networks:` nor `network_mode:` is
attached to the project's implicit `default` network — and because the compiled file defines
top-level `internal`/`web` but **not** `default`, Compose *creates* `<project>_default` to hold it.
So every stack that instantiates `frontend-exec` (which `docex test` does, via
`docker compose run … ./test.sh`) mints an **extra, unintended** `<project>_default` network.

Evidence:
- The failure log shows `./test.sh for 'frontend' slot 12` creating `nasmyth-test-s12_default`.
- The orphans pruned during the incident were dominated by `*_default` nets:
  `nasmyth-check-<hash>_default` (×5, from the ephemeral check worktree), `nasmyth-test-s{2,3,9,10..}_default`.
- The otelcol sidecars are **innocent** — they use `network_mode: service:<app>` (that's why the app
  reaches the collector on `localhost:4318`), so they create nothing.
- `frontend`'s `test.sh` creates no networks itself — it only runs svelte-check + vitest.

Likely because the `frontend` codebase declares no backing-service `uses`/network membership, the
compiler emits no `networks:` for its exec service, and Compose's implicit default fills the gap.

### 2. Teardown doesn't reap the `_default` (and fails to clean up on the up-failure path)

The `*_default` networks accumulate run over run — evidence they are not being torn down. And when a
slot's `compose up` fails **mid-way** (e.g. `s10-web` created before `s10-internal` fails on pool
exhaustion), the partial networks orphan because the aborted stack never reaches a clean
`compose down`. That is a **positive-feedback loop**: once you're near the ceiling, a failed run
leaves more orphans, making the next run more likely to fail.

### 3. The host ceiling is unconfigured (amplifier)

There is no `/etc/docker/daemon.json` on the dev machine, so Docker uses its built-in default address
pools, which exhaust at **~31** user networks — exactly where we hit the wall. Standing stacks
(dev + stage + prod + test named nets) plus `--slots 4` (each slot = `internal` + `web` + an unwanted
`_default` ≈ 3 nets) plus the check worktree's own `_default` plus accumulated orphans blow past it.

Sharding is **not** itself buggy — it multiplies and *exposes* the latent compiler leak (one unwanted
`_default` per project × N slots + the worktree) against a low, unconfigured ceiling.

## Immediate mitigation (what unblocked advance 012)

```sh
docker network prune -f          # safe: only removes networks with NO connected containers,
                                 # so running dev/stage/PROD stacks are untouched (verified)
./bin/docex envinfra down dev    # free the dev stack's nets if dev isn't needed for the run
```

Prune removed 15 orphaned networks (31 → 16, then 15 after dev down); the re-run of `check --slots 4`
went green.

## Permanent fixes (in priority order)

| # | Fix | Where |
| - | --- | --- |
| 1 | **Emit an explicit `networks:` on *every* exec service** (or explicitly pin the project `default` network) so Compose never auto-creates a `<project>_default`. This kills the leak at the source. | docex CICL compiler (`docex-edit`) |
| 2 | On slot/worktree teardown **and on the up-failure path**, run `docker compose -p <project> down --remove-orphans` so any stray `_default` is reaped even if #1 misses one. | docex sharding/check teardown (`docex-edit`) |
| 3 | Configure `default-address-pools` in `/etc/docker/daemon.json` (e.g. base `10.200.0.0/16`, size `24` → 256 subnets) to raise the ceiling so transient spikes don't wall out. | host config (operator) |

#1 is the true fix; #2 and #3 are defense-in-depth.

## One-line repro for the docex owner

> `frontend-exec` is compiled with no network membership, so Compose auto-creates a per-project
> `_default` network that teardown doesn't reap; sharding multiplies it and the host's unconfigured
> address pool (~31 nets) then exhausts.
