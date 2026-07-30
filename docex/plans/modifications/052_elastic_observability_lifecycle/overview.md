# Mod 052 — Elastic Observability + Lifecycle (Gaps E, F)

Fourth and final mod of the post-shape-overhaul advance (049–052), feeding the single `1.1.0` minor cut. Two **independent** elastic-only workstreams: **E** (ECS container logs → CloudWatch) and **F** (automated, safe elastic teardown). This is the heaviest mod of the advance — both gaps carry multi-file doctrine touches and Gap F adds new `tofu_destroy` + AWS primitives.

No per-mod cut, no version bump — accumulates under `CHANGELOG.md`'s `[Unreleased]`.

---

## Gap E — ECS task definitions emit no `logConfiguration`

**Symptom:** container stdout/stderr on elastic is invisible — no CloudWatch, no sink. A silently-failing worker or a migration whose error lives in stdout means hand-patching a task-def with `awslogs` and `RunTask`-ing it by hand.

**Design — settled this session** (recorded in the advance Gap E entry). The reframe: this is the **Class-2 diagnostic-stdout** path (crashes, pre-SDK-init output, `migrate.sh`), distinct from Class-1 SDK telemetry (which already flows app → OTel sidecar → HyperDX). Class-2 goes to **CloudWatch via `awslogs`** — the doctrine already half-committed to this (`elastic_iam.md` grants the log perms; the emit just never wired it — confirmed: no `logConfiguration` / `aws_cloudwatch_log_group` exists in `hcl.py` today).

**docex change (`src/docex/emit/hcl.py`):**
- Emit `logConfiguration { logDriver = "awslogs", options = {...} }` on **every** container definition in `render_task_definition` — the app container, the **OTel sidecar**, and the **`_migrate`** container (the migration-stdout case is the headline symptom). Points at the explicit log group below.
- Emit a new **per-env `aws_cloudwatch_log_group`** resource — `/<project_dns_label>/<env>/<service>` (or a per-env group), with `retention_in_days` + `managed_by = "doctrine"` tag, torn down with the env. **Not** `awslogs-create-group=true` — the task-execution role grants `CreateLogStream`+`PutLogEvents` but **not** `CreateLogGroup`, so tofu must own the group (this also gives retention + tagging + clean teardown, dovetailing with Gap F).

**Doctrine touches (Gap E):**
- `telemetry_infra.md` — new subsection: Class-2 stdout → `awslogs`→CloudWatch; explicit per-env log group + retention; the Class-1/Class-2 split.
- `practices/logging.md` — **author** the dangling `§ With Respect to Telemetry` section (referenced by `telemetry_infra.md` but absent): route app telemetry via the OTel SDK; reserve stdout for Class-2; see dev telemetry via the sidecar `debug` exporter (do **not** mirror OTel to app stdout — would double into CloudWatch). Draw the Class-1/Class-2 line so the `basicConfig`→stderr stub doesn't reintroduce duplication.
- `projinfra/elastic_iam.md` — reconcile the drift: it claims per-env log groups are emitted; make that true.
- **Open sub-decision (deferred to impl):** retention value — fixed default (e.g. 30 days) vs operator-tunable via an `infra.yml` field. Lean fixed-default unless a tuning need is concrete (a field expands the CICL surface + needs validation).

---

## Gap F — automated, safe elastic teardown (Model X, full scope)

**Symptom:** `docex projinfra down production` on elastic is a stub ("no automated path; run `teardown.sh` manually"). And there's **no elastic env-teardown at all** — `docex down` is dev/test-only (`assert_fixed_env`). So an elastic production side can only be retired by hand via the bespoke `teardown.sh`.

