# Mod 096 — Process nesting: implementation

Design: [`overview.md`](./overview.md). Rule of record:
[`cicl.md`](../../../../doctrine/infrastructure/cicl.md) (written by Mod 094 —
already committed; **do not edit any doctrine file in this mod**).

Repo root for every path below: `/home/ubuntu/.claude/jean_baudrillard`.
`docex/` paths are relative to that unless stated.

**Baseline: 748 passed** (`cd docex && python3 -m pytest tests/unit -q`).

---

## How this document is organized

Five ordered stages. Each has a **self-check** you run before moving on.

- **Pass A = stages 1-3.** Model, validate, compile. The suite will be **red**
  at the end of pass A and that is expected — emit and tests are untouched.
  Pass A's report must state the exact failure count and confirm every failure
  traces to stage 4 or 5 work.
- **Pass B = stages 4-5.** Emit, downstream, tests. Ends green at 748+.

Do not reorder. Stage 3 depends on stage 1's model; stage 4 depends on stage
3's `CompiledService` shape.

## Two rules that override any instinct to be clever

1. **Never edit a test assertion to make a behavioral change go away.** If a
   test's *intent* is now wrong (not just its literal string), leave it failing
   and write it up in your report. Retargeting a test to match new behavior is
   only correct when the behavior change is one this document specifies.
2. **If the `http_host` equivalence guard trips (stage 3), stop and report.**
   Do not proceed past it.

---

# Stage 1 — Model and `ProcessRef`

**Files:** `docex/src/docex/cicl/model.py`, the four fixture `infra.yml` files,
one contract rename.

## 1.1 `ProcessRef`

Add to `model.py`, above `ProjectManifest`:

```python
@dataclass(frozen=True)
class ProcessRef:
    """A reference to one process type of one core service.

    Dots for reference, hyphens for emission (cicl.md § Dots for reference,
    hyphens for emission). Authoring and reference forms — ``consumes:``
    targets, ``domain_default_process``, magic refs, ``describe`` node ids —
    are dotted; emitted data-plane names are hyphenated. This type is the one
    place that rule is expressed.
    """

    service: str
    process: str

    @classmethod
    def parse(cls, raw: str) -> "ProcessRef":
        """Parse ``"api.web"``. A bare name is an error, not shorthand."""
        parts = raw.split(".")
        if len(parts) != 2 or not all(p.strip() for p in parts):
            raise ValueError(
                f"{raw!r} is not a valid process reference. The form is "
                f"'<service>.<process>' (e.g. 'api.web'). A bare core service "
                f"name is illegal, not shorthand: a codebase has no single "
                f"boundary. See cicl.md § Magic Refs."
            )
        return cls(service=parts[0], process=parts[1])

    @property
    def dotted(self) -> str:
        return f"{self.service}.{self.process}"

    @property
    def compiled(self) -> str:
        """The two-segment compiled identity — ``CompiledService.name``."""
        return f"{self.service}-{self.process}"
```

`from dataclasses import dataclass` at the top of the module.

## 1.2 `ProcessType`

Add after `Resources`. It does **not** inherit `_ServiceBase` — the base's
`role`/`networks`/`depends_on`/`port` set is close but the requiredness differs
and `BackingService` still needs the base as-is.

```python
class ProcessType(BaseModel):
    """One named way of invoking a core service's build artifact.

    Its own role, command, resources, networks and port. One codebase, one
    image, N process types. See cicl.md § Process Types.
    """

    # Role-specific fields (health_check_path, schedule, ...) land in
    # model_extra, exactly as they do on _ServiceBase today. Role-specific
    # fields follow `role`, which is invocation-determined, so they are
    # process-scoped by derivation (cicl.md § Field scoping).
    model_config = ConfigDict(extra="allow")

    role: str
    # Rule 23. Required on EVERY process type including `web`: with several
    # process types sharing one image, at most one could inherit the
    # Dockerfile CMD and "which one" is an ambiguity worth deleting.
    command: str | list[str]
    networks: list[str] = Field(min_length=1)
    resources: Resources
    port: int | None = None
    # Rule 24: backing services only. A core process type here is an error.
    depends_on: list[str] = Field(default_factory=list)
    # Carried onto CompiledService; NOTHING is emitted from it in this mod.
    # Emission (fixed unroll + elastic desired_count) is Mod 100.
    replicas: int = Field(default=1, ge=1)
    # The only field valid at both levels. A process type's effective env is
    # the service-level block merged under its own (cicl.md § Field scoping).
    env: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_command_nonempty(self) -> "ProcessType":
        if isinstance(self.command, str):
            if not self.command.strip():
                raise ValueError("command must not be empty")
        elif not self.command:
            raise ValueError("command must not be an empty list")
        return self
```

**No `consumes` field.** Mod 098 adds it. A project writing `consumes:` in this
window gets `tt_rule_4_undeclared_field`; that is correct for now.

## 1.3 `CoreService`

Replace the whole class. It no longer inherits `_ServiceBase`.

```python
# Fields that moved from the core service to the process type in CICL v2.
# Used only to produce a targeted migration error — see below.
_MOVED_TO_PROCESS = (
    "role", "command", "networks", "resources", "port",
    "depends_on", "replicas",
)


class CoreService(BaseModel):
    """A core service in ``infra.yml``: one codebase, one build artifact.

    The service level accepts only ``{processes, secrets, config, env}``
    (rule 22). Everything invocation-determined lives on a ProcessType.
    """

    model_config = ConfigDict(extra="forbid")

    # Rule 22: required and non-empty.
    processes: dict[str, ProcessType] = Field(min_length=1)
    env: dict[str, Any] = Field(default_factory=dict)
    secrets: dict[str, str] = Field(default_factory=dict)
    config: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _reject_v1_shape(cls, data: Any) -> Any:
        # WHY: bare extra="forbid" says only "Extra inputs are not permitted",
        # which does not hint at the nesting. A stray service-level `role:` /
        # `resources:` / `command:` is THE migration mistake from CICL v1, so
        # it gets a message that names the fix.
        if not isinstance(data, dict):
            return data
        stray = sorted(k for k in _MOVED_TO_PROCESS if k in data)
        if stray:
            raise ValueError(
                f"{stray} moved from the core service to the process type in "
                f"CICL v2. Nest them under a named entry in a `processes:` "
                f"block. Only {{processes, secrets, config, env}} are valid "
                f"at the service level (cicl.md § Field scoping, rule 22). "
                f"See upgrades/upgrade_1.6.0.md."
            )
        return data
```

