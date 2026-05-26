# `docex` — Phase 4 Implementation

This document covers the work needed to ship Phase 4 of `docex`: the elastic-foundation halves of the command surface. After Phase 4, `docex` is the doctrine's complete executor — every command in `docex.md` is fully implemented for both `fixed` and `elastic` foundations.

Phase 4's success criterion: against an elastic-foundation project with one core service and one backing service, a developer can:

1. Run `./bin/docex bootstrap` once and have the project's OpenTofu state backend (S3 + DynamoDB) created/reconciled.
2. Run the full CI/CD chain — `docex merge && docex containerize && docex release stage && docex stagetest && docex release prod` — and land code in a deployed prod environment on AWS.
3. Run `./bin/docex migrate stage` or `./bin/docex migrate prod` standalone to apply migrations against a deployed env.

## Required Reading

You should already have the Phase 1-3 doctrine context. Additional load-bearing reads for Phase 4:

1. `~/.claude/jean_baudrillard/doctrine/infrastructure/specifics/elastic_bootstrap.md` — authoritative for the `bootstrap` command. Read every line.
2. `~/.claude/jean_baudrillard/doctrine/infrastructure/specifics/release_mechanism.md` §§ "Elastic Foundation: OpenTofu" and "Migrations / Elastic-foundation mechanism" — authoritative for elastic `release` and `migrate`.
3. `~/.claude/jean_baudrillard/doctrine/infrastructure/specifics/transfer_tables.md` § "Substitution Grammar" — re-read carefully. Phase 4 fixes the `$[VAR]` → ECS `secrets[]` translation and the `@<expr>` handling for RDS-style provider-allocated values.
4. `~/.claude/jean_baudrillard/doctrine/infrastructure/shape2.md` § "Elastic-Foundation" — the resources Phase 4's emitter outputs.
5. `~/.claude/jean_baudrillard/doctrine/infrastructure/credentials.md` § "Elastic" — for the credentials sourcing rules (`~/.aws/credentials`).
6. `~/.claude/jean_baudrillard/docex/implementation/phase_3.md` — to know the patterns Phase 3 established (GitClient + AnsibleRunner pattern; Phase 4 follows the same shape for AWS and OpenTofu).

## Scope Boundaries

**In scope for Phase 4:**
- `bootstrap` — idempotent S3 bucket + DynamoDB table creation for the project's OpenTofu state backend.
- `release <env>` for elastic foundation — SSM push → ECS RunTask migration → `tofu apply`.
- `migrate <env>` for elastic foundation (`stage`/`prod`) — standalone ECS RunTask of the migration task definition, without a full `tofu apply`.
- `AWSClient` abstraction parallel to `DockerClient`/`GitClient`. Implementation uses `boto3`.
- `OpenTofuRunner` — function-level abstraction parallel to the ansible runner.
- OpenTofu CLI + AWS CLI + `boto3` added to the image.
- **Six Phase 1 elastic HCL emitter patches** — Phase 4 cannot ship until these are fixed because the emitted HCL would fail at `tofu validate` or `tofu apply`:
  1. Block-attribute formatting (no semicolons inside `filter`, `ingress`, `fixed_response`, `redirect` blocks).
  2. Fargate `(cpu, memory)` pair validation — must round/validate to AWS's allowed combinations.
  3. Ephemeral storage floor — minimum 21 GiB on Fargate; fail loudly below.
  4. `$[VAR]` → ECS `secrets[]` block translation, not literal env-var values.
  5. RDS password handling — pull from SSM via `data "aws_ssm_parameter"`, not literal `$[POSTGRES_PASSWORD]`.
  6. Listener rule `host_header.values` — use `${env_subdomain}`, not the env name.
- Elastic-fixture extensions for end-to-end validation.

**Explicitly NOT in scope:**
- Rollback (`docex rollback`) — doctrine-deferred.
- Observability — doctrine-deferred.
- Multi-region elastic — doctrine pins to `us-east-1`.
- IAM role provisioning beyond what OpenTofu manages — that's the operator's responsibility per the doctrine.
- Multi-account AWS — one account per project per the doctrine.
- External-secret rotation handling — doctrine explicitly clobbers `.env` values on each release.
- Anything fixed-foundation-only that was settled in Phases 1-3.

## What Phase 3 Already Provides

Phase 3 shipped these pieces Phase 4 leans on:

