# Mod 101 — Contracts and health gates

## Purpose

Mods 094–100 built the pieces; this mod is where CI finally *reads* them. `consumes`
has existed since Mod 098 and is read by nothing. `check.py` is its first reader.

Three things happen here:

1. A function that has been silently broken since it was written is fixed.
2. The contract provider *criteria* — deliberately left alone by Mod 096 behind two
   `# Mod 101` markers — move onto `consumes`.
3. The health-endpoint gate stops asserting a codebase-level, `depends_on`-only
   approximation and starts asserting the doctrine's actual model.

**Rule of record: [`doctrine/infrastructure/contracts.md`](../../../../doctrine/infrastructure/contracts.md)
§ Contracts and § Health Checks**, as written in Mod 094. Where the design record
(`plans/advances/004_next/service_processes_refactor.md`) differs, the doctrine wins.

**Touches:** `src/docex/pipeline/check.py` (the substance), `src/docex/cicl/model.py` +
`src/docex/cicl/validate.py` (rule 25's scheduler clause, and one parser promoted so
there is not a second one), two stale-path repairs (`src/docex/errors.py`,
`plans/core/masterplan.md`), and new tests.

**Three doctrine edits authorized by the C.O.** after the design review (see § Design
questions for how each was ruled): two clauses in `contracts.md § Fan-out`, and rule 25
in `cicl.md`. Nothing else in either file. Precedent: `cicl.md` has no downstream owner,
so the mod that discovers a gap fixes the text — 095 added rule 28, 099 amended rule 5,
100 added a rule 5 clause.

## The defect being fixed

`_infer_contract_format` (`check.py:109-131`) has never returned anything but
`"openapi"`. Its own docstring concedes the design — *"Phase 3 keeps this shallow…
Guess the contract format."* The asyncapi branch is provably unreachable:

- The sole call site is `_gate_contracts:347`, which passes `svc_name` — a **core**
  service name, drawn from `infra.all_processes()`.
- The function then does `infra.backing_services.get(service)` with that core name.
- `model.py` forbids a name from being both a core and a backing service.

So `backing` is always `None`, the `if` never fires, and every provider gets
`openapi`. That unreachability is *why* the async-contract path was never exercised
and the `depends_on` flaw in `_gate_health_endpoints` went unnoticed for this long:
no test ever produced an AsyncAPI provider, because no code path could.

The replacement is not a refactor of the heuristic. The heuristic is deleted. Per
`contracts.md § Standards`, the format follows from the **provider's `role`** —
"the role is what fixes the communication mechanism, so it is the honest source."

## Design

### 1. Format derives from role

`_infer_contract_format(infra, service)` → `_contract_format_for_role(role)`.

| `role` | format |
| ------ | ------ |
| `web` | `openapi` |
| `worker` | `asyncapi` |

`scheduler` never reaches this function — it is never a provider (below). An
unrecognized role falls back to `openapi` rather than raising: an unknown core role is
already a transfer-table load error, and a gate that raises mid-aggregation would deny
the operator every *other* gate's result, which is the whole point of the aggregation
pattern. **The fallback is named in the gate's detail line**, not taken silently — a
provider quietly treated as openapi because its role was unrecognized is a debugging
trap (C.O. ruling).

The `infra` parameter is dropped. Nothing else in the module calls it.

### 2. Provider set = (`consumes` targets) ∪ (web-network process types)

Per `contracts.md`: *"The provider set is (`consumes` targets) ∪ (`web`-network
process types). Both arms are load-bearing."*

```
consumed  = { ProcessRef.parse(raw).dotted  for every process type's consumes: }
providers = { (s,p) : "web" in p.networks }  ∪  { (s,p) : "s.p" ∈ consumed }
          − { (s,p) : p.role == "scheduler" }
```

- Parse failures are **dropped**, matching `validate._parsed_consumes`'s reasoning:
  rule 25 already reports each malformed entry once, and a malformed entry must not
  also surface as a mystifying missing-contract error.
- A dotted target naming a process that does not exist contributes nothing, because
  the set is built by testing membership against real process types rather than by
  trusting the reference.
- The web arm is why this cannot be driven off `consumes` alone: a publicly-reachable
  boundary that nothing internal consumes would silently lose its contract, and with
  it everything the health-endpoint gate has to validate.