Keep `_ServiceBase` unchanged — `BackingService` still uses it.

## 1.4 `CICLDocument`

- Rename `domain_default_service` → `domain_default_process`. Update its
  docstring: it names a **process type**, dotted (`api.web`), and the canonical
  host form is `<service>-<process>.<env>.<project>.<apex_domain>`.
- Add a `cicl_version` validator:

```python
    @model_validator(mode="after")
    def _validate_cicl_version(self) -> "CICLDocument":
        # Rule 21. Rejected, not shimmed: a compatibility parser accepting
        # both forms would reintroduce the flat pre-`processes:` shape as a
        # permanent second code path, to serve a migration every project
        # performs exactly once. See cicl.md § CICL Version.
        if self.cicl_version == "2":
            return self
        if self.cicl_version == "1":
            raise ValueError(
                "cicl_version '1' is no longer supported. CICL v2 makes the "
                "`processes:` block mandatory on every core service and adds "
                "the `consumes` relation and four-segment core magic refs. "
                "Follow upgrades/upgrade_1.6.0.md to migrate this infra.yml, "
                "then set cicl_version: \"2\"."
            )
        raise ValueError(
            f"unknown cicl_version {self.cicl_version!r}; the current "
            f"generation of the CICL format is \"2\"."
        )
```

- Add the process-level walk next to `all_services()`:

```python
    def all_processes(self) -> list[tuple[str, str, CoreService, ProcessType]]:
        """Every ``(service_name, process_name, service, process)``, sorted.

        The process-level companion to :meth:`all_services`, which stays the
        *authoring* view (authoring models keyed by authoring name) because
        every validator depends on that.
        """
        out = []
        for svc_name in sorted(self.core_services):
            svc = self.core_services[svc_name]
            for proc_name in sorted(svc.processes):
                out.append((svc_name, proc_name, svc, svc.processes[proc_name]))
        return out
```

- `_validate_service_names` keeps its existing checks unchanged. Add a
  process-name pattern check in the same validator: every process name must
  match `_SERVICE_NAME_RE` (same rule as a service name).

## 1.5 `primary_process()`

Add to `model.py` (it needs `CoreService`, and both `compile.py` and
`orchestrate/_common.py` consume it — putting it here avoids a circular
import).

```python
def primary_process(svc: CoreService) -> str:
    """The process type that stands in for a codebase when exactly one
    container must be chosen.

    !!! TEMPORARY BRIDGE — DELETED BY MOD 099 !!!

    Two consumers, both of which Mod 099 removes:

    1. The migrate task definition's *resources* (its env is codebase-scoped
       and does NOT come from here). Mod 099 hoists migration onto the
       per-codebase exec service.
    2. ``orchestrate/_common.py::compose_service_key``, which needs some
       container to ``compose exec`` into. Mod 099 deletes that function and
       replaces it with ``exec_service_key`` against an emitted exec service.

    Do not add a third consumer. If you need "which container represents this
    codebase", the answer after Mod 099 is the exec service, not this.

    The rule — lowest-sorted non-``scheduler``, falling back to lowest-sorted
    overall — is the design record's own named "cheaper fallback"
    (service_processes_refactor.md § Per-Codebase Operations). Non-scheduler
    first because a scheduler's ``resources:`` is sized for a small job and a
    migration inheriting it could OOM.
    """
    names = sorted(svc.processes)
    for n in names:
        if svc.processes[n].role != "scheduler":
            return n
    return names[0]
```

## 1.6 Fixtures

Rewrite all four. Each gets `cicl_version: "2"`,
`domain_default_service: api` → `domain_default_process: api.web`, and its
core services nested. **Keep every other value byte-identical** — same ports,
networks, `depends_on`, env, resources — so the only diffs downstream are the
ones this mod intends.

`command:` is now required. None of the four `api` services declares one today,
so add `command: ["python", "/service/dist/root.py"]` — this matches what
`test_projects/fixed`'s `reaper` already uses, so it is the established
in-repo form rather than a new invention.

### `docex/tests/fixtures/sample_project/infra/infra.yml`

```yaml
cicl_version: "2"
foundation: fixed
apex_domain: "example.com"
container_registry: "registry.example.com"
observability_backend_url: "https://hyperdx.luxrnd.tech"
domain_default_process: api.web

core_services:
  api:
    env:
      # api composes its own connection string from these parts at startup;
      # the identical magic refs work on both foundations (parts-only model).
      DATABASE_HOST: ${backing_services.appdb.host}
      DATABASE_PORT: ${backing_services.appdb.port}
      DATABASE_NAME: ${backing_services.appdb.db}
      DATABASE_USER: ${backing_services.appdb.user}
      DATABASE_PASSWORD: ${backing_services.appdb.password}
    processes:
      web:
        role: web
        command: ["python", "/service/dist/root.py"]
        port: 8080
        networks: [web, internal]
        depends_on: [appdb]
        resources:
          cpu: 1.0
          memory: 2GB
          disk: 20GB
```

`backing_services:` unchanged, including `schema_owned_by: api` — that names a
**codebase** and does not gain a process segment.

Note the `env:` block sits at the **service** level. It is codebase-scoped
(`DATABASE_*` — the code needs a database) and putting it there is what makes
the migrate task definition's service-level-only env non-empty, which stage 4
depends on.

### `docex/tests/fixtures/sample_project_elastic/infra/infra.yml`

Same transformation. Keep `disk: 25GB` and its comment; keep the absent
`container_registry`.

### `docex/tests/fixtures/sample_project_scheduler_fixed/infra/infra.yml`

Two codebases stay two codebases — `nightly_cleanup` is **not** folded into
`api`. This fixture exists to prove a scheduler codebase coexists with a web
codebase; a mixed web+scheduler codebase is Mod 103's fixture work.

