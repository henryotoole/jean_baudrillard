# Mod 088 — Implementation steps

All paths relative to the repo root `~/.claude/jean_baudrillard` unless noted.
The docex project root is `~/.claude/jean_baudrillard/docex`.

## 1. Doctrine clarification (operator-approved)

File: `doctrine/infrastructure/specifics/scheduler.md`

In the `## Caveats` section, the first bullet ("**`test` suppresses the scheduler
trigger.**") ends with:

> ... Exercise a job's logic through its own unit/module tests, or in `dev`,
> rather than relying on a `test`-window fire.

Append one sentence to that bullet, verbatim:

> `docex test` still runs a scheduler's `test.sh`: since there is no
> `test`-stack container to `exec` into, docex builds the service's `test`-stage
> image and runs `test.sh` as a one-off container (no env-tier stack attached),
> so keep a scheduler's tests self-contained unit/module tests.

Change nothing else in the doctrine.

## 2. docex code

File: `docex/src/docex/orchestrate/test.py`

- Import `scheduler_services` from `docex.orchestrate._common` (alongside the
  existing imports).
- Add a small helper, `_run_scheduler_test.sh` runner, e.g.:

  ```python
  def _run_scheduler_tests(
      ctx: ProjectContext,
      docker: DockerClient,
      svc: str,
      *,
      project_dir: "Path | None",
  ) -> int:
      """Run a scheduler service's test.sh via a one-off container.

      A scheduler has no long-running container in the ``test`` stack
      (scheduler.md §225 — the compiler emits no Ofelia container for
      ``test``), so it cannot be ``compose exec``-ed like other core
      services. Build its ``test``-stage image and run ``test.sh`` as a
      one-off (mirrors ``up.py::_ensure_scheduler_image``'s build-directly
      pattern). The scheduler's tests are self-contained unit/module tests
      per the doctrine, so no env-tier stack/network is attached.
      """
      base = project_dir if project_dir is not None else ctx.project_root
      svc_dir = base / "core" / svc
      tag = f"docex-test-{dns_label(ctx.project.name)}-{svc}:latest"
      rc = docker.build_image(svc_dir, target="test", tag=tag)
      if rc != 0:
          return rc
      return docker.run_one_shot(tag, ["./test.sh"])
  ```

  Import `dns_label` from `docex.naming`.

- In `run_test` step 3 (the `for svc in core_services(ctx)` loop), partition on
  scheduler membership:

  ```python
  schedulers = set(scheduler_services(ctx))
  for svc in core_services(ctx):
      if svc in schedulers:
          rc = _run_scheduler_tests(ctx, docker, svc, project_dir=project_dir)
      else:
          key = compose_service_key(ctx, _TEST_ENV, svc)
          rc = docker.compose_exec(
              compose_file, key, ["./test.sh"],
              env_file=env_file, project_dir=project_dir,
              project_name=project_name,
          )
      if rc != 0:
          print(f"error: test.sh for {svc!r} exited {rc}.", file=sys.stderr)
          first_failure = rc
          return rc
  ```

  Keep the existing error message/behavior (fail on first failure) identical.

## 3. Unit tests

File: `docex/tests/unit/test_orchestrate_test.py`

Use the existing scheduler fixture `tests/fixtures/sample_project_scheduler_fixed`
(project `sample`, scheduler service `nightly_cleanup` + a `web` service). Copy
the `scheduler_ctx` fixture pattern from `tests/unit/test_orchestrate_up.py`
(lines ~18-31: `shutil.copytree` the fixture into `tmp_path`, drop
`infra/output`, `load_project_context(dest)`) into `test_orchestrate_test.py`
(or share it). `fake_docker.build_image` / `run_one_shot` are recorded, not
really executed, so no real `test`-stage image is needed.

Add a test asserting the scheduler path:
- `test_run_test_scheduler_uses_one_off`: with a scheduler-bearing ctx, run
  `run_test` on `fake_docker`; assert that for the scheduler service the fake
  recorded a `build_image(target="test", tag=...)` **and** a
  `run_one_shot(tag, ["./test.sh"])`, and did **not** record a `compose_exec`
  with the scheduler's key. Assert non-scheduler services still went through
  `compose_exec`.
- If `fake_docker` needs to return non-zero for a scheduler build/run to test the
  failure path, use the existing exit-code injection mechanism; assert `run_test`
  returns that code.

Ensure existing `test_orchestrate_test.py` cases still pass (non-scheduler
projects must behave exactly as before).

## 4. Verify

From `~/.claude/jean_baudrillard/docex`:

```
python -m pytest tests/unit/test_orchestrate_test.py -q
python -m pytest -q          # full unit suite must stay green
```

Do NOT run `-m integration`. Do NOT touch version artifacts, CHANGELOG, or any
core planning doc. Do NOT git commit — leave changes in the working tree.

## Acceptance

- `docex test` runs a scheduler's `test.sh` via `build_image(target="test")` +
  `run_one_shot(["./test.sh"])`; non-schedulers unchanged (`compose_exec`).
- `scheduler.md` caveat carries the one appended sentence, nothing else changed
  in doctrine.
- `test_orchestrate_test.py` covers the scheduler one-off path; full unit suite
  green.
