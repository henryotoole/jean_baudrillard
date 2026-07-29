---
stratum: conditional
---

# Scheduler

This file describes the `scheduler` role — how `docex` runs a project's own code
on a recurring **cron schedule**, rather than as a continuously-serving process.
It is foundation-aware in implementation but identical in contract: a `scheduler`
**process type** declares a `command` and a `schedule`, and `docex` arranges for
that command to run, in the **codebase's** image, on that schedule, with the
codebase-and-process env/secret surface any process type of that env receives.

This is documentation for the implementer of `docex` and the curious developer;
it is not meant to be force-loaded as general doctrine context. The shorter
`infra.yml`-facing summary is in [cicl.md § Service Fields](../cicl.md#service-fields)
and [cicl.md § Process Types](../cicl.md#process-types).

## What a scheduler process type is

A `scheduler` process type is one way of invoking a core service's image (the
project's own code, one image per codebase) whose `role:` is `scheduler`. Unlike
a `web` process type it does not serve HTTP, may not declare the `web` network
(rule 27), and has no long-running container or ECS service. It exists to run one
`command` to completion, on a schedule, and exit. Think "cron job in the
project's image": a nightly cleanup, an hourly report roll-up, a periodic cache
warm.

```yml
core_services:
  jobs:                                         # the codebase
    env:
      DATABASE_HOST: ${backing_services.appdb.host}
      DATABASE_PORT: ${backing_services.appdb.port}
      # ... codebase-scoped env, merged into every process type
    processes:
      nightly_cleanup:                          # the process type, named for the job
        role: scheduler
        schedule: "0 3 * * *"                   # 5-field cron (see § Cron format)
        command: ["python", "-m", "jobs.cleanup"]
        resources: { cpu: 0.25, memory: 512MB }
        networks: [internal]
        depends_on: [appdb]
```

Note the codebase is named `jobs` and the process type is named for the job, per
[cicl.md § Naming convention](../cicl.md#naming-convention): a codebase commonly
carries several jobs, and naming the codebase after one of them compiles to a
doubled identity like `nightly_cleanup-nightly_cleanup`.

The image is derived exactly as for any core service and is keyed on the
**codebase** (per
[cicl.md § Container Registry](../cicl.md#container-registry-and-service-images)):
a local build tag in `dev`/`test`, the registry ref in `stage`/`prod` — so a job
and its sibling `web` process type run **one** tag. The `resources:`,
`networks:`, and `depends_on:` fields, and the `env:`/`secrets:` surface, behave
identically to a `web` process type. Only the trigger differs.

## Cron format

`schedule:` is a **standard 5-field cron expression** —
`minute hour day-of-month month day-of-week` — in UTC. This is the project-facing
form; the compiler translates it per foundation. Two translation hazards the
compiler owns (and validates at compile time, failing cleanly on a malformed
expression):

1. **AWS EventBridge cron is 6-field with `?`-day semantics.** EventBridge uses
   `cron(minute hour day-of-month month day-of-week year)` and forbids `*` in
   *both* day-of-month and day-of-week — exactly one must be `?`. The compiler
   maps a 5-field expression by appending the year field `*` and substituting
   `?`: if day-of-week is `*` it becomes `?`; else if day-of-month is `*` it
   becomes `?`.
2. **Day-of-week numbering differs.** Standard cron numbers Sunday–Saturday as
   `0–6` (with `7` also Sunday); EventBridge numbers them `1–7` (Sunday = `1`).
   The compiler remaps any numeric day-of-week field when emitting the AWS form.
   Named days (`MON`, `SUN`, …) are unaffected and are the safer authoring
   choice.

Ofelia (the fixed primitive, below) uses a 6-field cron whose leading field is
**seconds**; the compiler prepends `0` (run at second 0) to the 5-field
expression. Ofelia's day-of-week numbering matches standard cron, so no remap is
needed there.

`schedule:` is required on a `scheduler` process type and rejected on a process
type of every other role (it would be inert). `command:` is required on **every**
process type now (per [cicl.md](../cicl.md#service-fields)), so requiring it here
no longer distinguishes a scheduler from anything else.

## Fixed Foundation — Ofelia

Docker Compose has no native scheduler, so on fixed `docex` emits a per-scheduler
[Ofelia](https://github.com/mcuadros/ofelia) container — a small, docker-native
job scheduler — that launches the job as a one-off container on each fire.

For a `scheduler` process type `<proc>` of core service `<svc>`, `docex compile`
emits one compose service `<project>-<env>-<svc>-<proc>-scheduler` running
`mcuadros/ofelia:<digest>` (pinned by digest, like every doctrine-shipped image).
One trigger per process type, so a codebase with three jobs gets three. It:

- Mounts the docker socket read-only (`/var/run/docker.sock`) so it can spawn the
  job container — the same DooD-adjacent pattern the project traefik uses.
- Reads its configuration from a rendered INI file (`ofelia-<svc>-<proc>.ini`) mounted
  via compose's top-level `configs:` block — the same config-delivery mechanism
  the OTel sidecar uses (see [telemetry_infra.md § Config Delivery](./telemetry_infra.md#config-delivery)).
- Carries the doctrine `docex.project` label and `restart: unless-stopped`, like
  every emitted container.

The rendered INI declares one `[job-run "<svc>-<proc>"]` section, keyed on the
two-segment compiled identity. Ofelia parses its
INI with `gcfg`, where a repeatable list field (`environment`, `volume`) is one
bare `key = value` line **per entry** — *not* a JSON array. (A JSON-array value
is mis-parsed: Ofelia takes the literal `["…` as the value, so the job never
runs.)

```ini
[job-run "jobs-nightly_cleanup"]
schedule = 0 0 3 * * *                       ; 0-seconds + the 5-field expression
image = myproject/jobs:0.4.2                 ; the CODEBASE image — same tag its sibling process types run
network = myproject-dev-internal             ; the process type's non-web network(s)
delete = true                                ; auto-remove the one-off container
environment = DATABASE_HOST=myproject-dev-appdb    ; one bare line per non-secret var
environment = OTEL_SERVICE_NAME=jobs-nightly_cleanup
command = sh -c '. /run/job.env && export DATABASE_USER="$POSTGRES_USER" && exec python -m jobs.cleanup'
volume = /opt/myproject/prod/.env:/run/job.env:ro  ; absolute source (see below)
```

**The image is the codebase's, which retires the self-contained job image.**
Earlier doctrine built a separate, `prod`-stage image per scheduler service, on
the correct observation that Ofelia spawns the job through the Docker API with no
bind mounts. That stopped being viable once the image became codebase-keyed: the
exec service builds the same tag at the `dev` target, and `compose run` builds
only when the image is *absent*, so a `prod`-stage image squatting on that tag
would be reused by `build`, `test`, and `migrate` — and the doctrinal `prod` stage
carries neither `build.sh` nor `test.sh`. Two consumers of one tag have to agree
about what is inside it.

**In `dev`, the codebase tag is the Dockerfile `dev` stage — for every process
type, including a cron job.** The accepted consequence: a `dev` job runs the
artifact the `dev` stage baked, refreshed on each `./bin/docex envinfra up dev`,
rather than the host's live `dist/`. Sibling process types get the `src/` and
`dist/` bind mounts and a job does not, because Ofelia spawns it outside Compose.
A **scheduler-only** codebase is the one shape no compose service builds — `up
--build` skips the profile-gated exec service and there is no other block of that
codebase — so `up dev` builds that tag itself.

### Env and secret delivery (the load-bearing detail)

The one-off job container must see the **same env-and-secret surface a normal
process type of that env sees** — `DATABASE_HOST`, the doctrine-injected
`OTEL_*`/`PROJECT_VERSION` vars, the `$[…]` secrets, everything. Because Ofelia
spawns the job container directly (not through Compose), Compose's `.env`
interpolation never reaches it, so the doctrine splits delivery along the same
secret/non-secret line elastic already uses (`environment[]` vs `secrets[]` on
the task definition):

- **Non-secret env — via Ofelia's INI `environment`.** Every value the compiler
  resolves at compile time and that is *not* a secret — magic-ref parts that
  resolve to literals (`DATABASE_HOST` → `<project>-<env>-appdb`), the
  doctrine-injected `OTEL_*` / `PROJECT_VERSION` block, plain literals from the
  process type's effective `env:` (codebase-scoped merged under process-scoped) —
  is rendered inline as one bare `environment = KEY=value`
  line per var in the `job-run` section (Ofelia's gcfg list form, not a JSON
  array). These are safe to inline because none are secret. Ofelia passes them
  to the one-off container.
- **Secrets — via a mounted, sourced env file, re-exported to the consumer
  keys.** Values that resolve to a `$[…]` runtime ref (e.g. `DATABASE_USER` →
  `$[POSTGRES_USER]`) are *not* known at compile and must not be inlined. The
  env's `.env` is mounted into the job at `/run/job.env:ro` and sourced before the
  command runs. Ofelia spawns the job through the Docker API rather than through
  Compose, so — unlike the
  [fixed migrate one-off](./migrations.md#stage-and-prod-on-fixed-foundation),
  which runs via `docker compose run` — it inherits neither Compose's
  relative-path resolution nor Compose's `${VAR}` env-mapping. Two consequences
  the compiler handles explicitly:
    1. **Absolute mount source.** The Docker API rejects a *relative* bind
       source, so the `volume` source must be an absolute host path. In fixed
       `stage`/`prod` it is the deterministic ansible deploy path
       `/opt/<project>/<env>/.env`, baked at compile. In `dev`/`test` the path is
       machine-specific (the operator's project root), so baking it would break
       compile determinism; instead the compiler emits `${DOCEX_SECRETS_ENV_FILE}`
       and `docex` sets that variable to the absolute `infra/secrets/<env>.env`
       when it brings the stack up, so Compose interpolates the real path into the
       rendered config.
    2. **Provider→consumer re-export.** The sourced `.env` carries the *provider*
       secret names (`POSTGRES_USER`), but the job reads the *consumer* keys
       (`DATABASE_USER`). Compose performs that mapping for ordinary services and
       the migrate one-off; the Ofelia job must do it explicitly. The compiler
       wraps the command as
       `sh -c '. /run/job.env && export DATABASE_USER="$POSTGRES_USER" && … && exec <command…>'`,
       one `export <consumer_key>="$<provider_var>"` per secret-bearing part. The
       `$`-refs are emitted **doubled** (`$$`) so Compose passes the literal
       `$POSTGRES_USER` through to the config and the *job* shell expands it from
       the sourced file at run time — the secret value never lands in the rendered
       config.

The two sets are disjoint (a provided part is either a literal or a single bare
`$[REF]`, never both — see [config_and_secrets.md § Parts-Only Rule](./config_and_secrets.md#parts-only-rule)),
so the inlined `environment` and the sourced secrets compose into exactly the env
surface a long-running service of that env would have.

Telemetry: a scheduler job is short-lived and there is no paired OTel sidecar
(no long-running container to share a netns with). Job stdout/stderr is captured
by the json-file driver on the one-off container as Class-2 diagnostics; SDK
telemetry from a scheduled job is a deferred concern (it would need a
batch-flush-before-exit story the v1 sidecar model doesn't cover).

## Elastic Foundation — EventBridge Scheduler → ECS RunTask

On elastic a `scheduler` process type compiles to two emit destinations and one
IAM role; there is **no `ecs_service`** (nothing runs continuously):

1. **`task_definition`** — the same task-def machinery a `web` process type uses:
   the project image, the `command`, the `resources:`-derived Fargate sizing, the
   ECS `secrets[]` block sourced from SSM, and the `awslogs` log configuration
   into the per-(env, codebase) CloudWatch group (mod 052). Elastic secret
   delivery is therefore already solved — nothing scheduler-specific is needed for
   it. The **OTel sidecar is omitted**, however: it is paired only with
   long-running process types (those that also emit `ecs_service`), and a one-shot
   RunTask has no place for it — consistent with the fixed side, where the one-off
   job container likewise has no sidecar. Consequently a codebase with a `web`
   process type and a nightly job gets exactly one sidecar — for the web process —
   which the old per-service phrasing could not express. It also means the
   scheduler's task-level Fargate sizing carries **no** sidecar overhead, since
   there is no sidecar to allow for (see
   [telemetry_infra.md § Task-Level Resource Allocation](./telemetry_infra.md#task-level-resource-allocation)).
   Job-level SDK telemetry is deferred on both foundations (see § Telemetry note
   under Fixed and § Caveats).
2. **`scheduled_task`** (new destination) — an `aws_scheduler_schedule`
   (EventBridge Scheduler) whose:
   - `schedule_expression` is the translated `cron(… ?-day … year)` form,
     `schedule_expression_timezone = "UTC"`, `flexible_time_window { mode = "OFF" }`.
   - `target` invokes ECS `RunTask`: `arn` is the env's ECS cluster ARN,
     `role_arn` is the scheduler-invocation role below, and `ecs_parameters`
     names the task-def ARN, `launch_type = "FARGATE"`, `task_count = 1`, and a
     `network_configuration` pinning the master VPC's primary-AZ **private**
     subnet with the process type's non-`web` security group(s) and
     `assign_public_ip = false` — the same network placement the migrate RunTask
     uses (see [migrations.md § Elastic](./migrations.md#stage-and-prod-on-elastic-foundation)).
3. **Scheduler-invocation IAM role** — trusted by `scheduler.amazonaws.com`,
   with an inline policy granting `ecs:RunTask` on the `scheduler` process type's
   task-definition family and `iam:PassRole` on the project task-execution role
   (and the process type's task role, if it declares one). Scoped to this project's
   resources, mirroring the minimal-IAM stance of
   [elastic_iam.md](./projinfra/elastic_iam.md). One role per `scheduler` process
   type in v1; consolidating to one per env is a future minimization.

EventBridge Scheduler is chosen over the older CloudWatch Events rule: it is the
current AWS-recommended primitive, models one-shot `RunTask` invocations
directly, and needs no always-on rule resource.

## Lifecycle and idempotency

- **Fixed:** the Ofelia container comes up with the env stack (`envinfra up <env>`
  / `release`) and is torn down with it. Re-running is idempotent — Compose
  reconciles the scheduler container like any other service. The one-off job
  containers are `delete = true`, so they don't accumulate. The `test` env is the
  exception: no Ofelia container is emitted for a `scheduler` process type there,
  so its stack carries no scheduler at all (see § Caveats).
- **Elastic:** the schedule, task def, and invocation role are env-tier — created
  and destroyed with the env by `release` / `envinfra down`. `tofu apply` against
  an unchanged schedule is a no-op.

## Caveats

- **`test` suppresses the scheduler trigger.** Like `web` routing (which `test`
  drops entirely — see [cicl.md § TLS Implications](../cicl.md#tls-implications)),
  a scheduler's trigger is omitted from the `test` stack: the compiler emits no
  Ofelia container for a `scheduler` process type, so the job never fires inside
  the `test` window. Because `dev`/`test` are always fixed, the Ofelia trigger is
  the only one `test` could carry, and it is dropped (the elastic EventBridge path
  is never reached for `test`). The `scheduler` process type is otherwise inert in
  every env — it has no long-running container. `docex test` runs a scheduler's
  `test.sh` through the same path as every other codebase — a one-off container of
  that codebase's exec service — so there is no scheduler carve-out and a
  scheduler-only codebase needs no special handling. Because the trigger is
  dropped in `test`, a `scheduler` process type contributes nothing to the `test`
  stack at all: a scheduler-only codebase's only compose block there is its exec
  service. Exercise a job's logic through its own unit/module tests, or in `dev`.
- **No backfill / catch-up.** A missed fire (host down, instance replacement) is
  not retroactively run. Both Ofelia and EventBridge Scheduler fire forward-only
  in the v1 configuration.
- **No per-job concurrency guard.** If a job's runtime exceeds its interval, a
  second instance can start before the first finishes. Jobs must be idempotent
  and safe to overlap, or self-guard with a lock.
- **Job-level SDK telemetry is deferred** (see § Fixed env delivery). Diagnostics
  flow to `docker logs` (fixed) / CloudWatch (elastic) as Class-2 output.