```yaml
core_services:
  # A long-running web service alongside the scheduler — proves the
  # scheduler emit does not disturb ordinary services (sidecar, traefik).
  api:
    env:
      DATABASE_HOST: ${backing_services.appdb.host}
      DATABASE_USER: ${backing_services.appdb.user}
      DATABASE_PASSWORD: ${backing_services.appdb.password}
    processes:
      web:
        role: web
        command: ["python", "/service/dist/root.py"]
        port: 8080
        networks: [web, internal]
        depends_on: [appdb]
        resources:
          cpu: 1.0
          memory: 2GB

  nightly_cleanup:
    env:
      # DATABASE_HOST resolves to a literal -> inlined into the INI.
      DATABASE_HOST: ${backing_services.appdb.host}
      # DATABASE_USER resolves through postgres' `kind: fixed` POSTGRES_USER,
      # so it is inlined as the literal `appuser` (mod 077). DATABASE_PASSWORD
      # resolves to a $[VAR] secret -> sourced from the mounted env file.
      DATABASE_USER: ${backing_services.appdb.user}
      DATABASE_PASSWORD: ${backing_services.appdb.password}
    processes:
      nightly_cleanup:
        role: scheduler
        schedule: "0 3 * * 1-5"
        command: ["python", "-m", "jobs.cleanup"]
        networks: [internal]
        depends_on: [appdb]
        resources:
          cpu: 0.25
          memory: 512MB
```

The compiled identity is therefore `nightly_cleanup-nightly_cleanup`. That is
ugly but *correct* — it is what the doctrine's naming convention produces for a
scheduler-only codebase, and inventing a collapse rule is exactly what
`processes:`-is-mandatory exists to prevent. Note it in your report; do not
"fix" it.

### `docex/tests/fixtures/sample_project_scheduler_elastic/infra/infra.yml`

Same shape, `schedule: "0 3 * * *"`, and `api`'s five DB env parts as today.

### Contract rename

```
git mv docex/tests/fixtures/sample_project/infra/contracts/api.openapi.yml \
       docex/tests/fixtures/sample_project/infra/contracts/api.web.openapi.yml
```

Content unchanged. (`check.py`'s right-anchored filename parsing is Mod 101;
stage 4 only keeps the existing parse from crashing.)

**Do not touch `docex/test_projects/{fixed,elastic}`.** They are outside
`testpaths` and Mod 107 owns them.

## Stage 1 self-check

```bash
cd docex && python3 - <<'PY'
from pathlib import Path
import yaml
from docex.cicl.model import CICLDocument
for p in sorted(Path("tests/fixtures").glob("*/infra/infra.yml")):
    CICLDocument.model_validate(yaml.safe_load(p.read_text()))
    print("ok", p)
PY
```

All four must parse. Also confirm a v1-shaped document raises the targeted
message, not bare "Extra inputs are not permitted".

---

# Stage 2 — Validation

**File:** `docex/src/docex/cicl/validate.py`.

## 2.1 Field allowlists

Replace `_STANDARD_CORE_FIELDS` (`:42-45`):

```python
# Service level is model-enforced (CoreService.extra="forbid"); listed for
# documentation only.
_STANDARD_SERVICE_FIELDS = {"processes", "secrets", "config", "env"}
# Process level: everything ProcessType declares as a real field. Anything
# else must be declared in the engine's `fields:` block (tt rule 4).
_STANDARD_PROCESS_FIELDS = {
    "role", "command", "networks", "depends_on", "port", "env",
    "resources", "replicas",
}
```

`_STANDARD_BACKING_FIELDS` unchanged.

## 2.2 `_validate_role_specific_fields`

The core branch walks `doc.all_processes()` instead of `doc.core_services`,
checking each `ProcessType.model_extra` against `_STANDARD_PROCESS_FIELDS`.
`where=` becomes `core_services.<svc>.processes.<proc>.<field>`. The backing
branch is unchanged.

## 2.3 `_validate_magic_refs`

- The core-service scan walks process types. Templates come from the process's
  effective env (service ∪ process), its `command`, and its `model_extra`.
  Backing services keep today's behavior.
- **Reject bare core refs** (ruling 3). When `kind == "core_services"`, emit:

```python
ValidationIssue(
    rule="rule_3_bare_core_magic_ref",
    message=(
        f"magic ref ${{core_services.{target}.{part}}} in "
        f"{where_label!r} names a bare core service. Refs to core "
        f"services carry the process dimension: "
        f"${{core_services.<service>.<process>.<part>}} — did you mean "
        f"${{core_services.{target}.<process>.{part}}}? A codebase has no "
        f"single boundary, so a bare name has no answer. "
        f"See cicl.md § Magic Refs."
    ),
    where=where_label,
)
```

  and `continue` — do not also run the rule-3 "part exposed" and rule-7 checks
  against it. Rule 7 for backing targets is unchanged (`depends_on` must
  include the target), evaluated against the **process's** `depends_on`.

  A service-level `env:` ref to a backing service obliges **every** process
  type to declare the `depends_on` edge, consistent with `cicl.md`
  § Consumes Relationships § Three clarifications. Implement it that way: when
  the template came from the service-level `env:`, check every process.

## 2.4 `_validate_depends_on` — rules 6 and 24

Three parts:

1. **Unknown-target check** over every `depends_on` list: core process types
   (`where=core_services.<svc>.processes.<proc>`) and backing services.
2. **Rule 24 (new).** A `depends_on` entry naming a key in `doc.core_services`:

```python
ValidationIssue(
    rule="rule_24_depends_on_core_service",
    message=(
        f"core process type {svc}.{proc} declares depends_on: [{dep!r}], "
        f"which is a core service. `depends_on` is a readiness gate and "
        f"names backing services ONLY. Interface coupling between core "
        f"process types is a different relation with different rules and "
        f"lives in `consumes:` (arriving in Mod 098). "
        f"See cicl.md § Depends-On Relationships."
    ),
    where=f"core_services.{svc}.processes.{proc}.depends_on",
)
```

   Apply the same rule to a *backing* service declaring a core target.
3. **Cycle detection (rule 6)** now runs over the **backing-service graph
   only**. With rule 24 in force, core process types are leaves, so they cannot
   participate in a cycle. Keep the existing DFS; narrow its node set to
   `doc.backing_services`.

