# Mod 034 — Command Surface Refresh

Fifth mod of the [doctrine-shape-and-tier campaign](../../campaigns/shape_overhaul_mod_list.md). Drops `bootstrap`; collapses `up`/`down` into `envinfra <direction> <env>`; wires stubs for `preinfra <side>` and `projinfra <direction> <side>`. Pure dispatcher / CLI-surface change — internal behavior is preserved.

## The Doctrine Change

From [`docex.md § Provided Tools`](../../../../doctrine/infrastructure/docex.md#provided-tools), the new command surface:

| Old | New | Notes |
| --- | --- | ----- |
| `bootstrap` | **removed** | Elastic-only one-shot, replaced by `projinfra up production` |
| `up <env>` | `envinfra up <env>` | Same behavior, symmetric naming |
| `down <env>` | `envinfra down <env>` | Same behavior, symmetric naming |
| *(none)* | **`preinfra <side>`** | Read-only check of prereq infra existence for development/production side. Does not create. Required to pass before `projinfra up <side>` or `envinfra up`. |
| *(none)* | **`projinfra <direction> <side>`** | Idempotent up/down of project-tier infra for a given side. Replaces `bootstrap` and adds teardown. |
| *(implicit only)* | **`migrate <env>`** | Was always implicit-inside-other-commands. Already explicit in docex; no change needed. |

Per [`docex.md § preinfra`](../../../../doctrine/infrastructure/docex.md#preinfra) and [`docex.md § projinfra`](../../../../doctrine/infrastructure/docex.md#projinfra), the new commands take side arguments (`development` or `production`), not env arguments.

## Scope of mod 034 — stubs, not behavior

This is a **CLI-surface mod**. Real `preinfra` checks land in mod 042; real `projinfra` emission and apply land in mods 036 (fixed), 037–039 (elastic). For mod 034:

- `preinfra <side>` — accepts the side argument, prints a "preinfra check (stub)" notice, returns 0.
- `projinfra up production` on **elastic projects** — runs the existing bootstrap flow (`pipeline/bootstrap.py:run_bootstrap`) which creates the OpenTofu state backend. This preserves the only useful behavior the old `bootstrap` command had.
- `projinfra up <other-side>` and `projinfra down <side>` for any other case — prints a "projinfra stub" notice, returns 0.

This pattern matches the campaign brief's instruction: "For elastic, `projinfra up production` initially continues to do what `bootstrap` did (state backend only). `preinfra` is a no-op success. Pure dispatcher / naming change; real behavior arrives in 036/037/042."

## Concrete dispatcher surface

### Removed

- `bootstrap` removed entirely. The handler function `_cmd_bootstrap` in `src/docex/__main__.py:385` becomes the seed for `_cmd_projinfra`'s elastic branch but the standalone command exits.
- `up` and `down` removed as standalone commands. They were placeholders for `envinfra up/down`.

### Added

- `envinfra <direction> <env>` — `direction` is `up` or `down`; `env` is `dev` or `test` (refuses `stage`/`prod` per [`docex.md § envinfra`](../../../../doctrine/infrastructure/docex.md#envinfra)). Dispatches to existing `orchestrate.up.run_up` / `orchestrate.down.run_down`.
- `preinfra <side>` — `side` is `development` or `production`. Stub: print and return 0.
- `projinfra <direction> <side>` — `direction` is `up` or `down`; `side` is `development` or `production`. Wired for the one real case (elastic `up production` → `run_bootstrap`) plus stubs for the rest.

### Unchanged

- `compile`, `describe`, `why`, `build`, `test`, `migrate`, `check`, `merge`, `containerize`, `release`, `stagetest`, `rollback`, `roles`, `role`.

### Help text and grouping

The current dispatcher organizes commands by "phase" (`_PHASE1_COMMANDS` through `_PHASE5_COMMANDS`). That categorization is internal to docex's build history and never appeared in the doctrine. The doctrine's `docex.md` lists commands as one flat table. Time to drop the phase grouping in the help text and replace with grouping by purpose, matching the doctrine table's logical order:

- **Introspection**: `compile`, `describe`, `why`, `roles`, `role`
- **Infrastructure**: `preinfra`, `projinfra`, `envinfra`
- **Development**: `build`, `test`, `migrate`
- **Pipeline**: `check`, `merge`, `containerize`, `release`, `stagetest`, `rollback`

The internal `_PHASE*_COMMANDS` constants and `_phase_of` helper can be deleted or repurposed; they're only consumed by `_format_usage`.

### Internal orchestrate module names

`src/docex/orchestrate/up.py` and `down.py` keep their names. They describe operational behavior (compose up / compose down); the CLI-surface name `envinfra` describes the doctrine tier the operation acts on. Different concepts; internal naming doesn't need to follow the CLI rename.

Same for `src/docex/pipeline/bootstrap.py` — keep the file and its `run_bootstrap` function for this mod. The function gets invoked from the new `_cmd_projinfra` handler instead of `_cmd_bootstrap`. Later mods (037–039) build out the broader `projinfra` flow on top of (eventually replacing) `run_bootstrap`.

## Ramifications

- **Breaking change** for any caller of `docex up`, `docex down`, or `docex bootstrap`. The operator (per their decision) has no in-flight consumer projects; only the smoke projects might use the old commands. The smoke projects will get rebuilt at end of campaign.
- The campaign brief's reading-order suggestion lists `docex.md` as #6 — the operator should expect the new surface to appear in the manifest from this mod forward.
- `docex --help` output changes shape (phase grouping → purpose grouping). Tests asserting on help text need updates.

## Operator Decisions

1. **Phase categorization** — drop. Internal `_PHASE*_COMMANDS` and the `Phase N (implemented)` help groupings go away; replaced with purpose-based grouping matching the doctrine table.
2. **`envinfra` argument validation** — refuses `stage`/`prod`; accepts only `dev`/`test`.
3. **`preinfra` stub** — returns 0 with an explicit "stub" notice. Mod 042 swaps the body without changing the contract.
4. **`projinfra` stubs** — fixed projects get a 0-with-notice stub on every direction/side. Elastic `projinfra up production` runs the existing bootstrap state-backend setup; every other elastic projinfra invocation is also a 0-with-notice stub. Real behavior arrives in mods 036 (fixed) and 037–039 (broader elastic).
5. **`bin/docex` shim** — no changes. The shim is a thin docker-run wrapper; command-name changes are transparent.

## What This Mod Is NOT

- Not implementing real `preinfra` checks (mod 042).
- Not implementing real `projinfra` emission or behavior on fixed (mod 036) or expanded elastic (mods 037–039).
- Not renaming any internal modules — `orchestrate/{up,down}.py`, `pipeline/bootstrap.py` keep their names.
- Not implementing migration `from old-command to new-command` shim — operator decision: no backwards compat.
- Not changing `migrate` semantics — already first-class as the doctrine wants.
