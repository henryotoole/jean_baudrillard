# Advance 006 — Surfaces and Health

Ships in the **unreleased 1.7.0 cut**, alongside advance 005. The design record is
[`surfaces_and_health.md`](./surfaces_and_health.md); it is settled and this plan
does not re-open it. Doctrine steps 3 (load-bearing edits) and 4 (sweep) are
**done** and committed at `9b16937`.

**Baseline at plan time:** branch `006_surfaces_and_health` off `8ffcd02`;
unit suite 1009 passed; `linkcheck doctrine skills` green.

---

# Goals

## Goal 1: `surfaces:` replaces role-derived contract selection

A core service declares a `surfaces:` map; each surface declares `api_styles:`
which resolve to exactly one contract format; each surface compiles to exactly
one contract file. Declaring a surface is what makes a core service a provider.

### Success Criteria

1. `docex compile` accepts a `surfaces:` block and rejects, with a named rule id:
   a surface whose `api_styles` span two formats (rule 29); a surface name that
   fails the service-name pattern (rule 30); a `uses` edge onto a core service
   declaring no surface (rule 31); a directly-addressed `uses` target with no
   `port` (rule 32); a `graphql`/`proto` surface ("format not yet implemented").
2. `docex check` derives the provider set from `surfaces:` alone — the
   `(uses targets) ∪ (web-network services)` union and `_CONTRACT_FORMAT_BY_ROLE`
   / `_FALLBACK_CONTRACT_FORMAT` return zero grep hits in `src/`.
3. Contract paths parse right-anchored on four segments;
   `api.web.rest.openapi.yml` resolves and `api.web.openapi.yml` does not.
4. Both seed projects compile, `check` green, with surfaces declared and their
   four contract files renamed.

## Goal 2: health leaves HTTP

The container probe becomes `./health.sh <service>`; `GET /health` survives only
where a load balancer reads it; the fan-out and everything enforcing it is gone;
`docex` reads liveness and version from the orchestrator.

### Success Criteria

1. Compiled output on both foundations carries `["CMD", "./health.sh", "<svc>"]`
   as every core service's container probe — and **not** on the `-exec` block or
   the `-otelcol` sidecar.
2. `/health/<codebase>/<service>` returns zero hits across `doctrine/`, `docex/src/`,
   `docex/tests/`, and both seed projects. `_gate_health_endpoints` is deleted.
3. A non-`web` core service compiles with no `port` and no `health_check_path`;
   rule 33 rejects a `web`-network service that omits `health_check_path` and a
   non-`web` one that declares it.
4. `docex check`'s `curl` gate fires only for `web`-network core services; its
   fourth codebase shim gate requires `health.sh`.
