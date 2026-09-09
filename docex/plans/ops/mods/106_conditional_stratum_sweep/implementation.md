# Mod 106 — Implementation

Doctrine prose only. **Touch no file under `docex/src/` or `docex/tests/`.**
**Touch no table under `docex/tables/`.** If you believe a code, table, or test
change is required, stop and report it — do not take it.

## Ground rules

1. **Surgical edits.** Preserve voice, heading structure, and link style. **Do
   not rename or add any heading** in any existing file. Anchors point at them.
2. **`cicl.md` and `contracts.md` are the rule of record.** Do not sweep them.
   The *only* `cicl.md` edit is Step 12 (rule 7's scope). Do not touch
   `contracts.md` at all.
3. **Do not touch these — operator work in progress:**
   `doctrine/practices/modifications.md`, `doctrine/chain/`,
   `doctrine/charts/configurable.md`, `doctrine/practices/advance.md`,
   `skills/chain-of-command/`, `skills/project-cohere/`,
   `skills/transcript-summary/`,
   `skills/skill-iteration/references/evaluation.md`.
4. **Work one step at a time and run that step's self-check before moving on.**
5. Paths are relative to `/home/ubuntu/.claude/jean_baudrillard/`.

## Step 0 — Baseline

```bash
cd /home/ubuntu/.claude/jean_baudrillard
python3 -m pytest docex/tests/unit -q 2>&1 | tail -3      # expect: 982 passed
git status --porcelain > /tmp/mod106_before.txt            # expect 118 lines
wc -l /tmp/mod106_before.txt
```

Copy the link checker to `/tmp/mod106_linkcheck.py` from
`/tmp/claude-1000/-home-ubuntu--claude-jean-baudrillard/26086b69-c94f-4900-95fc-b375cba7aaec/scratchpad/linkcheck.py`
if it exists; otherwise skip and rely on Step 14's grep sweeps.

Baseline link audit (`python3 /tmp/mod106_linkcheck.py doctrine skills`) reports
exactly **3** problems: `doctrine/chain/chain_of_command.md -> #use-of-agents`
and two `../../doctrine/path/to/file.md` (in `doctrine/skills/skills.md` and
`skills/skill-iteration/references/thread_body.md`). All three are expected and
**must be left alone**. Any *fourth* problem at the end is a regression.

---

## Step 1 — `doctrine/infrastructure/cicd.md`

### 1a. § Check Step, item 3.2

Replace:

```
	2. [Contracts](./infrastructure.md#contracts) exist which match `infra.yml` [depends-on](./cicl.md#depends-on-relationships) relationships.
```

with:

```
	2. [Contracts](./infrastructure.md#contracts) exist which match `infra.yml`'s [consumes](./cicl.md#consumes-relationships) relationships. One contract per provider process type, at `${service}.${process}.${format}.yml`.
```

### 1b. § Check Step, item 3.3

Replace:

```
	3. Contracts for core services on the `web` network have the mandatory [health check](./contracts.md#health-checks) endpoints.
```

with:

```
	3. Every `web`-network process type's contract carries the mandatory [health check](./contracts.md#health-checks) endpoints: its own `GET /health`, and a `/health/<service>/<process>` for each process type it `consumes` that is not itself on `web`. The self-`/health` assertion applies to OpenAPI providers; a `worker`'s probeability is declared by its fields, not by its AsyncAPI contract.
```

### 1c. § Check Step, item 3.4, plus a new item 3.5

Replace:

```
	4. Every `health_check_path`-declaring service's image carries `curl`.
```

with:

```
	4. Every core service whose image must answer a probe carries `curl`. The declaration is per process type — any one of a codebase's process types declaring `health_check_path` qualifies the codebase — but the subject is the codebase's single image, so the gate builds and probes once per core service.
	5. Every `consumes` target declares both `port` and `health_check_path`. Those two fields *are* its health declaration; see [contracts.md § Declared by fields](./contracts.md#declared-by-fields-not-by-the-contract).
```

### 1d. § Build Step, "Process (dev iteration)"

Replace the whole numbered list:

```
1. Ensure a dev-stage container of each target core service is available — either by reusing the running dev environment's containers, or by spawning an ephemeral dev container as needed.
2. Remove all contents of `$pr/core/${core_service_name}/dist` on the development machine.
3. Run `build.sh` within each core service's dev container.
	+ If any return a non-0 exit code, the build has failed.
	+ If any `dist` folder is empty afterward, the build has failed.
4. Updated artifacts appear in the host's `dist` folder via the container's bind-mount.
```

with:

```
1. Remove all contents of `$pr/core/${core_service_name}/dist` on the development machine.
2. Run `build.sh` in a one-off container of each core service's [exec service](./specifics/migrations.md#dev-and-test-mechanism) — `docker compose run --rm <project>-<env>-<core_service>-exec ./build.sh`. The exec service is the container that *is* the codebase; it is profile-gated, so no part of the dev stack needs to be running, and there is no per-process-type container to pick between.
	+ If any return a non-0 exit code, the build has failed.
	+ If any `dist` folder is empty afterward, the build has failed.
3. Updated artifacts appear in the host's `dist` folder via the container's bind-mount.
```

Then, immediately after that list, add one paragraph:

```
No image rebuild is triggered here. Dev iteration is the hot loop, so `./bin/docex build` deliberately runs against the codebase's existing image rather than rebuilding it; a stale image is refreshed by `./bin/docex envinfra up dev`.
```

### 1e. § Rollback, precondition 1

Insert a new sub-item **1.4** between the existing 1.3 and 1.4, and renumber the
old 1.4 to 1.5. The inserted text:

```
	4. `<target_version>`'s `infra.yml` declares a `cicl_version` this `docex` compiles. Rollback recompiles the target's `infra.yml` with the *current* compiler (step 3), so a target predating the v1 → v2 boundary cannot be rebuilt; the check reads the tag's `infra.yml` directly and aborts with a fix-forward message. See [cicl.md § CICL Version](./cicl.md#cicl-version).
```

The old 1.4 text (`Container images at <target_version> exist in the registry for
every core service.`) becomes item 5, unchanged.

### Self-check 1

```bash
cd /home/ubuntu/.claude/jean_baudrillard
grep -n "depends-on\|depends_on" doctrine/infrastructure/cicd.md   # no hit inside § Check Step item 3
grep -n "compose exec\|dev container" doctrine/infrastructure/cicd.md   # expect no hits
grep -c "^	[0-9]\." doctrine/infrastructure/cicd.md
```

Confirm § Rollback precondition 1 now runs 1..5 with no duplicate or skipped
number.

---

## Step 2 — `doctrine/infrastructure/docex.md`

### 2a. § describe, the formats list

Replace:

```
`dag` - Describe the infrastructure shape with a directed acyclic graph.
```

with:

```
`dag` - Describe the infrastructure shape with a directed graph. It renders both service relations with the edge kind distinguished: solid for [`depends_on`](./cicl.md#depends-on-relationships) (readiness), dashed for [`consumes`](./cicl.md#consumes-relationships) (interface). The graph is *directed*, not acyclic — `consumes` is a cyclic digraph by doctrine, so the rendered union may legally contain cycles; only the readiness relation on its own is acyclic. Node ids use the dotted reference form (`api.web`).
```

Leave the `--format dag` flag name alone everywhere. Write nothing suggesting it
should change.

### 2b. § preinfra, the dev-DNS paragraph

Replace:

```
The `development` side additionally verifies that each `dev` `web`-service hostname resolves in public DNS.
```

with:

```
The `development` side additionally verifies that every `dev` `web`-network hostname resolves in public DNS — one per `web` [process type](./cicl.md#process-types), plus any `web`-network backing service, plus the bare-env host when `domain_default_process` is set.
```

### 2c. § check

Replace `` `depends_on`-to-contract alignment checks `` with
`` `consumes`-to-contract alignment checks ``.

### 2d. § build

Replace:

```
Runs each core service's `build.sh` inside its running `dev`-stage container, depositing artifacts in `$pr/core/<service>/dist/` via bind-mount.
```

with:

```
Runs each core service's `build.sh` in a one-off container of that codebase's exec service (`docker compose run --rm … ./build.sh`), depositing artifacts in `$pr/core/<service>/dist/` via bind-mount. One exec service per codebase, so there is no per-process-type container to choose between, and the dev stack need not be running.
```

### 2e. § migrate

Replace:

```
For `dev` and `test`, runs `migrate.sh` inside each service's already-running container via `docker compose exec`.
```

with:

```
For `dev` and `test`, runs `migrate.sh` as a one-off container of each schema-owning codebase's exec service via `docker compose run --rm`.
```

### 2f. § role

Replace:

```
Describes one role: its engines (and foundations), the **provided parts** that magic refs target (`${backing_services.<svc>.<part>}`), which parts are secrets,
```

with:

```
Describes one role: its engines (and foundations), the **provided parts** that magic refs target (`${backing_services.<svc>.<part>}` for a backing role, `${core_services.<svc>.<proc>.<part>}` for a core one), which parts are secrets,
```

### Self-check 2

```bash
grep -n "acyclic" doctrine/infrastructure/docex.md      # expect exactly one hit: the "not acyclic" sentence
grep -n "format dag\|\"dag\", \"llm\"\|--format" doctrine/infrastructure/docex.md   # flag name intact
grep -n "compose exec\|web-service\|depends_on-to-contract" doctrine/infrastructure/docex.md   # expect no hits
```

---

## Step 3 — `doctrine/infrastructure/shape.md` (part 1: prose + rows)

### 3a. § General, Runtime Shape

Replace:

```
`prod` environments may also have multiple [core_service] containers running in parallel, and in this case the [reverse_proxy] doubles as a load balancer.
```

with:

```
`prod` environments may also have multiple containers of one [core_service] process type running in parallel. How they are load-balanced depends on the network: the [reverse_proxy] balances replicas of a `web` process type, because that is the traffic it terminates; replicas on an internal [network] are balanced by [service_discovery] instead, with no proxy in the path.
```

### 3b. § Fixed-Foundation, Runtime Shape

Replace:

```
In `prod`, there might be multiple of the same [service] (e.g. multiple workers) per environment - [reverse_proxy] load balances in this case.
```

with:

```
In `prod`, a [core_service] process type may run as several replica containers. Traefik's labels are keyed on the unqualified service name, so N replicas of a `web` process type register as N servers behind one router and [reverse_proxy] balances them. Replicas of a non-`web` process type — a worker, say — are never seen by the proxy at all: they share one docker network alias, and docker DNS round-robins across them.
```

### 3c. § Elastic-Foundation, Runtime Shape

Replace:

```
In `prod`, [core_service]s can have multiple replicas; the [reverse_proxy] load-balances across them.
```

with:

```
In `prod`, a [core_service] process type can have multiple replicas (ECS `desired_count`). The [reverse_proxy] load-balances the replicas of a `web` process type via its target group; replicas of an internal process type are balanced by [service_discovery], with no proxy involved.
```

### 3d. `core_service` rows — both tables

Fixed table, replace:

```
| core_service | environment | Docker container | A container running the project's own code (one of the project's [build_image]s). |
```

with:

```
| core_service | environment | Docker container | A container running the project's own code (one of the project's [build_image]s). One container per [process type](./cicl.md#process-types), not per codebase — a codebase's process types all run the same image with different `command`s. In `prod`, one container per replica. |
```

Elastic table, replace:

```
| core_service | environment | AWS ECS Fargate task | A Fargate container running one of the project's [build_image]s from ECR. Rolled by ECS on image updates. |
```

with:

```
| core_service | environment | AWS ECS Fargate task | A Fargate container running one of the project's [build_image]s from ECR. One ECS service and task definition per [process type](./cicl.md#process-types), all referencing the codebase's single image; `desired_count` carries the replica count in `prod`. Rolled by ECS on image updates. |
```

### 3e. `telemetry_sidecar` rows — both tables

Fixed table, replace:

```
| telemetry_sidecar | environment | OTel Collector | Collector sidecar, distinct compose container for each [service] sharing at least one of its networks. Accepts telemetry signals from the [service] and forwards to [observability_backend] |
```

with:

```
| telemetry_sidecar | environment | OTel Collector | Collector sidecar, one distinct compose container per *emitted* [core_service] container — i.e. per non-`scheduler` process type, and per replica. It is paired by network namespace (`network_mode: service:<container>`), not by shared network, so it always reaches its partner on loopback. Accepts telemetry signals from the [core_service] and forwards to [observability_backend] |
```

Elastic table, replace:

```
| telemetry_sidecar | environment | OTel Collector | Collector sidecar, paired with a [service] in a task definition. Accepts telemetry signals from the [service] and forwards to [observability_backend] |
```

with:

```
| telemetry_sidecar | environment | OTel Collector | Collector sidecar, one container inside each task definition that also runs an ECS service — so one per non-`scheduler` [process type](./cicl.md#process-types), and one per running replica. Accepts telemetry signals from the [core_service] and forwards to [observability_backend] |
```

### 3f. § Shape and Environment

Replace:

```
Furthermore, `test` and `dev` never have "replica" containers - only one container per role, per environment.
```

with:

```
Furthermore, `test` and `dev` never have "replica" containers - only one container per [process type](./cicl.md#process-types), per environment.
```

### Self-check 3

```bash
grep -n "multiple workers\|doubles as a load balancer\|per role, per environment" doctrine/infrastructure/shape.md   # expect no hits
grep -n "load.balanc" doctrine/infrastructure/shape.md   # every hit must be qualified by `web` or by service_discovery
```

---

## Step 4 — `doctrine/infrastructure/shape.md` (part 2: § Concrete Example)

Convert the example and its two compiled walk-throughs to CICL v2. **Minimal
conversion: keep one `api` codebase with one `web` process type.** Do not add a
worker.

### 4a. The `infra.yml` block

Replace the whole fenced yaml block (currently `cicl_version: "1"` …
`networks: [internal]`) with:

```yml
cicl_version: "2"
foundation: elastic
apex_domain: "example.com"
domain_default_process: api.web
repo_url: "https://github.com/owner_account/project_name"

core_services:
	api:
		env:
			DATABASE_HOST: ${backing_services.database.host}
			DATABASE_PORT: ${backing_services.database.port}
			DATABASE_NAME: ${backing_services.database.db}
			DATABASE_USER: ${backing_services.database.user}
			DATABASE_PASSWORD: ${backing_services.database.password}
		processes:
			web:
				role: web
				command: ["python", "-m", "entrypoints.http"]
				port: 8080
				networks: [web, internal]
				depends_on: [database]
				resources:
					cpu: 1.0
					memory: 2GB
					disk: 20GB

backing_services:
	database:
		role: relational_db
		engine: postgres
		version: "15"
		networks: [internal]
		schema_owned_by: api
```

Match the file's existing indentation style (this file uses **tabs** inside the
yaml fence — check the surrounding block and copy it exactly).

