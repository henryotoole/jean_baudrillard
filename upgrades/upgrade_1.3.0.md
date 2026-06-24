---
version: "1.3.0"
severity: minor
kind: incremental
scope: [machine]
---

# Upgrading to doctrine 1.3.0

The release that **unifies versioning across the whole repo**. Before 1.3.0 the
only version was `docex`'s; doctrine prose and skills rode along uncut. From
1.3.0 there is one doctrine-wide version (see [`../RELEASING.md`](../RELEASING.md)),
and this release adds the two skills that produce and consume it. See the
[1.3.0 CHANGELOG entry](../CHANGELOG.md) for the full list.

This is a **machine-only** upgrade: nothing about `docex`'s behavior changed, so
**no project needs to repin, recompile, or redeploy**. A project may advance its
`docex_version` pin to `1.3.0` whenever convenient (it now equals the doctrine
version it sits on), but nothing breaks if it lags.

## Machine sync

Run the **`doctrine-update`** skill (or do it by hand): `git pull` in
`~/.claude/jean_baudrillard`, then `bash setup.sh`. That single `setup.sh` run
lands everything in this release:

- **The new skills appear** — `doctrine-update` and `project-upgrade`. They land
  because `.claude-plugin/plugin.json`'s version, **previously stuck at `0.1.0`,
  is now synced to the doctrine version (`1.3.0`)**. The Claude plugin cache is
  keyed on that value, so the bump forces a fresh cache snapshot — which is also
  the fix that makes *all future* skill changes reliably land on `setup.sh`
  re-runs. If an old `0.1.0` snapshot lingers in your plugin cache, it is inert;
  the enabled plugin is the `1.3.0` snapshot.
- **`RESIDENT.md` is regenerated** from `stratum: resident` frontmatter. No
  resident-stratum files changed this release, so expect a no-op here.
- **`docex:1.3.0` is (re)built** if absent. `docex`'s code did not change from
  `1.2.0`, so this is a byte-identical rebuild apart from the embedded version —
  it exists only to keep the *doctrine version ⟺ `docex` image* invariant.

## Doctrine / behavior notes

What changed in *where things live*, so you're not surprised after the pull:

- **`VERSION`** at the repo root is the single source of truth for the version.
- **`CHANGELOG.md` moved to the repo root** (was `docex/CHANGELOG.md`, now a
  pointer stub) and is now doctrine-wide. All historical `docex` entries moved
  with it, verbatim.
- **`RELEASING.md`** (new, repo root) is the release process; `docex`'s
  `docex_process.md` keeps only `docex`-development specifics and points to it.
- **`upgrades/`** (new, repo root) holds these guides as a chained tape; the old
  `docex/plans/guides/` is gone.
- **Release tags are now `v<version>`**, not `docex-v<version>`. Old `docex-v*`
  tags remain for history.

## Verification

```bash
cd ~/.claude/jean_baudrillard
cat VERSION                       # → 1.3.0
docker images docex:1.3.0         # present
```

In a fresh Claude session, confirm the two new skills are discoverable
(`doctrine-update`, `project-upgrade`). Their presence confirms the plugin cache
refreshed onto the `1.3.0` snapshot.
