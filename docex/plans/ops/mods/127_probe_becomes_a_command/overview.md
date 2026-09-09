# Mod 127 — the probe becomes a command

Third mod of [advance 006](../../advances/006_surfaces_and_health/advance_plan.md).
Mods 125 and 126 taught CICL and `docex check` about surfaces and cut the health
half of the gate roster down. This mod moves the thing those gates used to talk
about: the container probe stops being a curl at an HTTP route derived from a
project field and becomes `./health.sh <service>`, emitted for every core service
on both foundations from the role tables' `defaults`.

**Territory.** `tables/roles/{web,worker,clock}.yml`; one function in
`src/docex/cicl/magic_refs.py`; two strings and one comment in
`src/docex/pipeline/release.py`; one comment clause in `src/docex/cicl/validate.py`;
one comment in `src/docex/emit/compose.py`; **one behavioral change in
`src/docex/emit/hcl.py`** ([Q1](#q1--the-elastic-probe-cannot-reach-the-container-through-a-merge-target)),
and the tests for all of it.

**Not touched.** `pipeline/stagetest.py` (mod 128), `test_projects/` (mods 129–130),
`pipeline/check.py` (done, mod 126), `plans/core/masterplan.md` § *The contract and
health gates* (mod 131). No doctrine file is edited; two doctrine findings are
raised in [§ 8](#8-doctrine-findings--raised-and-routed).

**Rule of record.** Already committed and authoritative:
[`healthchecks.md`](../../../../doctrine/infrastructure/healthchecks.md) — *"The
compiler emits `health.sh <service>` as the container-level health check on both
foundations: a `healthcheck:` block on `fixed`, a container `healthCheck` in the
task definition on `elastic`"*; and
[`transfer_tables.md`](../../../../doctrine/infrastructure/specifics/transfer_tables.md)
— *"The container probe is a default, not a field."*

**Baseline, re-derived not inherited.** Unit **1041 passed**; integration
**18 passed, green**. Both measured on this branch at `fa5d3fb` rather than carried
from advance 005's report — which is the habit that found the rotted integration
member in mod 126.

---

## 1. What actually changes in the three role tables

Identical edit in all three, plus one deletion that differs by role.

### 1.1 The probe, in `defaults`, on both foundations

```yml
      defaults:
        fixed:
          healthcheck:
            test: ["CMD", "./health.sh", "${service}"]
            interval: 30s
            timeout: 5s
            retries: 3
        elastic:
          launch_type: FARGATE
          network_mode: awsvpc
          healthCheck:
            command: ["CMD", "./health.sh", "${service}"]
            interval: 30
            timeout: 5
            retries: 3
            startPeriod: 10
```

The fixed block is `transfer_tables.md`'s worked example verbatim. Cadence is
doctrine-fixed and uniform; it is not a project-tunable field, and nothing in
`infra.yml` reaches it.

Three things about this that are decided rather than obvious:

1. **`${service}`, not `${service_name}`.** `compile.py:755` supplies `"service"`.
   Confirmed independently of the doctrine fix at `fa5d3fb` by reading the context
   construction, not by trusting the commit message.
2. **`CMD`, not `CMD-SHELL`, on elastic.** The retired worker/clock blocks used
   `CMD-SHELL` because they wrapped a curl in a `|| exit 1`. A command probe needs
   no shell and no exit-code laundering; `CMD` is exec-form on both foundations,
   which is what makes the two emissions read as one translation. Both foundations
   resolve `./health.sh` against `WORKDIR /service`, which
   [`infrastructure.md § Codebase Containers`](../../../../doctrine/infrastructure/infrastructure.md#codebase-containers)
   fixes for every codebase image.
3. **`startPeriod: 10` survives on elastic and has no fixed counterpart**, because
   **the two orchestrators do different things with a failing probe**. See
   [Q2](#q2--the-startperiod-asymmetry-rests-on-mechanism) for the verification;
   the short form is that ECS *kills and replaces* a task whose essential container
   fails, so a start grace protects against a real consequence, while Docker only
   *reports* — nothing on fixed acts on `unhealthy` except traefik, which drops the
   container from its pool, which is the behavior you want from a container that is
   not ready yet.

### 1.2 The `${service}` = `None` hazard, satisfied rather than assumed

`contexts[key]["service"]` is `svc_name`, which is `None` for a backing service
(`compile.py:755`, deliberately — `standard_tags` omits the `service` tag for
backing). A `${service}` template reaching a backing engine would therefore
substitute against `None`.

It cannot bite here for two independent reasons, and the second is the one worth
having:

1. **Structurally.** Only `web`, `worker`, and `clock` carry the template, and all
   three are core-only roles. A backing service never resolves one of these engines.
2. **And if it ever did, it fails loudly.** `substitute.py::_resolve_compile_time`
   raises `SubstitutionError` on a `None` context value — explicitly, with the
   template quoted — rather than emitting the string `"None"`. So the failure mode
   of the hazard is a compile error naming the template, not a container probing
   `./health.sh None`. This is pinned with a test ([§ 5](#5-tests)), because "it
   cannot happen" and "it fails safe if it does" are different claims and only the
   second survives a future table author.

### 1.3 `health_check_path` narrows to `web`

- **`web.yml`** keeps *only* the `elastic:` → `target_group` translation. Its
  `fixed:` translation — the curl block — is deleted outright. On fixed, traefik
  takes target health from the container healthcheck, so the field has no fixed
  consumer; it is still *declared* on the engine so rule 4 accepts it in a fixed
  project's `infra.yml`, which is what keeps a project portable across foundations.
  Rule 4 (`_validate_role_specific_fields`) unions field *names* across engines with
  no foundation filter, and `field_translation` returns `None` for an absent
  foundation which `compile.py` skips gracefully — verified in both functions, not
  assumed.
- **`worker.yml`** and **`clock.yml`** lose the field entirely. `worker`'s `fields:`
  becomes an empty mapping; `clock`'s keeps `schedules`. Rule 4 then rejects
  `health_check_path` on those roles, which is how
  [rule 33](../../../../doctrine/infrastructure/cicl.md#validation-rules)'s negative
  arm is enforced at the table layer with no second rule — the same mechanism
  `clock.yml` already documents for `schedules`.

`container_definition` **stays** in `worker`/`clock`'s `emits.elastic` even though
no shipped field routes to it any more. It is a declaration of an available
destination, its renderer emits nothing, and deleting it would be a capability
removal this mod was not asked for. See [§ 8](#8-doctrine-findings--raised-and-routed)
for the doctrine sentence this leaves stale.

### 1.4 The `provides:` comments

`worker.yml` and `clock.yml` both justify `provides.port` by the fan-out — *"which
is what lets a sibling `web` core service reach its /health one hop away."* The
justification is retired; the field is not. Reworded to the surviving reason: a core
service that declares a `port` is Service-Connect-discoverable, which is what lets a
consumer holding a magic ref to `<target>.host`/`.port` address it — rule 32's
positive arm. Nothing about `provides` changes.

---

## 2. The elastic delivery path — the one real mechanism decision

This is [Q1](#q1--the-elastic-probe-cannot-reach-the-container-through-a-merge-target)
and it is the only thing in this mod outside a corporal's authority. Stated here in
full because the design depends on the answer.

**The brief says the elastic probe "reaches the container def through the
`container_definition` merge target." It structurally cannot**, and the reason is
in the doctrine rather than in a bug:

> `transfer_tables.md § Anatomy of a Role Definition`: *"`defaults:` cannot route to
> a non-default target — that's what `fields:` translations with `target:` are for."*

`compile.py:800-802` implements exactly that: `body = engine.defaults_for(foundation)`
lands unconditionally on `engine.default_target(foundation)`, which for all three core
roles on elastic is `task_definition`. There is no `target:` key in a `defaults` body
and adding one would contradict the sentence above.

**And landing on `task_definition` is not by itself sufficient**, which is the part
recon missed. `emit/hcl.py::render_task_definition` does *not* pass `body` through;
it builds its container definition key-by-key and reads only the keys it names —
`cpu`, `memory`, `ephemeral_storage`, `image`, `command`. A `healthCheck` in `body`
would be silently dropped. The proof that this is a real hazard rather than a
theoretical one is sitting in the tables already: **`defaults.elastic`'s
`launch_type: FARGATE` and `network_mode: awsvpc` are never read by anything.** The
renderer hardcodes `requires_compatibilities = ["FARGATE"]` and
`network_mode = "awsvpc"` at `hcl.py:522-523`. Every core role's elastic defaults
block is, today, inert decoration.

**Say this plainly, because it is worth more than this mod.** Three role tables have
carried instructions in the rule-executing layer that nothing executes, and nothing
ever noticed — for the same reason nothing ever *could*. It is the exact defect shape
advance 005 catalogued eight times: **something that could not answer, and silence
read as agreement.** A `healthCheck` added to `defaults.elastic` would have joined
them — compiling clean, emitting valid HCL, passing every gate, and shipping an
elastic fleet with no container probe at all, discoverable only by a walk. The
explicit read is not defensive tidiness; it is the difference between a probe that
exists and one that appears to.

**Proposed: an explicit read, mirroring `image` and `command`.**

```python
    # The container probe, per healthchecks.md § The orchestrator carries the
    # result. It arrives in `body` because the probe is a transfer-table
    # DEFAULT (transfer_tables.md: `defaults:` cannot route to a non-default
    # target), and a default lands on the engine's default target — which on
    # elastic is `task_definition`, i.e. this renderer.
    #
    # WHY an explicit read and not a body merge: `body` is NOT generically
    # consumed here. This renderer names every key it lifts onto the container
    # definition — `image`, `command`, `cpu`/`memory`/`ephemeral_storage` on
    # the task def, and this. Everything else in `defaults.<foundation>` is
    # INERT: `launch_type` and `network_mode` sit in all three core roles'
    # `defaults.elastic` and are read by nothing, because the task definition
    # hardcodes FARGATE/awsvpc below. Do not infer from `healthCheck` being
    # honored that a sibling key would be.
    #
    # WHY this position — ahead of the `container_definition` merge: a field
    # routed to that target must still override a table default, which is the
    # same precedence `_deep_merge(body, resolved)` gives on the default
    # target. Moving this read below the merge silently inverts it.
    healthcheck = body.get("healthCheck")
    if healthcheck:
        container_def["healthCheck"] = healthcheck
```

Placed immediately before `container_def.update(svc.target_extras.get("container_definition", {}))`
(`hcl.py:381`).

Why this is the doctrine-conformant shape rather than a workaround: `image` and
`command` are *both* container-definition keys already delivered through `body` and
lifted by this renderer. The container definition is part of the task-definition
resource; a default landing on `task_definition` and being placed on its container is
precisely "defaults land on the default target." No doctrine sentence is contradicted
and no new routing concept is introduced.

**Rejected alternatives**, recorded so they are not re-proposed:

| Alternative | Why not |
| --- | --- |
| Give `defaults` a `target:` key | Contradicts `transfer_tables.md` outright. |
| Reorder `emits.elastic` so `container_definition` is first | Makes it the default target, so `launch_type`/`network_mode` land there too. Worse, and the reordering is invisible at the call site. |
| Declare the probe as a `fields:` entry | There is no `infra.yml` field to hang it on, and `transfer_tables.md` says in terms that the probe is a default *and not* a field. |
| Leave it in `defaults.elastic` and ship | Silently emits no elastic probe at all, indistinguishable from success until a walk. |

Cost if approved: ~8 lines including the comment. Blast radius: backing services are
unaffected (no shipped backing engine declares `defaults.elastic.healthCheck`), and
the merge-target precedence is unchanged.

---

## 3. The verification that matters most — three derivatives that must not inherit

Asserted with tests, not by reading compiled output. Findings from reading the code,
each to be **pinned** regardless of which way it came out:

### 3.1 The fixed `-exec` block — **already safe by construction**

`emit/compose.py:538` builds `exec_block` as a fresh dict and reads exactly one key
off a core service (`head.body.get("image", "")`). It never copies `body`. So it
cannot inherit a `healthcheck:`, and it does not.

[`exec_service.md`](../../../../doctrine/infrastructure/specifics/exec_service.md) and
`healthchecks.md` both say plainly that it must not — *"its own liveness question is
answered by the exit code it was invoked for."* The consequence beyond tidiness is
the one the brief names: an exec block carrying a `healthcheck:` changes what
`depends_on: service_healthy` means for anything gating on it, and compose would
report a `--rm` one-shot as `health: starting`.

The block's `# Deliberately unset:` comment enumerates `container_name`, `logging`,
`command`, `restart`. **`healthcheck` is added to that list** with the doctrine
citation, so the invariant is stated where the code that maintains it lives, not only
in a test.

### 3.2 The elastic exec analogue — the `_migrate` task definition

`render_migration_task_definitions` (`hcl.py:568+`) is the elastic one-shot. Same
construction: key-by-key, no `body` pass-through, no sidecar. Pinned with the same
assertion shape.

### 3.3 The `-otelcol` sidecar — **already safe by construction, both foundations**

`_sidecar_block` (compose) and `sidecar_def` (hcl) are dict literals. Neither reads
`body`. Existing tests already assert absence
(`test_compose_sidecar::test_sidecar_has_no_healthcheck`,
`test_hcl_sidecar::test_sidecar_has_no_healthcheck`,
`test_worker_role::test_worker_elastic_sidecar_has_no_healthcheck`), but **two of the
three are about to become vacuous or wrong**:

- `test_hcl_sidecar::test_sidecar_has_no_healthcheck` asserts `"healthCheck" not in
  api_td` — the **whole `api-web` task definition**. Once `api-web` gets a probe this
  test fails for the right reason and is a genuine defect in the assertion, not in the
  code: it was written when no core container had a `healthCheck`, so slicing the task
  def was equivalent to slicing the sidecar. It narrows to the sidecar container block
  and gains a positive control (the app container *does* carry one), which is what
  makes it non-vacuous for the first time.
- The compose sidecar test gains the same positive control in the same document.

Mod 024's reason survives verbatim and is worth restating in the test: the collector
image is `FROM scratch` and carries no probe tool, so a probe there would leave
compose reporting `health: starting` forever
([`telemetry_infra.md:243`](../../../../doctrine/infrastructure/specifics/telemetry_infra.md)).

---

## 4. The `depends_on` predicate — confirmed untouched

`emit/compose.py:598-609`:

```python
exec_deps = sorted({d for p in svcs for d in p.uses_backing})
...
"service_healthy" if "healthcheck" in target_block else "service_started"
```

The predicate reads `target_block`, and `target_block` is resolved from
`exec_deps`, which is `uses_backing` — **backing services only**, by an accessor whose
partition is derived from `"." in entry` and cannot include a core service. Backing
healthchecks come from engine defaults (postgres `pg_isready`, minio, redis) and this
mod does not touch a single backing engine table.

So "every core service now has a healthcheck" does not reach this predicate. That is
the correct outcome and it required no change — but it is exactly the kind of
predicate that leaks, so it gets a test that would fail if a core service ever
appeared in an exec gate: **`depends_on` keys ∩ core-service compose keys must be
empty**, asserted in a document where every core service now demonstrably carries a
`healthcheck:`. The existing
`test_exec_gate_is_service_started_when_target_has_no_healthcheck` (project-local
no-healthcheck backing role) keeps proving the `service_started` arm and should still
pass unchanged; if it does not, the predicate leaked and the mod stops.

---

## 5. Tests

Every new assertion is demonstrated red before green, per advance 005's standing rule.

### 5.1 The three `MOD 127:` tags flip

`grep -rn "MOD 127:"` returning **zero hits in `tests/`** is a completion criterion.
The tags in `plans/modifications/125_*` and `126_*` are historical records of prior
mods and are not code; the grep criterion is scoped to `src/` and `tests/`, and this
is stated explicitly so the criterion is checkable rather than arguable.

| Test | Becomes |
| --- | --- |
| `test_worker_role::test_worker_fixed_compose_healthcheck` | `block["healthcheck"]["test"] == ["CMD", "./health.sh", "worker"]` plus interval/timeout/retries |
| `test_worker_role::test_worker_elastic_container_healthcheck` | the `api-worker` app container's `healthCheck.command == ["CMD", "./health.sh", "worker"]` |
| `test_clock::test_fixed_clock_is_an_ordinary_compose_service` | `block["healthcheck"]["test"] == ["CMD", "./health.sh", "clock"]` |

Each docstring loses the interim narration and states the surviving rule. The
`test_worker_role` module docstring's closing paragraph ("…assert its ABSENCE until
mod 127…") is rewritten.

### 5.2 New coverage

1. **`web` fixed probe** — `sample-dev-api-web` carries
   `["CMD", "./health.sh", "web"]` with the doctrine cadence.
2. **`web` elastic probe** — `api-web`'s app container carries the same command.
3. **The probe does not follow `health_check_path`** — set the fixture's
   `health_check_path: /healthz` and assert the fixed probe is *still*
   `./health.sh web` and that **no curl appears in the compose document at all**.
   This is the assertion that would catch a half-done table edit that left the field's
   fixed translation in place.
4. **`web` elastic keeps its target-group HTTP check** — `health_check_path` still
   reaches `aws_lb_target_group.api-web`'s `health_check.path`. The ALB is the one
   consumer that survives, and narrowing the field must not silently drop it.
5. **`health_check_path` on a `worker`/`clock` is rejected** with
   `tt_rule_4_undeclared_field` among the reported issues. (Rule 33 also fires; the
   assertion is membership, not exclusivity — asserting a single rule id would make
   the test brittle against the aggregation the validator is built on.)
6. **The `-exec` block carries no `healthcheck:`**, with the positive control that
   every core service in the same document does. Vacuous otherwise.
7. **The elastic `_migrate` task definition carries no `healthCheck`**, same positive
   control against the app container.
8. **Sidecar, both foundations** — narrowed to the sidecar container, positive control
   on the app container (§ 3.3).
9. **`depends_on` keys name no core service** (§ 4).
10. **Backing services get no `health.sh` probe** — `appdb`'s fixed healthcheck is
    still the postgres engine's, and the `${service}`-is-`None` hazard is pinned
    separately: a project-local table declaring `${service}` on a *backing* engine
    raises `SubstitutionError` rather than emitting `None` (§ 1.2).

### 5.3 Expected red elsewhere — not this mod's

`test_projects/` seed projects are already red for two reasons (no `health.sh`,
three-segment contract filenames) and this mod adds a third: their checked-in
compiled output no longer matches a recompile. **All three are mods 129/130's.** Not
touched, not worked around.

---

## 6. Prose that outlived its model

| Site | Today | Becomes |
| --- | --- | --- |
| `magic_refs.py::self_uses_message` | *"its health fan-out would proxy its own `/health` at `/health/<cb>/<svc>`"* | the surviving absurdity: a self-edge makes the core service its own contract provider and its own `uses` target, so rules 31/32 would be satisfied by the service itself |
| `release.py:454` (comment) | *"the health fan-out is doctrine-mandated"* | the reconcile is mandated because a consumer that cannot resolve its `uses` target is broken |
| `release.py:461` (error) | *"the `/health/<cb>/<svc>` fan-out will return 503"* | the consumer cannot resolve a name it `uses`, **with both sides reporting healthy** |
| `release.py:479` (warning) | *"…may return 503 until they do"* | same, in the transient voice |
| `validate.py:511` (comment) | *"for the contract and the health fan-out"* | *"for the contract"* |
| `compose.py` exec block | `# Deliberately unset:` list | gains `healthcheck` with its citation (§ 3.1) |

**The reconcile logic does not move.** Only its stated symptom does — and the new
symptom is strictly worse than the old one, which is the point of rewording rather
than deleting: under the fan-out an unresolvable target surfaced as a 503 somebody
could see from outside. Now nothing external shows it. Both sides are healthy,
the release looks clean, and the work silently does not arrive. The strings say so.

---

## 7. Out of scope, deliberately

- `pipeline/stagetest.py` — mod 128.
- `test_projects/{fixed,elastic}` — mods 129/130, including their `health.sh` and
  their now-stale compiled output.
- `pipeline/check.py` — mod 126, complete.
- `plans/core/masterplan.md` § *The contract and health gates* — mod 131.
- `tables/roles/{cache,object_store,relational_db}.yml` — backing engines. Their
  healthchecks are engine concerns per `healthchecks.md § Backing services` and no
  project writes a `health.sh` for a database.
- The documentation step touches `CHANGELOG.md` and only those statements in
  `plans/core/` that this mod makes false about the *tables or emitters*; the health
  model's own doc block is mod 131's.

---

## 8. Doctrine findings — raised and routed

Neither is edited here. **Both are sarge's**, taken under the operator's grant *after*
this change lands, so the text describes what shipped rather than what was intended.

**Noted as a technique rather than three coincidences:** all three doctrine defects
this advance has found in `transfer_tables.md` — `${service_name}` (fixed at
`fa5d3fb`) and both below — were found the same way, by **reading the worked example
as an author would copy it** rather than reading the prose as a reader would. Prose
states intent and is checked by `cohere` and by every reader; an example is executable
instruction that no tool executes, and it is the artifact a future table author
actually reuses. It should be read adversarially whenever the surrounding prose moves.

1. **`transfer_tables.md` § Anatomy, the `emits` bullet** justifies the
   `container_definition` merge target with: *"This is how a `worker` gets a
   container-level `healthCheck`, since it has no target group to hang one on."*
   After this mod no shipped table routes anything to `container_definition` — the
   worker's probe arrives as a default on `task_definition` instead. The destination
   and its rationale are still correct *as a mechanism*; only the cited example is
   retired. Candidate for mod 131's sweep.
2. **`transfer_tables.md`'s worked `web` entry shows the probe in `defaults.fixed`
   only**, with `defaults.elastic` carrying just `launch_type`/`network_mode` — while
   the prose two screens down says the probe *"is emitted for every core service on
   both foundations."* The example and the prose disagree, and the example is the
   thing a future table author copies. This is the same class of defect as the
   `${service_name}` fix at `fa5d3fb`, found the same way.

A third finding is a `docex` defect rather than a doctrine one. **The analysis is
written up in full at
[`advances/007_small_edges/inert_elastic_defaults.md`](../../advances/007_small_edges/inert_elastic_defaults.md)**
— sarge's direction, on the grounds that reconstructing it later costs a day and
writing it now costs a page. It states the real question (how much of ECS the transfer
tables may legitimately control) and both candidate answers without choosing between
them. **Not fixed here.**

---

## Design questions

### Q1 — the elastic probe cannot reach the container through a merge target

**Full argument in [§ 2](#2-the-elastic-delivery-path--the-one-real-mechanism-decision).**
In one paragraph: `defaults:` cannot route off the default target — `transfer_tables.md`
forbids it in terms and `compile.py` implements the prohibition — so the elastic probe
lands on `task_definition`. But `render_task_definition` builds its container
definition key-by-key and reads only the `body` keys it names, so a `healthCheck`
there is dropped on the floor. The tell that this is a live hazard and not a
hypothetical: `defaults.elastic`'s `launch_type` and `network_mode` are dropped that
way **right now**, on all three core roles, and nothing has ever noticed.

**Recommendation: approve an ~8-line explicit read in `render_task_definition`,
mirroring the reads that already lift `image` and `command` out of `body` onto the
container definition.** Positioned ahead of the `container_definition` merge so a
table field still overrides a table default.

I am raising rather than deciding because it puts a behavioral line in `emit/hcl.py`,
which the brief's territory listed only for comments, and because the advance plan
records recon's finding as *"this is a table edit, not an emitter change."* That
finding is right about `emit/compose.py` (whole-body pass-through, no change needed)
and wrong about `emit/hcl.py`. If you would rather this land as its own mod, say so —
but a table edit that emits no elastic probe is not a shippable intermediate state,
so the two must land together in whichever mod they land in.

### Q2 — the `startPeriod` asymmetry rests on mechanism

**Answered, not open.** Sarge rejected my first justification — "the doctrine's worked
example enumerates exactly four keys" — as an argument from an example I had myself
shown to be defective in two other respects. He is right, and the replacement
justification was checked against the code rather than asserted.

**The two orchestrators do different things with a failing probe.** That is the whole
asymmetry, and it is not cosmetic:

| | What a failed probe causes | What a start grace therefore protects against |
| --- | --- | --- |
| **elastic** | ECS stops the task and the service replaces it. The retired `worker.yml` comment states this in the tables' own voice: *"a wedged consume loop gets the task killed and replaced by the service."* | A container that legitimately needs a moment to write its first tick being killed **before it ever ran** — a replacement loop that never converges. `startPeriod` exists for precisely this. |
| **fixed** | Docker marks the container `unhealthy` and does nothing else. | Nothing. There is no consequence to suppress. |

The fixed row is the load-bearing half, so it was verified rather than assumed —
every mechanism that could act on `unhealthy` on fixed was checked:

- **Docker does not restart on `unhealthy`.** `restart: unless-stopped` keys on exit,
  not on health.
- **`docex envinfra up` does not gate on it.** `subprocess_client.compose_up` emits
  `up --build -d` with **no `--wait`**, so compose returns without consulting health;
  `orchestrate/up.py`'s only health read is `_diagnose_unhealthy`, which runs *after*
  a non-zero exit purely to print a diagnostic.
- **`depends_on: service_healthy` cannot see a core service.** It appears only on the
  `-exec` block and only over `uses_backing` (§ 4).
- **Traefik is the one real consumer**, and it drops an unhealthy container from its
  pool — which is exactly the correct treatment of a container that is not ready.

So on fixed a start grace would **suppress correct behavior** rather than prevent a
wrong consequence: it would route traffic at a container during the window in which
its own probe is still saying no. The asymmetry is kept, and this is the reason of
record for it — not the example.

---

## Rulings (sarge, at design review)

Recorded so they are not re-litigated.

1. **Q1 — the emitter read is APPROVED, and the brief is withdrawn.** Sarge's
   instruction ("reaches the container def through the `container_definition` merge
   target") carried recon's summary forward without checking it against
   `transfer_tables.md` § Anatomy, which forbids `defaults:` routing off the default
   target. The rule of record contradicted the instruction; stopping was correct.
   Two conditions on the implementation, both met: the read sits **ahead** of the
   merge so a field still overrides a default, and its comment **names the
   inconsistency it creates** — `healthCheck` is honored and `launch_type` is not,
   and a reader must not infer the second from the first.
2. **Hardcoding the probe in `hcl.py` beside `launch_type` — considered and
   rejected.** It would avoid the inconsistency entirely, but `healthchecks.md` says
   probe cadence *"lives in the transfer tables rather than here"*, so hardcoding the
   numbers would put the doctrine's own values where the doctrine says they do not go.
   Table plus explicit read is correct.
3. **Q2 — asymmetry kept, but the reasoning is replaced.** An argument from a worked
   example is not admissible when that example has been shown defective twice in the
   same advance. The mechanism argument (ECS kills, Docker only reports) is the reason
   of record, and it was verified against the code.
4. **Both `transfer_tables.md` defects are sarge's to take**, after this change lands,
   so the text describes what shipped rather than what was intended. Not mod 131's.
5. **The inert-defaults finding gets its own brief** at
   [`advances/007_small_edges/inert_elastic_defaults.md`](../../advances/007_small_edges/inert_elastic_defaults.md),
   stating the question and both answers without choosing. Not fixed in this mod.
6. **Re-deriving test counts rather than inheriting them is standing practice** — the
   habit is why mod 126 discovered an integration member that had been red since
   before the advance began.