## 2.5 Rule 5 — rendered data-plane identity

New `_validate_rendered_identity(doc)`, registered in `validate_document`:

```python
def _normalized_identity(raw: str) -> str:
    # Every naming policy that reaches a service global_name (ecs, rds, s3)
    # is hyphen-separated and two of the three lowercase, so hyphenate-and-
    # lowercase is the conservative (most-collision-detecting) normalization.
    # The {project}_{env} prefix is common to every service, so comparing the
    # suffix alone is necessary and sufficient — which is what lets this run
    # without a project name or env.
    return raw.replace("_", "-").lower()
```

Build `dict[normalized, list[str]]` where the value is the human description
(`core process type 'api.web'` / `backing service 'api-db'`), over
`doc.all_processes()` (using `ProcessRef(svc, proc).compiled`) plus
`doc.backing_services`. Any bucket with more than one entry is a
`rule_5_rendered_identity_collision` issue naming both sides and explaining
that both render into the same data-plane namespace.

## 2.6 Rules re-scoped per process type

| Rule | Function | Change |
| ---- | -------- | ------ |
| 10, 11 | `_validate_resources` | walk `all_processes()`; `where=core_services.<svc>.processes.<proc>` |
| 12 | `_validate_domain_default_service` → **rename** `_validate_domain_default_process` | `ProcessRef.parse` the value (catch `ValueError` → issue), then check the service exists, the process exists on it, and `"web" in process.networks` |
| 14 | `_validate_service_name_blacklist` | additionally reject a **process** name in `_RESERVED_SERVICE_NAMES`; extend the message with the doctrine's reason (a process named `prod` renders `api-prod.dev.…`, which reads as a production host in a dev env) |
| 15 | `_validate_web_service_ports` | web-network **process types** need a port; backing services unchanged |
| 16 | `_validate_env_secrets_config_overlap` | compare the **effective** env (service ∪ process) per process against the service's `secrets`/`config` |
| 28 | `_validate_health_check_path_port` | read `process.model_extra` and `process.port`. This is the fix Mod 095's corporal flagged: today it reads `svc.model_extra`, which goes permanently empty once `ProcessType` exists |

## 2.7 Rules 26 and 27 — new

```python
def _validate_process_role_rules(doc):
    """Rules 26 + 27 — fields and networks that a role forbids.

    Rule 26: `replicas` on a scheduler is a compile error. Ofelia fires one
    job; a replica count is meaningless. Consistent with how `schedule:` is
    rejected on every non-scheduler role — inert fields fail rather than being
    silently ignored.

    Rule 27: a `worker` or `scheduler` process type may not declare `web` in
    `networks`. A process type wanting public ingress *is* a web process type
    and should say so with `role: web`. Replaces the prose-only, unenforced
    note this file carried for scheduler.
    """
```

Rule 26 needs to distinguish "declared 1" from "defaulted 1". Use
`"replicas" in (process.model_fields_set)`.

## 2.8 `_validate_scheduler_services`

Walk scheduler **process types**. The command-required half is now redundant
(the model requires `command` on every process type) — drop it and keep the
`schedule` presence + cron-wellformedness check. `where=` gains the process
segment.

## 2.9 `_validate_reserved_env_keys`

Evaluate against each process type's **effective** env, plus the service-level
`env`/`secrets`/`config`. Report the service-level source as
`core_services.<svc>.<source>` and a process-level one as
`core_services.<svc>.processes.<proc>.env`. Deduplicate: a key in the
service-level `env:` must be reported once, not once per process.

## 2.10 `_engine_for_service` and `_validate_emits`

`_engine_for_service` takes `role: str` rather than a service object, or gains
a process-aware overload — it is called for both kinds. `_validate_emits`'s
core arm walks process types (its `"web" not in svc.networks` conditional
target check at `:616` and its `svc.model_extra` read at `:622` are both
per-process now).

## Stage 2 self-check

```bash
cd docex && python3 - <<'PY'
from pathlib import Path
import yaml
from docex.cicl.model import CICLDocument
from docex.cicl.transfer import load_transfer_tables
from docex.cicl.validate import validate_document
t = load_transfer_tables(Path("tables"), None)
for p in sorted(Path("tests/fixtures").glob("*/infra/infra.yml")):
    issues = validate_document(CICLDocument.model_validate(yaml.safe_load(p.read_text())), t)
    print(p, "->", [i.rule for i in issues] or "clean")
PY
```

(Adjust the `load_transfer_tables` call to the real signature.) All four must
be **clean**.

---

# Stage 3 — Compile, naming, resources

**Files:** `docex/src/docex/cicl/compile.py`, `docex/src/docex/cicl/fargate.py`,
`docex/src/docex/emit/tags.py`, `docex/tables/naming_policies.yml`.

## 3.1 `CompiledService` — new fields

```python
    # --- Process expansion (Mod 096) -------------------------------------
    # The codebase this compiled service belongs to. None for backing
    # services. `name` is the two-segment compiled identity (`api-web`);
    # `core_service` is what stays keyed on the codebase — the image ref, the
    # ECR repo, `schema_owned_by`, and the `core/<svc>/` source folder.
    core_service: str | None = None
    process: str | None = None
    # `{project}-{env}-{core_service}` under the same naming policy as
    # `global_name`. The migrate task definition's family derives from this,
    # NOT from `global_name`, so one codebase yields one migrate family.
    # orchestrate/migrate.py reconstructs the identical string.
    codebase_global_name: str | None = None
    # The codebase-scoped env surface: the service-level `env:` block
    # resolved, plus secrets / config / doctrine-injected keys, EXCLUDING any
    # process-level `env:` overlay. Consumed by the migrate task definition
    # (and by Mod 099's exec service). See overview.md § Migration carrier.
    service_env: dict[str, Any] = field(default_factory=dict)
    # Declared parallelism. Carried only — NOTHING is emitted from it in this
    # mod. Fixed unroll and elastic desired_count are Mod 100.
    replicas: int = 1
```

## 3.2 `_global_service_name`

