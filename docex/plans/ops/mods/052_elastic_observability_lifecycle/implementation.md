# Mod 052 — Implementation Steps

Fresh-context guide for [`overview.md`](./overview.md). Two **independent** elastic-only workstreams: **E** (ECS logs → CloudWatch) and **F** (safe elastic teardown). All Mod 052 doctrine is **already done and committed** — do **not** edit `doctrine/**`.

**Plan context:** feeds a single later `1.1.0` cut. **Do NOT bump the version** (`pyproject.toml`/`__init__.py` stay `1.0.3`); only append to `CHANGELOG.md` `[Unreleased]`. Do **not** commit/tag/`docker build`. Leave changes uncommitted. Don't touch `engineer/tmp/*` or `plans/core` / `plans/advances`. `pytest` directly (no `python` on PATH; no venv).

Read the actual current code of every file before editing. Match surrounding idiom. New client/runner methods follow the three-place pattern (Protocol + concrete + conftest fake) where applicable.

---

## Gap E — `logConfiguration` → CloudWatch (elastic)

All in `src/docex/emit/hcl.py::render_task_definition` (emits both the main task-def and the `_migrate` variant) + its template, and `templates/main.tf.j2`.

1. **`logConfiguration` on every container** in each task definition — the application container, the **OTel sidecar**, and the **`_migrate`** container:
   ```hcl
   logConfiguration = {
     logDriver = "awslogs"
     options = {
       "awslogs-group"         = aws_cloudwatch_log_group.<svc>.name
       "awslogs-region"        = "us-east-1"
       "awslogs-stream-prefix" = "<app|otelcol|migrate>"
     }
   }
   ```
   One log group per `(env, service)`; the three containers share it, distinguished by `awslogs-stream-prefix` (`app` / `otelcol` / `migrate`).
2. **Emit `aws_cloudwatch_log_group` per service** in the env-tier HCL:
   ```hcl
   resource "aws_cloudwatch_log_group" "<svc>" {
     name              = "/<project>/<env>/<svc>"
     retention_in_days = 30
     tags = { ...managed_by = "doctrine"... }
   }
   ```
   **Critical:** the `name`'s `/<project>/<env>/` prefix must use the **same `<project>` form the task-execution-role IAM scope + SSM paths use** (raw, underscore-preserving — *not* the dns-label form), so the role's `arn:…:log-group:/<project>/<env>/*` scope actually matches. Verify against `elastic_iam.md` / how SSM paths are built.
3. The task-execution role already grants `CreateLogStream`+`PutLogEvents` (per `elastic_iam.md`) — **no IAM change**, and **do not** set `awslogs-create-group` (the role lacks `CreateLogGroup`; tofu owns the group).

**Tests (E):** assert the emitted env HCL contains a `logConfiguration` with `logDriver = "awslogs"` on all three container kinds (app, sidecar, migrate), and an `aws_cloudwatch_log_group` resource per service with `retention_in_days = 30` and the IAM-matching name prefix.

---

## Gap F — safe elastic teardown (Model X)

### F1. `tofu_destroy` runner
`src/docex/opentofu/subprocess_runner.py` — add `tofu_destroy(workdir, *, auto_approve=True, targets=None)` mirroring `tofu_apply` (same `-auto-approve` / `-target` handling, returns exit code).

### F2. New `AWSClient` methods (Protocol + `boto3_client` + conftest fake)
Keep each tight (the `boto3_client` is the only `boto3` importer — auditable surface):
- `rds_protected_instances(prefix: str) -> list[str]` — `describe_db_instances`, return identifiers (matching the project prefix) where `DeletionProtection` is True. (The env-down safety gate.)
- `ssm_delete_parameters(path_prefix: str) -> None` — delete all params under `/<project>/<env>/` (cleanup).
- `s3_delete_bucket(name: str) -> None` — empty + delete (state backend teardown).
- `ddb_delete_table(name: str) -> None` — delete the lock table.
- `ecr_repository_image_count(repository: str) -> int` (or `ecr_list_images`) — for the projinfra-down ECR pre-flight.
Add matching fakes in `tests/conftest.py` (scriptable), defaulting so existing tests are unaffected.

### F3. Elastic env teardown — `envinfra down <stage|prod>`
- `src/docex/orchestrate/down.py::run_down` — relax `assert_fixed_env` for the **down** direction. Branch:
  - dev/test (and fixed stage/prod): existing `compose_down` (unchanged).
  - elastic stage/prod: **pre-flight gate** — `aws.rds_protected_instances(<project-prefix>)`; if non-empty, print a refuse-and-report message listing each protected RDS + the resolution ("disable `deletion_protection` and re-run"), and return non-zero **without destroying anything**. Otherwise `tofu_destroy` against `infra/output/<env>/main.tf` (after `tofu_init`).
