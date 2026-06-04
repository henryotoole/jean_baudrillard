# Mod 029 — Rollback command

## Problem

The doctrine specifies the `rollback` feature ([cicd.md § Rollback](../../../../doctrine/infrastructure/cicd.md#rollback), [docex.md § rollback](../../../../doctrine/infrastructure/docex.md#rollback)) but `docex` does not yet implement it. An operator faced with a broken production release has no doctrine-supported way to revert — they have to manually retag, hand-drive ansible/tofu, and reason about migrations themselves.

The doctrine commits rollback to a narrow window: emergency-only, code-only (no reverse migrations), at most one minor version back, explicit target version. This mod ships that command.

## Scope

In scope:

1. **New CLI**: `./bin/docex rollback <env> <target_version>` for `<env> ∈ {stage, prod}`.
2. **New module**: `src/docex/pipeline/rollback.py` — orchestration entry point. Composes existing release machinery rather than duplicating it.
3. **Argparse wiring** in `src/docex/__main__.py`.
4. **`skip_migrations` parameterization** on the existing `_release_fixed` / `_release_elastic`. Internal API change; `release`'s call sites stay at the `False` default.
5. **Image-existence probes** added per foundation:
   - Fixed: `manifest_inspect`-shaped method on `src/docex/docker/subprocess_client.py` (and its abstract client interface), wrapping `docker manifest inspect`.
   - Elastic: `ecr_image_exists` method on the `AWSClient` interface (`src/docex/aws/client.py`) and its `boto3_client.py` implementation.
6. **Worktree-at-tag** mechanism. `check.py` has an ephemeral-worktree helper, but anchored at "feature tip merged onto fresh main". This mod either generalizes that helper or adds a small parallel one — see Design below.
7. **Tests**: unit coverage for preconditions, version comparison, image probes; integration coverage proving migrations are skipped on both foundations and that the elastic path still re-pushes secrets.
8. **`docex/plans/core/release_flow.md`** gets a "Rollback flow" section appended (the doc-update step happens post-implementation per the mod cycle).
9. **`PRE_CUT_CHECKLIST.md`**: a rollback step added to both foundation walks. The next minor cut exercises rollback in real infrastructure.
10. **CHANGELOG**: `[Unreleased]` entry.

Out of scope:

- The deletion-protection doctrine gap (deferred — see [cicd.md § Rollback](../../../../doctrine/infrastructure/cicd.md#rollback) narrow-window argument).
- A `./bin/docex inspect <env>` helper for detecting rolled-back state.
- Reverse migrations (doctrine commits to code-only rollback).
- Doctrine text changes — already settled in the prior turn.
- A docex version cut. This mod lands on `main` under `[Unreleased]`; the cut is a separate step run after the campaign closes.

## Design

### Command surface

```
./bin/docex rollback <env> <target_version>
```

- `<env>` ∈ `{stage, prod}`. Other values rejected (mirrors `release`).
- `<target_version>` is a SemVer string matching a `v<target_version>` git tag.
- One flag: `--dry-run`. Symmetric across both foundations — runs the precondition + worktree + recompile chain, then reports what would be applied without committing it. On fixed this maps to `ansible-playbook --check`; on elastic it maps to `tofu plan` (no apply). Useful safety net under emergency pressure; explicit target version still required.

### Preconditions (fail-fast, in order)

1. `<env>` is `stage` or `prod`.
2. Current git branch is `main`.
3. Working tree is clean (same helper used by `merge`).
4. `v<target_version>` tag exists locally (`git.tag_exists`).
5. `<target_version>` is no more than one minor behind `project.yml`'s current version. Concretely: parse both as `(major, minor, patch)`; require `target.major == current.major` and `target.minor >= current.minor - 1`.
6. For every core service declared in `infra.yml`, the image at `<target_version>` exists in the registry. Probes for **all** core services run before any failure is reported — the operator sees the complete list of missing images in one shot, not a fail-fast first match. Emergency diagnostics benefit from completeness; the probes are cheap.

Failure on any other precondition aborts on first hit (cheap, sequential checks).

### Worktree-at-tag and recompile

`check` already has an ephemeral-worktree helper, but its recipe is "feature tip merged onto fresh main". Two paths:

- **(a)** Generalize the helper to accept a ref / recipe; the existing `check` call site passes its merge recipe; rollback passes `v<target_version>`.
- **(b)** Add a small parallel helper used only by rollback.

(a) is structurally cleaner; (b) is smaller in this mod. The right call depends on how tightly the current helper is coupled to its specific recipe. I'll inspect during `implementation.md` drafting and pick then.

Once the worktree is checked out at `v<target_version>`:

- Recompile `infra/output/<env>/` against the worktree's `infra.yml` using the current `docex`'s compiler.
- The compiled output lives inside the worktree, not the operator's main working tree.
- The foundation-specific apply runs against this worktree-local output.

### Foundation-specific apply (migrations skipped)

The existing `_release_fixed` / `_release_elastic` gain a `skip_migrations: bool = False` parameter:

- **Fixed** with `skip_migrations=True`: the ansible-playbook invocation gains `--skip-tags migrate`. The playbook's per-task `tags: [migrate]` already declared per [release_mechanism.md § Fixed-foundation mechanism](../../../../doctrine/infrastructure/specifics/release_mechanism.md#fixed-foundation-mechanism) is what makes this work cleanly with no template changes.
- **Elastic** with `skip_migrations=True`: SSM push still happens; both the pre-migrate targeted `tofu apply` (from mod 008) and the `RunTask` migration step are skipped. The single full `tofu apply` against the recompiled HCL converges the env.

`rollback` calls these with `skip_migrations=True`. `release` continues with the default `False`.

When `--dry-run` is set, the apply step is replaced (not augmented) with its preview equivalent: `ansible-playbook --check` on fixed, `tofu plan` on elastic. Secrets push on elastic happens unchanged in dry-run mode — SSM push is idempotent and the operator sees the resulting plan against the new SSM values. (Alternative: skip the SSM push in dry-run. Settle in implementation.md after looking at how the existing release path stages SSM.)

### Image probes

Both probes return `bool` and treat "not found" as a normal answer, not an exception:

- **Fixed**: `DockerClient.manifest_inspect(ref: str) -> bool` — runs `docker manifest inspect <ref>`; returns `True` iff exit code is 0.
- **Elastic**: `AWSClient.ecr_image_exists(repository: str, tag: str) -> bool` — calls `ecr.describe_images(repositoryName=repository, imageIds=[{"imageTag": tag}])`; returns `True` on success, `False` on `ImageNotFoundException`, propagates other exceptions.

The dispatch in `rollback.py` selects the probe by `infra.foundation`.

### Module layout (proposed)

```
src/docex/pipeline/rollback.py                new
src/docex/pipeline/release.py                 + skip_migrations param
src/docex/__main__.py                         + argparse subcommand
src/docex/docker/{client,subprocess_client}.py + manifest_inspect
src/docex/aws/{client,boto3_client}.py        + ecr_image_exists
tests/pipeline/test_rollback.py               new
tests/docker/test_subprocess_client.py        extend
tests/aws/test_boto3_client.py                extend
```

### PRE_CUT_CHECKLIST walk pattern

To exercise rollback against real infrastructure, the cut walk for both test projects needs two versions present in the registry — the rollback target and the rollback-from. The pattern:

1. Standard walk through current version v0.0.X (release-prod lands prod on v0.0.X; first image in registry).
2. Bump test project: v0.0.X → v0.0.X+1 (mechanical bump, no code change). Inner-repo commit + tag move per `test_projects.md § Commit cadence`.
3. Containerize + release prod at v0.0.X+1 (second image in registry; prod now at v0.0.X+1).
4. `./bin/docex rollback prod 0.0.X`.
5. Verify env reports v0.0.X via `/health`.
6. Teardown.

No fix-forward release follows the rollback step in the walk — fix-forward is just a normal release, already exercised earlier in the walk. The novel surface tested here is rollback itself; verifying the env lands cleanly at the older version is what matters.

Cost: one test-project version bump per cut, in both smoke projects. The test project version creeps monotonically (carrying no semantic load).

### Deferred to implementation.md

**Worktree generalization vs. parallel helper.** `check`'s ephemeral-worktree helper anchors at a specific recipe; rollback needs an arbitrary tag checkout. Whether to generalize the helper or write a parallel one depends on how tightly `check`'s helper is coupled to its recipe. Resolved by reading `check.py` during implementation drafting.

## Five-artifact alignment

| Artifact | Change |
| -------- | ------ |
| `doctrine/.../*.md` | None — already settled in the doctrine pass. |
| `docex/plans/core/*.md` | `release_flow.md` gets a "Rollback flow" section appended (post-implementation step). |
| `tables/roles/*.yml` | None. |
| `src/docex/**` | New `pipeline/rollback.py`; small edits to `pipeline/release.py`, `__main__.py`, `docker/{client,subprocess_client}.py`, `aws/{client,boto3_client}.py`. |
| `tests/**` | New `tests/pipeline/test_rollback.py`; extend existing docker- and aws-client test files for the new probe methods. |

## Risk and rollback

- **Risk: rollback applies wrong version.** Mitigated by the explicit `<target_version>` argument and by the registry probe — target images must exist for every core service before any apply runs.
- **Risk: tofu destroys a stateful backing service added since the target version.** Accepted by the doctrine's narrow-window thesis. `deletion_protection: true` on RDS still gates this case; analogous protection on other engines is separate doctrine work.
- **Risk: `skip_migrations` parameter introduces a bug in the existing `release` path.** Mitigated by defaulting the new param to `False`; the existing call sites and tests stay unchanged. Integration tests cover both `False` and `True` paths.
- **Mod rollback**: revert the new files and the small edits. No state migration, no schema change, no doctrine reversion needed.

## What this mod does NOT do

- Does not cut a new docex version.
- Does not implement reverse migrations.
- Does not address the deletion-protection doctrine gap.
- Does not add a `docex inspect <env>` helper.
- Does not modify the ansible playbook template — the `--skip-tags migrate` selector works against the per-task `tags:` declaration that already exists.
- Does not modify the doctrine.
