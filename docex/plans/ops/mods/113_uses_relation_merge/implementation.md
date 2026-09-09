# Mod 113 — Implementation Steps

Executes the design in [`overview.md`](./overview.md). Read that first — it
carries the reasoning these steps assume.

**Rule of record:** `doctrine/infrastructure/cicl.md § Uses Relationships` and
the validation-rule list, as committed at `337d5a8`. Where the advance's design
record and the doctrine differ, **the doctrine wins**. Do not edit any doctrine
file in this mod.

**Branch:** `005_process_type_solidification`. Do not create branches.
**Commits:** path-scoped only. Never `git add -A`.

## Ground rules

1. **Rules 6 and 24 are tombstoned, not renumbered.** No rule number moves. Rule
   numbers appear in `ValidationIssue.rule` ids and in tests; changing one
   silently breaks both.
2. **`role: scheduler` is NOT retired here** (that is Mod 116). Every existing
   `scheduler` guard stays, renamed only where it names a merged field.
3. Do not touch: `upgrades/*.md`, `doctrine_excerpts/`, `skill_iter/`,
   `release.py`'s reconcile *predicate logic*, anything scheduler/clock.
4. Add `[Unreleased]` changelog line only (step 12) — nothing more.

## Step 0 — Baseline

Record, before changing anything:

```bash
cd docex
python3 -m pytest tests/unit -q 2>&1 | tail -3          # expect 995 passed
python3 -m pytest -q --collect-only 2>&1 | tail -2      # expect 1059 collected
python3 -m pytest -m integration -q --collect-only 2>&1 | tail -2   # expect 17
```

These three reconcile: 995 + 64 unmarked tests in
`tests/integration/test_compile.py` = 1059. `integration` is a **per-test
marker, not a directory**. Keep the numbers; step 13 reports the delta.

---

## Step 1 — `cicl/model.py`: one authored field, retired fields rejected

**1a. `CURRENT_CICL_VERSION`** (`:30`): `"2"` → `"3"`.

**1b. `CoreService`** (`:109-172`):

- Delete the `depends_on` field (`:131`) and the `consumes` field (`:138`) with
  their comments.
- Add in their place:

```python
# cicl.md § Uses Relationships. ONE relation: a bare entry names a backing
# service, a dotted entry names a core service, fully qualified. Only core
# services declare it — a backing service has no outbound edges and is a
# graph SINK, which is what makes the cycle rule fall out of the graph's
# shape instead of being enforced against it (rule 6, retired 1.7.0).
uses: list[str] = Field(default_factory=list)
```

- Replace `consumes_refs()` (`:156-172`) with two accessors. Keep the
  drop-on-unparse contract and its docstring reasoning **verbatim** — rule 25
  reports a malformed entry once and it must not resurface downstream:

```python
def core_uses(self) -> set[str]:
    """Dotted `uses:` targets, normalized. Unparseable entries dropped.
    <keep consumes_refs()'s existing WHY paragraph, s/consumes/uses/>"""

def backing_uses(self) -> list[str]:
    """Bare `uses:` targets, in authored order."""
```

Classification is **by form** — an entry containing `"."` is a core target.
Sound because `_SERVICE_NAME_RE` (`:24`) forbids a dot in any service name and
`_validate_service_names` enforces it on codebase, core-service, and backing
names alike. Put that reason in a comment on whichever helper does the split;
write the split **once** and have both accessors use it.

**1c. `_ServiceBase`** (`:176-185`): delete the `depends_on` field (`:184`).
Add **nothing** — this is the sink property in the type.

**1d. Retired-field rejection.** Add a `mode="before"` validator to **both**
`CoreService` and `_ServiceBase`, modelled on `Codebase._reject_v1_shape`
(`:218-235`) — same shape, same reason (a one-time migration mistake earns a
targeted message, not `tt_rule_4_undeclared_field`). Both models are
`extra="allow"`, so without this the fields land silently in `model_extra`.

