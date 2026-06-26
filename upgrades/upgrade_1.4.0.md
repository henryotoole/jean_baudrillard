---
version: "1.4.0"
severity: minor
kind: incremental
scope: [machine, project]
---

# Upgrading to doctrine 1.4.0

This release adds **opt-in host-resolved git credential passthrough** to the
`docex` shim, for development machines whose git access is brokered by a
`credential.helper` (a helper binary or socket) rather than a static key or
ssh-agent. On such a machine `docex merge` previously died at its first network
op with `could not read Username`, because the helper can't run inside docex's
container. The shim now resolves the credential **on the host** via
`git credential fill` and injects a short-lived `store` entry into the
container. See the [1.4.0 CHANGELOG entry](../CHANGELOG.md) for the full
description.

The change is **shim-only** — no `docex` `src/` change and a byte-identical
image. It is **fully backward-compatible**: with the opt-in signal unset the
shim behaves byte-for-byte as before, so **nothing breaks if a project lags**.

## Machine sync

Run the **`doctrine-update`** skill (or do it by hand): `git pull` in
`~/.claude/jean_baudrillard`, then `bash setup.sh`. That single run lands
everything machine-side:

- **The canonical shim is updated** in the repo (`docex/bin/docex`). Projects
  pick it up when they re-run `docex_install.sh` (see below) — the machine pull
  alone does not rewrite any project's `./bin/docex`.
- **`docex:1.4.0` is (re)built** if absent. `docex`'s code did not change from
  `1.3.x`, so this is a byte-identical rebuild apart from the embedded version —
  it exists only to keep the *doctrine version ⟺ `docex` image* invariant.
- **`RESIDENT.md` is regenerated** from `stratum: resident` frontmatter. No
  resident-stratum files changed this release, so expect a no-op.

## Project upgrade

A project adopts the new shim — and repins to `1.4.0` — by re-running the
installer from the project root:

```bash
bash ~/.claude/jean_baudrillard/docex_install.sh .
```

This copies the updated shim to `./bin/docex` and writes `docex_version: 1.4.0`
into `project.yml`. Both writes are idempotent.

This step is **only necessary if** the project's development machine brokers git
through a credential helper and you want the passthrough. To enable it, the
**environment** (e.g. a dev-box image) sets `DOCEX_GIT_CREDENTIAL_PASSTHROUGH`;
the project repo never sets it. With the variable unset the updated shim is a
complete no-op relative to the old one, so repinning carries no behavior risk.

No recompile, redeploy, or data migration is involved.

## Doctrine / behavior notes

- The shim is now explicitly documented as **version-independent and kept
  additive/backward-compatible** (`docex.md` § Project Installation,
  `docex/plans/core/masterplan.md` § The Shim) — one shim serves every `docex`
  version, and a newer shim is tolerated by an image of any version. This
  formalizes existing practice; it is not a new constraint on projects.
- `credentials.md` § Git Host Credentials now covers the credential-helper case
  alongside the static key/agent case.

## Verification

```bash
cd ~/.claude/jean_baudrillard
cat VERSION                       # → 1.4.0
docker images docex:1.4.0         # present
```

On a machine that uses the passthrough, with `DOCEX_GIT_CREDENTIAL_PASSTHROUGH`
set in the environment and an `https` `origin`, a `docex` command that touches
the network (e.g. `merge`) prints `docex: using host-resolved git credentials
for <host>` to stderr and succeeds where it previously failed with
`could not read Username`. With the variable unset, behavior is unchanged.