Contract path is unchanged from Mod 096: `infra/contracts/{svc}.{proc}.{fmt}.yml`.
Two HTTP process types on one codebase (`api.web` public, `api.admin` internal) each
get their own file — the doctrine's stated reason the path is process-keyed
unconditionally.

**Schedulers are excluded from the provider set explicitly**, not incidentally. Mod
096 makes `web` in a scheduler's `networks` an error, so the web arm cannot reach one;
the `consumes` arm is closed by **rule 25's new scheduler clause** (Q3, added by this
mod). The gate still states the exemption itself, so the validator and the gate are
belt-and-braces rather than the gate depending on the validator.

### 3. Right-anchored contract-filename parsing

New `_parse_contract_filename(name) -> (svc, proc, fmt) | None`, replacing
`path.name.split(".", 1)[0]` at `:392`.

The old split yields `api` from `api.web.openapi.yml` — a valid `core_services` key
purely by the accident that the codebase is the first segment — and then discards
the process entirely, so the gate reasoned at codebase granularity. On a two-web-process
codebase it would check `api.web`'s contract against `api.admin`'s dependencies and
never notice.

The new parser strips the `.yml`/`.yaml` suffix, splits on `.`, requires **exactly
three** segments, and indexes **from the right**: `fmt = parts[-1]`,
`proc = parts[-2]`, `svc = parts[-3]`. Anything else returns `None` and is skipped.
Exactly-three is safe to require because `_SERVICE_NAME_RE` (`model.py:24`) admits no
dots in either a service or a process name, so the canonical filename has three
segments and nothing else is a contract this gate authored.

### 4. `_gate_health_endpoints` against the doctrine's model

Reworked to run **per process type**, not per codebase. For each contract file:

**Self health.** Require `GET /health` from every **OpenAPI** provider. Per
`contracts.md § Self health`, *every* long-running process type serves `GET /health`;
the reason a `worker` is not checked here is not that it is exempt but that its
contract is AsyncAPI, which — per § Declared by fields — has no natural place for an
HTTP path. A worker's self-health is asserted through its fields instead (item 5).
This is a small widening of the old rule (was: web-network only) — see Q5.

**Fan-out.** For each process type on the `web` network, per § Fan-out:

```
fanout = resolve(consumes)                            # to core process types
       − scheduler targets − web-network targets
require  GET /health/<svc>/<proc>  for each
```

`scheduler` targets are exempt per § Health Checks. Web-network targets keep the
carve-out: a target on `web` is publicly reachable, so a stage test probes it directly
at its own hostname and there is nothing for a consumer to proxy — which is precisely
what § Health Checks' opening means by "those that aren't" (Q1). Backing services are
unchanged: § Fan-out's path form `/health/<service>/<process>` has no shape for a
service with no process types, and Mod 047 already narrowed this to core-only. A
project that voluntarily declares `/health/<backing>` (as the `sample_project` fixture
does for `appdb`) is still free to.

**The `depends_on` arm is dropped, and the doctrine sentence is corrected** (Q2). The
history: when § Fan-out was drafted, `depends_on` could still name core services, and
the union existed to stop the fan-out keying off `depends_on` *alone* — which would
have silently dropped the `web → worker` probe. **Mod 098's rule 24 then made
`depends_on` backing-only**, and a backing service has no `/health/<svc>/<proc>` form
at all. The union collapsed to `consumes` as a consequence of a later mod and nobody
went back to the sentence. Implementing it literally would ship a second unfireable
branch in the same mod that deletes one, so the code reads `consumes` only and
`contracts.md` records the historical reason in a clause, so that a future reader does
not "restore" the union.

**What `consumes` buys.** Under rule 24 a web process type cannot `depends_on` its
worker at all, so a `depends_on`-keyed gate now requires *nothing* of a `web → worker`
edge. That is the silent-switch-off the doctrine names: requests keep returning 200
while work piles up behind a dead consumer.

### 5. New assertion: a `consumes` target must declare `port` and `health_check_path`

Per § Declared by fields: *"A `consumes` target must declare both `port` and
`health_check_path`. Those two fields **are** the health declaration, and the check
step asserts them."* On elastic the `port` is additionally what makes the target
Service-Connect-discoverable, which is what lets a sibling `web` process reach its
`/health` one hop away.

