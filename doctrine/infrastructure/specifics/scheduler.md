---
stratum: conditional
---

# Scheduler

This file describes the `scheduler` role — how `docex` runs a project's own code
on a recurring **cron schedule**, rather than as a continuously-serving process.
It is foundation-aware in implementation but identical in contract: a scheduler
service declares a `command` and a `schedule`, and `docex` arranges for that
command to run, in the project's image, on that schedule, with the same resolved
environment-and-secret surface any core service of that env would receive.

This is documentation for the implementer of `docex` and the curious developer;
it is not meant to be force-loaded as general doctrine context. The shorter
`infra.yml`-facing summary is in [cicl.md § Service Fields](../cicl.md#service-fields).

## What a scheduler service is

A scheduler service is a **core service** (the project's own code, its own
image) whose `role:` is `scheduler`. Unlike a `web` core service it does not
serve HTTP, is never on the `web` network, and has no long-running container or
ECS service. It exists to run one `command` to completion, on a schedule, and
exit. Think "cron job in the project's image": a nightly cleanup, an hourly
report roll-up, a periodic cache warm.

```yml
core_services:
  nightly_cleanup:
    role: scheduler
    schedule: "0 3 * * *"                       # 5-field cron (see § Cron format)
    command: ["python", "-m", "jobs.cleanup"]   # the job entrypoint
    resources: { cpu: 0.25, memory: 512MB }
    networks: [internal]
    env:
      DATABASE_HOST: ${backing_services.appdb.host}
      DATABASE_PORT: ${backing_services.appdb.port}
      # ... same env/secret surface as any core service
    depends_on: [appdb]
```

The image is derived exactly as for any core service (per
[cicl.md § Container Registry](../cicl.md#container-registry-and-service-images)):
a local build tag in `dev`/`test`, the registry ref in `stage`/`prod`. The
`resources:`, `env:`, `secrets:`, and `depends_on:` fields behave identically to
a `web` core service. Only the trigger differs.

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

`schedule:` is required for the `scheduler` role and rejected on every other
role (it would be inert). `command:` is required for `scheduler` (there is no
sensible default job entrypoint).

## Fixed Foundation — Ofelia

Docker Compose has no native scheduler, so on fixed `docex` emits a per-scheduler
[Ofelia](https://github.com/mcuadros/ofelia) container — a small, docker-native
job scheduler — that launches the job as a one-off container on each fire.

For a scheduler service `<svc>`, `docex compile` emits one compose service
`<project>-<env>-<svc>-scheduler` running `mcuadros/ofelia:<digest>` (pinned by
digest, like every doctrine-shipped image). It:

- Mounts the docker socket read-only (`/var/run/docker.sock`) so it can spawn the
  job container — the same DooD-adjacent pattern the project traefik uses.
- Reads its configuration from a rendered INI file (`ofelia-<svc>.ini`) mounted
  via compose's top-level `configs:` block — the same config-delivery mechanism
  the OTel sidecar uses (see [telemetry_infra.md § Config Delivery](./telemetry_infra.md#config-delivery)).
- Carries the doctrine `docex.project` label and `restart: unless-stopped`, like
  every emitted container.

The rendered INI declares one `[job-run "<svc>"]` section. Ofelia parses its
INI with `gcfg`, where a repeatable list field (`environment`, `volume`) is one
bare `key = value` line **per entry** — *not* a JSON array. (A JSON-array value
is mis-parsed: Ofelia takes the literal `["…` as the value, so the job never
runs.)

```ini
[job-run "nightly_cleanup"]
schedule = 0 0 3 * * *                       ; 0-seconds + the 5-field expression
image = myproject/nightly_cleanup:0.4.2      ; same image ref a core service uses
network = myproject-dev-internal             ; the service's non-web network(s)
delete = true                                ; auto-remove the one-off container
environment = DATABASE_HOST=myproject-dev-appdb    ; one bare line per non-secret var
environment = OTEL_SERVICE_NAME=nightly_cleanup
command = sh -c '. /run/job.env && export DATABASE_USER="$POSTGRES_USER" && exec python -m jobs.cleanup'
volume = /opt/myproject/prod/.env:/run/job.env:ro  ; absolute source (see below)
```

### Env and secret delivery (the load-bearing detail)

The one-off job container must see the **same env-and-secret surface a normal
core service of that env sees** — `DATABASE_HOST`, the doctrine-injected
`OTEL_*`/`PROJECT_VERSION` vars, the `$[…]` secrets, everything. Because Ofelia
spawns the job container directly (not through Compose), Compose's `.env`
interpolation never reaches it, so the doctrine splits delivery along the same
secret/non-secret line elastic already uses (`environment[]` vs `secrets[]` on
the task definition):

- **Non-secret env — via Ofelia's INI `environment`.** Every value the compiler
  resolves at compile time and that is *not* a secret — magic-ref parts that
  resolve to literals (`DATABASE_HOST` → `<project>-<env>-appdb`), the
  doctrine-injected `OTEL_*` / `PROJECT_VERSION` block, plain literals from the
  service's `env:` — is rendered inline as one bare `environment = KEY=value`
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

On elastic a scheduler service compiles to two emit destinations and one IAM
role; there is **no `ecs_service`** (nothing runs continuously):

1. **`task_definition`** — the same task-def machinery a `web` service uses: the
   project image, the `command`, the `resources:`-derived Fargate sizing, the ECS
   `secrets[]` block sourced from SSM, and the `awslogs` log configuration into
   the per-(env,service) CloudWatch group (mod 052). Elastic secret delivery is
   therefore already solved — nothing scheduler-specific is needed for it. The
   **OTel sidecar is omitted**, however: it is paired only with long-running
   services (those that also emit `ecs_service`), and a one-shot RunTask has no
   place for it — consistent with the fixed side, where the one-off job container
   likewise has no sidecar. Job-level SDK telemetry is deferred on both
   foundations (see § Telemetry note under Fixed and § Caveats).
2. **`scheduled_task`** (new destination) — an `aws_scheduler_schedule`
   (EventBridge Scheduler) whose:
   - `schedule_expression` is the translated `cron(… ?-day … year)` form,
     `schedule_expression_timezone = "UTC"`, `flexible_time_window { mode = "OFF" }`.
   - `target` invokes ECS `RunTask`: `arn` is the env's ECS cluster ARN,
     `role_arn` is the scheduler-invocation role below, and `ecs_parameters`
     names the task-def ARN, `launch_type = "FARGATE"`, `task_count = 1`, and a
     `network_configuration` pinning the master VPC's primary-AZ **private**
     subnet with the service's non-`web` security group(s) and
     `assign_public_ip = false` — the same network placement the migrate RunTask
     uses (see [migrations.md § Elastic](./migrations.md#stage-and-prod-on-elastic-foundation)).
3. **Scheduler-invocation IAM role** — trusted by `scheduler.amazonaws.com`,
   with an inline policy granting `ecs:RunTask` on the scheduler service's
   task-definition family and `iam:PassRole` on the project task-execution role
   (and the service's task role, if it declares one). Scoped to this project's
   resources, mirroring the minimal-IAM stance of
   [elastic_iam.md](./projinfra/elastic_iam.md). One role per scheduler service
   in v1; consolidating to one per env is a future minimization.

EventBridge Scheduler is chosen over the older CloudWatch Events rule: it is the
current AWS-recommended primitive, models one-shot `RunTask` invocations
directly, and needs no always-on rule resource.

## Lifecycle and idempotency

- **Fixed:** the Ofelia container comes up with the env stack (`envinfra up <env>`
  / `release`) and is torn down with it. Re-running is idempotent — Compose
  reconciles the scheduler container like any other service. The one-off job
  containers are `delete = true`, so they don't accumulate. The `test` env is the
  exception: no Ofelia container is emitted for it, so its stack carries no
  scheduler at all (see § Caveats).
- **Elastic:** the schedule, task def, and invocation role are env-tier — created
  and destroyed with the env by `release` / `envinfra down`. `tofu apply` against
  an unchanged schedule is a no-op.

## Caveats

- **`test` suppresses the scheduler trigger.** Like `web` routing (which `test`
  drops entirely — see [cicl.md § TLS Implications](../cicl.md#tls-implications)),
  a scheduler's trigger is omitted from the `test` stack: the compiler emits no
  Ofelia container for a scheduler service, so the job never fires inside the
  `test` window. Because `dev`/`test` are always fixed, the Ofelia trigger is the
  only one `test` could carry, and it is dropped (the elastic EventBridge path is
  never reached for `test`). The scheduler service is otherwise inert in every
  env — it has no long-running container — so in `test` it produces no compiled
  output at all. Exercise a job's logic through its own unit/module tests, or in
  `dev`, rather than relying on a `test`-window fire.
- **No backfill / catch-up.** A missed fire (host down, instance replacement) is
  not retroactively run. Both Ofelia and EventBridge Scheduler fire forward-only
  in the v1 configuration.
- **No per-job concurrency guard.** If a job's runtime exceeds its interval, a
  second instance can start before the first finishes. Jobs must be idempotent
  and safe to overlap, or self-guard with a lock.
- **Job-level SDK telemetry is deferred** (see § Fixed env delivery). Diagnostics
  flow to `docker logs` (fixed) / CloudWatch (elastic) as Class-2 output.
