---
name: doctrine-update
description: Update the operator's machine to the latest released doctrine — git-pull the jean_baudrillard repo, run setup.sh, and report the version delta. Use whenever the operator wants to refresh, update, pull, or sync their doctrine install, get the newest skills, or is "behind" on the doctrine — e.g. "update the doctrine", "pull the latest jean", "get the new skills", "am I on the current doctrine?", "sync my doctrine install". This refreshes the MACHINE (resident stratum + skills + docex image); bringing a downstream PROJECT onto the new version is the separate project-upgrade skill.
metadata:
  type: conventional
---

# doctrine-update

Refresh this machine's doctrine install to the latest released version. The
doctrine repo always lives at `~/.claude/jean_baudrillard` (referred to below as
`$jb`); the version is doctrine-wide and stored in `$jb/VERSION` (see
`$jb/RELEASING.md` for how it's cut).

This skill updates the **machine** — the resident stratum loaded into every
session, the skill set delivered by the plugin, and the local `docex` image. It
does **not** touch any downstream project; moving a project onto the new version
is the [`project-upgrade`](../project-upgrade/SKILL.md) skill.

## Why a fresh session is needed afterward

The resident stratum and the skill set are read at **session start** — the
plugin cache snapshot and `RESIDENT.md` are consumed when a Claude session
boots, not mid-session. So new skills and resident changes from this update will
**not** be active in the current session. Finish the update, then tell the
operator to start a new session to pick them up. Plan the report around that.

## Procedure

1. **Record the current version.** `cat $jb/VERSION` → call it `OLD`. (If
   `VERSION` is absent, the install predates the unified scheme — `OLD` is
   whatever `docex/pyproject.toml` reports; treat the pull as crossing into the
   versioned era.)

2. **Guard the working tree.** `git -C $jb status --porcelain`. If it's dirty,
   **stop and report** rather than pulling — this may be a doctrine *maintainer's*
   working repo with uncommitted edits, and a pull could clobber or conflict.
   Let the operator stash/commit or confirm before proceeding. A clean tree is
   the normal consumer case; proceed.

3. **Pull `main`.** `git -C $jb pull --ff-only origin main`. If it can't
   fast-forward (diverged history, conflicts), stop and surface the git output —
   don't force it. The doctrine is trunk-based, so a consumer machine should
   always fast-forward.

4. **Read the new version.** `cat $jb/VERSION` → `NEW`. If `NEW == OLD`, the
   machine was already current — report that and stop (no need to re-run setup).

5. **Run setup.** `bash $jb/setup.sh`. This is idempotent and does three things:
   re-merges settings, regenerates `RESIDENT.md` from `stratum: resident`
   frontmatter, and reinstalls the plugin. The plugin reinstall is what lands
   new/changed/removed skills — the plugin's version (synced to `NEW` at release)
   keys the Claude plugin cache, so the bump forces a fresh snapshot. Watch its
   output for the marketplace/install warnings it prints if the `claude` CLI
   isn't on PATH.

6. **Build the `docex` image for `NEW` if missing.** `docker images docex:NEW`;
   if absent, `docker build -t docex:NEW $jb/docex`. A later `project-upgrade`
   that repins a project to `NEW` needs this image present locally (images are
   built locally, not pulled — see `$jb/docex/plans/core/masterplan.md`).

7. **Report the delta.** Tell the operator:
   - `OLD → NEW`.
   - A short summary of what changed, read from the `[NEW]` (and any intervening)
     entries in `$jb/CHANGELOG.md`.
   - Whether any **project upgrade** is implied: list the guides in
     `$jb/upgrades/` whose `version` frontmatter falls in `(OLD, NEW]`. If any
     exist with `project` in their `scope`, note that downstream projects on an
     older pin should be moved with the `project-upgrade` skill. Machine-only
     guides (`scope: [machine]`) are already fully handled by this run.
   - **Start a fresh session** to activate the new resident stratum and skills.

## When something blocks

Surface the real obstacle; never paper over it. A dirty tree, a non-fast-forward
pull, a failed `setup.sh` step, or a missing `claude` CLI each have a clear
remedy the operator can act on — report the exact command output and the
remedy, and stop. A half-applied update that silently "succeeds" is worse than a
clean stop.
