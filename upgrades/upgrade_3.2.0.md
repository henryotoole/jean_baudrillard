---
version: "3.2.0"
severity: minor
kind: incremental
scope: [machine, project]
---

# Upgrading to doctrine 3.2.0

## Summary

The advance-014 release. Two reinforcing threads: a new **`docex report`**
command that visualizes where a project's documentation and source-code *token
weight* falls, and the **`docex docs cxt_groups`** command gaining two
grouping knobs. Alongside, the doc-refine / cohere **skills were retired in
favor of agents**, and an exec-service **network-leak fix** (mod 178) landed.
See the [changelog](../CHANGELOG.md#320---2026-10-05) for the full narrative.

Everything that touches a project is **additive or forward-compatible** — no
project trips anything on repin, and there is no required project action beyond
repinning to make the new capabilities available.

## Machine sync

`git pull` + `setup.sh` handle the bulk: the plugin-cache version bump
reinstalls the skill set — which **removes the three retired skills**
(`doc-refine`, `doc-refine-orchestration`, `project-cohere`) from the plugin
cache and lands the new doc-edit agents — `RESIDENT.md` regenerates, and
`doctrine-update` builds the new `docex:3.2.0` image.

One **optional manual host step** (needed only if you shard with `docex test
/ check / merge --slots N` on this dev host): apply the Docker
`default-address-pools` stanza to `/etc/docker/daemon.json` and restart the
daemon, per [`fixed_master_network.md § The Docker Address Pool`](../doctrine/infrastructure/preinfra/fixed_master_network.md#the-docker-address-pool).
Without it a high `--slots` count can exhaust Docker's default address pool.
This is a one-time dev-host config, unrelated to any single project.

## Project upgrade

Repin to make the new capabilities available; nothing else is required.

```sh
bash ~/.claude/jean_baudrillard/docex_install.sh <project>   # moves docex_version → 3.2.0
cd <project> && ./bin/docex --version                        # prints 3.2.0
```

One compile-output change to be aware of (mod 178): a codebase whose **exec
service has no network membership** (a web-only codebase) now compiles its
exec service to `network_mode: none` instead of silently joining Compose's
undeclared `<project>_default` network. This is the fix for a `--slots`
address-pool leak and is forward-compatible — the exec service never legitimately
used that default network. A codebase whose exec service *does* declare networks
is byte-identical to before. Recompile (`./bin/docex compile`) and the change
appears on its own; no `infra.yml` edit is required.

## Doctrine / behavior notes

- **`docex report <type> [--format data|full]`** is new. The one shipped type,
  `docs`, buckets documentation and source-code token weight; `--format data`
  emits deterministic JSON (LLM-friendly), `--format full` (the default)
  composes a self-contained HTML treemap report (operator-friendly). See
  [`docex.md § report`](../doctrine/infrastructure/docex.md#report).
- **`docex docs cxt_groups`** gains `--depth {design_docs|code_level}` (mirrors
  `docex docs linkmap <depth>`) and `--optimize {tokens|module_integrity}`.
  Both defaults (`code_level`, `tokens`) reproduce prior output byte-for-byte,
  so existing callers are unaffected. See
  [`docex.md § docs`](../doctrine/infrastructure/docex.md#docs).
- **Doc-editing moved from skills to agents.** The retired `doc-refine`,
  `doc-refine-orchestration`, and `project-cohere` skills are replaced by the
  `doc-edit-orchestrator` (corporal), `doc-refiner`, and `doc-coherer` (private)
  agents. If you drove doc passes by invoking those skills, drive them through
  the agents instead — the orchestrator agent takes the same "edit-pass type +
  change start-point" inputs.

## Verification

```sh
cd <project> && ./bin/docex --version              # prints 3.2.0
./bin/docex report docs --format data | head       # well-formed JSON buckets
./bin/docex docs cxt_groups 100000 all --depth design_docs   # design-doc-only groups
```
