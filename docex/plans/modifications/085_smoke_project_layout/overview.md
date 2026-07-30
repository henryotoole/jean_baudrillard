# Mod 085 — Smoke-project migration to the new layout

Part of the [envmageddon advance](../../advances/003_envmageddon/implementation_plan.md)
(step 2, mod 10 of 11). Brings the two doctrine smoke-test projects
(`test_projects/{fixed,elastic}/`) onto the envmageddon layout so the operator's
cut-time walk runs on conformant projects.

## Ready-to-cut boundary (what this mod does / doesn't do)

The 1.5.0 `docex` image does not exist until the cut (`RELEASING.md`). So the
operations that require the new image — repin `docex_version` → `1.5.0`,
`docex secrets scaffold`, recompile `infra/output/` new-style, and the full
release walk — are the **operator's cut-time work** per
[`test_projects.md § Lifecycle`](../../core/test_projects.md) and
[`PRE_CUT_CHECKLIST.md`](../../../test_projects/PRE_CUT_CHECKLIST.md), **not**
this mod.

This mod does only the source-layout prep that needs no new-image recompile:

1. **Sync the shim.** `bin/docex` gained a conditional `-t -i` in Mod 083 (for
   interactive `docex secrets set`). The smoke copies are byte-stale; sync them
   from the canonical `docex/bin/docex`.
2. **Add the `tte/` + `config/` category dirs**, each with a `.gitignore`
   (value files ignored; dir kept) + `README.md`, mirroring the existing
   `secrets/` dir. TTE values are generated (fully gitignored); config values
   are per-env, non-secret, gitignored (declarations live in `infra.yml`).
3. **Root `.gitignore`** — add `infra/tte/*` and `infra/config/*` blocks
   mirroring the `infra/secrets/*` block.
4. **Refresh `secrets/README.md`** to describe the three-category split: the
   secrets file now holds only operator-supplied secrets + the doctrine-injected
   `TELEMETRY_API_KEY`; engine credentials (`POSTGRES_PASSWORD`) are minted into
   `infra/tte/`; non-secret per-env values live in `infra/config/`.

The `<env>.env` secret value files are gitignored (not tracked), so there is
nothing committed to rewrite — the operator regenerates them with
`docex secrets scaffold` at walk time.

## Git cadence (per `test_projects.md § Commit cadence`)

Each smoke project is its own nested git repo. For each:
1. Commit the layout changes in the **inner** repo (`main`).
2. **Force-move `v0.0.11`** (the current `project.yml` version) to the new inner
   HEAD — the tag must point at the current-version commit for `docex
   containerize` to find it during the walk. (The project *app* version is
   unchanged; the `docex_version` repin to 1.5.0 is a separate walk-time commit.)
3. Commit the same files in the **outer** `jean_baudrillard` repo as a catchup.

## Scope

**In:** shim sync, `tte/`+`config/` dir scaffolding, root `.gitignore`, README
refresh, in both projects; inner commits + `v0.0.11` retag + outer catchup.

**Out:** repin to 1.5.0, `secrets scaffold`, recompile, the release walk — all
operator cut-time work. A `config:` demonstration in `infra.yml` is left for the
operator to add during the walk if config end-to-end coverage is wanted (adding
it here would require a new-image recompile to keep `infra/output/` coherent).

## Doctrine anchors
- `config_and_secrets.md § Layout` (subdir-per-category).
- `test_projects.md § Git structure` / `§ Commit cadence` (nested repos, inner-first, tag-at-HEAD).
