# Upgrade Guides

This directory holds the **upgrade guides** that move a consuming project (and,
where relevant, an operator's machine) from one doctrine version to the next.
Each release that requires upgrade action ships one guide here; the
`project-upgrade` skill discovers and chains them.

The producer side — when and how a guide is authored — is in
[`../RELEASING.md`](../RELEASING.md). This file defines the **schema** and the
**chaining rule** the skill relies on.

## One Guide Per Release

A guide is **the upgrade guide that ships with one release** — it describes the
work to move onto that release from the one before it. It is written once, when
that release is cut, then never revised. **One narrow exception:** a guide's
**link targets** may be repointed when a later release renames the doctrine
section a link addresses. Nothing else may change — no prose, no instruction, and
no version claim. A guide's words are the historical artifact; its links are
pointers into living doctrine, and a dangling one preserves nothing while making
the guide unusable. The general rule for frozen history — targets may be repointed, claims may not — is stated once in [`../RELEASING.md`](../RELEASING.md#editing-frozen-history-targets-vs-claims). Guides form a totally-ordered **tape**:
`project-upgrade` finds a project's entry point in the sequence and plays the
guides forward to the target version. This keeps each guide small and
single-purpose; no guide has to anticipate "every possible starting point" (the
one exception is `kind: rebuild`, below).

Filename: `upgrade_<release_version>.md` (e.g. `upgrade_1.3.0.md`). The filename
is a convenience; the authoritative version is the `version:` frontmatter field.

A release with no upgrade action (a trivial PATCH) ships **no** guide. The
chaining algorithm treats a missing release as "nothing to do beyond pull +
setup" — guides chain by release order, not by an unbroken filename sequence.

## Frontmatter Schema

Every guide begins with YAML frontmatter:

```yaml
---
version: "1.3.0"       # the release this guide ships with (authoritative; filename mirrors it)
severity: minor        # patch | minor | major  (mirrors the SemVer bump)
kind: incremental      # incremental | rebuild   (see Chaining Rule)
scope: [machine]       # subset of [machine, project] — which targets have action items
---
```

- **`version`** — the release this guide ships with. The skill orders and
  selects guides by this, not by filename. There is no `from` field: the prior
  release is whatever precedes this one on the tape, and the authoritative
  lineage lives in the `v<x>` git tags and [`../CHANGELOG.md`](../CHANGELOG.md),
  not hand-copied into each guide.
- **`severity`** — the SemVer level of the bump. Orientation for the operator;
  not load-bearing for chaining.
- **`kind`** — `incremental` (the steps are replayable and chainable with
  adjacent guides) or `rebuild` (the upgrade tears infrastructure down and
  stands it up fresh; it is start-point-agnostic and **short-circuits** the
  chain — see below).
- **`scope`** — which upgrade targets actually have work. `machine` = the
  operator's `~/.claude/jean_baudrillard` install (handled mostly by
  `doctrine-update`). `project` = a consuming project's repo (handled by
  `project-upgrade`). A skill skips a guide whose scope excludes its target.

## Body Sections

In order, each present only when it has content:

| Section | Contents |
| ------- | -------- |
| **Summary** | One paragraph: what changed and why this guide exists. |
| **Machine sync** | What `git pull` + `setup.sh` handle automatically, and any manual machine-side step that doesn't (rare — e.g. a removed skill leaving a stale cache, a settings key needing attention). |
| **Project upgrade** | The heavy section: repin, recompile, `infra.yml` edits, redeploy, data implications. Ordered, with the *why* behind any non-obvious ordering. |
| **Doctrine / behavior notes** | Rule or convention changes the operator should know even if nothing mechanical breaks. |
| **Verification** | How to confirm the upgrade actually landed. |

## Chaining Rule

Given a project's current pin `FROM` and a `TARGET` version, `project-upgrade`:

1. Collects every guide whose `version` is in the half-open range `(FROM, TARGET]`.
2. Orders them ascending by `version`.
3. **If any guide in the set is `kind: rebuild`,** discards everything at or
   before the latest such guide and applies **only** that latest rebuild guide,
   followed by any `incremental` guides after it. A rebuild tears down and
   rebuilds from scratch, so replaying earlier incremental steps first would be
   wasted (or wrong) work — the rebuild guide carries complete, start-point-
   agnostic instructions on its own.
4. Otherwise applies the `incremental` chain in `version` order.

A guide whose `scope` doesn't include the running skill's target is noted and
skipped (e.g. `project-upgrade` skips a `scope: [machine]`-only guide).

## Relationship to the Changelog

The [changelog](../CHANGELOG.md) is the *narrative* of what changed in each
release; an upgrade guide is the *runbook* for acting on it. The guide should
link to the relevant changelog entry rather than restate it.
