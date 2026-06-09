# Mod 030 — Naming Policy Unification

First mod of the [doctrine-shape-and-tier campaign](../../campaigns/shape_overhaul_mod_list.md). Foundational data shift that every later mod depends on.

## The Doctrine Change

The doctrine just unified naming across the data plane. From [`transfer_tables.md § Naming Policies`](../../../../doctrine/infrastructure/specifics/transfer_tables.md#naming-policies):

> Anything name-resolvable on the data plane uses hyphens — Docker containers/networks/volumes, ECS cluster/service/task-def identifiers, ECS Service Connect names, ALB/target-group names, S3 buckets, RDS identifiers, hostnames. Underscores are preserved only for inert identifiers that AWS uses as record keys but applications never name in DNS or compose: IAM roles, SSM path segments, DynamoDB tables.

Net effect on the operator: a service's compiled name is **identical** on fixed Docker and elastic ECS — `${project}-${env}-${svc}` everywhere a human or container would reference it.

### Specific policy changes in `tables/naming_policies.yml`

| Policy | Old | New |
|--------|-----|-----|
| `docker` | `separator: underscore` | `separator: hyphen` |
| `ecs` | `separator: underscore` | `separator: hyphen` |
| `ecr_repo` | `separator: underscore, case: lower, max_len: 256` | **removed** |

Other policies (`s3`, `rds`, `ddb`, `alb`, `iam`, `ssm_path`, `http_host`) are unchanged.

The leading comment block in `naming_policies.yml` is now wrong ("doctrine prefers underscore matching the project-name form") and needs rewriting to match the new doctrine-default rule.

### ECR repo emission becomes structural

The `ecr_repo` policy went away because the single-separator policy machinery can't express the ECR repo shape: `${project}/${service}` with a literal `/` between segments and each segment's own underscores preserved verbatim.

The policy-driven version that currently lives at `src/docex/emit/hcl.py:787-790`:

```python
ecr_repo_names = {
    name: (
        apply_policy(project, ecr_p) + "/" + apply_policy(name, ecr_p)
    )
    for name in core_service_names
}
```

becomes simply:

```python
ecr_repo_names = {
    name: f"{project}/{name}"
    for name in core_service_names
}
```

Each segment passes verbatim — no lowercasing, no length cap, no separator translation. Per [`transfer_tables.md § How structural emitters reference a policy`](../../../../doctrine/infrastructure/specifics/transfer_tables.md#how-structural-emitters-reference-a-policy), this joins the doctrine's small but growing set of structural emit sites that don't go through a policy.

## Ramifications

### `global_service_name` flips form everywhere

This is the largest behavioral change of the campaign. Today, with `docker` and `ecs` policies on `separator: underscore`, a service named `api` in env `dev` of project `docex_smoke_elastic` compiles to:

- Container name: `docex_smoke_elastic_dev_api`
- Docker network: `docex_smoke_elastic_dev_web`, `docex_smoke_elastic_dev_internal`
- ECS cluster: `docex_smoke_elastic_dev` (well, `_stage` / `_prod`)
- ECS service: `docex_smoke_elastic_prod_api`
- ECS task-def family: `docex_smoke_elastic_prod_api`

After mod 030 all of those become hyphenated:

- Container name: `docex-smoke-elastic-dev-api`
- Docker network: `docex-smoke-elastic-dev-web`, `docex-smoke-elastic-dev-internal`
- ECS cluster: `docex-smoke-elastic-prod`
- ECS service: `docex-smoke-elastic-prod-api`
- ECS task-def family: `docex-smoke-elastic-prod-api`

The compiler path doesn't change — `apply_policy(internal_form, policy)` already takes the policy as data. What changes is the policy's `separator`, so every call site that pulls `docker` or `ecs` automatically flips.

Backing services follow their own engine's `naming:` ref (`rds` for postgres, etc.) and don't change behavior — they were already hyphenated.

### Underscores survive in three places

To make the mental model concrete:

- IAM roles (e.g. `docex_smoke_elastic_task_execution`)
- SSM path segments (e.g. `/docex_smoke_elastic/prod/POSTGRES_USER`)
- DynamoDB tables (e.g. `docex_smoke_elastic_tofu_locks`)

These are AWS record keys, never resolved on the data plane, never typed in a compose file, never reached by name from inside a container. The doctrine accepts that retaining the `project_name`-shape underscore form is more readable for these specific identifiers.

### ECR repo names — same string today, different mechanism

For `docex_smoke_elastic` with service `api`, today's emit produces `docex_smoke_elastic/api` (the `ecr_repo` policy was `case: lower` but the input was already lowercase; `separator: underscore` preserved the project-name underscores). After mod 030, the structural emit produces… `docex_smoke_elastic/api` — same string. But the *mechanism* differs: no policy is applied, no lowercasing happens, no length cap is enforced. A project whose name contained uppercase or hyphens would behave differently under the new path (the project would also fail ECR's own name validation, which is the right place for that failure to surface).

The image-reference forms in `infra/output/<env>/main.tf` and `infra/output/{dev,test}/docker-compose.yml` already use the literal `${project_name}/${service_name}` shape (the dev/test local tag construction at `src/docex/cicl/compile.py:281` builds it directly from project+service strings, no policy involved). Those don't need changes — only the explicit ECR repo `name` field in `project.tf.j2` consumes `ecr_repo_names`.

### Test ripple

Every test that asserts a compiled identifier for a Docker or ECS resource pins the underscore form today. Counting from a quick grep, that's most tests in `tests/integration/test_compile.py`, plus targeted unit tests under `tests/unit/`. Expected breakage:

- `tests/unit/test_naming.py` — already exercises `apply_policy`; needs cases updated where it asserts a specific output for the `docker` or `ecs` policies.
- `tests/integration/test_compile.py:432-434` — already passes literal strings through `apply_policy`; those will produce different values for any `docker`/`ecs` call site. The `s3` and `ddb` cases at that line don't change.
- Any tests that read fixture output files (`tests/fixtures/...`, if they exist) — fixtures will need regeneration.
- Strict-allowlist tests for `_ALLOWED_POLICY_NAMES` (mod 012) — drop `ecr_repo` from the allowed set.

The test churn is mechanical and large, not subtle. Most failures will be one-line s/_/-/g per assertion.

### Test-projects compiled output — explicitly deferred

`test_projects/{fixed,elastic}/infra/output/` is git-tracked and will diff heavily after this mod (every Docker network, container_name, ECS resource name). **Decision: do not recompile within this mod.** The test projects will be rebuilt from scratch at the end of the campaign as part of the major-version re-inception (per `docex_process.md` — major cuts require a fresh re-inception walk that replaces the seed). Carrying dirty test-project output across the campaign is acceptable; the re-inception blows it away.

Implementation note: the implementer should **not** run `./bin/docex compile` against either test project as part of this mod. Any tests that compile the test projects in-place and assert against committed output need handling — see [§ Test ripple](#test-ripple) below and the implementation steps.

### What does NOT change in mod 030

- Magic-ref grammar (`${...}`, `$[...]`, `@<expr>`) — untouched.
- ECR `provides:` shape and image-reference construction — already uses the structural form via project+service strings.
- The set of structural emit sites — still hardcoded in docex code per the doctrine; this mod just adds ECR to that set instead of routing it through a policy.
- Backing services using non-changed policies (`rds`, `s3`, etc.).

## Concrete File Surface

**Authoritative changes:**

- `tables/naming_policies.yml` — flip two separators, remove `ecr_repo`, rewrite leading comment to match new default rule.
- `src/docex/emit/hcl.py` — line 784 `ecr_p = naming_policies.get("ecr_repo")` removed; lines 787-790 `ecr_repo_names` dict rebuilt with verbatim `f"{project}/{name}"`.
- `src/docex/naming.py` and/or `src/docex/cicl/transfer.py` — `_ALLOWED_*` constants that name `ecr_repo` get it removed.

**Doc updates (in this mod, since they describe what's changing):**

- `docex/plans/core/compiler.md` — the "Structural vs engine emit" section currently lists `ecr_repo` as one example; ECR moves to the "rendering hardcoded" carve-out. The "naming flow" worked example (uses `ecs` policy) gets updated.
- `tables/README.md` — refresh if it describes the policy set.

**Test updates (mechanical, but bulk):**

- `tests/unit/test_naming.py` — flip `docker`/`ecs` expectations; drop any `ecr_repo` test.
- `tests/integration/test_compile.py` — flip `docker`/`ecs`-derived expectations; verify ECR repo names via the new structural form.
- Any other tests that assert compiled identifiers — flip mechanically.

**Test-project recompile (recommendation):**

- `test_projects/fixed/infra/output/` — recompile and commit.
- `test_projects/elastic/infra/output/` — recompile and commit.

## Operator Decisions

1. **Test-project recompile** — deferred to end-of-campaign re-inception. Do not run `./bin/docex compile` against the test projects in this mod.
2. **Backwards compatibility** — none, ever. All existing consumer projects under prior `docex_version` pins will be manually updated; no shims, no deprecation paths.
3. **In-flight consumers** — none beyond the two bundled smoke projects, which will be rebuilt at the end of the campaign. No changelog caveats needed beyond the standard major-bump note.
4. **`ecr_repo` policy** — delete, do not deprecate.

## What This Mod Is NOT

- Not adding the `reverse_proxy:` field (mod 031).
- Not renaming `domain:` → `apex_domain:` (mod 031).
- Not changing the telemetry sidecar name (mod 032; that change goes `_otelcol` → `-otelcol`, which is a separate doctrine concern flowing through this same naming-unification logic).
- Not introducing any new emit sites or commands.

The blast radius is wide (every Docker / ECS name flips) but the conceptual surface is narrow (two `separator:` flips + one policy removal + one ECR emit-site refactor).
