# Release flow

How docex actually drives a containerized build into a target environment. The doctrine specifies the *what* — [`release.md`](../../../doctrine/infrastructure/specifics/release.md) for the foundation-specific flows, [`cicd.md § Release Step`](../../../doctrine/infrastructure/cicd.md#release-step) for the CI/CD pipeline placement. This doc covers the *how*: foundation branches, first-release vs steady-state ordering, the AWS / Ansible adapter shape, and failure modes.

The compile phase that release reads is covered separately in [`compiler.md`](./compiler.md).

## Scope

`docex release <env>` takes:

- A clean, containerized build at the project's current `project.yml` version (precondition: `docex containerize` has already pushed the image to the registry).
- The compiled output under `infra/output/<env>/` (precondition: `docex compile`).
- The three per-env category dirs — `infra/{secrets,config,tte}/<env>.env` — merged by *aggregation* into the container-facing value set (mods 080-084), not a single `<env>.env`. `secrets` and `config` are operator-maintained; `tte` is the doctrine-minted store. `infra/secrets/<env>.env` is gitignored per project bootstrap. See [`config_and_secrets.md`](../../../doctrine/infrastructure/specifics/config_and_secrets.md).
- Foundation-specific deploy credentials — SSH key at `infra/deploy_creds/<env>` for fixed, AWS creds at `~/.aws/credentials` for elastic.

and converges the target environment to the declared desired state. Push-initiated, idempotent — re-running on a converged target produces zero changes.

`<env>` is `stage` or `prod`. The command refuses other values; `dev` and `test` are local-only via `docex envinfra up`.

## Foundation branches at the top

```python
# src/docex/pipeline/release.py
if ctx.infra.foundation == "fixed":
    return _release_fixed(...)
return _release_elastic(...)
```

The two branches share almost nothing operationally. Fixed deploys are SSH-driven Ansible plays against known hosts. Elastic deploys are AWS-API-driven through OpenTofu plus a thin layer of boto3 for the parts tofu can't model cleanly (SSM secret push, ECS `RunTask` for migrations).

The decision point is the `foundation:` field in `infra.yml`. Compile has already encoded the right output for the env into `infra/output/<env>/`: a `docker-compose.yml` + `playbook.yml` for fixed, a `main.tf` for elastic.

## Required-secret precondition

Before the foundation branch, `run_release` calls `_require_secrets_present(ctx, env)` (mod 091). It reads `infra/secrets/<env>.env` and aborts — raising `RequiredSecretsUnset` — if any key in the secret manifest (core `secrets:` + backing `kind: secret` + doctrine-injected `TELEMETRY_API_KEY`) is absent or empty. This runs before any side effect (aggregation, SSM push, ansible/tofu apply), so an incomplete secret set fails fast and clearly instead of surfacing as a runtime container failure. It is **secrets-only** (TTE is docex-minted put-if-absent; config is non-secret) and **stage/prod-only** — rollback bypasses it by calling `_release_fixed`/`_release_elastic` directly. See [`config_and_secrets.md § Required-Secret Guard`](../../../doctrine/infrastructure/specifics/config_and_secrets.md#required-secret-guard).

## Fixed-foundation flow

`_release_fixed` invokes the emitted Ansible playbook against the env's host(s):

```
docex release stage     (fixed)
└─ ansible-playbook infra/output/stage/playbook.yml -i infra/output/stage/inventory.yml
   └─ SSH to host as `deploy` user using infra/deploy_creds/stage
       ├─ docker pull <registry>/<project>/<cb>:<version>            (per codebase)
       ├─ render compose.yml + .env into /opt/<project>/<env>/
       ├─ docker compose run --rm <cb>-exec /service/migrate.sh      (per schema owner)
       └─ docker compose -f /opt/<project>/<env>/docker-compose.yml up -d
```

There is no first-release vs steady-state distinction on fixed. The playbook's tasks are idempotent (Ansible modules with `state: present` semantics); re-running on a converged host is a no-op.

Before the playbook runs, docex builds the aggregate (mod 081). `ensure_tte_fixed` SSH-reads the host-authoritative `/opt/<project>/<env>/tte.env` (`SSHClient.capture`), mints any absent minted keys, and stages the resulting superset; `aggregate_fixed_prod` merges secrets + config + TTE and writes `.docex/agg/<env>.env`. The playbook then renders both `tte.env` (the store) and `.env` (the aggregate) onto the host via `--extra-vars`. Note: `docex migrate stage/prod` reads the host `.env` a prior release already rendered — the untagged copy tasks are skipped under `--tags migrate`.

Adapter: `src/docex/ansible/subprocess_runner.py` shells out to `ansible-playbook` from inside the docex container. The playbook template lives at `src/docex/emit/templates/playbook.yml.j2`; the per-codebase migrate task is gated by an `ansible-playbook --tags migrate` invocation when `docex migrate <env>` is called standalone (the per-task `tags:` declaration enables that).

## Elastic-foundation flow

`_release_elastic` runs AWS-API operations bracketing one or two `tofu apply` invocations:

1. **Aggregate into SSM**. `aggregate_elastic` (mod 082, replaces the removed `_push_secrets`) treats the SSM prefix `/<project>/<env>/` *as* the aggregate: TTE minted-if-absent (`SecureString`, put-if-absent — never clobbers a live value, so no RDS lockout), secrets overwritten (`SecureString`), config overwritten (`String`). Each `<KEY>` lands at `/<project>/<env>/<KEY>`; the compiled HCL's ECS `secrets[]` / `environment[]` blocks reference them. `dry_run` skips it; `skip_migrations`/rollback preserves the live TTE. See [`config_and_secrets.md`](../../../doctrine/infrastructure/specifics/config_and_secrets.md).
2. **Detect first-release vs steady-state**. `aws.ecs_cluster_has_services(apply_policy(f"{project}_{env}", ecs_policy))` — if the env's cluster holds no ECS services, this is the first release of this env. Mod 071 moved the ECS cluster to the project tier (it always exists now), so cluster *existence* no longer distinguishes a first release; env-service existence does. The cluster name is policy-aware (mod 007); earlier versions used a literal `f"{project}-{env}"` which never matched after mod 005's naming policies landed.
3. **Branch on detection** — see [The four sequences](#the-four-sequences) below.
4. **Reconcile Service Connect consumers**, after the final apply on every branch including rollback. `_reconcile_service_connect_consumers` reads two pieces of *post-apply* AWS state — each namespace endpoint's Cloud Map `CreateDate` (`service_connect_endpoints`, client-bookkeeping entries filtered) and the `createdAt` of each candidate consumer's PRIMARY ECS deployment (`ecs_primary_deployment_times`, one `DescribeServices` batched at 10) — and `forceNewDeployment`s any core service whose deployment predates a name it `uses`, then waits, bounded, for steady state. Mod 109 introduced the step but triggered it off a namespace snapshot taken *before* the apply, which lived in one process's memory: an interrupted release left a permanently broken env and exited 0 on every re-run. Mod 114 replaced both operands with durable ones — but picked the wrong consumer-side event. `CreateDate` is stamped at ECS *service* creation, so a task of that service always starts after it, and `startedAt <= CreateDate` could not fire whenever consumer and target were created by one apply (every first release, and every release that bumps the consumer's image). The 1.7.0 elastic walk found it inert on `prod`. **Mod 123** replaced it with deployment age: Service Connect serves each Envoy a cluster list fixed for its deployment's task-set ARN, so the deployment is the thing whose age decides resolvability, and tasks replaced inside a stale deployment inherit the same stale list. The margin constant is **60 s**, and it is NOT a skew allowance — it deliberately collapses the concurrent-creation window into a redeploy, because that window is where the boundary is unmeasurable and because a false negative there is permanent and silent while a false positive is one rolling deploy. See the WHY in `release.py` and [`release.md § Service Connect Consumer Reconcile`](../../../doctrine/infrastructure/specifics/release.md#service-connect-consumer-reconcile).

Adapters: `src/docex/aws/client.py` (the `AWSClient` interface) and `src/docex/aws/boto3_client.py` (the only file in docex permitted to import `boto3` — kept narrow to keep the AWS surface auditable). `src/docex/opentofu/subprocess_runner.py` shells out to `tofu`.

## The four sequences

|  | Fixed (steady-state or first) | Elastic — first release | Elastic — steady state |
| --- | ----- | ----------------------- | ---------------------- |
| 1 | ansible-playbook (everything below happens inside it) | SSM push | SSM push |
| 2 | docker pull (per codebase) | tofu apply (full) | tofu apply (targeted: migration task-defs only) |
| 3 | render compose.yml + .env | run_migrate (`RunTask` per schema owner) | run_migrate (`RunTask` per schema owner) |
| 4 | docker compose run migrate (per schema owner) | — | tofu apply (full) |
| 5 | docker compose up -d | — | — |

**Why the elastic ordering differs between first-release and steady-state:**

- **First-release**: the env's ECS services and RDS don't exist yet (the ECS cluster itself is project-tier and already present since mod 071). `tofu apply` must run *before* migrate, because migrate needs the services + RDS to exist. The transient consequence is that newly-created ECS tasks may crash-loop until the migration completes, but no users are on a first-deploy env so the window is bounded by migration runtime.
- **Steady-state**: the doctrine prefers migrate-then-apply so the rolling deploy of new application code happens *after* the schema is migrated, preserving zero-downtime (see [`migrations.md § Backward-Compatibility Requirement`](../../../doctrine/infrastructure/specifics/migrations.md#backward-compatibility-requirement)). The pre-migrate **targeted** apply (mod 008) only bumps migration task-defs — not main service task-defs — so the in-flight web/worker tasks keep serving old code during the migration window. Without that targeted apply, RunTask would pick up the previous release's revision and any current-release task-def change (image tag, env-var refs) would be invisible to migrate.

## The migration step

`src/docex/orchestrate/migrate.py:run_migrate` is the entry point. `dev` / `test` envs run migrations inline against the local stack; `stage` / `prod` dispatch by foundation:

- **Fixed** (`stage` / `prod`): re-runs the emitted ansible playbook with `--tags migrate`. The playbook's per-codebase migrate task does `docker compose run --rm <cb>-exec /service/migrate.sh` against the deployed stack on the target host. Container reuses the live env vars from the rendered `.env`.
- **Elastic** (`stage` / `prod`): `_migrate_elastic` calls `aws.ecs_run_task` against the per-codebase migration task-def family — `apply_policy(f"{project}_{env}_{cb}_migrate", ecs)`. The task definition is doctrine-emitted alongside the main task def — same image, different command (`/service/migrate.sh` instead of the app entrypoint). After RunTask, poll `describe_tasks` until `lastStatus == STOPPED`, then read `containers[0].exitCode`. Non-zero exit aborts the release.

`codebases_with_schema(ctx)` in `src/docex/orchestrate/_common.py` returns the list of codebases that own a database schema, derived from each backing service's `schema_owned_by` field. The doctrine forbids two codebases owning the same schema (a compile-time check), so this list is a clean set.

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
| `release aborted — N required secret(s) unset for '<env>'` | A required secret (core `secrets:` / backing `kind: secret` / `TELEMETRY_API_KEY`) is absent or empty in `infra/secrets/<env>.env` | mod 091 guard — set it with `docex secrets set <env> <KEY>` (or `docex secrets scaffold <env>` to reconcile keys first); `pipeline/release.py:_require_secrets_present` |
| `InvalidBucketName` on bootstrap (precedes release on first elastic deploy) | Project-name policy mismatch | `pipeline/bootstrap.py` / `tables/naming_policies.yml` — mod 005 fixed this |
| Migration task fails to start with `unable to retrieve secrets from ssm: context deadline exceeded` | Per-network SG missing egress | `templates/main.tf.j2` per-network SG block — mod 006 fixed this |
| Migration task exits non-zero with `dial tcp: lookup <host>:<port>:<port>: no such host` | DB host part returning `host:port` instead of host | `tables/roles/relational_db.yml` `provides.host.elastic` — mod 007 fixed this |
| Migration uses stale env vars after a doctrine-side change | LATEST task-def revision is still previous release's | mod 008 fixed this — steady-state now runs pre-migrate targeted apply |
| Release log says `no ECS services in cluster ...` (mod 071 message; pre-071: `ECS cluster ... not yet provisioned`) on every steady-state release | First-release detector compared wrong name form | mod 007 fixed this — `apply_policy` on the probed name |
| `tofu destroy` of an env blocked by a deletion-protected RDS | RDS has `deletion_protection: true` | `docex envinfra down <env>` refuses-and-reports protected RDS up front (mod 052, Gap F) — disable protection deliberately and re-run; docex never disables it for you. The smoke `teardown.sh` does the disable automatically (smoke-only). |
| `RepositoryNotEmptyException` would block project-tier destroy | ECR repo still holds images | `docex projinfra down production` refuses-and-reports non-empty ECR up front (mod 052, Gap F) — empty the repo and re-run. |
| `HostedZoneNotEmpty` would block project-tier destroy of the Route53 child zone | Zone holds records tofu doesn't own — dev `A`-records forced into the child zone by NS delegation (dev is fixed / out-of-band), and stale ACM validation CNAMEs | Handled automatically — the zone is emitted `force_destroy = true` so `tofu destroy` sweeps all records first (mod 072). `projinfra down production` also prints a reminder to remove the parent-zone NS delegation (operator-managed; docex has no scope over the parent zone). See `doctrine/.../projinfra/elastic_route53_zone.md § Teardown`. |

For ECS-container-level diagnostics: every container in a task definition emits an `awslogs` `logConfiguration` to a per-(env, service) CloudWatch log group `/<project>/<env>/<service>` (mod 052, Gap E — the app container, the OTel sidecar, and the `_migrate` container, distinguished by stream prefix). To debug a failing task — including a `migrate.sh` that exits non-zero — read that CloudWatch log group; no hand-patching required. (This is Class-2 diagnostic stdout/stderr; structured app telemetry still flows via the OTel sidecar to the observability backend.)

## Where to look when changing things

| To change... | Touch... |
| ------------ | -------- |
| Foundation dispatch | `src/docex/pipeline/release.py:run_release` |
| The required-secret precondition (stage/prod) | `src/docex/pipeline/release.py:_require_secrets_present` (runs before the foundation branch; rollback bypasses it) |
| The fixed playbook tasks | `src/docex/emit/ansible.py` + `templates/playbook.yml.j2` |
| The order/sequence of release steps | `src/docex/pipeline/release.py` (`_release_fixed`, `_release_elastic`) |
| How migrate.sh is invoked on either foundation | `src/docex/orchestrate/migrate.py` (`_migrate_stage_prod`, `_migrate_elastic`) |
| AWS API calls docex makes | `src/docex/aws/boto3_client.py` (sole importer of `boto3`) |
| SSM push / aggregate semantics | `src/docex/orchestrate/aggregate.py:aggregate_elastic` (this replaced the removed `release.py:_push_secrets`) |
| TTE minting (either foundation) | `src/docex/orchestrate/aggregate.py:ensure_tte_elastic` / `ensure_tte_fixed` |
| The host TTE read (fixed) | `src/docex/ssh/client.py:capture` (`SSHClient`) |
| A single SSM parameter read | `src/docex/aws/boto3_client.py:ssm_get_parameter` |
| The fixed aggregate/store render onto the host | the playbook `agg_env_file` / `tte_store_file` `--extra-vars` (`templates/playbook.yml.j2`) |
| First-release vs steady-state detection | `src/docex/pipeline/release.py:_release_elastic` (`ecs_cluster_has_services` probe — mod 071; the project-tier cluster always exists, so an empty cluster signals first release) |
| Which consumers get redeployed after an elastic apply | `src/docex/pipeline/release.py:_reconcile_candidates` (the pure filter — which consumers are worth an API call) and `_consumer_reconcile_set` (the predicate), driven by `_reconcile_service_connect_consumers` (the step). Both operands are post-apply reads; nothing is carried across the apply or between releases (mods 114 / 123) |
| Schema-owner discovery | `src/docex/orchestrate/_common.py:codebases_with_schema` |
| Migration task-def family name | `src/docex/orchestrate/migrate.py:_migration_task_family` |
| The ECS cluster / Service Connect namespace name | `src/docex/naming.py:ecs_cluster_name` — **the only expression** (mod 128). Five sites had held verbatim copies: `release.py`, `orchestrate/migrate.py`, `pipeline/projinfra.py`, `emit/hcl.py` (which *emits* the clusters), and `stagetest`'s new read. The emitter/reader pair is why it mattered: a disagreement means a runtime read addressing a cluster nothing created |
| Whether a released env is actually healthy, and at what version | `src/docex/pipeline/orchestrator_health.py:assert_deployed_healthy` — read by `stagetest`, **not** by `release`. Release converges the env; `stagetest` is where the doctrine asserts the result ([`cicd.md § Staging Tests`](../../../doctrine/infrastructure/cicd.md#staging-tests) step 1) |

For a new doctrine-prescribed step in the release flow (e.g. a pre-migrate validation, a post-migrate verification), the entry point is `_release_elastic` or `_release_fixed`. Mirror the existing helper pattern (`_do_apply`, `_do_migrate`, and the aggregation call into `orchestrate/aggregate.py:aggregate_elastic`) — small, single-responsibility functions that the foundation branch composes.

For a new failure mode worth catching before it reaches AWS: add the check at compile time in `cicl/validate.py` rather than at release time. A compile error is always preferable to a tofu-side or AWS-side error.

## Rollback flow

How `docex rollback` drives an emergency reversion. The doctrine specifies the *what* in [`cicd.md § Rollback`](../../../doctrine/infrastructure/cicd.md#rollback); this section covers the *how*: precondition order, the worktree-at-tag mechanism, the skip-migrations parameterization on the existing release path, and dry-run semantics.

Rollback is intentionally a thin shell on top of release machinery rather than a parallel pipeline. The doctrine commits rollback to a narrow window (emergency-only, code-only, at most one minor version back), which means it can compose the existing release functions with a toggle rather than duplicate them.

### Scope

`run_rollback` takes:

- The current `ProjectContext` (on `main`, clean tree).
- `env` — `stage` or `prod`; other values raise `EnvNotSupported`.
- `target_version` — a SemVer string. Must resolve to a `v<target_version>` git tag, declare a `cicl_version` the current compiler accepts, and have per-codebase images present in the registry. Validated by preconditions before any state is touched.
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
    4. Mirror gitignored creds + secrets + config from project_root into worktree:
         infra/deploy_creds/<env>     (SSH key for fixed)
         infra/secrets/<env>.env      (per-env secrets, both foundations)
         infra/config/<env>.env       (per-env config, both foundations)
    5. Dispatch on infra.foundation:
         fixed   → _release_fixed(worktree_ctx, skip_migrations=True, dry_run=...)
         elastic → _release_elastic(worktree_ctx, skip_migrations=True, dry_run=..., tofu_plan=...)
    6. cleanup_worktree(...) in a finally block
```

The mirror step (4) exists because the release functions read those paths via `worktree_ctx.project_root`, but `git worktree add` does not carry gitignored files. All three are gitignored by doctrine bootstrap defaults. The mirror step is the complete fix; all other release inputs (compiled output, contracts, transfer tables, codebase files) are tracked and follow the worktree normally.

`_release_fixed` and `_release_elastic` were extended (mod 029) with `skip_migrations` and `dry_run` kwargs — defaults `False`, so `release`'s call sites are unchanged.

### Preconditions

Order matters: cheap fail-fast first, fail-aggregated registry probe last.

| Order | Check | Failure type |
| ----- | ----- | ------------ |
| 1 | `env in {"stage", "prod"}` | `EnvNotSupported` |
| 2 | `infra/infra.yml` present | exit 1 |
| 3 | On `main` branch | `RollbackPreconditionFailed` |
| 4 | No uncommitted changes outside `infra/output/` | `WorkingTreeDirty` |
| 5 | `v<target_version>` tag exists locally | `RollbackPreconditionFailed` |
| 6 | `validate_one_minor_back(current, target)` passes | `RollbackPreconditionFailed` |
| 7 | Target tag's `infra.yml` declares a compilable `cicl_version` | `RollbackPreconditionFailed` |
| 8 | All per-codebase images at `<target_version>` present in registry | `RollbackPreconditionFailed` (full list) |

Step 8 is the only fail-aggregated check. `_missing_images` probes every codebase, accumulates misses, and the caller raises with the complete list — under emergency pressure the operator benefits from one diagnostic showing the full gap, not a fail-fast first-match.

### The CICL-generation precondition (step 7)

Step 3 of the process recompiles the target's `infra.yml` with the **current** `docex`. So a target written in a CICL generation the current compiler rejects cannot be rolled back to at all — the recompile inside the worktree would fail. `cicl.md § CICL Version` states the consequence: rollback across the v2 → v3 boundary aborts at pre-flight, before anything is applied, with a fix-forward message.

`_target_cicl_version` reads `infra/infra.yml` out of the target tag via `GitClient.show` (no worktree, no checkout), `yaml.safe_load`s it, and returns the one top-level `cicl_version` key. Deliberately **not** a `CICLDocument` validation: a pre-v3 `infra.yml` fails full validation for several unrelated reasons at once (no `codebases:` — mod 112 traded the nouns, so a v2 document's top-level `core_services:` is now itself a forbidden extra under `extra="forbid"` (`model.py:327`, `:361`) — a bare rather than dotted `domain_default_service`, codebase-level `resources:`), and which one pydantic reports first would decide what the operator sees. "You are across the boundary" is the only fact that matters, and it is the one a single-key read cannot get wrong — it also has to work on a file that is not a valid CICL document at all.

Five outcomes, all raising `RollbackPreconditionFailed` so no branch can surface as a traceback: `"3"` proceeds; `"1"`, `"2"`, and *absent* all take the boundary branch (`_RECOGNIZED_OLDER_CICL = ("1", "2")` at `rollback.py:290`, plus the `None` test at `:307`) — a document predating the field is reported as predating it rather than as declaring `"1"`, though the message renders it as generation 1; any other value gets a distinct unrecognized-generation message; and an `infra.yml` that is unreadable, unparseable, or not a mapping aborts naming the tag and the path.

The boundary message is **not** a fixed `v1→v2` string. It renders `f"v{generation}→v{CURRENT_CICL_VERSION}"` (`rollback.py:315-316`), parameterized on the target's own declared generation by design — the `WHY` on `_boundary_message` says so explicitly: a message naming a fixed pair goes stale in the same instant the constant moves, which is exactly when the operator is reading it. This document went stale at the v2→v3 bump anyway, because it **restated** that message rather than quoting its rendered output; `upgrade_1.7.0.md § Rollback is unavailable across the boundary` quotes it, and that is the pattern to copy.

Two ordering constraints, both load-bearing:

- **Before the worktree** (`:139`) — the entire point. The unit tests assert `worktree_add` was never called and the worktree path does not exist, not merely that the call returned non-zero.
- **Before the image probe** — ordered by *decisiveness*, not only by cost. A missing image might be rebuilt from the tag; a boundary crossing cannot be resolved by anything except fixing forward, so a missing-image list would be noise at the moment noise is most expensive.

`CURRENT_CICL_VERSION` (`src/docex/cicl/model.py`) is the single source of the accepted generation, shared with rule 21's validator so the two cannot drift at the next CICL bump.

**The one-cycle window.** For exactly one release cycle after the CICL v3 break shipped (doctrine 1.7.0), `prod` has **no rollback path** — every extant older tag declares `cicl_version: "2"`. This is accepted and documented, not a defect: the alternative was a read-only flat-form parser maintained permanently to serve one code path. Once a second v3 version exists, rollback within v3 works normally. The window is a recurring property of a CICL bump, not a one-off — 1.6.0 carried the identical trap at its own v1→v2 boundary. `upgrade_1.7.0.md § Rollback is unavailable across the boundary` states this same condition for the operator, sourced by quoting `_boundary_message`'s rendered output; the two are one statement and must stay that way.

### Worktree mechanism

The worktree helpers live in `src/docex/pipeline/_worktree.py`, extracted from `check.py` in mod 029 — both commands share them:

- `worktree_path_for(project_root, slug)` → `.docex/worktrees/<slug>`. Caller composes the slug (`check-<sha>` or `rollback-<version>`).
- `make_temp_branch(prefix, ref_name)` → `docex-<prefix>/<safe_ref>-<timestamp>`. Timestamp suffix prevents collision when concurrent invocations target the same ref.
- `cleanup_worktree(...)` — best-effort teardown: force-remove, fall back to `shutil.rmtree`, prune the worktree list, delete the temp branch. Never raises.

Rollback's recipe differs from check's: no rebase, just a checkout at `v<target_version>`. The shared helpers cover the mechanical bits; the recipe lives in `run_rollback`.

### The skip-migrations toggle

The doctrine commits rollback to code-only behavior — migrations are not reversed; the rolled-back code runs against the existing (newer) schema. This works because forward migrations are already required to be backward-compatible (see [`migrations.md § Backward-Compatibility Requirement`](../../../doctrine/infrastructure/specifics/migrations.md#backward-compatibility-requirement)).

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
| `rollback aborted — cannot roll back across the CICL v<n>→v3 boundary` (rendered `v1→v3` or `v2→v3` depending on what the target declares — the pair is parameterized, not literal) | Target predates the CICL v3 break, so the current compiler cannot recompile its `infra.yml`. Expected for every target older than doctrine 1.7.0 | by design — nothing was touched; fix forward. See [the CICL-generation precondition](#the-cicl-generation-precondition-step-7) and its one-cycle window |
| `rollback aborted — target v... declares cicl_version '4'` | Target declares a generation this `docex` does not compile — usually a `docex` older than the target, i.e. the operator is rolling *forward* by mistake | check `project.yml`'s `docex_version` pin against the target tag's |
| `rollback aborted — could not read infra/infra.yml at tag '...'` | The tag exists but carries no `infra/infra.yml` (pre-doctrine tag, or a repo restructure since) | confirm the tag is a real release; fix forward if it predates the current layout |
| `tofu apply` destroys an RDS / stateful backing service during rollback | Target version's `infra.yml` lacked that backing service; doctrine's narrow-window destroy risk | `deletion_protection: true` on stateful engines should gate; if not, the rollback was outside the narrow window — fix-forward instead |
| Dry-run on elastic shows an unexpectedly empty diff | Plan ran against current SSM (rollback doesn't push in dry-run), and other resources didn't drift either | confirm the target version is actually older than what is deployed by reading it from the **orchestrator** (`pipeline/orchestrator_health.py`, the read `stagetest` makes: task-definition revision on elastic, `.Config.Image` on fixed). A `web` edge's `GET /health` still reports a version and is the weaker of the two — a stale container will happily falsify it, which is why [`healthchecks.md § Version`](../../../doctrine/infrastructure/healthchecks.md#version) makes the orchestrator authoritative |
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
| Which CICL generations rollback accepts | `src/docex/cicl/model.py:CURRENT_CICL_VERSION` (shared with rule 21's validator), read by `src/docex/pipeline/rollback.py:_target_cicl_version` |
| Rollback abort wording | `src/docex/pipeline/rollback.py:_boundary_message` / `_FIX_FORWARD` |
| Reading a file out of a git ref without a worktree | `GitClient.show` — `src/docex/git/subprocess_client.py`; `check.py:_git_show` wraps it with a raise-on-failure contract |
| Worktree path / branch naming convention | `src/docex/pipeline/_worktree.py` |

For a new doctrine-prescribed step in rollback specifically (not in release): the seam is `run_rollback`. For a new property of "what a rollback does to the env" (e.g. a new flag on the release functions): add the parameter on `_release_fixed` / `_release_elastic` with a `False` default so the existing `release` path stays unchanged, then set it from `run_rollback`.
