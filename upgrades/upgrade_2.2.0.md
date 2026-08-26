---
version: "2.2.0"
severity: minor
kind: incremental
scope: [machine, project]
---

# Upgrading to doctrine 2.2.0

## Summary

Advance 009 ("Test Overhaul") is **entirely additive**. It ships durable,
re-attachable pipeline jobs (`test` / `check` / `merge`), scoped test runs
(`docex test [subset]`), whole-suite slot sharding (`docex test --slots N`), a
faster `merge`, and a `test` env that no longer needs `projinfra up`. The single
per-codebase `test.sh` shim is **unchanged**, and `infra.yml` is untouched — so a
downstream project needs **no per-codebase migration**: repin, recompile, re-run
the suite. See the [changelog](../CHANGELOG.md) 2.2.0 entry (mods 146–158) for the
full narrative.

This is a plain `incremental` upgrade: **no teardown, no data migration, no state
surgery.** The recompile assumes the project is already on `cicl_version "3"` (from
2.0.0); a project further back reaches this guide through the earlier ones on the
tape, which carry the CICL v2→v3 migration.

## Machine sync

`git pull` + `setup.sh` handle it: the plugin-cache bump reinstalls the skill set
(the **`testing`** skill changed this advance — durable jobs, the subset/slot
contract), `RESIDENT.md` regenerates, and `doctrine-update` builds the new
`docex:2.2.0` image. No manual machine-side step.

## Project upgrade

### 1. Repin

Bump `docex_version` to `2.2.0` and re-run the installer:

```sh
bash ~/.claude/jean_baudrillard/docex_install.sh <project>   # moves docex_version → 2.2.0
```

The shim itself never changes between versions; the pin selects the image.

### 2. Add `.docex/` to `.gitignore` (pre-056 installs only)

