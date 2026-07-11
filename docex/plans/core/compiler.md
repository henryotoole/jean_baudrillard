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
- **`CompiledEnv` / `CompiledService`** — the per-env compile result. `CompiledService` carries `name`, `role`, `engine`, `is_core`, `global_name` (policy-applied), `body` (engine defaults merged with project overrides), `env` block, `networks`, `port`, etc. This is what the emit layer reads.

In `src/docex/naming.py`:

- **`apply_policy(name, policy)`** — the single naming-translation entry point. Mod 005 collapsed two duplicated inline implementations (in `compile.py` and `orchestrate/migrate.py`) into this. Mod 069 added policy `overflow` handling: a name over `max_len` normally errors, but a policy with `overflow: hash_truncate` (the `alb` policy) instead keeps a readable prefix and appends a 6-hex-char SHA-256 suffix so AWS `name` identifiers fit their 32-char cap — the descriptive form stays in the resource's `Name` tag.

In `src/docex/cicl/substitute.py`:

- **`HCLLiteral`** — a `str` subclass marking a value as raw HCL. The emit layer skips quoting on `HCLLiteral` values, so `aws_db_instance.appdb.address` ends up in the artifact as an HCL expression rather than a quoted string.
- **`substitute_string` / `substitute_tree`** — the compile-time-substitution helpers.

In `src/docex/cicl/magic_refs.py`:

- **`MagicRefResolver`** — resolves `${backing_services.<svc>.<part>}` and `${core_services.<svc>.<part>}` against the named service's engine `provides:` block. State (compile contexts, engines, foundation) is held on the resolver instance.

## Substitution grammar — three layers, three resolvers