- `DockerClient`, `GitClient`, and the `AnsibleRunner` function. Phase 4 adds AWS + OpenTofu in the same shape.
- `docex.pipeline.release.run_release(ctx, ...)` — Phase 3 implemented the fixed branch; Phase 4 implements the elastic branch within the same function (the function already dispatches on foundation).
- `docex.orchestrate.migrate.run_migrate` — Phase 3 implemented the fixed stage/prod path via ansible `--tags migrate`. Phase 4 implements the elastic stage/prod path via ECS RunTask.
- The Phase 1 elastic HCL emitter, which produces structurally-informative but **not deployable** HCL. Phase 4 replaces the broken parts and adds the SSM data sources / ECS secrets blocks.
- `tests/fixtures/sample_project_elastic/` — exists but minimal. Phase 4 extends it with a real `core/api/` tree (or symlinks one in from `sample_project/`).

## Step-by-Step Implementation

### Step 1: Update Dockerfile — opentofu + aws CLI + boto3

Phase 4's image needs:
- **OpenTofu CLI** (pin a specific version; `tofu` 1.8.x family or whatever is current). Install from the official tarball or a vendored deb; the project doesn't dictate.
- **AWS CLI v2** — useful for debugging from inside the container; not strictly required by docex code (which uses boto3), but the operator will appreciate it being present.
- **`boto3`** + **`botocore`** added to `pyproject.toml`'s dependencies. Pin both to specific versions.

Update `pyproject.toml`'s version + `docex.__version__` to `0.4.0`. Update every stub message that references the version. Rebuild and confirm `tofu version`, `aws --version`, and `python3 -c "import boto3; print(boto3.__version__)"` all work inside the new image.

### Step 2: `AWSClient` abstraction

Create `src/docex/aws/` parallel to `src/docex/docker/` and `src/docex/git/`:

```
src/docex/aws/
├── __init__.py
├── client.py             (AWSClient Protocol)
└── boto3_client.py       (Boto3AWSClient; the ONLY module permitted to import boto3)
```

The Protocol covers every AWS operation Phase 4 needs:

```python
class AWSClient(Protocol):
    def caller_identity(self) -> str: ...  # AWS account ID
    # SSM
    def ssm_put_parameter(self, name: str, value: str, *, overwrite: bool = True) -> None: ...
    # S3 (bootstrap)
    def s3_bucket_exists(self, name: str) -> bool: ...
    def s3_create_bucket(self, name: str, *, region: str) -> None: ...
    def s3_enable_versioning(self, name: str) -> None: ...
    def s3_enable_encryption(self, name: str) -> None: ...
    def s3_block_public_access(self, name: str) -> None: ...
    # DynamoDB (bootstrap)
    def ddb_table_exists(self, name: str) -> bool: ...
    def ddb_create_locking_table(self, name: str) -> None: ...
    # ECS (release migrations)
    def ecs_register_task_definition(self, family: str, definition: dict) -> str: ...  # returns ARN
    def ecs_run_task(self, *, cluster: str, task_definition: str, subnets: list[str], security_groups: list[str]) -> str: ...  # returns task ARN
    def ecs_wait_for_task(self, *, cluster: str, task_arn: str, timeout_s: int = 600) -> int: ...  # returns container exit code
    # Lookups (release-time HCL prerequisites)
    def get_default_subnets(self, *, vpc_id: str, tier: str) -> list[str]: ...  # tier in {"public", "private"}
    def get_security_group_id(self, *, vpc_id: str, name: str) -> str: ...
    def get_ecs_cluster_arn(self, name: str) -> str: ...
```

Same chokepoint rule as Phases 2-3: `boto3` is imported ONLY from `boto3_client.py`. Add new errors to `errors.py`: `AWSCredentialsMissing`, `BootstrapFailed`, `SSMPushFailed`, `ECSTaskFailed`, `TofuValidateFailed`, `TofuApplyFailed`.

The `caller_identity()` method returns the account ID — needed for SSM ARNs and ECR URL derivation. Sources from `sts.GetCallerIdentity`.

### Step 3: `OpenTofuRunner` — function-level abstraction

Same pattern as the ansible runner. Single function per operation:

