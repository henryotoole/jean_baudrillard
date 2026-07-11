# Mod 093 — Guard the fixed release playbook's env-render tasks for dry-run

## Problem

`docex rollback <env> --dry-run` on the **fixed** foundation aborts with
`'tte_store_file' is undefined` (ansible exits 2, task "Render TTE store onto
host").

Root cause is an envmageddon (1.5.0) regression. `_release_fixed`
(`pipeline/release.py`) builds the aggregate only when **not** `dry_run` — dry-run
must be side-effect-free, so it deliberately skips aggregation (which would mint
TTE values). Consequently `extra_vars` is empty in dry-run, and the playbook is
invoked with `check_mode=True` but **without** `agg_env_file` / `tte_store_file`.
The two render tasks introduced by mods 081/082 —

- "Render TTE store onto host" → `src: "{{ tte_store_file }}"`
- "Render .env onto host" → `src: "{{ agg_env_file }}"`

— template those extra-vars unconditionally, so ansible fails resolving the
undefined variable even in `--check` mode (arg templating happens before the
copy is simulated).

Blast radius is narrow: only `rollback --dry-run` on fixed exposes it (`docex
release` has no dry-run; elastic dry-run runs `tofu plan`, no ansible). Real
releases and the real rollback pass the extra-vars normally and are unaffected.
Surfaced by the 1.5.0 pre-cut fixed smoke walk (C.10). Rolled into 1.5.0.

## Design

Gate the two extra-var-dependent render tasks on the presence of their variable:

- "Render TTE store onto host" → `when: tte_store_file is defined`
- "Render .env onto host" → `when: agg_env_file is defined`

A real release passes both extra-vars, so the tasks run exactly as before. A
dry-run passes neither, so both tasks skip — which is correct: dry-run is a
side-effect-free `--check` preview, and the meaningful diff (image pull, stack
bring-up) still previews against the host's existing `.env`/`tte.env` from the
prior release. This matches the doctrine's dry-run contract
(`release_flow.md § Dry-run`: "Reports would-change tasks without mutating the
env") — no doctrine-prose change is required.

`when` references the ansible **runtime** var, not a docex compile-time var, so
`emit/ansible.py` needs no new render context — the change is entirely in
`emit/templates/playbook.yml.j2`.

## Hard boundaries

- No change to the real-release path (extra-vars still passed, tasks still run).
- No change to elastic (no ansible in its dry-run).
- No change to `docex migrate --tags migrate` (render tasks are untagged and
  already skipped there).