5. `docex stagetest` fails, before it builds the tester image, when any core
   service is unhealthy or on the wrong version — read from `docker inspect` over
   SSH on fixed and `describe_tasks` on elastic. Demonstrated failing, not only
   passing (advance 005's standing rule).
6. Both seed projects run zero HTTP servers on non-`web` core services; worker and
   clock liveness is a tick file, observed stale-and-failing at least once.

## Goal 3: the 1.7.0 cut stays shippable

### Success Criteria

1. Six-artifact alignment held (doctrine / `plans/core` / `tables` / `src` /
   `tests` / `doctrine_excerpts`), with the `doctrine_excerpts` verdict — including
   any deliberate "no entry" — written into `docex_process.md`.
2. `upgrades/upgrade_1.7.0.md` extended to cover both breaking halves.
3. `PRE_CUT_CHECKLIST.md` boxes B.9, B.10, B.6/B.7, C.8, C.9, D.6, D.9, D.10, D.11
   rewritten against the new model before either walk starts.
4. Unit + integration suites green; both smoke walks green; `cohere` findings
   resolved.

---

# Tactical Plan

Mods are numbered from **125** (advance 005 ended at 124). Every mod cycle is run
by the `jean-baudrillard:corporal:mod-developer` subagent unless noted. Per
`docex_process.md` there is **no manual-test pause** in a `docex` mod cycle.

### Phase 1 — the language (CICL)

1. **Mod 125: `surfaces` in the model, and the rule set.** `corporal`.
   `cicl/model.py`: a `Surface` model, `CoreService.surfaces`, surface names
   validated against `_SERVICE_NAME_RE` (already dot-free, which is what keeps the
   four-segment path parse unambiguous). `cicl/validate.py`:
   `_STANDARD_SERVICE_FIELDS += "surfaces"` (without which every project trips
   `tt_rule_4_undeclared_field`), new rules 29–33, and rule 28 deleted with its
   number tombstoned in the module docstring roster.
   Both files are one territory — the rules are meaningless without the field, and
   `validate_document`'s flat registry makes each rule a one-line registration plus
   one function. Rule 28's deletion rides here rather than with Part II because it
   is 40 lines in this file and its replacement (rule 33) is being written anyway.
   → DECISION (corporal raises in design; sarge rules): **how rule 32 detects
     "directly addressed."** The doctrine states the principle, not a lookup table.
     The strong candidate is *a consumer holding a magic ref to the target's
     `provides` parts* — which rule 7 already walks, so the signal exists and needs
     no new authored field. If that reading does not close, sarge decides between
     it and a style-derived mapping before implementation.
   → NOTE: rule 33 keys on **network membership**, not on role. A `role: web`
     service off the `web` network declares no `health_check_path`.

2. **Mod 126: the check gates.** `corporal`.
   `pipeline/check.py`: delete `_CONTRACT_FORMAT_BY_ROLE`, `_FALLBACK_CONTRACT_FORMAT`,
   `_contract_format_for_role`; add an `api_style → format` map and a
   surface→format resolver; `_parse_contract_filename` 3→4 segments and one
   extension per format; `_gate_contracts` rewritten off `surfaces`;
   `_gate_health_endpoints` **deleted**; `_gate_healthcheck_tooling` narrowed to
   `web`-network services; `_gate_codebase_scripts` gains `health.sh` as the fourth
   shim. Fixture `infra.yml`s gain surfaces and the fixture contracts are renamed.
   The fan-out gate's deletion is pulled forward into this mod on purpose: it
   shares `_parse_contract_filename` with the contract gate, so cutting between
   them would mean shipping a version of the fan-out gate nobody wants.
   `tests/unit/test_contract_health_gates.py` is effectively rewritten (11 tests,
   ~7 die outright); `test_pipeline_check.py`'s gate-roster assertion moves.
   → GATE: after this mod the seed projects will not pass `docex check` until mod
     129 adds their `health.sh`. That is expected and is not a defect.

### Phase 2 — the probe

3. **Mod 127: the probe becomes a command.** `corporal`.
   `tables/roles/{web,worker,clock}.yml`: the container probe moves into
   `defaults` as `["CMD", "./health.sh", "${service}"]` on both foundations;
   `health_check_path` keeps only its `elastic` → `target_group` translation on
   `web` and is removed from `worker`/`clock` entirely. Reword the `provides:`
   comments that justify a port by the fan-out, `magic_refs.py::self_uses_message`,
   and `release.py`'s two Service-Connect strings (the reconcile logic itself does
   not move — only its stated symptom).
   Recon's de-risking finding: the substitution context **already** carries
   `"service"`, so this is a table edit, not an emitter change; `emit/compose.py`
   passes the body through whole and `emit/hcl.py` merges `container_definition`
   blindly. Emitter tests assert the exact literal curl strings and will churn.
   → VERIFY: the emitted probe must land on core-service blocks **only**. The
     `-exec` block and the `-otelcol` sidecar must not inherit it
     ([`exec_service.md`](../../../../doctrine/infrastructure/specifics/exec_service.md)
     is explicit that the exec block has no health check). Assert this with a test,
     not by reading the output.

4. **Mod 128: `stagetest` reads the orchestrator.** `corporal`.
   A foundation-aware liveness/version pre-step ahead of the tester build. This is
   its own mod because it is the advance's only *additive* piece and the only one
   touching two transport abstractions: `AWSClient` needs a new Protocol method
   (`describe_tasks`/`describe_services` — it has neither today) plus a boto3 impl
   plus a `FakeAWSClient` method, and the fixed path must read
   `docker inspect --format` **over SSH** to the deployed host, because on fixed
   `stage`/`prod` do not run on the operator's machine. `__main__::_cmd_stagetest`
   currently constructs only a `DockerClient` and must thread the other two, as
   `_cmd_release` already does. ~250 net new lines across ~6 files; all 7
   `test_pipeline_stagetest.py` tests rewrite (they assert on positional call-tuple
   indices).
   → DECISION (corporal raises): the ECS cluster name is computed identically at
     `release.py:591` and `orchestrate/migrate.py:246`. A third copy is a drift
     surface — lift it to a shared helper rather than copy it.
   → GATE: Success Criterion 2.5 requires the pre-step be **observed failing**.
     Demonstrate red before green, per advance 005's standing rule.