Both fields live in `ProcessType.model_extra` / `.port`. `tables/roles/worker.yml`
declares `health_check_path` for the `worker` role, so this is satisfiable.

This assertion is folded into `_gate_health_endpoints` rather than given its own gate
row. Rationale: § Declared by fields is a *subsection* of § Health Checks describing
how one requirement splits between fields and contract — one doctrine rule, one gate.
Failure detail strings name the consumer, the target, and the missing field(s).

Note this is not redundant with rule 28 (`health_check_path` obliges `port`): rule 28
constrains a process type that *has* the field; this requires a `consumes` target to
*have* it. Different direction.

### 6. Curl gate untouched

`_gate_healthcheck_tooling` stays keyed off `health_check_path`. It becomes correct
automatically now that the field is process-scoped, and re-keying it off `role` would
be strictly worse — the compiler emits the curl healthcheck from the *field*, and
`infrastructure.md` states the requirement in terms of the field. Mod 096 already
repaired this gate; before that it read `getattr(svc, ...)` against the `CoreService`,
went permanently `None`, and passed while checking nothing.

### 7. Rule 25 gains a scheduler clause (`cicl.md` + `validate.py`)

`contracts.md` states "a scheduler is never a `consumes` target" as fact, but rule 25
(`validate.py:605`) only checks that the target *exists* — `consumes: [jobs.nightly]`
naming a scheduler passes validation today. This mod is the one that has to work
*around* that gap, and a workaround justified by "the validator does not enforce this
yet" is worse than five lines of validator (C.O. ruling, Q3). So:

- `cicl.md` rule 25 gains: a `consumes` target may not be a `scheduler` process type.
- `validate.py::_validate_consumes` gains the matching check, after the target's
  existence is confirmed, under a new rule id `rule_25_consumes_scheduler`.

The gate's own scheduler exemption stays, becoming belt-and-braces rather than
load-bearing — the right relationship between a validator and a gate.

### 8. One parser, not two

`_consumes_targets` in `check.py` would be a second implementation of
`validate._parsed_consumes`. `_validate_consumes`'s own docstring rejects exactly this
— *"a second parser would be a second place for that rule to drift."* So the parse is
promoted to `ProcessType.consumes_refs()` on the model (which already owns `ProcessRef`
and the dots-for-reference rule), `_parsed_consumes` is deleted, and both readers call
the method. This is why `model.py` and `validate.py` appear in Touches beyond the
plan's "`pipeline/check.py`".

### 9. Stale-reference repairs

- `src/docex/errors.py:127` — docstring says `infra/contracts/<svc>.<fmt>.yml`; the
  path gained a process segment in Mod 096.
- `plans/core/masterplan.md:163` — same stale path in § Filesystem Surface.
- `_gate_contracts`'s docstring cites "contracts.md § Contract Location", a heading
  that does not exist; the path is fixed in that file's opening prose.

## Testing

New file `tests/unit/test_contract_health_gates.py`, built on the inline-`infra.yml`
pattern `_hc_ctx` already uses in `test_pipeline_check.py` (tmp_path project, direct
gate invocation) rather than a new fixture project — the shapes under test are
one-off and a fixture dir per shape would not pay for itself.

| Test | What it pins |
| ---- | ------------ |
| `test_worker_provider_gets_asyncapi` | `api.web consumes api.worker` ⇒ `api.worker.asyncapi.yml` required. **Fails before this mod**: old code makes a non-web, non-`depends_on`-target process a non-provider, so no contract is expected at all — and even as a provider it would be handed `openapi`. |
| `test_two_web_processes_each_get_a_contract` | `api.web` + `api.admin` both on `web` ⇒ two distinct openapi paths. |
| `test_contract_filename_parsed_right_anchored` | `_parse_contract_filename` direct: 3-segment ok, 2-segment `None`, 4-segment `None`. |
| `test_missing_fanout_probe_fails` | `api.web consumes api.worker`, contract lacks `GET /health/api/worker` ⇒ gate fails. |
| `test_fanout_required_without_depends_on` | The point of keying off `consumes`: the same edge with **no** `depends_on` anywhere still requires the probe. |
| `test_consumes_scheduler_rejected` | Rule 25's new clause (in `test_consumes_relation.py`, where rule 25 already lives). |
| `test_unknown_role_fallback_is_reported` | The openapi fallback appears in the gate detail rather than being silent. |
| `test_consumes_target_without_port_fails` | Worker declaring `health_check_path` but no `port` ⇒ fails. Plus the mirror: no `health_check_path` ⇒ fails. |
| `test_scheduler_never_a_provider` | A scheduler process type demands no contract, and is exempt from the fan-out and from the port/`health_check_path` assertion. |
| `test_openapi_provider_requires_self_health` | Self-`/health` still enforced. |

