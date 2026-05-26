# `docex` — Phase 2 Implementation

This document covers the work needed to ship Phase 2 of `docex`: the `up`, `down`, `build`, `test`, and `migrate` commands. Phase 2 takes the doctrine from "authorable" (Phase 1 — you can write `infra.yml` and inspect what it would produce) to "runnable on a fixed dev/test stack" — a developer can bring up a real stack locally, iterate on source against bind-mounted containers, run unit + integration tests, and apply migrations.

Phase 2's success criterion: against a project with one core service and at least one backing service, a developer can:

1. Run `./bin/docex up dev` and get a working local stack with their code running.
2. Edit source, run `./bin/docex build`, see fresh artifacts in `dist/` without rebuilding the container image.
3. Run `./bin/docex test` and get exit 0 if all services' tests pass, non-zero on first failure.
4. Run `./bin/docex migrate dev` and have it apply against the dev database.
5. Run `./bin/docex down dev` and have the stack come down cleanly while preserving named volumes.

## Required Reading

You should already have all the doctrine context from `phase_1.md`. The additional load-bearing reads for Phase 2:

1. `~/.claude/jean_baudrillard/doctrine/infrastructure/cicd.md` §§ Build Step, Build Test Step, Migrate Step — re-read these. They are the spec for what `build`, `test`, and `migrate` actually do.
2. `~/.claude/jean_baudrillard/doctrine/infrastructure/docex.md` §§ up, down, build, test, migrate — the per-command surfaces.
3. `~/.claude/jean_baudrillard/doctrine/infrastructure/infrastructure.md` § Core Service Containers — the four Dockerfile stages (`build`, `dev`, `prod`, `test`) every core service must provide.
4. `~/.claude/jean_baudrillard/doctrine/infrastructure/specifics/release_mechanism.md` § Migrations — context for migrate timing (mostly Phase 3+, but the invocation contract is shared).
5. `~/.claude/jean_baudrillard/docex/implementation/phase_1.md` — to know what's already on disk and what conventions to follow.
6. `~/.claude/jean_baudrillard/docex/src/docex/__main__.py` — to know what the existing dispatcher looks like so you wire new commands in consistently.

## Scope Boundaries

**In scope for Phase 2:**
- `up <env>` for fixed envs (`dev`, `test`).
- `down <env>` for fixed envs.
- `build [<svc>]` — dev-iteration build inside a running dev container.
- `test` — fresh test env, migrate, run all `test.sh` scripts, tear down.
- `migrate <env>` for dev/test envs only. **Stage/prod migrate stays stubbed**, returning a Phase 3 (fixed) / Phase 4 (elastic) "not yet implemented" message.
- Docker CLI added to the image so the orchestration code can shell out.
- A `DockerClient` abstraction so unit tests can mock subprocess calls cheaply.
- Sample fixture extended with real service code (Dockerfile + `build.sh` + `test.sh` + `migrate.sh` + a trivial `src/` and `migrations/`) so Phase 2 can be exercised end-to-end.
- A small **Phase 1 patch**: the dev compose output must bind-mount `core/<svc>/src/` and `core/<svc>/dist/` into each core service's container, so `docex build` can refresh `dist/` from the host without a container rebuild. See Step 1.

**Explicitly NOT in scope:**
- `up`/`down` for `stage`/`prod` (those go through `release` in Phase 3/4, not `up`).
- `migrate stage` / `migrate prod`.
- `check`, `merge`, `containerize`, `release`, `stagetest` — Phase 3.
- `bootstrap` and elastic-specific orchestration — Phase 4.
- Anything that requires the AWS API, ansible, or git.

## What Phase 1 Already Provides

Phase 1 shipped these pieces you'll lean on:

- `docex.context.load_project_context()` — finds the project root, parses `project.yml` and `infra/infra.yml`, returns a `ProjectContext`.
- `docex.cicl.compile.run_compile()` — runs the compiler against a context. Phase 2 commands invoke this implicitly: `up`, `test`, and `migrate` all assume up-to-date `infra/output/<env>/`. Either re-compile defensively, or document that the user must run `docex compile` first. **Decision: re-compile implicitly.** It's cheap (the Phase 1 compiler is fast and deterministic) and removes a footgun.
- The dispatcher in `src/docex/__main__.py` — has stubs reserved for `up`, `down`, `build`, `test`, `migrate`. You will replace those stubs with real implementations.
- The error types in `src/docex/errors.py` — extend with new types (`DockerNotAvailable`, `EnvNotSupported`, `BuildFailed`, etc.) as you go.

