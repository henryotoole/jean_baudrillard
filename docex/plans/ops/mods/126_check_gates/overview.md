# Mod 126 — the check gates

Second mod of [advance 006](../../advances/006_surfaces_and_health/advance_plan.md).
Mod 125 taught the CICL *language* about surfaces; this mod teaches `docex check` to
read them. The provider set stops being inferred from the graph and the network and
becomes exactly what `surfaces:` declares, and the health half of the gate roster is
cut down to what the doctrine still asks for.

**Territory.** `src/docex/pipeline/check.py`, `src/docex/errors.py`, their tests
(`tests/unit/test_contract_health_gates.py`, `tests/unit/test_pipeline_check.py`,
`tests/integration/test_check_real.py`, `tests/integration/test_check_hcgate_real.py`),
and `tests/fixtures/**`. Nothing else. `tables/`, `emit/`, `stagetest.py`,
`release.py`, and `test_projects/` belong to mods 127–130.

**Rule of record.** Already committed and authoritative:
[`contracts.md`](../../../../doctrine/infrastructure/contracts.md) (38 lines now — the
fan-out, § Self health, and § Declared by fields are gone),
[`healthchecks.md`](../../../../doctrine/infrastructure/healthchecks.md),
[`cicd.md § Check Step`](../../../../doctrine/infrastructure/cicd.md#check-step),
[`cicl.md § Surfaces`](../../../../doctrine/infrastructure/cicl.md#surfaces),
[`infrastructure.md § Codebase Containers`](../../../../doctrine/infrastructure/infrastructure.md#codebase-containers).
This mod changes no doctrine file.

**Inherited from mod 125, imported and not copied.**
`cicl/model.py::API_STYLE_FORMATS` and `::IMPLEMENTED_CONTRACT_FORMATS`;
`Surface.formats()`; `CoreService.surfaces`. Rules 29–33 are enforced at compile
time. Nothing here re-raises them.

---

## 1. What `cicd.md § Check Step` actually still asks for

The gate roster is being cut, so the honest starting point is the rule of record's
own list. Step 3's four items, each mapped to who enforces it *after* mod 125:

| `cicd.md` step 3 item | Enforced by |
| --------------------- | ----------- |
| 3.1 `build.sh`, `test.sh`, `health.sh`, `migrate.sh` if required | **this gate** (`_gate_codebase_scripts`, § 6) |
| 3.2 one contract per declared surface, in the surface's format | **this gate** (`_gate_contracts`, § 4) |
| 3.3 every `uses` target declares a surface; a directly-addressed one declares a `port` | compile — rules 31/32 |
| 3.4a every `web`-network core service declares `health_check_path` | compile — rule 33 |
| 3.4b where it *also* declares an `openapi` surface, its contract declares that path | **nobody, if the brief is followed literally** → [Q1](#q1--the-self-health-contract-assertion) |

Two of the four items moved to compile time in mod 125, which is why two gates die
here. 3.4b is the one item the brief's deletion list would leave unowned, and it is
this mod's only escalated decision.

## 2. Deletions — the format-by-role machinery

`_CONTRACT_FORMAT_BY_ROLE`, `_FALLBACK_CONTRACT_FORMAT`, and
`_contract_format_for_role` are deleted outright, along with the `fallbacks` /
`fallback_clause` plumbing in `_gate_contracts` that surfaced the fallback in the
gate detail.

The fallback's own justification is what retires it. Its `WHY` reads: *"an
unrecognized core role is already a transfer-table load error, and raising here
would deny the operator every other gate's result — the aggregation pattern exists
precisely to avoid that."* That argument was sound while the format came from a
value the gate had to *interpret*. It no longer does: an unrecognized `api_style` is
`rule_29_unknown_api_style` and a `graphql`/`proto` surface is
`rule_contract_format_not_implemented`, both raised by `docex compile` with a named
rule id before this gate is reached in earnest. There is nothing left for the gate to
guess at, so there is nothing for it to guess *wrong* and report as an assumption.

`_resolve_service` also goes (§ 4.3 explains what replaces it).

## 3. `_parse_contract_filename` — four segments, one extension

Signature becomes `str -> tuple[str, str, str, str] | None`, yielding
`(codebase, service, surface, format)`.

```
api.web.rest.openapi.yml   -> ("api", "web", "rest", "openapi")
api.web.rest.openapi.yaml  -> None      # narrowed: contracts.md fixes ONE ext per format
api.web.openapi.yml        -> None      # the retired three-segment shape
a.b.c.d.e.openapi.yml      -> None      # exact length, still
```

Two changes and one thing deliberately unchanged:

1. **Four stem segments, not three.** Still indexed from the right (`parts[-4]` …
   `parts[-1]`), still requiring the exact count. "Right-anchored" here has always
   meant *negative indexing off the extension*, not *take the last four of however
   many* — `a.b.c.d.yml` returns `None` today and the four-segment analogue must
   too. `_SERVICE_NAME_RE` admits no dots in a codebase, core-service, or (mod 125)
   surface name, so a canonical name has exactly four and nothing else is a name
   `docex` authored.
2. **The extension is checked against the format, not against a list of accepted
   suffixes.** Today the parser strips `.yml` *or* `.yaml` and never looks at the
   format again. `contracts.md § Standards` fixes one extension per format
   (`openapi`/`asyncapi` → `yml`, `graphql` → `graphql`, `proto` → `proto`), so the
   parse resolves the format first and then requires *its* extension. This is what
   makes the non-YAML formats expressible in the same template rather than
   special-cased later.

A `_FORMAT_EXTENSIONS` table transcribed from `contracts.md § Standards` lands in
`check.py`, **not** `model.py`. Mod 125's reason for putting `API_STYLE_FORMATS` in
`model.py` was that two modules need it; the extension table has exactly one consumer
and `model.py` is not this mod's territory. It carries all four rows including the
unimplemented two — they are the doctrine's table, and when `graphql` lands the only
edit is one line of `IMPLEMENTED_CONTRACT_FORMATS` in `model.py`.

## 4. `_gate_contracts` — rewritten off `surfaces`

### 4.1 The provider set

The two-armed `(core-targeted uses) ∪ (web-network core services)` union is deleted
whole. **A core service is a provider iff it declares `surfaces:`.** One expected
contract file per surface, at
`infra/contracts/<codebase>.<service>.<surface>.<format>.<ext>`, in the format that
surface's `api_styles` resolve to via `Surface.formats()`.

The old docstring defended both arms as load-bearing, the second on the grounds that
it *"catches every publicly reachable boundary even when nothing inside the project
uses it, which is what gives the health-endpoint gate something to validate."* Both
halves of that sentence are now false. The second arm's real content — "public
reachability implies a described boundary" — is **wrong**, and the consequence is
worth a comment in the new code: a `web`-network core service that declares no
surface, which is precisely a frontend serving a browser, now correctly requires
**no** contract, where the old arm forced one and `infrastructure.md § Contracts`
uses that exact case (`frontend.web` declares no surface) as its worked example.

`providers` (the second return value) survives, now meaning *core services that
declare at least one surface*. It is discarded by `run_check` and asserted by tests;
under the new model it is a one-line read of the declared set rather than a derived
union, and it is the cheapest available assertion that the provider rule changed.

### 4.2 Two skips, each avoiding a double-report

Per surface, in order:

- `len(surface.formats()) != 1` → **skip**. Rule 29 (`rule_29_mixed_contract_formats`,
  `rule_29_unknown_api_style`) reports it at compile time; a second complaint here
  would name a filename the author could never have produced.
- format not in `IMPLEMENTED_CONTRACT_FORMATS` → **skip**. `rule_contract_format_not_implemented`
  reports it. Note the sequencing that makes the skip honest rather than lax: gates
  run *before* `run_compile` inside the same `run_check`, so skipping here does not
  let the project through — `check` still fails, at step 6, with the message that
  names the actual problem ("format not yet implemented") instead of a missing
  `api.web.gql.graphql.graphql`.

This is the same policy `_resolve_service`'s docstring stated for rule 25, preserved
as the expectation builder's skip rule.

### 4.3 One expectation builder, two consumers

`_expected_contracts(infra, contracts_dir) -> list[ContractExpectation]` — a frozen
dataclass carrying `codebase`, `service`, `surface`, `fmt`, `path`, and the
`CoreService`. Computed once and shared, because two gates need the same filenames
and a second copy of the naming expression is a second place for it to drift. It also
deletes `_resolve_service`: an expectation already holds the resolved `CoreService`,
so nothing re-parses a filename back into a service.

`_gate_contracts` returns the *existing* subset, exactly as today, for the next gate.

### 4.4 Orphans — a contract file for a surface nobody declares

New failure clause on the same `contracts_exist` gate: a file in `infra/contracts/`
that no declared surface expects is **reported and fails the gate**.

Scope, chosen to catch the real case without inventing false positives: files whose
name parses canonically but names an undeclared codebase/service/surface, **plus**
files ending in any contract extension (`.yml`, `.yaml`, `.graphql`, `.proto`) that
do not parse at all. Dotfiles, subdirectories, and anything else (`README.md`,
`.gitkeep`) are ignored. The unparseable arm is what makes this worth having: a
leftover three-segment `api.web.openapi.yml` after the 1.7.0 rename is the single
most likely upgrade mistake in this entire advance, and it is invisible to an
existence-only gate. Failing rather than warning is deliberate — an unexpected
contract is drift, and a contract nobody serves is worse than no contract because it
reads as documentation.

**Decided, not escalated:** the gate keeps the name `contracts_exist` rather than
becoming `contracts_match_surfaces`. The orphan arm is still an existence claim (a
file exists that should not), the name appears in operator-facing report output and
in `test_pipeline_check.py`, and mod 131 has enough checklist churn without a gate
rename it did not ask for.

## 5. Gates deleted

### 5.1 `_gate_health_endpoints` — deleted

All three of its assertions:

1. **Fan-out** (`GET /health/<codebase>/<service>` per non-`web` core `uses` target).
   `healthchecks.md § What this doctrine does not do` is explicit: *"There is no
   proxying, no `/health/<codebase>/<service>`, no fan-out."* Nothing to salvage.
2. **Probeability** (a core `uses` target declares `port` *and* `health_check_path`).
   Both halves are now wrong, not merely unenforced. Rule 33 *forbids*
   `health_check_path` off the `web` network, and rule 32 makes `port` conditional on
   direct addressing — so on the canonical `api.web` → `api.worker` queue edge this
   gate demanded exactly the two fields compile now rejects. This is the gate that
   makes `docex check` fail on the seed projects between mods 125 and 126, and its
   deletion is what closes that.
3. **Self health** (`GET /health` in every OpenAPI provider's contract) — see
   [Q1](#q1--the-self-health-contract-assertion). This is the one assertion the
   doctrine still asks for, in narrowed form, and the only thing in this mod I am not
   willing to delete on my own authority.

Pulled into this mod rather than left to 127 because the gate shares
`_parse_contract_filename` with the contract gate: cutting between them would mean
shipping a version of the fan-out gate that reads four-segment names, which nobody
wants and nothing tests.

### 5.2 `_gate_healthcheck_tooling` — deleted, not narrowed

This supersedes the design record's docex-impact table, which says "narrow to `web`".
Verified against the committed doctrine rather than assumed:

- `infrastructure.md § Codebase Containers` now reads *"Every image must be able to
  run `./health.sh <service>`… What that requires — an HTTP client, a file stat, a
  language runtime — is the project's to install."*
- `cicd.md § Check Step`'s list carries no curl item at all.
- A repo-wide grep finds no remaining `curl`-in-codebase-image mandate anywhere in
  `doctrine/`.

A gate enforcing a requirement the rule of record has withdrawn is worse than no
gate: it fails correct projects, and the operator's only recourse is to install a tool
the doctrine explicitly stopped asking for.

**Engaging with the docstring being deleted, because it argues at length and it was
right.** Mod 059's 25-line block insists the gate must **not** filter by network:
*"The curl need follows the field, not the `web` network: the compiler emits the curl
healthcheck whenever `health_check_path` is set… and a curl-less healthcheck marks the
container `unhealthy` — which drops the Traefik route for a `web` service AND breaks
any `depends_on: service_healthy` waiting on a non-`web` one."* Every clause of that
was true under the old model, and mod 096 later found the gate reading the wrong
object and fixed it precisely because the protection mattered. It is being
**superseded, not overturned**: its premise was that HTTP is the universal probe
substrate, so the tool the probe needs is knowable from one field. Under
`healthchecks.md` the probe is a project-authored command whose requirements the
doctrine deliberately does not fix, so no gate can know what tool to look for. The
narrowing the design record proposed would have been the worse of the three options —
it keeps a gate whose reasoning has been withdrawn and gives it a scope its own
docstring spends a paragraph arguing against.

**Not salvaged by building and running the probe.** The tempting rescue is to build
the image and execute `./health.sh <service>` in it. `healthchecks.md` closes that
off in one sentence: *"The [check step] asserts the file exists. Nothing can
statically assert that it is *correct*."* At check time no stack is running, so a
correct `health.sh` for a `web` edge (curl your own port) or a worker (stat a tick
file) fails for the right reason, and a gate that cannot distinguish that from a
broken script is a gate that teaches operators to ignore it. Existence is the
assertion the doctrine asks for, and § 6 is where it lands.

Consequence for the roster: `_gate_healthcheck_tooling` was the only gate consuming
`DockerClient`. `run_check` still needs `docker` for `_compose_build`, so no signature
changes — but this is now the *only* thing docker is used for before step 6.

## 6. `_gate_codebase_scripts` — `health.sh` is the fourth shim

`("build.sh", "test.sh")` becomes `("build.sh", "test.sh", "health.sh")`, checked for
presence and the executable bit exactly as the others are. `migrate.sh` stays
conditional on schema ownership. The pass detail names all three unconditional shims
instead of "build.sh/test.sh".

One comment, per `cicd.md § Check Step` 3.1: `health.sh` is invoked **per core
service**, as `./health.sh <service>`, and the compiler supplies the argv. That is
the one asymmetry against the other three shims — they are properties of the source
tree and so codebase-scoped, while health is a property of a running process. It
changes nothing about *this* gate (one file per codebase either way), which is
exactly why it needs saying: a reader who knows the argv exists will otherwise expect
a per-core-service check here and find none.

## 7. Stale prose, error text, and the roster

- `_parse_contract_filename`'s docstring narrates the mod-096 left-anchored bug and
  "the health gate reasoned at codebase granularity". Rewritten to the four-segment
  parse; the archaeology goes, since the gate it names is gone.
- `_gate_contracts`'s docstring — the whole two-arm defence (§ 4.1).
- `errors.py`: `ContractMissing` cites `<codebase>.<service>.<fmt>.yml` and
  `ContractInvalid` says "missing a doctrinally required endpoint". Both docstrings
  updated to the four-segment path. **Both classes are unraised anywhere in `src/`**
  (the gates report through `CheckReport` instead), so this is a documentation fix on
  dead-but-exported types, not a behavior change. I am not deleting them: they are
  part of the public error taxonomy and the deletion decision is not this mod's.
  If [Q1](#q1--the-self-health-contract-assertion) rules for deletion,
  `ContractInvalid` describes something no code checks, and that should be said
  plainly in its docstring rather than left to imply a gate that does not exist.
- `run_check`: `_gate_health_endpoints` and `_gate_healthcheck_tooling` calls removed;
  new health-path gate added if Q1 approves. Gate count goes **10 → 9** (Q1 approved)
  or **10 → 8** (Q1 declined). `test_pipeline_check.py::test_check_happy_path_aggregates_all_passing`
  and the seed-walk checklist boxes both key on the roster; the latter is mod 131's,
  and the count belongs in the handoff.

## 8. Fixtures

`tests/fixtures/sample_project` and `sample_project_elastic` (the only two with a
`core/` tree or a `contracts/` dir):

- `infra.yml`: `api.web` gains `surfaces: {rest: {api_styles: [rest]}}`. Without this
  it declares no surface, is therefore not a provider, and its contract file becomes
  an *orphan* under § 4.4 — the fixture would fail the very gate it exists to
  exercise.
- `infra/contracts/api.web.openapi.yml` → `api.web.rest.openapi.yml`. Its header
  comment documents the three-segment scheme and the `/health/appdb` backing-service
  fan-out (an assertion `docex` stopped making in mod 047); rewritten. The
  `/health/appdb` path itself is dropped — nothing requires it and leaving it models
  a shape the doctrine now forbids.
- `core/api/health.sh`: **new, executable.** Required by § 6, without which every
  `worktree_setup`-based test in `test_pipeline_check.py` fails on
  `codebase_scripts`. A `case "$1" in web) ...` skeleton with a comment that the argv
  is the core service name.

The three infra-only fixtures (`sample_project_clock_{fixed,elastic}`,
`sample_project_multi_fixed`) have no `core/` tree and no `contracts/` dir and are not
loaded by any check test, so they need nothing. `test_projects/` is untouched and its
`docex check` stays red until mod 129 — booked as a GATE in the advance plan, not a
defect.

## 9. Tests

### 9.1 `tests/unit/test_contract_health_gates.py` — effectively rewritten

The module docstring is built on the fan-out premise ("the health fan-out keys on
CORE `uses` targets specifically") and on format-follows-role; both go. Of the eleven
tests:

| Test | Fate |
| ---- | ---- |
| `test_worker_provider_gets_asyncapi` | **rewritten** — same shape, but `api.worker` is a provider because it declares `surfaces: {events: {api_styles: [events]}}`, not because it is a `uses` target, and the expected name is `api.worker.events.asyncapi.yml` |
| `test_two_web_processes_each_get_a_contract` | **rewritten** — both now declare surfaces; still the "path is service-keyed unconditionally" assertion |
| `test_unknown_role_fallback_is_reported` | **deleted** — no fallback exists; the unknown-style case is compile-time and mod 125 covers it in `test_surfaces.py` |
| `test_contract_filename_parsed_right_anchored` | **inverted** — it asserts a four-segment stem is *invalid*, which is now the only valid shape |
| `test_missing_fanout_probe_fails` | **deleted** |
| `test_web_target_is_not_proxied` | **deleted** |
| `test_openapi_provider_requires_self_health` | **narrowed or deleted** per Q1 |
| `test_internal_openapi_provider_requires_self_health` | **deleted regardless** — see § 9.3 |
| `test_core_uses_target_without_port_fails` | **deleted** |
| `test_core_uses_target_without_health_check_path_fails` | **deleted** |
| `test_fully_declared_core_uses_target_passes` | **deleted** |

`_proc`'s helper signature gains a `surfaces` parameter; `_HEAD` and `_project` are
unchanged. The `_ASYNCAPI` constant survives but its comment (which explains § Declared
by fields) does not.

### 9.2 New coverage, each demonstrated red before green

1. **Two surfaces, two required contracts.** One core service declaring `rest`
   (openapi) and `events` (asyncapi); both files required; supplying one leaves the
   other named in the failure detail.
2. **Two surfaces of the same format on one core service.** `rest_public` and
   `rest_admin`, both openapi — legal per `cicl.md § Surfaces`' naming note. Two
   distinct filenames, both required, and the right-anchored parse round-trips both
   without confusing them. This is the case a naive `<cb>.<svc>.<fmt>` scheme cannot
   express at all, and the reason the surface segment exists.
3. **A `web`-network core service with no surfaces requires no contract.** The
   deleted second arm's exact inverse; the frontend case from
   `infrastructure.md § Contracts`.
4. **An orphan contract fails the gate.** Both arms of § 4.4: a canonical name for an
   undeclared surface, and a leftover three-segment `api.web.openapi.yml`.
5. **Extension narrowing.** `api.web.rest.openapi.yaml` on disk does not satisfy the
   expectation for `api.web.rest.openapi.yml` — it is an orphan, and the gate says
   so.
6. **`health.sh` missing / non-executable fails `codebase_scripts`**, with a positive
   control. `test_pipeline_check.py`, beside the existing script-gate coverage.

Every one of these gets its red observed and recorded in the implementation doc's
verification step, per advance 005's standing rule.

### 9.3 `test_internal_openapi_provider_requires_self_health` is deleted, and why it
is not merely a casualty

Mod 101 added it as "Q5's widening": self-`/health` follows the OpenAPI contract, not
`web` membership, because *"§ Self health has no web-network qualifier — an
internal-only `web`-role core service reached via `uses` is exactly what must be
probeable one hop away."* The justification is the fan-out — "probeable one hop away"
is a statement about a sibling proxying it. `healthchecks.md § What this doctrine does
not do` now says a non-`web` service *"needs no HTTP surface of any kind — a queue
consumer built under this doctrine listens on nothing."* So the widening is not
narrowed by accident; its entire premise was removed. This holds under either Q1
outcome.

### 9.4 `test_pipeline_check.py`

- `test_check_health_endpoint_missing_failure` — asserts `"health_endpoints" in out`.
  Retargeted to the new gate name under Q1-approved; deleted under Q1-declined.
- `test_check_contracts_missing_failure` — contract filename updated.
- The five `_gate_healthcheck_tooling` unit tests (and the `_hc_ctx` helper and
  `fake_docker`'s build/run scripting they rely on) **deleted** with the gate.
- `test_check_happy_path_aggregates_all_passing` — the roster assertion.

### 9.5 Integration

- `test_check_real.py`: the contract filename in both tests.
  `test_check_real_fails_on_missing_contract_health` **survives under Q1-approved**
  (it rewrites the contract to drop `/health`, which is exactly the surviving
  assertion) and is **deleted under Q1-declined**, leaving `check`'s only
  contract-content integration failure mode unrepresented. See Q1.
- `test_check_hcgate_real.py`: **deleted entirely.** The file exists solely to
  exercise the curl gate against real `docker build` + `docker run`; with the gate
  gone it has no subject. Integration count 20 → 18.

## 10. Out of scope, deliberately

- `tables/roles/*.yml` — the emitted probe is mod 127's. Between this mod and that
  one, a non-`web` core service gets no container probe at all; mod 125 recorded that
  truthfully in two inverted tests tagged `# MOD 127:`, and nothing here touches
  them.
- `stagetest.py` (mod 128), `release.py`'s Service Connect strings (127),
  `test_projects/` (129/130).
- `plans/core/masterplan.md` § *The contract and health gates* — describes the model
  being deleted and is **mod 131's**. Left alone.
- `plans/core/compiler.md` § Validation — brought current by mod 125. Not redone.
- The documentation step of this cycle touches `CHANGELOG.md` and nothing in
  `plans/core/` except where a statement about the *gate roster* is now false; the
  roster's own doc block is mod 131's.

---

## Design questions

### Q1 — the self-health contract assertion

**The brief orders `_gate_health_endpoints` deleted "entirely, along with the
`/health/<codebase>/<service>` fan-out expectations and the self-`/health` contract
assertion." I am asking you to reconsider the third clause only, because the
committed doctrine asks for it twice, in the same imperative voice you used to retire
the curl gate.**

The rule of record, in two files:

> `healthchecks.md § web services also serve GET /health`: *"Where a `web`-network
> core service **also** declares an `openapi` surface, `GET /health` is part of that
> surface and belongs in its contract, **which the check step asserts as well**."*

> `cicd.md § Check Step` 3.4: *"Where the service *also* declares an `openapi`
> surface, its contract declares that path too. A `web`-network core service with no
> surface (a frontend, say) has no contract for the path to appear in, and needs
> none."*

Both sentences were written by the same doctrine pass that deleted the fan-out. They
are not survivals; they are the *narrowed* form of the assertion, and `cicd.md`'s
list of what the check step does has exactly one item this mod would otherwise leave
unowned.

The symmetry with your `_gate_healthcheck_tooling` ruling is the argument. That gate
dies because *"a gate enforcing a requirement the rule of record has withdrawn is
worse than no gate"* — and I verified the withdrawal by grep before agreeing. Run the
same test here and it comes back the other way: the requirement is not withdrawn, it
is restated in two files, one of them the enumerated list of this command's own
duties. Deleting the gate anyway would be the mirror-image error — dropping a gate
the rule of record still asks for.

**Recommendation: keep the assertion, radically narrowed, as its own small gate
`_gate_contract_health_path` (~30 lines).**

*Scope.* For each core service that is on the `web` network **and** declares at least
one `openapi` surface: at least one of its existing openapi contracts declares a
`GET` on the service's `health_check_path`. Rule 33 guarantees the field is present,
so there is no absent-field branch.

Three sub-decisions inside that, each of which I will take on my own authority if you
approve the shape:

1. **The path asserted is the declared `health_check_path` value, not the literal
   `/health`.** `healthchecks.md` says both ("serves `GET /health`" and "the path is
   declared by the core service's `health_check_path` field"). Reading the field is
   never wrong and is right for a project that declares `/healthz`; hardcoding
   `/health` would fail a conforming project.
2. **"At least one" openapi surface, not all of them.** A core service with
   `rest_public` and `rest_admin` serves the path once. Requiring it in both would
   force `rest_admin`'s contract to document a route that is not part of that
   boundary — and `cicl.md § Surfaces` offers that exact pair as the canonical
   two-surfaces-one-format case, so it is not hypothetical.
3. **`web`-network membership, not role.** Consistent with rule 33, which mod 125
   keyed on networks for the same reason: the field is what the reverse proxy reads,
   and a `role: web` service off the `web` network has no reverse proxy.

*What is lost if you rule for deletion.* Not much in unit coverage, but one specific
thing: `test_check_real_fails_on_missing_contract_health` is `check`'s only
integration test that breaks a contract's *content* rather than its existence, and it
has no subject left. `docex` would then never read a contract file's body at any
point in the pipeline — contract *tests* are the project's own `test.sh` concern — so
`ContractInvalid` becomes permanently unraisable and the word "invalid" leaves the
tool's vocabulary. That may be a defensible place to land; it should be a decision
rather than a side effect.

*If you rule for deletion,* say so and I will delete it, drop the integration test,
and note in `ContractInvalid`'s docstring that no gate raises it.

### Q2 — one note, no question (see also Ruling 5)

`docex check` on both seed projects stays red after this mod for **two** reasons, not
one. The advance plan books the missing `health.sh` (mod 129). The second is § 8's
orphan clause: the seed projects' contract files are still three-segment, so they will
fail as unparseable orphans as well as missing expectations. Same mod fixes both, same
GATE covers it, no action wanted — recorded only so the failure output does not read
as a surprise when mod 129 opens.

---

## Rulings (sarge, at design review)

Recorded so they are not re-litigated during implementation or review.

1. **Q1 — KEEP the self-`/health` assertion, in the narrowed form proposed. The
   original order was wrong and is withdrawn.** Sarge re-read both sentences directly
   rather than accepting them on report. Reason of record: the same doctrine pass that
   deleted the fan-out wrote them, which makes them the *narrowing* rather than
   residue — and the test sarge supplied for `_gate_healthcheck_tooling` ("is the
   requirement withdrawn?") returns the opposite answer here. Implement
   `_gate_contract_health_path`: `web`-network **and** at least one `openapi` surface;
   assert `GET` on the **declared `health_check_path` value**, never a hardcoded
   `/health`.
2. **"Satisfied by any one `openapi` surface" — approved, and the argument goes in the
   code comment, not only here.** The doctrine says "an `openapi` surface", singular,
   and does not contemplate two. The alternative reading (require the path in *every*
   openapi surface) is worse than lenient: it would force `rest_admin` to document a
   route that is not part of the admin boundary, i.e. a **false** contract. A contract
   that documents something outside its own boundary is a worse defect than one that
   omits something documented next door. "Any one" is the reading under which every
   contract stays true.
   Sarge is **not** editing the doctrine to close the ambiguity — authority from the
   operator covers `cicl.md`, and these two sentences live in `healthchecks.md` and
   `cicd.md`. The ambiguity and the chosen reading go in the advance report for the
   operator to close or leave. Nothing here blocks on it.
3. **`test_internal_openapi_provider_requires_self_health` dies — ratified**, with one
   addition to the reasoning worth keeping: a non-`web` `openapi` provider is a
   perfectly coherent thing (internal REST, reached by magic ref, `port` required by
   rule 32's positive arm, `health_check_path` forbidden by rule 33), and it must
   **not** declare `/health` in its contract. The old test asserted the opposite.
4. **The orphan clause's unparseable arm — ratified as the most valuable thing in the
   design.** An existence-only gate is blind to a half-renamed contracts directory
   *precisely because the new file also exists*. Two directives:
   1. The failure message must **name the expected four-segment form** and say
      "rename or delete", so the operator does not have to infer which.
   2. `upgrades/upgrade_2.0.0.md` gets a Verification line grepping for surviving
      three-segment filenames. **Mod 131's**, booked by sarge; recorded here so it is
      recorded twice.
5. **`_FORMAT_EXTENSIONS` in `check.py` — agreed, for the stated reason.** Mod 125 put
   the style table in `model.py` because two consumers needed it; a one-consumer table
   does not earn a home outside its consumer, and reaching into another mod's
   territory to place a table you alone read would be the wrong instinct.
6. **The two double-report skips — approved, conditional on a `run_check`-level
   test.** The skips are honest only because the gates and `run_compile` share one
   `run_check` invocation, so a mixed-format surface still fails the command with rule
   29's message. **Pin the ordering with a test at the `run_check` level, not only at
   the gate level** — a skip that is honest today becomes a hole the moment someone
   reorders `run_check`, and the test is what makes the ordering load-bearing rather
   than incidental.
