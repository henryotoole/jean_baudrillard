# Advance 008 — Housekeeping

A backlog-clearing advance. Its scope is the twelve briefs in
[`references/`](./references/) — deferred defects, small correctness fixes, two
verification-gated infra bugs, one feature, and two deferred doctrine decisions,
all triaged forward from the `floating_todo` set. Each mod below owns one or more
of those briefs; the brief is the design record and this plan does not restate it.
Every open decision was resolved at plan review — the rulings are recorded per mod
and collected at the end.

Unlike advances 005–007, nothing here is one large feature — it is many small,
mostly-independent items. Mods are bundled by subsystem and by whether they need
round-trip verification, per the rule that a brief earns its **own** mod only if
it is a genuine feature or needs real-machine round-tripping; everything else is
bundled with its neighbours.

**Cut target:** **2.1.0** (minor). Two rulings below introduce **new hard
rejections** — Mod 138 rejects a non-DNS-label project name, and Mod 137 rejects
an `object_store` with no `version` — which are breaking *in principle* (a config
that compiles today would error). They are treated as minor rather than major
because each merely enforces a rule the doctrine already states (the DNS-label
scheme; `version` "required" in cicl.md § Service Fields), closing an enforcement
gap rather than changing the contract, and no current project trips either. The
upgrade guide must state this explicitly and give the grep-check that proves it
(no capitalized project name; no `object_store` without `version`). Mod 141 adds
new behaviour, also minor.

**Baseline at plan time:** branch `advance_008_housekeeping` off the current `main`
tip (`0049e84`, "Cut 2.0.1"). Suite counts **re-derived** at plan time rather than
inherited (this advance's own
[`misfiled_compile_tests.md`](./references/misfiled_compile_tests.md) is exactly
that failure):

| Invocation | Result |
| --- | --- |
| `.venv/bin/python -m pytest tests -q` | **1204 passed, 21 deselected** |
| `.venv/bin/python -m pytest tests -q -m integration` | **21 passed, 1204 deselected** |

