# Mod 088 — `docex test` handles scheduler-role core services

## Problem

`docex test` fails when a project has a `scheduler`-role core service:

```
service "reaper" is not running
error: test.sh for 'reaper' exited 1.
```

Surfaced by the 1.5.0 pre-cut fixed smoke walk (PRE_CUT_CHECKLIST C.5).

## Root cause

`orchestrate/test.py` step 3 iterates **every** `core_services(ctx)` and runs
each service's `test.sh` via `docker compose exec <service> ./test.sh`. That
assumes each core service has a long-running, exec-able container in the `test`
compose stack. A `scheduler`-role service does not: the compiler deliberately
emits **no** scheduler (Ofelia) container in the `test` stack
(`scheduler.md` §225 — "`test` suppresses the scheduler trigger"; confirmed:
`reaper` is present in the `dev` compose, absent from `test`). So
`compose_service_key` finds no matching service, falls back to the bare name
`reaper`, and `docker compose exec reaper` fails with "service not running".

Pre-existing and orthogonal to envmageddon: the scheduler role landed in mod 055;
`test.py`'s exec-every-core-service loop predates it (last touched mod 080). The
combination — a scheduler present while `docex test` runs — was simply never
exercised until this walk.

## Design

A scheduler still has real `test.sh` unit/module tests that must run — both
`cicd.md` ("run each core service's `test.sh`") and `scheduler.md` §233
("Exercise a job's logic through its own unit/module tests") require it. Since
there is no `test`-stack container to `exec` into, run the scheduler's `test.sh`
as a **one-off container** built from its `test`-stage image — mirroring how
`orchestrate/up.py::_ensure_scheduler_image` builds a scheduler's self-contained
image directly rather than through Compose.

In `run_test` step 3, partition core services:

- **non-scheduler** → `compose_exec ./test.sh` (unchanged).
- **scheduler** → `build_image(<svc>/, target="test", tag=<local test tag>)`
  then `run_one_shot(tag, ["./test.sh"])`. Both primitives already exist on
  `DockerClient`. The scheduler's `test` stage is `FROM prod AS test`,
  `WORKDIR /service`, no `ENTRYPOINT`, so the one-off runs `/service/test.sh`
  (`pytest /service/tests`) cleanly. The build context base honors the
  `project_dir` override (equals `ctx.project_root` under `docex check`'s
  worktree), consistent with how Compose resolves build contexts.

The one-off attaches **no** env-tier stack or network — a scheduler's tests are
self-contained unit/module tests per the doctrine (the job's runtime env surface
is exercised in `dev`, not `test`). This is called out in the code comment and
the doctrine clarification below.

## Doctrine / artifact alignment

- **Doctrine** (`scheduler.md`, `test` caveat) — the current text says exercise a
  scheduler's logic "through its own unit/module tests, or in `dev`". Add one
  clarifying sentence: `docex test` runs a scheduler's `test.sh` via a one-off
  built from its `test`-stage image (no env-tier stack attached), so those tests
  must be self-contained. **Operator-approved** wording (this is the only
  doctrine edit in the mod).
- **src** (`orchestrate/test.py`) + **tests** (`tests/unit/test_orchestrate_test.py`)
  as below.
- No transfer-table change; no other core-doc change required.

## Non-goals

- No change to how non-scheduler services run their tests.
- No attempt to attach the test-env DB/network to a scheduler's one-off (schedulers'
  tests are self-contained by doctrine). If a future scheduler needs integration
  fixtures, that is a separate enhancement.
