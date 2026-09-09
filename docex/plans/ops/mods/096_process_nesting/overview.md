# Mod 096 — Process nesting

Phase 2 of the **service process types** advance
([plan](../../advances/004_next/service_processes_implementation_plan.md),
[design record](../../advances/004_next/service_processes_refactor.md)).
The rule of record is [`cicl.md`](../../../../doctrine/infrastructure/cicl.md)
as written by Mod 094; where the design record and the doctrine differ in
wording, the doctrine wins.

## Goal

Make `processes:` real. One core service key in `infra.yml` expands into **N**
compiled services, one per process type. This is the format break: it is gated
on `cicl_version: "2"`, every core service's emitted identity gains a second
segment, and nothing about it is additive. Everything in this mod lands together
or the suite is red.

Baseline to beat: **748 passed** (`pytest tests/unit`).

## The backbone

```
CoreService(api) × {web, worker, nightly_cleanup}
    -> CompiledService(name="api-web",             core_service="api", process="web")
    -> CompiledService(name="api-worker",          core_service="api", process="worker")
    -> CompiledService(name="api-nightly_cleanup", core_service="api", process="nightly_cleanup")
```

> **`CompiledService.name` carries the two-segment compiled identity (`api-web`);
> the authoring models keep the authoring names.**

Plus one value type carrying the dots-for-reference / hyphens-for-emission rule
so it is expressed once rather than at every read site:

```python
@dataclass(frozen=True)
class ProcessRef:
    service: str
    process: str
    @classmethod
    def parse(cls, raw: str) -> "ProcessRef": ...   # "api.web"; a bare name is an error
    @property
    def dotted(self) -> str: ...                    # "api.web"
    @property
    def compiled(self) -> str: ...                  # "api-web"  == CompiledService.name
```

### The "correct for free" claim — verified, with three exceptions

I audited every derivation from `svc.name` / `svc.global_name` in
`emit/hcl.py` (1271 lines) and `emit/compose.py` (820 lines) rather than
trusting the claim. **It holds broadly**: the following all become correct with
no emitter change, because producer and consumer both read the compiled
identity and therefore move together.

| Site | File:line | Why it is free |
| --- | --- | --- |
| ECS container name | `hcl.py:329` | anchors `:425`, `:428`, `:589`, `:607`, all of which read the same value |
| task-definition address + family | `hcl.py:474-475` | `ecs` policy `max_len: 255`; no overflow risk |
| ECS service address + name | `hcl.py:565-566` | matches `:474` |
| paired sidecar container | `hcl.py:425,428`; `compose.py:215,559-561` | `{name}-otelcol`, one per process type — intended |
| Service Connect `port_name` / `discovery_name` / `dns_name` | `hcl.py:345,589,590,593` | `:345` and `:589` agree by construction |
| CloudWatch log group + address | `hcl.py:465-466` | per process type, per Settled Convention 11 |
| target group + listener rule | `hcl.py:633-637,669-674` | see the `alb` caveat below |
| ALB rule priorities | `hcl.py:634` vs `:1230` | both keyed on `s.name` |
| traefik router / service keys | `compose.py:149-159`; `hcl.py:375` | keyed on `global_name` |
| compose service key | `compose.py:537` | keyed on `global_name` |
| envinfra tag block | `compile.py:866-896` | tag *values* churn on first apply — upgrade-guide note |
| scheduler IAM role / EventBridge schedule | `hcl.py:850-853,864,880,903-904` | see the `iam` caveat below |
| network SGs | `main.tf.j2:60` via `hcl.py:1261` | emitted from `networks_sorted`, not per service — cannot duplicate |

**Three places where it does not hold**, all of which this mod fixes:

1. **`_image_ref` (`compile.py:287-322`)** must be fed `core_service`, not
   `name`. Otherwise the compose/HCL image ref becomes `<proj>/api-web:<ver>`
   while `containerize.py:155` pushed `<proj>/api:<ver>` — build succeeds, push
   succeeds, **release fails at pull time**. The same call also builds the
   elastic remote-state output key `ecr_repository_{service}_url`, which
   `project.tf.j2:777` only declares for codebase names.
