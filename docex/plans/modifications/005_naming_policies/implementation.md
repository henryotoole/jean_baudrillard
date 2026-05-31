# Mod 005 — Implementation Steps

This file is the implementation steps for mod 005 "Naming policies". Read `overview.md` in this folder first for the design rationale and decisions.

You are running in a fresh context. Everything you need is captured here and in the referenced files. Work through the steps in order. Run tests at the end.

## Scope

Lift naming from a per-engine inline struct to a top-level, reusable named-policy concept in the transfer tables. Engines and structural emitters (bootstrap, project-tier emit) all route name-building through one helper. Sweeps the immediate S3-state-backend bug, the project ECR / IAM / SSM-prefix naming, and the duplicate naming-logic implementations in `compile.py` and `migrate.py`.

**Foundation-wide rule established by this mod**: where an AWS resource type allows both underscore and hyphen, the doctrine prefers underscore (matching the project-name form). Hyphen-translation happens only where AWS requires it (S3 bucket, RDS identifier, ALB, ALB target group). This is a behavior change for ECS cluster / service / family / migration task — they switch from the current hyphen form to underscore.

## Decisions recap (from `overview.md`)

1. New top-level `naming_policies:` block in transfer tables.
2. Policies named by resource type (`s3`, `rds`, `alb`, `ecs`, `ddb`, `ecr_repo`, `iam`, `ssm_path`, `docker`, `http_host`).
3. Schema unchanged: `{ separator: underscore | hyphen, case: any | lower, max_len: <int> }`.
4. Engines reference policies by string name: `naming: rds`.
5. Structural emitters reference policies by hardcoded name in docex code (no `structural_resources:` table section).
6. Default to underscore where AWS allows both.
7. Hard break on the old inline `naming:` struct schema. Project-local transfer tables migrate.
8. Bundled policies live in a new file `tables/naming_policies.yml`.

## Step 1 — Create the bundled `naming_policies.yml`

New file `tables/naming_policies.yml`:

```yaml
# Generated and maintained by the doctrine. Defines the canonical set of
# AWS-resource-type naming policies the compiler applies anywhere a project
# / env / service name is interpolated into an identifier.
#
# Each policy describes:
#   separator: underscore | hyphen  -- character used to join name parts;
#                                      also the form internal underscores
#                                      get translated to (hyphen) or
#                                      preserved as (underscore).
#   case:      any | lower          -- whether to lowercase the result.
#   max_len:   <int>                -- optional ceiling; compile errors if
#                                      the rendered name is longer.
#
# Default policy: where AWS allows both separators, the doctrine prefers
# underscore (matching the project-name form). Hyphen is used only where
# AWS rejects underscores.

naming_policies:
  # S3 bucket names: lowercase, hyphens only.
  s3:
    separator: hyphen
    case: lower
    max_len: 63

  # RDS instance identifier / DB subnet group: lowercase, hyphens only.
  rds:
    separator: hyphen
    case: lower
    max_len: 63

  # DynamoDB tables accept both. Preserve underscores (decision 3).
  ddb:
    separator: underscore
    case: any
    max_len: 255

  # ALB and target-group names: hyphens only, 32-char ceiling.
  alb:
    separator: hyphen
    case: any
    max_len: 32

  # ECS cluster / service / task-definition family: both accepted; prefer
  # underscore for consistency with project-name form.
  ecs:
    separator: underscore
    case: any
    max_len: 255

  # ECR repo names: lowercase, both separators allowed; prefer underscore.
  ecr_repo:
    separator: underscore
    case: lower
    max_len: 256

  # IAM role / policy names: both accepted; prefer underscore.
  iam:
    separator: underscore
    case: any
    max_len: 64

  # SSM parameter path segments: both accepted; prefer underscore (matches
  # the `.env` key naming).
  ssm_path:
    separator: underscore
    case: any
    max_len: 1024

  # Docker network/container/volume names: both accepted; prefer underscore.
  docker:
    separator: underscore
    case: any

  # DNS labels (hostnames): hyphens only, lowercase.
  http_host:
    separator: hyphen
    case: lower
```

## Step 2 — Add `src/docex/naming.py`