The doctrine spec is in [`transfer_tables.md § Substitution Grammar`](../../../doctrine/infrastructure/specifics/transfer_tables.md#substitution-grammar). The implementation enforces the layering:

| Syntax | Stage | Resolver |
| ------ | ----- | -------- |
| `${var}` | compile time | `compile.py` + `cicl/substitute.py`. Compile errors if unresolved. |
| `$[var]` | runtime (container start) | Emitted verbatim. Translates to compose `${VAR}` (fixed) or an ECS `secrets[]` entry (elastic). |
| `@<expr>` | tofu apply | Emitted as HCL (after stripping `@`). Compile errors if a `@<expr>` appears on the fixed branch. |

A compile-time `${var}` embedded inside a `@<expr>` is resolved during emit; the outer `@` survives so OpenTofu sees a real HCL expression.

**Engine-env `kind` short-circuits `$[VAR]` (mod 077).** When a `$[VAR]` names a `kind: fixed` engine env var, `magic_refs.py::_inline_fixed` substitutes the var's literal `value:` at compile time rather than emitting a runtime ref. `minted`/`secret` vars stay runtime pass-through. So `POSTGRES_USER` inlines to `appuser` everywhere and the fixed var's backing-body / `provides` `$[VAR]` never reaches emit — no emitter change was needed. The elastic SSM data-source / `secrets[]` therefore fire only for the non-fixed vars (e.g. `POSTGRES_PASSWORD`).

## Naming flow

The compiler always joins parts with `_` internally; the policy decides what reaches the artifact. For service `web` in env `stage` of project `docex_smoke_elastic`:

1. Internal form: `docex_smoke_elastic_stage_web`.
2. Engine `container` (role `web`) declares `naming: ecs`.
3. Policy lookup → `ecs = {separator: hyphen, case: any, max_len: 255}` (mod 030: data-plane resolvable, hyphen).
4. `apply_policy(...)` translates underscores → `docex-smoke-elastic-stage-web`.

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
- Every magic-ref dependency between services has a matching `depends_on` declaration.
- A minted var's `policy:` names a defined `generation_policies` entry (rule 13, load-time — mod 076).
- `kind: fixed` ⇒ a `value` and no `policy`; `kind: minted` ⇒ a `policy` and no `value` (rule 14, mod 076).
- Per service, the `env` / `secrets` / `config` key sets do not overlap (rule 16, mod 079).
- Project-wide, source keys are cross-category disjoint — no key is a secret in one service and config in another (rule 20, via `classify_source_keys`); doctrine-injected keys are reserved in every category (mod 079).

A compile-time error is always preferable to a tofu/AWS-side error. A load-time error is preferable to a compile-time error. When in doubt, add validation at the earliest layer where the problem is detectable.

## Where to look when changing things

| To change... | Touch... |
| ------------ | -------- |
| What a role/engine emits per foundation | `tables/roles/<role>.yml` (data) |
| How a name is formatted | `tables/naming_policies.yml` (data) + the engine's `naming: <policy>` ref |
| How the compiler walks services | `src/docex/cicl/compile.py` |
| How magic refs are resolved | `src/docex/cicl/magic_refs.py` + `cicl/substitute.py` |
| How doctrine env vars are injected on core services | `src/docex/cicl/compile.py` — the `env_block[...]` assignments after the resolved-magic-ref loop |
| What compose YAML looks like | `src/docex/emit/compose.py` |
| What env-tier HCL looks like | `src/docex/emit/hcl.py` + `templates/main.tf.j2` |
| How a specific AWS resource type is rendered | `src/docex/emit/hcl.py` — the matching `render_<destination>` function (one per entry in `EMIT_DESTINATIONS["elastic"]`). Dispatch is keyed off the engine's `emits.elastic` list via `_DESTINATION_RENDERERS`. Mod 013. |
| What project-tier HCL looks like | `src/docex/emit/hcl.py::emit_hcl_project` + `templates/project.tf.j2` |
| How ec2_traefik discovers routes (the ECS-provider `traefik.*` labels on web-service task defs; the instance's `providers.ecs` static config) | `src/docex/emit/hcl.py::render_task_definition` (the `dockerLabels` block) + `templates/ec2_traefik_user_data.sh.j2`. Mod 070. Routing is label-driven, not release-pushed — there is no SSM routing param. |
| What ansible playbook looks like | `src/docex/emit/ansible.py` + `templates/playbook.yml.j2` |
| What the scaffold manifest render looks like | `src/docex/emit/secrets.py::render_manifest_env` |
| What the OTel sidecar config looks like | `src/docex/emit/otelcol.py` |
| How the sidecar is paired with each core service | `src/docex/emit/compose.py::_sidecar_block` (fixed) + `src/docex/emit/hcl.py::render_task_definition` second container entry (elastic) |
| An engine env var's `kind` / a fixed literal / a minted policy | `tables/roles/<role>.yml` `env:` + `tables/generation_policies.yml`; loader in `cicl/transfer.py` |
| How a minted value is generated | `src/docex/cicl/generate.py` |
| How `$[VAR]` resolves per kind (fixed inline vs runtime ref) | `src/docex/cicl/magic_refs.py::_inline_fixed` |
| The declared config block | `src/docex/cicl/model.py` (`CoreService.config`) + the config loop in `src/docex/cicl/compile.py` |
| Which category a source key falls in | `src/docex/cicl/categories.py` (`classify_source_keys`, `secret_manifest`, `config_manifest`) |
| The container-facing env file (dev/test aggregate) | `src/docex/orchestrate/aggregate.py` + `src/docex/envfile.py` |

For a new doctrine-prescribed AWS resource that isn't owned by any `infra.yml` service (a new structural emit): pick a policy from `naming_policies.yml` (or add one), call `apply_policy` from the emit site (mirror `bootstrap.py`'s pattern), and add a validation rule if the resource has its own constraints. If the structural set keeps growing, that's the signal to lift `structural_resources:` into the transfer tables (see mod 005 overview for the deferred design).

### Project segment on data-plane names

When forming a data-plane name (Docker network/container/volume, ECS Service Connect namespace, Route53 zone or record, ACM cert) that interpolates the project segment piecewise — i.e. not through `apply_policy` against the engine-naming policy — derive the project segment from `compiled.project_dns_label`, **not** from `compiled.project`. The raw `project` may carry underscores (`docex_smoke_elastic`); data-plane resolution requires hyphens (`docex-smoke-elastic`). Mod 046 added this field after several emit sites were found leaking underscores into Route53 / ACM / compose names. Inert AWS record-key identifiers (IAM, SSM, DDB) keep the raw `compiled.project` since the corresponding policies (`iam`, `ssm_path`, `ddb`) preserve underscores.