Message must: name the offending field, state there is one relation named
`uses`, and point at `upgrades/upgrade_2.0.0.md`. On `_ServiceBase` it must also
say a backing service declares **no** outbound edges and that engine-level
container needs belong in the engine's transfer-table `defaults` block.
**Never accept either field as a silent alias.**

**1e. `_MOVED_TO_SERVICE`** (`:190-193`): `"depends_on"` → `"uses"`.

**1f. The stale v1 message** (`:322-329`): it currently says v2 "adds the
`consumes` relation" and tells the operator to `set cicl_version: "2"`. Rewrite:
name the `uses` relation, end at `"3"`, keep both guides in the chain
(1.6.0 then 1.7.0).

**1g. `ServiceRef` docstring** (`:38`): `` `consumes:` targets `` → `` `uses:`
targets ``.

---

## Step 2 — `cicl/compile.py`: one stored field, two derived properties

**2a. `CompiledService`** (`:460-534`). Delete the `depends_on` field (`:470`)
and the `consumes` field (`:534`, with its long placement comment). Add a single
field **in `depends_on`'s old position** (the non-defaulted region), so the
one construction site's ordering is undisturbed:

```python
# The authored `uses:` entries, VERBATIM — bare for a backing target, dotted
# for a core one. See cicl.md § Uses Relationships.
#
# WHY one field with two derived accessors, and not two fields: the
# backing/core split below is DERIVED FROM TARGET KIND, not authored. There
# is one relation in `infra.yml` (the two-field `depends_on`/`consumes`
# split was retired in 1.7.0), and storing the split would invite a
# construction site that populates the two lists inconsistently. Nothing can
# land in the wrong list because nothing is placed into a list at all.
uses: list[str]
```

Then two read-only properties — **the one and only derivation**:

```python
@property
def uses_backing(self) -> list[str]:
    """`uses` targets that are backing services. A backing service's
    compiled identity IS its bare name, so no translation is needed."""

@property
def uses_core(self) -> list[str]:
    """`uses` targets that are core services, as COMPILED identities
    (`api-worker`) — the same keys into `CompiledEnv.services`."""
```

Both classify on `"." in entry`. State in a comment why that is total and
unambiguous: `_SERVICE_NAME_RE` forbids dots in service names, so bare/dotted
partitions the entries with no overlap and no gap, and rule 25 makes that
partition *mean* target kind.

**2b. The construction site** (`:1012-1089`). Replace the `depends_on=` kwarg
(`:1021`) and the `consumes=` kwarg (`:1082-1088`) with one:

```python
uses=(list(svc.uses or []) if is_core else []),
```

Backing services get `[]` unconditionally — they cannot declare the field.

**2c. `_apply_fixed_invariants`** (`:1150-1151`). **Delete these two lines:**

```python
if svc.depends_on:
    out["depends_on"] = list(svc.depends_on)
```

> This is the real deletion of the mod. It is the single source of every
> emitted `depends_on:` on a core or backing block, and removing it is what
> makes *"`uses` emits nothing onto a core service's own block"* true. Do not
> substitute `uses_backing` here.

---

## Step 3 — `cicl/validate.py`: rule 7 collapses, rule 25 absorbs

**3a. Field sets** (`:58-65`):
- `_STANDARD_SERVICE_FIELDS`: drop `"depends_on"`, `"consumes"`; add `"uses"`.
- `_STANDARD_BACKING_FIELDS`: drop `"depends_on"`; **add `"uses"`**. Adding it
  keeps the extras walk quiet so step 3e is the single reporter of a
  backing-scoped `uses`.

**3b. `_validate_magic_refs.scan`** (`:281-459`). Collapse the two parameters
`depends_on: list[str]` and `consumes: set[str] | None` into one:
`uses: set[str] | None` — the referencer's full `uses` set (core targets dotted,
backing targets bare), or `None` for a **backing referencer**.

- **Core-target branch** (`:361-406`): check `dotted not in uses`. Issue id
  becomes `rule_7_magic_ref_implies_uses`. Keep the ONE-DIRECTIONAL comment and
  the same-codebase-is-not-exempt clause **verbatim in substance** — both are
  doctrine (§ Three clarifications). Update the trailing citation to
  `cicl.md § Uses Relationships`.
