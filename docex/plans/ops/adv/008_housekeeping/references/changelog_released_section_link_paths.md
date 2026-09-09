# Bring the repo-root markdown files into linkcheck scope

The frozen-section exclusion (option 1 of the original brief) already shipped in
mod 132: `linkcheck.py` skips released `CHANGELOG.md` sections via
`CHANGELOG_RELEASED_RE`. That removed the acute risk (a checker exiting non-zero
forever). What remains is elective cleanup so `CHANGELOG.md`, `README.md`, and
`RELEASING.md` can join the default scan. None of it is urgent; none of it
produces a failure today (the root files are out of scope entirely).

## Changes to make

1. **Repair the dead relative links in released sections of the repo-root
   `CHANGELOG.md`.** They are historical residue: paths written as if the file
   still sat at `docex/` (before the 1.3.0 versioning move), so `../doctrine/...`
   escapes above the repo root and `plans/...` only resolves from `docex/`. A few
   are also links to advance/mod files that have since been deleted. As of
   2026-08-20 there are 16 (line numbers will drift):

   - `./docex/plans/advances/007_small_edges/contract_spec_version_ungated.md`
   - `./docex/plans/advances/007_small_edges/doctrine_excerpts_stale_entries.md`
   - `plans/modifications/048_elastic_walk_polish/`
   - `plans/modifications/047_smoke_walk_polish/`
   - `plans/campaigns/shape_overhaul_mod_list.md`
   - `../doctrine/infrastructure/specifics/projinfra/elastic_route53_zone.md`
   - `../doctrine/infrastructure/contracts.md#health-checks`
   - `../doctrine/infrastructure/specifics/projinfra/ec2_traefik.md`
   - `../doctrine/infrastructure/docex.md` (×2)
   - `../doctrine/infrastructure/specifics/projinfra/fixed_reverse_proxy.md`
   - `../doctrine/infrastructure/cicl.md#simplifications`
   - `../doctrine/infrastructure/cicd.md#rollback` (×2)
   - `../doctrine/infrastructure/shape.md`
   - `../doctrine/infrastructure/specifics/elastic_bootstrap.md`

   Repointing a **link target** in frozen history is allowed; rewording a
   **claim** is not. Repair only the paths, leave every word of prose intact.

2. **Add a file-as-root capability to `linkcheck.py::main`.** It currently
   rejects any root that is not a directory (`os.path.isdir`), so the root files
   cannot be scanned even explicitly. Accept a file path as a root (~5 lines).

3. **Add an inline suppression marker** (`<!-- linkcheck-ignore -->` recognized
   in `scannable_lines`, ~2 lines). Repairing paths is not sufficient to bring
   the root files into scope: released history and live prose sometimes *quote* a
   dead reference as evidence (e.g. a changelog entry describing the repair of a
   citation to a file that never existed). Those cannot be repaired without
   destroying the evidence, so they need a per-line suppression.

4. **State the target-vs-claim rule once, in a shared location.** Two sound rules
   collide here — *frozen history is not revised* and *a link that resolves
   nowhere is debt* — and the resolution is that a link target may be repointed
   where a claim may not. `upgrades/README.md` already says this locally about
   upgrade guides; lift it somewhere both it and the changelog can cite.