```python
def _global_service_name(
    project: str, env: str, service: str, policy: NamingPolicy,
    *, process: str | None = None,
) -> str:
    raw = (
        f"{project}_{env}_{service}_{process}" if process is not None
        else f"{project}_{env}_{service}"
    )
    return apply_policy(raw, policy)
```

## 3.3 `engines_by_service` and `contexts` re-key

Both dicts key on the **compiled identity** — backing services by `name`, core
process types by `ProcessRef(svc, proc).compiled` — because `role`, and
therefore the engine, is now per-process.

Context entries for a core process type:

- `name` → the compiled identity (`api-web`)
- `role_name` → the **process's** role
- `port` / `networks` → the **process's** values
- `global_service_name` → four-segment
- everything else unchanged

The magic-ref resolver's `contexts` / `engines` lookups therefore key on the
compiled identity. Combined with stage 2.3, a three-segment core ref now fails
with a clear message at validation; if one reaches the resolver, raise the
same-shaped `SubstitutionError` from `_resolve_part` rather than the generic
"no engine resolved".

## 3.4 The per-service loop

Restructure `:570-785` to iterate a merged work list:

```python
work: list[tuple[str, Any, str | None, str | None]] = []  # (key, model, svc, proc)
for name in sorted(doc.backing_services):
    work.append((name, doc.backing_services[name], None, None))
for svc_name, proc_name, svc, proc in doc.all_processes():
    work.append((ProcessRef(svc_name, proc_name).compiled, proc, svc_name, proc_name))
```

Inside the loop, `svc` (the old variable) becomes the `ProcessType` for core
entries; the owning `CoreService` is fetched via `doc.core_services[svc_name]`
where service-level fields (`env`, `secrets`, `config`) are needed.

Specific changes inside the body:

- **Role-field routing** (`:598-618`) reads the `ProcessType`'s `model_extra`.
- **`_image_ref`** (`:635-638`, `:656-659`) is passed **`svc_name`** (the
  codebase), never the compiled identity. This is the single most important
  line in the mod: get it wrong and containerize pushes one tag while the
  deploy pulls another.
- **`_resources_to_fixed` / `_resources_to_elastic`** read the process's
  `resources`.
- **`command`** is now always present; `body["command"] = proc.command`
  unconditionally for core.
- **Host ports** (`:647-648`) — per ruling 5, **delete the core-service
  publish**. Replace the block and its comment with:

```python
                # Core process types never publish a host port. A `web`
                # process is reached through the reverse proxy over the docker
                # network; a non-web process's port (e.g. a worker's health
                # port) is probed from inside the netns by the container
                # healthcheck and reached by a sibling over the internal
                # network. Neither path needs a host publish, elastic never
                # published one, and publishing would collide across the
                # workers of two codebases sharing a port in `dev`. Backing
                # services keep their publish (handled by their own
                # transfer-table bodies). Mod 096.
```

- **`env_block`** is built from the **effective** env: service-level `env:`
  first, then the process-level `env:` merged over it, key by key, each value
  passed through the resolver. Then `secrets`, `config`, `PROJECT_VERSION`,
  and the OTEL quartet as today. `OTEL_SERVICE_NAME` becomes the compiled
  identity — a side effect of `name` changing, which is intended (Mod 102 adds
  the resource attributes on top).
- **`service_env`** is built the same way but from the **service-level `env:`
  only**, plus `secrets`, `config`, `PROJECT_VERSION`, and the OTEL quartet.
  Factor the shared tail into a helper so the two cannot drift.
- **`schedule`** (`:780-784`) reads the `ProcessType`'s `model_extra`.
- **`schema_owned_by_db`** is `True` only for the **carrier**:

```python
        is_carrier = (
            svc_name is not None
            and svc_name in core_owning_schema
            and proc_name == primary_process(doc.core_services[svc_name])
        )
```

  `core_owning_schema` (`:562-568`) is unchanged — it already collects codebase
  names. `schema_owned_by` (`:771`) stays `None` for core.
- **`codebase_global_name`** — computed with the same policy as `global_name`:
  `_global_service_name(project_name, env, svc_name, policy)`.
- **`networks_seen`** updates from the process's networks.

## 3.5 `_apply_elastic_invariants` and `standard_tags`

`standard_tags` gains `process: str | None = None`. When `tier ==
"environment"` and `process` is not None, add `tags["process"] = process` and
make `Name` `f"{project}_{env}_{service}_{process}"`. Backing services (no
process) are byte-identical to today. Per `cicl.md § Elastic Foundation`:
*"`process` — present on env-tier resources that belong to a specific core
service process type; omitted for backing services, which have none."*

`_apply_elastic_invariants` passes `ctx["process"]` through (add `process` to
the context dict, `None` for backing).

## 3.6 `_web_hosts` / `web_hostnames_for_env` — and the `http_host` guard

`tables/naming_policies.yml`:

```yaml
  # DNS labels (hostnames): hyphens only, lowercase. DNS labels hard-cap at
  # 63 octets; without the ceiling an overlong two-segment service label
  # would fail confusingly at cert-issuance time rather than at compile.
  http_host:
    separator: hyphen
    case: lower
    max_len: 63
    overflow: error
```

`_web_hosts` gains a `policy: NamingPolicy` parameter and builds the label as
`apply_policy(name, policy)` instead of `_dns_label(name)`, where `name` is the
compiled identity. `default_service` becomes `default_process_compiled: str |
None` — the caller passes
`ProcessRef.parse(doc.domain_default_process).compiled` — and the comparison is
against the compiled identity.

`web_hostnames_for_env(doc, project_name, env, naming_policies)` walks core
process types plus backing services. `preinfra.py:175` passes
`ctx.transfer_tables.naming_policies`.

**The guard.** `apply_policy(n, http_host)` and `_dns_label(n)` are provably
identical for any `n` of 63 characters or fewer:

```
_dns_label(n)              = n.replace("_", "-").lower()
apply_policy(n, http_host) = n.replace("_", "-").lower()  + length check
```

Write a test asserting exactly that over a spread of inputs (plain, underscored,
mixed-case, hyphenated, 63 chars, 64 chars → raises). **If you observe any
existing fixture hostname change for a reason other than gaining its process
segment, STOP and report — do not work around it.** A silent hostname change
invalidates TLS certs and DNS records for deployed projects.