2. **The migrate task definition (`hcl.py:509-550`)** is emitted *inside* the
   per-process `render_task_definition`, so a three-process codebase would emit
   three `…-migrate` families — and neither `release.py:401` nor
   `migrate.py:325-351`, which independently reconstruct the address
   `{codebase}_migrate` and the family `{project}-{env}-{codebase}-migrate`,
   would match any of them. `release.py`'s targeted pre-migrate apply would
   silently no-op and the migration would then run against the *previous
   release's* task definition. See § Migration carrier.
3. **`emit/ansible.py:23-30`** compares a backing service's `schema_owned_by`
   (an authoring key) against `CompiledService.name`. Under the rename the
   comparison silently never matches, `core_services_with_schema` goes empty,
   and the fixed stage/prod playbook emits **no migrate tasks at all** while
   reporting success. This site was not on the assigned list; it is the most
   dangerous silent failure in the mod.

Two naming caveats that are the policies working as designed, not bugs:

- **`alb` (32 chars, `hash_truncate`)** starts biting target-group names. The
  descriptive form survives in the `Name` tag. Existing target groups whose
  names previously fit will be renamed → destroy/recreate on first apply.
  Upgrade-guide note (Mod 107).
- **`iam` (64 chars, `overflow: error`)** applies to
  `apply_policy(f"{global_name}_scheduler", iam)` at `hcl.py:850-853`. With a
  fourth segment this can now *hard-fail at compile* for a long
  project+env+service+process name. That is a clean failure at the earliest
  layer, which is the doctrine's stated preference — but it is new, and it is
  worth a test pinning the message.

## Model (`cicl/model.py`)

**`ProcessType`** — new. `extra="allow"` so role-specific fields (`schedule`,
`health_check_path`) land in `model_extra`, exactly as `_ServiceBase` does
today.

| Field | Required | Notes |
| ----- | -------- | ----- |
| `role` | yes | |
| `command` | **yes** | `str \| list[str]`, non-empty. Rule 23. Supersedes the Dockerfile `CMD`. |
| `networks` | yes | `min_length=1` |
| `resources` | yes | Rule 10 |
| `port` | no | |
| `depends_on` | no | backing services only (rule 24) |
| `replicas` | no | default 1, `ge=1`. **Carried, never emitted** — Mod 100 |
| `env` | no | merges over the service-level block |

**No `consumes`.** That is Mod 098. A project writing `consumes:` in this
window trips `tt_rule_4_undeclared_field`; the fixtures do not, and Mod 098
lands before Mod 107 migrates the smoke projects.

**`CoreService`** becomes `{processes, secrets, config, env}` with
`extra="forbid"`. `processes: dict[str, ProcessType]` required and non-empty
(rule 22). Everything else moves to `ProcessType`.

Bare `extra="forbid"` yields pydantic's *"Extra inputs are not permitted"*,
which does not hint at the nesting. Since a stray service-level `role:` /
`resources:` / `command:` is *the* migration mistake, a `mode="before"`
validator on `CoreService` intercepts the known-moved key set and raises a
targeted message naming `processes:` and the upgrade guide.

**`ProcessRef`** — as above. `parse()` requires exactly two dot-separated
non-empty segments; a bare name and a three-segment value are both errors with
a message showing the expected form.

**`domain_default_service` → `domain_default_process`**, taking a dotted ref.

**`cicl_version`** validated: `"2"` accepted, anything else rejected. `"1"`
gets a bespoke message naming `upgrades/upgrade_1.6.0.md` (the guides live at
`$jb/upgrades/`, written in Mod 107). Rule 21.

`all_services()` keeps returning authoring models keyed by authoring name — it
is the *authoring* view and every validator depends on that. A new
`all_processes()` yielding `(service_name, process_name, CoreService,
ProcessType)` is the process-level walk.

