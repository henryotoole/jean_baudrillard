# Mod 005 — Naming policies

## Problem

`docex bootstrap` for an elastic project named `docex_smoke_elastic` fails immediately with `InvalidBucketName` from S3. The state-backend bucket name is constructed as `f"{project}-tofu-state"` → `docex_smoke_elastic-tofu-state`, and S3 disallows underscores in bucket names.

The bug is narrow as written (three sites: `src/docex/pipeline/bootstrap.py:60-61`, `src/docex/emit/templates/project.tf.j2:20,23`, `src/docex/emit/templates/main.tf.j2:16,19,41`), but the underlying cause is systemic: the existing engine-level `naming:` block (per `transfer_tables.md § Naming Conventions`) only reaches resources owned by an engine. It doesn't reach:

- The state-backend S3 bucket and DynamoDB table (bootstrap.py).
- The project ECR repositories, project IAM execution role, project SSM path prefix (project tier emit).
- The ECS migration task family name (orchestrate/migrate.py — currently duplicates the naming logic inline).

Every time the doctrine adds a new structural resource — anything not associated with an `infra.yml` service — the same gap recurs and gets discovered only when AWS rejects the request. The five-artifact alignment in `docex_process.md` is the right place to fix this: refactor the naming rules into a doctrinal primitive that all emit sites — engine and structural — go through.

## Design

### Lift `naming:` to a top-level, named, reusable concept

Today, in each engine entry:

```yaml
roles:
  relational_db:
    postgres:
      ...
      naming:
        separator: hyphen
        case: lower
        max_len: 63
```

Proposed: add a top-level `naming_policies:` section to the transfer tables, and have engines (and structural emitters) reference a policy by name:

```yaml
naming_policies:
  s3:        { separator: hyphen, case: lower, max_len: 63 }   # S3 bucket
  rds:       { separator: hyphen, case: lower, max_len: 63 }   # RDS identifier, subnet group
  ddb:       { separator: hyphen, case: any,   max_len: 255 }  # DynamoDB table
  alb:       { separator: hyphen, case: any,   max_len: 32 }   # ALB and target-group name
  ecs:       { separator: hyphen, case: any,   max_len: 255 }  # ECS cluster, service, task family
  ecr_repo:  { separator: hyphen, case: lower, max_len: 256 }  # ECR repo name
  iam:       { separator: hyphen, case: any,   max_len: 64 }   # IAM role / policy
  ssm_path:  { separator: underscore, case: any, max_len: 1024 } # SSM parameter path segments
  docker:    { separator: underscore, case: any }              # Docker network/container/volume
  http_host: { separator: hyphen, case: lower }                # DNS-label form for hostnames

roles:
  relational_db:
    postgres:
      ...
      naming: rds          # was a struct; now a string ref into naming_policies
```

The policy schema is identical to today's inline `naming:` block — `{ separator: underscore | hyphen, case: any | lower, max_len: <int> }`. No new fields. Per the conversation that prompted this mod: the binary underscore-vs-hyphen choice is sufficient until we encounter a resource that needs something else.

### Names by resource-type vs by semantics

Two naming conventions for the policies themselves are reasonable:

- **By resource type** (`s3`, `rds`, `alb`, …) — the policy table reads like a doctrinal enumeration of "AWS resource types we know how to name." Easier for a doctrine reader to follow at the call site (`naming: rds` is self-explanatory).
- **By rule** (`hyphen_lower_63`, `underscore_any`, …) — self-describing; one policy can serve multiple resource types that happen to share constraints.

Recommendation: **by resource type**, because the doctrine wants a single canonical recipe per resource type and the call sites become readable. Where two resource types share an identical rule (S3 and RDS both happen to be hyphen+lower+63 right now), we still keep two named policies — they describe different intents and may diverge later.

### Structural emitters: how they get a policy

The state backend, project ECR repos, project IAM role, etc. don't appear under `roles:`. There are two ways they can reach a policy:

1. **Hardcoded name in docex code.** `bootstrap.py` calls `apply_policy(f"{project}-tofu-state", policy="s3")`. The policy *body* lives in the transfer tables and is reloadable; the *choice* of policy is doctrine knowledge embedded in docex itself.
2. **A new transfer-table `structural_resources:` section.** A declarative enumeration of every doctrine-emitted structural resource, each pointing at a policy. Cleaner but adds scope.

Recommendation: **option 1 for this mod.** Structural resources are a small, closed set today (state bucket, state DDB table, project ECR repos, project IAM role, SSM path prefix). Hardcoding the policy name at the emit site is fine and avoids dragging in a new doctrinal section. If the set grows, we can lift in a future mod.

### Single source of truth: a naming helper

Centralize policy application in one place:

```python
# src/docex/naming.py
def apply_policy(name: str, policy: NamingPolicy) -> str:
    out = name.replace("_", "-") if policy.separator == "hyphen" else name
    if policy.case == "lower":
        out = out.lower()
    if policy.max_len is not None and len(out) > policy.max_len:
        raise CompileError(...)
    return out
```

`src/docex/cicl/compile.py:194-206` and `src/docex/orchestrate/migrate.py:311+` currently each implement this inline; both will be replaced by calls to the new helper.

### Bootstrap.py and the j2 templates

- `bootstrap.py:60-61` becomes:
  ```python
  bucket = apply_policy(f"{project}-tofu-state", policies["s3"])
  table  = apply_policy(f"{project}-tofu-locks", policies["ddb"])
  ```
- The j2 templates already receive a `project` variable for string interpolation. They'll instead receive the pre-translated `state_bucket` and `state_table` values, and substitute those into the `backend "s3"` block. Logic stays in Python; templates just consume.

### Project ECR repos, IAM role, SSM path

While we're touching the structural emitters, the same translation should apply to:
- ECR repo name in `project.tf.j2` (`<project>/<svc>` — currently lowercases via tags but the literal repo name is the raw project string).
- IAM role/policy name (`<project>-task-execution`, `<project>-task-execution-ssm`).
- SSM path prefix in the IAM role's inline policy (`/<project>/*`).

This catches them all in one mod rather than triaging each as a separate ad-hoc fix.

Concretely:
- ECR repo → `apply_policy(f"{project}/{svc}", policies["ecr_repo"])`
- IAM role/policy → `apply_policy(f"{project}-task-execution", policies["iam"])`
- SSM prefix → `apply_policy(project, policies["ssm_path"])` (today: underscore-preserving, so no change for the smoke project, but explicit)

Note: this means the project-tier `main.tf` will reference `docex-smoke-elastic/web` for ECR while the registry tag the operator pushes also needs the same form. Containerize already builds the registry host string from the same template, so both sides stay aligned as long as both route through `apply_policy`.

### Backwards compatibility

Project-local transfer tables (per `cicl.md § CICL Transfer Tables`) may have inlined the old `naming:` struct. After this mod, that schema is unsupported — the loader will only accept a string ref into `naming_policies`. We're pre-1.0 (docex 0.7.x), so a hard break is appropriate. The CHANGELOG will call this out as a breaking change in the docex version that ships this mod.

## Five-artifact alignment

