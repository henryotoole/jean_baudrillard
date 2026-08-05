# Mod 113 — `uses` in the compiler; `cicl_version: "3"`

**Advance 005, Phase 2. Breaking.** Mod 112 landed the rule
([`cicl.md § Uses Relationships`](../../../../doctrine/infrastructure/cicl.md#uses-relationships),
committed at `337d5a8`). This mod makes the executor match it.

Where the [design record](../../advances/005_process_type_solidification/uses_relation_merge.md)
and the committed doctrine differ in wording, **the doctrine wins**. Every
statement below is checked against the doctrine as committed, not against the
record.

## Baseline

Captured on a clean tree at `337d5a8` before any change. **Three numbers, not
one** — the selections differ and conflating them will manufacture a phantom
delta:

| Selection | Collected | Note |
| --------- | --------- | ---- |
| `pytest tests/unit` | **995** (995 passed, 123 s) | the kickoff's command; the delta in this mod is stated against this |
| bare `pytest` (default suite) | **1059** | `pyproject.toml` sets `testpaths = ["tests"]` and `addopts = "-m 'not integration'"`, so this is `tests/unit` **plus the 64 unmarked tests in `tests/integration/test_compile.py`** |
| `pytest -m integration` | **17** | `integration` is a **per-test marker, not a directory** — `tests/integration/test_compile.py` collects 66 of which only 2 are marked |

995 + 64 = 1059 exactly. The three reconcile; none is stale. The implementation
will report all three so a reviewer comparing against a differently-scoped run
does not chase a difference that is only a selection.

## What the rule says

Read as committed, the rule is five sentences:

1. `uses` is the single relation. An entry names a **backing service** bare
   (`database`) or a **core service** dotted and fully qualified (`api.worker`).
   (§ Uses Relationships; rule 25.)
2. **Only core services declare `uses`.** A backing service has no outbound
   edges at all and is a graph **sink**. (§ Uses Relationships; Service Fields
   scope column — `uses` is scoped `core service`, and `./bin/docex compile`
   "will always fail loudly when a field is in the wrong scope".)
3. `uses` **emits nothing onto a core service's own block** — no compose key, no
   HCL resource, on either foundation. (§ Uses Relationships.)
4. The **exec block** carries "the union of its codebase's backing-targeted
   `uses` edges, rewritten to `condition: service_healthy`". This is the sole
   emission. (§ Startup ordering is not a doctrine feature;
   [`migrations.md § Dev and Test Mechanism`](../../../../doctrine/infrastructure/specifics/migrations.md).)
5. `cicl_version` is `"3"`. Earlier generations are **rejected, not translated**.
   (Rule 21.)

Rules 6 and 24 are **tombstoned, not renumbered**. No rule number moves.

## Design

### 1. The authoring model carries one field; the compiled model carries the derived split

`CoreService.depends_on` and `CoreService.consumes` are replaced by a single
`uses: list[str]`. `BackingService` (`_ServiceBase`) **loses `depends_on` and
gains nothing** — that is rule-of-record item 2 expressed in the type.

Classification of an entry is **by form**, and form determines kind because
rule 25 makes them equivalent: bare ⇒ backing target, dotted ⇒ core target.
Two accessors on `CoreService` replace `consumes_refs()`:

| Accessor | Returns | Replaces |
| -------- | ------- | -------- |
| `backing_uses()` | bare entries, in order | the old `depends_on` list |
| `core_uses()` | dotted entries normalized via `ServiceRef.parse`, unparseable dropped | `consumes_refs()` |

`core_uses()` inherits `consumes_refs()`'s drop-on-unparse contract verbatim and
for the same reason: rule 25 reports a malformed entry **once**, and it must not
also resurface downstream as a mystifying rule-7 miss or a missing contract.

On `CompiledService`, `depends_on` and `consumes` collapse into **one stored
field `uses`**, holding the authored entries verbatim (bare *and* dotted).
`uses_backing` and `uses_core` become **read-only derived properties**, not
fields:

```python
uses: list[str] = field(default_factory=list)   # authored form, verbatim

@property
def uses_backing(self) -> list[str]: ...   # bare entries — compiled id IS the bare name
@property
def uses_core(self) -> list[str]: ...      # dotted entries → ServiceRef.parse(x).compiled
```

> **Sarge's condition, satisfied structurally rather than by discipline.** There
> is one stored field, so the two lists cannot be populated inconsistently —
> they are not populated at all. There is no third construction site to get
> wrong, because construction takes one argument. The derivation lives in
> exactly one place: these two properties.
>
> **Why form is a sound proxy for target kind, totally and unambiguously.**
> `model.py:24`'s `_SERVICE_NAME_RE` is `^[a-zA-Z][a-zA-Z0-9_-]*$` — **a service
> name cannot contain a dot**, and `CICLDocument._validate_service_names`
> enforces this on codebase names, core service names, and backing service
> names alike. So "contains a dot" partitions the entries with no overlap and no
> gap, and rule 25 makes that partition *mean* target kind: bare ⇒ backing,
> dotted ⇒ core. This is the doctrine's own claim that the compiler knows target
> kind for every edge (§ The graph may contain cycles), discharged by the
> lexical rule rather than by a lookup that could miss.
>
> **The split is derived, not authored.** A WHY comment on the field will say
> so, in those words, so a future reader finding two accessors does not conclude
> the retired two-field authoring split survived.

The rejected alternative was one compiled list plus a
`compiled.services[k].is_core` lookup at each of the six read sites: same
derivation in six places, each free to drift, and each degrading to a silent
`None` on a miss. Also rejected: two stored fields — that is what invites the
inconsistent third construction site.

Consequence for the read sites: `release.py` gets `svc.consumes` →
`svc.uses_core` and `compose.py` gets `p.depends_on` → `p.uses_backing`. Both
are literally a field rename at the call site, which is what keeps Mod 114's
diff clean.

### 2. `depends_on:` and `consumes:` become hard errors

At the **model layer**, as `mode="before"` validators on `CoreService` and on
`_ServiceBase` — following the `Codebase._reject_v1_shape` precedent, which
exists for precisely this case (a one-time migration mistake earning a targeted
message rather than a generic "extra inputs are not permitted"). Both models are
`extra="allow"`, so without this the fields land silently in `model_extra` and
surface as `tt_rule_4_undeclared_field` — an unrelated message about
transfer-table field declarations.

The message names the field, says there is one relation now, and points at
`upgrades/upgrade_1.7.0.md`. **Never a silent alias.**

Ordering matters: a genuine v2 document also declares `cicl_version: "2"`, and
`CICLDocument._validate_cicl_version` is a document-level `mode="before"`
validator, so it fires before nested models are built. An operator upgrading
sees the version message first, which is the right one.

### 3. `uses:` on a backing service is rejected

Not a numbered rule — Mod 112 deliberately declined to invent one, and this mod
does not invent one either. It is the Service Fields scope column plus the
standing "fails loudly when a field is in the wrong scope" sentence
(`cicl.md:160`).

Enforced in `validate.py` as issue id **`rule_uses_on_backing_service`**,
matching the existing `rule_<descriptive>` convention for unnumbered checks
(`rule_domain_default_not_web`, `rule_web_service_needs_port`, …). `"uses"` is
added to `_STANDARD_BACKING_FIELDS` so the extras walk stays quiet and this
check is the single reporter. The message states the sink property and points at
the engine's transfer-table `defaults` block as the correct home.

`where=` gives the backing service path, which is why this one lives in
`validate.py` rather than the model layer: it is a standing scope rule, not a
migration artifact.

### 4. Validation: rule 7 collapses, rule 25 absorbs the target checks

**Rule 7** (`_validate_magic_refs.scan`). The function currently takes
`depends_on: list[str]` and `consumes: set[str] | None` and answers rule 7 in two
places (`:384-405` core, `:447-459` backing) against two different fields. It
collapses to one parameter — the referencer's `uses` set, or `None` for a
backing referencer — and one clause: *a magic ref must be matched by a `uses`
entry on the referencing core service*. The existing branch structure at
`:362-401` / `:447-457` is what makes this a collapse rather than new machinery.

Issue ids: `rule_7_magic_ref_implies_consumes` and
`rule_7_magic_ref_implies_depends_on` both become
**`rule_7_magic_ref_implies_uses`**. Two ids become one because the rule is one.

The `consumes is None` branch — a backing service holding a core ref — survives
**unchanged in behaviour** and gets simpler to justify: backing services declare
no edges at all, so this is rule 7 correctly *not applying*. The doctrine says
this in as many words (rule 7, second sentence onward), and its two pinning
tests must survive.

**Rule 25** absorbs the shape *and* target checks:

| Issue id | Fires on | Was |
| -------- | -------- | --- |
| `rule_25_uses_malformed` | an entry that is neither a bare backing-service name nor a parseable `<cb>.<svc>` | `rule_25_consumes_malformed` |
| `rule_25_self_uses` | a core service naming itself | `rule_25_self_consumes` |
| `rule_25_unresolved_uses` | a bare entry matching no backing service; a dotted entry whose codebase or core service does not exist | `rule_25_unresolved_consumes` **and** `rule_6_unknown_depends_on` |

> **The unknown-target check survives.** `validate.py:526`'s
> `rule_6_unknown_depends_on` is named after a rule that is now tombstoned, but
> the check itself is live and necessary: a typo'd `uses` target must fail at
> compile time, not later as an unresolvable magic ref or not at all. It merges
> into `rule_25_unresolved_uses`, where its sibling for core targets already
> lived. Rule 25 is the natural home: an entry naming nothing that exists does
> not "name either a backing service or a core service".

**Deleted:** `_validate_depends_on` in full — its rule-24 clause (`:530-543`),
its DFS cycle detection (`:554-580`), and the `rule_6_depends_on_cycle` /
`rule_24_depends_on_core_service` ids. The cycle DFS goes because a backing
service is now a sink and cannot sit in a cycle; the doctrine states this as
structural, and a rule enforcing a property the graph's shape already guarantees
is dead weight. `_validate_consumes` is renamed `_validate_uses` and grows the
backing-target arm.

**Untouched, and knowingly out of step with the doctrine:**
`rule_25_consumes_scheduler` (`:666-679`) is renamed `rule_25_uses_scheduler`
and its logic kept. Committed rule 25 no longer carries a scheduler clause, but
`role: scheduler` is not retired until **Mod 116**, and deleting the guard here
would leave a live role unguarded across three mod boundaries. Recorded in
[Drift handed forward](#drift-handed-forward).

### 5. Emission: the exec gate is the last one standing

Three edits, and the third is the one that carries risk.

**(a) `compile.py:1150-1151` stops writing `depends_on` into the service body.**
This is the actual source of every emitted `depends_on:` on a core or backing
block. Deleting it — not the compose pass — is what makes rule-of-record item 3
true.

**(b) `compose.py:741-743`, the exec gate, is kept**, re-derived as
`sorted({d for p in svcs for d in p.uses_backing})`. Identical derivation,
different source word — and already backing-only today, since retired rule 24
forbade a core `depends_on` outright.

**(c) `compose.py:756-782`, the long-form rewrite, is deleted *as a second pass*
and its logic moves inline into the exec-block construction.**

> ### Finding: deleting `756-782` outright would silently break the migrate gate
>
> The kickoff says "delete `compose.py:756-782` outright". Taken literally that
> leaves the exec block's `depends_on` in compose **short-form**, which waits
> only for the target container to *start* — not for its healthcheck. Postgres
> accepts connections measurably later than it starts, so the first
> `docex migrate` against a cold `dev` stack would race the database and surface
> as a flaky migration rather than as a compiler bug. That is the exact failure
> the kickoff's GATE names.
>
> It is also a **doctrine violation**, not merely a regression:
> `migrations.md § Dev and Test Mechanism` and
> `cicl.md § Startup ordering is not a doctrine feature` both state the exec
> block carries its edges "rewritten to `condition: service_healthy`".
>
> The mechanism must therefore be retained. It does **not** need to be a second
> pass: the pass exists only because a dependency's condition depends on whether
> the target block already carries a `healthcheck` key. By the time the exec
> loop runs (`compose.py:698`) every core, replica, backing, and sidecar block
> is already in `services` — verified by reading the emission order — and exec
> deps are backing-targeted by construction. So the condition can be resolved
> **inline in the exec loop**, and the second pass disappears entirely.
>
> Net effect is exactly what the kickoff intends: the loop over *every* block is
> gone, `756-782` as written is gone, and the one surviving derivation lives at
> the single site that is allowed to have it. `simple_to_global` shrinks to the
> exec loop's local use.

**(d) `hcl.py:845,879,915`** — the three `body.pop("depends_on", None)` strips on
the RDS / ElastiCache / S3 renderers become unreachable once (a) lands. Deleted:
they name a key the compiler can no longer produce, and leaving them is stale
vocabulary in the elastic emitter.

After this mod, **`grep -n 'depends_on:' infra/output/*/docker-compose.yml`
across both smoke projects returns hits only inside `-exec` blocks.** That grep
is the mod's acceptance test and is listed in Verification below.

### 6. Derived readers key on target kind

| Site | Change |
| ---- | ------ |
| `dag.py:95-100` | edge kind from target kind: `uses_backing` → solid `->`, `uses_core` → dashed `..>` |
| `dag.py:153-159` | headings become "uses edges (backing target) — solid:" / "uses edges (core target) — dashed:" |
| `dag.py` module docstring, `collect_edges` docstring | rewritten; the flat-pass / no-traversal reasoning is kept verbatim, since a `uses` graph is still cyclic |
| `llm.py:51-54` | keys `depends_on` / `consumes` → `uses_backing` / `uses_core` |
| `check.py:352-380` | provider set = (**core**-targeted `uses`) ∪ (`web`-network core service). Both arms load-bearing, unchanged |
| `check.py:445-460`, `:503-542` | fan-out and probeability read `core_uses()`. Comments citing rule 24 rewritten to cite the sink property |
| `release.py:217-259` | **field rename only** — `svc.consumes` → `svc.uses_core`. Mod 114 owns this predicate's logic |

`check.py`'s three gates read the **authoring** model, so they use
`core_uses()`. `release.py` and `dag.py`/`llm.py` read the **compiled** model,
so they use `uses_core` / `uses_backing`. Nothing needs a target-kind lookup at
the point of use.

### 7. `CURRENT_CICL_VERSION = "3"` and its two stale messages

`model.py:30` moves to `"3"`. Two messages go stale in the same instant:

- **`model.py:322-329`** — the `"1"` branch currently tells the operator to
  "set `cicl_version: \"2\"`" and describes the v2 shape as adding "the
  `consumes` relation". Rewritten: end at `"3"`, name the `uses` relation, keep
  both guides in the chain (1.6.0 then 1.7.0).
- **`rollback.py:296-316`** — `_boundary_message` special-cases `None`/`"1"` as
  "the CICL v1→v2 boundary" and closes with the reassurance *"once a second
  cicl_version "2" release exists, rollback works normally"*. Under `"3"` a
  target declaring `"2"` falls into the **generic** branch, which is accurate
  but drops exactly the reassurance the situation calls for. Generalized:
  any recognized older generation (`None`, `"1"`, `"2"`) gets the boundary
  message parameterized on the target's own generation and the current one, with
  the reassurance line intact; anything unrecognized keeps the generic branch.

> **Known trap, deliberately not papered over.** Once the constant moves, every
> existing tagged release declares `"2"`, so `rollback` aborts
> (`rollback.py:135-146`) until a second v3 release exists. This is expected and
> precedented (`upgrade_1.6.0.md:463-484` documents the same trap for the
> previous bump). **The precondition is not weakened.** This mod's only
> obligation is that the message it produces is intelligible — which is what
> the `_boundary_message` generalization above delivers. Disclosure in the
> upgrade guide belongs to **Mod 117**.

### 8. Fixtures and smoke projects

Both smoke projects' `infra/infra.yml` and all test fixtures move to `uses:` +
`cicl_version: "3"` **in this mod**, so nothing in the tree is left
uncompilable between mod boundaries. The mechanical rewrite is:

```
depends_on: [a, b]  +  consumes: [x.y]   →   uses: [a, b, x.y]
```

— union on the same core service, and `depends_on` deleted outright from every
backing service. Checked-in compiled output under `infra/output/` is
regenerated, not hand-edited.

## Blast radius

Inventoried against the tree, not estimated. The per-module list goes into
`implementation.md` so the implementor works from a list rather than a grep.

| Surface | Extent |
| ------- | ------ |
| Source | 11 files, ~147 mentions — `cicl/{model,validate,compile}.py`, `emit/{compose,hcl}.py`, `describe/{dag,llm}.py`, `pipeline/{check,release,rollback}.py` |
| Tests | **22 modules, 285 raw hits**; ~82 test functions assert on the fields directly, ~160 more ride on a module-level fixture constant that merely *contains* `depends_on:` |
| Fixtures | **4** `infra.yml`s (not 5), all `cicl_version: "2"`, none declaring `consumes:` — every hit is `depends_on: [appdb]`. Two of the four are `sample_project_scheduler_{fixed,elastic}`, which **Mod 116 deletes** |
| Smoke projects | both `infra/infra.yml`; **only `elastic` has committed `infra/output/`** (`fixed` has none), and 8 compose blocks there carry `depends_on:` |
| Transfer tables | **zero** mentions — both fields are handled outside the table mechanism, so no role table changes |

**Where the test delta comes from** (all against the 995 figure):

- `test_consumes_relation.py` — 36 tests, and the module *is* the split. Its
  centrepiece,
  `test_12_consumes_cycle_is_legal_while_a_depends_on_cycle_is_fatal`, plus six
  tests pinning "neither branch is satisfiable by the other", lose their
  subject outright. Rewritten as `test_uses_relation.py`, materially smaller.
- `test_service_expansion_emit.py::test_consumes_reaches_no_emitted_artifact`
  asserts `"consumes" not in <emitted>`. It **survives and strengthens**: the
  assertion becomes `"uses" not in <emitted>`, which is now true of the *whole*
  relation rather than half of it — rule-of-record item 3, pinned.
- `test_contract_health_gates.py::test_fanout_required_without_depends_on`
  becomes void — there is no second field for the fan-out not to key on.
- `test_describe.py` — 9 tests asserting two edge kinds by literal heading
  string; the headings change, the count roughly holds.
- `test_service_nesting.py` (rule 24, 4 tests) and `test_validate.py`
  (`rule_6_depends_on_cycle`, `rule_7_magic_ref_implies_depends_on`) — rule-24
  and cycle coverage deletes; rule-7 ids merge two into one.

A net decrease is therefore expected and correct. The implementation must
account for it test-by-test.

## Verification

1. `pytest tests/unit` green. Delta stated against **995** and explained
   test-by-test in the implementation's closing step — a large delta is expected
   (rule 6 and 24 coverage deletes; two rule-7 ids merge into one), an
   *unexplained* delta is not.
2. `pytest -m integration` green.
3. **The central claim.** Compile both smoke projects for all four envs and grep
   every compiled `docker-compose.yml` for `depends_on:`. The **only** permitted
   hits are inside `-exec` blocks, and each must be long-form with a
   `condition:`. A hit on any other block fails the mod.
   Note the asymmetry found during inventory: **`fixed` has no committed
   `infra/output/`**, so it must be compiled fresh for this grep; `elastic` has
   9 tracked output files of which two compose files carry 8 `depends_on:`
   blocks today, and those are regenerated. Four of the eight are already
   `-exec` blocks and stay; the four on `api-web` / `api-worker` must vanish.
   Also ignore `output/project/production/main.tf:64`, which contains the word
   "consumes" in prose.
4. **The migrate gate.** See the finding below — the existing suite does **not**
   prove it, so this mod adds the test that does.

> ### Finding: nothing in the current suite would catch a migrate-gate regression
>
> `tests/integration/test_migrate_real.py` is the only test that runs a real
> migration, and it calls `run_up(...)` **before** `run_migrate(...)`. The
> database is already up and healthy by the time migrate runs, so the test
> passes whether the exec gate is `service_healthy`, `service_started`, or
> absent. `pytest tests/unit` cannot see it either — it is a runtime race.
>
> So a regression here would survive both suites and first appear during a smoke
> walk as an intermittent migration failure, which is exactly the misdiagnosis
> the kickoff's GATE warns about.
>
> Two guards, both in this mod:
>
> 1. **Emission-level, unit.**
>    `test_exec_service.py::test_7_depends_on_is_long_form_and_health_gated`
>    (`:94-109`) already asserts the exec block is long-form and health-gated.
>    It is renamed, **not weakened**, and is the reason § 5(c) keeps the
>    long-form derivation instead of deleting it.
> 2. **Behavioural, integration — new.** A `@pytest.mark.integration` test that
>    invokes `run_migrate` on a **cold** stack, with no prior `run_up`, so
>    `compose run` must bring the database up and the gate is the only thing
>    standing between the migration and a refused socket. This is the check the
>    GATE actually asks for, and it did not exist before.
5. No `git grep -n 'depends_on\|consumes'` hits remain in `src/` except the
   compose `depends_on:` **key name** on the exec block, which is Docker's word,
   not CICL's.

## Drift handed forward

Knowingly created here; not this mod's to fix.

| Drift | Owner |
| ----- | ----- |
| `rule_25_uses_scheduler` kept in code though committed rule 25 carries no scheduler clause | **Mod 116** |
| `check.py`'s `role == "scheduler"` exemptions (`:390`, `:481`, `:508`, `:529`) kept | **Mod 116** |
| `release.py:246`'s scheduler comment kept | **Mod 116** |
| Code rules 26/27 still keyed on `scheduler`; doctrine says `clock` | **Mods 115–116** |
| `release.py`'s reconcile *predicate logic* untouched — rename only | **Mod 114** |
| `doctrine_excerpts/index.yml` gains no `uses` entry | **Mod 118** |
| `upgrades/upgrade_1.7.0.md` not completed; root `CHANGELOG.md` gets a brief `[Unreleased]` line only | **Mod 117** |
| `docex/plans/core/compiler.md` (l.57, 58, 260, 341, 355, 356, 482, 489, 490, 491), `masterplan.md` (l.239–249), `test_projects.md` (l.16) updated for this mod only | sweep in **Mod 118** |
| `sample_project_scheduler_{fixed,elastic}` fixtures migrated to `uses:` here rather than deleted — **Mod 116** deletes them, and leaving them uncompilable in the interim would red the suite at this mod's boundary | **Mod 116** |
| `skill_iter/eval/outcome/infra-compile/evals.json:7,11` hard-code *"adds `cache` to web's `depends_on`"* as expected output, and `skill_iter/eval/queries.json:70` asks for `depends_on`. **These will fail their outcome eval after this mod.** Not caught by either pytest suite | advance **close-out** (the skill-eval decision sarge already flagged) |
| `upgrades/upgrade_1.6.0.md` § 6 documents the now-retired split. Historical guide — superseded, not edited | **Mod 117** |

## Design questions — all three ruled on, approved

> **Ruling (sarge, at design review).** All three approved.
> **(1)** `rule_25_unresolved_uses` stands — the doctrine fixes rule *numbers*,
> not issue ids, and what mattered was the check surviving.
> **(2)** The derived split is approved **on the condition that it is derived in
> exactly one place**, carries a WHY comment stating the split is derived from
> target kind rather than authored, and makes it impossible to build a
> `CompiledService` whose edge landed in the wrong list. § 1 above was rewritten
> to satisfy this structurally — one stored field, two derived properties.
> **(3)** The cold-stack integration test is approved without reservation: a
> test that cannot fail is worse than a missing test, because it reads as
> coverage.
>
> Also ruled: the brief's "delete `compose.py:756-782` outright" **was wrong**
> and this mod implements the § 5(c) resolution instead. `skill_iter` and the
> `fixed` project's absent `infra/output/` are logged to the close-out and to
> this mod's report respectively — neither is fixed here.

The questions as originally raised, kept for the record:

**1. Issue id for the surviving unknown-target check.** I have folded
`rule_6_unknown_depends_on` into **`rule_25_unresolved_uses`** rather than
inventing a new id, on the reasoning that rule 25 already owned the
unknown-*core*-target case and an entry naming nothing that exists fails rule
25's own sentence. Doctrine fixes rule numbers, not issue ids, so I treated this
as within my authority — flagging it because the kickoff singled the check out
and a veto here is cheap.

**2. The compiled model keeps a two-list split (`uses_backing` / `uses_core`).**
Reasoning in § 1. This is a derived precomputation, not a surviving authored
split, and it is what makes "release.py: field rename only" literally
achievable. If you would rather see one compiled list with target-kind resolved
at each read site, say so before implementation — it is a different shape for
six call sites and much harder to undo afterwards.

**3. Adding an integration test to a mod scoped as a compiler change.** The
migrate gate finding above means I am proposing a **new** cold-stack
`@pytest.mark.integration` test, which is slightly outside "make the executor
match the rule". I judge it in scope — `docex_process.md` step 2.2 says to add
an integration test "when behavior crosses a real boundary", and this mod makes
the exec gate the *only* ordering emission in existence, so the boundary it
crosses is now load-bearing in a way it was not before. Flagging it because it
adds runtime to the integration suite and because you may prefer it deferred to
the close-out walks. **Default: I include it.**

**Nothing here requires a doctrine edit.** Mod 112's output stands unmodified.