Note three additions the v1 example lacked and v2 requires: `command`,
`depends_on: [database]` (a service-level `env:` magic ref obliges every process
type to declare the edge), and `schema_owned_by: api` is retained.

### 4b. § Compiled for `dev`, Environment infrastructure bullet

Replace:

```
- An `api` container on both networks (no published host port), with Traefik labels routing both `dev.myproject.example.com` (it's the `domain_default_service`) and `api.dev.myproject.example.com` to it, plus `DATABASE_*` env for internally constructing the db url
```

with:

```
- An `api-web` container on both networks (no published host port), with Traefik labels routing both `dev.myproject.example.com` (it's the `domain_default_process`) and `api-web.dev.myproject.example.com` to it, plus `DATABASE_*` env for internally constructing the db url
- An `api-exec` container, profile-gated so `up` never starts it — the per-codebase one-off container `build`, `test`, and `migrate` run inside
```

### 4c. § Compiled for `dev`, the paragraph after the bullets

Replace `the `api` container's labels` with `the `api-web` container's labels`,
and `` `api.dev.myproject.example.com` `` with
`` `api-web.dev.myproject.example.com` ``.

### 4d. § Compiled for `prod`, Environment infrastructure bullets

- `1 ECS service for `api`` → `1 ECS service for `api-web``
- `1 ALB target group for the prod `api` service` → `... for the prod `api-web`
  process type`
