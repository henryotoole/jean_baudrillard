# Advance 009 — Test Overhaul: Report

**Branch:** `advance_009_test_overhaul` · **Status:** all mod work + close-out complete; merge + release deferred (offered to the operator).

This advance reshaped how docex runs tests. It touched two layers: docex's own **source** (real mod cycles) and the **doctrine prose** docex implements (the doctrine is docex's upstream spec, not its own core docs). Every mod landed the doctrine-text amendments for the systemic change it implemented; a `cohere` pass validated cross-file consistency at close-out, and `project-cohere` reconciled docex's own core docs.

## Goals — all five delivered

| Goal | Delivered by | Outcome |
| ---- | ------------ | ------- |
| **1** — long test runs decoupled from call limits (async, re-attachable) | Mod 148 | `docex test` is a durable job on a container vessel; a killed monitor leaves the run alive and re-attachable via `docex job ls`/`wait`; deterministic-name lock + self-heal reaper. |
| **2** — a blessed fast inner loop | Mods 147, 151 | Two-shim contract (`test_unit.sh`/`test_integration.sh`); `docex test unit [subset]` runs no-stack; `docex test integration [subset]` stack-backed; `DOCEX_TEST_SELECTOR` injection. |
| **3** — CI/CD stops paying wasted test time | Mods 146, 150 | `merge` `git ls-remote` auth preflight (fast-fail, no build/test); unbuffered output; `check` records `.docex/checks/` provenance and `merge` skips its redundant defensive recheck when nothing moved. |
| **4** — integration tier shards across parallel slots | Mods 152, 153, 154, 155 | The env-agnostic slot primitive (`_s{k}` namespaces every physical name; slot 1 byte-identical); `test`'s web network re-tiered to a per-slot env bridge; `docex test --slots N` (unit once + integration sharded via `DOCEX_TEST_SLOT`/`_SLOTS`); fleet reaper; the `check`/`merge` reserved-slot band closes the `--project-name` DB-volume collision. |
| **5** — test scope is a policy-governed choice | Mod 156 | "Iterate scoped, close full; advance closes full; CI/CD always full; no computed selector" encoded in `modifications.md`, `advance.md`, `cicd.md`, both agent defs, and the `testing` skill. |

## Mod sequence (docex mods 146–157)

- **146** — merge QoL (F1): `git ls-remote origin` auth preflight; `PYTHONUNBUFFERED=1`.
- **147** — unit/integration two-shim contract (SC1): `test.sh` → `test_unit.sh` + `test_integration.sh`; contract folds into integration; the 5 conceptual tiers map onto 2 execution classes; fixtures migrated to `tests/{unit,integration}/`.
- **148** — the `job` substrate keystone (F3/SC3): `src/docex/jobs/` (record/vessel/reaper/commands); `.docex/runs/<id>/` handles; atomic `exit` file; `docex job ls|status|wait|logs|result`; `--detach`; container vessel with name-as-lock; single-run reaper.
- **149** — `check`/`merge` onto the job substrate (SC3): both become durable jobs on the same `ContainerVessel` (the "host-process vessel" of the pre-plan proved incoherent under DooD — see Deviations); per-command locks; `merge --detach` + credential-passthrough fail-fast.
- **150** — recheck-skip provenance (F2/SC4): `.docex/checks/latest.json`; commit-based skip predicate; any-staleness-forces-full-recheck rule.
- **151** — scoped runs + two modes (F5): `docex test unit`/`integration [subset]`; the `DOCEX_TEST_SELECTOR` contract.
- **152** — the env-agnostic slot primitive (SC2): `compile_env(slot=k)`/`compile_slot`; `_s{k}` on every physical name; slot>1 output to `.docex/slots/`; the four-env → slot-axis doctrine amendment.
- **153** — re-tier the `test` web network (F7 §4): env-tier per-slot non-external bridge; `test` has no projinfra dependency; "all four `-web`" → "all three".
- **154** — `docex test --slots N` orchestration + fleet reaper + shard injection (F7): unit-once + integration sharded N ways; `DOCEX_TEST_SLOT`/`_SLOTS`; fleet reaper; three slot-aware seams.
- **155** — the reserved-slot band (SC4): `MAX_TEST_SLOTS=8`, `CHECK_SLOT=9`, `MERGE_SLOT=10`; closes the `check --project-name` DB-volume collision.
- **156** — test-selection policy (F6/SC5): prose across doctrine + agent defs + skill.
- **157** — fix the vessel entrypoint doubling (a close-out blocker): the container vessel died on launch (`docex docex __run-job` → "unknown command 'docex'", exit 64) because the vessel command re-included `docex` on top of the cloned image's `ENTRYPOINT ["docex"]` — so **every** durable-job path (`test`/`check`/`merge`, foreground and `--detach`, and `--slots N`) was broken end-to-end, with only the synchronous `docex test unit` lane escaping. Fixed by making the entrypoint explicit at the `run_detached` boundary (`--entrypoint docex` + `command=["__run-job", <id>]`), and — the crux — closed the coverage gap with a real-docex-image vessel integration test (fresh build into a dedicated tag, proven to fail on the bug / pass on the fix).

## Plan deviations (per Advance process step 3 — plans change)

