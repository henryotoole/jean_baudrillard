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

Two modes, chosen by the shape of the work:

- **Single isolated change.** Bump the version in `pyproject.toml` +
  `src/docex/__init__.py`, move `[Unreleased]` → `[<version>]` in the
  changelog, rebuild (`docker build -t docex:<version> .` from `docex/`), and
  reinstall into consumers (`bash docex_install.sh <project>`).
- **Campaign** (several related changes, e.g. an overhaul). Work under a
  single **uncut, rolling version**: leave `pyproject.toml` and `__init__.py`
  untouched during the work, accumulate every change under `[Unreleased]`, and
  **cut once at the end** — assign the version, move `[Unreleased]` → `[<v>]`,
  bump both version files, rebuild the image, and reinstall into consumers.
  This avoids a rebuild-and-reinstall churn per change while the surface is
  still moving.

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