New file `src/docex/naming.py`:

```python
"""Naming policies.

Per ``transfer_tables.md § Naming Policies``, name interpolation is
governed by a small, named set of policies that map "AWS resource type"
to "how to format an identifier." Engines reference a policy by name
(``naming: rds``); structural emitters in docex code reference one by
hardcoded name (``apply_policy(..., policy_name="s3")``).

This module exposes:

- ``NamingPolicy`` — the dataclass form of one policy.
- ``NamingPolicies`` — the loaded table, keyed by policy name.
- ``apply_policy(name, policy)`` — the single translation entry point.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from docex.errors import TransferTableError


@dataclass(frozen=True)
class NamingPolicy:
    """One naming policy.

    Attributes mirror the per-engine ``naming:`` block as documented in
    ``transfer_tables.md``. The schema is intentionally narrow: binary
    separator choice, optional case lowercasing, optional max-length
    ceiling.
    """

    name: str
    separator: str  # 'underscore' | 'hyphen'
    case: str       # 'any' | 'lower'
    max_len: int | None


@dataclass(frozen=True)
class NamingPolicies:
    """Loaded set of policies, keyed by name."""

    by_name: Mapping[str, NamingPolicy]

    def get(self, policy_name: str) -> NamingPolicy:
        if policy_name not in self.by_name:
            raise TransferTableError(
                f"unknown naming policy {policy_name!r}; defined: "
                f"{sorted(self.by_name)}"
            )
        return self.by_name[policy_name]


def parse_policies(raw: dict) -> NamingPolicies:
    """Parse a transfer-table ``naming_policies:`` block."""
    by_name: dict[str, NamingPolicy] = {}
    for name, body in (raw or {}).items():
        if not isinstance(body, dict):
            raise TransferTableError(
                f"naming_policies.{name}: expected a mapping"
            )
        sep = body.get("separator")
        if sep not in ("underscore", "hyphen"):
            raise TransferTableError(
                f"naming_policies.{name}.separator must be "
                f"'underscore' or 'hyphen' (got {sep!r})"
            )
        case = body.get("case", "any")
        if case not in ("any", "lower"):
            raise TransferTableError(
                f"naming_policies.{name}.case must be "
                f"'any' or 'lower' (got {case!r})"
            )
        max_len = body.get("max_len")
        if max_len is not None and not isinstance(max_len, int):
            raise TransferTableError(
                f"naming_policies.{name}.max_len must be an int or absent"
            )
        by_name[name] = NamingPolicy(
            name=name, separator=sep, case=case, max_len=max_len
        )
    return NamingPolicies(by_name=by_name)


def apply_policy(name: str, policy: NamingPolicy) -> str:
    """Apply one naming policy to an assembled identifier.

    The compiler always joins parts with ``_`` internally; this function
    decides whether to keep them or translate to ``-``. If ``case`` is
    ``lower``, the result is lowercased. If ``max_len`` is set and the
    result exceeds it, a clear error is raised — silent truncation is a
    known footgun and the doctrine prefers a clean compile-time failure
    (per ``transfer_tables.md`` validation rule).
    """
    if policy.separator == "hyphen":
        out = name.replace("_", "-")
    else:
        out = name.replace("-", "_")
    if policy.case == "lower":
        out = out.lower()
    if policy.max_len is not None and len(out) > policy.max_len:
        raise TransferTableError(
            f"name {out!r} exceeds policy {policy.name!r} max_len "
            f"{policy.max_len}; shorten project/env/service names"
        )
    return out
```

Use `TransferTableError` (existing in `docex.errors`) for any validation failures here. If the existing error types don't fit cleanly, add a `CompileError` subclass — but `TransferTableError` is appropriate because these are doctrine-table-shaped problems.

## Step 3 — Update the transfer-table loader

In `src/docex/cicl/transfer.py`:

3a. Import the new module and add `naming_policies` to `TransferTables`:

```python
from docex.naming import NamingPolicies, parse_policies
```

```python
@dataclass
class TransferTables:
    by_role: dict[str, dict[str, EngineEntry]]
    descriptions: dict[str, str] = field(default_factory=dict)
    naming_policies: NamingPolicies = field(
        default_factory=lambda: NamingPolicies(by_name={})
    )
```