- the host-header set `api.prod.myproject.example.com` →
  `api-web.prod.myproject.example.com`
- Add one bullet after the ECS service bullet:
  `- 1 migration ECS task definition for the `api` codebase (family `myproject-prod-api-migrate`), run as a one-off `RunTask` at release`

### 4e. § Compiled for `prod`, Production-side project infrastructure

`- ECR repo for the `api` image` — leave as is; it is already codebase-keyed and
correct. Optionally append `(one repo per codebase, shared by every process
type)`.

### 4f. § Compiled for `prod`, the closing paragraphs

Replace `The `api` service runs in the master VPC's` with `The `api-web` service
runs in the master VPC's`, and `` `api` composes its own connection string `` with
`` `api-web` composes its own connection string ``.

### Self-check 4

```bash
grep -n 'cicl_version: "1"\|domain_default_service' doctrine/infrastructure/shape.md   # expect no hits
grep -n '`api`' doctrine/infrastructure/shape.md   # every surviving hit must be about the CODEBASE (image, ECR repo, migrate family, schema_owned_by)
grep -n 'api\.dev\.\|api\.prod\.' doctrine/infrastructure/shape.md   # expect no hits
```

---

## Step 5 — `doctrine/infrastructure/tests.md`

§ Staging Tests, replace:

```
+ Liveness Checks - Each core service responds to its [health-check endpoint](./contracts.md#health-checks).
```

with:

```
+ Liveness Checks - Each `web`-network process type responds to its own `GET /health` at its own hostname. Process types that are not on `web` are not reachable from the stage tester at all, so their liveness is asserted through the `/health/<service>/<process>` [fan-out](./contracts.md#fan-out) on the `web` process type that `consumes` them. `scheduler` process types are exempt — they have no long-running container to probe.
```

### Self-check 5

```bash
python3 /tmp/mod106_linkcheck.py doctrine   # the new #fan-out anchor must resolve
```

---

## Step 6 — `doctrine/infrastructure/telemetry.md`

### 6a. § Collector Sidecar (~`:84`)

Replace:

```
The telemetry signals hit the OTel Collector sidecar. This sidecar is a dedicated container running `otelcol`; there is one per core service container. The sidecar runs in a special subgroup with its parent container - in ECS this is a "task".
```

with:

```
The telemetry signals hit the OTel Collector sidecar. This sidecar is a dedicated container running `otelcol`; there is one per *emitted* core service container — that is, one per [process type](./cicl.md#process-types), and one per replica. `scheduler` process types are the exception and get none: a cron job is short-lived and has no long-running container to pair with. The sidecar runs in a special subgroup with its parent container - in ECS this is a "task".
```

### 6b. § Resource Attributes and Env Vars, item 1

Replace:

```
1. OTEL_SERVICE_NAME - Simply the name of the service in `infra.yml`. OTel SDK will automatically include this as the `service.name` resource attribute.
```

with:

```
1. OTEL_SERVICE_NAME - The process type's two-segment compiled identity, `<core_service>-<process>` (e.g. `api-web`). OTel SDK will automatically include this as the `service.name` resource attribute. Per process type is the OTel-correct granularity: the semantic convention requires `service.name` to be identical across horizontally-scaled instances, so it must not vary per replica, and a codebase's web edge and queue consumer are genuinely different services.
```

### 6c. § Resource Attributes and Env Vars, item 4

Replace:

```
4. OTEL_RESOURCE_ATTRIBUTES - Additional attributes the SDK will automatically set. `docex` will use: `service.namespace=${project_name},service.version=${project_version},deployment.environment.name=${env_name}`.
```

with:

```
4. OTEL_RESOURCE_ATTRIBUTES - Additional attributes the SDK will automatically set. `docex` will use: `service.namespace=${project_name},service.version=${project_version},deployment.environment.name=${env_name},docex.core_service=${core_service},docex.process_type=${process}`. The last two carry the two axes `service.name` fuses, so each is independently queryable — a hyphenated `service.name` cannot be decomposed, since a service name and a process name may each contain `-`. See [transfer_tables.md § Per-core-service env](./specifics/transfer_tables.md#per-core-service-env-both-foundations) for the canonical table, including the per-codebase artifacts on which `docex.process_type` is absent.
```

### 6d. § During Development (~`:125`)

Replace `` `docker compose logs <svc>-otelcol` `` with
`` `docker compose logs <svc>-<proc>-otelcol` ``.

### Self-check 6

```bash
grep -n "otelcol" doctrine/infrastructure/telemetry.md   # must show <svc>-<proc>-otelcol
grep -n "one per core service container" doctrine/infrastructure/telemetry.md  # expect no hits
python3 /tmp/mod106_linkcheck.py doctrine
```

---

## Step 7 — `doctrine/infrastructure/specifics/scheduler.md`

The heaviest file. Do not rename headings.

### 7a. Opening framing (`:7-16`)

