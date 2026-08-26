---
stratum: conditional
---

# Exec Service

This file answers one question: **where does a one-off, codebase-scoped job run?**

The answer is the **exec service** — the compiled block that *is* the [codebase](../cicl.md#core-services). The compiler emits exactly one per codebase, keyed `${project}-${env}-${codebase}-exec`, and it is the container `build.sh`, `test.sh`, and `migrate.sh` all run inside.

It is not a [core service](../cicl.md#core-services). No project declares it, nothing routes to it, and `compose up` never starts it. It is a compiler-owned derivative, like the `-otelcol` sidecar.

`health.sh` is the one codebase shim that does **not** run here. It probes a long-running process, and the exec block is a one-off that exits — its own liveness question is answered by the exit code it was invoked for. See [healthchecks.md](../healthchecks.md).

## Why it exists

A codebase with several core services offers **no principled way to pick one of their containers to `exec` into**. Any rule for choosing a representative — lowest-sorted, first-declared — moves a migration's environment when an unrelated core service is renamed. The exec service deletes the question by giving the codebase its own container.

Three further properties fall out of that, and each is load-bearing:

1. **Codebase-scoped env is enforceable by absence.** The block carries the codebase-level `env:` block only, never a core service's overlay. So *`build.sh`, `test.sh`, and `migrate.sh` may depend only on codebase-scoped env* is not a convention a script can quietly break — a core-service-scoped key is simply not present. A migration has no business reading a worker's concurrency knob, and now it cannot.
2. **Nothing needs to be running.** The block is gated behind `profiles: [exec]`, so `compose up` never starts it, while `compose run` implicitly enables the profile of the service it names.
3. **It is the compiler's one remaining ordering emission.** No core-service block carries `depends_on`. The exec block carries the union of its codebase's *backing*-targeted [`uses`](../cicl.md#uses-relationships) edges, rewritten to long-form `condition: service_healthy`. [Disposability](../cicl.md#uses-relationships) says a long-running process must tolerate a dependency vanishing; nothing in it makes a one-shot script succeed against a database not yet accepting connections. For a batch job, "be tolerant" *means* "wait until ready".

## What the block carries

| | |
| --- | --- |
| Image | The codebase's image ref — identical across its core services. `build:` in `dev`/`test`, the registry ref in `stage`/`prod`. |
| Env | Codebase-level `env:` only. Its telemetry identity is de-qualified to match: `OTEL_SERVICE_NAME=${codebase}`, no `docex.service` (see [transfer_tables.md](./transfer_tables.md#per-core-service-env-both-foundations)). |
| Volumes | `src` and `dist` bind mounts, **`dev` only** — `test` bakes artifacts into the image, `stage`/`prod` ship them from the registry. |
| Networks | The union of the codebase's networks **less `web`**. A one-off operations shell is never publicly routed. |
| `depends_on` | As above. Long-form always; `service_started` where a target declares no healthcheck. |
| `command` | Deliberately unset — supplied at the call site. Codebase Dockerfiles declare no `ENTRYPOINT`, and `WORKDIR` is the fixed `/service` root, so `run --rm …-exec ./migrate.sh` executes the script directly. |

## Invocation

Normally you do not invoke it by hand — `docex` does, at four sites: [`build`](../cicd.md#build-step), [`test`](../cicd.md#build-test-step), [`migrate`](./migrations.md) (including implicitly from `envinfra up dev` and `test`), and the fixed-foundation `stage`/`prod` Ansible playbook's migrate task. The raw form matters when a job has no `docex` command of its own.

**Applying migrations in `dev`:**

```bash
docker compose -f infra/output/dev/docker-compose.yml \
    run --rm myproject-dev-api-exec ./migrate.sh
```

**Running the suite in `test`:**

```bash
docker compose -f infra/output/test/docker-compose.yml \
    run --rm --build myproject-test-api-exec ./test.sh
```

`--build` is added in `test` only. There the image *is* the artifact under test, and `compose run` builds only when the image is **absent** — it silently reuses a stale one otherwise. In `dev` source arrives by bind mount and the `dev` stage exists precisely so `build.sh` can be re-invoked without a rebuild, so forcing one there would contradict the stage's purpose.

**An ad-hoc job**, e.g. seeding a dev database. Since the block declares no `command`, any argv against the image works, with the codebase's backing services gated healthy first:

```bash
docker compose -f infra/output/dev/docker-compose.yml \
    run --rm myproject-dev-api-exec python -m tools.seed
```

## Scope limits

- **It is a compose artifact.** Emitted in all four *fixed-compiled* envs — not just `dev`/`test`, because routing fixed `stage`/`prod` migration through the same block is what makes the codebase-scoped-env rule hold in the environment where violating it costs most.
- **Elastic `stage`/`prod` have no exec container.** Migration there is an ECS `RunTask` against a per-codebase migration task definition — see [migrations.md § Stage and Prod on Elastic Foundation](./migrations.md#stage-and-prod-on-elastic-foundation). Build and test never run against an elastic env at all.
- **The name is reserved by collision.** A core service named `exec` on codebase `api` is a compile error: it renders `api-exec`, byte-identical to this block. See [cicl.md § Validation Rules](../cicl.md#validation-rules).