`docex` now writes machine-local run state — durable-job records, ephemeral
worktrees, slot output — under a `.docex/` directory in the project root. New
projects already ignore it (inception's default gitignore, mod 056) and both
smoke seeds carry it. A **pre-056 existing project must add it by hand**:

```sh
grep -qxF '.docex/' .gitignore || printf '\n# docex machine-local run state\n.docex/\n' >> .gitignore
```

### 3. Recompile

```sh
cd <project> && ./bin/docex compile
```

Expect a **green compile**. This release changes no `infra.yml` surface, so
`infra/output/` is unchanged **except** the mod-153 `test`-web-network reshape:
the `test` env's `web` network is re-tiered out of projinfra into an env-tier,
per-slot bridge, so projinfra now emits **three** `-web` networks (dev/stage/prod)
instead of four. A routine dev-side projinfra redeploy reconciles the topology
whenever you next bring it up; nothing to author.

### 4. Re-run a full test

```sh
./bin/docex check        # unchanged codebase_scripts gate: build.sh/test.sh/health.sh
./bin/docex test         # fresh test stack; runs each codebase's test.sh
```

No redeploy of running services is required by this upgrade beyond what your
normal release does. There is nothing to tear down and no data to migrate.

### 5. (Optional) Adopt the subset / shard shim contract

Only if you want `docex test [subset]` scoping or `docex test --slots N` sharding.
Both reach the codebase's `test.sh` as **one-way, stable, injected env vars**
(unset ⇒ whole suite, so ignoring them is byte-identical to today):

- **`DOCEX_TEST_SELECTOR`** — a pytest-args fragment; when set, the shim runs that
  instead of the whole suite. Powers `docex test [subset]`.
- **`DOCEX_TEST_SLOT` / `DOCEX_TEST_SLOTS`** — this shard's 1-based index and the
  count N; when N>1, `test.sh` runs only its deterministic 1/N share of the whole
  suite. Powers `docex test --slots N`. A **recommend-not-mandate** pattern — shard
  however is idiomatic to your runner.

The seeds' `test.sh` carries a copy-pasteable reference implementation of both
(`--collect-only` + a modulo shard split): `../docex/test_projects/{fixed,elastic}/core/api/test.sh`.
See [`tests.md § Injected environment`](../doctrine/infrastructure/tests.md#injected-environment).

## Doctrine / behavior notes

None of the below requires action; they are what the advance *gives* you.

- **`docex test` is now a durable, re-attachable job.** It runs in a detached,
  deterministically-named vessel container but **still blocks and exits with the
  run's code by default** (the CI exit-code contract is intact). A killed
  foreground monitor no longer orphans the run. New surface: `docex test --detach`
  (returns a handle in ~seconds) and `docex job <ls|status|wait|logs|result>` over
  handles — `job ls` is the durable rediscovery path. The vessel's deterministic
  name **is** a per-`(project, test)` lock: a second concurrent run refuses rather
  than contending, and a hard-killed run is reaped by the next invocation's
  preflight. (mods 148–149)
- **`docex check` and `docex merge` are durable jobs too**, on the same substrate,
  each with its own `--detach` and its own per-command lock scope (two `check`s
  refuse each other; a `check` and a `merge` may co-occur). What `check` and
  `merge` *do* is unchanged. One caveat: `merge --detach` **refuses up front** when
  brokered git-credential passthrough is active — run `merge` attached, or use a
  static credential. (mod 149)
- **A blessed subset.** `docex test [subset]` narrows the run to a subset of the
  suite; docex forwards the `[subset]` to the codebase's `test.sh` as
  `DOCEX_TEST_SELECTOR`. Omitting it runs the whole suite. (mod 151)
- **`docex test --slots N` shards the whole suite** across N fully-isolated `test`
  stacks on one host (each physical name carries an `_s{k}` slot segment). A shard
  that passes is torn down; a shard that fails is left up for debugging and reaped
  by the next run. `--slots 1` / omitted is byte- and behavior-identical to today.
  (mods 152–155)
- **`docex test` no longer needs `projinfra up`.** For the `test` env only, the
  `web` network is re-tiered out of projinfra into an env-tier, per-slot docker
  bridge the `test` stack itself creates and tears down. A recompile therefore
  emits **three** project-tier `-web` networks (dev/stage/prod) instead of four,
  and the per-project traefik joins three; `dev`/`stage`/`prod` output is otherwise
  byte-identical. Nothing to author — a routine dev-side projinfra redeploy
  reconciles the network topology whenever you next bring it up. (mod 153)
- **`docex merge` is faster and fails earlier.** It now runs a `git ls-remote`
  **auth/reachability preflight** at the very top — a broken or unauthenticated
  `origin` fails in seconds by name, instead of after a full build + suite. And a
  green `docex check` writes a provenance record (`.docex/checks/latest.json`) that
  `merge` trusts to **skip its defensive recheck** when trunk and the feature tip
  are unmoved, the tree is clean, and the docex version matches — eliminating the
  doubled ~30-min run. The record is a **performance cache, never a correctness
  gate**: any staleness forces the full recheck, and CI/CD stays always-full.
  (mods 146, 150) See [`cicd.md § Merge`](../doctrine/infrastructure/cicd.md#merge).
- **Test scope is now policy.** A **mod cycle** may iterate with scoped runs but
  **closes on a full run**; an **advance closes on a full run** across the project;
  **CI/CD (`check`/`merge`) always runs the full suite and never scopes.** Scope is
  agent judgment via the `[subset]` mechanism — no computed "affected" selector
  ships, by design. (mod 156)

## Verification

```sh
cd <project>
./bin/docex --version                       # prints 2.2.0
./bin/docex check                           # passes; `codebase_scripts` gate green
./bin/docex test                            # full run green
```

1. **`docex check` passes `codebase_scripts`**, naming
   `build.sh/test.sh/health.sh present` for every codebase (the shim gate is
   unchanged from before the advance).
2. **`.gitignore` ignores `.docex/`** — `git check-ignore .docex/` prints the path;
   `git status` shows no `.docex/` noise.
3. **`docex compile` touches `infra/output/` only in the mod-153 three-`-web`-network
   projinfra reshape** — any other diff is a defect (this release changes no
   `infra.yml` surface).
4. **A full `docex test` brings up a fresh `test` stack and runs each codebase's
   `test.sh`** to a green exit — and does so with **no `projinfra up`** required
   (mod 153).
