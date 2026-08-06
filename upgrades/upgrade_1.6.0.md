---
version: "1.6.0"
severity: minor
kind: incremental
scope: [machine, project]
---

# Upgrading to doctrine 1.6.0

This release makes a core service a **codebase** that declares **N process
types**. One source tree, one build artifact, one image — started N different
ways, each with its own role, `command`, port, networks, and resources. A web
edge, a queue consumer, and a nightly job can all be the same image.

The `processes:` block is **mandatory and non-empty** on every core service.
There is no flat form and no single-process shorthand, which is what makes every
emitted identity unconditionally two-segment: `api-web`, not sometimes `api` and
sometimes `api-web`. That costs a few lines on a service that genuinely has one
process type and buys the deletion of collapse logic at the emitted name, the
hostname, the contract path, the health path, `OTEL_SERVICE_NAME`, and every tag.

See [`cicl.md § Process Types`](../doctrine/infrastructure/cicl.md#core-services)
for the model and the [1.6.0 CHANGELOG entry](../CHANGELOG.md) for the full list
of what changed.

**Why this is `incremental`, not a rebuild.** No infrastructure is torn down and
no `tofu` state is discarded. But be clear-eyed about what "incremental" does
*not* mean here: **resources are renamed**, so the first apply after this upgrade
**replaces** containers, ECS services, task definitions, log groups, sidecars,
traefik routers, hostnames, and — on `alb` — target groups. The
[not-process-qualified table](#what-does-not-move) below is the inventory of what
survives untouched.

**Read [§ Rollback is unavailable across the boundary](#rollback-is-unavailable-across-the-boundary)
before you cut.** For exactly one release cycle, prod has no rollback path.

---

## Machine sync

Run the **`doctrine-update`** skill (or by hand: `git pull` in
`~/.claude/jean_baudrillard`, then `bash setup.sh`). That lands machine-side:

- the **`docex:1.6.0` image** (built locally on cut);
- the **refreshed skill set**, including the new `worker` role in the transfer
  tables and the reworked `infra-compile` / `contracts` skill bodies.

One machine-side detail worth knowing: `.claude-plugin/plugin.json`'s `version`
field is what keys the plugin cache. Its bump to `1.6.0` is what invalidates that
cache so new and changed skills actually land. If skills look stale after an
update, that field going unbumped is the usual cause — here it is bumped, so
`doctrine-update` is sufficient.

Nothing breaks if a project lags on an older pin — old images keep working, and a
`cicl_version: "1"` project keeps compiling under its pinned `docex:1.5.0`.

---

## Project upgrade

Do this per consuming project (the `project-upgrade` skill drives it). The
migration is mechanical but broad; nine ordered steps below.

Throughout, the reference implementation is
[`docex/test_projects/*/core/api`](../docex/test_projects/fixed/core/api) — a
real two-process-type codebase with entrypoints, a liveness tick, a health
fan-out, and both contract formats. When a step below is ambiguous, read that.

### What does not move

Start here. Most of a project is *not* process-qualified, and knowing which half
is which saves a lot of churn:

| Identity | Keyed on | Changes? |
| --- | --- | --- |
| image ref `{registry}/{project}/{service}:{version}`, ECR repo | codebase | **no** |
| source folder `core/{service}/`, doc folder `plans/core/{service}/` | codebase | **no** |
| `schema_owned_by` target, `migrate.sh`, `migrations/` | codebase | **no** |
| `secrets:` / `config:` declarations | codebase | **no** |
| networks / SGs `{project}-{env}-{network}` | network | **no** |
| SSM prefix, aggregate env file, compose project name | env | **no** |
| backing service names, RDS/S3 identifiers, docker volumes | n/a | **no** |
| container / ECS service / task-def / log group / sidecar / traefik router | process type | **yes** |
| hostname label, contract filename, health path, `OTEL_SERVICE_NAME` | process type | **yes** |

In particular: **you do not get a second image, a second ECR repo, or a second
`migrate.sh`** by adding a process type. Two process types on one codebase share
one tag and differ only by `command`.

### 0. The error you will actually see

Before touching anything, run `./bin/docex compile` under the new pin so you know
what a failed migration looks like. A `cicl_version: "1"` `infra.yml` under 1.6.0
fails with **one** error naming this guide:

```
error:
/path/to/project/infra/infra.yml:
1 validation error for CICLDocument
  Value error, cicl_version '1' is no longer supported. CICL v2 makes the
`processes:` block mandatory on every core service and adds the `consumes`
relation and four-segment core magic refs. Follow upgrades/upgrade_1.6.0.md to
migrate this infra.yml, then set cicl_version: "2". , 'backups': True}}},
input_type=dict]
    For further information visit https://errors.pydantic.dev/2.13/v/value_error
```

That trailing `, 'backups': True}}}, input_type=dict]` is not part of the
message — it is the tail of pydantic's echo of your raw document, most of which
the CLI's console swallows as markup. Ignore it; the sentence before it is the
whole content.

**Once you correct `cicl_version` but before you finish nesting**, you get the
*second* error shape: one per core service still carrying moved fields, plus
`extra_forbidden` on `domain_default_service`. That one is useful — it names
exactly which fields to nest, per service:

```
4 validation errors for CICLDocument
core_services.web
  Value error, ['depends_on', 'networks', 'port', 'resources', 'role'] moved
from the core service to the process type in CICL v2. Nest them under a named
entry in a `processes:` block. Only {processes, secrets, config, env} are valid
at the service level (cicl.md § Field scoping, rule 22). See
upgrades/upgrade_1.6.0.md.
...
domain_default_service
  Extra inputs are not permitted
```

So: expect the version message first, and the field-scoping list as your
worklist once the version is corrected.

### 1. Repin + sync the shim

Bump `project.yml`'s `docex_version` to `1.6.0` and re-run the project installer
(`docex_install.sh`) so the project gets the current shim. Commit on a feature
branch as usual.

Note that `docex_install.sh` derives the pin by grepping `docex/pyproject.toml`.
That file is therefore functionally load-bearing, not the mere "packaging
metadata" it is sometimes called.

### 2. Nest every core service under `processes:`

Before:

```yml
cicl_version: "1"
domain_default_service: web

core_services:
  api:
    role: web
    port: 8080
    networks: [web, internal]
    health_check_path: /health
    depends_on: [database, cache]
    replicas: 3
    secrets:
      STRIPE_API_KEY: "Payments."
    env:
      DATABASE_HOST: ${backing_services.database.host}
    resources:
      cpu: 1.0
      memory: 2GB
```

After:

```yml
cicl_version: "2"
domain_default_process: api.web

core_services:
  api:
    # Codebase-scoped — hoisted OUT of the process type.
    secrets:
      STRIPE_API_KEY: "Payments."
    env:
      DATABASE_HOST: ${backing_services.database.host}
    processes:
      web:
        role: web
        command: ["python", "-m", "entrypoints.http"]   # now REQUIRED
        port: 8080
        networks: [web, internal]
        health_check_path: /health
        depends_on: [database, cache]
        replicas: 3
        resources:
          cpu: 1.0
          memory: 2GB
```

Three things bite here:

- **`secrets:` and `config:` hoist to the service level, unconditionally.** They
  are codebase-scoped — the *code* is what reads `STRIPE_API_KEY` — and are not
  valid on a process type at all.
- **`command:` is required on every process type, including `web`.** With several
  process types sharing one image, at most one could inherit the Dockerfile
  `CMD`, and "which one" is an ambiguity worth deleting rather than answering.
  Requiring it universally makes the Dockerfile `CMD` **irrelevant** for core
  services. Leave a note in your Dockerfile saying so; a stale `CMD` that no
  longer works is otherwise a trap for the next reader.
- **The service level accepts only `{processes, secrets, config, env}`.** Anything
  else is a hard error, because a stray `resources:` at the service level is
  almost always a mis-nested process-type field and failing loudly beats silently
  doing nothing.

**`env:` is the one field valid at both levels**, and the split is worth thinking
about rather than defaulting. A process type's effective env is the service-level
block merged under its own, process-level winning on collision. Put a variable at
the service level when the *code* needs it (`DATABASE_HOST` — the codebase talks
to a database); keep it on a process type when only that invocation needs it. See
step 8 for the reason this is not merely tidy.

### 3. Add `src/entrypoints/`

Each process type's `command` must invoke exactly one module under
`src/entrypoints/`, and **the composition root must construct without
activating**: it builds no server, opens no socket, and consumes no queue. See
[`internal_dependency_rules.md § Entrypoints`](../doctrine/hexagonal_architecture/internal_dependency_rules.md#entrypoints).

Practically, if your `root.py` ends in

```python
if __name__ == "__main__":
    uvicorn.run(build_app(), ...)
```

that block moves to `entrypoints/web.py`. `root.py` keeps `build_app()` and
grows a `build_<other>()` per additional process type. **Never split the root**
into `root_web.py` / `root_worker.py` — two copies of the driven wiring drift,
which is exactly the bug class module integration tests exist to catch.

The runtime host is not an adapter. Nobody ever thought uvicorn was one; a
broker's consume loop is not one either. Both belong to the entrypoint, and the
adapter's job stays *translation*.

**The liveness obligation for loop-owning process types.** A process type that
owns a loop rather than a request cycle — a queue consumer, a stream processor, a
polling worker — must serve `GET /health` on its declared `port` reporting the
*loop's* liveness, not the process's:

- the loop bumps an in-process **monotonic** tick each iteration;
- the loop ticks **at least every 10 seconds even when idle** (its receive is
  bounded, not indefinite);
- the handler returns **503** once that tick is **30 seconds** stale.

Both thresholds are **doctrine-fixed. Do not add an env var or a config key for
them.** Thirty is three times ten, so a healthy loop misses two consecutive ticks
before it is called stale — enough slack for scheduling jitter and one slow
iteration without flapping, while still failing a wedged loop inside the window
the container healthcheck acts on. A long unit of work does not threaten this:
the tick belongs to the receive loop, not to the work.

Two details that are easy to get wrong, and both are wrong in the direction of
*reporting healthy when you are not*:

1. **Do not bump the tick in the exception path.** A loop that fails every single
   iteration is not alive in any useful sense; bumping there answers 200 forever
   while no work moves.
2. **Do not source liveness from the health thread's own aliveness.** A separate
   liveness thread will cheerfully report health while nothing is being
   processed. A wedged consumer must fail its own probe.

Run the health server in a daemon thread and the loop in the **main** thread:
signals only reach the main thread, and it is the loop that has to hear SIGTERM.

`scheduler` process types are **exempt** from all of this. There is no
long-running container to probe, and a scheduler is never a `consumes` target —
cron invokes it and nobody else does. "Did last night's job run" is a telemetry
question.

Worked example:
[`core/api/src/entrypoints/worker.py`](../docex/test_projects/fixed/core/api/src/entrypoints/worker.py).

### 4. `domain_default_service` → `domain_default_process`

Renamed, and its value is now a **dotted, fully qualified** process reference:

```yml
domain_default_process: api.web      # was: domain_default_service: web
```

The old name is a small lie in a doctrine that just spent effort distinguishing
the two nouns, and every `infra.yml` is being rewritten anyway. The old key is
rejected as `extra_forbidden`, not silently ignored.

### 5. Rename contract files; add the fan-out and any AsyncAPI contracts

Contracts are keyed on the **process type**, unconditionally:

```
infra/contracts/api.openapi.yml   →   infra/contracts/api.web.openapi.yml
```

The format alone could not stand in for the process segment: one codebase may run
two HTTP process types — a public `api` and an internal `admin`, on different
networks with different resources — and both are genuine boundaries.

**The provider set is (`consumes` targets) ∪ (`web`-network process types).** Both
arms are load-bearing, and the first arm is what is new: a non-web `worker` that
anything in the project consumes is now a provider and needs a contract, even
though nothing routes to it. **The format follows from the provider's `role`** —
`role: web` → OpenAPI, `role: worker` → **AsyncAPI** — because the role is what
fixes the communication mechanism.

So a typical web/worker project gains a file it never had:

```
infra/contracts/api.worker.asyncapi.yml
```

Keep it to the message boundary. It describes channels and messages; it must
**not** carry a `/health` path. The worker's probeability is declared by its
`port` + `health_check_path` fields (step 6), and its liveness is *exposed*
through the consumer's OpenAPI:

**Health fan-out paths gain a segment.** Every `web`-network process type declares

```
GET /health/<service>/<process>      # /health/api/worker — TWO segments
```

once per `consumes` target that is not itself on the `web` network. Targets on
`web` are skipped: they are publicly reachable and answer their own `/health` at
their own hostname, so there is nothing to proxy.

**One hop only.** The fan-out proxies the target's *self* `/health` with a short
hard timeout, and **never** the target's own fan-out endpoints. The `consumes`
graph may legally contain cycles, so a fan-out calling a fan-out recurses without
bound.

### 6. `depends_on` is backing-services-only; core→core moves to `consumes:`

`depends_on` is a **readiness gate** and now names **backing services only**. A
core process type in a `depends_on` list is a hard error. Interface coupling
between core process types is a different relation with different rules:

```yml
processes:
  web:
    depends_on: [database, cache]     # backings only
    consumes: [api.worker]            # core process types only, dotted
```

|  | `depends_on` | `consumes` |
| --- | --- | --- |
| Names | backing services only | core process types only |
| Job | readiness gate | contracts, health fan-out, rule 7 |
| Cycles | fatal | **legal** |
| Emitted | compose `condition:` on fixed; nothing on elastic | nothing — CI only |

Walk each core→core `depends_on` you have and either reclassify it as `consumes`
or **delete it as spurious**. Then add the `consumes` edges that exist only
asynchronously — through a broker — and therefore never showed up in
`depends_on` at all. Those are the ones most projects are missing, and they are
the ones the health fan-out depends on.

Three clarifications, all of which surprise people:

- **One-directional: a ref implies an edge, never the reverse.** A magic ref to a
  core process type obliges a matching `consumes` entry. A `consumes` entry does
  *not* oblige a magic ref — `api.web` may declare `consumes: [api.worker]` for
  the contract and the health fan-out while holding no ref to it, because it
  reaches the worker through the broker.
- **Same-codebase is not exempt.** `api.worker` referencing
  `${core_services.api.web.host}` still declares `consumes: [api.web]`. Sharing
  source does not make it not a boundary.
- **A service-level `env:` ref obliges *every* process type** to declare the edge.
  If every process receives `WEB_HOST`, every process talks to `api.web`. This is
  the sharpest practical reason to keep an invocation-specific ref on its process
  type rather than hoisting it — see step 8.

And declare the target's fields: **a `consumes` target must carry both `port` and
`health_check_path`.** Those two fields *are* its health declaration, and
`docex check` asserts them — along with `curl` being present in the image, which
it keys off `health_check_path` with no network filter. A worker is never routed,
so a `port` on it can feel wrong; it is not. On elastic the `port` is also
exactly what makes the process type Service-Connect-discoverable, which is what
lets a sibling `web` process reach its `/health` one hop away.

### 7. Qualify core magic refs — four segments

```
${core_services.api.host}            →   ${core_services.api.web.host}
${backing_services.database.host}        (unchanged — three segments)
```

A **bare** core service name is now illegal rather than shorthand: a codebase has
no single boundary, so `${core_services.api.host}` has no answer. The asymmetry
with backing services is honest rather than accidental — a backing service has no
process types, so there is nothing to qualify.

A process type may not reference **itself**. Beyond being degenerate,
`provides.host` is the *internal* discovery name, so the one plausible motive —
building an absolute URL to oneself — would not return what you expect. Use
`localhost`.

### 8. `migrate.sh` / `test.sh` / `build.sh` read **service-level `env:` only**

**Call this out to yourself in writing before you recompile.** It is the break
most likely to bite silently, and it produces no error of any kind.

All three shims are invoked **once per codebase**, not once per process type —
there is no process type in play when `migrate.sh` runs, so there is no
process-level `env:` block to merge. A shim that reads a process-scoped variable
gets **nothing**: an empty string or an unset var, not a failure. A migration
whose `DATABASE_HOST` sits on `api.web` will attempt to connect to `""`.

Audit every variable your three shims read and confirm each one is declared at
the **service** level of `infra.yml`. In practice this means the database parts
almost always belong at the service level, which is where you want them anyway:
both a web edge and a worker need a database.

### 9. On fixed: add public DNS records for every new web hostname *before* `envinfra up`

Every `web`-network process type's hostname gains a segment:

```
web.dev.myproject.example.com   →   api-web.dev.myproject.example.com
```

On **fixed** foundations, traefik issues per-host Let's Encrypt certs via the
**HTTP-01** challenge, which requires the hostname to resolve publicly to the
host *before* the ACME order is placed. Create the A-records for every new web
hostname **before** `envinfra up dev`.

Get this wrong and the cost is not a retry. Traefik places ACME orders it cannot
satisfy, and Let's Encrypt's **failed-authorization rate limit is time-based** —
so the penalty is roughly an hour of waiting per env, not one more attempt.
`docex preinfra development` surfaces the gap first; run it.

(A project holding per-env **wildcard** records — `*.dev.myproject.example.com` —
needs nothing here: the process segment shares the same DNS label as the service,
hyphen-joined, so an existing wildcard already covers `api-web`. The doctrine's
own smoke projects are in that position, which is why
`docex/test_projects/PRE_CUT_CHECKLIST.md § A.4.1` says no new records are
needed. Both statements are correct for their subject.)

### 10. Recompile, redeploy

Recompile, commit the branch, and run the normal pipeline
(`check → merge → containerize → release stage → stagetest → release prod`).

Expect the first apply per env to **replace** every core-service resource, since
they are renamed. On elastic that is a `tofu` plan full of create/destroy pairs;
read it once before applying, and see the notes below on target groups.

---

## Doctrine / behavior notes

### Rollback is unavailable across the boundary

For exactly **one release cycle** after adopting 1.6.0, prod has no rollback
path. `docex rollback` refuses at cheap pre-flight — before any worktree is
created and before any apply — because rollback recompiles the *target* version's
`infra.yml` with the *current* docex (`cicd.md § Rollback` step 3), and the
current docex compiles only `cicl_version: "2"`.

Verbatim:

```
rollback aborted — cannot roll back across the CICL v1→v2 boundary.
Nothing has been touched.

Target v0.0.13's infra/infra.yml declares cicl_version "1". This docex compiles
only cicl_version "2", and rollback recompiles the target's infra.yml with the
*current* docex (cicd.md § Rollback step 3) — so no rollback to this target can
succeed.

Fix forward instead:
  1. On main, fix the defect and bump project.yml past the broken version.
  2. ./bin/docex check  →  merge  →  containerize  →  release <env>

Once a second cicl_version "2" release exists, rollback works normally.
```

There is no mitigation beyond **keeping the window short**: get a second
`cicl_version: "2"` release out promptly, and prefer not to schedule this upgrade
immediately before a period you cannot supervise. The refusal is cheap and early
by design — an operator mid-outage learns it before anything is touched, rather
than from a compile error inside a worktree.

### `${a-b}` now errors, and there is no escape

The compile-time variable pattern was widened to admit `-`. Previously a
`${...}` carrying a hyphen matched **nothing** — not the compile-time pattern,
not the magic-ref pattern — and was emitted **verbatim into the compose/HCL
output** instead of failing. That was a real bug (four-segment magic refs with
hyphenated names were passed through as literal text). It is fixed, and the
consequence is that a `${a-b}` you previously relied on as literal text is now an
undefined-compile-time-variable error.

The grammar is exactly `${var}`, `$[var]`, `@expr`, with **no escape form**. Be
clear about this, because there is a doubled `$$` visible in the compiled output
that looks like one: that doubling is applied by the **emitters, after
substitution**, and never reaches the resolver. `$${a-b}` is not a workaround.

**The fix is to rename the variable.** In practice these are mistypes
(`${env-name}` for `${env_name}`) that were silently emitting garbage.

### New emitted names for every core service

Enumerated so nothing surprises you mid-apply. For a codebase `api` with a
process type `web`, in env `dev`:

| Resource | Was | Is |
| -------- | --- | -- |
| Compose service / container | `<proj>-dev-web` | `<proj>-dev-api-web` |
| ECS service / task-def family | `<proj>-dev-web` | `<proj>-dev-api-web` |
| CloudWatch log group | `…/web` | `…/api-web` |
| OTel sidecar service | `<proj>-dev-web-otelcol` | `<proj>-dev-api-web-otelcol` |
| Traefik router / service key | `<proj>-dev-web` | `<proj>-dev-api-web` |
| Hostname | `web.dev.<proj>.<apex>` | `api-web.dev.<proj>.<apex>` |
| `OTEL_SERVICE_NAME` | `web` | `api-web` |
| Contract file | `api.openapi.yml` | `api.web.openapi.yml` |
| Health fan-out path | `/health/api` | `/health/api/web` |

The process type occupies the **same DNS label** as the service, hyphen-joined —
`api-web.dev.…`, never `web.api.dev.…`. Three independent reasons, any one
decisive: TLS wildcards cover exactly one label (`*.stage.<project>.<apex>` would
not cover a host two labels deep, and multi-level wildcards are invalid in TLS);
the domain parse is positional; and the bare-env / bare-project routes are
defined relative to the four-part form.

Nothing ever reverse-parses `api-web` back into `(service, process)`. The label is
a rendered output, never an input to be decomposed.

Two identities that do **not** gain a segment, because they are keyed on the
codebase: the **exec service** used by `build`/`test`/`migrate` (one per
codebase, carrying **service-level `env:` only**), and its `OTEL_SERVICE_NAME`,
which stays de-qualified (`api`, with no `docex.process_type` attribute).

### `alb` target-group names gain hash suffixes; `iam` can now hard-fail

Word this carefully to yourself, because the obvious diagnosis is wrong:
**neither policy changed in this release.** The only edit to
`tables/naming_policies.yml` is `http_host` gaining `max_len: 63,
overflow: error`. `alb`'s 32-char `hash_truncate` dates to mod 069 and `iam`'s
64-char cap to mods 005/030. What changed is that there is now a **fourth name
segment** for those long-standing policies to apply themselves to. An operator
sent looking for a policy diff will not find one — do not send them.

Two concrete consequences:

- **`alb` target groups whose names previously fit are destroyed and recreated on
  the first apply.** The policy is working as designed and the descriptive name
  survives in the `Name` tag, but the AWS identifier changes. Observed in the
  doctrine's own elastic smoke project: `docex-smoke-elastic-prod-web-tg` (31
  chars, fit) became `docex-smoke-elastic-prod-09e172` (hash-truncated from a
  35-char `…-api-web-tg`), with `Name = docex_smoke_elastic_prod_api_web` intact.
  Read the plan; expect the replacement.
- **An `iam` scheduler-role name can now exceed 64 characters and hard-fail the
  compile.** `iam` inherits the default `overflow: error` — it does not
  hash-truncate. So a project that compiles today may not compile after nesting,
  purely because `<project>_<env>_<service>_<process>_scheduler` is longer than
  `<project>_<env>_<service>_scheduler` was. If that happens, shorten the process
  name (or the codebase name); there is no policy knob.

### Scheduler-only naming: name the codebase after the codebase, the process after the job

A mandatory `processes:` block will tempt you into doubling. A codebase named
after its job produces `nightly_cleanup-nightly_cleanup` — correct, and ugly.

The convention (`cicl.md § Naming convention`) is: **a process type is named after
its role**, unless a codebase declares two process types on the same role — with
one exception, `role: scheduler`, which is named after **the job**, precisely
because a codebase commonly carries several jobs.

So the doubling is never the codebase's fault, and the fix is not to rename the
codebase. Worked example in the doctrine's smoke projects:
[`core/reaper`](../docex/test_projects/fixed/core/reaper) is codebase `reaper`
with process type `prune`, emitting `reaper-prune`. A project that genuinely
needs two HTTP boundaries names them by boundary — `api.public`, `api.admin` —
and deviates deliberately.

### `replicas` is honoured in `prod` only

`replicas` is now actually read — it was declared, range-checked, and documented
in prior releases while `desired_count` stayed hardcoded to 1. It is **clamped to
1 in `dev`, `test`, and `stage`**.

Flag this as a known limitation, because of what it implies: a process type that
does not tolerate siblings — one that assumes it is the only consumer, or holds a
non-shareable resource — **first surfaces in production**. `stage` exists to be
production-equivalent and this is the one shape it cannot rehearse. If you set
`replicas > 1`, reason explicitly about concurrent claims (advisory locks,
`FOR UPDATE SKIP LOCKED`) rather than discovering the need at 3am.

---

## Verification

- `./bin/docex compile` succeeds with `cicl_version: "2"`.
- Emitted names carry **two segments** everywhere the table above says they
  should: `grep -rn 'api-web' infra/output/` finds containers / ECS services /
  task-defs / log groups / sidecars / traefik routers / hostnames.
- **One image and one ECR repo per codebase.** `containerize` pushes
  `…/api:<v>`, not `…/api-web:<v>` and `…/api-worker:<v>`. On elastic, confirm
  the project tier provisioned one repo per codebase and no more.
- **One `…-migrate` task-def family per codebase** (elastic), one migrate task
  per codebase in the rendered playbook (fixed) — not one per process type.
- `OTEL_SERVICE_NAME` is distinct per process type (`api-web`, `api-worker`) and
  carries `docex.process_type` in `OTEL_RESOURCE_ATTRIBUTES`; the per-codebase
  **exec** service carries the de-qualified `api` with no `docex.process_type`.
- Four-segment magic refs **resolved**: `grep -rn 'core_services\.' infra/output/`
  finds nothing. A literal `${core_services.api.worker.host}` in the output means
  the ref was passed through as text.
- `GET /health/<svc>/<proc>` is reachable from outside for every `consumes`
  target not on the `web` network, and returns the same `version` as `/health`.
- A loop-owning process type's `/health` **503s when its loop is wedged.** Worth
  testing once by hand (pause the loop, or point it at an unreachable
  dependency): a 200 there means the tick is being bumped from the wrong place.
- `./bin/docex check` passes, including its new assertion that every `consumes`
  target declares both `port` and `health_check_path`. Note the `curl` gate is
  keyed on the **codebase image**: any one process type declaring
  `health_check_path` obliges the shared image to carry `curl`. If a
  previously-curl-less worker image merged into a codebase that now declares the
  field, that gate fires against it for the first time.
