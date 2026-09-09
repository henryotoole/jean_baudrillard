# Mod 073 — Scheduler `test` suppression

## Problem

The `scheduler` role (mod 055) is emitted normally in every environment,
including `test`. The scheduler doctrine flagged this as a known gap:

> **`test` does not suppress schedulers.** ... A future doctrine extension may
> add a test-time suppression.

A scheduler that fires inside a `test` stack runs the project's job against the
ephemeral test database on whatever cadence its cron declares. Even though jobs
are typically infrequent, the doctrine's intent is that `test` is exercised
deterministically "from the outside" (flow tests over the internal network), not
perturbed by background jobs firing on a wall-clock schedule. This mirrors the
`web`-routing decision (mod 054), where `test` drops web routing entirely.

## Change

Suppress a scheduler service's **trigger** in the `test` env.

The key simplification: `dev` and `test` are **always fixed foundation**
(`_env_foundation` in `compile.py`), so the `test` env always compiles to
docker-compose — never to elastic HCL. A scheduler's only possible trigger in
`test` is therefore the **Ofelia container** emitted by `emit/compose.py`; the
EventBridge / `scheduled_task` HCL path is unreachable for `test` on either
foundation. So the entire change is a single guard in the compose emitter: skip
the Ofelia scheduler container (and its rendered INI config) when
`compiled.env == "test"`.

The scheduler service is already never emitted as a long-running container in any
env (the services loop `continue`s past it). With the Ofelia container also
dropped in `test`, a scheduler service produces **no compiled output at all** in
`test`. The job cannot fire.

`dev`, `stage`, and `prod` are unchanged: `dev`/`stage`/`prod` on fixed still get
their Ofelia container; `stage`/`prod` on elastic still get their EventBridge
schedule + invocation role.

## Doctrine changes (operator-approved)

`doctrine/infrastructure/specifics/scheduler.md`:

1. § Caveats — the first caveat is rewritten from "`test` does not suppress
   schedulers" to "`test` suppresses the scheduler trigger", describing the
   Ofelia-omission and noting that `dev`/`test` being always-fixed means the
   Ofelia trigger is the only one `test` could carry.
2. § Lifecycle and idempotency — the Fixed bullet gains a sentence noting `test`
   emits no Ofelia container.

## Scope / non-goals

- **Not** a change to how schedulers compile in `dev`/`stage`/`prod`.
- **Not** the fix for the separate dev image-build gap (a dev scheduler job's
  image is never built, so Ofelia cannot launch it locally). That is a distinct
  concern tracked as its own follow-up mod; it is unrelated to `test`
  suppression (which removes the scheduler from `test` rather than running it).

## Verification

Compile the two bundled scheduler fixtures (one fixed-foundation, one
elastic-foundation) and assert:

- `test/docker-compose.yml` for **both** fixtures contains no
  `*-<svc>-scheduler` Ofelia container and no `ofelia_<svc>` config entry.
- `dev/docker-compose.yml` for both still contains the Ofelia container + config
  (regression guard).
- The elastic fixture's `stage`/`prod` HCL still emits the EventBridge schedule
  (unchanged path).