- **Backing-target branch** (`:447-459`): check `ref.target not in uses`. Same
  id, `rule_7_magic_ref_implies_uses`. Two ids become one because the rule is
  one.
- **The `uses is None` branch** (`:369-383`) survives **unchanged in
  behaviour**. Rewrite its comment to the simpler justification the doctrine now
  gives: a backing service declares no edges at all, so there is nothing it
  could declare; a backing service embedding a core hostname (a CORS origin) is
  not *calling* it, so no interface implication exists. This is rule 7 correctly
  **not applying**. Its two pinning tests must survive.

- **Call sites**: core scan (`:480-487`) passes
  `svc.core_uses() | set(svc.backing_uses())`; backing scan (`:508`) passes
  `None` and loses the `depends_on` argument entirely.

**3c. Delete `_validate_depends_on`** (`:518-581`) **in full**, and its
registration at `:107`. That removes:
- `rule_24_depends_on_core_service` (`:530-543`) — rule 24 is retired.
- `rule_6_depends_on_cycle` and the DFS (`:554-580`) — a backing service is now
  a sink and cannot sit in a cycle; the doctrine states acyclicity as a property
  of the graph's shape, so a rule enforcing it is dead weight.
- **BUT NOT** the unknown-target check at `:522-529`. See 3d.

**3d. Rename `_validate_consumes` → `_validate_uses`** (`:589-680`) and fold in
the backing arm. For each entry on each core service:

| Condition | Issue id |
| --------- | -------- |
| no `"."` and names a known backing service | **valid** |
| no `"."` and names a known *codebase* | `rule_25_uses_malformed` — keep the existing "a codebase has no single boundary" message; this is the mistake the field invites |
| no `"."` and names nothing that exists | `rule_25_unresolved_uses` |
| dotted, unparseable | `rule_25_uses_malformed` |
| dotted, names itself | `rule_25_self_uses` |
| dotted, codebase or core service unknown | `rule_25_unresolved_uses` |
| dotted, target role is `scheduler` | `rule_25_uses_scheduler` |

> **The unknown-target check must survive.** `:526`'s
> `rule_6_unknown_depends_on` is named after a retired rule but is live and
> necessary — a typo'd `uses` target must fail at compile time, not later as an
> unresolvable magic ref or not at all. It becomes the bare-name arm of
> `rule_25_unresolved_uses`. **Do not delete it with rule 6.**

Keep `rule_25_uses_scheduler` (was `rule_25_consumes_scheduler`, `:666-679`)
with its logic intact. Committed rule 25 carries no scheduler clause, but
`role: scheduler` lives until Mod 116; add a comment saying so.

Update `magic_refs.py`: `self_consumes_message` → `self_uses_message`
(`:194-205`) and the `consumes`/rule-25 references in the `:170-181` comments.

**3e. New check: `uses` on a backing service.** A standing scope rule, not a
numbered one — Mod 112 deliberately declined to invent a number, so do not
invent one. Add to `_validate_uses`:

```python
rule="rule_uses_on_backing_service"
```

matching the existing `rule_<descriptive>` convention
(`rule_domain_default_not_web`, `rule_web_service_needs_port`). Read it off
`svc.model_extra`. Message: a backing service declares no outbound edges and is
a graph sink; engine-level container needs belong in the engine's transfer-table
`defaults` block. Cite `cicl.md § Uses Relationships` and the Service Fields
scope column. `where=` is the backing service path.

**3f.** Update the section banner comments at `:271-273`, `:513-515`, `:584-586`
so they name the rules that actually live below them.

---

## Step 4 — `emit/compose.py`: the exec gate is the last emission

Read overview § 5(c) before touching this. **The brief's "delete `756-782`
outright" was overruled at design review** — deleting it wholesale downgrades
the exec gate to `service_started` and races every first migration against its
database.

