---
name: docex-edit
description: Orientation for modifying `docex` itself — the doctrine's executor software — by loading its codebase docs into context. Use whenever the work is *on docex's own source code*: fixing a bug in how docex compiles, releases, migrates, rolls back, or detects infrastructure; adding or changing a docex subcommand or its dispatcher; or altering docex internals. Trigger even when the prompt names a pipeline step — "docex's release code has a bug", "fix the migrate logic inside docex", "add a new docex command" — the tell is that docex's code is being *changed*, not merely *run*. For *running* the pipeline against a project (executing a release/migrate/rollback, a release not picking up a secret), use cicd-pipeline instead.
metadata:
  type: thread
---

`docex` is the executor software of the `doctrine`. It is stored in a subfolder of the `jean_baudrillard` repo which itself can always be found at `~/.claude/jean_baudrillard`.

The exact filepath of the `docex` project root folder is always `~/.claude/jean_baudrillard/docex`. This is the "project folder" for the `docex` code project. Its documentation lives at `$jb/docex/plans/design` — a hand-maintained corpus that *resembles* the doctrine arc42 shape without complying with it (docex is the executor, not a doctrine-authored project). Start with the L1 state docs `$jb/docex/plans/design/{boundary_conditions,concepts_and_decisions,structures_and_views}.md` and `lexicon.md`; the detail tier is `$jb/docex/plans/design/specifics/` (`compiler.md`, `release_flow.md`, `test_projects.md`, `the_shim.md`, `subcommand_surface.md`, and `docex_process.md` — the development process). The reasoning behind load-bearing decisions is in `$jb/docex/plans/design/adrs/`.

Read the L1 arc42 docs, then the relevant `specifics/` files under `$jb/docex/plans/design`, before making any changes to the code.

Also read `~/.claude/jean_baudrillard/doctrine/infrastructure/*.md` to get a good grounding on high level infrastructure concepts.

`docex` no longer carries its own version or cut procedure. As of doctrine version `1.3.0` the version is **doctrine-wide** — doctrine prose, skills, and `docex` advance together under one number, and a `docex` change ships as part of a doctrine release. If your change touches anything the release tracks — the version artifacts (`docex/pyproject.toml`, `docex/src/docex/__init__.py`), the changelog, or behavior that gates a cut — read [`~/.claude/jean_baudrillard/RELEASING.md`](../../RELEASING.md) (the repo-root release process) alongside `docex_process.md`, which keeps only the `docex`-development specifics and routes there.

Furthermore, it's a good idea to be aware of all files in `~/.claude/jean_baudrillard/doctrine/infrastructure/specifics` as well. These contain details from the doctrine on several key functions that `docex` performs.