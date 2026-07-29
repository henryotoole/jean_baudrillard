# Compiler

How docex's `compile` pipeline walks `infra.yml` and the transfer tables to produce the emitted artifacts under `infra/output/`. The doctrine specifies the *what* — [`cicl.md`](../../../doctrine/infrastructure/cicl.md) for the input language, [`transfer_tables.md`](../../../doctrine/infrastructure/specifics/transfer_tables.md) for the per-role-per-engine translation rules, [`networks.md`](../../../doctrine/infrastructure/specifics/networks.md) for the network plane. This doc covers the *how*: data flow, key types, and the layered emit stage.

## Scope

`docex compile` takes:

- `project.yml` — project name, project version, `docex_version` pin.
- `infra/infra.yml` — CICL source (foundation, services, env refs, etc.).
- Transfer tables — bundled at `/opt/docex/tables/` inside the image; optionally extended by `infra/transfer_tables/` in the project.

and writes, under `infra/output/`:

- `dev/docker-compose.yml`, `test/docker-compose.yml` — always emitted (dev and test are always fixed-foundation per [`shape.md`](../../../doctrine/infrastructure/shape.md#shape-and-environment)).
- `stage/docker-compose.yml`, `prod/docker-compose.yml` plus `playbook.yml`, `inventory.yml`, `ansible.cfg` — fixed-foundation projects.
- `project/main.tf`, `stage/main.tf`, `prod/main.tf` — elastic-foundation projects.

`compile` writes nothing outside `infra/output/`. The secret key set is not
emitted as a file — it is derived on demand by `secret_manifest` and reconciled
into `infra/secrets/<env>.env` by `docex secrets scaffold` (mod 092 removed the
old `infra/secrets/example.env` manifest).

The compiler is **offline-pure**: no AWS calls, no docker calls. Same inputs deterministically produce the same outputs.

## Pipeline shape

```
infra.yml + project.yml  ──┐
                            │
transfer tables  ───────────┤    cicl/transfer.py      → TransferTables
(bundled + project-local)   │    cicl/compile.py       → CompiledEnv per env
                            ▼    cicl/substitute.py    \
                    ┌──────────────────┐                ├ rendering helpers
                    │ load + compile   │ cicl/magic_refs.py /
                    │       ↓          │
                    │   CompiledEnv    │ ← what the emit layer consumes
                    │       ↓          │
                    │ emit/...         │ compose.py, hcl.py, ansible.py, secrets.py
                    └──────────────────┘
                            ↓
                    infra/output/<env>/...
```

Each env is compiled independently (a project compiles all four). Cross-env state is none — env A's compile never reads env B's outputs.

## Key types

In `src/docex/cicl/`:

- **`TransferTables`** — the loaded, merged tables. `by_role[role][engine] → EngineEntry`, plus `naming_policies: NamingPolicies`. Built by `load_transfer_tables` (does the doctrine-bundled + project-local deep-merge).
- **`EngineEntry`** — one engine of one role. Carries `foundation` (`fixed`/`elastic`/`both`), `defaults`, `fields`, `provides`, `env` (now `dict[str, EnvVarSpec]` — mod 076), `naming` (string ref into `naming_policies`), `default_port`, `reserved_names`.
- **`EnvVarSpec`** — the per-var schema of an engine `env:` block (mod 076, `cicl/transfer.py`). Carries `name`, `kind` (`fixed`/`minted`/`secret`, default `secret`), `value` (fixed only), `policy` (minted only — a `generation_policies` ref), and `desc`. The `kind` drives how the var is treated at compile and emit (see Substitution grammar below).
- **`GenerationPolicy` / `generate`** (`cicl/generate.py`, a sibling to `naming.py`) — a minted var's value is drawn by the CSPRNG `generate` from a named policy (`{length, alphabet}`, alphabets `url_safe`/`alnum`); policies load from `tables/generation_policies.yml`. Minting itself runs during aggregation at bring-up/release, never in `compile` — see [`config_and_secrets.md`](../../../doctrine/infrastructure/specifics/config_and_secrets.md).
- **`SourceKeyCategories` / `classify_source_keys`** (`cicl/categories.py`, mod 078) — a pure partition of a service's source-key namespace into TTE / secret / config. `secret_manifest` / `config_manifest` derive the per-category key sets (mods 083/084) and `minted_policies` derives the minted key→policy map. These back the three-category model in [`config_and_secrets.md`](../../../doctrine/infrastructure/specifics/config_and_secrets.md); don't re-derive it here.
- **`NamingPolicy` / `NamingPolicies`** — see [`transfer_tables.md § Naming Policies`](../../../doctrine/infrastructure/specifics/transfer_tables.md#naming-policies). Lifted from inline engine `naming` structs in mod 005 so structural emitters can share the table.
- **`CompiledEnv` / `CompiledService`** — the per-env compile result. `CompiledService` carries `name`, `role`, `engine`, `is_core`, `global_name` (policy-applied), `body` (engine defaults merged with project overrides), `env` block, `networks`, `port`, etc. This is what the emit layer reads. Since mod 096 it also carries the process-expansion fields — see [Process expansion](#process-expansion).
- **`ProcessType` / `ProcessRef`** (`cicl/model.py`, mod 096) — `ProcessType` is one named way of invoking a core service's build artifact (`role`, `command`, `networks`, `resources`, `port`, `depends_on`, `consumes`, `replicas`, `env`), per [`cicl.md § Process Types`](../../../doctrine/infrastructure/cicl.md#process-types). `ProcessRef` is the value type carrying the dots-for-reference / hyphens-for-emission rule: `.dotted` → `api.web`, `.compiled` → `api-web`, `.parse()` rejecting a bare name. It is the single place that rule is expressed, so read sites never re-derive it.

In `src/docex/naming.py`:

- **`apply_policy(name, policy)`** — the single naming-translation entry point. Mod 005 collapsed two duplicated inline implementations (in `compile.py` and `orchestrate/migrate.py`) into this. Mod 069 added policy `overflow` handling: a name over `max_len` normally errors, but a policy with `overflow: hash_truncate` (the `alb` policy) instead keeps a readable prefix and appends a 6-hex-char SHA-256 suffix so AWS `name` identifiers fit their 32-char cap — the descriptive form stays in the resource's `Name` tag.

In `src/docex/cicl/substitute.py`:

- **`HCLLiteral`** — a `str` subclass marking a value as raw HCL. The emit layer skips quoting on `HCLLiteral` values, so `aws_db_instance.appdb.address` ends up in the artifact as an HCL expression rather than a quoted string.
- **`substitute_string` / `substitute_tree`** — the compile-time-substitution helpers.

In `src/docex/cicl/magic_refs.py`:

- **`MagicRefResolver`** — resolves a magic ref against the named service's engine `provides:` block. State (compile contexts, engines, foundation) is held on the resolver instance. Refs to core services carry the process dimension; refs to backing services do not, because a backing service has no process types to qualify:

  ```
  ${core_services.<service>.<process>.<part>}     # four segments — api.web.host
  ${backing_services.<service>.<part>}            # three segments — database.host
  ```

  A core ref resolves against the **compiled** identity (`api-web`), which is what `contexts` and `engines` are keyed on. A process type may not reference itself — `provides.host` is the internal discovery name, so the one plausible motive would not return what the author expects. See [`cicl.md § Magic Refs`](../../../doctrine/infrastructure/cicl.md#magic-refs).

- **Parse generically, then arity-check by kind** (mod 097). `_MAGIC_RE` matches *any* `${core_services.…}` / `${backing_services.…}`, whatever its body; the body is split on `.` and its segment count checked against the kind by one shared generator, so the two wrong-arity messages cannot drift apart. This is deliberate rather than a widened pattern: whether a string **is** a magic ref must be decided independently of whether that ref is **well-formed**. When the two were coupled, a four-segment ref — or any ref carrying a `-` in a name — matched neither `_MAGIC_RE` nor `substitute._COMPILE_RE` and was written verbatim into the emitted compose/HCL as literal `${…}` text. That is silent corruption of infrastructure config, not a message-quality problem, and generic capture is what closes it structurally.

## Substitution grammar — three layers, three resolvers

The doctrine spec is in [`transfer_tables.md § Substitution Grammar`](../../../doctrine/infrastructure/specifics/transfer_tables.md#substitution-grammar). The implementation enforces the layering:

| Syntax | Stage | Resolver |
| ------ | ----- | -------- |
| `${var}` | compile time | `compile.py` + `cicl/substitute.py`. Compile errors if unresolved. Names admit letters, digits, `.`, `_`, `-`; there is **no** escape form for a literal `${…}` (mod 097). |
| `$[var]` | runtime (container start) | Emitted verbatim. Translates to compose `${VAR}` (fixed) or an ECS `secrets[]` entry (elastic). |
| `@<expr>` | tofu apply | Emitted as HCL (after stripping `@`). Compile errors if a `@<expr>` appears on the fixed branch. |

A compile-time `${var}` embedded inside a `@<expr>` is resolved during emit; the outer `@` survives so OpenTofu sees a real HCL expression.

**Engine-env `kind` short-circuits `$[VAR]` (mod 077).** When a `$[VAR]` names a `kind: fixed` engine env var, `magic_refs.py::_inline_fixed` substitutes the var's literal `value:` at compile time rather than emitting a runtime ref. `minted`/`secret` vars stay runtime pass-through. So `POSTGRES_USER` inlines to `appuser` everywhere and the fixed var's backing-body / `provides` `$[VAR]` never reaches emit — no emitter change was needed. The elastic SSM data-source / `secrets[]` therefore fire only for the non-fixed vars (e.g. `POSTGRES_PASSWORD`).

## Process expansion

Mod 096. One core service key in `infra.yml` maps to **N** `CompiledService`
objects, one per [process type](../../../doctrine/infrastructure/cicl.md#process-types) —
a codebase invoked several ways from one image.

```
CoreService(api) × {web, worker, nightly_cleanup}
    -> CompiledService(name="api-web",    core_service="api", process="web")
    -> CompiledService(name="api-worker", core_service="api", process="worker")
    -> CompiledService(name="api-nightly_cleanup", …)
```

The governing principle, and the reason the emit layer barely changed:

> **`CompiledService.name` carries the two-segment compiled identity (`api-web`);
> the authoring models keep the authoring names.**

Traefik router keys, ECS container/task-def/service names, the paired sidecar,
Service Connect names, the CloudWatch log group, target groups, ALB rule
priorities and the envinfra tag block all already derived from `svc.name` /
`svc.global_name`, so they became per-process for free.

**What stays keyed on the codebase.** Getting any of these wrong defeats the
point of the expansion, which is one build artifact per codebase:

| Identity | Field to read |
| -------- | ------------- |
| image ref + the `ecr_repository_<svc>_url` remote-state output | `core_service` |
| the project-tier ECR repo set (`emit_hcl_project`) | `list(infra.core_services)` |
| `schema_owned_by` / which codebase owns migrations | `core_service` |
| the `core/<svc>/` source folder — compose bind mounts and build context | `core_service` |
| the migrate task-def family and address | `codebase_global_name` / `core_service` |

`CompiledService` therefore carries `core_service`, `process`,
`codebase_global_name` (`{project}-{env}-{codebase}` under the same naming
policy as `global_name`), `service_env`, and `replicas`.

**`service_env`** is the codebase-scoped env surface: the service-level `env:`
block resolved, plus `secrets` / `config` / doctrine-injected keys, and
**excluding** any process-level `env:` overlay. The migrate task definition
consumes it rather than the app container's env, because `migrate.sh` may
depend only on codebase-scoped env — a process-level `DATABASE_*` would
otherwise make a migration silently dependent on which process type it happened
to inherit from.

**`replicas`** is the **declared** count. `effective_replicas(svc, env)`
(`cicl/compile.py`) applies the clamp — the count applies in `prod` only, per
[`shape.md`](../../../doctrine/infrastructure/shape.md)'s Runtime Shape
paragraphs — and both emitters call it, so the prod-only rule is stated once.
See [Replicas](#replicas).

### Replicas

Mod 100. The governing principle:

> **A replica is an emission detail, not a topology node.**

`CompiledEnv.services` is the topology model, read by `describe`, the `check.py`
gates, `group_by_codebase`, `_named_volumes` and the network section. It holds
**exactly one entry per process type** no matter what `replicas` says. Four
`api.worker` replicas are one process type, one contract, one health target,
one exec service, one image; unrolling into the compiled model would give
`describe` four worker nodes, the contract gate four providers, and four exec
services per codebase. The multiplication belongs to emission.

**Elastic sets a count.** `render_ecs_service` emits
`desired_count = effective_replicas(svc, ctx.env)` — one `aws_ecs_service` and
one task definition per process type, as before. No `deployment_configuration`
block is emitted, so ECS's defaults (`minimum_healthy_percent = 100`,
`maximum_percent = 200`) apply, which is correct for a static count. N tasks
give N collector sidecars automatically, because the collector is a container
*inside* the task definition.

**Fixed cannot set a count, so it unrolls.** `deploy.replicas` is unusable here
for two independent reasons: the collector sidecar pairs via
`network_mode: "service:<svc>"` to share the app container's netns and Compose
has no replica-to-replica pairing semantics, so one sidecar cannot serve N
replicas; and Compose refuses `deploy.replicas` alongside `container_name`,
which would cost the container-name DNS entry and the readable names operators
debug with. So `emit/compose.py` writes N distinct services keyed
`{global_name}-{i}`, each with its own `container_name` and its own 1:1 sidecar
`{global_name}-{i}-otelcol` on `network_mode: service:{global_name}-{i}`.

Three invariants carry the unroll, each pinned by a test in
`tests/unit/test_replicas.py`:

| Invariant | Mechanism |
| --------- | --------- |
| `provides.host` unchanged | A shared network alias `{global_name}` on **every** network of every replica (`_replica_networks`), resolved to all N by Docker DNS, round-robin. This is the emitter's only `aliases` handling and the only place it converts compose's short-form `networks:` list to map form. |
| Traefik aggregates | `_traefik_labels` keys on the **unqualified** `{global_name}`, so N containers declare one router and one service and traefik's docker provider loads them as N servers. Qualifying the labels per replica would produce N routers fighting over one `Host()` rule — a constraint, not an accident. |
| Sidecar stays 1:1 on loopback | One collector per *emitted container*, so `OTEL_EXPORTER_OTLP_ENDPOINT` is identical across replicas and across foundations. |

Blast radius is deliberately small: the clamp means `dev`, `test` and fixed
`stage` unroll to exactly one and emit output **byte-identical** to the
pre-mod-100 compiler, which is asserted directly (bytes, not parsed YAML)
rather than argued.

Two non-problems, checked and recorded so they stay non-problems.
`_named_volumes` walks *compiled* services rather than emitted ones, so a
volume introduced by a derived service would go undeclared — the unroll
introduces none, because each replica copies the compiled body, and core roles
declare no persistent storage anyway (only `tmpfs`, which is per-container and
therefore correctly per-replica). And host-port collisions cannot arise because
mod 096 stopped non-`web` core process types from publishing host ports and
`web` never published — which is *why* replicas are viable on fixed at all.

### Per-codebase artifacts

Three things are emitted once per **codebase** rather than once per process
type. All three iterate `group_by_codebase(compiled)` (`cicl/compile.py`), which
is the single expression of the grouping rule — there is deliberately no rule
for *picking a representative* process type, because every such rule is
unstable under renames of process types that have nothing to do with the
artifact.

**The exec service** (`emit/compose.py`) — one `{project}-{env}-{codebase}-exec`
block per codebase, in every fixed env. It is the container that *is* the
codebase: `migrate`, `test` and `build` run one-off inside it via
`docker compose run --rm`, rather than `compose exec`-ing into whichever process
type's container happened to be chosen. Two properties carry it:

- `profiles: [exec]` keeps `compose up` from ever starting it, while
  `compose run` implicitly enables the profile of the service it names. The
  block is inert until something runs in it. (It is the only `profiles:` key
  the compiler emits.)
- Its `environment:` is `service_env` — the service-level surface only, never a
  process type's overlay. That is what makes *`migrate.sh`, `test.sh` and
  `build.sh` may depend only on codebase-scoped env* an enforceable rule rather
  than a convention: a process-level key is not discouraged there, it is absent.

It carries the codebase's image ref (identical across the codebase's process
types, so one tag and one build), the `build:` block in `dev`/`test`, the dev
bind mounts in `dev`, the union of the codebase's non-`web` networks, and the
union of its `depends_on` — which the emitter's existing second pass rewrites to
`condition: service_healthy`, so a one-off gates on the database being ready
instead of assuming the stack is already up.

**The migration task definition** (`emit/hcl.py::render_migration_task_definitions`)
— one `aws_ecs_task_definition "<codebase>_migrate"` per schema-owning codebase,
plus the per-codebase `aws_cloudwatch_log_group` it writes to. Both halves are
codebase-keyed or neither can be: log groups are addressed by compiled identity,
so a codebase-keyed log reference with a per-process group would be a dangling
address. `schema_owned_by_db` is an honest codebase property (true of every
process type of a schema-owning codebase); the "exactly one" invariant comes
from the grouping, not from a flag on a chosen carrier.

Its **resources are the per-dimension maximum** across the codebase's process
types, over the already-Fargate-tiered values. Max because it is commutative —
the migration's size cannot move because an unrelated process type was renamed
or added — and because it never under-provisions, which removes the need for
any carve-out. A single-process codebase's max is that process's value, so the
common case is byte-identical to a per-process emission. Fargate's allowed
memory range is monotone non-decreasing in cpu, which makes `(max_cpu, max_mem)`
provably a valid tier; the `fargate_pair_from_units` round-trip afterwards is
what turns that proof into an enforced guarantee.

**The fixed stage/prod migrate step** (`emit/ansible.py` + `playbook.yml.j2`) —
one playbook task per schema-owning codebase, running
`compose run --rm <codebase>-exec /service/migrate.sh`. This is why the exec
service is emitted in all four fixed envs and not just `dev`/`test`: the
codebase-scoped-env rule has to hold in production, or it does not hold.

Outside the compiler, two identities are reconstructed from
`codebase_global_name` and must match it byte-for-byte —
`orchestrate/_common.py::exec_service_key` (`-exec`) and
`orchestrate/migrate.py::_migration_task_family` (`-migrate`). Both derive the
codebase's naming policy through `_codebase_naming_policy`, which resolves every
process type's policy and requires agreement rather than reading one.

## Naming flow

The compiler always joins parts with `_` internally; the policy decides what reaches the artifact. For the `web` process type of core service `api` in env `stage` of project `docex_smoke_elastic`:

1. Internal form: `docex_smoke_elastic_stage_api_web` — four segments for a core process type, three (`{project}_{env}_{service}`) for a backing service.
2. Engine `container` (role `web`) declares `naming: ecs`.
3. Policy lookup → `ecs = {separator: hyphen, case: any, max_len: 255}` (mod 030: data-plane resolvable, hyphen).
4. `apply_policy(...)` translates underscores → `docex-smoke-elastic-stage-api-web`.

Two policies feel the fourth segment. The `alb` policy (32 chars,
`hash_truncate`) starts truncating target-group names that previously fit — the
descriptive form survives in the `Name` tag. The `iam` policy (64 chars,
`overflow: error`) can now *hard-fail* a compile on
`{global_name}_scheduler`; that is the doctrine's stated preference for loud
failure over silent truncation, and it fails at the earliest layer.

The same internal form passed through the `iam` policy (a doctrine record-key identifier) would stay `docex_smoke_elastic_stage_web` (underscores preserved). This decouples docex's internal join convention from each AWS resource type's identifier convention — without this layer, a policy's choice of `_` vs `-` would leak across every emit site.

## Structural vs engine emit

Two distinct kinds of identifiers get formed:

- **Engine-owned** — the ECS service for `web`, the RDS instance for `appdb`, the ALB target group for any `web`-network service. An engine declares `naming: <policy>` in the transfer table; the compiler applies it via `_global_service_name`. The result lands on `svc.global_name`. Subsequent emit sites read `svc.global_name`.
- **Structural** — the OpenTofu state-backend S3 bucket, project ECR repos, project IAM exec role, SSM path prefix, ALB and ECS cluster names. These are emitted at the project tier (`emit_hcl_project`) or in foundation-specific code (`pipeline/bootstrap.py`) and aren't owned by any `infra.yml` service. The choice of policy lives in docex source — e.g. `bootstrap.py` calls `apply_policy(f"{project}_tofu_state", policies.get("s3"))`. The policy body still lives in `naming_policies.yml` so it remains reloadable, but the *choice* of which policy applies is doctrine knowledge embedded in docex.

  Two structural sites bypass the policy table entirely (per `doctrine/infrastructure/specifics/transfer_tables.md § How structural emitters reference a policy`): ECR repo names are emitted as the literal `f"{project}/{name}"` with each segment verbatim (single-separator policies cannot express the `/`-joined two-segment shape), and the dev/test local image tag built in `cicl/compile.py` follows the same pattern.

If the structural set grows substantially, the next refactor is a `structural_resources:` section in transfer tables that declares the structural emit set declaratively. The current closed set (state bucket, lock table, project ECR repos × N, IAM role + inline policy, SSM prefix, ALB, ECS cluster) was small enough that hardcoding the policy choice was the better trade in mod 005.

## Worked example — `${backing_services.appdb.host}` end-to-end

The elastic test project's `web` core service declares:

```yaml
env:
  DATABASE_HOST: ${backing_services.appdb.host}
```

How the compiler turns that into the final ECS task definition's `environment[]` entry in `infra/output/stage/main.tf`:

1. **Load**. `load_transfer_tables` reads the bundled + project-local YAML, parses `naming_policies:` and every `roles.<role>.<engine>` block, returns a `TransferTables`. Every engine's `naming` ref is cross-validated against the policy table at load time.
2. **Resolve engine per service**. `compile_env(env="stage", foundation="elastic")` walks `infra.yml`'s `core_services` and `backing_services`. For `appdb` (role `relational_db`, engine `postgres`), it loads the postgres `EngineEntry` and verifies `engine.supports("elastic")`.
3. **Form `global_name`**. `_global_service_name("docex_smoke_elastic", "stage", "appdb", rds_policy)` → `apply_policy("docex_smoke_elastic_stage_appdb", rds)` → `docex-smoke-elastic-stage-appdb` (hyphenated, lowercased, ≤ 63).
4. **Resolve the magic ref**. `MagicRefResolver` sees `${backing_services.appdb.host}` in `web`'s env block. It looks up the postgres engine's `provides.host.elastic` template: `@aws_db_instance.${name}.address`. It substitutes `${name}` (the consumed service's `name`, `appdb`) into the template. The `@` prefix marks the result as HCL pass-through. The output is an `HCLLiteral("aws_db_instance.appdb.address")`.
5. **Place on the consumer**. `web`'s `CompiledService.env["DATABASE_HOST"]` is set to that `HCLLiteral`. The literal type matters — the emit layer treats `HCLLiteral` values as un-quoted HCL.
6. **Emit**. `emit/hcl.py::render_task_definition` (called via `render_service`'s dispatch) walks `svc.env`. For the `HCLLiteral` entry it emits:

   ```hcl
   environment = [{
     name  = "DATABASE_HOST"
     value = "${aws_db_instance.appdb.address}"
   }, ...]
   ```

7. **Apply**. At `tofu apply`, OpenTofu resolves `aws_db_instance.appdb.address` to the live RDS hostname and substitutes it into the task definition.

Same input on fixed-foundation `dev`: postgres `provides.host.fixed` is `${global_service_name}`, which the compiler resolves to `docex-smoke-elastic-dev-appdb` (the container name on the internal docker network — `${global_service_name}` is policy-applied, and postgres declares `naming: rds` which is hyphen-lower-63). The emit layer drops it into compose as a plain string env var — no `HCLLiteral`, no pass-through.

## Output layout

```
infra/output/
├── project/                       project-tier output, split by side (mod 035)
│   ├── development/
│   │   └── docker-compose.yml     emit/compose.py::emit_project_compose — always emitted; declares the four ${project}-${env}-web networks + docex-ingress
│   └── production/
│       ├── docker-compose.yml     fixed-foundation only — same shape as development side
│       └── main.tf                elastic-foundation only — emit/hcl.py::emit_hcl_project; state backend ref, VPC, Route53 zone, ACM cert, ECR repos, IAM
├── dev/
│   └── docker-compose.yml         emit/compose.py (dev is always fixed)
├── test/
│   └── docker-compose.yml         emit/compose.py (test is always fixed)
├── stage/
│   ├── docker-compose.yml         fixed stage
│   ├── playbook.yml               emit/ansible.py — fixed stage
│   ├── inventory.yml              emit/ansible.py — fixed stage
│   ├── ansible.cfg                emit/ansible.py — fixed stage
│   └── main.tf                    emit/hcl.py::emit_hcl — elastic stage
└── prod/                          same shape as stage
```

The project-tier development and production sides are both applied by
``docex projinfra <direction> <side>``. Mod 035 emits the project-tier
compose files with networks only — the per-project traefik joins these
networks in mod 036. Ansible artifacts (``playbook.yml``,
``inventory.yml``, ``ansible.cfg``) at project tier are deferred to mod
036's "fixed + remote prod host" path.

The compiler no longer emits a secrets manifest file (mod 092 removed
`infra/secrets/example.env`). The required-secret key set lives in
`secret_manifest` (`cicl/categories.py`) — core `secrets:` + backing `kind: secret`
env vars + doctrine-injected secrets — and is materialized on demand by `docex
secrets scaffold`/`status`, never written by `compile`. `emit/secrets.py` retains
only `render_manifest_env`, the shared grouped-`KEY=value` renderer those scaffold
commands use (see [`config_and_secrets.md`](../../../doctrine/infrastructure/specifics/config_and_secrets.md)).

The Jinja templates live in `src/docex/emit/templates/` — `main.tf.j2` (env-tier HCL), `project.tf.j2` (project-tier HCL), `playbook.yml.j2`, `inventory.yml.j2`, `ansible.cfg.j2`. Pre-translated names (state bucket, ALB name, ECS cluster, etc.) are computed in Python and passed to the templates as context; the templates do not do naming translation themselves.

## Validation

Validation lives at two layers:

**Load-time** (`cicl/transfer.py::load_transfer_tables` + `naming.py::_validate_policy_keys`) — runs before any `infra.yml` is compiled. Strict schema enforcement on every transfer-table YAML file, bundled or project-local. Allowlist-based: unknown top-level keys, unknown engine sub-keys, unknown naming-policy sub-keys, and unknown emit destinations all hard-error at load with source attribution and "did you mean X?" hints for plausible typos. Per [`transfer_tables.md § Failure-mode contract`](../../../doctrine/infrastructure/specifics/transfer_tables.md#failure-mode-contract). Allowlists live as `_ALLOWED_*` constants in `transfer.py` and `naming.py` (mod 012).

**Compile-time** (`cicl/validate.py`) — runs against the loaded tables + `infra.yml`. Enforces the rules listed in [`cicl.md § Validation Rules`](../../../doctrine/infrastructure/cicl.md#validation-rules). Among them:

- Every magic ref resolves to a `provides:` part the referenced engine exposes.
- Every engine is permitted on the target foundation.
- Every `naming:` value references a defined policy (mod 005).
- Every backing-service name avoids the engine's `reserved_names` (mod 006 extended postgres's list).
- Every magic ref is matched by the edge **its kind calls for** (rule 7, kind-aware since mod 098): a ref to a **backing service** by a `depends_on` entry, a ref to a **core process type** by a `consumes` entry. Three properties follow from *where* the check sits rather than from extra conditionals, which is why each is pinned by its own test: it is **one-directional** (the walk is over refs, so an edge never obliges a ref — `api.web` consumes `api.worker` for the contract and health fan-out while holding no ref to it); **same-codebase is not exempt** (the comparison is between dotted targets and never between codebases); and a **service-level `env:` ref obliges every process type**, since the scan runs once per process type over its *effective* env. A **backing** service holding a core ref is the one referencer rule 7 does not reach — it has no `consumes:` and, per rule 24, may not `depends_on` a core service. That is the rule correctly not applying rather than a gap: embedding a core hostname in your own config (an `object_store` CORS origin) is not a call, so it implies no readiness coupling and crosses no interface boundary. The skip is deliberate and pinned.
- A minted var's `policy:` names a defined `generation_policies` entry (rule 13, load-time — mod 076).
- `kind: fixed` ⇒ a `value` and no `policy`; `kind: minted` ⇒ a `policy` and no `value` (rule 14, mod 076).
- Per process type, the *effective* `env` (service-level merged under process-level) does not overlap the service's `secrets` / `config` (rule 16, mods 079 + 096).
- Project-wide, source keys are cross-category disjoint — no key is a secret in one service and config in another (rule 20, via `classify_source_keys`); doctrine-injected keys are reserved in every category (mod 079).
- `cicl_version` is `"2"`; `"1"` is rejected with a message naming the upgrade guide, not shimmed (rule 21, mod 096).
- Rendered data-plane identities are unique after naming-policy normalization, across core process types, backing services, **and the derivatives the compiler appends to them** (rule 5; mod 096 added the first two, mod 099 the third, mod 100 the replica index). The check normalizes to hyphenate-and-lowercase and compares the un-prefixed suffix — the `{project}_{env}` prefix is common to every service, which is what lets the rule run without a project name or env. It catches collisions the exact-name check cannot: `api`+`web-v2` against `api-web`+`v2`, and a core process rendering `api-db` against a backing service literally named `api-db`. The derivatives are `-otelcol` (collector sidecar) and `-scheduler` (Ofelia trigger), per process type, and `-exec` (operations container) and `-migrate` (migration task definition), per codebase — so a process type named `exec` on codebase `api` renders `api-exec` and is rejected rather than silently sharing a compose key with `api`'s exec container. Three of the four holes predate mod 099. Mod 100 added a fifth derivative, the `-1`…`-N` replica index the fixed-`prod` unroll appends, seeded only where the process type declares `replicas > 1` — with a count of 1 the suffix is never emitted by anything, and the rule does not forbid a name that collides with nothing. Seeding the container identity alone is sufficient: a sidecar collision would need `{P}-otelcol == {Q}-{i}-otelcol`, i.e. `P == Q-i`, which is exactly the container-level collision already seeded. The rule is keyed on **collision, not on a reserved-name list**, which is what makes it cover every suffix the compiler learns in future with no further edit, and what keeps a name that collides with nothing from being forbidden for its own sake. `-migrate` is seeded even for a codebase that owns no schema today: schema ownership is declared on a *backing* service and can be added later without touching the codebase, so a name that would collide the moment it is should not be legal in the meantime.
- `depends_on` names backing services only; a core process type in a `depends_on` list is an error pointing at `consumes:` (rule 24, mod 096). Because core process types are therefore leaves, cycle detection (rule 6) runs over the backing-service graph alone. **Do not "complete" that walk over `consumes` edges.** `consumes` is a cyclic digraph by doctrine — `web ↔ worker` is the most common topology there is and is legal — so there is one DAG (`depends_on`, cycles fatal) and one cyclic digraph (`consumes`, cycles fine). The legality is asserted rather than merely unchecked (mod 098).
- `consumes` names only core process types, fully qualified as `<service>.<process>`; a bare name is an error, not shorthand, and a process type may not consume itself (rule 25, mod 098). `ProcessRef.parse` is the parser, so the bare-name rule lives in one place — but a bare entry naming a *backing* service is dispatched on the namespace first and answered with `depends_on:`, because that is the mistake the field invites. `consumes` is validated and read by CI only (contracts, health fan-out, rule 7): it is a declared pydantic field, so it never appears in `model_extra` and therefore cannot reach field translation or any emitted artifact. A test asserts the absence in compiled output, because "is not read" and "cannot be read" look identical until someone adds a read site.
- `replicas` is not declared on a `scheduler`, and `worker` / `scheduler` process types do not declare `web` in `networks` (rules 26 + 27, mod 096) — the latter replaces a prose-only, unenforced note.
- Per-process re-scoping of rules 10, 11, 12, 14, 15 and 28 (mod 096): resources, GPU-on-elastic, `domain_default_process`, the reserved-name blacklist (now covering process names), the web-network port requirement, and `health_check_path`-obliges-`port`.

A compile-time error is always preferable to a tofu/AWS-side error. A load-time error is preferable to a compile-time error. When in doubt, add validation at the earliest layer where the problem is detectable.

## Where to look when changing things

| To change... | Touch... |
| ------------ | -------- |
| What a role/engine emits per foundation | `tables/roles/<role>.yml` (data) |
| How a name is formatted | `tables/naming_policies.yml` (data) + the engine's `naming: <policy>` ref |
| How the compiler walks services | `src/docex/cicl/compile.py` — the work list in `compile_env` pairs each backing service with each `(service, process)` from `CICLDocument.all_processes()` |
| Whether a new identity is per-process or per-codebase | [Process expansion](#process-expansion). The default is per-process, because `CompiledService.name` already is; the codebase-keyed set is small and listed there |
| What a core service may declare, and at which level | `src/docex/cicl/model.py` (`CoreService` is `extra="forbid"` over `{processes, secrets, config, env}`; `ProcessType` is `extra="allow"` so role-specific fields land in `model_extra`) |
| How magic refs are resolved | `src/docex/cicl/magic_refs.py` + `cicl/substitute.py` |
| How doctrine env vars are injected on core services | `src/docex/cicl/compile.py` — the `env_block[...]` assignments after the resolved-magic-ref loop |
| What compose YAML looks like | `src/docex/emit/compose.py` |
| What env-tier HCL looks like | `src/docex/emit/hcl.py` + `templates/main.tf.j2` |
| How a specific AWS resource type is rendered | `src/docex/emit/hcl.py` — the matching `render_<destination>` function (one per entry in `EMIT_DESTINATIONS["elastic"]`). Dispatch is keyed off the engine's `emits.elastic` list via `_DESTINATION_RENDERERS`. Mod 013. |
| How a transfer-table field lands *inside* an ECS container definition instead of as its own resource | `src/docex/emit/hcl.py::render_task_definition` — the `container_def.update(svc.target_extras["container_definition"])` merge, placed ahead of the `dockerLabels` / `mountPoints` / `dependsOn` assignments so those compiler-owned keys win. `container_definition` is a **merge target**, not a resource: its `_DESTINATION_RENDERERS` entry is a deliberate no-op, registered only so the dispatch loop and transfer-table rule 12 are satisfied. Mod 095. |
| What project-tier HCL looks like | `src/docex/emit/hcl.py::emit_hcl_project` + `templates/project.tf.j2` |
| How ec2_traefik discovers routes (the ECS-provider `traefik.*` labels on web-service task defs; the instance's `providers.ecs` static config) | `src/docex/emit/hcl.py::render_task_definition` (the `dockerLabels` block) + `templates/ec2_traefik_user_data.sh.j2`. Mod 070. Routing is label-driven, not release-pushed — there is no SSM routing param. |
| What ansible playbook looks like | `src/docex/emit/ansible.py` + `templates/playbook.yml.j2` |
| What the scaffold manifest render looks like | `src/docex/emit/secrets.py::render_manifest_env` |
| What the OTel sidecar config looks like | `src/docex/emit/otelcol.py` |
| How the sidecar is paired with each core service | `src/docex/emit/compose.py::_sidecar_block` (fixed — one per *emitted container*, so one per replica; its `paired_key` is the container it shares a netns with) + `src/docex/emit/hcl.py::render_task_definition` second container entry (elastic) |
| How `replicas` becomes containers or tasks | `src/docex/cicl/compile.py::effective_replicas` (the `prod`-only clamp) + `emit/compose.py` (the fixed unroll) + `emit/hcl.py::render_ecs_service` (`desired_count`) |
| An engine env var's `kind` / a fixed literal / a minted policy | `tables/roles/<role>.yml` `env:` + `tables/generation_policies.yml`; loader in `cicl/transfer.py` |
| How a minted value is generated | `src/docex/cicl/generate.py` |
| How `$[VAR]` resolves per kind (fixed inline vs runtime ref) | `src/docex/cicl/magic_refs.py::_inline_fixed` |
| The declared config block | `src/docex/cicl/model.py` (`CoreService.config`) + the config loop in `src/docex/cicl/compile.py` |
| Which category a source key falls in | `src/docex/cicl/categories.py` (`classify_source_keys`, `secret_manifest`, `config_manifest`) |
| The container-facing env file (dev/test aggregate) | `src/docex/orchestrate/aggregate.py` + `src/docex/envfile.py` |

For a new doctrine-prescribed AWS resource that isn't owned by any `infra.yml` service (a new structural emit): pick a policy from `naming_policies.yml` (or add one), call `apply_policy` from the emit site (mirror `bootstrap.py`'s pattern), and add a validation rule if the resource has its own constraints. If the structural set keeps growing, that's the signal to lift `structural_resources:` into the transfer tables (see mod 005 overview for the deferred design).

### Project segment on data-plane names

When forming a data-plane name (Docker network/container/volume, ECS Service Connect namespace, Route53 zone or record, ACM cert) that interpolates the project segment piecewise — i.e. not through `apply_policy` against the engine-naming policy — derive the project segment from `compiled.project_dns_label`, **not** from `compiled.project`. The raw `project` may carry underscores (`docex_smoke_elastic`); data-plane resolution requires hyphens (`docex-smoke-elastic`). Mod 046 added this field after several emit sites were found leaking underscores into Route53 / ACM / compose names. Inert AWS record-key identifiers (IAM, SSM, DDB) keep the raw `compiled.project` since the corresponding policies (`iam`, `ssm_path`, `ddb`) preserve underscores.