## Validate (`cicl/validate.py`)

`_STANDARD_CORE_FIELDS` splits:

```python
_STANDARD_SERVICE_FIELDS  = {"processes", "secrets", "config", "env"}   # model-enforced
_STANDARD_PROCESS_FIELDS  = {"role", "command", "networks", "depends_on",
                             "port", "env", "resources", "replicas"}
```

`_validate_role_specific_fields` walks process types against
`_STANDARD_PROCESS_FIELDS`; the service level needs no walk (the model forbids
extras outright).

Re-scoped per process type: **10** (resources), **11** (no GPU on elastic),
**12** (`domain_default_process` names a web-network *process*), **14**
(reserved-name list applies to process names too), **15** (web-network process
declares a port), **16** (effective env vs `secrets`/`config`), **28**
(`health_check_path` obliges a `port` — currently reads `svc.model_extra` on
the wrong object once `ProcessType` exists, as Mod 095's corporal flagged).
`_validate_scheduler_services` re-scopes to scheduler *processes*; its
command-required half becomes redundant against the model and collapses to the
`schedule` cron check.

`_RESERVED_CORE_ENV_KEYS` and `DOCTRINE_INJECTED_SECRETS` are evaluated against
each process type's **effective** env (service ∪ process) plus the service's
`secrets` / `config`, so a process-level block cannot shadow
`OTEL_SERVICE_NAME`.

### Rule 5 — rendered data-plane identity

> The rendered data-plane identity of every emitted service must be unique
> after naming-policy normalization, across core process types **and** backing
> services.

`validate_document(doc, tables)` has no project name or env, and does not need
one: the `{project}_{env}` prefix is common to every service, so uniqueness of
the suffix is necessary and sufficient. Every policy that reaches a service
`global_name` (`ecs`, `rds`, `s3`) is hyphen-separated, and two are
lower-cased, so normalizing to **hyphenate-and-lowercase** is the conservative
(most-collision-detecting) form:

```
core:    f"{service}-{process}".replace("_", "-").lower()
backing: service.replace("_", "-").lower()
```

Catches all three collision classes the design record names: `api`+`web-v2` vs
`api-web`+`v2`; core `api`+`db` vs a backing service named `api-db`;
`my_api`+`web` vs `my`+`api_web`. `model.py::_validate_service_names` keeps its
exact-duplicate and core/backing-overlap checks — those are structural and
per-document; rule 5 extends rather than replaces them.

### Rule 24 — pulled forward from Mod 098

`depends_on` names backing services only. Pulled forward because expansion
makes a core→core edge genuinely unrepresentable: `compose.py:445`'s
`simple_to_global` cannot resolve a bare core name to one of N process types,
and `compose.py:585` would pass the unresolved name straight through into a
compose file that fails at `up` time. Implemented as a hard error whose message
points at `consumes:` and says it arrives in Mod 098.

Consequence for rule 6: with core→core gone, core process types are leaves, so
cycle detection runs over the backing-service graph alone. Unknown-target
checking still spans every `depends_on` list.

### Rules 22, 23, 26, 27

22 (non-empty `processes`, nothing else at the service level) and 23 (`command`
required) are model-enforced, consistent with how rule 1 is handled today; 26
(`replicas` on a `scheduler`) and 27 (`web` in `networks` on a `worker` or
`scheduler`) are new checks in `validate.py`. 27 replaces the prose-only,
unenforced note in `_validate_scheduler_services`.

### Bare core magic refs

`contexts` and `engines` re-key to the compiled identity, so a three-segment
core ref `${core_services.api.host}` no longer finds a context. Mod 097 owns
making the *four*-segment form resolve; this mod owns the honest failure in the
meantime, which is doctrine as written (`cicl.md § Magic Refs`: a bare core
service name is illegal, not shorthand). Both the validator and the resolver
reject it with a message naming the four-segment form. No fixture or test
resolves a core magic ref today — `test_magic_refs.py:115` only exercises
`find_magic_refs` as string parsing — so nothing goes red in the window.

## Compile (`cicl/compile.py`)

- `_global_service_name` takes a fourth segment (core only; backing stays
  three).
- `engines_by_service` (`:507-531`) and `contexts` (`:534-551`) re-key to the
  compiled identity, because `role` — and therefore the engine — is now
  per-process. The `role_name` / `port` / `networks` context entries come from
  the `ProcessType`; `name` becomes the compiled identity.
- The per-service loop (`:570-785`) iterates backing services plus
  `(service, process)` pairs. `compiled_services[compiled_name]` replaces the
  single-slot assumption at `:743`.
- `CompiledService` gains `core_service: str | None`, `process: str | None`,
  `replicas: int = 1`. Backing services leave the first two `None`.
- Role-field routing (`:598-618`) and `schedule` extraction (`:780-784`) read
  the `ProcessType`'s `model_extra`. Both are silent failures if missed — the
  scheduler's `schedule` simply becomes `None` and no job ever fires.
- `_resources_to_elastic` / `fargate.py:105,134,159` take a `where=` path
  argument so errors read
  `core_services.<svc>.processes.<proc>.resources.disk`. (`fargate.py` receives
  `service_name` as a plain string, so this is a threading change, not a
  structural one.)
- `_apply_elastic_invariants` passes `process` through to `standard_tags`,
  which gains a `process: str | None` parameter; `Name` becomes
  `{project}_{env}_{service}_{process}` for core, unchanged for backing.
- `_web_hosts` / `web_hostnames_for_env` walk process types; `per_service`
  becomes the two-segment label; `domain_default_process` is compared against
  the compiled identity.
- **Host-port publishing stops for non-`web` core process types**
  (`:647-648`), per ruling 5. Backing services keep theirs. Two lines, and it
  closes a day-one `dev` collision between the workers of two codebases that
  this mod would otherwise open.
- `CompiledService` also gains `service_env` (the codebase-scoped env surface,
  § Migration carrier) and `codebase_global_name`
  (`apply_policy(f"{project}_{env}_{core_service}", policy)`) so the migrate
  family has a codebase-keyed form. `migrate.py:325-351` reconstructs the same
  string through the same helper, which makes the two provably agree rather
  than agreeing by coincidence — a test asserts it.

### Kept on the codebase, not the process

The main hazard. Getting any of these wrong defeats the advance.

| Site | Keyed on |
| ---- | -------- |
| `_image_ref` (`:287-322`) incl. `ecr_repository_{svc}_url` | `core_service` |
| `emit_hcl_project(core_service_names=…)` (`:1013`) | `list(infra.core_services)` — already correct, must stay |
| `core_owning_schema` (`:562-568`) / `schema_owned_by_db` (`:772`) | `core_service` |
| compose bind mounts (`compose.py:466-476`) and build context (`:486`) | `core_service` |
| ofelia job image (`compose.py:317` via `body["image"]`) | inherits `_image_ref`, therefore `core_service` |

### The `http_host` policy actually has to be wired

`http_host` gains `max_len: 63, overflow: error`, but today the policy is
applied at exactly one site — the project label in `emit_hcl_project`
(`hcl.py:1101-1102`). The label that grows is the *service* label, and
`_web_hosts` builds it with a bare `_dns_label()` call that consults no policy.
So adding the cap alone would be inert. `_web_hosts` and
`web_hostnames_for_env` therefore take the `http_host` policy and route the
service label through `apply_policy`; `preinfra.py:175` passes
`ctx.transfer_tables.naming_policies`. Without this the cap is decoration —
and a cap that nothing applies is worse than no cap, because it reads as
enforcement.

**Hard guard (C.O. ruling).** For every existing fixture the wired
`apply_policy(…, http_host)` must produce hostnames **byte-identical** to
today's `_dns_label()` output, modulo the intended new process segment. A
silent hostname change would invalidate TLS certs and DNS records for every
deployed project beyond what this advance intends.

The equivalence holds *by construction* and I have checked it against both
implementations rather than asserting it:

```
_dns_label(n)                  = n.replace("_", "-").lower()
apply_policy(n, http_host)     = n.replace("_", "-")   # separator: hyphen
                                  .lower()             # case: lower
                                  + length check       # max_len: 63, overflow: error
```

Identical for every input of 63 characters or fewer; the only new behavior is
a compile error above that. A test pins the equivalence directly. **If the
implementor finds any existing label changes, stop and raise rather than
proceeding.**

## Downstream re-scoping this mod is forced to carry

The assigned scope lists these as an audit; the audit found each of them is
load-bearing for a green suite. Semantics are held constant — this is
mechanical re-scoping only, and the mods that own the *behavior* are named.

| Site | Change | Owner of the semantics |
| ---- | ------ | ---------------------- |
| `check.py:120,321,328,386,403,410,478` | read process types instead of `CoreService` attributes; five of these are hard `AttributeError`, and `:478` is a **silent** pass that defeats Mod 051's curl gate entirely | Mod 101 |
| `_common.py:116` `scheduler_services` | `getattr(svc, "role", …)` silently returns `[]` for every project, taking `up.py:195,206` and `test.py:139` down the wrong branch with no error. Split into `scheduler_services` (codebases with *any* scheduler process) and `scheduler_only_services` (codebases with *no* long-running process) — the two call sites want different predicates | Mod 103 |
| `_common.py:142-166` `compose_service_key`, `build.py:109,120-127` | resolve to a codebase's **primary process** (below) instead of suffix-matching a bare name | Mod 099 deletes both |
| `migrate.py:340` | `tables.role(core.role)` — hard `AttributeError` on every elastic migrate, therefore every elastic release | — |
| `migrate.py:325-351`, `release.py:400-403` | left **unchanged**, and that is the point: keeping the migrate identity codebase-keyed is what keeps their independent reconstructions valid | Mod 099 |
| `emit/ansible.py:23-30` | filter on `s.schema_owned_by_db` rather than comparing an authoring key to `s.name` | — |
| `up.py:98-109,158,201-207,238` | primary-process resolution; scheduler predicates | Mods 099/103 |
| `preinfra.py:175` | follows from `web_hostnames_for_env` | Mod 104 pins the test |
| `describe/{dag,llm}.py` | node ids become two-segment for free; the dangling core→core edges resolve themselves once rule 24 lands | Mod 104 |
| `categories.py` | **no change** — every core-service read is `secrets`/`config`, which stay service-level; every `svc.role` read is a `BackingService` | — |
| `containerize.py:126,155`, `rollback.py:235-238`, `build.py:73,142`, `test.py:57,140`, `projinfra.py:177-181`, `check.py:531-547` | **no change** — correctly codebase-keyed already | — |
| `orchestrate/{down,aggregate}.py` | **no change** — verified clean | — |

### Migration carrier

`schema_owned_by_db` is set on exactly **one** compiled service per codebase,
and the migrate task definition it gates is emitted with the codebase-keyed
family `{project}-{env}-{codebase}-migrate` and address `{codebase}_migrate`.
That is what keeps `release.py:401` and `migrate.py:350` correct, and it emits
one migrate resource per codebase rather than N.

The carrier decides two separate things, and per the C.O.'s ruling they get
two separate answers.

**Env — service-level only. Permanent, not a bridge.** The design record's
§ Per-Codebase Operations states the rule as *"`migrate.sh`, `test.sh`, and
`build.sh` may depend only on codebase-scoped env"* — a rule about the scripts,
not about compose, so it has to hold on elastic too. Inheriting a process
type's env is exactly the trap that section identifies (`DATABASE_*` declared
on `api.web` breaking an exec into `api.worker`). `CompiledService` therefore
gains `service_env`: the service-level `env:` block resolved, plus
`secrets:` / `config:` / the doctrine-injected keys, and **excluding any
process-level `env:` overlay**. The migrate task definition consumes
`service_env`; Mod 099's exec service consumes the same field.

