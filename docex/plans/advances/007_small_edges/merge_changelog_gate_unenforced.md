# The changelog obligation has no enforcement, and a core doc claimed it did

**Found:** advance 006, mod 134b, while verifying `masterplan.md`'s *Filesystem Surface*
section against the code. **Not fixed there** — adding a gate is a behavior change, and
the question of *what* to gate on is genuinely open.

## The finding

`doctrine/infrastructure/version_control.md § Updating` is unconditional:

> Any time a version number is incremented, an update should be added to the changelog.

`docex merge` is the command that increments-and-tags. Its own module docstring
(`pipeline/merge.py:1-11`) lists the steps:

```
  4. Tag ``v<project.version>``; refuse if the tag already exists.
  5. Push ``main`` and the new tag.
```

It reads `project.yml`'s `version`, refuses a tag that already exists (`merge.py:131-137`),
tags `main`, and pushes. **No code in `docex` reads `CHANGELOG.md`.** A grep across
`src/` returns zero hits in any module — the only matches are in
`src/docex.egg-info/PKG-INFO`, a build artifact carrying a copy of the prose.

So the one doctrine obligation attached to a version bump is enforced by nothing, at the
exact moment the bump becomes permanent and public.

## Why it is worth a brief — how the absence stayed invisible

`plans/core/masterplan.md:201` listed, under the commands' **Read** inventory:

```
- `CHANGELOG.md` — referenced by `merge` for version-bump validation
```

The core doc asserted the gate existed. Anyone auditing "is the changelog obligation
enforced?" against the documentation would have found the answer *yes* and stopped.

That is this advance's **signature defect shape** — a documented obligation with no
enforcement, plus a document asserting the enforcement — and here it lands in the
release process itself, on the one artifact whose purpose is to tell a future reader
what changed between two versions.

Mod 134b **deleted** that line, because a false entry in a Read inventory is worse than
an absent one. This brief is what stops the deletion also deleting the finding: after
the deletion, nothing anywhere records that anybody noticed.

## The real question — stated, not answered

**Should `merge` gate on a changelog entry, and if so, on what predicate?**

Three candidates, each with a real objection:

- **A `## [<version>]` heading matching `project.yml`'s version.** The most direct
  reading of the obligation, and the only predicate that actually checks *this* bump was
  recorded. Objection: it hardcodes a changelog *format*. The doctrine recommends
  keepachangelog but a downstream project's changelog may reasonably drift from it, and a
  gate that fails on a differently-shaped-but-honest changelog teaches operators to
  bypass gates.
- **A non-empty `## [Unreleased]` section.** Cheap and format-light. Objection: it gates
  the **wrong artifact**. The `[Unreleased]` section is emptied *by* the release — moved
  into the new version's heading — so a correctly-rolled changelog fails this check and
  an un-rolled one passes it. It tests that work was recorded, not that it was released.
- **A non-empty diff of `CHANGELOG.md` against the previous tag.** Format-agnostic and
  cannot be confused about which release it is checking. Objection: permissive to the
  point of meaninglessness — one whitespace change satisfies it, and a gate that any
  edit satisfies is a gate that trains people to make one.

## The prior-art constraint

The doctrine's own release process, `RELEASING.md:92-97`, walks the changelog step **by
hand**:

> 3. **Roll the changelog.** In `CHANGELOG.md`, move `[Unreleased]` → `[<v>]` with
>    today's date (Keep a Changelog format).
> …
> 5. **Commit** the version bump and changelog roll.

So a gate in `docex` would be the **first mechanical enforcement** of an obligation the
doctrine has so far discharged through operator discipline. That cuts both ways: it is
evidence the obligation is real and routinely honored, and it is evidence that nobody has
yet needed a machine to honor it.

**Also open: whether it belongs in `merge` or in `check`.** `merge` is where the bump
becomes permanent, which argues for gating there. But `check` is where every other gate
lives, it runs against the merged state in a worktree, and it runs *before* the operator
has committed to anything — so a `check`-time failure is cheap and a `merge`-time failure
is not. Choosing between them is a question about where the pipeline's gates belong, not
about changelogs, and this brief does not answer it either.

## The obligation is already being missed, in the artifacts closest to hand

Found while executing mod 134b, and worth recording because it turns the brief from a
hypothetical into a measurement. **Both smoke seeds — the trees downstream projects copy
— have shipped versions with no changelog entry at all**, and both have an
`## [Unreleased]` section that has never been rolled:

Counted by differencing each seed's `git tag` list against its `## [<version>]` headings
— which is the only honest way to count it, and is what a gate would do:

| Seed | Tags | Changelog entries | Versions shipped with **no** entry |
| ---- | ---- | ----------------- | ---------------------------------- |
| `fixed` | `v0.0.1`–`v0.0.20` (20) | 13 | `0.0.6`, `0.0.7`, `0.0.8`, `0.0.9`, `0.0.10`, `0.0.12`, `0.0.18` — **7** |
| `elastic` | `v0.0.1`–`v0.0.24` (24) | 15 | `0.0.6`, `0.0.7`, `0.0.8`, `0.0.9`, `0.0.10`, `0.0.12`, `0.0.21`, `0.0.22`, `0.0.23` — **9** |

**Sixteen missed entries across two repos** — 36% of all tagged versions — in the one
place a reader looks for an exemplar of the doctrine's own practice. Nothing reported it,
because nothing can, which is the brief's whole point arriving as evidence rather than
argument.

A note on the count, since this brief is about believable wrong numbers: mod 134b's
implementor first reported **four** (`0.0.18` on `fixed`; `0.0.21`–`0.0.23` on `elastic`)
by reading the recent tail of each file. Differencing against the tag list found the older
`0.0.6`–`0.0.10` and `0.0.12` gaps as well, and quadrupled the figure. Whoever builds the
gate should difference against tags rather than eyeballing, for the same reason.

Two consequences worth carrying into whatever fixes this:

- **A gate keyed on "a `## [<version>]` heading matching `project.yml` exists" would have
  caught all four**, which is a point in that predicate's favour that the objection above
  does not answer.
- **The stale `## [Unreleased]` section is a second, quieter failure.** Mod 134b added its
  version headings *above* the untouched `[Unreleased]` block rather than rolling it,
  deliberately: rolling it would have moved advance-006 content that mod had no claim on.
  So "roll `[Unreleased]` into the new version" is a step no command performs and no
  operator has performed either, and any gate design has to decide whether it is asserting
  that the section is empty, that it is non-empty, or nothing about it at all.

## Where to look

- `doctrine/infrastructure/version_control.md § Updating` — the obligation, in one
  sentence.
- `test_projects/{fixed,elastic}/CHANGELOG.md` — the four missed entries and the two
  never-rolled `[Unreleased]` sections.
- `src/docex/pipeline/merge.py:1-11` — the step list; `:131-137` — the version read and
  the tag refusal, i.e. the only place `project.yml`'s version is acted on.
- `src/docex/pipeline/check.py` — where every other gate lives, and the alternative home.
- `plans/core/masterplan.md` § *Filesystem Surface* — the **Read** list the false claim
  was removed from (mod 134b).
- `RELEASING.md:92-97` — the by-hand changelog step the gate would mechanize.