**4a. Exec gate** (`:741-743`): `p.depends_on` → `p.uses_backing`.

**4b. Move the long-form rewrite inline** into the exec loop, immediately after
4a, and **delete the second pass at `:756-782`** along with the
now-unneeded loop over `services.values()`.

Safe because by the time the exec loop runs (`:698`) every core, replica,
backing, and sidecar block is already in `services` — verified by reading the
emission order; only ofelia containers are emitted later, and they are never
exec targets. Exec deps are backing-targeted by construction.

```python
exec_deps = sorted({d for p in svcs for d in p.uses_backing})
if exec_deps:
    long_form: dict[str, Any] = {}
    for dep in exec_deps:
        target_global = simple_to_global.get(dep, dep)
        target_block = services.get(target_global, {})
        long_form[target_global] = {
            "condition": (
                "service_healthy" if "healthcheck" in target_block
                else "service_started"
            )
        }
    exec_block["depends_on"] = long_form
```

Carry the `service_healthy` / `service_started` reasoning from `:758-764` into a
comment here — it is doctrine
(`migrations.md § Dev and Test Mechanism`: the exec block carries its
backing-targeted `uses` edges "rewritten to `condition: service_healthy`"), and
losing the explanation is how the next agent deletes it again.

**4c.** `simple_to_global` (`:527-529`) now has one consumer. Move it into the
exec loop or leave it where it is, but rewrite the comment at `:518-526` — it
cites retired rule 24.

**4d.** `:694-697`'s comment about the exec pass running "BEFORE the depends_on
second pass" describes a pass that no longer exists. Rewrite.

**After this step, no core-service or backing-service block in any compiled
`docker-compose.yml` carries `depends_on:`.**

---

## Step 5 — `emit/hcl.py`: drop three dead strips

Delete `body.pop("depends_on", None)` at **`:845`, `:879`, `:915`** (RDS /
ElastiCache / S3). Unreachable once step 2c lands — the compiler can no longer
produce that key — and leaving them is stale vocabulary. Elastic already
discarded the field; nothing else changes here.

---

## Step 6 — `describe/{dag,llm}.py`: edge kind from target kind

**6a. `dag.py` module docstring** (`:1-10`): both relations → one relation
rendered as two edge kinds **derived from target kind**. Keep the "may legally
contain cycles" point — a `uses` graph is still cyclic (§ The graph may contain
cycles).

**6b. `collect_edges`** (`:76-101`): `svc.depends_on` → `svc.uses_backing`,
`svc.consumes` → `svc.uses_core`. Edge-kind strings become
`"uses_backing"` / `"uses_core"`. Keep the flat-pass / no-traversal comment —
still load-bearing.

**6c. `render_dag`** (`:151-165`): headings become
`"uses edges (backing target) — solid:"` and
`"uses edges (core target) — dashed:"`. Update the "carried TWICE" comment: the
grep target is now `uses`.

**6d. `llm.py`** (`:51-54`): keys `depends_on`/`consumes` → `uses_backing`/
`uses_core`. Keep `target_id(...)` mapping on the core arm.

---

## Step 7 — `pipeline/check.py`: three gates read `uses`

Authoring-model reads throughout, so use `core_uses()`.

- **`_gate_contracts`** (`:352-380`): docstring — provider set is
  (**core-targeted `uses`**) ∪ (`web`-network core service). Both arms stay
  load-bearing. `:378-380` → `consumed |= svc.core_uses()`.
- **`_gate_health_endpoints`** (`:435-462` docstring, `:503`, `:524`):
  `svc.consumes_refs()` → `svc.core_uses()`. **Rewrite the `:446-449` comment** —
  it justifies the fan-out by citing rule 24's ban on core `depends_on`, which no
  longer exists. New justification: the fan-out is keyed on **core-targeted**
  edges because a backing target has no `<codebase>/<service>` health form.
- `:516`, `:542`: message text `consumes` → `uses`.
- **Leave every `role == "scheduler"` guard** (`:390`, `:481`, `:508`, `:529`) —
  Mod 116.