3b. Change `EngineEntry.naming` from `dict[str, Any]` to `str` (policy ref). Drop the default:

```python
@dataclass
class EngineEntry:
    role: str
    engine: str
    foundation: str
    defaults: dict[str, Any] = field(default_factory=dict)
    fields: dict[str, Any] = field(default_factory=dict)
    provides: dict[str, Any] = field(default_factory=dict)
    env: dict[str, str] = field(default_factory=dict)
    naming: str = ""    # was: dict[str, Any]
    default_port: int | None = None
    reserved_names: list[str] = field(default_factory=list)
```

3c. Update `_parse_entry`. The `naming` value in a transfer table is now a string. Validate that it's present and that it resolves to a known policy (this validation happens after both top-level and roles get loaded):

```python
def _parse_entry(role: str, engine: str, raw: dict[str, Any]) -> EngineEntry:
    foundation = raw.get("foundation")
    if foundation not in ("fixed", "elastic", "both"):
        raise TransferTableError(...)
    naming_ref = raw.get("naming")
    if not isinstance(naming_ref, str) or not naming_ref:
        raise TransferTableError(
            f"role {role!r} engine {engine!r}: `naming:` must be a string "
            f"naming-policy reference (got {naming_ref!r}). "
            f"See transfer_tables.md § Naming Policies."
        )
    return EngineEntry(
        role=role,
        engine=engine,
        foundation=foundation,
        defaults=raw.get("defaults", {}) or {},
        fields=raw.get("fields", {}) or {},
        provides=raw.get("provides", {}) or {},
        env=raw.get("env", {}) or {},
        naming=naming_ref,
        default_port=raw.get("default_port"),
        reserved_names=[str(item).lower() for item in (raw.get("reserved_names") or [])],
    )
```

3d. Update `load_transfer_tables` to also merge `naming_policies:` from the bundled and project-local files, then cross-validate every engine's `naming` ref:

```python
def load_transfer_tables(project_root: Path | None) -> TransferTables:
    raw_merged: dict[str, Any] = {}

    bundled_root = _bundled_tables_root()
    sources: list[Path] = []
    if bundled_root is not None:
        sources.append(bundled_root)
    proj_root = _project_tables_root(project_root)
    if proj_root is not None:
        sources.append(proj_root)

    for root in sources:
        for _path, doc in _read_yaml_files(root):
            if "roles" in doc and isinstance(doc["roles"], dict):
                raw_merged = _deep_merge(raw_merged, {"roles": doc["roles"]})
            if "naming_policies" in doc and isinstance(doc["naming_policies"], dict):
                raw_merged = _deep_merge(
                    raw_merged, {"naming_policies": doc["naming_policies"]}
                )

    policies = parse_policies(raw_merged.get("naming_policies", {}))

    by_role: dict[str, dict[str, EngineEntry]] = {}
    descriptions: dict[str, str] = {}
    for role, engines in (raw_merged.get("roles") or {}).items():
        if not isinstance(engines, dict):
            raise TransferTableError(...)
        for engine, raw_entry in engines.items():
            if engine == "description":
                if isinstance(raw_entry, str):
                    descriptions[role] = raw_entry
                continue
            if not isinstance(raw_entry, dict):
                raise TransferTableError(...)
            entry = _parse_entry(role, engine, raw_entry)
            # Cross-validate the naming ref against the policy table.
            policies.get(entry.naming)
            by_role.setdefault(role, {})[engine] = entry

    return TransferTables(
        by_role=by_role,
        descriptions=descriptions,
        naming_policies=policies,
    )
```

## Step 4 — Migrate every bundled engine to a string ref

Six engine entries today carry an inline `naming:` struct. Update each to a string ref into the new policy table:

| File | Engine | Old | New |
| ---- | ------ | --- | --- |
| `tables/roles/relational_db.yml:168-171` | postgres | inline `{separator: hyphen, case: lower, max_len: 63}` | `naming: rds` |
| `tables/roles/reverse_proxy.yml:40-?` | traefik (et al.) | inline `{separator: hyphen, …}` | look up which AWS resource it ends up as; if no AWS resource at all (it's a fixed-only docker container), use `docker` |
| `tables/roles/web.yml:51-?` | container | inline `{separator: hyphen, …}` | `ecs` (the elastic emit creates ECS task/service for it) |
| `tables/roles/object_store.yml:56-?` | minio | inline `{separator: hyphen, …}` | minio is a fixed-only docker container → `docker` |
| `tables/roles/object_store.yml:81-?` | s3 | inline `{separator: hyphen, case: lower, max_len: 63}` | `s3` |
| `tables/roles/cache.yml:50-?` | redis (or similar) | inline `{separator: hyphen, …}` | redis-as-ElastiCache on elastic uses cluster identifier rules (similar to RDS — hyphen-only). Read each engine's `foundation:` field and pick: `docker` for fixed-only, otherwise the matching AWS resource policy. For redis-on-ElastiCache, the cluster identifier rules are similar to RDS — use `rds`. (If the project doesn't actually deploy this engine, the policy choice doesn't impact compiled output; pick the conservatively-correct one anyway.)

For each engine, read its current `defaults.fixed` / `defaults.elastic` blocks and confirm which AWS resource type the policy applies to. Use the resource-type policy. Open the existing files individually before editing.

## Step 5 — Centralize naming-application logic in compile.py

In `src/docex/cicl/compile.py`:

5a. Delete `_apply_naming` (lines 192-209). Replace with an import:

```python
from docex.naming import apply_policy, NamingPolicy
```

5b. Update `_global_service_name`. It currently takes the raw `naming` dict; switch to take a `NamingPolicy` directly:

```python
def _global_service_name(
    project: str, env: str, service: str, policy: NamingPolicy
) -> str:
    raw = f"{project}_{env}_{service}"
    return apply_policy(raw, policy)
```

5c. Find each call site of `_global_service_name`. Each one passes the engine's `naming` value. Resolve to a policy first:

```python
# was: name = _global_service_name(project, env, svc, engine.naming)
policy = ctx.transfer_tables.naming_policies.get(engine.naming)
name = _global_service_name(project, env, svc, policy)
```

This pattern (resolve once, pass `NamingPolicy`) keeps the helper's signature crisp and lifts the lookup to the call site where the engine identity is known.

5d. `_dns_label` (lines 265-267) is a fixed translation for DNS-label rules, not policy-driven. Leave it alone — it's used for per-service hostnames where the policy is always equivalent to `http_host` (hyphen + lower).

## Step 6 — Update migrate.py to use the helper

In `src/docex/orchestrate/migrate.py` (around line 290-322):

The function (currently inline-translates with `naming.get("separator", ...)`) re-derives the migration task family name at release time. After the mod, it should:

```python
# 1. Resolve the engine for the migrate-owning core service's role on elastic.
engines = tables.role(core.role)
engine_entry = None
for eng_name in sorted(engines):
    entry = engines[eng_name]
    if entry.supports("elastic"):
        engine_entry = entry
        break
if engine_entry is None:
    return f"{project}_{env}_{svc}_migrate"  # best-effort fallback
# 2. Apply the resolved policy.
policy = tables.naming_policies.get(engine_entry.naming)
raw = f"{project}_{env}_{svc}_migrate"
return apply_policy(raw, policy)
```

Delete the duplicate inline `separator`/`case` logic. Single source of truth.

## Step 7 — Update bootstrap.py

In `src/docex/pipeline/bootstrap.py:60-61`:

```python
from docex.naming import apply_policy

# ...
policies = ctx.transfer_tables.naming_policies
bucket = apply_policy(f"{project}_tofu_state", policies.get("s3"))
table  = apply_policy(f"{project}_tofu_locks", policies.get("ddb"))
```

Note the *raw* input is now underscore-joined (`{project}_tofu_state`). `apply_policy` decides whether to translate. This makes the helper the single point of decision.

For `docex_smoke_elastic`:
- `bucket` → `apply_policy("docex_smoke_elastic_tofu_state", s3)` → `"docex-smoke-elastic-tofu-state"`. Valid S3 name.
- `table` → `apply_policy("docex_smoke_elastic_tofu_locks", ddb)` → `"docex_smoke_elastic_tofu_locks"`. Valid DDB name; underscores preserved.

`ctx` must already carry `transfer_tables`. Check `src/docex/__main__.py` and `context.py` to confirm bootstrap receives it. If bootstrap's entry function doesn't yet receive `transfer_tables`, route it through — same pattern as the other commands.

## Step 8 — Update the project-tier emit (hcl.py + project.tf.j2)

In `src/docex/emit/hcl.py:emit_hcl_project` (around line 435-470):

Pre-compute every name slot before rendering the template. The template no longer assembles names from `{{ project }}` for resource identifiers; it receives them pre-formed.

Add to the Jinja context passed into `project.tf.j2`:

```python
policies = compiled.transfer_tables.naming_policies  # or wherever it's reachable
ctx = {
    "project": compiled.project,
    "project_version": compiled.project_version,
    "domain": compiled.domain,
    "region": compiled.region,
    "core_service_names": [...],
    # New: pre-translated resource identifiers
    "state_bucket": apply_policy(f"{compiled.project}_tofu_state", policies.get("s3")),
    "state_lock_table": apply_policy(f"{compiled.project}_tofu_locks", policies.get("ddb")),
    "task_execution_role_name": apply_policy(f"{compiled.project}_task_execution", policies.get("iam")),
    "task_execution_ssm_policy_name": apply_policy(f"{compiled.project}_task_execution_ssm", policies.get("iam")),
    # ECR repo names: <project>/<svc>. The `/` separator is not affected
    # by the policy; only the segments on either side are. Compute both
    # segments under the ecr_repo policy and reassemble.
    "ecr_repo_names": {
        svc.name: (
            apply_policy(compiled.project, policies.get("ecr_repo"))
            + "/"
            + apply_policy(svc.name, policies.get("ecr_repo"))
        )
        for svc in compiled.core_services
    },
    # SSM path prefix in the IAM inline policy (preserves underscores).
    "ssm_path_project": apply_policy(compiled.project, policies.get("ssm_path")),
}
```

In `src/docex/emit/templates/project.tf.j2`:

- Line 20, 23: `bucket = "{{ state_bucket }}"`, `dynamodb_table = "{{ state_lock_table }}"`.
- Line 213-221 (ECR repo block): `name = "{{ ecr_repo_names[svc.name] }}"`.
- Line 241: `name = "{{ task_execution_role_name }}"`.
- Line 266: `name = "{{ task_execution_ssm_policy_name }}"`.
- Line 274 (SSM IAM resource): `Resource = "arn:aws:ssm:{{ region }}:${data.aws_caller_identity.current.account_id}:parameter/{{ ssm_path_project }}/*"`.

Leave every `tags = { project = "{{ project }}", ... }` and every `Name = "{{ project }}..."` *tag* alone — those are documentary, not identifiers. The raw `{{ project }}` form is correct in tags.

## Step 9 — Update the env-tier emit (hcl.py + main.tf.j2)

In `src/docex/emit/hcl.py:emit_hcl` (around line 471 onward):

Pre-compute env-tier name slots and pass to the template:

```python
policies = compiled.transfer_tables.naming_policies
ctx = {
    "project": compiled.project,
    "env": compiled.env,
    # ...
    "state_bucket": apply_policy(f"{compiled.project}_tofu_state", policies.get("s3")),
    "alb_name": apply_policy(f"{compiled.project}_{compiled.env}_alb", policies.get("alb")),
    "ecs_cluster_name": apply_policy(f"{compiled.project}_{compiled.env}", policies.get("ecs")),
}
```

In `src/docex/emit/templates/main.tf.j2`:

- Line 16, 19: `bucket = "{{ state_bucket }}"`, `dynamodb_table = "{{ state_lock_table }}"` (define `state_lock_table` in ctx the same way).
- Line 41: `bucket = "{{ state_bucket }}"` (data source for project remote state).
- Line 119: `name = "{{ alb_name }}"`.
- Line 165: `name = "{{ ecs_cluster_name }}"`.
- Line 52, 87: SG names use `{{ project }}_{{ env }}_{{ short }}` and `{{ project }}_{{ env }}_alb`. SGs accept underscores; per decision 3 we keep them. *No change needed*. (Leave the literal `_` joiners.)

The `render_backing` and `render_core` helpers in `hcl.py` already use `svc.global_name`. After step 5, `svc.global_name` flows from `_global_service_name` which now applies the policy from `engine.naming`. So those resources (RDS identifier, ECS task family, ECS service, target group) inherit the policy automatically — no per-call-site changes needed.

## Step 10 — Cross-validate during compile

In `src/docex/cicl/validate.py` (or wherever validation runs):

Validation rule 9 of `transfer_tables.md` will be extended (see step 11). Add a runtime check: for every loaded engine, confirm `engine.naming` resolves in the policy table.

The cross-validation in `load_transfer_tables` (step 3d) covers this at load time — that's sufficient. No additional code path needed unless project-local naming overrides come into play.

## Step 11 — Update the doctrine

11a. `doctrine/infrastructure/specifics/transfer_tables.md` — § Naming Conventions:

Replace the current text describing per-engine `naming:` inline structs with a description of `naming_policies:` as a top-level transfer-table section. Add a sub-section "Naming Policies" with:

- Schema of one policy: `{ separator, case, max_len }`.
- A table listing every doctrine-shipped policy with its rule.
- The doctrine-wide default: underscores preferred where AWS allows both.
- How engines reference one (`naming: rds`).
- How structural emitters reference one (hardcoded policy name in docex code).
- Cross-reference for the bug this prevents (see § Validation, rule 9 below).

Update the postgres walking example (lines 109-167 in current file) — replace inline `naming:` block with `naming: rds`.

Update the "Walking example: web / container" example similarly: `naming: ecs`.

Update § Validation rule list: add a new rule (becomes rule 10) — "Every engine's `naming:` value is the name of a policy declared in `naming_policies:`".

11b. `doctrine/infrastructure/specifics/elastic_bootstrap.md` — § State backend:

Add a sentence under each of "S3 bucket for state" and "DynamoDB table for locking" noting the name is constructed by applying the `s3` and `ddb` naming policies respectively (with a cross-reference to `transfer_tables.md § Naming Policies`).

Under § Project-tier infrastructure, add a sentence: "All resource identifiers are formed by applying the matching naming policy (S3 → `s3`, RDS → `rds`, ALB → `alb`, ECS → `ecs`, ECR repo → `ecr_repo`, IAM → `iam`, SSM path → `ssm_path`)."

11c. `doctrine/infrastructure/cicl.md` — § Validation Rules:

Add: "15. Every engine's `naming:` value in a transfer table is the name of a policy declared in `naming_policies:`." (or whatever the next rule number is — current rules end at 14)

## Step 12 — Update CHANGELOG

In `docex/CHANGELOG.md`, under `## [Unreleased]`, add or extend a `### Changed` section:

```markdown
### Changed

- **BREAKING (transfer tables)** — the per-engine inline `naming:` struct
  is replaced by a string reference into a new top-level
  `naming_policies:` table. Project-local transfer tables must migrate:
  e.g. `naming: { separator: hyphen, case: lower, max_len: 63 }` becomes
  `naming: rds`. See `doctrine/infrastructure/specifics/transfer_tables.md`
  § Naming Policies for the canonical policy set.
- ECS cluster, service, task-definition family, and migration task names
  now use underscore form (matching the project-name convention) instead
  of the previous hyphen form. Existing deployments will see tofu plan a
  recreation of those resources on next apply; ECS is stateless and the
  recreate is safe.
- The OpenTofu state-backend S3 bucket name is now hyphen-translated so
  projects with underscore-bearing names (e.g. `docex_smoke_elastic`)
  pass S3 bucket-name validation. Existing buckets retain their old
  name; new bootstraps create the hyphen form.
```

## Step 13 — Tests

13a. Unit tests for `src/docex/naming.py` (new file: `tests/unit/test_naming.py`):

- `apply_policy` with `separator: hyphen` translates underscores in the input to hyphens.
- `apply_policy` with `separator: underscore` translates hyphens back to underscores.
- `apply_policy` with `case: lower` lowercases the result.
- `apply_policy` with `max_len` raises `TransferTableError` on overflow.
- `parse_policies` rejects unknown separator/case values with a clear error.
- `NamingPolicies.get` raises a clear error for unknown policy names.

13b. Unit test for the loader (`tests/unit/test_transfer.py` — extend the existing file):

- A transfer-table fixture with `naming_policies:` and engines referencing them loads cleanly.
- A transfer-table fixture with an engine `naming: nonexistent` fails to load with a clear error.
- The old inline-struct schema fails to load (proves the breaking change is enforced).

13c. Snapshot/compile tests (`tests/integration/` or whatever the existing convention is):

- Recompile `test_projects/elastic` and assert key strings in the output:
  - Project main.tf: `bucket = "docex-smoke-elastic-tofu-state"`, `dynamodb_table = "docex_smoke_elastic_tofu_locks"`, ECR repo `"docex_smoke_elastic/web"`, IAM role `"docex_smoke_elastic_task_execution"`.
  - Stage main.tf: ALB `"docex-smoke-elastic-stage-alb"`, ECS cluster `"docex_smoke_elastic_stage"`, RDS identifier `"docex-smoke-elastic-stage-db"`, ECS service `"docex_smoke_elastic_stage_web"`, task family `"docex_smoke_elastic_stage_web"`.
- A test that the project main.tf's `backend "s3"` block's `bucket` and `dynamodb_table` match the names bootstrap would create.

13d. Bootstrap unit test (`tests/unit/test_bootstrap.py` — extend or create):

- Stub the AWS client. Run bootstrap against a project named `docex_smoke_elastic`. Assert `aws.s3_create_bucket` was called with `docex-smoke-elastic-tofu-state` and `aws.ddb_create_locking_table` was called with `docex_smoke_elastic_tofu_locks`.

## Step 14 — Recompile the smoke-test project's compiled output

After all code changes are in:

```
cd test_projects/elastic
./bin/docex compile
```

Confirm the new compiled output is in place:

```
grep -nE 'docex.smoke.elastic.tofu' infra/output/project/main.tf infra/output/stage/main.tf
```

Expected substrings:
- `bucket         = "docex-smoke-elastic-tofu-state"`
- `dynamodb_table = "docex_smoke_elastic_tofu_locks"`

Also confirm:
- ECS cluster name in `stage/main.tf` is now `docex_smoke_elastic_stage`.
- ECS service / task family names use underscores throughout.
- ALB name remains hyphenated (`docex-smoke-elastic-stage-alb`).
- IAM role/policy names use underscores (`docex_smoke_elastic_task_execution`).
- ECR repo names: `docex_smoke_elastic/web`, `docex_smoke_elastic/worker`.

Stage in the new compiled output as part of the working tree (the test project's git repo is separate; commit there separately).

The fixed-foundation test project (`test_projects/fixed/`) should also be recompiled. Its compiled output has no AWS resources so the changes are minimal — confirm `docex compile` still produces a clean compose file with no errors.

## Step 15 — Test sweep

```
cd ~/.claude/jean_baudrillard/docex
python3 -m pytest tests/unit/        # all green
python3 -m pytest tests/             # all green (integration tests too)
```

If any existing snapshot fails because of the changed compiled output: re-read the failing snapshot, confirm the new output is correct per this mod, and update the snapshot fixture. Do not blanket-update fixtures without reading each diff.

## Out of scope

- Rebuilding the `docex:0.7.x` image. The operator will do that as the next step after reviewing the implementation.
- The actual D.1+ smoke walk against AWS. The operator runs this after the rebuild.
- Adding policies for resources docex doesn't yet emit (Step Functions, EventBridge, Lambda, etc.). When the doctrine grows a new resource type, add the policy at that time.
- Any changes to `core/<svc>` application code in the test projects.

## Final commit shape

When the work is complete and tests pass, leave the changes uncommitted. The original "design-context" LLM will review the diff before any commit happens, per the mod process step 5.
