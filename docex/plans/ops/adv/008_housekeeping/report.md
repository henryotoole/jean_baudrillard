# Advance 008 — Housekeeping — Report

A backlog-clearing advance: twelve triaged briefs delivered across eight mods
(137–144) plus a cohere fix-pass (145), on branch `advance_008_housekeeping` off
`main` tip `0049e84` ("Cut 2.0.1"). **Cut target: 2.1.0 (minor).**

## Outcome by goal

**Goal 1 — docex emits/validates what the doctrine says.** ✅ (edits)
- `object_store` `version:` now pins the minio image tag; `:latest` gone; a missing
  `version` on an engine that has the field is a compile error
  (`rule_version_required`, `s3` exempt structurally). (137)
- `docex check` fails a contract below the spec floor (OpenAPI 3.2 / AsyncAPI 3.0)
  via `_gate_contract_spec_version` — the 10th check gate. (137)
- The env subdomain is derived once (`compile.env_subdomain_for`); both readers
  route through it, no hand-rolled copy remains. (137)
- A non-DNS-label project name is rejected at load (`_PROJECT_NAME_RE`);
  `project_dns_label` is threaded into HCL so the four template sites stop
  disagreeing (a mixed-case name previously compiled to two spellings of its own
  project segment — a case-sensitive-AWS split-brain). (138)

**Goal 2 — QA instruments and excerpts tell the truth.** ✅
- `linkcheck` gained file-as-root + a suppression marker; `CHANGELOG.md`/`README.md`/
  `RELEASING.md` joined the default scan; the target-vs-claim rule lives once in
  `RELEASING.md`, cited from `upgrades/README.md`. (139)
- The 60 misfiled compile tests moved to `tests/unit/`; `test_collection_partition.py`
  asserts the buckets partition the suite (fails on either misfiling mode). (139)
- All 18 `doctrine_excerpts/` entries rewritten against current doctrine (`vpc`
  retired, five resource entries added, two network keys renamed); every
  `Doctrine reference:` footer bounded (repo-wide `unbounded` 25→10); the artifact
  gained its first automated consumer (`test_doctrine_excerpts_index.py`). (140)
  — The linkcheck-*enumerate* half of the citation brief was deliberately NOT
  folded in; it stays booked (see Follow-ups).

**Goal 3 — feature and process gaps.** ✅
- `docex secrets` value fingerprints: a `FINGERPRINT` column on `status` and a
  cross-env `fingerprints` matrix, salted + non-revealing, scoped to the secret
  category, with a value-blind-leak test. (141)
- Inception establishes an empty `main` on origin before branching, so the first
  `docex merge` takes the normal rebase path; `merge.py`'s dead seed-trunk path
  removed and replaced with a clear precondition failure. (142)
- The two deferred CICL scope decisions: `defaults.elastic` cleaned + guarded
  (`rule_elastic_defaults_unread_key`); rule 32 left as-is with `healthchecks.md`
  prose softened to match. (138)

**Goal 4 — the two verification-gated infra defects.** ✅ EDITS DONE, BOTH GATES VERIFIED ON REAL INFRA
- Preinfra dedicated traefiks got a `docex.project` discovery constraint + matching
  labels (`container_registry.md`, `telemetry_preinfra.md`) — doctrine-only. (143)
- The fixed release playbook pulls without starting, so migrate runs before up
  (`playbook.yml.j2`), with a test asserting the pull task starts nothing. (144)
- **Both gates require the operator-supervised pre-cut walk** — see below.
- **RESOLVED (2026-08-24):** Mod 143 verified on the live preinfra host (registry-traefik constrained; foreign ACME discovery stopped; registry cert intact). Mod 144 verified by the **fixed** smoke walk (migrate completed before the app containers' StartedAt on stage AND prod; clock first-fire clean). Both **mandatory smoke walks are GREEN and torn down clean** — the fixed walk (`fixed_walk_mod144_evidence.md`) and the elastic walk (`elastic_walk_evidence.md`, which additionally verified Mod 138's HCL `project_dns_label` threading + `defaults.elastic` guard on real AWS output). `verify_clean` exit 0 on both; no AWS spend lingering.