- `:585`'s `depends_on: service_healthy` prose refers to *compose's* key on the
  exec block. Still true; leave it.

---

## Step 8 — `pipeline/release.py`: field rename ONLY

`_consumer_reconcile_set` (`:217-261`): `svc.consumes` → `svc.uses_core`
(`:241`, `:248`). Prose `consumes` → `uses` in the docstring (`:222`) and the
two messages (`:308`, `:318`).

> **Do not change this predicate's logic.** Mod 114 rewrites it onto durable
> operands. Leave the `:243-246` scheduler comment and the `ecs_service` guards
> exactly as they are.

---

## Step 9 — `pipeline/rollback.py`: intelligible boundary message

No change to the precondition at `:135-146`. **Do not weaken it.**

`_boundary_message` (`:290-318`) currently special-cases `None`/`"1"` as "the
CICL v1→v2 boundary" and closes with *"once a second cicl_version "2" release
exists, rollback works normally"*. Under `"3"` a target declaring `"2"` falls
into the generic branch and loses exactly that reassurance.

Generalize: any **recognized older** generation (`None`, `"1"`, `"2"`) gets the
boundary message, parameterized on the target's own generation and
`CURRENT_CICL_VERSION`, with the reassurance line intact and correct.
Unrecognized values keep the generic branch.

> **Known trap — expected, precedented, not to be papered over.** Every existing
> tagged release declares `"2"`, so rollback aborts until a second v3 release
> exists. `upgrade_1.6.0.md:463-484` documents the same trap for the previous
> bump. This mod's only obligation is an intelligible message. Mod 117 discloses
> it in the guide.

---

## Step 10 — Fixtures and smoke projects

Mechanical rewrite everywhere: `depends_on: [a, b]` + `consumes: [x.y]` on the
same core service → `uses: [a, b, x.y]`; `depends_on` deleted outright from every
backing service; `cicl_version: "2"` → `"3"`.

**10a. Four fixture `infra.yml`s** — all `cicl_version: "2"`, none declares
`consumes:`, every hit is `depends_on: [appdb]`:

| Path (under `docex/tests/fixtures/`) | Lines |
| ------------------------------------ | ----- |
| `sample_project/infra/infra.yml` | 24 |
| `sample_project_elastic/infra/infra.yml` | 23 |
| `sample_project_scheduler_fixed/infra/infra.yml` | 22, 42 |
| `sample_project_scheduler_elastic/infra/infra.yml` | 23, 39 |

Migrate the two `sample_project_scheduler_*` fixtures rather than deleting them —
Mod 116 deletes them, and leaving them uncompilable would red the suite at this
mod's boundary.

**10b. Inline docs built inside test modules.** These are module-level
constants, so a miss reds a whole module:
`test_validate.py:34` (`_BASE_FIXED`), `test_categories.py:54` (`_MIXED`),
`test_telemetry.py:50,84`, `test_secretsmgmt.py:49` (`_INFRA`),
`test_scheduler.py:45` (`_JOB`), `test_compile.py:534,554` (`_NAMING_INFRA`),
`test_worker_role.py:52,284`, `test_service_expansion_emit.py:39-73`,
`test_replicas.py:56,64`, `test_hcl_emitter.py:571,1076`,
`test_pipeline_preinfra.py:219`, `test_magic_refs.py:106`,
`test_consumes_relation.py:48,57`, `test_contract_health_gates.py:58,71`.

Direct model/dataclass kwargs also need the rename:
`test_magic_refs.py:106` (`CoreService(depends_on=…)`),
`test_emit_dispatch.py:62-75`, `test_naming_policy_leak.py:77-92`,
`test_replicas.py:339` (`CompiledService(depends_on=…)` → `uses=…`).

**10c. Smoke projects.** Both at `docex/test_projects/{fixed,elastic}/infra/infra.yml`,
both `cicl_version: "2"` on line 1. Each has:
- `api.web`: `depends_on: [appdb, probe, events]` + `consumes: [api.worker]` →
  `uses: [appdb, probe, events, api.worker]`
