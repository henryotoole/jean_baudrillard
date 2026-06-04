# Release flow

How docex actually drives a containerized build into a target environment. The doctrine specifies the *what* — [`release_mechanism.md`](../../../doctrine/infrastructure/specifics/release_mechanism.md) for the foundation-specific flows, [`cicd.md § Release Step`](../../../doctrine/infrastructure/cicd.md#release-step) for the CI/CD pipeline placement. This doc covers the *how*: foundation branches, first-release vs steady-state ordering, the AWS / Ansible adapter shape, and failure modes.

The compile phase that release reads is covered separately in [`compiler.md`](./compiler.md).

## Scope

`docex release <env>` takes:

- A clean, containerized build at the project's current `project.yml` version (precondition: `docex containerize` has already pushed the image to the registry).
- The compiled output under `infra/output/<env>/` (precondition: `docex compile`).
- Operator-maintained `infra/secrets/<env>.env` (gitignored per project bootstrap).
- Foundation-specific deploy credentials — SSH key at `infra/deploy_creds/<env>` for fixed, AWS creds at `~/.aws/credentials` for elastic.

and converges the target environment to the declared desired state. Push-initiated, idempotent — re-running on a converged target produces zero changes.

`<env>` is `stage` or `prod`. The command refuses other values; `dev` and `test` are local-only via `docex up`.

## Foundation branches at the top

```python
# src/docex/pipeline/release.py
if ctx.infra.foundation == "fixed":
    return _release_fixed(...)
return _release_elastic(...)
```

The two branches share almost nothing operationally. Fixed deploys are SSH-driven Ansible plays against known hosts. Elastic deploys are AWS-API-driven through OpenTofu plus a thin layer of boto3 for the parts tofu can't model cleanly (SSM secret push, ECS `RunTask` for migrations).

The decision point is the `foundation:` field in `infra.yml`. Compile has already encoded the right output for the env into `infra/output/<env>/`: a `docker-compose.yml` + `playbook.yml` for fixed, a `main.tf` for elastic.

## Fixed-foundation flow

`_release_fixed` invokes the emitted Ansible playbook against the env's host(s):

```
docex release stage     (fixed)
└─ ansible-playbook infra/output/stage/playbook.yml -i infra/output/stage/inventory.yml
   └─ SSH to host as `deploy` user using infra/deploy_creds/stage
       ├─ docker pull <registry>/<project>/<svc>:<version>           (per core service)
       ├─ render compose.yml + .env into /opt/<project>/<env>/
       ├─ docker compose run --rm <svc>_migrate /service/migrate.sh  (per schema owner)
       └─ docker compose -f /opt/<project>/<env>/docker-compose.yml up -d
```

There is no first-release vs steady-state distinction on fixed. The playbook's tasks are idempotent (Ansible modules with `state: present` semantics); re-running on a converged host is a no-op.

Adapter: `src/docex/ansible/subprocess_runner.py` shells out to `ansible-playbook` from inside the docex container. The playbook template lives at `src/docex/emit/templates/playbook.yml.j2`; the per-service migrate task is gated by an `ansible-playbook --tags migrate` invocation when `docex migrate <env>` is called standalone (the per-task `tags:` declaration enables that).

## Elastic-foundation flow

`_release_elastic` runs AWS-API operations bracketing one or two `tofu apply` invocations:

1. **Push secrets to SSM**. Every `KEY=value` line of `infra/secrets/<env>.env` becomes `/<project>/<env>/<KEY>` as a `SecureString` parameter (encrypted with the default `aws/ssm` KMS key). The compiled HCL's ECS `secrets[]` blocks reference these by ARN. Overwrite=True per doctrine — SSM is clobbered every release. See `_push_secrets`.
2. **Detect first-release vs steady-state**. `aws.ecs_cluster_exists(apply_policy(f"{project}_{env}", ecs_policy))` — if the env's ECS cluster is absent in AWS, this is the first release of this env. The cluster name is policy-aware (mod 007); earlier versions used a literal `f"{project}-{env}"` which never matched after mod 005's naming policies landed.
3. **Branch on detection** — see [The four sequences](#the-four-sequences) below.

Adapters: `src/docex/aws/client.py` (the `AWSClient` interface) and `src/docex/aws/boto3_client.py` (the only file in docex permitted to import `boto3` — kept narrow to keep the AWS surface auditable). `src/docex/opentofu/subprocess_runner.py` shells out to `tofu`.

## The four sequences

|  | Fixed (steady-state or first) | Elastic — first release | Elastic — steady state |
| --- | ----- | ----------------------- | ---------------------- |
| 1 | ansible-playbook (everything below happens inside it) | SSM push | SSM push |
| 2 | docker pull (per core service) | tofu apply (full) | tofu apply (targeted: migration task-defs only) |
| 3 | render compose.yml + .env | run_migrate (`RunTask` per schema owner) | run_migrate (`RunTask` per schema owner) |
| 4 | docker compose run migrate (per schema owner) | — | tofu apply (full) |
| 5 | docker compose up -d | — | — |

**Why the elastic ordering differs between first-release and steady-state:**

- **First-release**: the env's ECS cluster, RDS, ALB don't exist yet. `tofu apply` must run *before* migrate, because migrate needs the cluster + RDS to exist. The transient consequence is that newly-created ECS tasks may crash-loop until the migration completes, but no users are on a first-deploy env so the window is bounded by migration runtime.
- **Steady-state**: the doctrine prefers migrate-then-apply so the rolling deploy of new application code happens *after* the schema is migrated, preserving zero-downtime (see [`release_mechanism.md § Backward-compatibility requirement`](../../../doctrine/infrastructure/specifics/release_mechanism.md#backward-compatibility-requirement)). The pre-migrate **targeted** apply (mod 008) only bumps migration task-defs — not main service task-defs — so the in-flight web/worker tasks keep serving old code during the migration window. Without that targeted apply, RunTask would pick up the previous release's revision and any current-release task-def change (image tag, env-var refs) would be invisible to migrate.

## The migration step

`src/docex/orchestrate/migrate.py:run_migrate` is the entry point. `dev` / `test` envs run migrations inline against the local stack; `stage` / `prod` dispatch by foundation:

- **Fixed** (`stage` / `prod`): re-runs the emitted ansible playbook with `--tags migrate`. The playbook's per-service migrate task does `docker compose run --rm <svc>_migrate /service/migrate.sh` against the deployed stack on the target host. Container reuses the live env vars from the rendered `.env`.
- **Elastic** (`stage` / `prod`): `_migrate_elastic` calls `aws.ecs_run_task` against the per-service migration task-def family — `apply_policy(f"{project}_{env}_{svc}_migrate", ecs)`. The task definition is doctrine-emitted alongside the main task def — same image, different command (`/service/migrate.sh` instead of the app entrypoint). After RunTask, poll `describe_tasks` until `lastStatus == STOPPED`, then read `containers[0].exitCode`. Non-zero exit aborts the release.

`services_with_schema(ctx)` in `src/docex/orchestrate/_common.py` returns the list of core services that own a database schema, derived from each backing service's `schema_owned_by` field. The doctrine forbids two services owning the same schema (a compile-time check), so this list is a clean set.

`migrate.sh` itself is **project code**, not docex code. The doctrine only mandates the exit-code contract (0 success, non-zero abort) and that the env vars match what the service uses at runtime (per the [parts-only model](../../../doctrine/infrastructure/cicl.md#provided-fields)). The project picks its tool — dbmate in the smoke projects.

## Credentials and ambient host state

`docex release` consumes credentials from well-known locations; docex does not manage credential storage. From [`credentials.md`](../../../doctrine/infrastructure/credentials.md):

| Need | Source | Used by |
| ---- | ------ | ------- |
| AWS API | `~/.aws/credentials` (or env vars / OIDC) | elastic — SSM push, RunTask, `tofu apply` |
| SSH to host | `infra/deploy_creds/<env>` private key | fixed — ansible-playbook |
| Registry pull on target | target host's `~/.docker/config.json` | fixed — `docker pull` inside the playbook |

The shim (`bin/docex`) bind-mounts all of these into the docex container so the in-container CLIs (aws, tofu, ansible, ssh) see what the operator sees. See [`masterplan.md § Docker-outside-of-Docker`](./masterplan.md#docker-outside-of-docker) for the mount model.

## Common failure modes

| What you'd see | Probable cause | Where to look |
| -------------- | -------------- | ------------- |
| `InvalidBucketName` on bootstrap (precedes release on first elastic deploy) | Project-name policy mismatch | `pipeline/bootstrap.py` / `tables/naming_policies.yml` — mod 005 fixed this |
| Migration task fails to start with `unable to retrieve secrets from ssm: context deadline exceeded` | Per-network SG missing egress | `templates/main.tf.j2` per-network SG block — mod 006 fixed this |
| Migration task exits non-zero with `dial tcp: lookup <host>:<port>:<port>: no such host` | DB host part returning `host:port` instead of host | `tables/roles/relational_db.yml` `provides.host.elastic` — mod 007 fixed this |
| Migration uses stale env vars after a doctrine-side change | LATEST task-def revision is still previous release's | mod 008 fixed this — steady-state now runs pre-migrate targeted apply |
| Release log says `ECS cluster ... not yet provisioned` on every steady-state release | First-release detector compared wrong name form | mod 007 fixed this — `apply_policy` on the probed name |
| `tofu destroy` of project tier loops on ENI detach | RDS not yet deleted (it has `deletion_protection: true`) | smoke-project `teardown.sh` step 1 disables protection (open doctrine gap re: production retirement story) |
| `RepositoryNotEmptyException` at project-tier destroy | ECR `force_delete = false` and images still present | `templates/project.tf.j2` ECR block (open gap — workaround in teardown.sh pre-purges images) |

A general rule of thumb: any error that surfaces inside an ECS task container is invisible by default — task definitions have no `logConfiguration` (a known gap; doctrine-side logging support is a planned addition). Until then, the debug technique is to hand-patch a new task-def revision with an `awslogs` log driver, RunTask it manually, and read CloudWatch.

## Where to look when changing things

| To change... | Touch... |
| ------------ | -------- |
| Foundation dispatch | `src/docex/pipeline/release.py:run_release` |
| The fixed playbook tasks | `src/docex/emit/ansible.py` + `templates/playbook.yml.j2` |
| The order/sequence of release steps | `src/docex/pipeline/release.py` (`_release_fixed`, `_release_elastic`) |
| How migrate.sh is invoked on either foundation | `src/docex/orchestrate/migrate.py` (`_migrate_stage_prod`, `_migrate_elastic`) |
| AWS API calls docex makes | `src/docex/aws/boto3_client.py` (sole importer of `boto3`) |
| SSM push semantics | `src/docex/pipeline/release.py:_push_secrets` |
| First-release vs steady-state detection | `src/docex/pipeline/release.py:_release_elastic` (`ecs_cluster_exists` probe) |
| Schema-owner discovery | `src/docex/orchestrate/_common.py:services_with_schema` |
| Migration task-def family name | `src/docex/orchestrate/migrate.py:_migration_task_family` |

For a new doctrine-prescribed step in the release flow (e.g. a pre-migrate validation, a post-migrate verification), the entry point is `_release_elastic` or `_release_fixed`. Mirror the existing helper pattern (`_do_apply`, `_do_migrate`, `_push_secrets`) — small, single-responsibility functions that the foundation branch composes.

For a new failure mode worth catching before it reaches AWS: add the check at compile time in `cicl/validate.py` rather than at release time. A compile error is always preferable to a tofu-side or AWS-side error.

## Rollback flow

How `docex rollback` drives an emergency reversion. The doctrine specifies the *what* in [`cicd.md § Rollback`](../../../doctrine/infrastructure/cicd.md#rollback); this section covers the *how*: precondition order, the worktree-at-tag mechanism, the skip-migrations parameterization on the existing release path, and dry-run semantics.

Rollback is intentionally a thin shell on top of release machinery rather than a parallel pipeline. The doctrine commits rollback to a narrow window (emergency-only, code-only, at most one minor version back), which means it can compose the existing release functions with a toggle rather than duplicate them.

### Scope

`run_rollback` takes:

- The current `ProjectContext` (on `main`, clean tree).
- `env` — `stage` or `prod`; other values raise `EnvNotSupported`.
- `target_version` — a SemVer string. Must resolve to a `v<target_version>` git tag and have core-service images present in the registry. Validated by preconditions before any state is touched.
- The same injected runners as `release` (ansible, tofu_init, tofu_apply), plus a `tofu_plan` runner for dry-run, plus `DockerClient` / `GitClient` / `AWSClient`.
- `dry_run: bool` — the only flag on the CLI surface.

and converges `<env>` to whatever the rolled-back version's `infra.yml` declares, with migrations not run. The operator's working tree, `project.yml`, and `main` are untouched on every exit path.

### Code shape

```
docex rollback <env> <target_version>
└─ run_rollback (pipeline/rollback.py)
    1. Preconditions (cheap fail-fast, then fail-aggregated image probe)
    2. git worktree add  v<target_version>  →  .docex/worktrees/rollback-<version>/
    3. run_compile(worktree_ctx)  using *current* docex
    4. Mirror gitignored creds + secrets from project_root into worktree:
         infra/deploy_creds/<env>     (SSH key for fixed)
         infra/secrets/<env>.env      (per-env secrets, both foundations)
    5. Dispatch on infra.foundation:
         fixed   → _release_fixed(worktree_ctx, skip_migrations=True, dry_run=...)
         elastic → _release_elastic(worktree_ctx, skip_migrations=True, dry_run=..., tofu_plan=...)
    6. cleanup_worktree(...) in a finally block
```

The mirror step (4) exists because the release functions read those two paths via `worktree_ctx.project_root`, but `git worktree add` does not carry gitignored files. Both paths are gitignored by doctrine bootstrap defaults. The mirror step is the complete fix; all other release inputs (compiled output, contracts, transfer tables, core service files) are tracked and follow the worktree normally.

`_release_fixed` and `_release_elastic` were extended (mod 029) with `skip_migrations` and `dry_run` kwargs — defaults `False`, so `release`'s call sites are unchanged.

### Preconditions

Order matters: cheap fail-fast first, fail-aggregated registry probe last.

| Order | Check | Failure type |
| ----- | ----- | ------------ |
| 1 | `env in {"stage", "prod"}` | `EnvNotSupported` |
| 2 | `infra/infra.yml` present | exit 1 |
| 3 | On `main` branch | `RollbackPreconditionFailed` |
| 4 | Working tree clean | `WorkingTreeDirty` |
| 5 | `v<target_version>` tag exists locally | `RollbackPreconditionFailed` |
| 6 | `validate_one_minor_back(current, target)` passes | `RollbackPreconditionFailed` |
| 7 | All core-service images at `<target_version>` present in registry | `RollbackPreconditionFailed` (full list) |

Step 7 is the only fail-aggregated check. `_missing_images` probes every core service, accumulates misses, and the caller raises with the complete list — under emergency pressure the operator benefits from one diagnostic showing the full gap, not a fail-fast first-match.

### Worktree mechanism

The worktree helpers live in `src/docex/pipeline/_worktree.py`, extracted from `check.py` in mod 029 — both commands share them:

- `worktree_path_for(project_root, slug)` → `.docex/worktrees/<slug>`. Caller composes the slug (`check-<sha>` or `rollback-<version>`).
- `make_temp_branch(prefix, ref_name)` → `docex-<prefix>/<safe_ref>-<timestamp>`. Timestamp suffix prevents collision when concurrent invocations target the same ref.
- `cleanup_worktree(...)` — best-effort teardown: force-remove, fall back to `shutil.rmtree`, prune the worktree list, delete the temp branch. Never raises.

Rollback's recipe differs from check's: no rebase, just a checkout at `v<target_version>`. The shared helpers cover the mechanical bits; the recipe lives in `run_rollback`.

### The skip-migrations toggle

The doctrine commits rollback to code-only behavior — migrations are not reversed; the rolled-back code runs against the existing (newer) schema. This works because forward migrations are already required to be backward-compatible (see [`release_mechanism.md § Backward-compatibility requirement`](../../../doctrine/infrastructure/specifics/release_mechanism.md#backward-compatibility-requirement)).

In code:

- **Fixed** with `skip_migrations=True`: `_release_fixed` passes `skip_tags=["migrate"]` to `run_playbook`. Works against the existing playbook because the per-task `tags: [migrate]` declaration was already there for `docex migrate stage/prod`; no template changes were needed.
- **Elastic** with `skip_migrations=True`: `_release_elastic` skips the first-release detector, the pre-migrate targeted `tofu apply` (mod 008), and the `_do_migrate` step. SSM push happens; a single unrestricted `tofu apply` against the recompiled HCL converges the env.

### Dry-run

`--dry-run` is symmetric across foundations: the precondition + worktree + recompile chain runs unchanged; the apply step is replaced (not augmented) with a preview; the worktree is cleaned up either way.

- **Fixed**: `ansible-playbook --check` via the new `check_mode=` kwarg on `run_playbook`. Reports would-change tasks without mutating the env.
- **Elastic**: `tofu plan` via the existing `tofu_plan` runner. **Side-effect free** — SSM is NOT pushed in dry-run mode, so the plan reflects current SSM values, not what would be pushed. Rationale: dry-run should be reversibly idempotent; SSM is a side-effect the operator may not want to commit.

### Image probes

Mod 029 added:

- `DockerClient.manifest_inspect(ref) -> bool` (fixed) — runs `docker manifest inspect <ref>`, returns True iff exit code is 0.
- `AWSClient.ecr_image_exists(repository, tag) -> bool` (elastic) — calls `ecr.describe_images(repositoryName=..., imageIds=[{"imageTag": tag}])`; returns True on success, False on `ImageNotFoundException` / `RepositoryNotFoundException`, propagates other exceptions.

Both return clean booleans so the precondition aggregator (`_missing_images` in `rollback.py`) builds the diagnostic list without exception ceremony.

### Common failure modes

| What you'd see | Probable cause | Where to look |
| -------------- | -------------- | ------------- |
| `target version 'X' is more than one minor version behind ...` | Operator tried to go further back than doctrine permits | by design — recover via fix-forward |
| `rollback aborted — image(s) missing in registry: ...` | Target version was never containerized, or registry retention dropped the tag | check containerize history; rebuild from the target tag if needed |
| `tofu apply` destroys an RDS / stateful backing service during rollback | Target version's `infra.yml` lacked that backing service; doctrine's narrow-window destroy risk | `deletion_protection: true` on stateful engines should gate; if not, the rollback was outside the narrow window — fix-forward instead |
| Dry-run on elastic shows an unexpectedly empty diff | Plan ran against current SSM (rollback doesn't push in dry-run), and other resources didn't drift either | confirm target version is actually older than current via `/health` on the deployed env |
| Fixed rollback hangs at `docker pull` of the older image | Image present in registry but unreachable from host (network or auth) | target host's `~/.docker/config.json`; same diagnostic as a regular release pull failure |

### Where to look when changing things

| To change... | Touch... |
| ------------ | -------- |
| Rollback preconditions | `src/docex/pipeline/rollback.py:run_rollback` (early portion) |
| Image-probe surface (per foundation) | `src/docex/pipeline/rollback.py:_missing_images` |
| Skip-migrations behavior on fixed | `src/docex/pipeline/release.py:_release_fixed` (the `skip_tags` branch) |
| Skip-migrations behavior on elastic | `src/docex/pipeline/release.py:_release_elastic` (the `skip_migrations` branch) |
| Dry-run behavior on elastic | `src/docex/pipeline/release.py:_release_elastic` (the `dry_run` branch) |
| Dry-run behavior on fixed | `run_playbook`'s `check_mode=` kwarg in `src/docex/ansible/subprocess_runner.py` |
| One-minor-back rule | `src/docex/pipeline/_worktree.py:validate_one_minor_back` |
| Worktree path / branch naming convention | `src/docex/pipeline/_worktree.py` |

For a new doctrine-prescribed step in rollback specifically (not in release): the seam is `run_rollback`. For a new property of "what a rollback does to the env" (e.g. a new flag on the release functions): add the parameter on `_release_fixed` / `_release_elastic` with a `False` default so the existing `release` path stays unchanged, then set it from `run_rollback`.
