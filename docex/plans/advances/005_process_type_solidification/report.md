# Advance 005 — Report

**Target cut: 1.7.0.** Thirteen mods (112–124), two recons against real AWS, one
`cohere` audit, and two full smoke walks. Status at handoff: **ready to cut.**

## Goals — outcomes

**Goal 1 — the elastic consumer reconcile reads durable state.** Achieved, but
not on the first attempt; see [The reconcile, three times](#the-reconcile-three-times).
The shipped trigger compares the consumer's PRIMARY deployment `createdAt`
against the target's Cloud Map `CreateDate` with a 60 s margin, and fires when a
consumer's deployment age is unreadable. Both verdicts — fire and skip — were
observed on `prod`.

**Goal 2 — one relation, `uses`; project-level startup ordering retired.**
Achieved. `depends_on` and `consumes` merged; rules 24 and 6 retired as
tombstones; the compose ordering emission deleted outright. The proof is a grep:
across both smoke projects' compiled output, every `depends_on:` block sits on an
`-exec` service, and `appdb` gates at `service_healthy` in every env. The exec
gate is now the only ordering emission in existence, and it held on a genuinely
cold stack.

**Goal 3 — `role: scheduler` retired; the clock is a core service.** Achieved.
`cron.py`, the Ofelia emitter, the `scheduled_task` destination, the
EventBridge path and the scheduler IAM role are deleted; `role: clock` compiles
to an ordinary long-running service on both foundations. `scheduler.md` deleted,
`clock.md` written in its place. The clock was observed firing, deferring, and
being drained by a worker — on one shared job uuid — on both foundations.

**Goal 4 — coherent release, proven on both foundations.** Achieved. Six-artifact
alignment verified with evidence per artifact; `cohere` run and its 27 findings
fixed; both walks green through prod release, rollback and teardown; the AWS
account verified empty.

## The reconcile, three times

The advance's most instructive thread, and the one that cost the most.

1. **Mod 109 (inherited)** snapshotted the namespace before the apply and
   diffed after. Correct on the normal path and free on code-only releases, but
   an interrupted release left a permanently broken env and exited 0.
2. **Mod 114** replaced the snapshot with two durable timestamps — consumer task
   `startedAt` vs. Cloud Map `CreateDate`. **It could never fire.** Recon 1 had
   measured that `CreateDate` is stamped at ECS *service* creation, before any
   task exists; sarge folded that into the design record as "this strengthens the
   fix," which is exactly backwards — it makes the comparison unsatisfiable. The
   elastic walk shipped a 503 fan-out on `prod` that three clean releases neither
   detected nor repaired.
3. **Mod 123** fixed the operand after **Recon 2** established the mechanism: a
   Service Connect Envoy identifies to xDS by **task-set ARN**, so the resolvable
   name set is frozen at *deployment* creation and a task replaced inside the same
   deployment inherits the stale set — 47 probes over 8 minutes, zero resolutions.
   Task timestamps are irrelevant. Recon 2 also bracketed the boundary to
   `(createdAt − 11.6 s, createdAt + 2.4 s]`, which is what the 60 s margin
   absorbs.

**The lesson worth keeping:** Recon 1's finding was correct and the inference
drawn from it was wrong, in the same sentence. A measurement does not protect you
from the conclusion you attach to it.

## The recurring defect

One failure shape appeared, independently, at least **eight** times: *something
that could not answer reported zero, and zero read as clean.*

- `verify_clean.sh` on fixed: no auth header, wrong `Accept` for OCI indexes, a
  service loop that could not see repos retired by a rename — 30 leaked tags
  while it printed `OK`, across several prior releases.
- `verify_clean.sh` on elastic: 21 swallowing query sites, two presence checks
  that could not distinguish *absent* from *call failed*, no credential
  preflight. Expired credentials alone made all ~20 checks report `OK` and exit
  0 — on the gate that certifies an account has stopped billing.
- A `mark_fail` lost inside a command substitution; a git pathspec that matched
  nothing and produced a vacuous PASS; a `check()` helper that reported `OK`
  three times with the docker daemon unreachable.
- And in the doctrine itself: `clock.md` describing a `docex check` capability
  nothing implemented.

The remedy is now written into the seeds and into `test_projects.md`: **a
verification step's pass is worthless until the step has been observed failing.**
`verify_clean.sh` ships with six failure proofs, each demonstrated red then green,
plus a control that reconstructs the old helper and watches it report clean while
blind.

## Unplanned work admitted deliberately

- **Mod 119** — `docex build` leaked disk without bound: the dev container wrote
  root-owned `.pyc` into `dist/`, the host uid could not unlink it, and pytest's
  retention `rm_rf` then abandoned whole roots. 30 GB in `/tmp`, first presenting
  as unrelated `tofu validate` failures on `no space left on device`. Fixed; a
  full integration run now costs nothing measurable.
- **Mods 122–124** — smoke-walk findings, including the two `verify_clean.sh`
  repairs above.

## Deferred to advance 006

- `docex preinfra development` should probe the registry's
  `storage.delete.enabled` (`_advance_006_preinfra_registry_delete_check.md`).
- `linkcheck.py` cannot simply be widened to reach the seed trees
  (`_advance_006_linkcheck_scope.md`).
- `docex-edit` declares `type: thread` with no thread body
  (`_advance_006_skill_body_conformance.md`).
- Whether "a clock's loop must not exit on a failed fire" becomes doctrine.
- Whether `find` in the dev stage earns a doctrine requirement plus a `check`
  gate, alongside `curl`.

## State at handoff

- Version artifacts staged at **1.7.0**; `docex:1.7.0` built locally; both smoke
  projects repinned and their inner repos clean with tags at HEAD.
- **Unit 1009, integration 20/0.** `linkcheck` and the example-compile harness
  both green and both now shipped as executors.
- `upgrades/upgrade_2.0.0.md` is complete and shippable; its fragment banner and
  `status:` frontmatter are gone.
- AWS account `256071447730` verified empty, twice, by a `verify_clean.sh` that
  has been shown capable of failing.

**Remaining, and the operator's per `RELEASING.md`:** roll `[Unreleased]` →
`[1.7.0]`, commit, tag `v1.7.0`, rebuild the image on the tagged commit, push.

## One process incident

A killed session left a **detached** `docex release stage` running with nobody
driving it; it later fired its own `release prod`, won the tofu state lock, and
made a concurrently-launched walk fail closed. Nothing was lost — the orphan's
apply was adopted as the D.11 evidence — but the incident is the same failure the
fixed walk had already documented: *the tooling severs the session and the
container keeps running.* It also, accidentally, proved `minted-if-absent`
correct: `POSTGRES_PASSWORD` stayed at Version 1 through two concurrent releases,
where a double-mint would have locked `prod` out of its own database.