- `api.worker`: `depends_on: [appdb]` → `uses: [appdb]`
- `reaper.prune`: `depends_on: [appdb]` → `uses: [appdb]`
- backing services declare none — nothing to remove

Rewrite the surrounding comments: the long ones on `api.web` explain the
`depends_on`/`consumes` distinction and cite § Consumes Relationships. They must
now explain the one relation and cite § Uses Relationships. Keep the
substantive points — the one-directional edge, and why `probe`/`events` are
core-service-scoped rather than codebase-scoped (a codebase-level ref would
oblige every core service to declare the edge).

**10d. Regenerate compiled output.** `elastic` has 9 tracked files under
`infra/output/`; `fixed` has **none** — do not create one. Recompile elastic and
commit the regenerated output. Expect the four `-exec` blocks to keep a
long-form `depends_on:` and the four on `api-web`/`api-worker` to vanish:

| File | Blocks losing `depends_on:` | Blocks keeping it |
| ---- | --------------------------- | ----------------- |
| `output/dev/docker-compose.yml` | `…-api-web` (l.107), `…-api-worker` (l.197) | `…-api-exec` (l.69), `…-reaper-exec` (l.308) |
| `output/test/docker-compose.yml` | `…-api-web` (l.67), `…-api-worker` (l.146) | `…-api-exec` (l.32), `…-reaper-exec` (l.254) |

`output/project/production/main.tf:64` contains the word "consumes" in **prose** —
leave it.

---

## Step 11 — Tests

**11a. Rename `test_consumes_relation.py` → `test_uses_relation.py`** and
rewrite. It is 36 tests and the module *is* the retired split. Delete outright
the tests whose subject no longer exists:
- `test_12_consumes_cycle_is_legal_while_a_depends_on_cycle_is_fatal` — the
  asymmetry is gone; a backing service is a sink.
- the ~6 tests pinning "neither branch is satisfiable by the other".

**Keep and re-key**, because they pin surviving doctrine:
- the two `test_backing_referencer_*` tests — rule 7 correctly **not applying**.
- one-directional, same-codebase-not-exempt, and codebase-level-`env:` (§ Three
  clarifications).
- a cycle test: `api.web uses api.worker` **and** `api.worker uses api.web` is
  legal and must compile clean.

**Add:**
- a bare `uses` entry naming an unknown service → `rule_25_unresolved_uses`
  (this is the surviving `rule_6_unknown_depends_on`; it must have a test).
- `depends_on:` on a core service → hard error naming `upgrade_2.0.0.md`.
- `consumes:` on a core service → same.
- `uses:` on a backing service → `rule_uses_on_backing_service`.
- `cicl_version: "2"` → rejected, message names `"3"`.

**11b. `test_service_expansion_emit.py::test_consumes_reaches_no_emitted_artifact`**
(`:366-388`) — rename and **strengthen**: assert `"uses"` appears in no emitted
artifact. Now true of the whole relation, not half of it. This is
rule-of-record item 3's pin.

**11c. `test_exec_service.py`** — `test_7_depends_on_is_long_form_and_health_gated`
(`:94-109`) is the guard on step 4. Rename, **do not weaken**: it must still
assert long-form with `condition: service_healthy` against the database.

**11d. `test_contract_health_gates.py`** — `test_fanout_required_without_depends_on`
(`:354-368`) is void; there is no second field for the fan-out not to key on.
Delete it. `_svc(consumes=…)` builder (`:58,71`) → `uses=`.

**11e. `test_describe.py`** — 9 tests assert the literal heading strings and the
`{"depends_on","consumes"}` edge-kind set. Update to the new headings and
`{"uses_backing","uses_core"}`.

**11f. `test_service_nesting.py`** (`:377-445`) — rule-24 and
`rule_6_depends_on_cycle` coverage deletes. `test_validate.py` (`:249-281`) —
`rule_6_depends_on_cycle` deletes; `rule_7_magic_ref_implies_depends_on` →
`rule_7_magic_ref_implies_uses`.