### Phase 3 — the seed projects

Both foundations' `core/` trees are byte-identical by design (audit box B.14
diffs them), so every source edit below is made twice, identically.

5. **Mod 129: seed projects — source, contracts, infra.** `corporal`.
   Per project: `infra.yml` gains `surfaces:` on `api.web` and `api.worker` and
   loses `port`/`health_check_path` on `worker` and `clock`; the four contract
   files are renamed and their headers rewritten (both currently *document* the
   three-segment scheme and the fan-out mandate in prose); `core/api/health.sh` is
   written and copied in the `dev` and `prod` Dockerfile stages; `worker.py` and
   `clock.py` lose their FastAPI/uvicorn health servers and retarget `_Tick` to a
   file; `root.py` loses the `/health/api/worker` fan-out handler; `EXPOSE` and the
   `curl` rationale narrow; `infra/stage/tests/test_smoke.py` loses its fan-out
   test and its liveness-first docstring.
   → DECISION (corporal raises; sarge rules): **does `api.web` keep an edge to
     `api.worker`?** Today that edge exists largely to feed the fan-out
     (`WORKER_HOST`/`WORKER_PORT`). Drop it and `api.worker` survives as a provider
     only through `api.clock`'s queue edge — which means the seeds stop exercising
     rule 32's positive arm (a directly-addressed core target with a `port`) on any
     core service. Coverage of a rule the advance is *introducing* is worth more
     than a tidier seed, so the presumption is to keep a real HTTP edge; sarge
     confirms once mod 125 has settled how rule 32 is detected.

6. **Mod 130: seed projects — recompile, docs, git cadence.** `corporal`.
   Recompile all envs both foundations (~24 checked-in artifacts churn wholesale),
   update each project's `plans/core/*` and `CHANGELOG.md`, then the three-step
   cadence from `test_projects.md`: inner-repo commit first, `git tag -f v<version>`
   if the change crosses a release boundary, then the outer catchup commit.
   Split from mod 129 because the recompile is only meaningful once the source is
   settled, and because a mechanical 24-artifact diff review does not want to share
   a context with hand-written application code.

### Phase 4 — `docex`'s own artifacts

7. **Mod 131: alignment sweep and cut artifacts.** `corporal`.
   - `plans/core/masterplan.md` § *The contract and health gates* — the whole block
     describes the deleted model and is rewritten.
   - `plans/core/compiler.md` — the rule-7 and `uses` prose still narrates the
     health fan-out; the Validation section's rule-28 line; `Where to look`.
   - `plans/core/release_flow.md`, `plans/core/test_projects.md`.
   - `doctrine_excerpts/` — `core_service.md`, `codebase.md`, `reverse_proxy.md`,
     `service_discovery.md`. **No excerpt currently contradicts the new model**
     (a grep for health/contract/surface across all 18 returns zero), so this is an
     *addition* decision, not a correction. Whatever is decided about a `surface`
     entry in `index.yml` — the stated criterion says resources, not CICL fields,
     so the likely answer is no — **write the verdict into `docex_process.md`**,
     because on this artifact a silent no is indistinguishable from an oversight.
   - `PRE_CUT_CHECKLIST.md` — B.9, B.10, B.6/B.7/B.7.1, C.8, C.9, D.6, D.9, D.10,
     D.11. Per `test_projects.md`'s own lesson, key each box on **what the tool
     prints**, not on a restated configuration: D.9/D.11's "if N is not 2" becomes
     wrong the moment the reconcile consumer set changes.
   - `upgrades/upgrade_1.7.0.md` — extended, not replaced (1.7.0 is unreleased, so
     both advances ship in one guide). Mirror its own conventions: the numbered
     change table, "what does not move", cause→expected-difference on recompile,
     and a Verification section that greps for zero occurrences of the retired
     spellings (`health_check_path` off `web`, `/health/<cb>/<svc>`, three-segment
     contract filenames).
   → RULING (sarge, recorded here so it is not re-litigated): **`cicl_version`
     stays `"3"`.** Generation 3 was introduced by advance 005 and has never been
     released, so folding `surfaces:` into it costs nothing and a `"4"` bump would
     manufacture a second rollback-unavailable boundary inside one cut. The upgrade
     guide must say this explicitly rather than leave it inferred.