- `src/docex/__main__.py::_cmd_envinfra` — allow `down` for `stage`/`prod`; keep `up` dev/test-only with a clear error if someone runs `envinfra up stage` ("stage/prod are brought up by `docex release`").
- Determine `<project-prefix>` consistently with how env RDS instances are named (the `rds` naming policy → hyphenated `<project_dns_label>-<env>-...`). Use `compiled`/context to derive it; confirm against `render_rds_instance`'s identifier.

### F4. Project-tier teardown — elastic `projinfra down production`
- New `run_projinfra_elastic_down(ctx, aws, ...)` in `src/docex/pipeline/projinfra.py` — the inverse of `run_bootstrap`:
  1. **Refuse-if-envs-up:** for each env (`stage`, `prod`), probe `aws.ecs_cluster_exists(<project>-<env>` cluster name, policy-applied) (or other env-tier markers). If any env-tier resource exists, refuse with "tear down envs first (`envinfra down <env>`)" and return non-zero.
  2. **ECR pre-flight:** for each project ECR repo, `aws.ecr_repository_image_count`; if any non-empty, refuse-and-report ("repo `<name>` has N images; empty it and re-run").
  3. `tofu_destroy` against `infra/output/project/production/main.tf` (after `tofu_init` against the project state backend).
  4. Cleanup: `aws.ssm_delete_parameters` for the project's paths, then `aws.s3_delete_bucket` (state bucket) + `aws.ddb_delete_table` (lock table) — the state backend is the **last** thing removed (nothing tofu-managed remains).
- `src/docex/__main__.py::_cmd_projinfra` — replace the elastic `(down, production)` stub (currently prints "no automated path") with a call to `run_projinfra_elastic_down`.

**Tests (F):**
- `tofu_destroy` runner: arg-shape unit test (mirror the `tofu_apply` test).
- env-down gate: `run_down` on an elastic stage env where the fake `AWSClient` reports a protected RDS → asserts refuse-and-report message + non-zero + **no `tofu_destroy` call**; and the clean case → `tofu_destroy` invoked.
- `_cmd_envinfra` rejects `up stage` with the clear error.
- `run_projinfra_elastic_down`: refuses when an env ECS cluster exists; refuses on non-empty ECR; on the clean path, calls `tofu_destroy` then the SSM/S3/DDB cleanups in order.
- Real-AWS integration is **out of scope** for unit tests — the elastic smoke walk at the cut is the real proof.

---

## CHANGELOG (no version bump)

Append to `[Unreleased]`:
- **Added (E):** ECS task definitions now emit `awslogs` `logConfiguration` on every container (app, sidecar, migrate) → a per-env/service `aws_cloudwatch_log_group` (30-day retention); container stdout/stderr is now captured on elastic.
- **Added (F):** `docex envinfra down` now tears down elastic `stage`/`prod` env-tier (with a deletion-protection pre-flight gate), and `docex projinfra down production` automates the elastic project-tier teardown (refuse-if-envs-up + ECR/SSM/state-backend cleanup), replacing the manual `teardown.sh` path. New `tofu_destroy` runner + narrow RDS/SSM/S3/DDB/ECR `AWSClient` methods.

---

## Files expected to change

| File | Why |
| ---- | --- |
| `src/docex/emit/hcl.py` (+ `templates/main.tf.j2`) | `logConfiguration` on all containers + `aws_cloudwatch_log_group` (E) |
| `src/docex/opentofu/subprocess_runner.py` | `tofu_destroy` (F1) |
| `src/docex/aws/{client.py, boto3_client.py}` | RDS-protection / SSM-delete / S3-delete / DDB-delete / ECR-count methods (F2) |
| `src/docex/orchestrate/down.py` | elastic env teardown + RDS gate (F3) |
| `src/docex/pipeline/projinfra.py` | `run_projinfra_elastic_down` (F4) |
| `src/docex/__main__.py` | `_cmd_envinfra` (allow down stage/prod), `_cmd_projinfra` (elastic down-production) |
| `tests/conftest.py` | fake AWS methods |
| `tests/unit/…` | E emit assertions; F gate/teardown unit tests |
| `CHANGELOG.md` | `[Unreleased]` (no version bump) |

Out of scope: version bump, doctrine edits (done), promoting `teardown.sh`'s aggressive `deletion_protection`-disable into docex (stays smoke-specific), real-AWS integration tests (smoke walk covers it), retention as a tunable field (fixed 30d per the settled sub-decision).
