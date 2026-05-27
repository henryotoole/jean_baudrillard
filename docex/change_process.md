# `docex` — Change Process

This file is the canonical process for changing `docex` itself.

`docex` executes the doctrine, but its own development **does not follow the
standard [mod cycle](../doctrine/practices/modifications.md)** — there is no
`plans/modifications/` tree for it. This document exists because that leaves a
gap: a repeatable, written way to evolve the tool safely.

## Why `docex` needs its own process

Two properties make `docex` different from an ordinary project:

1. **Determinism is the product.** A project pins `docex_version` in its
   `project.yml` and is promised byte-identical compiler output forever (see
   [design_proposal.md § Goals](./design_proposal.md#goals)). Changing
   behavior therefore isn't just a code edit — it implies a new version, an
   image rebuild, and a reinstall into every consuming project. The mod cycle
   never deals with any of that.
2. **Doctrine ↔ docex coupling.** A single change is often simultaneously a
   *doctrine-rule* change and a *docex* change. Up to four artifacts move
   together, and the main hazard is drift between them:

   | Artifact | Role |
   | -------- | ---- |
   | `doctrine/.../*.md` | The rule of record. The *why* and the canonical statement. |
   | `tables/roles/*.yml` | Transfer tables — how a role/engine compiles per foundation. |
   | `src/docex/**` | Compiler / orchestration code that executes the rule. |
   | `tests/**` | Proof the executor matches the rule. |

   Keep them aligned. Fixing the code while leaving the rule stale (or vice
   versa) is the failure mode this process guards against.

## Per-change loop

For each discrete change:

1. **Settle the rule.** If the change alters doctrine, decide the rule first
   and edit the relevant `doctrine/.../*.md`. The doctrine is the source of
   truth; docex follows it, not the reverse.
2. **Update docex to match** — transfer tables first, then code.
3. **Add or adjust tests.** Unit tests by default; add an integration test
   when behavior crosses a real boundary (docker / AWS / git).
4. **Verify.** From `docex/`, run `python3 -m pytest -q` (offline, ~9s;
   integration tests are gated and skipped by default). Green before moving on.
5. **Record.** Add an entry under `[Unreleased]` in
   [`CHANGELOG.md`](./CHANGELOG.md), and keep `design_proposal.md` and any
   affected doctrine specifics in sync as part of the same change.

## Versioning & cutting an image

`docex` follows SemVer per
[version_control.md](../doctrine/infrastructure/version_control.md). The image
tag always equals the version — no floating tags (see
[design_proposal.md § Distribution](./design_proposal.md#distribution)). The
image is the unit of determinism, so a version is only meaningful once its
image is built.

**Built images are not git-tracked** — they are build artifacts living in the
local Docker store. The determinism promise ("a project pinned to a version
gets identical output forever") therefore rests on being able to *rebuild* a
version's image from source, which requires that version's source to be
recoverable. **The git tag is what makes it recoverable** — without it, finding
"the commit that was 0.4.0" is archaeology. So every cut is tagged, mirroring
the discipline `docex merge` already enforces for consumer projects.

### Cutting a version

Whatever the mode, a *cut* is the same ordered procedure, run from a clean
tree:

1. Assign the version `<v>` (SemVer).
2. Move `[Unreleased]` → `[<v>]` (dated) in [`CHANGELOG.md`](./CHANGELOG.md).
3. Bump the version in `pyproject.toml` **and** `src/docex/__init__.py`.
4. Commit.
5. **Tag the cut commit `docex-v<v>`.** The tag is namespaced (`docex-v…`, not
   a bare `v…`) because this repo also holds the doctrine — a bare version tag
   would collide if the doctrine is ever versioned.
6. Rebuild the image: `docker build -t docex:<v> .` from `docex/`.
7. Reinstall into consumers: `bash docex_install.sh <project>`.

### When to cut

- **Single isolated change** — cut immediately after the per-change loop.
- **Campaign** (several related changes, e.g. an overhaul) — work under a
  single **uncut, rolling version**: leave both version files untouched,
  accumulate every change under `[Unreleased]`, and **cut once at the end**.
  This avoids rebuild-and-reinstall churn per change while the surface is still
  moving.

## Git

Trunk-based: commit directly to `master`, consistent with the doctrine's
[branch conventions](../doctrine/infrastructure/version_control.md#branch-conventions)
and how the rest of this repo is maintained.

## Verification reference

- **Inner loop:** `python3 -m pytest -q` from `docex/` — offline unit +
  compile tests.
- **End-to-end:** `pytest -m integration` (requires a real docker daemon; the
  suite self-skips if `docker info` fails), and/or rebuild the image and
  exercise it against a real consumer project.

## Backlog

Outstanding issues surfaced during real-project use are tracked in
[`engineer/todo.md`](../engineer/todo.md) under the "First Run Fix List".
