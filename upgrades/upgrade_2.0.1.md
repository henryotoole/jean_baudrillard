---
version: "2.0.1"
severity: patch
kind: incremental
scope: [machine, project]
---

# Upgrading to doctrine 2.0.1

Two bug fixes in the git-facing pipeline; see the
[2.0.1 CHANGELOG entry](../CHANGELOG.md). The load-bearing one lives in the
**version-independent `docex` shim** (`bin/docex`), so — unlike an ordinary release — it
reaches a project only when the shim is recopied, not when the `docex_version` pin moves.
No `infra.yml`, CICL, or contract change.

## Machine sync

Run **`doctrine-update`** (or by hand): `git pull` in `~/.claude/jean_baudrillard`, then
`bash setup.sh`. That builds `docex:2.0.1` (a real rebuild — `docex` source changed:
`pipeline/check.py`) and regenerates `RESIDENT.md` (no resident-stratum change expected).

## Project upgrade

### Recopy the shim (this is the actual fix)

    bash ~/.claude/jean_baudrillard/docex_install.sh .

This repins `project.yml` to `2.0.1` **and** overwrites `bin/docex` with the fixed shim —
the latter carries the credential fix. Re-run it in **every** project whose box brokers git
through a path-scoped credential helper (`DOCEX_GIT_CREDENTIAL_PASSTHROUGH` set — e.g.
Periscope runner boxes). Projects on static SSH keys or agents are unaffected by the shim
fix but should repin for hygiene.

No recompile or redeploy is required — the fixes are in the shim and in `docex check`,
neither of which changes emitted infrastructure.

## Doctrine / behavior notes

- The shim now supports **path-scoped** git credential helpers (per-repo brokers), per
  [`credentials.md § Git Host Credentials`](../doctrine/infrastructure/credentials.md#git-host-credentials).
- `docex check` no longer reports success on a git-fetch failure; it fails the same way
  `docex merge` does, so a green `check` again means the pipeline can proceed.

## Verification

    # The shim carries the fix.
    grep -n "useHttpPath" ./bin/docex   # want GIT_CONFIG_VALUE_2=true and the responder's -c ...=true

    # On a passthrough box, check reaches the network without the pathless-cred failure,
    # and no longer warns-and-continues past a fetch failure.
    ./bin/docex check