Scope limit, stated plainly: this lands on **elastic** in this mod, where docex
owns the migrate task definition's env directly. On fixed the playbook runs
`docker compose run --rm <compose service> /service/migrate.sh` inside the
carrier's own container, which necessarily carries that process's env. Mod
099's exec service is what brings fixed into line; this mod does not pretend
otherwise.

**Resources — lowest-sorted non-`scheduler`, an explicit temporary bridge.**
Falls back to lowest-sorted overall for a scheduler-only codebase. Non-scheduler
first because a scheduler's `resources:` is typically sized for a small job
(`0.25 vCPU / 512MB` in the doctrine's own example) and a migration inheriting
it could OOM. There is no settled answer for migration sizing and inventing a
doctrine-fixed one is above this mod's authority; the C.O. is carrying it to
the operator. Marked temporary at the definition site.

The same `primary_process()` helper backs `compose_service_key` — one rule, one
place. Its definition site names Mod 099 as the mod that deletes it, so 099
does not inherit it as load-bearing.

## Naming

`tables/naming_policies.yml` — `http_host` gains `max_len: 63, overflow:
error`, wired as above.

## Fixtures and tests

All four fixtures to `cicl_version: "2"` with `processes:`, and
`domain_default_service: api` → `domain_default_process: api.web`:

| Fixture | Rewrite |
| ------- | ------- |
| `sample_project` | `api` → one `web` process. `core/api/` unchanged (codebase-keyed) |
| `sample_project_elastic` | same |
| `sample_project_scheduler_fixed` | `api` → `web`; `nightly_cleanup` → `api`-sibling? **No** — kept as its own codebase with one `nightly_cleanup` process, preserving what the fixture tests (a scheduler codebase alongside a web codebase). A mixed-codebase case is Mod 103's fixture work |
| `sample_project_scheduler_elastic` | same |

`infra/contracts/api.openapi.yml` → `api.web.openapi.yml`.

`test_projects/{fixed,elastic}` are **not** rewritten here — they sit outside
`testpaths`, so the suite cannot catch them, and Mod 107 owns them along with
adding a genuine `worker` process to exercise the motivating capability.

Test churn is broad and mostly mechanical: **41 of 64 test modules** carry a
bare-`api` identifier (375 occurrences). Twelve modules build their own
`infra.yml` inline rather than using an on-disk fixture and each needs a
`processes:` block; nine more read a fixture and patch it. Heaviest:
`test_compose_emitter.py` (49), `test_hcl_emitter.py` (25),
`test_magic_refs.py` (19), `test_orchestrate_build.py` (18),
`test_hcl_sidecar.py` (18), `test_compile.py` (18).

**Do not paper over a behavioral change by editing an assertion.** Where a
test's *intent* becomes wrong rather than its literal, it goes in the drift
review rather than being quietly retargeted.

New coverage, at minimum:

- `processes:` absent, and `processes: {}`, both rejected
- service-level `resources:` rejected, with the targeted message
- a process type missing `command` rejected
- `cicl_version: "1"` rejected, message names `upgrades/upgrade_1.6.0.md`
- rendered-identity collision in **both** forms: two service+process pairs
  colliding, and a core process colliding with a backing service name
- core→core `depends_on` rejected, message points at `consumes:`
- one core service with three process types emits **three** compose services
  and **three** ECS services **all referencing one image**, and exactly **one**
  ECR repo / one migrate task definition / one `core/<svc>` build context
- a bare three-segment core magic ref fails with the four-segment hint
- `http_host` overflow: a >63-char service label fails at compile

## Implementation staging

`implementation.md` will be written as **five ordered stages**, each
independently self-checkable, because the diff is too large to hold safely in
one context:

1. **Model + `ProcessRef`** — `cicl/model.py` only. Self-check: the four
   fixtures parse under the new schema (fixtures rewritten in this stage);
   everything downstream is red, which is expected and stated.
2. **Validate** — `cicl/validate.py`, rules 5/10/11/12/14/15/16/21-24/26-28.
3. **Compile + naming** — `cicl/compile.py`, `cicl/fargate.py`,
   `emit/tags.py`, `tables/naming_policies.yml`. Self-check: the four fixtures
   compile; `emit/` is untouched.
4. **Emit + downstream** — `emit/{compose,hcl,ansible}.py`,
   `orchestrate/*`, `pipeline/{check,preinfra}.py`.
5. **Tests** — the mechanical churn plus the new coverage. Self-check: 748+
   green.

Stages 1-3 go to one implementor pass and stages 4-5 to a second, so neither
pass has to hold the whole diff.

**The first pass is not expected to leave the suite green** — it deliberately
lands the model/validate/compile break without the emit and test side. What it
*is* required to do is leave the suite in a **known** state: its report must
carry the exact failure count and confirm that every failure traces to work
assigned to stages 4-5. A red suite between passes is fine; a red suite that
cannot be accounted for is not, and is the signal to stop rather than continue.

## Out of scope

`consumes` (098) · four-segment magic refs (097) · the exec service and
`compose_service_key` deletion (099) · replica **emission**, fixed unroll and
elastic `desired_count` (100) — `replicas` is carried onto `CompiledService`
and nothing is emitted from it · contract and health **gates** in `check.py`
(101) · the two new `docex.*` telemetry attributes (102) · ofelia rework (103) ·
`describe` (104) · any doctrine file (106) · any version artifact (107).

`OTEL_SERVICE_NAME` becomes two-segment as a side effect of the compiled
identity changing. Expected and correct; Mod 102 adds the resource attributes
on top.

---

## Design questions — resolved

All six were ruled on by the C.O. before implementation. Recorded here so the
mod is self-contained.

**1. Migration carrier — split answer.** *Env:* service-level only, and
**permanent**, not a bridge — the design record's rule is about the scripts,
not about compose, so it must hold on elastic. *Resources:* lowest-sorted
non-`scheduler`, accepted as an explicit temporary bridge, marked as such at
the definition site. "What resources should a migration get" is carried to the
operator as an open question. See § Migration carrier.

**2. `primary_process()` bridge — confirmed.** Leaving `orchestrate` red for
three mods violates the advance's green-at-every-boundary constraint. The
helper's temporary status must be impossible to miss at the definition site,
naming Mod 099 as the mod that deletes it.

**3. Reject bare core magic refs here — confirmed.** The resolver's key domain
changes whether this mod acts or not, so the real choice is between a good
error and a bad one. Mod 097 still owns making the four-segment form resolve.

**4. Wire `http_host` — confirmed**, with a hard byte-identity guard on every
existing hostname. See § The `http_host` policy actually has to be wired.

**5. Host ports for non-`web` core process types — fold the fix in.** This
reverses the deferral given to Mod 095's corporal, because the situation
changed: the collision is no longer between replicas of one process type (Mod
100's territory) but between workers of two *different codebases*, in `dev`,
on day one. `compile.py:647-648` stops publishing for non-`web` **core** process
types; backing services keep their publish. The justification is clean — the
health port is probed from inside the netns by the container healthcheck and
from a sibling over the internal network, and elastic never published, so
removing it *improves* dev/prod parity. Flagged-for-operator #2 is resolved
here; Mod 100 should not expect it.

**6. `iam` hard-fail — accept the clean compile error.** The doctrine's stated
preference is loud failure over silent truncation. Pinned with a test; the
upgrade-guide note lands in Mod 107. Whether `iam` should hash-truncate like
`alb`, and whether the two policies should agree, is a naming-policy change and
therefore a doctrine change — raised to the operator, not decided here.
