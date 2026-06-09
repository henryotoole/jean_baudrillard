# Mod 045 — Campaign Closeout

Sixteenth and final mod of the [doctrine-shape-and-tier campaign](../../campaigns/shape_overhaul_mod_list.md). Reframed from the original "test projects update + smoke walk" scope (operator deferred test-project changes to post-cut re-inception) into a campaign-closeout / version-cut-prep mod.

## What this mod does

Per [`docex_process.md § Cutting a version`](../../core/docex_process.md#cutting-a-version), the prep steps (1–4) that happen on the docex side before the operator/agent runs the actual build + reinstall:

1. **Assign the version.** Campaign forces a major bump (data-plane naming flip, command surface rename, CICL surface rename, project-tier reshape, master VPC switchover, new EC2-traefik variant, IAM scoping tightening — every consumer needs to recompile and redeploy with new identifier forms).

2. **Move `[Unreleased]` → `[<version>] - <date>`** in `CHANGELOG.md`. The campaign has accumulated 15+ `[Unreleased]` entries (one per mod with breaking changes). They become one dated version block.

3. **Cohere the CHANGELOG entries** — current `[Unreleased]` interleaves entries in reverse-chronological mod order. Reading top-to-bottom should tell a coherent story about *what changed in this version*. Restructure into doctrine-shaped sections:
   - `### Added` — EC2-traefik variant (mod 044), `preinfra`/`projinfra`/`envinfra` commands (mod 034), new doctrine-injected env vars (mod 032, which was already in place pre-campaign).
   - `### Changed` — naming policy unification (030), CICL surface (031), telemetry sidecar (032), command surface (034), compiler output (035), per-project traefik (036), Route53+ACM (037), ALB project-tier (038), IAM policy (039), env-tier SG names (040), master VPC preinfra (041), preinfra real checks (042), Service Connect (043).
   - `### Removed` — `bootstrap` command, `up`/`down` commands, `reverse_proxy` role, `domain:` field, `ecr_repo` naming policy, machine-wide-traefik model, per-project VPC.
   - `### Known v1 gaps` — the EC2-traefik SSM release-rerender gap (mod 044), multi-machine fixed deferred.

4. **Bump version in `pyproject.toml`** and **`src/docex/__init__.py`**.

5. **Make the cut commit** with message `Cut docex <v>` matching the existing convention (e.g. `1b69bdc Cut docex 0.12.1`).

## What this mod does NOT do

- **Does NOT build the docker image** — that's operator-side per `docex_process.md § Cutting a version` step 6.
- **Does NOT tag** — operator tags `docex-v<v>` post-commit per step 5.
- **Does NOT reinstall into consumers** — operator runs `docex_install.sh` per step 7.
- **Does NOT re-incept test projects** — that's a separate post-cut workflow per `docex_process.md § Lifecycle` (major cuts trigger re-inception, replacing the seed test projects with fresh-built ones against the new doctrine).
- **Does NOT walk the test projects** — happens during/after re-inception.
- **Does NOT update `test_projects/{fixed,elastic}/`** — those stay in their current (broken-against-new-doctrine) state; re-inception replaces them.

## Version-bump proposal

Current: `0.12.1`. Two reasonable targets:

| Bump | Rationale |
| ---- | --------- |
| `0.13.0` (minor) | Pre-1.0 SemVer allows breaking changes in minor bumps. Avoids the "1.0 means stable API" promise docex hasn't formally made. Per `docex_process.md § Lifecycle`, a minor cut requires smoke walk but not full re-inception. |
| `1.0.0` (major) | Recognizes the scale of the campaign: data plane name forms changed, project file layout reshaped, command surface renamed, new commands added, every backing infrastructure resource subject to change. Matches the operator's earlier statement *"plan to cut a major version number, which will mean a re-write of the test projects anyways"*. Per `docex_process.md § Lifecycle`, major cut requires full re-inception. |

The operator's earlier statement points at `1.0.0`. Treating this as the formal 1.0 framing also signals to future docex consumers: "the doctrine is stable enough to commit to."

## Concrete file surface

- `CHANGELOG.md` — restructure the `[Unreleased]` block into a `[<v>] - <date>` block with doctrine-shaped sections (Added / Changed / Removed / Known v1 gaps).
- `pyproject.toml:7` — version string.
- `src/docex/__init__.py:3` — `__version__` string.

Three files. Mostly textual.

## Operator post-cut activities

After mod 045 lands, the operator (with agent help) runs:

```bash
# Tag the cut commit
git tag docex-v<v>

# Build the new image
docker build -t docex:<v> .

# Push to local registry if applicable

# Re-incept the test projects against the new doctrine (per
# docex_process.md § Lifecycle — major cuts require this).
# Each test project goes through inception PARTs I-IV from scratch,
# producing fresh doctrine-faithful project trees that supersede
# the current test_projects/{fixed,elastic}/ state.

# Walk both new projects through PRE_CUT_CHECKLIST.md against real
# infrastructure.
```

These are outside docex's source tree. Documented here for continuity.

## Operator Decisions

1. **Version: `1.0.0`** — major bump matching the campaign's scale. Triggers full re-inception per `docex_process.md § Lifecycle`.
2. **CHANGELOG restructured** into doctrine-shaped sections (Added / Changed / Removed / Known v1 gaps). Top-to-bottom reads as the story of v1.0.0.

## What This Mod Is NOT

(Repeated for emphasis given the reframe.)

- No code changes beyond the two version constants.
- No `test_projects/` edits.
- No docker image build.
- No git tag (operator action).
- No re-inception (operator action).
- No smoke walk (operator action, post-re-inception).