The Phase 1 dev compose file is missing per-service bind mounts for `src/` and `dist/`. That's a real gap for the `build` command. Step 1 patches it.

## Step-by-Step Implementation

### Step 1: Patch Phase 1 — emit dev bind mounts for core services

Without this, `docex build` (Step 7) has no way to refresh `dist/` from the host. The compiler currently emits no `volumes:` block for core service containers in dev compose output.

In `src/docex/emit/compose.py` (or wherever the compose emitter applies env-dependent decorations), add: when `env == "dev"` and the service is core, emit a `volumes:` block on its compose service:

```yml
volumes:
  - ./core/<service>/src:/service/src
  - ./core/<service>/dist:/service/dist
```

Use compose's relative-path form (`./core/<service>/...`) so it resolves against the project root the same way regardless of where the user invokes compose from. (The Phase 1 shim already passes `COMPOSE_PROJECT_DIR`, which keeps these paths host-correct under DooD.)

The container-side path (`/service/src`, `/service/dist`) is a doctrinal default — record it as a comment in the transfer table for `web/container` and reference it from `build.sh` documentation in the sample fixture (Step 3).

Apply this **only** to the `dev` environment. The `test` environment must not get bind mounts — `docex test` deliberately builds artifacts inside the image via `docker build`, so the test container's source/dist must come from `COPY`, not from the host. Stage and prod likewise get no bind mounts.

Add a unit test (`tests/unit/test_compose_emitter.py` or extended `test_compile.py`) asserting:
- Dev compose has `volumes:` on the core service with both bind mounts.
- Test/stage/prod compose does **not**.

### Step 2: Add docker CLI to the image

Phase 2's image needs `docker` and `docker compose` available for subprocess calls. The host's docker daemon is reached via the bind-mounted socket (already in the shim); we just need the client.

Update `Dockerfile`:

```dockerfile
# After the existing python install line, install docker CLI + compose plugin
# from Docker's apt repository. The version is pinned so docex:0.x.y bakes in
# a specific docker CLI version.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl gnupg \
 && install -m 0755 -d /etc/apt/keyrings \
 && curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg \
 && chmod a+r /etc/apt/keyrings/docker.gpg \
 && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian $(. /etc/os-release && echo "$VERSION_CODENAME") stable" > /etc/apt/sources.list.d/docker.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends docker-ce-cli=5:<pinned> docker-compose-plugin=2.<pinned> \
 && rm -rf /var/lib/apt/lists/*
```

Pick a concrete pinned version when you build. The principle: every docex image baked from this Dockerfile uses identical CLI versions, regardless of when it's built. Update `pyproject.toml`'s version to `0.2.0` since the image surface is changing.

Rebuild the image once you're done and confirm `docker --version` and `docker compose version` work inside it.

### Step 3: Extend the sample fixture with real service code

Phase 1's `tests/fixtures/sample_project/` has only `project.yml` and `infra/infra.yml`. Phase 2 needs a real core service so we can `up`, `build`, `test`, and `migrate` against it. Add:

```
tests/fixtures/sample_project/
├── project.yml                                       (already exists)
├── infra/infra.yml                                   (already exists; add health_check_path if not present)
└── core/
    └── api/
        ├── Dockerfile                                (multi-stage: build, dev, prod, test)
        ├── build.sh                                  (POSIX shell; deposits artifact in dist/)
        ├── test.sh                                   (POSIX shell; runs pytest, exits 0/non-0)
        ├── migrate.sh                                (POSIX shell; runs a trivial migration)
        ├── src/
        │   └── app.py                                (trivial HTTP server returning {"version": "..."} on /health)
        ├── tests/
        │   └── test_smoke.py                         (one passing test)
        └── migrations/
            └── 20260101000000_init.sql               (creates a single table)
```

