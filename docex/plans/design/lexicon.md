# Project Lexicon

Terms load-bearing to `docex`'s own design. Doctrine-wide vocabulary (foundation,
environment, core/backing service, preinfra/projinfra/envinfra, TTE, CICL, transfer
tables, …) is defined once in the doctrine
[`lexicon.md`](../../../doctrine/lexicon.md) and not restated here; this file covers only
the terms that are specific to how `docex` is built.

| Word | Definition |
| ---- | ---------- |
| Shim | The ~10-line, version-independent `./bin/docex` bash script checked into every project. Reads the `docex_version` pin and runs the pinned image with the full mount set. See [`specifics/the_shim.md`](./specifics/the_shim.md). |
| DooD | Docker-outside-of-Docker: the `docex` container runs the `docker` CLI against the **host** daemon over a mounted socket — no nested daemon, no `--privileged`. See [`concepts_and_decisions.md § Docker-outside-of-Docker`](./concepts_and_decisions.md#docker-outside-of-docker). |
| Durable job | A long-running command (`test` / `check` / `merge`) whose run outlives the invoking call, executed in a detached sibling container with an on-disk run record. See [`specifics/subcommand_surface.md § Durable jobs`](./specifics/subcommand_surface.md#durable-jobs-the-job-substrate). |
| Vessel | The single container kind (`ContainerVessel`) that runs a durable job — a detached, deterministically-named, non-`--rm` sibling docex container cloned from the foreground container's own spec. |
| Reaper | The single-run self-heal that reclaims the resource an orphaned (hard-killed) durable job leaked, keyed off the run record's `meta.kind`. |
| Slot | A per-run-isolated env stack used to shard the test suite (`--slots N`) or to keep `check`/`merge` defensive test stacks name-disjoint. Distinct from the doctrine `test`-env slot only in that these are docex-assigned reserved constants. |
| Vessel lock | The deterministic vessel **name** used as a per-command mutex (no flock): a second run on the same `(project, kind)` scope loses the `docker run --name` create race and refuses. |
| Six-artifact alignment | The rule that a change touching `docex` must keep the doctrine prose, `docex/plans/design/**`, the transfer tables, `src/`, `tests/`, and `doctrine_excerpts/` aligned. See [`specifics/docex_process.md § Additional Artifacts`](./specifics/docex_process.md#additional-artifacts). |
| Provider set | The core services a project declares `surfaces:` on — exactly the set for which `docex check` requires a contract. See [`specifics/subcommand_surface.md § The contract and shim gates`](./specifics/subcommand_surface.md#the-contract-and-shim-gates). |
