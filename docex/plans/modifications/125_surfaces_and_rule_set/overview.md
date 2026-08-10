# Mod 125 — `surfaces` in the model, and the rule set

First mod of [advance 006](../../advances/006_surfaces_and_health/advance_plan.md).
Teaches the CICL **language** about surfaces: a `Surface` model, `CoreService.surfaces`
as a real declared field, and the rule-set changes for both halves of the advance —
new rules 29–33, rule 28 deleted and tombstoned.

**Territory.** `src/docex/cicl/model.py` and `src/docex/cicl/validate.py`, plus their
tests and the `tests/fixtures/sample_project*` `infra.yml` files. Nothing else.
`pipeline/check.py`, `tables/`, `emit/`, and `test_projects/` belong to mods 126–130
and are not touched.

**Rule of record.** The doctrine is already committed and authoritative:
[`cicl.md § Surfaces`](../../../../doctrine/infrastructure/cicl.md#surfaces),
[`§ Validation Rules`](../../../../doctrine/infrastructure/cicl.md#validation-rules)
rules 28–33, [`contracts.md`](../../../../doctrine/infrastructure/contracts.md),
[`healthchecks.md`](../../../../doctrine/infrastructure/healthchecks.md). This mod
changes no doctrine file.

---

## 1. `cicl/model.py`

### 1.1 The style → format table

```py
API_STYLE_FORMATS = {
    "rest": "openapi", "stream": "openapi", "webhook": "openapi",
    "rpc": "asyncapi", "events": "asyncapi", "socket": "asyncapi",
    "graphql": "graphql", "grpc": "proto",
}
IMPLEMENTED_CONTRACT_FORMATS = frozenset({"openapi", "asyncapi"})
```

Transcribed from `cicl.md § Surfaces`'s table, which is the source of truth. It lives
in `model.py` rather than `validate.py` because **mod 126 needs the same table** to
resolve a surface to a contract filename; two copies of a doctrine table is precisely
the drift surface `docex_process.md` warns about. Rule 29 is *derived* from this table
(`len({format(s) for s in api_styles}) == 1`) and never tabulates legal style pairs, so
it cannot rot as styles are added.

`IMPLEMENTED_CONTRACT_FORMATS` is deliberately a separate set rather than an absence
from the table: `graphql` and `proto` are *defined language*, and a project declaring
one must be told "not yet implemented", not "unknown style"
(`surfaces_and_health.md` resolved decision 3).

### 1.2 `Surface`

```py
class Surface(BaseModel):
    model_config = ConfigDict(extra="forbid")
    api_styles: list[str] = Field(min_length=1)

    def formats(self) -> set[str]: ...   # resolved formats; unknown styles omitted
```

Sibling in size and shape to `GPUSpec` / `Resources`. `extra="forbid"` on purpose —
`api_style:` (singular) is the typo this field invites, and it must fail loudly rather
than be ignored. `min_length=1` makes `api_styles: []` a pydantic error, so rule 29
never has to reason about the empty set.

`formats()` is the only accessor added. It is what rule 29 tests for singularity and
what mod 126 will read to name a contract file. No further API is built on
speculation — per-surface `port` is deferred by
[resolved decision 4](../../advances/006_surfaces_and_health/surfaces_and_health.md#resolved-decisions)
and nothing here anticipates it.

### 1.3 `CoreService.surfaces`

`surfaces: dict[str, Surface] = Field(default_factory=dict)`, declared beside `uses`.

This must be a **real declared field**, not an accepted extra. `CoreService` is
`extra="allow"`, so an authored `surfaces:` today lands in `model_extra` and resurfaces
as `tt_rule_4_undeclared_field` — a message about transfer-table field declarations,
which is the wrong answer to a correctly-authored block. Absent (`{}`) is the honest
default: declaring no surface is what makes a core service a non-provider, which is
exactly a `clock`'s state.

### 1.4 Surface names (rule 30)

Validated inside `CICLDocument._validate_service_names`, nested in the existing
core-service-name loop, against the existing `_SERVICE_NAME_RE`. **Reused, not
reinvented**: that pattern is already dot-free, and dot-freeness is the property that
keeps the four-segment contract path (`api.web.rest.openapi.yml`) unambiguous under a
right-anchored parse. A second pattern would be a second place for that property to
drift.

Like rule 5's name pattern, this raises a pydantic `ValueError` rather than emitting a
`rule_30_*` `ValidationIssue`. That is the existing convention for *name-shape* rules
(rule 14's blacklist is the aggregated-issue one, and it is a different kind of check),
and the mod brief directs this placement.

---

## 2. `cicl/validate.py`

### 2.1 `_STANDARD_SERVICE_FIELDS` gains `"surfaces"`

Without this, every project that declares a surface trips
`tt_rule_4_undeclared_field`. Mechanical, but load-bearing — it is the reason 1.3 and
this line are one mod.

### 2.2 Rule 29 — one contract format per surface

Registered as `_validate_surfaces(doc)`. Three issue ids:

| id | fires when |
| -- | ---------- |
| `rule_29_unknown_api_style` | a style is absent from `API_STYLE_FORMATS` |
| `rule_29_mixed_contract_formats` | `len(surface.formats()) > 1` — message says *split this into two surfaces* |
| `rule_contract_format_not_implemented` | the resolved format is `graphql` or `proto` |

Sub-ids under one number follow `rule_25_*`'s precedent. The third id is **un-numbered**
because the doctrine states it in `contracts.md` prose rather than in the numbered rule
list, matching `rule_uses_on_backing_service` / `rule_clock_schedules_required`.

`[rest, stream, webhook]` passes. `[rest, rpc]` fails.

### 2.3 Rule 31 — a `uses` target declares a surface

A **third clause inside `_validate_uses`**, after the existing target-resolution
branches. Justification for nesting rather than a sibling function: `_validate_uses`
already parses the ref and resolves the target `CoreService`, and it already decides
which malformed entries to stop reporting on. A sibling function would re-walk and
re-resolve — duplicating both the parse and the drop-malformed policy — and would make
a typo'd `uses:` entry report *twice*: once as rule 25, once as a mystifying "declares
no surface" for a target that does not exist. The rule reads off exactly what the
function already has in hand.

Id: `rule_31_uses_target_declares_no_surface`.

### 2.4 Rule 32 — a directly-addressed target declares a `port`

**This is the mod's escalated decision; see [Design questions](#design-questions) Q1/Q2.**
Recommended shape, implemented as its own function `_validate_uses_addressing(doc)`:

*Detection.* A consumer addresses a target **directly** iff it holds a magic ref to
that target — `${codebases.<cb>.core_services.<svc>.<part>}` — in its effective `env:`,
its `command`, or any role-specific field. The magic-ref walk is factored out of
`_validate_magic_refs` into a shared `_ref_templates(cb, svc)` helper so there is one
template-collection expression, not two.

*Positive arm.* Target addressed directly by at least one of its consumers and
`port is None` → `rule_32_direct_target_needs_port`.

*Negative arm.* Target is some core service's `uses` target, no consumer addresses it
directly, it is **not on the `web` network**, and it declares a `port` →
`rule_32_unaddressed_target_declares_port`.

*Why the `web` carve-out is mandatory.* Rule 15 requires a `port` on every
`web`-network core service. A `frontend.web` that `uses: [api.web]` reaches it by
public URL from `config:` — the browser cannot resolve an internal hostname — so it
holds no magic ref, and without the carve-out rules 15 and 32 would contradict each
other on the single most common two-codebase topology in the doctrine.

Rule 32 stays in one function rather than splitting its positive arm into
`_validate_uses`: the negative arm needs a document-wide aggregation (*every* consumer
of a target, plus every core service's magic refs), which `_validate_uses` does not
have and should not grow.

### 2.5 Rule 33 — `health_check_path` is a `web`-network field

`_validate_health_check_path_port` (rule 28) is **deleted** and replaced by
`_validate_health_check_declaration`, keyed on **network membership, not role**:

| id | fires when |
| -- | ---------- |
| `rule_33_web_service_needs_health_check_path` | `"web" in networks` and the field is absent |
| `rule_33_health_check_path_off_web` | `"web" not in networks` and the field is declared |

A `role: web` core service off the `web` network declares none — the field is what the
reverse proxy reads, and there is no reverse proxy in front of it.

Rule 28's number is tombstoned in the module-docstring roster exactly as 6 and 24 are,
with its reasoning recorded: rule 33 confines the field to `web`-network services and
rule 15 already requires a `port` on those, so the old obligation is **redundant**
rather than merely obsolete.

---

## 3. Blast radius — measured, not estimated

A throwaway prototype of rules 31/32/33 was run against the suite and then reverted
(baseline re-confirmed at **1009 passed**). The findings drive the implementation plan
and are larger than the mod brief anticipated:

| Stage | Failures |
| ----- | -------- |
| Rules 31+33 wired, nothing else changed | **194 failed, 129 errors** |
| …after the five `sample_project*` fixtures are corrected | 40 failed, 22 errors |
| …plus rule 32 (both arms) | 41 failed, 47 errors |
| …after dropping `port:` from `worker` in the two clock fixtures | **40 failed, 22 errors** |

Two conclusions worth stating:

1. **Almost all of the initial 323 is one missing line per fixture.** Rule 33's
   required arm bites every fixture, because no bundled fixture's `api.web` declares
   `health_check_path` today.
2. **Rule 32's negative arm costs one fixture line and breaks nothing else.** A
   port-less `worker` compiles clean on both foundations — no emitter churn at all.
   This is the empirical case for enforcing that arm (Q2).

### 3.1 Fixture edits (all five `tests/fixtures/sample_project*`)

- `api.web` gains `health_check_path: /health` (rule 33, required arm).
- `worker` / `clock` lose `health_check_path` (rule 33, forbidden arm) — clock ×2,
  `sample_project_multi_fixed`'s `reporter.worker`.
- The two clock fixtures' `api.worker` gains `surfaces: {events: {api_styles: [events]}}`
  (rule 31 — `api.clock` uses it) and loses `port: 8081` (rule 32, negative arm: the
  clock reaches it through a queue and holds no magic ref to it).

### 3.2 Residual test edits (~62 items, 12 files)

Mechanical: inline `_BASE`-style documents gain a `surfaces:` block on any core service
that is a `uses` target, gain/lose `health_check_path` per rule 33, and lose a `port`
on queue-reached targets. Affected: `test_service_expansion_emit`,
`test_service_connect_reconcile`, `test_uses_relation`, `test_worker_role`,
`test_exec_service_resolution`, `test_validate`, `test_service_nesting`, `test_clock`,
`test_telemetry`, `test_pipeline_bootstrap`, `test_hcl_emitter`, `test_exec_service`.

**Four items are not mechanical**, and they are the ones that brush mod 127's
territory (see Q3):

| Test | Why it dies | Handling |
| ---- | ----------- | -------- |
| `test_worker_role::test_health_check_path_without_port_rejected` | rule 28 is gone | delete (with `_WORKER_DOC`, now unused) |
| `test_worker_role::test_health_check_path_with_port_passes` | rule 28 is gone | delete |
| `test_worker_role::test_web_service_unaffected_by_rule_28` | rule 28 is gone | delete |
| `test_worker_role::test_worker_fixed_compose_healthcheck` + `::test_worker_elastic_container_healthcheck` | a non-`web` worker can no longer declare `health_check_path`, so no probe is emitted for it at all | invert to assert **no** probe is emitted, tagged `# MOD 127:` — mod 127 flips them to `["CMD", "./health.sh", "worker"]` |
| `test_hcl_emitter::test_aws_lb_target_group_omits_health_check_when_no_field` | its premise — a `web`-network service declaring no `health_check_path` — is now unrepresentable | delete; rule 33 is what now guarantees the block is always present |

Nothing under `emit/` or `tables/` is edited. These are test-side consequences of a
validation rule, which is the only way a rule change can be proved to bite.

## 4. Tests added

- **`tests/unit/test_surfaces.py`** (new) — the `Surface` model (extras forbidden,
  empty `api_styles` rejected), the style→format table's agreement with `cicl.md`, and
  rules 29 / 30 / 31 / 32. Rules 31 and 32 live here rather than in
  `test_uses_relation.py` because both are *consequences of the surface model*: 31
  requires one, and 32's entire justification is what a consumer does with one.
- **`tests/unit/test_validate.py`** — rule 33 both arms, beside rule 15
  (`test_rule_web_service_needs_port`), its sibling; plus a tombstone comment for rule
  28 in the style of the existing rule-6 one.

Every new rule gets **a failing case and a passing case**. Advance 005's standing
lesson is that a verification step's pass is worthless until the step has been observed
failing, and that applies to a validation rule more literally than to anything else.
Specifically demonstrated red: `[rest, rpc]`; `api_styles: [graphql]`;
`surface.name` with a dot; a `uses` edge onto a surface-less target; a magic-ref-addressed
target with no `port`; a queue-reached target that declares one; a `web` service missing
`health_check_path`; a `worker` that declares one.

## 5. Out of scope, deliberately

- `pipeline/check.py` (mod 126). After this mod, `check.py:519`'s gate demands
  `health_check_path` on a core `uses` target, which rule 33 now forbids off the `web`
  network. `docex check` on the seed projects is therefore expected to fail between
  mods 125 and 126 — the advance plan already books this as a GATE, not a defect. No
  unit test covers that path, so the suite stays green.
- `tables/roles/{worker,clock}.yml`'s `health_check_path` field entries become
  unreachable-but-harmless here; mod 127 removes them.
- `plans/core/compiler.md` § Validation is updated in this mod's **documentation** step
  (it lists the rules). `masterplan.md`'s health-gate block is mod 131's.

---

## Design questions

### Q1 — how rule 32 detects "directly addressed" (the mod's mandated escalation)

**Recommendation: the magic ref, as you predicted. I read the code and it holds — with
one argument in its favour that is stronger than the "rule 7 already walks it" one.**

Rule 32's doctrine sentence is *"a `uses` target that **its consumer** addresses
directly declares a `port`."* The unit is the **edge**, not the target. Two consumers
can legitimately reach one target differently: `api.web` calls `api.worker`'s RPC
surface directly while `api.clock` enqueues to it through a broker. A style-derived
mapping is per-*target* and structurally cannot express that; it must collapse the two
edges into one answer. The magic ref is per-edge and asks the actual question.

The style-derived alternative fails on three further counts:

1. **The mapping does not exist in the doctrine.** `cicl.md` rule 32 states a
   principle; `contracts.md` and `healthchecks.md` state the same principle; no file
   anywhere gives a style→addressability table. Implementing style-derived means
   *inventing* that table, which is above my authority and exactly the drift the
   "derived, never tabulated" language of rule 29 exists to prevent.
2. **A mixed-surface target is ambiguous under it.** A core service declaring both a
   `rest` surface and an `events` surface has no style-derived answer; the only
   tie-break ("any direct-capable style ⇒ port required") forces a port onto a worker
   whose only actual consumer enqueues.
3. It re-couples `api_styles` to a deployment-shaped consequence, which Part I of the
   design record spends a paragraph forbidding — and the record's own escape hatch
   ("this is a validation consequence, not deployment config") reads much more
   comfortably over the magic-ref reading than over a style table.

The magic ref is also *free*: `find_magic_refs` + the existing template walk already
produce the whole set, and the doctrine's own § Rules item 2 ("when services
communicate over URLs, those URLs are built from provided fields at startup") makes
"holds a magic ref to it" the doctrine-sanctioned definition of addressing an
in-project service. A consumer that addresses a sibling by hard-coded hostname is
already violating that rule; rule 32 declining to bless it is correct.

**No contradiction with your prior. Ruling requested only to close it formally.**

### Q2 — does rule 32's negative arm get enforced?

Doctrine rule 32's second sentence is *"A target reached only through a queue or broker
declares none — there is no address at which a consumer reaches it, so a port would be
decoration."* Rule 33 states its negative arm as an explicit conjunction (`"and no core
service off the web network declares one"`); rule 32 states it as a following sentence.
Both are in the same normative voice, so I read both arms as normative — but the
grammatical difference is real and this is your call, not mine.

**Recommendation: enforce it, with the `web`-network carve-out from § 2.4.** Reasons:

- It is what makes mod 129's *"loses `port`/`health_check_path` on `worker` and
  `clock`"* a requirement rather than a tidy-up. Without it, a decorative port on a
  queue-reached worker stays legal forever and the seed projects' shape becomes
  advisory.
- Measured cost: **one fixture line, zero emitter churn** (§ 3).
- The false-positive hazard is closed by doctrine rather than by luck: the only way to
  address an in-project core service *without* a magic ref is to violate `cicl.md`
  § Rules item 2.

**Known asymmetry, stated plainly:** the arm is scoped to `uses` *targets*, because
that is the scope of the doctrine's sentence. A `worker` that nobody uses may still
declare a pointless `port`. I am not extending the rule past its sentence to close
that; if you want it closed, it is a doctrine edit, not a validator edit.

Fall-back if you rule against: positive arm only. Strictly smaller, no fixture change
beyond § 3.1's surfaces, and rule 32 still catches the failure that actually breaks a
deployment (a consumer with nothing to connect to).

### Q3 — five test deletions/inversions that touch mod 127's ground

Rules 33 and 32 make three inputs *unrepresentable*, which kills five tests whose
subject is emitted output rather than validation (§ 3.2). I propose to delete three
(rule 28's own tests, which have no subject left), delete one (`test_hcl_emitter`'s
"omits health_check when no field" — rule 33 now guarantees the field is present on
every service that gets a target group), and **invert** two to assert that a non-`web`
worker gets no container probe at all, tagged `# MOD 127:` with the literal that
replaces them.

The inversion is the part I want signed off: for the two mods between here and 127,
`docex` genuinely emits no probe for a `worker` or `clock`, and asserting that
truthfully is better than deleting the coverage — but it does mean mod 127 must flip
two assertions it would otherwise only extend. Say the word and I will delete them
instead and let mod 127 write them fresh.

### Q4 — no question, one note for the record

`cicl.md § Service Fields` lists the row as `surface` (singular) where the field is
`surfaces:`. This is already booked as an operator-owned defect in the advance plan; I
am implementing `surfaces:` per § Surfaces and rules 29–31, and touching no doctrine
file.

---

## Rulings (sarge, at design review)

Recorded here so they are not re-litigated during implementation or review.

1. **Q1 — magic ref, edge-scoped. Approved, and the *edge* argument is the reason of
   record**, superseding "rule 7 already walks it" (which is an argument about cost, not
   correctness). Both the implementation doc and the code comment state the edge
   argument first. Sarge's cost argument is a footnote to it. The observation that no
   doctrine file gives a style→addressability table is independently decisive:
   style-derived would mean inventing doctrine.
2. **Q2 — enforce both arms, with the `web`-network carve-out. Approved**, with three
   directives:
   1. The carve-out carries a `WHY` comment naming the tension it resolves (rule 15
      vs. rule 32 on the `frontend.web → api.web` topology), so no future reader can
      mistake it for laxity.
   2. **The carve-out gets its own test**, not merely the two arms: `frontend.web`
      `uses: [api.web]` with no magic ref, `api.web` on `web` with a port → **no
      issue**. An unpinned carve-out is a carve-out that gets deleted by someone
      reading only the doctrine sentence.
   3. The declined asymmetry (a `uses`-less worker may keep a decorative port) **stays
      declined** — extending a rule past its sentence is a doctrine edit wearing a
      validator's clothes. Written up instead as
      [`007_small_edges/rule_32_unused_target_port.md`](../../advances/007_small_edges/rule_32_unused_target_port.md).
      Sarge separately raises the rule-15/32 text tension with the operator; nothing
      here blocks on it.
3. **Q3 — invert the two, delete the other three plus the `test_hcl_emitter` one.
   Approved.** Reason of record: an inverted assertion is better than both alternatives
   *because mod 127 makes it fail loudly*. A deletion loses coverage silently; an
   `xfail` flips to `XPASS`, which reads as noise; an inverted assertion mod 127
   contradicts stops the suite at exactly the moment attention is warranted. The
   `# MOD 127:` tag must be greppable — `grep -rn "MOD 127:"` finds every one — and
   carries the replacement literal verbatim.
4. **`IMPLEMENTED_CONTRACT_FORMATS` is enforced in *this* mod**, with its own named
   issue id — not deferred to mod 126's gate. A `graphql`/`proto` surface is a
   *compile* error per resolved decision 3; if the check landed only in `check.py`,
   `docex compile` would accept it and the honesty of the boundary would be lost.
5. **The ~62-item fixture sweep is the largest mechanical surface in the mod.** If it
   threatens the context ceiling, **stop and report rather than compact mid-mod** — a
   mod 125b is cheap, a compaction is not.
6. `API_STYLE_FORMATS` in `model.py` for mod 126 to share is confirmed correct: one
   copy of a doctrine table, per `docex_process.md`.