| Artifact | Change |
| -------- | ------ |
| `doctrine/.../*.md` | `transfer_tables.md` § Naming Conventions — replace the per-engine inline `naming:` description with the `naming_policies:` model, including a table of the doctrine-shipped policies. `elastic_bootstrap.md` § State backend — note that the bucket/table names are formed via the `s3` / `ddb` naming policies. `cicl.md` § Validation Rules — add a rule: every `naming:` ref in a transfer table resolves to a defined policy. |
| `docex/plans/core/*.md` | No change. The masterplan doesn't go into naming; this stays a transfer-table concern. |
| `tables/roles/*.yml` | Add `naming_policies:` block to one of the bundled tables (or create a new top-level `naming_policies.yml` and have the loader merge). Migrate the six existing engine `naming:` entries from inline struct to string ref. |
| `src/docex/**` | New: `src/docex/naming.py` with `NamingPolicy` and `apply_policy`. Loader: read `naming_policies:` from merged transfer tables; expose via context. `cicl/compile.py` and `orchestrate/migrate.py`: replace inline naming logic with `apply_policy` calls. `pipeline/bootstrap.py`: route state-backend names through `apply_policy`. `emit/hcl.py` (and any helper): route project ECR / IAM / SSM-path names through `apply_policy`. j2 templates: receive pre-translated values. |
| `tests/**` | Unit tests for `apply_policy` (hyphen translation, lowercase, max-len overflow error). Bootstrap unit test that asserts the bucket name passed to `s3_create_bucket` is the hyphen form. Compile output snapshot tests updated for any name changes in `project.tf` / `main.tf`. Transfer-table validation test: unknown policy ref fails compile. |

## Validation

1. `python3 -m pytest tests/unit/` — all tests pass.
2. `python3 -m pytest tests/` — all tests pass (including any new integration tests).
3. **Compile output regression check**:
   - `cd test_projects/elastic && ./bin/docex compile`
   - `grep -nE 'docex_smoke_elastic-' infra/output/project/main.tf infra/output/{stage,prod}/main.tf` — should return zero matches. Every `${project}-…` form is now hyphenated to `docex-smoke-elastic-…`.
   - `grep -nE 'docex_smoke_elastic_' infra/output/stage/main.tf` — should match only the SSM path / SG names / tags where the underscore form is intentional.
4. **End-to-end smoke for D.1**:
   - `cd test_projects/elastic && ./bin/docex bootstrap` — phase 1 succeeds; S3 bucket `docex-smoke-elastic-tofu-state` and DDB table `docex-smoke-elastic-tofu-locks` exist; Route53 zone applied; NS records printed.
5. Doctrine-shipped policies match the resource-type constraints in the AWS docs. (Validation by cross-reference; AWS doesn't have a single canonical machine-readable source for this.)

## Decisions captured

1. **Top-level `naming_policies:`, referenced by name.** Closed enumeration of AWS-resource-type constraints; both engines and structural emitters reference. Single source of truth.
2. **Policy names by resource type** (`s3`, `rds`, …), not by rule. Makes call sites readable; doctrine becomes a clear "here are the AWS resource types we know how to name" table.
3. **Schema unchanged** — still `{ separator: underscore | hyphen, case: any | lower, max_len: <int> }`. Binary separator is sufficient until we encounter a resource that needs something else.
4. **Hardcode policy choices for structural emitters in docex code**, not in a new transfer-table section. Closed and small set today; lift later if it grows.
5. **Hard break on project-local transfer-table schema.** Pre-1.0; CHANGELOG documents the change. Project-local tables migrate by replacing the inline `naming:` struct with a string ref.
6. **Sweep all project-tier structural resources** (state backend, ECR, IAM, SSM prefix) in this mod, not just the S3 blocker. Same root cause; same change shape; sweeping avoids three mods that all look the same.

## Open questions

1. **Policy name bikeshed.** Names above (`s3`, `rds`, `alb`, …) are by resource type. Open to feedback on naming style or the initial set itself.
2. **Where to put `naming_policies:` in the bundled tables.** New file `tables/naming_policies.yml` vs. embed at the top of an existing file vs. a new `tables/core.yml`. Loader has to be told to merge it either way; new file is cleanest.
3. **DDB table — hyphen or underscore?** DynamoDB accepts both. Doctrine consistency argues hyphen (same `<project>` segment as the S3 bucket); existing compiled output happens to be `docex_smoke_elastic-tofu-locks` (the bucket has hyphens *after* `<project>` but the project string itself is untranslated, so it ends up mixed). Going hyphen everywhere — including DDB — gives `docex-smoke-elastic-tofu-locks`, which is internally consistent.
