# Mod 080 — `aggregate()` + `ensure_tte()` (dev/test path)

Part of the [envmageddon advance](../../advances/003_envmageddon/implementation_plan.md)
(step 2, mod 5 of 11). Introduces the aggregation machinery and wires it into
the dev/test bring-up paths. Stage/prod aggregation is Mods 081 (fixed) / 082
(elastic).

## Why

`config_and_secrets.md § Aggregation`: the three source categories are re-merged
into the container-facing env **just before containers first read it**. For
dev/test that moment is `docker compose up`. The merge is a plain **disjoint
union** (`TTE ∪ secrets ∪ config`) — disjointness is compile-guaranteed (Mod
079), so there is no precedence.

TTE generation is impure/stateful, so it never runs at `compile` (which is
offline-pure). It is the **first sub-step of aggregation** (`ensure_tte`), with
the **authoritative store = the store the target env's containers actually
read** (`config_and_secrets.md § authoritative-store rule`). For dev/test that
is the local `infra/tte/<env>.env` (compose reads it directly). `ensure_tte`
**generates only if absent** — a re-run reuses existing values, never re-mints.

## The two objects (do not conflate)

| Object | Path (dev/test) | Lifecycle |
| ------ | --------------- | --------- |
| **Persistent TTE store** (authority) | `infra/tte/<env>.env` | persists; `ensure_tte` mints-if-absent, never clobbers |
| **Aggregate** (derived) | `.docex/agg/<env>.env` | regenerated every bring-up = `TTE ∪ secrets ∪ config` |

`.docex/` is already gitignored (worktrees live there), so the aggregate is
covered. `infra/tte/` and `infra/config/` value files need new gitignore
entries — added to the smoke projects in Mod 085 and documented for inception in
Mod 086; if docex owns a `.gitignore` scaffold, add them there too (the
implementer checks).

## Design: explicit `aggregate()`, pure `env_file_for`

Every fixed-env **bring-up** must feed compose the aggregate (not the raw
secrets file, which no longer holds TTE/config). But **teardown must not mint**.
So:

- `aggregate(ctx, *, env) -> Path` — **side-effectful**: `ensure_tte` →
  merge → write `.docex/agg/<env>.env`, return it. Called by every bring-up site.
- `env_file_for(ctx, env)` — stays **pure** (no side effects); repurposed to
  return the aggregate path if it exists, else `None`. Used by `down` (reuses
  the last aggregate; never mints) and any read-only path.

Naming a helper `env_file_for` side-effectfully mint credentials would violate
least-astonishment; keeping generation in the explicitly-named `aggregate()` is
the point.

## Bring-up sites to wire (all must aggregate)

`up` (dev/test), `test` (test env), `build` (dev), `migrate` (dev/test branch),
and `check`'s in-worktree `test` run. Each: call `aggregate(ctx, env=…)` and
pass its returned path to compose. `down` keeps `env_file_for` (pure). The
`check ↔ test` `env_file_override` path must carry the aggregate coherently —
this is the one delicate site; preserve its existing secret-sourcing and test it.

## Scope

**In:** `docex/envfile.py` (standard-form read/write); `orchestrate/aggregate.py`
(`aggregate`, `ensure_tte`); `categories.minted_policies` (minted key → resolved
`GenerationPolicy`); `env_file_for` → aggregate path; wire the 5 bring-up sites;
tests.

**Out:** stage/prod aggregation (Mods 081/082 — `aggregate`'s stage/prod branch
raises a clear NotImplementedError until then); the `secrets`/`config` tooling
(Mods 083/084); smoke-project gitignore/layout (Mod 085).

## Doctrine anchors
- `config_and_secrets.md § Aggregation`, `§ TTE Vars` (generate-if-absent, authoritative store, dev/test = local file), `§ Standard Form` (the flat `KEY=value` parse rules).
- `plan.md §4.2` (aggregate location `.docex/agg/<env>.env`, store-vs-aggregate distinction, `--env-file` consumption).

## Artifact alignment
doctrine (committed) ⇄ `src/docex/**` (this mod) ⇄ `tests/**` (this mod). Core-doc
narrative (compiler.md/release_flow.md) batched to Mod 086.