## 3.7 `_resources_to_elastic` and `fargate.py` error paths

Replace the `service_name` parameter with a `where` path string built by the
caller: `core_services.<svc>.processes.<proc>.resources` (core) or
`backing_services.<svc>.resources` (backing). Thread it into `fargate.py`'s
three `where=` sites (`:105`, `:134`, `:159`) and `compile.py:255,264`. The
Fargate rounding *notice* text should still name something human-readable —
use the compiled identity there.

## Stage 3 self-check

```bash
cd docex && python3 - <<'PY'
import shutil, tempfile
from pathlib import Path
from docex.context import load_project_context   # confirm the real import
from docex.cicl.compile import run_compile
for f in ("sample_project", "sample_project_elastic",
          "sample_project_scheduler_fixed", "sample_project_scheduler_elastic"):
    d = Path(tempfile.mkdtemp()) / "p"
    shutil.copytree(f"tests/fixtures/{f}", d)
    shutil.rmtree(d / "infra" / "output", ignore_errors=True)
    print(f, run_compile(load_project_context(d)))
PY
```

All four must compile to 0. Then **manually read** `infra/output/dev/docker-compose.yml`
and `infra/output/stage/main.tf` for `sample_project_elastic` and confirm:

- the compose service key is `sample-dev-api-web`
- the image ref is `sample/api:0.1.0` — **not** `sample/api-web:0.1.0`
- the sidecar is `sample-dev-api-web-otelcol`
- exactly **one** `aws_ecs_task_definition "api_migrate"` with family
  `sample-stage-api-migrate`
- the web host is `api-web.dev.sample.example.com`
- no `ports:` publish on any core service

**End of Pass A.** Run `python3 -m pytest tests/unit -q`. Report the exact
failure count and confirm every failing module is one stage 4 or 5 touches.

---

# Stage 4 — Emit and downstream

**Files:** `emit/{compose,hcl,ansible}.py`, `orchestrate/{_common,build,test,migrate,up}.py`,
`pipeline/{check,preinfra}.py`.

## 4.1 `emit/compose.py`

| Line | Change |
| ---- | ------ |
| `:444-446` | `simple_to_global` is now `{compiled_key: global_name}`. Since rule 24 forbids core targets, every `depends_on` entry is a backing-service name and still resolves. No structural change, but update the comment to say why. |
| `:466-476` | bind mounts → `./core/{svc.core_service}/src`, `./core/{svc.core_service}/dist` |
| `:486` | build context → `./core/{svc.core_service}` |
| `:559-561`, `:215` | sidecar name — **no change**, `svc.name` is correct (one sidecar per process type) |
| `:663-666` | ofelia container name + config key — **no change**, two-segment for free |
| `:149-159` | traefik labels — **no change** |

## 4.2 `emit/hcl.py`

**The migrate block (`:509-550`)** — three changes:

```python
        mig_family = f"{svc.codebase_global_name}-migrate"
        ...
        # env comes from service_env, NOT from the app container's env.
        mig_env_entries, mig_secret_entries = _container_env_entries(
            svc.service_env, ctx.project, ctx.env
        )
        ...
        out.append(
            f'resource "aws_ecs_task_definition" "{svc.core_service}_migrate" {{'
        )
```

Add a WHY comment: the family and address are keyed on the **codebase** so one
codebase yields one migrate family, and `orchestrate/migrate.py` and
`pipeline/release.py` reconstruct exactly these strings. The env is
codebase-scoped per the design record's *"`migrate.sh` may depend only on
codebase-scoped env"* rule.