**Design decisions (settled this session):**
1. **Model X** — extend **`envinfra down`** to all envs. `envinfra up` stays dev/test-only; `envinfra down` now also tears down elastic `stage`/`prod` env-tier (via `tofu destroy` of `infra/output/<env>/main.tf`). The asymmetry is principled: bringing an env *up* needs a versioned build (so stage/prod-up is `release`'s job), but teardown is build-agnostic, so `down` can be uniform.
2. **Safe-by-default stateful gate** — docex **never** disables a protection itself. A **pre-flight scan** refuses *before destroying anything*, reporting the complete list of blockers; the operator deliberately clears them (out-of-band) and re-runs. No `--force` flag.
3. **Layered ordering** — `projinfra down production` **refuses if any env-tier resources are still up**; envs come down first (`envinfra down stage`, `envinfra down prod`), then `projinfra down production`.

**The teardown sequence becomes:** `envinfra down prod` → `envinfra down stage` → `projinfra down production`. (`teardown.sh` becomes a thin smoke-only wrapper that disables protection + calls these — its aggressive overrides stay *smoke-specific*, not promoted into docex.)

**Where each safety gate lives:**
- **Env-down (`envinfra down <elastic env>`):** the **RDS deletion-protection** gate. Pre-flight scan for deletion-protected stateful resources in the env; refuse with the list ("RDS `<id>` is deletion-protected — disable protection and re-run") if any. Otherwise `tofu destroy` the env `main.tf`.
- **`projinfra down production`:** refuse-if-envs-up (probe each env's ECS cluster via `ecs_cluster_exists`); then tofu-destroy the project tier + cleanup. Its blockers are project-tier — a **non-empty ECR repo** and the **tofu state bucket**. *(Open sub-decision: ECR images are reproducible build artifacts, not data — auto-purge on an explicit `down production`, or apply the same refuse-and-report gate? Lean: surface in the pre-flight like everything else for consistency; revisit if tedious. State bucket is the final deletion step, inherent to full teardown.)*

**New primitives Gap F needs (none exist today):**
- `tofu_destroy` runner in `src/docex/opentofu/subprocess_runner.py` (mirror `tofu_apply`).
- `AWSClient` additions (Protocol + `boto3_client` + conftest fake) — expands the deliberately-narrow AWS surface, so keep each method tight: an RDS deletion-protection probe (`describe-db-instances` → `DeletionProtection`, scoped by project prefix), `ssm_delete_parameters` (cleanup), `s3_delete_bucket` (state backend), `ddb_delete_table` (state lock table), and an ECR emptiness/list probe.

**docex change sites:**
- `src/docex/orchestrate/down.py::run_down` — branch by foundation/env: dev/test → `compose_down` (unchanged); elastic stage/prod → RDS-protection pre-flight gate + `tofu destroy` of the env `main.tf`. Relax `assert_fixed_env` for the `down` direction.
- `src/docex/__main__.py::_cmd_envinfra` — allow `down` for `stage`/`prod` (keep `up` dev/test-only, with a clear error if someone tries `envinfra up stage`).
- `src/docex/__main__.py::_cmd_projinfra` + a new `run_projinfra_elastic_down` (in `pipeline/projinfra.py`, inverse of `run_bootstrap`) — replace the stub: refuse-if-envs-up, project-tier `tofu destroy`, ECR + SSM + state-backend cleanup.

**Doctrine touches (Gap F):**
- `docex.md § envinfra` — `down` now covers all envs (dev/test locally; stage/prod via `tofu destroy` on elastic); `up` stays dev/test-only. State the asymmetry + its root cause (up needs a build).
- `docex.md § projinfra` (+ `specifics/projinfra/projinfra.md`) — `down production` on elastic: refuse-if-envs-up, project-tier teardown, the safe-by-default stateful gate.
- A teardown-ordering note where the layering is documented (preinfra→projinfra→envinfra inverse).

---

## Doctrine status across this mod

| Gap | Doctrine | Status |
| --- | --- | --- |
| E | `telemetry_infra.md`, `practices/logging.md` (author § With Respect to Telemetry), `projinfra/elastic_iam.md` | **pending — draft for approval** (design recorded) |
| F | `docex.md` (envinfra + projinfra), `projinfra/projinfra.md` | **pending — draft for approval** |

Per `docex_process.md` (doctrine-first), I'll draft all of this for operator approval and make the doctrine edits **before** `implementation.md`. Given the surface, expect to review the wording in a couple of focused passes (E's telemetry/logging cluster, then F's command-semantics cluster).

---

## What lands in this mod (docex code)

| Change | File(s) |
| ------ | ------- |
| `logConfiguration` on app/sidecar/migrate containers + per-env `aws_cloudwatch_log_group` (E) | `src/docex/emit/hcl.py` (+ `templates/main.tf.j2`) |
| `tofu_destroy` runner (F) | `src/docex/opentofu/subprocess_runner.py` |
| RDS-protection / SSM-delete / S3-delete / DDB-delete / ECR-list AWS methods (F) | `src/docex/aws/{client.py, boto3_client.py}`, `tests/conftest.py` |
| Elastic env teardown + RDS gate (F) | `src/docex/orchestrate/down.py`, `src/docex/__main__.py` (`_cmd_envinfra`) |
| `projinfra down production` elastic path (F) | `src/docex/__main__.py` (`_cmd_projinfra`), `src/docex/pipeline/projinfra.py` |
| `[Unreleased]` entries (no version bump) | `CHANGELOG.md` |

Tests: Gap E — assert `logConfiguration` on all three container kinds + the `aws_cloudwatch_log_group` resource in emitted HCL. Gap F — unit-test the RDS-protection gate (refuses + reports when protected; proceeds when not) and refuse-if-envs-up (via fake `AWSClient`); unit-test `_cmd_envinfra` rejects `up stage`; a real-AWS integration test is out of scope for unit (the elastic smoke walk at the cut is the real proof).

## Cut shape

No own cut; the **final** mod before the batched `1.1.0` cut. Both gaps are elastic-only and consequential, so the **elastic smoke walk** at cut time is the real integration proof — Gap E (CloudWatch actually receives stdout) and Gap F (the full `envinfra down → projinfra down production` teardown retires the project cleanly, replacing `teardown.sh`). The smoke walk will also exercise the deletion-protection gate (the smoke wrapper disables protection, then the docex path runs).
