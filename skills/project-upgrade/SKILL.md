---
name: project-upgrade
description: Move a downstream project onto a newer doctrine version by walking the chain of upgrade guides between the project's current docex_version pin and the target version. Use whenever the operator wants to upgrade, repin, or bring a project up to date with the doctrine — e.g. "upgrade this project to the latest doctrine", "bring this project onto 1.3.0", "repin docex and follow the upgrade guides", "this project is on an old docex, update it". This acts on a PROJECT (its repo, infra, deploys); refreshing the operator's MACHINE to the latest doctrine first is the separate doctrine-update skill.
metadata:
  type: conventional
---

# project-upgrade

Move one consuming project from its current pinned doctrine version onto a newer
one, by walking the [upgrade-guide tape](../../upgrades/README.md). The doctrine
repo is at `~/.claude/jean_baudrillard` (`$jb`); upgrade guides live in
`$jb/upgrades/`, one per release that needs action, each named
`upgrade_<version>.md` with `version` / `severity` / `kind` / `scope`
frontmatter.

This skill acts on a **project** — its repo, compiled output, infrastructure,
and deploys. The project's `project.yml` `docex_version` pin *is* the doctrine
version it currently sits on.

## Precondition: the machine must already be on the target

Guides are read from `$jb/upgrades/`, so the machine's installed doctrine must
already be at (or above) the version you're upgrading the project to — otherwise
the target guide isn't on disk yet. If `$jb/VERSION` is behind where the
operator wants the project, run [`doctrine-update`](../doctrine-update/SKILL.md)
first, then come back. The default `TARGET` is `$jb/VERSION`.

## Procedure

1. **Identify the project and its pin.** Confirm the working directory (or the
   path the operator names) is a doctrine project — it has `project.yml` with a
   `docex_version` field. Read that field → `FROM`. Read `$jb/VERSION` →
   `TARGET` (unless the operator named a different, on-disk target).
   - If `FROM == TARGET`, the project is already current — say so and stop.
   - If `FROM > TARGET`, this isn't an upgrade. Stop and explain — moving *back*
     a version is not this skill's job (and `docex rollback` is a different
     thing: it reverts a deployed *env*, not a doctrine pin).

2. **Build the guide chain** over `(FROM, TARGET]`. List `$jb/upgrades/upgrade_*.md`,
   read each one's `version` frontmatter, and select those whose `version` is
   greater than `FROM` and ≤ `TARGET`. Order ascending by `version`. A release
   with no guide simply contributes nothing — chaining is by release order, not
   an unbroken filename sequence.

3. **Apply the chaining rule** (authority: `$jb/upgrades/README.md`):
   - **If any selected guide is `kind: rebuild`,** discard everything at or before
     the *latest* such guide and keep only that rebuild guide, followed by any
     `incremental` guides after it. A rebuild tears down and stands up fresh, so
     replaying earlier incremental steps first is wasted or wrong work; the
     rebuild guide carries complete, start-point-agnostic instructions itself.
   - **Otherwise** keep the full `incremental` chain in `version` order.
   - Drop any guide whose `scope` does not include `project` — that work belonged
     to `doctrine-update` on the machine side. Note what you dropped and why.

4. **Present the plan and get confirmation before acting.** Show the ordered
   guides with their `version`, `severity`, and `kind`. This matters most for a
   `kind: rebuild` step: it destroys stage/prod infrastructure (and requires
   data backups + DNS/secret records up front), so the operator must understand
   the blast radius before you begin. Do not start mutating a project on an
   unconfirmed plan.

5. **Walk the chain.** For each guide in order, follow its **Project upgrade**
   section as the authoritative runbook for that step — typically: repin via
   `bash $jb/docex_install.sh <project>`, `./bin/docex compile` and review the
   diff, any `infra.yml` edits the guide calls for, then redeploy through the
   pipeline. The guide is the source of truth for *its* transition; this skill
   only orders and sequences the guides, it does not restate their steps.

6. **Verify.** Run each guide's **Verification** section. For the final state,
   confirm `./bin/docex --version` matches `TARGET` and `grep docex_version
   project.yml` is `TARGET`. Don't declare the upgrade complete until the project
   actually runs on the new version (and, after a rebuild, until restored data
   reads back correctly).

## Why confirmation and ordering are load-bearing

The guides do the work; this skill's value is *which guides, in what order, and
the rebuild short-circuit*. Getting that wrong is what causes damage — replaying
incremental steps across a rebuild, or running a destructive rebuild the
operator didn't expect. So the two non-negotiables are: compute the chain per
the rule above, and surface a destructive plan for confirmation before touching
the project.