The existing `test_pipeline_check.py` cases run against `sample_project` (one web
process, one backing `depends_on`) and must stay green unchanged — that shape is
unaffected by every change here, which is the regression signal that matters.

## Out of scope

Telemetry (102) · ofelia / `_run_scheduler_tests` (103) · `describe` (104) · rollback
(105) · any version artifact (107). `consumes` is read off the **authoring** model
(`ctx.infra.core_services[…].processes[…]`); carrying it onto `CompiledService` is
Mod 104's.

**Doctrine** is out of scope *except* the three C.O.-authorized edits in § Design
(contracts.md § Fan-out ×2, cicl.md rule 25). Everything else stays with Mod 106 —
including `cicd.md § Check Step`, where item **3.2** ("contracts … match `depends_on`
relationships" — now `consumes`) is already on 106's list and the C.O. has expanded
that line to also cover item **3.3** (health endpoints, now per process type off
`consumes`) and a new item for the `port` + `health_check_path` assertion.

## Integration tests that go stale

Neither can run in this environment (both need real docker/git).

- `tests/integration/test_check_real.py` — **still valid, now blind.** It exercises
  the one-web-process `sample_project` shape end-to-end and breaks `/health` in
  `api.web.openapi.yml`; every assertion still holds. But that shape has no
  `consumes` edge and no worker, so nothing this mod adds is covered at the real-git
  layer. Worth a `consumes`-bearing case eventually; not this mod's to add, since the
  smoke/fixture projects only gain a worker in Mod 107.
- `tests/integration/test_check_hcgate_real.py` — **untouched.** It exercises only
  `_gate_healthcheck_tooling`, which this mod deliberately leaves keyed off
  `health_check_path`. Already process-scoped by Mod 096.


## Design questions — resolved

All five were ruled on by the C.O. at design review. Recorded here because three of the
rulings changed the design and two produced doctrine edits.

**Q1 — Keep the web-target carve-out in the fan-out? → KEEP, and fix the wording.**
The carve-out is *correct*, not merely pre-existing: a target on `web` is publicly
reachable, so a stage test probes it directly at its own hostname and there is nothing
for a consumer to proxy. That is exactly what § Health Checks' opening means by "those
that aren't". § Fan-out's "everything it talks to" is loose wording that contradicts its
own section's premise. **Doctrine edit authorized**: qualify § Fan-out with "targets not
themselves on the `web` network".

**Q2 — The `depends_on` arm of the union is inert. Keep it? → DROP IT.**
Reproducing an unfireable branch in the mod that deletes one would be incoherent.
**Doctrine edit authorized**: § Fan-out says `consumes`, with the historical reason
preserved in a clause so a future reader does not "restore" the union. See § Design 4
for the history.

**Q3 — Nothing rejects `consumes:` pointed at a `scheduler`. → FIX IT HERE.**
Not a follow-on: this mod is the one that has to work around the gap, and a workaround
justified by "the validator does not enforce this yet" is worse than five lines of
validator. **Doctrine edit authorized**: rule 25 in `cicl.md`, plus the matching check in
`validate.py`. See § Design 7.

**Q4 — `cicd.md § Check Step` needs more than 106's list names. → ROUTED, no action.**
The C.O. is expanding Mod 106's `cicd.md` line to cover item 3.3 and to add an item for
the `port` + `health_check_path` assertion. No doctrine file touched by this mod on that
account.

**Q5 — Widening self-`/health` to all OpenAPI providers. → TAKE IT.**
More faithful to § Self health, which says *every* long-running process type serves
`GET /health` with no web-network qualifier. An internal-only `web`-role process reached
via `consumes` genuinely should have a self-health endpoint — that is what makes it
probeable one hop away.

**On the unknown-role fallback**, the C.O. confirmed openapi-not-raise for the reason
given, with the condition that the fallback be visible in gate output. Folded into
§ Design 1.