**11g. `test_compose_emitter.py`** (`:170-183`, `:265-311`) — the long-form
rewrite is now exec-only. Rewrite these to assert (i) the exec block is
long-form and health-gated, and (ii) **no core or backing block carries
`depends_on:` at all**.

**11h. `test_replicas.py::test_9_depends_on_second_pass_reaches_derived_services`**
(`:275-278`) — the second pass is gone and replicas were only ever
*targets*. Either delete, or re-point at the exec block. Decide and say which in
the report.

**11i. `test_orchestrate_test.py:143`** — docstring only.
`test_hcl_emitter.py:629,652` — the word "consumes" in *remote-state prose*.
**False positives; leave both.**

**11j. NEW integration test — the cold-stack migrate gate.** Add to
`docex/tests/integration/`, marked `@pytest.mark.integration`.

`test_migrate_real.py` calls `run_up` **before** `run_migrate`, so the database
is already warm and it passes with any gate or none. Nothing in either suite
asserts the behaviour this mod puts at risk.

Model the new test on `test_migrate_real.py` but **call `run_migrate` first,
with no prior `run_up`**, against a `fresh_project`. `compose run` must bring
the database up through the exec block's gate; the migration must succeed. Then
tear down with `run_down`. Docstring must say why it exists: the exec gate is
the only ordering emission left in the compiler, and a regression here surfaces
as a flaky migration rather than as a compiler bug.

---

## Step 12 — `docex` core planning docs + changelog

Update only for this mod's changes; Mod 118 sweeps the rest.

- `docex/plans/core/compiler.md` — `:57` (both relations), `:58` (field list),
  `:260` (exec union + "second pass"), `:341`, `:355`, `:356`, `:482` (rule 7
  kind-aware), `:489` (rule 24 + "one DAG / one cyclic digraph"), `:490`,
  `:491` (rule 25, `consumes_refs()`). `:37`, `:137` are prose false positives.
- `docex/plans/core/masterplan.md` — `:239`, `:241`, `:245`, `:246`, `:249`.
  `:200` is a false positive.
- `docex/plans/core/test_projects.md` — `:16`.
- `docex/plans/core/release_flow.md:95` — prose; no change.
- Root `CHANGELOG.md` — **one brief `[Unreleased]` line only.** Mod 117 owns the
  changelog beyond that.

Also update the prose/comment references in the smoke projects' own docs
(`core/api/src/root.py`, `plans/core/masterplan.md`, `plans/core/api/api.md`,
`infra/contracts/*.yml`, `infra/stage/tests/test_smoke.py`) so a downstream
reader copying the reference project sees the current vocabulary.

---

## Step 13 — Verify

1. `python3 -m pytest tests/unit -q` — green. Report the delta against **995**
   and explain it test-by-test. A net decrease is expected and correct; an
   *unexplained* delta is not.
2. `python3 -m pytest -m integration -q` — green (needs a docker daemon).
3. **The central claim.** Compile **both** smoke projects for all four envs —
   `fixed` has no committed output, so **compile it fresh** and grep that; say
   so explicitly in the report rather than quietly grepping only `elastic`:

   ```bash
   grep -n "depends_on:" <each compiled docker-compose.yml>
   ```

   The **only** permitted hits are inside `-exec` blocks, each long-form with a
   `condition:`. A hit on any other block **fails the mod**.
4. `git grep -n "depends_on\|consumes" -- docex/src/` returns only the compose
   `depends_on:` **key name** on the exec block (Docker's word, not CICL's).
5. `./bin/docex dag` and `./bin/docex describe` run clean on a smoke project.

## Step 14 — Commit

Path-scoped. **Never `git add -A`** — a shared index cross-contaminated two
commits earlier in this advance.

```bash
git add docex/src docex/tests docex/test_projects docex/plans CHANGELOG.md
git commit -m "mod 113 complete; designed, implemented, and documented."
```

Verify with `git status --short` that nothing outside those paths was staged.