## Verification state
- Test suite: **1254 passed, 21 deselected** (default) / **21 passed, 1254
  deselected** (integration, run alone). Baseline at plan time was 1204/21; the net
  +50 are new tests (nothing removed but the seed-trunk tests, replaced).
- `linkcheck`: green (130+ files incl. the three repo-root files).
- `verify_examples.py`: green (mod 137's new rule had made `cicl.md`'s flagship
  example uncompilable — fixed in 145).
- Both cohere audits ran at close-out (see Process notes).

## Deferred — require the operator-supervised pre-cut walk (both foundations mandatory)
1. **Mod 143 gate** — on the live preinfra host: a dedicated traefik must open ACME
   orders for ONLY its own host(s); the `Cannot retrieve the ACME challenge` spam /
   LE 429 burn on project traefiks must stop. The immediate host mitigation
   (editing `/opt/docex-preinfra/.../traefik.yml` + labels + restart) is applied
   here too — it was deliberately NOT applied early (operator ruling: a week of
   existing pollution, a few more hours is immaterial).
2. **Mod 144 gate** — a **fixed** smoke walk: verify by comparing container
   `StartedAt` against migration completion (migrate must precede up) and that a
   first release's clock fire raises no `UndefinedTable`. A green playbook proves
   nothing.
Once verified, retire the "pending walk verification" qualifier on the
`migrations.md` note (currently "✔ Fixed by mod 144 — pending walk verification").

## Skill gates — deferred to the cut (operator ruling)
No mod changed a skill *description*, and linkcheck confirms no skill's doctrine
pointers dangle, so the `skill-iteration` trigger-eval suite that RELEASING already
runs at cut time is the gate. An outcome eval of `configurable-vars` (whose routed
doctrine gained the fingerprint feature) is advisable there.

## Hand-off for the cut (2.1.0, per RELEASING.md)
- The working tree carries **operator WIP** (`RELEASING.md`, a `floating_todo/`
  reorg, an untracked `009_test_overhaul/`) — commit or set aside for a clean cut tree.
- 2.1.0 is **minor**: it introduces two new hard rejections (non-DNS-label project
  name; `object_store` without `version`) that are breaking *in principle* but
  enforce rules the doctrine already stated. The upgrade guide must state this and
  give the grep-checks (no capitalized project name; no `object_store` without
  `version`). See the plan header.
- Minor cut ⇒ both smoke walks mandatory (`test_projects.md` Lifecycle) — which is
  where the two gates above are satisfied.

## Process notes (worth carrying forward)
- **Mod drift-checks missed doctrine EXAMPLES, cohere caught them.** Three of the
  advance's own mods (137, 138, 141) updated a doctrine *claim* or added a *rule*
  but left a doctrine *example* that then violated it — the `cicl.md` flagship
  `infra.yml` (uncompilable under the new version rule), the `transfer_tables.md`
  walking example (`defaults.elastic` keys the new guard rejects), and
  `config_and_secrets.md`'s "no hash" claim (contradicted by the fingerprint
  feature). A drift-check that reads the changed *rule* but not the doctrine's own
  *worked examples* is structurally blind to this class. The lesson: after adding
  or tightening a rule, grep the doctrine's examples for something the rule now
  rejects — and `verify_examples.py` is the mechanical backstop that makes the
  `cicl.md` case loud rather than silent.
- **The session survived a mid-mod network death** (during mod 137) with no lost
  work — the implementation and design-done commit were intact on disk, and the
  cycle's reviewer tail (docs + final commit) was completed on recovery.
- **A concurrent operator reorg of `floating_todo/` ran alongside mods 141–145**
  without contamination, because every corporal staged explicit paths (never
  `git add -A`) and each commit was audited for stray WIP.