```python
# src/docex/opentofu/__init__.py

def tofu_init(workdir: Path) -> int: ...
def tofu_validate(workdir: Path) -> int: ...
def tofu_plan(workdir: Path, *, out_path: Path | None = None) -> int: ...
def tofu_apply(workdir: Path, *, plan_file: Path | None = None, auto_approve: bool = False) -> int: ...
```

Implementation in `src/docex/opentofu/subprocess_runner.py`. Only module permitted to `import subprocess` for tofu.

The runner expects AWS creds in the environment (the docex container inherits `~/.aws/credentials` via the shim mount). It does not manage credential storage.

For `apply`, default `auto_approve=False` is footgun-resistant; the dispatcher passes `auto_approve=True` for the release flow. Document this in the function docstring.

### Step 4: Patch the elastic HCL emitter

This is the largest Phase 4 step. The Phase 1 elastic emitter produces HCL that fails `tofu validate` and would fail `tofu apply` in multiple ways. Fix each:

#### 4a — Block-attribute formatting

In `src/docex/emit/templates/main.tf.j2` (and any helper), replace inline-semicolon blocks like:

```hcl
filter { name = "vpc-id"; values = [data.aws_vpc.project.id] }
ingress { from_port = 443; to_port = 443; protocol = "tcp"; cidr_blocks = ["0.0.0.0/0"] }
fixed_response { content_type = "text/plain"; status_code = "404"; message_body = "not found" }
redirect { port = "443"; protocol = "HTTPS"; status_code = "HTTP_301" }
```

with one-attribute-per-line form. HCL parses semicolons-as-separators in some contexts but the patterns above all fail `tofu validate`. Use:

```hcl
filter {
  name   = "vpc-id"
  values = [data.aws_vpc.project.id]
}

ingress {
  from_port   = 443
  to_port     = 443
  protocol    = "tcp"
  cidr_blocks = ["0.0.0.0/0"]
}
```

Verify by running `tofu validate` (via the Phase 4 OpenTofuRunner) against compiled output for the elastic fixture in tests.

#### 4b — Fargate (cpu, memory) pair validation

AWS Fargate accepts only specific `(cpu, memory)` combinations:

| CPU (Fargate units) | Valid memory range (MiB) |
| ------------------- | ------------------------ |
| 256 (0.25 vCPU) | 512, 1024, 2048 |
| 512 | 1024, 2048, 3072, 4096 |
| 1024 | 2048..8192 (1024 increments) |
| 2048 | 4096..16384 (1024 increments) |
| 4096 | 8192..30720 (1024 increments) |
| 8192 | 16384..61440 (4096 increments) |
| 16384 | 32768..122880 (8192 increments) |

The Phase 1 emitter does `2GB → 1907 MiB` which is **invalid**.

Add `_fargate_pair(cpu: float, memory: str) -> tuple[int, int]` to the compiler (or to a new `src/docex/cicl/fargate.py`). It:
1. Converts `cpu` to Fargate units (multiply by 1024, round to nearest valid: 256/512/1024/2048/4096/8192/16384).
2. Converts `memory` string (e.g. `"2GB"`) to a target MiB value.
3. Looks up the valid memory list for the chosen CPU.
4. Rounds the target memory **up** to the next valid value.
5. Returns `(fargate_cpu, fargate_memory_mib)`.

If the requested combination would exceed the maximum (e.g. 1 vCPU + 9000 MB), raise a `ValidationError` at compile time pointing at the service.

Update the emitter to call this and use the validated values in the task definition.

#### 4c — Ephemeral storage floor

Fargate's ephemeral storage minimum is **21 GiB** and maximum is **200 GiB**. The Phase 1 emitter rounds `20GB → 19 GiB`, which is below the floor.