The two agree in both directions, which is the cross-check
[`docex_process.md § Running the automated tests`](../../core/docex_process.md#running-the-automated-tests)
demands — a bare `pytest` reports a deselect count one short and runs nothing.
Note `python` is not on PATH on this box; the interpreter is `docex/.venv/bin/python`.
`-m integration` runs **alone** (~8 min; it contends for real docker state).

`linkcheck` was **red at setup** and is green as of the pre-flight commit — see
[Setup findings](#setup-findings-pre-flight).

---

# Goals

## Goal 1 — docex emits and validates what the doctrine says

The compiler stops accepting instructions it silently ignores, stops emitting
values it silently defaults, and stops re-deriving one rule in disagreeing places.

### Success Criteria
1. An `object_store` service's `version:` pins the `minio` image tag; `:latest`
   never appears in compiled output; and omitting `version` on a backing engine
   that has one is a compile error (`s3` exempt).
2. `docex check` fails a contract whose declared spec version is below the
   doctrine floor (OpenAPI 3.2, AsyncAPI 3.0).
3. The env-subdomain expression is read from `compiled.subdomain` in every
   consumer; no site hand-derives `<env>.<project>.<apex>`.
4. A capitalized (non-DNS-label) project name is rejected at entry with a clear
   message; `project_dns_label` enters HCL template context so the four sites stop
   disagreeing.

## Goal 2 — the QA instruments and the excerpts tell the truth

The link checker, the pytest layout, and `docex why` stop being able to pass while
wrong.

### Success Criteria
1. `linkcheck` can be pointed at the repo-root files; released-changelog dead
   links are repaired or suppressed; the target-vs-claim rule is stated once in a
   shared place.
2. The 60 fast compile tests are relocated to `tests/unit/`, and a CI guard
   asserts the buckets partition the suite.
3. Every `doctrine_excerpts/` entry matches current doctrine; `index.yml` keys
   reconcile with `shape.md` (the `vpc` key retired); the artifact gains an
   automated consumer.

## Goal 3 — close the named feature and process gaps

### Success Criteria
1. `docex secrets` can fingerprint a value non-revealingly, and a cross-env matrix
   shows propagation/drift.
2. Inception establishes an empty `main` on origin before branching, so the first
   `docex merge` takes the normal rebase path; `merge.py`'s dead seed-trunk path is
   removed.
3. The two deferred CICL scope questions are decided and recorded (see rulings):
   `defaults.elastic` is cleaned + guarded; rule 32 is left as-is with the prose
   aligned to it.

## Goal 4 — fix the two verification-gated infra defects

Both require a real machine to confirm; both are invisible to the suite.

### Success Criteria
1. Preinfra dedicated traefiks discover only their own project — the cross-project
   ACME pollution and LE rate-limit burn stop, verified against the live host.
2. A fixed `stage`/`prod` release migrates **before** the new stack starts,
   verified by timestamps in a fixed smoke walk (not by a green playbook).

---

# Tactical Plan

Mods numbered from **137** (advance 007 ended at 136). Every mod is run by the
`jean-baudrillard:corporal:mod-developer` subagent; per `docex_process.md` there
is no manual-test pause in a `docex` mod cycle.

### Phase 1 — docex correctness (unit-testable, no round-trip)

1. **Mod 137: emit/validate small fixes.** `corporal`. Bundles three mechanical,
   unit-testable src fixes:
   [`docex_object_store_version_gap.md`](./references/docex_object_store_version_gap.md),
   [`contract_spec_version_ungated.md`](./references/contract_spec_version_ungated.md),
   and [`env_subdomain_fourth_copy.md`](./references/env_subdomain_fourth_copy.md).
   → RULING: object_store — `version` is **required** on any backing engine that
     has one; omitting it is a compile error, `s3` exempt. Pins `minio` from
     `version:`; drops the hardcoded `:latest`.

2. **Mod 138: project-name normalization and two deferred scope decisions.**
   `corporal`.
   [`project_name_dns_label_divergence.md`](./references/project_name_dns_label_divergence.md)
   (the serious one),
   [`inert_elastic_defaults.md`](./references/inert_elastic_defaults.md), and
   [`rule_32_unused_target_port.md`](./references/rule_32_unused_target_port.md).
   → RULING: project name — **reject at entry** (`context.py` / `ProjectManifest`)
     if it is not already a clean DNS label. Chosen over silent normalization
     (which changes deployed resource identity invisibly) and a `check`-time gate.
     Then pass `project_dns_label` into HCL context and retire the four
     re-derivations; add a fixture so the divergence can never pass silently again.
   → RULING: `defaults.elastic` — **Answer A + C**: delete the dead
     `launch_type`/`network_mode` keys AND make compile reject any
     `defaults.elastic` key no renderer reads. (Generic merge — B — rejected as
     over-scoped.)
   → RULING: rule 32 — **leave as-is** (won't-fix; the gap is inert and rescoping
     would newly reject decorative ports for zero correctness gain). Close the
     coherence gap instead by **softening `healthchecks.md § What this doctrine
     does not do`** so its broader prose no longer overstates the rule.

### Phase 2 — QA instruments and docs (no docex behaviour change)

3. **Mod 139: QA instrument hygiene.** `corporal`.
   [`changelog_released_section_link_paths.md`](./references/changelog_released_section_link_paths.md)
   (linkcheck file-as-root + suppression marker + dead-link repair + the
   target-vs-claim rule) and
   [`misfiled_compile_tests.md`](./references/misfiled_compile_tests.md).
   → RULING: misfiled tests — **relocate the 60 to `tests/unit/`** (not re-mark in
     place), plus the partition guard.

4. **Mod 140: `doctrine_excerpts/` overhaul.** `corporal`. The whole-directory
   rewrite of
   [`doctrine_excerpts_overhaul.md`](./references/doctrine_excerpts_overhaul.md) —
   all 18 entries read against their rule of record and rewritten, `index.yml`
   reconciled with `shape.md`, missing entries added, and an automated consumer
   introduced. Its own mod because it is prose authorship at volume, not code.
   → RULING: retire the `vpc` key (no `shape.md` referent; covered by
     `master_network`'s new entry).
   → RULING (added at sergeant setup, operator-approved): **bound every
     `Doctrine reference:` citation** as part of the rewrite, per the restored
     [`unbounded_citation_enumeration.md`](./references/unbounded_citation_enumeration.md).
     `linkcheck` classifies a citation's heading only when the path **and** the `§`
     sit inside one inline-code span; the directory's house style splits them, so
     **15 of 16** citations are counted `unbounded` — file verified, heading never
     checked — and the count is unchanged since mod 133 (measured at setup:
     24 unbounded repo-wide). Mod 140 is rewriting all 16 of those lines anyway, so
     the marginal cost is ~zero and the alternative is an overhaul that leaves the
     check exactly as blind as it found it. **Verify by measurement, not by
     reading:** re-run `linkcheck` and watch `unbounded` fall and `exact` rise by
     the same amount. (The *other* half of that brief — making `linkcheck`
     **enumerate** unbounded citations instead of only counting them — was **not**
     folded in and stays booked.)
   → NOTE: this subsumed two retired briefs (stale-entries, reverse-proxy elastic
     gap); the overhaul is the single owner of every excerpt defect.

### Phase 3 — feature and process

5. **Mod 141: `docex secrets` value fingerprints.** `corporal`. The feature in
   [`secret_fingerprint.md`](./references/secret_fingerprint.md) — a
   `FINGERPRINT` column on `status` and a cross-env `fingerprints` matrix, added to
   the unified `secretsmgmt/engine.py`, scoped to the secret category.

6. **Mod 142: inception establishes an empty `main`.** `corporal`. The inception
   fix in
   [`first_release_merge_bug.md`](./references/first_release_merge_bug.md) —
   `inception.md` PART I creates and pushes an empty `main` before branching.
   → RULING: **remove** `merge.py`'s now-unreachable seed-trunk path as dead code
     (not repair it); `merge` may assume `main` exists.

### Phase 4 — round-trip verification (real machine, run last)

7. **Mod 143: preinfra traefik discovery constraint.** `corporal`.
   [`acme_cert_issue_fixed.md`](./references/acme_cert_issue_fixed.md) — add a
   `docex.project` discovery constraint (and matching label) to the preinfra
   dedicated traefik configs in `container_registry.md` and `telemetry_preinfra.md`.
   → GATE: verify against the live host — a preinfra traefik must open ACME orders
     for **only** its own host(s), and the `Cannot retrieve the ACME challenge`
     spam / LE 429 burn on project traefiks must stop. The immediate host
     mitigation (currently unapplied) is separate from the doctrine edit.

8. **Mod 144: fixed release migration ordering.** `corporal`.
   [`fixed_release_migrates_after_up.md`](./references/fixed_release_migrates_after_up.md)
   — the playbook "Pull all images" task becomes a real pull (no `state: present`),
   plus the test asserting it starts no services.
   → GATE: the fix and a **fixed smoke walk** land together. Verify by comparing
     container `StartedAt` against migration completion and asserting the clock's
     first fire raises no `UndefinedTable` — a green playbook proves nothing.
   → NOTE: retire the known-divergence note in `migrations.md § Stage and Prod on
     Fixed Foundation` (which points at Mod 144's brief) once this lands.

---

# Close-out

1. **Static audits.** `cohere` over the doctrine (RELEASING gates it whenever
   doctrine prose moves — Mods 138/140/143/144 all move it) and one
   `project-cohere` pass over `docex` after the code mods. Triage findings; inject
   a fix-pass mod only if warranted.
2. **Automated tests.** Unit + `pytest -m integration` (alone), against the
   re-derived plan-time baseline.
3. **Skill gates.** Any skill moved by the doctrine edits (candidates:
   `configurable-vars` for Mod 141, `inception` for Mod 142, `preinfra-setup` for
   Mod 143, `cicd-pipeline` for Mod 144) fires `skill-iteration`'s trigger eval,
   plus an outcome eval for any that changed materially.
4. **Smoke walks.** **Both walks are mandatory** (operator ruling at sergeant
   setup) — the cut target is a **minor** (2.1.0), and `test_projects.md`'s
   Lifecycle table requires both foundations green for a minor, so this was never a
   cut-time question. Consequence, folded in now rather than at cut time: Mod 143's
   live-host gate and Mod 144's **fixed** smoke walk are **instrumentation inside
   the mandatory pre-cut walk**, not standalone verification runs — Mod 143 asserts
   its ACME-order-scoping check against the same live preinfra host the walk uses,
   and Mod 144 reads `StartedAt`-vs-migration timestamps during the fixed walk's
   `release stage`/`release prod`. Real AWS, real cost, operator-supervised; the
   plan's largest risk sits here.
   → RULING (ACME host mitigation): **keep with the plan** — the immediate host
     mitigation is **not** applied early. The pollution has run live for over a
     week; a few more hours costs no meaningful additional LE rate-limit burn, and
     the mitigation lands with Mod 143's doctrine edit in Phase 4 as written. The
     mitigation touches shared preinfra serving other projects, so it stays
     operator-supervised with the rest of Phase 4.
5. **Hand back for the cut**, per `RELEASING.md`.

---

# Setup findings (pre-flight)

Found by the sergeant at Setup, before any mod ran. Both trace to the same act:
the plan-prep triage emptied `007_small_edges/` (a booking bin of 23 briefs) into
`008_housekeeping/references/` and `floating_todo/`, and deletion is not
redistribution.

1. **`linkcheck` was red.** Three live markdown links in
   `docex/plans/core/docex_process.md` (:157, :163, :197) pointed at deleted
   briefs. Repaired in the pre-flight commit: two re-pointed at
   `008_housekeeping/references/`, and the third — which cited the *retired*
   `doctrine_excerpts_stale_entries.md` — had its sentence rewritten to name the
   overhaul as sole owner rather than re-pointed at a brief that no longer exists.
   Three further refs outside `linkcheck`'s roots were repaired for the same
   reason (`RELEASING.md`, `skills/cohere/executor/linkcheck.py`'s own docstring,
   `docex/tests/unit/test_worker_role.py`). The ~20 refs under
   `docex/plans/modifications/**` are **out of scope by design** — frozen record —
   and were left alone. Note for **Mod 139**: teaching `linkcheck` file-as-root
   pulls `RELEASING.md` and `CHANGELOG.md` into reach, so verify the repaired
   `RELEASING.md` link and confirm the three `CHANGELOG.md` hits stay suppressed
   as frozen released-section lines.

2. **Seven briefs were deleted with no destination; six were still open work.**
   Each was recovered from `HEAD` and checked against the current tree rather than
   against the changelog:

   | Brief | Verdict | Disposition |
   | --- | --- | --- |
   | `doctrine_tweaks.md` | **DONE** — answered by advance 006's `api_styles` → format table (`cicl.md` `rpc → asyncapi`), mod 125 | correctly deleted |
   | `unbounded_citation_enumeration.md` | OPEN, both halves | → `008/references/`; **in scope** (Mod 140, above) |
   | `merge_changelog_gate_unenforced.md` | OPEN — zero `CHANGELOG` reads in `src/`; both seeds still carry an unrolled `## [Unreleased]` | → `floating_todo/surprise_discovered/` |
   | `project_upgrade_recall_regression.md` | OPEN — and its *mandated first action* (re-measure on the corrected harness) never ran; the only post-fix datum is the disowned load-saturated run | → `floating_todo/surprise_discovered/` |
   | `sarge_full_reading.md` | OPEN — untouched | → `floating_todo/surprise_discovered/` |
   | `test_fixture_base_image_rot.md` | PARTIAL — the process half landed (this plan's own re-derive rule); all four fixture/seed bases still float `python:3.12-slim` while the shipped image pins by digest | → `floating_todo/surprise_discovered/` |
   | `trigger_eval_cwd_confound_run_eval.md` | OPEN — `run_eval.py:89` still passes `cwd=project_root`; only the `RELEASING.md` "gate on `run_suite.py`" mitigation exists | → `floating_todo/surprise_discovered/` |

   Operator ruling: park the five in `floating_todo/surprise_discovered/` for
   later review; they are **not** in this advance's scope and no mod was added for
   them. Recorded here because a deleted brief is a deleted design record, and the
   defect stays real whether or not the record does.

---

# Decisions made at plan review

Recorded so they are not re-litigated mid-advance.

1. **Project name — reject at entry** (Mod 138). Non-DNS-label names fail their
   next compile. Breaking in principle; functions as a bugfix aligning names to
   the doctrine's own DNS-label rule.
2. **`defaults.elastic` — Answer A + C** (Mod 138): delete the dead keys and add a
   fail-loud guard on unread keys.
3. **Rule 32 — leave as-is** (Mod 138): won't-fix; soften `healthchecks.md`'s
   broader prose to match the rule rather than rescope the rule.
4. **object_store — `version` required, `s3` exempt** (Mod 137). Aligns code to
   cicl.md's existing "required" claim; no pinned fallback.
5. **merge seed-trunk path — remove as dead code** (Mod 142), now that inception
   guarantees `origin/main`.
6. **Misfiled compile tests — relocate to `tests/unit/`** (Mod 139), plus the
   partition guard.
7. **`vpc` excerpt — retire the key** (Mod 140); covered by `master_network`.
8. **ACME account email — struck from this advance.** A proper configurable-values
   home is planned but not yet available; the finding is returned to
   `floating_todo/traefik_acme_email_unwired.md` to wait for it.
9. **Bundling grain — keep the bundles as-is** (8 mods). Mods 137/138/139 carry
   more than one brief; not split further. The items are small, 138/139 are
   thematically coherent, and 137's three are independently testable.
10. **Cut version — 2.1.0** (minor; see the rationale and required grep-check in
    the header).

The plan carries no open decisions; it is ready to hand to the sergeant.