### Phase 5 — folded-in deferrals from advance 005

Both admitted by operator ruling at plan review. The third deferral (thread-skill
body conformance) stays deferred: its own brief argues the fix must run through
`skill-iteration`'s trigger and outcome evals, which is a different territory and
a different measurement apparatus from anything else in this advance.

8. **Mod 132: `linkcheck.py` scopes its checks independently.** `corporal`.
   Check 1 (links + anchors) and check 3 (duplicate filenames) take independent
   roots, so the tool can reach `PRE_CUT_CHECKLIST.md` without the seed trees —
   which mirror each other **by design**, so their twelve duplicate filenames are
   the doctrine working correctly rather than a finding. Lands after mod 131 so it
   validates the checklist that mod just rewrote. A plain root widening is the
   thing this mod exists *not* to do: shipping a tool configured to always exit
   non-zero trains readers to ignore it.
9. **Mod 133: `preinfra development` probes the registry's delete capability.**
   `corporal`. Independent of everything above; order is free.

## Close-out

10. **Static audits.** `cohere` over the doctrine (RELEASING gates it whenever
   doctrine prose moves) and one `project-cohere` pass over `docex` — once, after
   every mod, per the token-cost heuristic. Findings triaged; a fix-pass mod
   injected only if they warrant one.
11. **Automated tests.** Unit + `pytest -m integration`. Baseline to beat: 1009 unit,
   20 integration.
12. **Skill gates.** Five skills moved in the doctrine edits (`contracts`,
    `testing`, `cicd-pipeline`, `infra-compile`, `skill-iteration`), so
    `skill-iteration`'s suite-level trigger eval fires, plus an outcome eval for
    `contracts`, which changed materially.
13. **Both smoke walks**, per `PRE_CUT_CHECKLIST.md`. Mandatory: this is a minor
    cut touching `docex` behavior, doctrine prose, and skills, so all three gates
    fire. Real AWS, real cost, operator-supervised. **This is the expensive step
    and the plan's largest single risk.**
14. **Hand back for the cut.** The cut itself is the operator's per `RELEASING.md`.

---

# Operator rulings at plan review

Recorded so they are not re-litigated mid-advance.

1. **Plan approved as drafted.**
2. **Two of advance 005's three deferrals fold in** — the `preinfra` registry
   delete probe and the `linkcheck` scope fix, now mods 133 and 132. Thread-skill
   body conformance stays deferred.
3. **The smoke walks are in scope.** This advance ends genuinely cut-ready, as
   advance 005 did.
4. **The `Mcp` controller-suffix row is the operator's to write.** `hex_overview.md`
   is resident stratum; nothing in this plan blocks on it, and no mod here touches
   that table.

## Sarge's own rulings

- **`cicl_version` stays `"3"`.** Generation 3 was introduced by advance 005 and has
  never been released, so folding `surfaces:` into it costs nothing and a `"4"` bump
  would manufacture a second rollback-unavailable boundary inside one cut. The
  upgrade guide states this explicitly rather than leaving it inferred.
- **`upgrades/upgrade_1.7.0.md` is extended, not replaced.** 1.7.0 is untagged, so
  both advances ship in one guide.

## Defects found in the committed doctrine edits

Both in operator-owned files; carried here so they are not lost. The operator will
take them, or hand them back to a mod.

- `cicl.md` § Service Fields lists the row as `surface` (singular) where the field
  is `surfaces:`.
- `docex/doctrine_excerpts/service_discovery.md` closes with a prose "Doctrine
  reference: `cicl.md § Resilience covers reachability, not resolvability`" — an
  anchor the rewrite deleted. It is prose rather than a markdown link, so
  `linkcheck` cannot see it: exactly the silent-drift class that artifact is known
  for. Mod 131 sweeps it.