Recommendations for keeping the fixture tight:

- **`Dockerfile`** — `FROM python:3.12-slim` base. Four stages per [infrastructure.md § Core Service Containers](../../doctrine/infrastructure/infrastructure.md#core-service-containers): `build` (runs `./build.sh`), `dev` (carries source + uvicorn or similar, expects bind-mounted `/service/src` and `/service/dist`), `prod` (`COPY --from=build /service/dist /service/dist`), `test` (extends prod with pytest + httpx).
- **`build.sh`** — for a Python project, this is just `mkdir -p dist && cp -r src/* dist/`. Trivial but real.
- **`test.sh`** — `exec pytest -q /service/tests`. Exits 0 on pass.
- **`migrate.sh`** — `exec psql "$DATABASE_URL" -f /service/migrations/*.sql` or, more robustly, install `dbmate` in the test stage and `exec dbmate up`. Pick whichever is simplest; the doctrine doesn't prescribe.
- **`src/app.py`** — minimal ASGI app (FastAPI or even bare `http.server`) serving `/health` returning `{"version": "0.1.0"}`.
- **`tests/test_smoke.py`** — `def test_passes(): assert True`. The point is exercising the `test.sh` shim, not testing the app.
- **`migrations/...sql`** — `CREATE TABLE IF NOT EXISTS health(checked_at TIMESTAMP);`.

Add `infra/secrets/dev.env` to the fixture with placeholder POSTGRES_USER/POSTGRES_PASSWORD values (committed) so docker compose can substitute them — but mark in the fixture README that real projects gitignore `<env>.env`.

The elastic fixture (`sample_project_elastic/`) does **not** need a `core/` tree for Phase 2 — Phase 2 only exercises fixed envs (`dev`/`test`), and both fixtures hit fixed for those. Both fixtures should produce identical dev/test compose output (modulo network names if the elastic project's `infra.yml` differs).

### Step 4: The `DockerClient` abstraction

Create `src/docex/docker/__init__.py` and `src/docex/docker/client.py`. The `DockerClient` interface wraps every docker / docker compose invocation Phase 2 needs:

```python
class DockerClient(Protocol):
    def compose_up(self, compose_file: Path, *, build: bool = True, detach: bool = True) -> int: ...
    def compose_down(self, compose_file: Path, *, preserve_volumes: bool = True) -> int: ...
    def compose_run_one_off(self, compose_file: Path, service: str, command: list[str], *, env: dict[str, str] | None = None) -> int: ...
    def compose_exec(self, compose_file: Path, service: str, command: list[str]) -> int: ...
    def compose_ps(self, compose_file: Path) -> list[str]: ...  # list of running service names
    def is_available(self) -> bool: ...  # quick `docker info` probe
```

The real implementation (`SubprocessDockerClient`) shells out via `subprocess.run`, streams stdout/stderr to the user's terminal, and returns the exit code. Stash it under `src/docex/docker/subprocess_client.py`.

Every Phase 2 command takes a `DockerClient` as a dependency — wired by the dispatcher to the subprocess implementation in normal use, and to a fake in unit tests. Don't import `subprocess` from anywhere outside `docker/subprocess_client.py`. This rule is what makes the unit test story tractable.

Add `DockerNotAvailable` to `errors.py`. The dispatcher should call `docker_client.is_available()` before any Phase 2 command and bail with that error if false.

### Step 5: Orchestration package

Create `src/docex/orchestrate/` per the design proposal. One module per command:

```
src/docex/orchestrate/
├── __init__.py
├── up.py
├── down.py
├── build.py
├── test.py
└── migrate.py
```

Each module exposes a `run_<command>(ctx: ProjectContext, docker: DockerClient, **args) -> int` entry point. The dispatcher imports and calls these.

The shared concerns (recompile-before-run, validate env name is fixed, locate compose file) go in `src/docex/orchestrate/_common.py`:

```python
def ensure_compiled(ctx: ProjectContext) -> None: ...
def compose_file_for(ctx: ProjectContext, env: str) -> Path: ...
def assert_fixed_env(env: str) -> None: ...  # raises if env not in {"dev", "test"} where applicable
def services_with_schema(ctx: ProjectContext) -> list[str]: ...  # core services with schema_owned_by
def core_services(ctx: ProjectContext) -> list[str]: ...
```

`ensure_compiled` calls `run_compile(ctx)` defensively — keeps the user from having to remember `docex compile` before `docex up`. Document this in each command's docstring.

### Step 6: `up <env>`

`src/docex/orchestrate/up.py`. Per [docex.md § up](../../doctrine/infrastructure/docex.md#up) and [cicd.md § Migrate Step](../../doctrine/infrastructure/cicd.md#migrate-step):

1. Validate `env in {"dev", "test"}`. Reject `stage`/`prod` with `EnvNotSupported("'docex up' is only for dev/test envs; for stage/prod, use docex release.")`.
2. Call `ensure_compiled(ctx)`.
3. Call `docker.compose_up(compose_file_for(ctx, env), build=True, detach=True)`. Compose handles "rebuild if Dockerfile or context changed".
4. For each `services_with_schema(ctx)` core service: call `docker.compose_exec(..., service, ["./migrate.sh"])` (after the stack is up). Per the doctrine, dev/test migrations run inside the running container.
5. Exit 0 on success; if compose_up fails or any migration fails, exit non-zero and leave the stack as-is (don't auto-tear-down on `up` failure — the developer needs the half-up state to debug).

Print a short post-success message: `Stack up. Compose file: <path>. Services: <list>. Domain: dev.<domain>`.

### Step 7: `down <env>`

`src/docex/orchestrate/down.py`. Per [docex.md § down](../../doctrine/infrastructure/docex.md#down):

1. Validate `env in {"dev", "test"}`.
2. Call `docker.compose_down(compose_file_for(ctx, env), preserve_volumes=True)`.

Preserving volumes is doctrinal — persistent data survives `docex down`. Inside `SubprocessDockerClient`, that's `docker compose down` without `-v`.

### Step 8: `build [<svc>]`

`src/docex/orchestrate/build.py`. Per [docex.md § build](../../doctrine/infrastructure/docex.md#build) and [cicd.md § Build Step (dev iteration)](../../doctrine/infrastructure/cicd.md#process-dev-iteration):

1. Validate `env == "dev"`. `build` is dev-iteration-only; running it without an `up dev` is an error.
2. If `<svc>` is omitted: iterate over `core_services(ctx)`. Otherwise: just `<svc>`.
3. For each service:
   a. Verify the dev container is running. If not, error: `"dev env is not running; run 'docex up dev' first"`.
   b. Clear the host's `core/<svc>/dist/` directory (it's bind-mounted into the container — clearing on host clears it inside too).
   c. `docker.compose_exec(compose_file_for(ctx, "dev"), svc, ["./build.sh"])`.
   d. After execution: assert `core/<svc>/dist/` is non-empty. If it is empty, fail with the doctrine's error pointing at likely causes (misconfigured bind mount, wrong output path in `build.sh`).
4. Exit 0 on full success; non-zero on the first failure (skip remaining services).

The "dev container running" check is what makes this command meaningfully different from "just run `docker compose exec` yourself": the doctrine prescribes a single canonical iteration path, with dist-empty diagnostics built in.

### Step 9: `test`

`src/docex/orchestrate/test.py`. Per [docex.md § test](../../doctrine/infrastructure/docex.md#test) and [cicd.md § Build Test Step](../../doctrine/infrastructure/cicd.md#build-test-step):

1. Call `ensure_compiled(ctx)`.
2. Bring up the **test** env: `docker.compose_up(compose_file_for(ctx, "test"), build=True, detach=True)`. The Dockerfile's `build` stage runs `build.sh` inside `docker build`, so artifacts inside the test image are correct by construction.
3. Run migrations: for each `services_with_schema(ctx)` service, `docker.compose_exec(..., svc, ["./migrate.sh"])`.
4. Run tests: for each core service in `core_services(ctx)`, `docker.compose_exec(..., svc, ["./test.sh"])`. Collect the per-service exit codes.
5. **Always tear down**, success or failure: `docker.compose_down(compose_file_for(ctx, "test"), preserve_volumes=False)`. The test env is throwaway — tear down deletes volumes too. Use a `try/finally` so a Python exception in step 4 doesn't leak the test stack.
6. Exit 0 if every step exited 0; non-zero on the first failure encountered.

Per the doctrine the test env's volumes are not persistent — fresh test runs get fresh databases. That's why we pass `preserve_volumes=False` here.

### Step 10: `migrate <env>`

`src/docex/orchestrate/migrate.py`. Per [docex.md § migrate](../../doctrine/infrastructure/docex.md#migrate) (you may need to add a short section to docex.md if it isn't already there) and the migrate-step in cicd.md:

1. If `env in {"stage", "prod"}`: exit with `"'docex migrate <env>' for stage/prod is part of Phase 3 (fixed) / Phase 4 (elastic); not yet implemented in docex 0.2.0"` and code 2. Same shape as the Phase 2/3/4 stubs in the dispatcher.
2. If `env in {"dev", "test"}`: for each `services_with_schema(ctx)` service, `docker.compose_exec(compose_file_for(ctx, env), svc, ["./migrate.sh"])`. Requires the env to be up; error clearly if not.
3. Exit 0 if all succeeded; non-zero on first failure.

The `up <env>` command in Step 6 already invokes the migrate machinery — `docex migrate dev` is the explicit-form equivalent, useful when a developer adds a migration mid-session and wants to apply it without restarting the stack.

### Step 11: Wire dispatcher

In `src/docex/__main__.py`, replace the five Phase 2 stubs (`up`, `down`, `build`, `test`, `migrate`) with real argparse subparsers that import the orchestrate-package entry points and pass a `SubprocessDockerClient`.

Keep the Phase 3/4 stubs untouched. Add `migrate stage` / `migrate prod` as a special case **inside** the migrate handler (per Step 10) — not as separate subparsers, since `<env>` is an argument.

Bump `docex.__version__` to `0.2.0` and update the stub messages everywhere to reference the new version.

### Step 12: Unit tests with mocked `DockerClient`

Under `tests/unit/`, add:

- `test_orchestrate_up.py` — uses a `FakeDockerClient` that records every call and returns scripted exit codes. Asserts:
  - `up dev` rejects stage/prod env names.
  - `up dev` calls `compose_up` then `compose_exec` for each schema-owning service.
  - `up dev` short-circuits on migration failure and returns the failed exit code.
- `test_orchestrate_down.py` — verifies `preserve_volumes=True`, env validation.
- `test_orchestrate_build.py` — asserts `dist/` is cleared before `build.sh`, error raised if `dist/` empty after, env-not-dev rejected.
- `test_orchestrate_test.py` — asserts compose_down runs in the failure path too (the `try/finally`), `preserve_volumes=False` for tear-down, multi-service test runs in declared order.
- `test_orchestrate_migrate.py` — stage/prod stubs return the right message and exit code; dev/test paths call compose_exec per schema-owning service.

The `FakeDockerClient` lives at `tests/conftest.py` (extend the existing one) as a pytest fixture. Each call appends to a `calls: list[tuple[str, ...]]` so assertions read naturally.

### Step 13: Integration tests with real docker

Under `tests/integration/`, add:

- `test_up_down_real.py` — gated by a pytest skip-marker that checks `docker info` works at collection time. Brings up the sample fixture's dev env, asserts containers are running, tears down. Cleans up named volumes so the test is hermetic across runs.
- `test_build_real.py` — brings up dev, writes a new file to `src/`, runs `docex build api`, asserts the new file appears in `dist/`.
- `test_migrate_real.py` — brings up dev, runs `docex migrate dev`, asserts the migration's table exists in postgres (use `compose_exec` with `psql -c '\dt'`).
- `test_test_real.py` — runs `docex test`, asserts exit 0, asserts the test env is torn down afterward (`docker compose ps` returns empty).

Mark these with `@pytest.mark.integration` and configure pytest to skip them by default. Run them via `pytest -m integration`. Document this in `tests/README.md`.

CI does **not** need to run integration tests for Phase 2 — they're for the implementer's manual confirmation that real docker works. If you want a CI gate, set up a single GitHub Actions or local-runner step that calls `pytest -m integration` on a docker-enabled runner.

### Step 14: End-to-end smoke test

The Phase 2 acceptance gate. After Step 13's integration tests are passing locally, do this manually:

1. Rebuild the image: `cd ~/.claude/jean_baudrillard/docex && docker build -t docex:0.2.0 .`
2. Update the sample fixture's `project.yml` to pin `docex_version: "0.2.0"`.
3. Copy the fixture to a fresh dir: `rm -rf /tmp/smoke2 && cp -r tests/fixtures/sample_project /tmp/smoke2 && cd /tmp/smoke2`
4. Run `./bin/docex compile`. Confirm dev compose has the bind mounts (Step 1 fix).
5. Run `./bin/docex up dev`. Confirm:
   - Containers start (`docker ps` shows `sample-dev-api`, `sample-dev-database`).
   - The api service is reachable: `curl http://dev.example.com/health` (or hit the container directly on its port) returns `{"version": "0.1.0"}`.
   - Migrations ran (psql into the database and confirm the `health` table exists).
6. Edit `core/api/src/app.py` to change the version string. Run `./bin/docex build api`. Confirm `core/api/dist/app.py` now contains the new version. Without restarting the container, hit `/health` again — it should report the new version (assuming the app re-reads its source or you restart it via `docker compose restart`).
7. Run `./bin/docex migrate dev` again — it should be a no-op (migrations are idempotent) and exit 0.
8. Run `./bin/docex test`. Confirm:
   - The test env spins up.
   - The smoke test passes.
   - The test env is torn down afterward (`docker ps` no longer shows `sample-test-*` containers).
   - Named volumes for the test env are also gone (`docker volume ls` shouldn't list `sample-test-database_data`).
9. Run `./bin/docex down dev`. Confirm containers stop and disappear. Confirm the named volume `sample-dev-database_data` is still present (preserved per doctrine).
10. Run `./bin/docex up dev` again. Confirm the database still contains the migrated data (volume preservation worked).
11. Stub commands still work: `./bin/docex containerize`, `./bin/docex release stage`, `./bin/docex migrate prod` all return Phase 3/4 messages.

If all 11 succeed, Phase 2 is done.

## Things to Avoid

- **Don't bypass `DockerClient`.** Every docker call must go through it. If you `import subprocess` anywhere outside `subprocess_client.py`, you'll lose the ability to unit-test that path. The temptation will arise — resist.
- **Don't reach for `docker compose -f ... up -d` strings inline.** Build the argument list as a Python list and let `subprocess.run` quote correctly. Shell-interpolating compose-file paths is a quoting bug waiting to happen.
- **Don't add features beyond the five Phase 2 commands.** `docex logs`, `docex shell`, `docex restart` etc. are very tempting but out of scope. The doctrine doesn't prescribe them; adding them now would set permanent contracts unilaterally.
- **Don't make `up dev` smart about reusing state.** Compose's idempotence is enough. Re-running `docex up dev` against an already-up stack should be a near-no-op via compose's own logic; we don't add docex-level caching on top.
- **Don't pre-implement migrate for stage/prod.** Even partially. Phase 3 and Phase 4 will revisit migrate when wiring release flows — letting them have a clean canvas avoids rework.
- **Don't break the depends_on regression test or the substitution tests added in Phase 1.** The Phase 1 patch in Step 1 touches the compose emitter — re-run the full test suite after every change.
- **Don't add a separate dev-vs-prod codepath for transfer table content.** The bind-mount additions in Step 1 are an env-specific decoration applied at compile time, not a different transfer table entry. Keep the table content foundation-symmetric.

## What Happens After Phase 2

When Phase 2 ships, the doctrine is *runnable locally* on a fixed dev/test stack. A developer can author, build, migrate, and test against real containers — the entire inner development loop. They still cannot release to stage or prod through docex.

Phase 3 (`check`, `merge`, `containerize`, `release` for fixed, `stagetest`) closes the rest of the fixed-foundation CI/CD chain. That's the natural next implementation document.
