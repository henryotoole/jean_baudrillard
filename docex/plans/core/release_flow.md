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
