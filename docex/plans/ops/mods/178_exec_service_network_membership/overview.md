# Mod 178 — Exec Service Network Membership

## Goal

Fix the network-orphan leak documented in
[`orphaned_network_problem.md`](../../adv/014_docs_report_and_skill_refactor/orphaned_network_problem.md),
as reprioritized by the advance plan's sharpened diagnosis
([`advance_plan.md § Mod 178`](../../adv/014_docs_report_and_skill_refactor/advance_plan.md)).
This is the last agent-owned mechanical mod of Phase A of advance 014.

## Root cause (confirmed against the code)

The exec service's networks are, by doctrine
([`exec_service.md § What the block carries`](../../../../../doctrine/infrastructure/specifics/exec_service.md)),
*"the union of the codebase's networks **less `web`**."* The compiler faithfully
implements this at `emit/compose.py:595-601`:

```py
exec_nets = sorted({n for p in svcs for n in p.networks if n != "web"})
if exec_nets:
    exec_block["networks"] = exec_nets
```

For a **web-only codebase** — a frontend whose only core service sits on `web`
and uses no backing service — that union is **empty**. The `if exec_nets:` guard
then writes no `networks:` key, and the exec block sets no `network_mode` either.
A Compose service with *neither* key attaches to Compose's implicit,
auto-created `<project>_default` bridge, which the top-level `networks:` block
never declares. Every `docker compose run --rm …-exec ./test.sh` mints an
unreaped `<project>_default`; `--slots N` multiplies it; the host address pool
exhausts.

**Reproduction (current code, verified this cycle):** a `sample_project` variant
with an added `frontend` codebase (one `web`-only core service, no `uses`)
compiles `sample-dev-frontend-exec` with keys
`[build, environment, image, labels, profiles, volumes]` — no `networks`, no
`network_mode` — while top-level `networks:` declares only `internal` and `web`.
The bug is an **unhandled empty-set case** in a doctrine rule the compiler obeys,
so the fix touches **both** the compiler and `exec_service.md`.

## The fix (report fix #1, corrected — the true fix)

When `exec_nets` is empty, still emit **explicit network intent** so Compose
never auto-creates `_default`. Default to **`network_mode: none`**: a one-off
build/test/ops shell for a web-only codebase needs no intra-stack network, and
`none` creates **zero** networks (the doctrinally honest answer). The non-empty
path stays **byte-identical** to today — the change is a pure `else` branch.

### `network_mode: none` egress prerequisite — VERIFIED

`none` is correct only if no doctrine-conformant `build.sh`/`test.sh` needs
network **egress at exec time**. Verified:

- Dependencies install at **image-build** time (the `build`/`test` Dockerfile
  stages), never at exec — [`cicd.md § Build Step`](../../../../../doctrine/infrastructure/cicd.md#build-step)
  and [`exec_service.md`](../../../../../doctrine/infrastructure/specifics/exec_service.md).
  `build.sh` compiles already-installed source into `dist/`; `test.sh` runs the
  suite against the baked image.
- The exec container needs a network only to reach **backing services** (a real
  test DB) — and those live on `internal`. A codebase that reaches a backing
  service is authored on `internal`, so its `exec_nets` is **non-empty** and
  takes the unchanged `if` branch. The empty-set case is *precisely* the codebase
  with nothing internal to reach.
- Module/codebase tests stub external gateways; a web-only frontend has no
  backing service and no internal peer.

So the empty-`exec_nets` codebase legitimately needs no exec-time network at all,
and `network_mode: none` is right. `internal` (the considered alternative) is
**not** chosen: there is no `internal` for a web-only codebase to attach to, and
inventing one would fabricate reachability the codebase does not have.

## Folded in (doctrine only) — the address-pool ceiling

Even leak-free, a max `--slots 8` run plus standing dev/stage/prod stacks plus a
check worktree approaches Docker's default ~31-network ceiling. This mod adds a
`default-address-pools` stanza to the **fixed development-side preinfra
doctrine**, sharing the same `/etc/docker/daemon.json` that
[`telemetry_preinfra.md § step 6`](../../../../../doctrine/infrastructure/preinfra/telemetry_preinfra.md#hyperdx-installation)
already uses for the log-cap, repeating those caveats (applies only to containers
created afterward; a daemon restart bounces every container on a shared host)
plus the **subnet-collision** caveat (the pool must not overlap the master
network / existing subnets).

**Placement decision — `fixed_master_network.md`, not `telemetry_preinfra.md`.**
The address-pool concern is a property of the **fixed dev host that runs project
stacks and `--slots` test shards** — it has nothing to do with HyperDX, which an
operator may never self-host (they can use a cloud backend). The one file every
fixed dev-host operator reads is
[`fixed_master_network.md`](../../../../../doctrine/infrastructure/preinfra/fixed_master_network.md)
(*"applies to every machine that hosts at least one doctrine project's env
stack"*), and its subject **is** the master network and its subnets — exactly
what the subnet-collision caveat is about. Grafting a docex-slot address-pool
subsection into HyperDX's numbered install list would hide it from any operator
not setting up HyperDX. So the primary doctrine lands in `fixed_master_network.md`
as a new section, cross-referencing the telemetry log-cap stanza as sharing the
same `daemon.json` (no edit to `telemetry_preinfra.md`). This keeps the change to
exactly the two pre-authorized doctrine edits.

It is **operator host config, not compiler code** — the mod ships only the
doctrine text; the operator applies it on the dev host (a Phase D pre-req).

## Explicitly NOT done — report fix #2

No `--remove-orphans` on teardown, no reaper-side network prune. Fix #1 removes
`_default` at its source; the advance plan drops #2 by decision.

## Aligned-artifact plan (six artifacts)

| Artifact | Touched? | What |
| --- | --- | --- |
| `doctrine/**` | **Yes** | `exec_service.md` Networks rule (empty-set fallback); `fixed_master_network.md` (`default-address-pools` stanza) |
| `docex/plans/design/**` | **Yes** | `specifics/compiler.md` exec-service section notes the empty-set → `network_mode: none` fallback |
| `tables/roles/*.yml` | No | The exec service is a compiler-owned derivative, not a role; no role table describes it |
| `src/docex/**` | **Yes** | `emit/compose.py` — the `else` branch |
| `tests/**` | **Yes** | `test_exec_service.py` — web-only fixture + compiled-output assertions |
| `doctrine_excerpts/*.md` + `index.yml` | No | `network_mode: none` introduces **no** new infrastructural resource (it creates zero networks — the *absence* of one), so no `index.yml` key. No existing excerpt describes exec-service network membership (`codebase.md`/`core_service.md`/`network*.md` all checked), so nothing to reconcile |

## Success Criteria mapping

1. Web-only exec never network-less → `network_mode: none`, no `networks:`, no
   `_default` — proven by the new web-only fixture unit test.
2. Non-empty `exec_nets` byte-identical → `else`-only change; existing exec tests
   (`test_6`, `test_7c`) unchanged and green; explicit assertion `network_mode`
   absent on the `internal`-bearing block.
3. `exec_service.md` Networks rule amended.
4. `fixed_master_network.md` documents the `default-address-pools` daemon.json
   stanza with caveats.
5. Live `--slots 4` check is **Phase D step 0**, not run here.
6. docex unit tests over compiled output; aligned artifacts reconciled.

## Design questions

None. The spec is fully specified and the one prerequisite (`network_mode: none`
egress) is verified above.
