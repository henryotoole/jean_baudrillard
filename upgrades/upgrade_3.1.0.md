---
version: "3.1.0"
severity: minor
kind: incremental
scope: [machine, project]
---

# Upgrading to doctrine 3.1.0

## Summary

A single-feature release (mod 174): `docex check` and `docex merge` now accept
`--slots N`, sharding their defensive test run the same way `docex test --slots N`
already did. See the [changelog](../CHANGELOG.md#310---2026-09-10) for the full
narrative. It is **purely additive** — `--slots 1` (or omitting the flag) is
byte-identical to prior behavior, so no project trips anything on repin and there
is no required project action.

## Machine sync

`git pull` + `setup.sh` handle it: the plugin-cache version bump reinstalls the
skill set, `RESIDENT.md` regenerates, and `doctrine-update` builds the new
`docex:3.1.0` image. No manual machine step. (No skill *description* changed this
release.)

## Project upgrade

Repin to make the capability available; nothing else is required.

```sh
bash ~/.claude/jean_baudrillard/docex_install.sh <project>   # moves docex_version → 3.1.0
cd <project> && ./bin/docex --version                        # prints 3.1.0
```

A green `check`/`merge` on 3.0.x stays green. `--slots N` is opt-in; reach for it
only when a project's gate suite is slow enough that sharding the defensive run
pays for the extra concurrent stacks.

## Doctrine / behavior notes

- **`docex check --slots N` / `docex merge --slots N`** shard the gate's defensive
  test run across a reserved slot band above the `docex test --slots` band
  (`check` → slots `9..16`, `merge` → `17..24`, each `MAX_TEST_SLOTS` wide). Shards
  carry the **logical** `1..N` index in `DOCEX_TEST_SLOT` while the physical band
  slot names compose resource identities, and the fleet reaper reclaims every band
  stack a hard-killed sharded gate leaks. There is a hard limit of 8 slots, as with
  `docex test`. No action; available when you want it.

## Verification

```sh
cd <project> && ./bin/docex --version          # prints 3.1.0
./bin/docex check --slots 2                     # runs a two-stack sharded gate (green as before)
```