Add a `ValidationError` at compile time if a user requests `disk:` below 21 GiB on an elastic-stage/prod env. Document this in the cicl.md resources section (it's already partly there — confirm and extend).

If `disk:` is omitted on a Fargate service, omit `ephemeral_storage` from the task definition entirely (accepting Fargate's 21 GiB default). The Phase 1 emitter did this correctly; just make sure it still works after the `disk:` rounding logic is added.

#### 4d — `$[VAR]` → ECS `secrets[]` block

The Phase 1 emitter emits literal `"$[POSTGRES_USER]"` strings into ECS container_definitions. Per transfer_tables.md § Substitution Grammar, on elastic these must translate to a `secrets[]` block referencing SSM Parameter Store paths.

For each core service, the emitter walks the service's env block (after magic-ref resolution) and partitions entries:
- Entries whose value is a literal string (no `$[...]`) go to `environment[]`.
- Entries whose value contains `$[VAR]` go to `secrets[]` with `valueFrom = "arn:aws:ssm:${region}:${account_id}:parameter/${project}/${env}/${VAR}"`.

The emitter needs the account ID at compile time. Three options, in order of preference:
1. Emit a `data "aws_caller_identity" "current"` block in the HCL and reference its `.account_id` attribute. Tofu resolves it at apply time. No compile-time AWS calls needed. **Use this.**
2. Resolve via `boto3.client("sts").get_caller_identity()` at compile time. Requires AWS creds for compile, breaks offline compiles.
3. Require the operator to set an `aws_account_id` field in `project.yml`. Doctrinally clean but adds toil.

Option 1 keeps compile pure. The resulting `secrets[]` entry looks like:

```hcl
secrets = [
  {
    name      = "POSTGRES_USER"
    valueFrom = "arn:aws:ssm:us-east-1:${data.aws_caller_identity.current.account_id}:parameter/${project}/${env}/POSTGRES_USER"
  }
]
```

#### 4e — RDS password via SSM data source

Currently `password = "$[POSTGRES_PASSWORD]"` ends up as a literal string in the HCL. Instead emit:

```hcl
data "aws_ssm_parameter" "${name}_password" {
  name            = "/${project}/${env}/POSTGRES_PASSWORD"
  with_decryption = true
}

resource "aws_db_instance" "${name}" {
  ...
  username = data.aws_ssm_parameter.${name}_username.value
  password = data.aws_ssm_parameter.${name}_password.value
  ...
}
```

(Same pattern for `username`.) Update the postgres engine's transfer-table `defaults.elastic` block to use the SSM data source references rather than literal `$[VAR]` substitutions. The data source name should be the service name + the SSM key suffix to avoid collisions if multiple databases live in the same project.

The release flow puts SSM parameters BEFORE running `tofu apply` (per release_mechanism.md), so the data sources resolve correctly by the time tofu evaluates them.

#### 4f — Listener-rule host_header

Currently `host_header.values = ["prod"]`. Per the doctrine, this should be `["${env_subdomain}"]` (e.g. `["www.example.com"]` for prod, `["stage.example.com"]` for stage). Fix in the template.

#### 4g — Sanity test

After all six fixes, the compiled elastic HCL for the sample fixture should pass `tofu init && tofu validate` in a clean directory with no real AWS calls. **This is the acceptance gate for Step 4.** Add a unit test that runs `tofu validate` against the compiled output and asserts exit 0. Skip the test on hosts without `tofu` in PATH; flag the dependency in `tests/README.md`.

### Step 5: Update transfer tables for elastic correctness

The `postgres/elastic` defaults block needs the SSM data source references introduced in 4e. The `redis/elastic` (ElastiCache) provides block needs review — Phase 1 may have left it sparse.

Audit every engine entry in `tables/roles/*.yml`:
- For each backing service engine that has `env:` keys (e.g. `POSTGRES_USER`, `POSTGRES_PASSWORD`): confirm the `provides:` block translates these via SSM on elastic.
- For each engine that exposes URL-shaped parts: confirm the elastic template uses `@<expr>` correctly for provider-allocated values (e.g. `@aws_db_instance.${name}.endpoint`).
- For `cache/redis/elastic` (ElastiCache): set `engine = "redis"`, `node_type = "cache.t3.micro"` defaults; expose `host` via `@aws_elasticache_cluster.${name}.cache_nodes[0].address`.

Document each engine's elastic-side translation in a top-of-file comment.

### Step 6: `bootstrap`

`src/docex/pipeline/bootstrap.py` per [elastic_bootstrap.md](../../doctrine/infrastructure/specifics/elastic_bootstrap.md).

```python
def run_bootstrap(ctx: ProjectContext, aws: AWSClient) -> int:
    if ctx.infra is not None and ctx.infra.foundation == "fixed":
        print("docex bootstrap is a no-op for fixed-foundation projects.")
        return 0
    project = ctx.project.name
    region = "us-east-1"  # CICL simplification — only region we support
    bucket = f"{project}-tofu-state"
    table = f"{project}-tofu-locks"

    # S3 bucket — idempotent
    if not aws.s3_bucket_exists(bucket):
        aws.s3_create_bucket(bucket, region=region)
        print(f"bootstrap: created S3 bucket {bucket}")
    else:
        print(f"bootstrap: S3 bucket {bucket} already exists")
    aws.s3_enable_versioning(bucket)         # idempotent
    aws.s3_enable_encryption(bucket)         # idempotent
    aws.s3_block_public_access(bucket)       # idempotent

    # DynamoDB lock table — idempotent
    if not aws.ddb_table_exists(table):
        aws.ddb_create_locking_table(table)
        print(f"bootstrap: created DynamoDB table {table}")
    else:
        print(f"bootstrap: DynamoDB table {table} already exists")

    print(f"bootstrap: project {project!r} state backend ready (region={region}).")
    return 0
```

The idempotence pattern matches elastic_bootstrap.md exactly: every operation is safe to re-run.

If any AWS call raises an exception, surface it through `BootstrapFailed` with the underlying message. Re-running the command later should reconcile any partial state.

### Step 7: `release <env>` — elastic

In `src/docex/pipeline/release.py`, replace the existing elastic stub with the real implementation per [release_mechanism.md § Elastic Foundation: OpenTofu](../../doctrine/infrastructure/specifics/release_mechanism.md#elastic-foundation-opentofu) and the migration section.

Sequence:
1. Validate `env in {"stage", "prod"}` (already done in Phase 3).
2. Confirm `ctx.infra.foundation == "elastic"` — Phase 3's fixed branch already handles the other case.
3. `ensure_compiled(ctx)`.
4. **Push secrets to SSM:** read `infra/secrets/<env>.env`, parse `KEY=value` lines, push each to `/${project}/${env}/${KEY}` as a `SecureString`. Use `aws.ssm_put_parameter(name, value, overwrite=True)`. If any push fails, abort before touching ECS or tofu.
5. **Run migrations via ECS RunTask** (call `run_migrate(ctx, docker, env=env, aws=aws)` which dispatches to the elastic branch built in Step 8). Abort the release if any migration task exits non-zero.
6. **`tofu init` + `tofu apply --auto-approve`** in `infra/output/<env>/`. The OpenTofuRunner handles streaming output; surface the exit code.

The `tofu init` step is idempotent and cheap on subsequent runs; always run it before apply to ensure the state backend is wired up (the bootstrap created the bucket/table; init wires the local working dir to it).

### Step 8: `migrate <env>` — elastic

In `src/docex/orchestrate/migrate.py`, replace the existing elastic stub for stage/prod with the real implementation. Sequence per [release_mechanism.md § Migrations § Elastic-foundation mechanism](../../doctrine/infrastructure/specifics/release_mechanism.md#elastic-foundation-mechanism):

1. For each `services_with_schema(ctx)` core service:
   a. Construct the migration task definition's family name: `${project}_${env}_${svc}_migrate`.
   b. Register a new task-definition revision via `aws.ecs_register_task_definition(family, definition)`. The definition mirrors the service's main task definition but with `command = ["/service/migrate.sh"]`. The compiler can emit the migration definition as a `aws_ecs_task_definition` resource so it gets created on `tofu apply`; alternatively the AWSClient registers it directly. **Decision: emit it as a tofu resource so it lives in state.** Then `release` (which always runs `tofu apply` BEFORE invoking migrate when called directly via `docex migrate`) ensures it exists.
2. Look up the env's ECS cluster, private subnets, and internal security group via `aws.get_default_subnets / get_security_group_id / get_ecs_cluster_arn`. These were emitted with deterministic names by the compiler.
3. Call `aws.ecs_run_task(...)` for the migration task definition. Capture the task ARN.
4. Poll `aws.ecs_wait_for_task(...)` until the task exits. The wait helper uses `ecs.describe_tasks` and returns the container's exit code. Timeout default 10 minutes; raise `ECSTaskFailed` on timeout or non-zero exit.
5. Repeat for each schema-owning service. First failure aborts the rest.

Use `run_one_shot=False` semantics — the task lives in state, but each invocation creates a fresh run. Don't try to deregister old revisions; ECS handles that automatically based on the task definition's revision history.

### Step 9: Update dispatcher

In `src/docex/__main__.py`:
- Replace the `bootstrap` stub with the real handler, passing a `Boto3AWSClient` instance.
- The existing `release` and `migrate` handlers automatically pick up Phase 4 behavior since they dispatch on foundation. Verify by tracing the code path for an elastic project.
- Update the usage banner: Phase 4 commands move from "planned" to "implemented." Bootstrap is the only Phase 4 command in the table.

Bump version-stub messages to reference `docex 0.4.0`. **There are no more stubs** — every command is implemented. The dispatcher's stub-emitting code can be retired (or kept as a guard for unknown commands, which already returns code 64).

### Step 10: Extend the elastic fixture

`tests/fixtures/sample_project_elastic/` currently has only `project.yml` and `infra/infra.yml`. For Phase 4 acceptance, add either:

- (Recommended) A symlinked `core/api/` pointing at the fixed fixture's tree, so both fixtures share one service definition. Document the symlink in the fixture README so a future developer doesn't break the link by accident.
- Or a full copy if symlinks would complicate things on certain hosts.

The elastic fixture also needs an `infra/contracts/api.openapi.yml` for the Phase 3 `check` gate (can also be a symlink).

Add `infra/secrets/dev.env`, `test.env`, `stage.env`, `prod.env` (placeholder values; gitignored in real projects). These are needed by the SSM push step in `release`.

The elastic fixture does NOT need `infra/deploy_creds/` — elastic projects authenticate via `~/.aws/credentials`, not SSH keys.

### Step 11: Unit tests

Under `tests/unit/`, add one test file per Phase 4 command + emitter tests for the HCL fixes:

- `test_pipeline_bootstrap.py` — uses `FakeAWSClient` that records every call. Asserts:
  - Idempotent: re-running with existing bucket/table is no-op except for the always-run reconciliation (versioning, encryption, block-public-access).
  - Fixed-foundation projects return 0 with the "no-op" message.
  - Failed S3 calls surface as `BootstrapFailed`.
- `test_pipeline_release_elastic.py` — asserts SSM push runs before tofu apply, migration ECS RunTask runs between SSM and apply, tofu apply runs last, any earlier failure aborts.
- `test_orchestrate_migrate_elastic.py` — asserts ECS RunTask per schema-owning service, polls for completion, first failure aborts the rest.
- `test_hcl_emitter.py` (new) — asserts the six elastic emitter fixes:
  - No semicolons in `filter`/`ingress`/`fixed_response`/`redirect` blocks.
  - Fargate `(cpu, memory)` pair validation maps `cpu=1.0, memory=2GB` → `(1024, 2048)`.
  - `disk: 20GB` on elastic raises `ValidationError` (below 21 GiB floor).
  - `$[VAR]` env entries appear in `secrets[]` block with SSM ARN, not in `environment[]`.
  - RDS resource uses `data.aws_ssm_parameter.<name>_password.value` for password.
  - `aws_lb_listener_rule.condition.host_header.values` equals the env subdomain.

Add `FakeAWSClient` to `tests/conftest.py` alongside the other fakes. Same recorder pattern as `FakeDockerClient` / `FakeGitClient`.

### Step 12: Integration tests

Under `tests/integration/`, add (all gated by `@pytest.mark.integration`):

- `test_hcl_validate_real.py` — compiles the elastic fixture into a temp dir, runs `tofu init` (offline mode if possible; otherwise skip when no AWS creds present) + `tofu validate`. Asserts exit 0. This is the regression check that catches HCL syntax/structure errors.
- `test_bootstrap_localstack.py` — **optional**. Uses LocalStack if `LOCALSTACK_ENDPOINT` env var is set; skipped otherwise. Runs `docex bootstrap` and asserts the S3 bucket + DynamoDB table appear in LocalStack's mocked services.

**Do NOT add `test_release_real.py`** or `test_migrate_elastic_real.py` — these would require a real AWS account with billable resources. Manual smoke test (Step 13) is the acceptance for the real-AWS path.

### Step 13: End-to-end smoke test

The Phase 4 acceptance gate. Manually:

1. Rebuild the image: `docker build -t docex:0.4.0 .`
2. Bump the fixture's `project.yml` to `docex_version: "0.4.0"`.
3. **Tofu validate path** (no real AWS needed): copy the elastic fixture to a fresh dir. Run `./bin/docex compile`. Confirm `infra/output/stage/main.tf` and `infra/output/prod/main.tf` exist. Run `tofu -chdir=infra/output/prod init -backend=false && tofu -chdir=infra/output/prod validate`. Confirm exit 0.
4. **Real AWS path** (requires an AWS account with billing enabled — do at your own discretion):
   a. Configure `~/.aws/credentials` with a dedicated project IAM role.
   b. Run `./bin/docex bootstrap`. Confirm:
      - `aws s3 ls | grep <project>-tofu-state` shows the bucket.
      - `aws dynamodb list-tables | grep <project>-tofu-locks` shows the table.
      - Re-running is a no-op with reconcile messages.
   c. Populate real-ish values in `infra/secrets/stage.env`.
   d. Containerize: set up a local registry or use ECR (`docex` will derive ECR URL via `data.aws_caller_identity`). Run `./bin/docex containerize`.
   e. Run `./bin/docex release stage`. Confirm:
      - SSM parameters created under `/<project>/stage/`.
      - ECS migration task ran and exited 0.
      - `tofu apply` created the VPC resources, ALB, ECS service, RDS instance.
      - The deployed app responds at `https://stage.<domain>/health` returning the version.
   f. Run `./bin/docex stagetest`. Confirm the smoke test passes.
   g. Repeat for prod (`./bin/docex release prod`).
   h. **Teardown:** `tofu -chdir=infra/output/prod destroy` then `tofu -chdir=infra/output/stage destroy`. The bootstrap'd S3 bucket and DynamoDB table can be deleted manually if cleanup matters.
5. Stubs: there should be none left. Confirm `docex bogus` returns exit 64 and the usage banner lists every Phase 1-4 command under "implemented."

If step 3 succeeds, **Phase 4 is functionally complete**. Step 4 is operator-dependent; if you have no AWS credentials handy, step 3 is sufficient acceptance for the doctrine — the HCL is structurally valid and the orchestration is exercised end-to-end by unit tests.

## Things to Avoid

- **Don't bypass `AWSClient` or the tofu runner.** Same rule as Phases 2-3 — every subprocess and SDK call goes through the chokepoint. `boto3` is imported ONLY from `boto3_client.py`. The unit-test story depends on it.
- **Don't shell out to `aws` CLI from Python.** Use boto3 throughout. The aws CLI is in the image for operator debugging, not for docex's code path.
- **Don't pre-compute the AWS account ID at compile time.** Emit `data "aws_caller_identity" "current"` in the HCL and let tofu resolve at apply time. Keeps compile pure (no AWS creds needed for compile).
- **Don't try to handle multi-region or multi-account in this phase.** The doctrine pins to `us-east-1` and one account per project. Adding either would be a doctrine change, not a docex change.
- **Don't silently round Fargate `(cpu, memory)` to surprising values.** If the user requests an invalid combination, fail at compile time with a clear error pointing at the service and showing the valid options. Doctrine prefers loud failures.
- **Don't roll back automatically on `tofu apply` failure.** OpenTofu's state file is authoritative; a partial apply leaves resources in a state the operator can inspect with `tofu plan`. Auto-rollback would obscure the partial state.
- **Don't add a separate `docex update-secrets` command.** Updating SSM is part of `release` — the doctrine's "single push initiates the deploy" property depends on this. A standalone secrets-only push is a temptation that breaks doctrine's clobbering invariant (release would still overwrite the manual push on next run).
- **Don't pre-implement rollback in Phase 4** even partially. Doctrine explicitly defers it.
- **Don't break the Phase 1-3 regression tests.** The Step 4 HCL emitter changes touch the elastic template; the existing `test_compile_elastic_produces_main_tf` test only checks for file existence, not content. Confirm tofu validate passes; that's the real gate.

## What Happens After Phase 4

Phase 4 is the last phase the design proposal calls for. After Phase 4 ships, `docex` is the complete executor of the doctrine as defined: every command in `docex.md` works for both foundations, the manual CI/CD chain runs end-to-end on real infrastructure, and projects can author and deploy entirely through `docex` invocations.

**Beyond Phase 4** lives doctrine work that this doctrine version explicitly defers — observability, rollback, multi-machine fixed-foundation, automated CI/CD triggers (PR-driven pipelines), and externally-rotated secret handling. Each of those would be a new doctrine version with corresponding `docex` work. The phasing structure established by these four implementation docs scales naturally to those future additions.