1. **SC3 D2 vessel taxonomy amended (Mod 149).** The pre-plan's "container vessel for `test`, host-process vessel for `check`/`merge`" was found incoherent under DooD (the foreground docex container dies with the shim call, and an in-container docex can spawn only a container over the socket — never a durable host process). Collapsed to **one `ContainerVessel` for every durable job**, with `meta.kind` selecting the body and the reaper's teardown resource. A strict simplification that is also, unlike D2 as written, actually durable.
2. **Wave-3 Mod 9 split into two mods (154 + 155).** The combined F7 orchestration + SC4 check/merge slot-adoption would have breached the context ceiling and spans distinct territory (`orchestrate/`+`jobs/` vs `pipeline/`). Mod 154 shipped SC1/2/3; Mod 155 shipped SC4.
3. **Elastic golden accidental-deletion, repaired (Mod 152).** The byte-identical gate found `test_projects/elastic/infra/output/` had been deleted in the operator's pre-advance commit `fd8c578`. Escalated via field radio; operator confirmed it was **accidental** and asked to **regenerate now**. Mod 152 regenerated it (captured from the pre-slot compiler at the current version, confirmed byte-identical), restoring both-foundation gate coverage.
4. **Flagship blocker found at close-out → injected fix Mod 157.** The hands-on live exercise (close-out step 13) caught what the 1388-green suite could not: the durable-job vessel died on launch (entrypoint doubling), breaking every vessel path end-to-end. The suite missed it because its "real" vessel integration tests stub the vessel with `alpine` + shell one-liners (no `docex` entrypoint, so the doubling can't surface) and the slots test calls `run_test` in-process. Mod 157 fixed it and added the real-docex-image vessel test that closes the gap. **Lesson of record:** an integration test that stubs away the real artifact cannot catch artifact-specific bugs; the durable-job surface now has one test that drives the actual docex image as a vessel.

## Close-out

- **`cohere`** (`4cd73fa`) — doctrine coherency over the 20 amended files. Caught four "four `-web` → three" stragglers the mod sweeps missed (one contradicting its own next line) + wording fixes. Linkcheck 0 broken across 134 files / 586 anchors / 313 citations.
- **`project-cohere`** (`a10f7c8`) — reconciled docex's five core docs. Fixed a `compiler.md` Scope claim (check/merge now reach `compile_slot`), a masterplan "Vessel protocol" over-claim (no such protocol exists in code — reworded to the `vessel_kind` discriminator), and a stale integration-test count (21 → 25).
- **Source hygiene** (`3bc31ce`) — fixed the stale `compile_slot` docstring and removed dead, wrong-separator `_network_name`. Suite green (1388 passed).
- **Inner-fixture reconciliation** — the `test_projects/{fixed,elastic}` inner repos (the authoritative history `check`/`merge`/`containerize` introspect) were dirty because the advance committed fixture changes to the outer repo but never the inner repos (inner-first cadence was skipped). Reconciled per `test_projects.md`: one catch-up commit each, same-version tag force-moved to HEAD (fixed `v0.0.21`@`08dca74`, elastic `v0.0.25`@`aebe6bb`, both clean/on-main). No version bump — repinning to the new docex version is release-time work.
- **Verify** — full suite green (1388 passed, 26 deselected after Mod 157), including real-docker integration tests exercising the detached-container→exit-file→`job wait` path, the check-job vessel, the single-slot web bridge over HTTP, the `--slots 2` isolation, and (new) the real-docex-image vessel. The hands-on live exercise (close-out step 13) found the Mod-157 blocker on its first pass; after the fix, a **re-run confirmed all four flagship surfaces PASS end-to-end through the real `docex` CLI**: `docex test unit` (no stack), `docex test --detach` + `job wait` (vessel runs the body, returns real exit), the **killed-monitor re-attach** (hard-killed the host shim *and* the monitor container — the vessel survived, ran to completion, tore down its own stack, and `job wait` re-attached to the real exit 0, no re-run, no 75-timeout), and `docex test --slots 2` (two isolated stacks with `_s2` on containers/networks/volumes, per-slot `DOCEX_TEST_SLOT`/`_SLOTS`, integration sharded 2+3, unit once, reaped clean). All scratch state cleaned up; committed fixtures and outer repo untouched.

## Carried forward for the release (out of scope here — flag at release time)

1. **Breaking contract change** — the two-shim split means every downstream project must ship `test_unit.sh`/`test_integration.sh`. Needs a **project-upgrade guide** and a **doctrine-wide version bump**.
2. **`.docex/` gitignore for pre-056 installs** — new projects + the smoke seeds already ignore `.docex/`; pre-056 existing installs need it added. Deliberately NOT folded into `docex_install.sh` (kept scaffolding-free); the upgrade guide must include the step.
3. **Fleet-reaper residual edge (Q3, accepted)** — a failed higher-numbered slot can persist across a smaller-`N` run until an `N≥k` run or manual teardown (documented as an accepted property). Options (b) "max-slots-ever sweep" / (c) "enumerate test projects by label" noted as a cheap future refinement.
4. **The fixtures repin to the new docex version + a real smoke-walk** belong to the release (with the new image built and the fixtures re-tagged).

## Verification of record

The suite is the automated evidence: **1388 passed, 26 deselected**, green on `advance_009_test_overhaul` at `6559837`, including the new real-docker integration coverage. Byte-identical default proven on both foundations (the slot primitive's slot-1 output is diff-identical to pre-advance). The hands-on live re-verify is the end-to-end evidence the suite alone could not provide — see § Close-out. Inner `test_projects` repos reconciled and clean (fixed `v0.0.21`, elastic `v0.0.25`, tags at HEAD).