Rewrite the intro paragraph so the subject is a **process type**, keeping its
shape and its closing pointer. Target content: the `scheduler` role is how
`docex` runs a project's own code on a recurring cron schedule rather than as a
continuously-serving process; a `scheduler` **process type** declares a `command`
and a `schedule`, and `docex` arranges for that command to run, in the
**codebase's** image, on that schedule, with the codebase-and-process env/secret
surface any process type of that env receives. Keep the final sentence pointing
at `cicl.md § Service Fields` (and add `cicl.md § Process Types` alongside it).

### 7b. § What a scheduler service is

Rewrite the first paragraph: a `scheduler` **process type** is one way of
invoking a core service's image (the project's own code, one image per codebase)
whose `role:` is `scheduler`. Unlike a `web` process type it does not serve HTTP,
may not declare the `web` network (rule 27), and has no long-running container or
ECS service. Keep the "Think 'cron job in the project's image'" sentence.

Replace the yaml example with (match the file's 2-space yaml indent):

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

Add a short note after it: the codebase is named `jobs` and the process type is
named for the job, per `cicl.md § Naming convention` — a codebase commonly has
several jobs, and naming the codebase after one job compiles to a doubled
identity like `nightly_cleanup-nightly_cleanup`.

Then replace:

```
The image is derived exactly as for any core service (per
[cicl.md § Container Registry](../cicl.md#container-registry-and-service-images)):
a local build tag in `dev`/`test`, the registry ref in `stage`/`prod`. The
`resources:`, `env:`, `secrets:`, and `depends_on:` fields behave identically to
a `web` core service. Only the trigger differs.
```

with a version stating: the image is derived exactly as for any core service and
is keyed on the **codebase** (per the same link) — a local build tag in
`dev`/`test`, the registry ref in `stage`/`prod` — so a job and its sibling `web`
process type run **one** tag. `resources:`, `networks:`, `depends_on:` and the
`env:`/`secrets:` surface behave identically to a `web` process type. Only the
trigger differs.

### 7c. § Cron format, closing paragraph

Replace `` `schedule:` is required for the `scheduler` role and rejected on every
other role `` — keep the sentence but make the subject the process type, and note
`command:` is required on **every** process type now (per `cicl.md`), so the
scheduler-specific half of that claim is no longer distinguishing.

### 7d. § Fixed Foundation — Ofelia

Replace:

```
For a scheduler service `<svc>`, `docex compile` emits one compose service
`<project>-<env>-<svc>-scheduler` running `mcuadros/ofelia:<digest>` (pinned by
digest, like every doctrine-shipped image). It:
```

with:

```
For a `scheduler` process type `<proc>` of core service `<svc>`, `docex compile`
emits one compose service `<project>-<env>-<svc>-<proc>-scheduler` running
`mcuadros/ofelia:<digest>` (pinned by digest, like every doctrine-shipped image).
One trigger per process type, so a codebase with three jobs gets three. It:
```

In the following bullet, `` (`ofelia-<svc>.ini`) `` → `` (`ofelia-<svc>-<proc>.ini`) ``.

Replace:

```
The rendered INI declares one `[job-run "<svc>"]` section.
```

with:

```
The rendered INI declares one `[job-run "<svc>-<proc>"]` section, keyed on the
two-segment compiled identity.
```

Update the INI sample so it is consistent with the `jobs` / `nightly_cleanup`
example:

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

Add a subsection-free paragraph immediately after the INI block (no new heading):

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
```

### 7e. § Env and secret delivery — first sentence

Replace "the **same env-and-secret surface a normal core service of that env
sees**" with "the **same env-and-secret surface a normal process type of that env
sees**", and adjust `the service's `env:`` to `the process type's effective
`env:` (codebase-scoped merged under process-scoped)`.

### 7f. § Elastic Foundation — first sentence

Replace `On elastic a scheduler service compiles to two emit destinations` with
`On elastic a `scheduler` process type compiles to two emit destinations`. In
bullet 1, `the same task-def machinery a `web` service uses` →
`` a `web` process type uses ``, and `the per-(env,service) CloudWatch group` →
`the per-(env, codebase) CloudWatch group`. In bullet 3, `One role per scheduler
service in v1` → `One role per `scheduler` process type in v1`.

Also in bullet 1, the sidecar sentence: `it is paired only with long-running
services (those that also emit `ecs_service`)` → `...long-running process types
(those that also emit `ecs_service`)`. Add: consequently a codebase with a `web`
process type and a nightly job gets exactly one sidecar — for the web process —
which the old per-service phrasing could not express.

Also note the scheduler's task-level Fargate sizing carries **no** sidecar
overhead, since there is no sidecar to allow for; link
`telemetry_infra.md § Task-Level Resource Allocation`.

### 7g. § Lifecycle and idempotency

`the Ofelia container comes up with the env stack` — fine. Adjust `no Ofelia
container is emitted for it, so its stack carries no scheduler at all` to name
the process type.

### 7h. § Caveats — **delete the `test.sh` carve-out**

In the first caveat, delete this sentence entirely:

```
`docex test` still runs a scheduler's `test.sh`: since there is no `test`-stack container to `exec` into, docex builds the service's `test`-stage image and runs `test.sh` as a one-off container (no env-tier stack attached), so keep a scheduler's tests self-contained unit/module tests.
```

Replace it with:

```
`docex test` runs a scheduler's `test.sh` through the same path as every other codebase — a one-off container of that codebase's exec service — so there is no scheduler carve-out and a scheduler-only codebase needs no special handling. Because the trigger is dropped in `test`, a `scheduler` process type contributes nothing to the `test` stack at all: a scheduler-only codebase's only compose block there is its exec service. Exercise a job's logic through its own unit/module tests, or in `dev`.
```

Also fix the earlier sentences in the same caveat that say "the compiler emits no
Ofelia container for a scheduler service" → process type, and "The scheduler
service is otherwise inert in every env" → process type.

### Self-check 7

```bash
grep -n "scheduler service\|scheduler's service\|<svc>-scheduler\|job-run \"<svc>\"\|exec into\|container to \`exec\` into" doctrine/infrastructure/specifics/scheduler.md
# expect no hits
grep -n "role: scheduler" doctrine/infrastructure/specifics/scheduler.md   # must be indented under processes:
python3 /tmp/mod106_linkcheck.py doctrine
```

---

## Step 8 — `doctrine/infrastructure/specifics/transfer_tables.md`

### 8a. § Available compile-time variables — `${name}`

Replace:

```
| `${name}` | The simple service name from `infra.yml` (e.g., `database`). |
```

with:

```
| `${name}` | The service's identity as the compiler keys it: the simple `infra.yml` name for a backing service (e.g. `database`), and the two-segment compiled identity for a core [process type](../cicl.md#process-types) (e.g. `api-web`). |
```

### 8b. § Per-container (fixed)

Keep the invariant yaml block as-is (it is still literally what every compose
service receives), but replace the sentence introducing it,
`Every compose service receives:`, with `Every compose service receives — for a
core service, once per [process type](../cicl.md#process-types):`.

Then, after the `docex.project` label paragraph, insert:

```
**Under a replica unroll the shape shifts, and only then.** When a process type
declares `replicas: N` and the count is in effect (`prod` only), the compiler
emits N services keyed `${global_service_name}-<i>`, each with its own
`container_name`, and rewrites `networks:` from compose's short-form list into
map form to carry a **shared alias** equal to the unqualified
`${global_service_name}` on every network. Docker DNS round-robins that alias
across the N containers, which is what keeps `provides.host` meaning the same
thing whether a process type has one replica or four. Outside that case there is
no `aliases` handling and the short-form list is emitted unchanged.
```

Then, after the traefik label yaml block, insert:

```
**The traefik labels are keyed on the unqualified `${global_service_name}`, and
must stay that way.** Under a replica unroll, N containers therefore declare the
*same* router and the *same* service, and traefik's docker provider loads them as
N servers behind one router — which is how the reverse proxy load-balances a
`web` process type's replicas. Qualifying the labels per replica would instead
produce N routers fighting over one `Host()` rule.
```

Finally, replace:

```
`${host_rule}` is the per-service host rule derived from [cicl.md § Domain](../cicl.md#domain) — `Host(\`${service}.${env}.${project}.${apex_domain}\`)`, with the additional bare-env / bare-project rules for the `domain_default_service` in prod.
```

with:

```
`${host_rule}` is the per-process-type host rule derived from [cicl.md § Domain](../cicl.md#domain) — `Host(\`${service}-${process}.${env}.${project}.${apex_domain}\`)`, with the additional bare-env / bare-project rules for the `domain_default_process` in prod.
```

### 8c. § Per-core-service env

In the table, replace the `OTEL_SERVICE_NAME` row:

```
| `OTEL_SERVICE_NAME` | The service's `infra.yml` name | `infra.yml` `core_services.<name>` key |
```

with:

```
| `OTEL_SERVICE_NAME` | The process type's compiled identity, `<core_service>-<process>` | `infra.yml` `core_services.<svc>.processes.<proc>` keys, hyphen-joined |
```

And replace the `OTEL_RESOURCE_ATTRIBUTES` row's value cell so it reads:

```
`service.namespace=${project_name},service.version=${project_version},deployment.environment.name=${env_name},docex.core_service=${core_service},docex.process_type=${process}`
```

(keep the Source cell, extending it to note the two `docex.*` attributes are the
process expansion's two axes made independently queryable).

Then, after the paragraph beginning "The four `OTEL_*` variables are the OTel
SDK's standard auto-discovery surface", insert:

```
**There are two identity forms, not one.** The table above describes the surface
a **process type**'s container receives. The compiler also emits two artifacts
that belong to the **codebase** rather than to any process type — the per-codebase
exec container and the elastic migration task definition — and those carry a
*de-qualified* identity:

| Key | process-type surface | per-codebase surface |
| --- | -------------------- | -------------------- |
| `OTEL_SERVICE_NAME` | `api-web` — the compiled identity | `api` — the **authoring** core service name |
| `docex.core_service` | `api` | `api` |
| `docex.process_type` | `web` | *absent* |

The per-codebase value is the authoring name (`api`), deliberately **not** the
global name (`myproject-prod-api`): it matches the migrate container's `name` and
the CloudWatch log group, both codebase-keyed, exactly as the process surface
carries the compiled two-segment name rather than the global one.

**`docex.process_type`'s presence is the signal.** It is set if and only if the
emitter is a declared process type, so its absence identifies a per-codebase
artifact rather than a value someone forgot to fill in. Stamping the identity
before the surfaces split would give a migration the name of whichever process
type happened to sort first — an identity that moves when an unrelated process
type is renamed.
```

### 8d. § Per-resource (elastic) — the envinfra tag block

Replace the tags block:

```hcl
tags = {
	managed_by = "doctrine"
	infra_tier = "environment"
	shape_name = "${shape_name}"   # core_service | backing_service
	descriptor = "${descriptor}"   # e.g. RDS, S3, ecs-svc, task-def
	project    = "${project_name}"
	env        = "${env_name}"
	service    = "${name}"
	role       = "${role_name}"
	Name       = "${project_name}_${env_name}_${name}"
}
```

with:

```hcl
tags = {
	managed_by = "doctrine"
	infra_tier = "environment"
	shape_name = "${shape_name}"   # core_service | backing_service
	descriptor = "${descriptor}"   # e.g. RDS, S3, ecs-svc, task-def
	project    = "${project_name}"
	env        = "${env_name}"
	service    = "${core_service_name}"
	process    = "${process_name}"  # core process types only; key OMITTED otherwise
	role       = "${role_name}"
	Name       = "${project_name}_${env_name}_${core_service_name}_${process_name}"
}
```

And extend the paragraph after it with:

```
The `process` tag is present only on resources belonging to a specific core
service process type. For a backing service — and for the per-codebase migration
resources — the key is **omitted entirely** rather than emitted empty, which is
what keeps a backing service's tag block byte-identical to its pre-process-expansion
form; `Name` then falls back to `${project}_${env}_${service}`. Note the joiner
here is `_`, not `-`: this is a tag value, not a data-plane name.
```

### 8e. § Anatomy of a Role Definition — the `emits` field reference

In the `**emits**` bullet, extend the parenthetical list of destination examples
to include `container_definition`, described as a merge target rather than a
resource. Suggested insertion into that parenthetical, after the
`scheduled_task` example:

```
; `container_definition` → **not a resource at all but a merge target**: its renderer emits nothing, and a field routed to it is merged into the ECS *container* definition the `task_definition` destination already builds. This is how a `worker` gets a container-level `healthCheck`, since it has no target group to hang one on
```

### 8f. § Authoring Project-Local Transfer Tables — bundled engine list

Replace:

```
`relational_db/postgres`, `cache/redis`, `object_store/{minio,s3}`, `web/container`, `scheduler/container` (cron-triggered jobs — see [scheduler.md](./scheduler.md))
```

with:

```
`relational_db/postgres`, `cache/redis`, `object_store/{minio,s3}`, `web/container`, `worker/container` (long-running non-HTTP process types — queue consumers, stream processors), `scheduler/container` (cron-triggered jobs — see [scheduler.md](./scheduler.md))
```

### 8g. § Resources Translation

- Opening sentence: `The project's per-service [`resources:` block]` →
  `per-process-type`.
- § Fixed: `For each core service, the compiler emits:` → `For each core service
  process type, the compiler emits:`
- § Elastic: `For each core service, the compiler computes` → `For each core
  service process type, the compiler computes`
- In step 1 of the elastic computation, after "and any doctrine-fixed sidecar
  overhead", add: "— which applies only to process types that actually get a
  sidecar, so a `scheduler` (no `ecs_service`, no sidecar) pays none".
- § Tier rounding paragraph: `**Tier rounding is uniform across all core
  services**` → `across all core service process types`.
- Add one sentence at the end of § Elastic: "The overhead is paid once **per task
  definition**, i.e. once per process type, so a codebase with three process
  types pays it three times and each rounds to its own tier independently."

### 8h. § Depends-on emission (fixed)

The parenthetical `` (or `compose exec` from `./bin/docex up`) `` is stale.
Replace with `` (or a `compose run` one-off from `./bin/docex envinfra up`) ``.

### Self-check 8

```bash
grep -n "domain_default_service\|compose exec" doctrine/infrastructure/specifics/transfer_tables.md   # expect no hits
grep -n "process_name\|docex.process_type" doctrine/infrastructure/specifics/transfer_tables.md       # expect hits
python3 /tmp/mod106_linkcheck.py doctrine skills
```

---

## Step 9 — `doctrine/infrastructure/specifics/migrations.md`

### 9a. § Source of Truth

`Each backing service whose role uses `schema_owned_by` … names a core service`
is still correct — `schema_owned_by` names a codebase. Leave it, but in the
`core/<service>/` block comment and the following paragraph make explicit that
migration is a **per-codebase** operation: `migrate.sh` runs once per codebase,
never once per process type.

### 9b. § Invocation Timing, final paragraph

`migration runs as a separate process invocation against the service's image` →
`against the codebase's image`.

### 9c. § Dev and Test Mechanism — rewrite the section body

Replace:

```
For `dev` and `test` envs, on both foundations, `./bin/docex migrate <env>` runs `migrate.sh` inside each schema-owning core service's already-running container via `docker compose exec`:

```bash
docker compose -f infra/output/<env>/docker-compose.yml \
    exec <service> /service/migrate.sh
```

The service's container is already up (it was brought up by `./bin/docex envinfra up <env>` or `./bin/docex test`), already on the env's internal network, and already carries the runtime env vars the shim needs to reach the database. `docker compose exec` reuses all of that — no separate container, no separate network attachment, no env-var rendering.

The exec runs in the service's `dev`-stage (or `test`-stage) container, which carries the build tools and any migration-tool dependencies the project's `Dockerfile` declares for development. The application process itself keeps running while the exec is in flight; `migrate.sh` is invoked as an independent process inside the same container.
```

with:

```
For `dev` and `test` envs, on both foundations, `./bin/docex migrate <env>` runs `migrate.sh` as a one-off container of each schema-owning **codebase's** exec service:

```bash
docker compose -f infra/output/<env>/docker-compose.yml \
    run --rm <project>-<env>-<core_service>-exec ./migrate.sh
```

(`./migrate.sh` is relative because the image's working directory is the fixed `/service` root — see [Core Service Containers](../infrastructure.md#core-service-containers). `--build` is added in `test` only; `dev` reuses the existing image.)

The exec service is the compiled block that *is* the codebase: one per core service, carrying the codebase's image, the dev bind mounts in `dev`, the union of the codebase's non-`web` networks, and the union of its `depends_on` rewritten to `condition: service_healthy`. Two properties matter here:

- **Nothing needs to be running.** The exec service is gated behind `profiles: [exec]` so `compose up` never starts it, while `compose run` implicitly enables the profile of the service it names. And because it gates on its backing services' healthchecks, the one-off waits for the database instead of assuming the stack is already up.
- **It carries service-level `env:` only** — never a process type's overlay. That is what makes *`migrate.sh`, `test.sh`, and `build.sh` may depend only on codebase-scoped env* an enforceable rule rather than a convention: a process-scoped key is not discouraged there, it is absent. A migration has no business reading a worker's concurrency knob, and now it cannot.

This also removes a question that has no good answer. A codebase with several [process types](../cicl.md#process-types) offers no principled way to pick one of their containers to `exec` into, and any rule for choosing a representative moves the migration's environment when an unrelated process type is renamed.
```

Adjust the following retry paragraph: `Since the env is unchanged otherwise,
retry is just another exec` → `retry is just another one-off run`.

### 9d. § Stage and Prod on Fixed Foundation

Replace the pseudo-playbook block with the emitted form:

```yaml
# Pseudo-playbook step
- name: Run migrations for {{ svc.codebase }}
  ansible.builtin.command:
    cmd: >-
      docker compose -p {{ compose_project_name }}
      run --rm {{ svc.exec_service }} /service/migrate.sh
  loop: "{{ codebases_with_schema }}"
```

Then replace the paragraph after it:

```
For each schema-owning core service, a one-off container runs `migrate.sh` using the new image. The container joins the project's existing internal network to reach the database, reads its env vars from the rendered `.env`, and exits with a status code. The old service containers are still running and serving traffic against the (about-to-be-migrated) database — see [Backward Compatibility](#backward-compatibility-requirement) below.
```

with:

```
For each schema-owning codebase, `compose run` starts a one-off container of that codebase's exec service using the new image. Routing production migration through the *same* exec service `dev` and `test` use is what makes the codebase-scoped-env rule hold everywhere: a rule that lapsed in `stage`/`prod` would not be a rule. The container inherits the exec service's networks and `depends_on` gates, reads its env vars from the rendered `.env`, and exits with a status code. The old service containers are still running and serving traffic against the (about-to-be-migrated) database — see [Backward Compatibility](#backward-compatibility-requirement) below.

Note the path is absolute here (`/service/migrate.sh`) while `dev`/`test` use the relative `./migrate.sh`. Both resolve to the same script; the absolute form is used where the command is rendered into a playbook rather than issued against a known working directory.
```

### 9e. § Stage and Prod on Elastic Foundation

Replace the opening:

```
For `stage`/`prod` on elastic projects, the compiler emits a separate "migration" ECS task definition for each schema-owning core service. Both the migration task definition and the main service task definition reference the same image — the difference is the command:
```

with:

```
For `stage`/`prod` on elastic projects, the compiler emits one "migration" ECS task definition per schema-owning **codebase** — family `${project}-${env}-${codebase}-migrate`, not one per process type, since `migrate.sh` runs once per codebase. Its sizing is the per-dimension **maximum** across the codebase's process types, which is order-independent (so the migration cannot be resized by renaming or adding an unrelated process type) and never under-provisions. Its environment is the codebase-scoped surface only, matching the fixed path. The migration and the application task definitions reference the same image — the difference is the command:
```

In the numbered sequence, `for each service with a schema` → `for each codebase
with a schema`, and in § First-Time Release adjust `the env's ECS services, RDS,
and migration task definition` (still fine) but check for any per-service
phrasing.

### 9f. § Caveats

First caveat: `names exactly one core service` is correct (a codebase). Add a
clause making it explicit that `schema_owned_by` names a **codebase, never a
process type**.

### Self-check 9

```bash
grep -n "compose exec\|exec <service>\|another exec" doctrine/infrastructure/specifics/migrations.md   # expect no hits
grep -n "migrate.sh" doctrine/infrastructure/specifics/migrations.md   # both ./migrate.sh and /service/migrate.sh present, each in the right section
python3 /tmp/mod106_linkcheck.py doctrine
```

---

## Step 10 — `doctrine/infrastructure/specifics/telemetry_infra.md`

### 10a. § Per-Env Exporter Configuration (`:57`)

`docker compose logs -f <svc>-otelcol` → `docker compose logs -f <svc>-<proc>-otelcol`.

### 10b. § Env Vars Injected on Core Services

Update the `OTEL_SERVICE_NAME` and `OTEL_RESOURCE_ATTRIBUTES` rows to match
Step 8c **verbatim** in value. Change the section's opening sentence from
`Every core service receives` to `Every core service **process type** receives`,
and add one sentence pointing at
`transfer_tables.md § Per-core-service env` for the two per-codebase artifacts
whose identity is de-qualified.

### 10c. § Failure Modes table (`:163`)

`docker compose logs <svc>-otelcol` → `<svc>-<proc>-otelcol`.

### 10d. § Fixed → § Sidecar as Paired Compose Service

Replace:

```
For each core service `<svc>`, `docex compile` emits an additional compose service named `<svc>-otelcol`. The sidecar shares the core service's network namespace via compose's `network_mode: "service:<svc>"` — it does not declare its own `networks:` (mutually exclusive with `network_mode`).
```

with:

```
For each **emitted** core service container, `docex compile` emits an additional compose service named `<container>-otelcol`. For a process type `<proc>` of core service `<svc>` that is the container `<svc>-<proc>`, so the sidecar is `<svc>-<proc>-otelcol`; under a [replica unroll](../shape.md#fixed-foundation) each replica `<svc>-<proc>-<i>` gets its own `<svc>-<proc>-<i>-otelcol`. The pairing is therefore strictly 1:1, which is exactly why compose's `deploy.replicas` cannot be used — it has no replica-to-replica pairing semantics, so one sidecar could not serve N replicas.

A `scheduler` process type gets **no** sidecar: there is no long-running container to pair with. So a codebase with a `web` process type and a nightly job emits one sidecar, for the web process — something the pre-expansion, per-service phrasing could not express.

The sidecar shares its partner's network namespace via compose's `network_mode: "service:<container>"` — it does not declare its own `networks:` (mutually exclusive with `network_mode`).
```

In the illustrative yaml block, replace `<svc>-otelcol:` → `<svc>-<proc>-otelcol:`,
`container_name: ${project}-${env}-<svc>-otelcol` →
`container_name: ${project}-${env}-<svc>-<proc>-otelcol`, and
`network_mode: "service:<svc>"` → `network_mode: "service:${project}-${env}-<svc>-<proc>"`.

### 10e. § Fixed → § Service Discovery and § Healthcheck and Startup Ordering

Replace the remaining `service:<svc>` and `<svc>-otelcol` literals in these two
sections with the `<svc>-<proc>` forms. The reasoning in both is unchanged and
must be preserved verbatim apart from the identifiers.

### 10f. § Elastic → § Sidecar as Paired Task Container

Replace:

```
For each core service `<svc>`, the ECS task definition contains two containers: the application container and an `<svc>-otelcol` container. They share the task netns. There is no separate ECS service for the sidecar.
```

with:

```
For each core service **process type** that also runs an ECS service, the task definition contains two containers: the application container and an `<svc>-<proc>-otelcol` container. They share the task netns. There is no separate ECS service for the sidecar, and N replicas give N sidecars automatically, because the collector is a container *inside* the task definition.

Two task definitions carry no sidecar: a `scheduler` process type's (it emits no `ecs_service` — nothing runs continuously) and the per-codebase migration task definition.
```

In the illustrative HCL, `<svc>` → `<svc>-<proc>` and `<svc>-otelcol` →
`<svc>-<proc>-otelcol`.

### 10g. § Elastic → § Container Dependencies and Essentiality

Same identifier substitution in the `dependsOn` block and its prose.

### 10h. § Elastic → § Task-Level Resource Allocation

Keep both existing arithmetic paragraphs verbatim — they are correct. Append:

```
**The overhead is per task definition, so it is per process type.** A codebase
with a `web` and a `worker` process type produces two task definitions and pays
the 0.1 vCPU / 128 MB twice, each rounding to its own Fargate tier independently;
sizing is declared per process type, so this is the intended shape rather than a
surprise. A `scheduler` process type pays it **zero** times, since it emits no
ECS service and therefore has no sidecar to allow for.

On fixed there is no tier arithmetic, but the same count applies: the number of
collectors in an env is the **sum**, over each non-`scheduler` process type, of
that process type's effective replica count. It is a sum and not a product,
because `replicas` is declared per process type — a `web` with `replicas: 3`
alongside a single `worker` yields four collectors, not six.
```

### Self-check 10

```bash
grep -n '<svc>-otelcol\|service:<svc>"' doctrine/infrastructure/specifics/telemetry_infra.md   # expect no hits
grep -n "N × R\|N x R" doctrine/infrastructure/specifics/telemetry_infra.md   # expect no hits — it is a sum
python3 /tmp/mod106_linkcheck.py doctrine
```

---

## Step 11 — `doctrine/infrastructure/specifics/networks.md`

**Do not rename any heading**, including
`## Per-Service Attachment by Name`, `### `networks: [web]``, and
`### `networks: [internal]` (and any other non-special name)`. They are linked
from `infra-compile`, `transfer_tables.md`, and `shape.md`.

Edits, all prose-internal:

1. `:7` — `**env-tier per-service network attachment**` →
   `**env-tier per-process network attachment**`, and later in the same sentence
   `which docker networks a container joins` is fine.
2. Tier table, Envinfra row — `per-service network attachment` →
   `per-process (and per-backing-service) network attachment`.
3. `:19` — `Per-service network attachment is what the compiler decides on the
   basis of each service's `networks:` list in `infra.yml`.` →
   `... on the basis of each core service **process type**'s `networks:` list —
   and each backing service's. Membership is declared per process type, not per
   codebase: a codebase's web edge and its queue consumer routinely sit on
   different networks.`
4. § `networks: [web]` — first sentence, `A service on the `web` network is
   reachable … at the [domain] derived from its name, env, and project` →
   derived from its **two-segment identity** (`<service>-<process>`), env, and
   project. Add one clause noting a `worker` or `scheduler` process type may not
   declare `web` at all (rule 27).
5. § `networks: [internal]`, the Fixed bullet — after `reach it by container
   name, which equals `${global_service_name}``, append: `In `prod`, a process
   type declaring `replicas` is emitted as N containers and
   `${global_service_name}` becomes a **shared network alias** across all of
   them rather than any one container's name, so the same reference resolves
   round-robin.`

### Self-check 11

```bash
grep -n "^#" doctrine/infrastructure/specifics/networks.md   # heading text must be byte-identical to before
python3 /tmp/mod106_linkcheck.py doctrine skills
```

---

## Step 12 — `doctrine/infrastructure/cicl.md` (the ONE permitted edit)

Rule 7's scope. Two surgical additions; **no heading changes, no renumbering.**

### 12a. Rule 7

Append to rule 7, after the existing "See [Consumes Relationships]…" sentence:

```
 Rule 7 governs **process-type referencers**. A backing service that embeds a core process type's part — an `object_store` holding `${core_services.api.web.host}` as a CORS origin, say — cannot satisfy it at all: backing services have no `consumes:`, and rule 24 forbids them a `depends_on` to a core service. That is rule 7 correctly **not applying** rather than a gap, because a backing service embedding a core hostname is not *calling* it, so there is no readiness or interface implication for either relation to express.
```

### 12b. § Consumes Relationships → § Three clarifications

Append a fourth bullet to the existing list:

```
- **The rule binds referencers that *have* a relation to declare.** Both arms of rule 7 place the obligation on a process type, because a process type is the only thing that can hold a `consumes` or a `depends_on`. A backing service holding a core magic ref is outside the rule's reach by construction — see [rule 7](#validation-rules).
```

The heading says "Three clarifications" and there will now be four bullets. **Do
not rename the heading** (it is anchor-bearing); instead change the sentence that
introduces the list, or if there is none, leave the heading and accept the
count drift — flag it in your report and let the reviewer decide. Do **not**
rename it on your own initiative.

### Self-check 12

```bash
grep -c "^[0-9]\+\. " doctrine/infrastructure/cicl.md   # rule count unchanged (28 rules)
grep -n "Three clarifications" doctrine/infrastructure/cicl.md   # heading unchanged
python3 /tmp/mod106_linkcheck.py doctrine skills
git diff --stat doctrine/infrastructure/cicl.md   # must be small: rule 7 + one bullet only
```

---

## Step 13 — `doctrine/infrastructure/preinfra/fixed_master_network.md`

**Behavior is unchanged. Only the comment and the prose list are wrong.** Do not
alter the Lua code, the PSL logic, or any HAProxy config.

### 13a. The prose list (`:20`)

`1. `<service>.<env>.<project_name>.<apex_domain>`` →
`1. `<service>-<process>.<env>.<project_name>.<apex_domain>``

### 13b. The Lua header comment (`:105-108`)

Replace:

```lua
-- Expects requests in one of the three canonical doctrine forms:
--   <service>.<env>.<project>.<apex_domain>
--   <env>.<project>.<apex_domain>
--   <project>.<apex_domain>
```

with:

```lua
-- The canonical doctrine forms are:
--   <service>-<process>.<env>.<project>.<apex_domain>
--   <env>.<project>.<apex_domain>
--   <project>.<apex_domain>
--
-- The parse does not actually count them. It is right-anchored and has no
-- opinion about how many labels sit to the LEFT of the project, which is why
-- the service label gaining a process segment needed no change here.
```

### Self-check 13

```bash
grep -n "three canonical" doctrine/infrastructure/preinfra/fixed_master_network.md   # expect no hits
git diff doctrine/infrastructure/preinfra/fixed_master_network.md   # only comment + list lines
```

---

## Step 14 — Skills router nudges

`skills/infra-compile/SKILL.md` only. Two blurbs:

1. `[networks.md]` blurb — `how a service's `networks:` list becomes docker
   attachment (fixed) or security-group membership (elastic)` →
   `how a process type's `networks:` list becomes …`
2. `[scheduler.md]` blurb — `Read when adding a cron-style scheduled service.` →
   `Read when adding a cron-style scheduled process type.`

Change nothing else in any skill. Do **not** touch
`skills/chain-of-command/`, `skills/project-cohere/`,
`skills/transcript-summary/`, or `skills/skill-iteration/`.

---

## Step 15 — The four `projinfra/` specifics

**APPROVED — do this step.** (It is kept as its own step only so the projinfra
edits stay reviewable on their own; nothing in Steps 1–14 depends on it.)

All four carry `domain_default_service` — a field the compiler now rejects — and
the pre-advance 3-label hostname form.

1. `doctrine/infrastructure/specifics/projinfra/elastic_acm_certs.md:21` —
   `domain_default_service` → `domain_default_process`.
2. `doctrine/infrastructure/specifics/projinfra/fixed_reverse_proxy.md:112` —
   `domain_default_service` → `domain_default_process`; the per-cert domain
   `<service>.<env>.<project>.<apex_domain>` →
   `<service>-<process>.<env>.<project>.<apex_domain>`; `Each `web`-network
   service gets its own cert` → `Each `web`-network process type`.
3. `doctrine/infrastructure/specifics/projinfra/elastic_alb.md:64` —
   `domain_default_service` → `domain_default_process`; `this example assumes
   `api` is the project's ...` → `api.web`; `services that are not the default
   get only the full `<service>.<env>.<project>.<apex>` host` → `process types
   that are not the default get only the full
   `<service>-<process>.<env>.<project>.<apex>` host`.
4. `doctrine/infrastructure/specifics/projinfra/ec2_traefik.md:61,70` — both
   `domain_default_service` → `domain_default_process` (and `api` → `api.web` at
   `:61`); the 3-label host form → the 2-segment form; `Router names encode the
   env (`<service>-<env>`)` → `(`<service>-<process>-<env>`)` **only if you can
   confirm it against `emit/hcl.py`** — if you cannot confirm it, leave that
   clause alone and report it. And `port-less workers and backing services are
   never exposed` → replace the `port-less workers` premise, which no longer
   holds (the `worker` role provides a `port`, and rule 28 requires one alongside
   `health_check_path`); the true reason is that only containers carrying
   `traefik.enable=true` are routed, and the compiler emits that label only for
   `web`-network process types.

### Self-check 15

```bash
grep -rn "domain_default_service" doctrine/ skills/   # expect no hits
python3 /tmp/mod106_linkcheck.py doctrine skills
```

---

## Step 16 — Final verification

```bash
cd /home/ubuntu/.claude/jean_baudrillard

# 1. No code, table, or test was touched.
#    NOTE: the baseline is NOT clean here — `docex/tests/unit/test_pipeline_projinfra.py`
#    is already modified in /tmp/mod106_before.txt and is NOT yours. So compare, don't grep:
git status --porcelain | grep -E 'docex/src/|docex/tests/|docex/tables/' \
  > /tmp/mod106_code_after.txt
grep -E 'docex/src/|docex/tests/|docex/tables/' /tmp/mod106_before.txt \
  > /tmp/mod106_code_before.txt
diff /tmp/mod106_code_before.txt /tmp/mod106_code_after.txt   # MUST be empty (no new entries)

# 2. The unit suite is unchanged.
python3 -m pytest docex/tests/unit -q 2>&1 | tail -3    # MUST be exactly 982 passed

# 3. Links.
python3 /tmp/mod106_linkcheck.py doctrine skills        # MUST be the same 3 baseline items, no more

# 4. Retired vocabulary is gone from doctrine/ and skills/.
grep -rn "domain_default_service" doctrine/ skills/                      # empty
grep -rn '<svc>-otelcol' doctrine/ skills/                               # empty
grep -rn "directed acyclic graph" doctrine/ skills/                      # empty
grep -rn 'cicl_version: "1"' doctrine/                                   # empty
grep -rn "compose exec" doctrine/ skills/                                # empty
grep -rn "scheduler service" doctrine/ skills/                           # empty

# 5. Nothing of the operator's moved.
git status --porcelain | grep -E 'practices/modifications|doctrine/chain|charts/configurable|practices/advance|skill-iteration|chain-of-command|project-cohere|transcript-summary'
# MUST match the baseline entries for those paths exactly — same status letters, no new ones
```

Then diff the full working tree against `/tmp/mod106_before.txt`. Every new entry
must be a `doctrine/` or `skills/infra-compile/` file from Steps 1–15, plus the
two new files in `docex/plans/modifications/106_conditional_stratum_sweep/`.

**Report, explicitly:**
- the unit-suite number;
- the link-audit result;
- any place where the described edit did not match the file's actual text (this
  means the plan was written against a different state — stop and report rather
  than improvising);
- any code, table, or test change you believe is needed but did **not** make.