Leave `mig_container["name"]`, the log-configuration prefix, `cpu`/`memory`
(the carrier's), and the tags on `svc.name`.

Everything else in `hcl.py` is correct for free — see `overview.md` § The
"correct for free" claim. Do **not** re-key the log group, the SSM data-source
name, the scheduler IAM role, or the ECR project pass to `core_service`; each
would produce duplicate HCL addresses.

**The six direct `standard_tags` call sites** — `:470`, `:505`, `:548`,
`:663`, `:804`, `:876` all pass `service=svc.name`. Per `cicl.md § Elastic
Foundation` the envinfra `service` tag is `${core_service_name}` and the
`process` tag is `${process_name}`, so each becomes:

```python
        service=svc.core_service or svc.name,
        role=svc.role,
        process=svc.process,
```

**This is required for consistency, not cosmetics.** Pass A already made
`_apply_elastic_invariants` build the *body* tags that way (correctly — it is
what the doctrine says). Left as-is, the same resource would carry
`service = "api"` from the body path and `service = "api-web"` from the direct
path. `svc.process` is `None` for backing services, and `standard_tags` omits
the key in that case, so their tag block stays byte-identical.

**`emit_hcl_project`** — no change. Its `core_service_names` already comes from
`list(ctx.infra.core_services.keys())` at `compile.py:1013`, which is
codebase-keyed and must stay that way. One ECR repo per codebase.

## 4.3 `emit/ansible.py`

`:23-30` currently compares `b.schema_owned_by == s.name` — an authoring key
against a compiled name. Under the rename it silently never matches, the
playbook emits zero migrate tasks, and reports success. Replace with the
carrier flag the compiler already set:

```python
    core_with_schema = sorted(
        (s for s in compiled.services.values()
         if s.is_core and s.schema_owned_by_db),
        key=lambda s: s.name,
    )
```

One entry per codebase, by construction. `playbook.yml.j2` needs no change —
`svc.global_name` is the carrier's compose service and `svc.name` is a valid
Ansible `register:` identifier.

Add a test that the fixed stage playbook contains exactly one
`Run migrations for` task. There is no such assertion today, which is why the
silent failure was possible.

## 4.4 `orchestrate/_common.py`

- **`core_services()`** — unchanged (codebase keys). Update the docstring to
  say "codebase keys" rather than "simple names of every core service".
- **`services_with_schema()`** — unchanged.
- **`scheduler_services()`** (`:116`) — `getattr(svc, "role", None)` silently
  returns `[]` for every project once `role` moves. Split:

```python
def scheduler_services(ctx) -> list[str]:
    """Codebase keys with AT LEAST ONE scheduler process type."""

def scheduler_only_services(ctx) -> list[str]:
    """Codebase keys with NO long-running process type.

    Distinct from scheduler_services because the two call sites want
    different predicates: `_ensure_scheduler_image` must run for any codebase
    carrying a scheduler job, while the dev-build skip and the test-path
    branch apply only when there is no long-running container at all.
    """
```

- **`compose_service_key()`** (`:142-166`) — resolve through
  `primary_process()` and match the full two-segment suffix:

```python
    # !!! TEMPORARY — DELETED BY MOD 099, which replaces this with
    # `exec_service_key` against an emitted per-codebase exec service. Do not
    # build on it. Today's suffix scan already mis-resolves (a codebase named
    # `web` matches `sample-dev-api-web` — wrong container, no error); this
    # keeps it working under two-segment keys, nothing more.
    core = ctx.infra.core_services.get(simple_name)
    suffix = (
        f"{simple_name}-{primary_process(core)}" if core is not None
        else simple_name
    )
```

  then match `key.endswith(f"-{suffix}")`, falling back as today. **Exclude
  sidecar and ofelia keys** from the scan (`-otelcol`, `-scheduler` suffixes)
  so they cannot be matched.

## 4.5 `orchestrate/build.py`

`:109` and `:120-127` carry two more copies of the suffix heuristic. Replace
both with a `compose_service_key` call so there is one implementation. `:73`
(`core_services(ctx)`) and `:142` (`core/<svc>/dist`) are codebase-keyed and
correct — do not touch.

## 4.6 `orchestrate/test.py`, `migrate.py`, `up.py`

- `test.py:121,144` — `compose_service_key` now resolves; `:139-144` uses
  `scheduler_only_services`.
- `migrate.py:102` — resolves via `compose_service_key`.
- `migrate.py:336-350` `_migration_task_family` — `core.role` is a hard
  `AttributeError`. Resolve the role from the **primary process**:

```python
    proc = core.processes[primary_process(core)]
    engines = tables.role(proc.role)
```

  Leave `raw = f"{project}_{env}_{svc}"` **exactly as it is** — that is the
  codebase-keyed form the compiler now emits. Update the docstring to name
  `codebase_global_name` as the thing it must match.
- `up.py:201` → `scheduler_only_services`; `:206` → `scheduler_services`;
  `:158`, `:238` → `compose_service_key`. `:98-109`'s `_ensure_scheduler_image`
  keeps passing the **codebase** name to `_image_ref` — that is what preserves
  the "byte-identical to the Ofelia INI's `image =`" invariant its docstring
  claims.

## 4.7 `pipeline/check.py` — mechanical only

Five hard `AttributeError`s and one silent pass. **Semantics do not change** —
Mod 101 owns the contract/health gate rework. Re-scope only:

| Line | Change |
| ---- | ------ |
| `:120` | `consumer.depends_on` → the consumer's process types' `depends_on` (union) |
| `:321` | `dependants` map built over process types |
| `:328` | "is a provider" test → **any** process type on `web` |
| `:374-377` | filename parse — leave `split(".", 1)[0]` for now; it yields `api` from `api.web.openapi.yml`, which is still a valid `core_services` key, so it does not crash. Mod 101 makes it right-anchored. Add a `# Mod 101` marker. |
| `:386` | web test → any process type on `web` |
| `:403` | `svc_decl.depends_on` → union over process types |
| `:410` | `dep_decl.networks` → any process type on `web` |
| `:478` | **`getattr(svc, "health_check_path", …)` silently sees nothing once the field is process-scoped**, so the curl gate passes while checking nothing and Mod 051's protection is defeated. Iterate process types and read each one's `model_extra`. Keep the gate keyed off `health_check_path`, **not** off `role` — the field-driven form is strictly better and becomes correct automatically. |

`:326,333-338` (contract path per codebase), `:492`, `:531-547` are
codebase-keyed and correct.

## 4.8 `pipeline/preinfra.py`

`:175` — pass `ctx.transfer_tables.naming_policies` to `web_hostnames_for_env`.
Nothing else.

## 4.9 Not touched in stage 4

`describe/{dag,llm}.py` (Mod 104 — node ids become two-segment for free and the
dangling core→core edges resolve themselves once rule 24 lands),
`containerize.py`, `rollback.py`, `projinfra.py`, `categories.py`,
`orchestrate/{down,aggregate}.py`, `emit/secrets.py`, `cicl/generate.py`.
Verified correct as-is.

---

# Stage 5 — Tests

## 5.1 Mechanical churn

41 of 64 modules carry a bare-`api` identifier. Work through them in this
order, heaviest first: `test_compose_emitter.py` (49 hits),
`test_hcl_emitter.py` (25), `test_magic_refs.py` (19),
`test_orchestrate_build.py` (18), `test_hcl_sidecar.py` (18),
`integration/test_compile.py` (18), `test_pipeline_check.py` (16),
`test_validate.py` (15), `test_orchestrate_up.py` (14, and the most
`sample-dev-api`-literal file), `test_telemetry.py` (12).

Three mechanisms need different handling:

- **On-disk fixtures** (`sample_ctx` at `conftest.py:239-255`, `elastic_ctx` at
  `:258-273`, and `test_scheduler.py:22-45`) — already rewritten in stage 1.
- **Inline `infra.yml` builders — 12 modules.** Each needs a `processes:`
  block. `test_validate.py:20-44` (`_BASE_FIXED`), `test_telemetry.py:30-90`
  and `:163-213`, `test_categories.py:36+`, `test_magic_refs.py:56-81` (the only
  kwargs-form builder — construct `CoreService(processes={"web":
  ProcessType(...)})`), `test_web_hostnames.py:22-51`,
  `test_secretsmgmt.py:31-57`, `test_worker_role.py:268-343`,
  `test_scheduler.py:295-357`, `test_pipeline_check.py:248-280`,
  `test_pipeline_bootstrap.py:286-300`, `integration/test_compile.py:442-460`
  / `:531-560` / `:692-699`, `integration/test_check_hcgate_real.py:30-47`.
- **Fixture-mutating tests — 9 modules** that read the on-disk infra.yml and
  patch it (`test_hcl_emitter.py:89-108,607-611`,
  `test_compose_emitter.py:155-158,254-267`, `test_config_block.py:30-35`,
  `test_release_secret_guard.py:39-45`, `test_worker_role.py:60-64`,
  `integration/test_compile.py:367-373,400-405,430-436,1069-1081`,
  `integration/test_containerize_real.py:42-44`). Their patch paths move under
  `processes.<proc>`.
- **Stub `CompiledService` builders** — `test_naming_policy_leak.py:77-83`,
  `test_emit_dispatch.py:5-9`, `test_check_observability_gate.py:28-43`: add
  `core_service` / `process` where the code under test now reads them.

`test_worker_role.py` was written in Mod 095 anticipating this rewrite
(comment at `:13-15`); its `_inject_worker` helper should now inject a worker
**process type** into `api` rather than a flat sibling service.

## 5.2 New coverage — required

Put schema/validation cases in `tests/unit/test_process_nesting.py` (new) and
emit cases alongside their existing emitter modules.

| # | Assertion |
| - | --------- |
| 1 | `processes:` absent → rejected |
| 2 | `processes: {}` → rejected |
| 3 | service-level `resources:` → rejected, **and the message names `processes:`** (not bare "Extra inputs are not permitted") |
| 4 | service-level `role:` / `command:` → same targeted message |
| 5 | a process type with no `command` → rejected |
| 6 | `command: []` and `command: ""` → rejected |
| 7 | `cicl_version: "1"` → rejected, message contains `upgrade_1.6.0.md` |
| 8 | `cicl_version: "3"` → rejected, distinct message |
| 9 | rule 5, form A: service `api` + process `web-v2` vs service `api-web` + process `v2` → collision |
| 10 | rule 5, form B: core `api` + process `db` vs backing service `api-db` → collision |
| 11 | rule 5, form C: `my_api`+`web` vs `my`+`api_web` → collision (underscore normalization) |
| 12 | core→core `depends_on` → rejected, message names `consumes:` |
| 13 | backing→core `depends_on` → rejected |
| 14 | a `depends_on` cycle among backing services is still fatal |
| 15 | rule 26: `replicas: 2` on a scheduler → rejected; `replicas` unset on a scheduler → clean |
| 16 | rule 27: `web` in a worker's `networks` → rejected; same for scheduler; `web` on a `web` process → clean |
| 17 | rule 28 reads the process type: `health_check_path` without `port` on a **process** → rejected |
| 18 | rule 14: a process named `prod` → rejected |
| 19 | rule 12: `domain_default_process: api` (bare) → rejected; `api.nope` → rejected; `api.worker` (non-web) → rejected; `api.web` → clean |
| 20 | rule 16: a **process-level** `env:` key colliding with the service's `secrets:` → rejected |
| 21 | reserved env keys: a process-level `env:` cannot shadow `OTEL_SERVICE_NAME` |
| 22 | a bare three-segment core magic ref → rejected, message shows the four-segment form |
| 23 | `ProcessRef.parse` round-trips; rejects `"api"`, `"api.web.x"`, `""`, `"api."` |
| 24 | **`apply_policy(n, http_host) == _dns_label(n)`** for a spread of inputs ≤63 chars; 64 chars raises |
| 25 | `iam` overflow: a project+env+service+process long enough to exceed 64 on `{global_name}_scheduler` fails compile with the policy's message |

**The headline integration assertion** — one core service, three process types
(`web` / `worker` / `nightly_cleanup`), compiled on both foundations:

| # | Assertion |
| - | --------- |
| 26 | fixed: **three** compose services, keys `…-api-web`, `…-api-worker`, `…-api-nightly_cleanup` (the last suppressed — a scheduler emits no long-running service, so two service blocks plus one ofelia container) |
| 27 | fixed: **two** sidecars (`api-web`, `api-worker`), none for the scheduler |
| 28 | fixed: **all** core blocks carry `image: sample/api:0.1.0` — one image |
| 29 | fixed: exactly **one** `build.context: ./core/api`, and the bind mounts say `./core/api/src` |
| 30 | fixed: **no** `ports:` key on any core service block (ruling 5) |
| 31 | elastic: **three** `aws_ecs_task_definition` resources, **two** `aws_ecs_service` (no ECS service for the scheduler), **one** `aws_lb_target_group` (web only) |
| 32 | elastic: all three task defs reference the **same** image ref |
| 33 | elastic: exactly **one** `aws_ecs_task_definition "api_migrate"`, family `…-api-migrate` (no process segment) |
| 34 | elastic: the migrate container's `environment` matches `service_env` — it contains the service-level keys and **not** a process-level-only key. Add a process-level `env:` key to the fixture for this test specifically. |
| 35 | elastic: `emit_hcl_project` emits **one** `aws_ecr_repository` and one `ecr_repository_api_url` output |
| 36 | elastic: envinfra tags carry `process = "web"` and `Name = "<proj>_<env>_api_web"`; a backing service's tags carry **no** `process` key |
| 37 | `OTEL_SERVICE_NAME` differs per process type (`api-web` vs `api-worker`) |
| 38 | web hostnames: `api-web.dev.sample.example.com`; the worker gets none |
| 39 | `migrate.py::_migration_task_family` returns exactly `CompiledService.codebase_global_name + "-migrate"` for the same project/env/service — assert against a real compile rather than a hand-written string |
| 40 | `emit_ansible` produces exactly one `Run migrations for` task for a three-process codebase |

## 5.3 Green

```bash
cd docex && python3 -m pytest tests/unit -q
```

**748 or more.** If you cannot reach it, **stop and report** with the failing
list — do not delete or skip tests to get there.

Also run `python3 -m pytest tests/ -q -m integration --collect-only` to confirm
the integration suite still *collects* (it is not run here; docker is out of
scope for this mod).

---

# Reporting

Both passes report:

1. Files changed.
2. Suite result — pass A: exact failure count plus confirmation that every
   failure maps to stage 4/5 work. Pass B: the final passed count.
3. Anything you had to decide that this document did not specify.
4. Any test whose **intent** you believe is now wrong (as opposed to its
   literal strings) — leave it failing and say so, per the rule at the top.
5. Whether the `http_host` byte-identity guard held.

**Do not commit.** The mod cycle owns both commits.
