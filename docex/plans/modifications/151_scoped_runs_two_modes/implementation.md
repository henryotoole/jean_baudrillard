# Mod 151 — Implementation Steps

Fresh-context implementation guide for **Mod 151 — Scoped Runs + Two Honest
Modes (F5)**. Read `overview.md` in this folder first for the design and the two
resolved design questions. This mod is **docex-source + doctrine** work; it builds
on Mods 147 (two-shim contract) and 148 (durable-job substrate), neither of whose
mechanisms it changes.

All paths are relative to the docex project root
`/home/ubuntu/.claude/jean_baudrillard/docex/` unless noted `doctrine/…` or
`skills/…` (those live one level up, under `/home/ubuntu/.claude/jean_baudrillard/`).

The end state delivers three surfaces:
- `docex test` — unchanged (durable job, both tiers, fresh throwaway stack).
- `docex test integration [subset]` — durable job (shares `test`'s lock), fresh
  stack, integration tier only, optional subset.
- `docex test unit [subset]` — **plain synchronous** throwaway run, **no compose
  stack**, no lock, `--detach` rejected.

Subset selection is carried to the project shims by one injected env var,
**`DOCEX_TEST_SELECTOR`**.

Do the steps in order. Run `python -m pytest tests` (NOT bare `pytest`) at the end
and keep it green.

---

## Step 1 — Add `no_deps` to the docker client's `compose_run_one_off`

Two files define this method: the protocol/base and the subprocess impl. Add a
keyword-only `no_deps: bool = False` param to both, defaulting False so every
existing call site is unaffected.

### 1a. `src/docex/docker/client.py`

Add `no_deps: bool = False` to the `compose_run_one_off` signature (keyword-only,
after `build`). Extend the docstring with one line:

> `no_deps=True` adds `--no-deps` so `compose run` does **not** start the
> service's `depends_on` backing services — used by the no-stack `docex test unit`
> fast lane, which must create zero stack containers.

### 1b. `src/docex/docker/subprocess_client.py`

In `compose_run_one_off` (around line 161), add the same param and emit the flag.
The current command build is:

```python
) + ["run", "--rm", "-T"]
if build:
    cmd.append("--build")
```

Add, right after the `--build` block (order relative to `--build` does not matter
to compose, but keep it adjacent):

```python
if no_deps:
    cmd.append("--no-deps")
```

---

## Step 2 — Extend the `FakeDockerClient` to record `env` and accept `no_deps`

`tests/conftest.py`, `FakeDockerClient.compose_run_one_off` (around line 108).

1. Add `no_deps: bool = False` to the signature (keyword-only, after `build`).
2. Record `env` and `no_deps` as **side-calls**, the same pattern `build` already
   uses (so the primary `("compose_run_one_off", file, svc, cmd)` tuple that many
   tests assert on verbatim is untouched). After the existing `build` side-call
   block, add:

```python
if env:
    self.calls.append(
        ("compose_run_one_off_env", service, tuple(command), tuple(sorted(env.items())))
    )
if no_deps:
    self.calls.append(
        ("compose_run_one_off_no_deps", service, tuple(command))
    )
```

Leave the `exit_codes` lookup keyed on the primary tuple exactly as is.

---

## Step 3 — Parametrize `run_test` and add the synchronous unit lane

`src/docex/orchestrate/test.py`.

### 3a. Parametrize `run_test` with `tiers` and `selector`

Change the signature to add two keyword-only params:

```python
def run_test(
    ctx: ProjectContext,
    docker: DockerClient,
    *,
    project_dir: "Path | None" = None,
    env_file_override: "Path | None" = None,
    project_name: "str | None" = None,
    tiers: "tuple[str, ...]" = ("unit", "integration"),
    selector: "str | None" = None,
) -> int:
```

Update the module/function docstrings to note the new params:
- `tiers` — which shim tiers to run in the up stack; defaults to both (the full
  `docex test`). `("integration",)` is the `docex test integration [subset]` lane
  (still stack-backed: up + migrate + tear down, but runs only
  `test_integration.sh`).
- `selector` — when set, injected into each shim's one-off container as
  `DOCEX_TEST_SELECTOR` so the project shim can narrow the run to a subset.

Then, in the shim-running loop (currently step 3, the
`for shim in ("./test_unit.sh", "./test_integration.sh"):` block), make it honor
`tiers` and inject the selector. Replace the hardcoded shim tuple with a mapping
from tier name to shim filename, iterate only the requested tiers **in
unit-before-integration order**, and pass the selector env:

```python
_TIER_SHIMS = {"unit": "./test_unit.sh", "integration": "./test_integration.sh"}
```
(module-level constant, near `_TEST_ENV`.)

```python
        # 3. Requested tiers, phased (unit before integration). Each shim runs as
        # a one-off in the codebase's exec service against the already-up stack.
        # `selector`, when set, reaches the project shim as DOCEX_TEST_SELECTOR so
        # it can narrow the run to a subset (see tests.md § Two execution modes).
        selector_env = (
            {"DOCEX_TEST_SELECTOR": selector} if selector else None
        )
        for tier in ("unit", "integration"):
            if tier not in tiers:
                continue
            shim = _TIER_SHIMS[tier]
            for svc in codebases(ctx):
                key = exec_service_key(ctx, _TEST_ENV, svc)
                rc = docker.compose_run_one_off(
                    compose_file, key, [shim], build=True,
                    env=selector_env,
                    env_file=env_file, project_dir=project_dir,
                    project_name=project_name,
                )
                if rc != 0:
                    print(f"error: {shim} for {svc!r} exited {rc}.",
                          file=sys.stderr)
                    first_failure = rc
                    return rc
```

Everything else in `run_test` (compose up, migrate over `codebases_with_schema`,
the `finally` teardown with `preserve_volumes=False`) is unchanged. The
integration lane still brings the stack up and migrates — it is stack-backed.

**Note on migrate + `tiers=("integration",)`:** keep the migrate loop
unconditional (it runs for every stack-backed invocation). For the full run and
the integration lane both, migrate is correct. It is only the *unit* lane (Step
3b, a separate function) that skips migrate.

### 3b. Add `run_test_unit` — the synchronous no-stack fast lane

Add a new function to the same module. It brings up **no stack**, does **no
migrate**, and does **no teardown** — it runs each codebase's `test_unit.sh` as a
one-off with `--no-deps` so the `depends_on` backing services never start. It uses
the standard `test` compose project name so the exec image is shared with the full
`test` env (keeping the lane fast — no distinct-project image rebuild).

```python
def run_test_unit(
    ctx: ProjectContext,
    docker: DockerClient,
    *,
    selector: "str | None" = None,
) -> int:
    """The no-stack unit fast lane (``docex test unit [subset]``).

    Runs ONLY each codebase's ``test_unit.sh`` in a throwaway ``--rm`` exec
    container with ``--no-deps`` — so no ``depends_on`` backing services start
    and **no compose stack is brought up**. There is no migrate (the unit tier is
    no-infra), no teardown, and no durable job / lock (a stackless run touches no
    shared infra, so nothing can contend). Seconds, not minutes.

    ``selector``, when set, reaches ``test_unit.sh`` as ``DOCEX_TEST_SELECTOR`` so
    the shim can narrow to a subset (see tests.md § Two execution modes). Uses the
    standard ``test`` compose project name so the exec image is shared with the
    full ``test`` env. Fail-fast on the first non-zero; returns that code.
    """
    ensure_compiled(ctx)
    compose_file = compose_file_for(ctx, _TEST_ENV)
    env_file = aggregate(ctx, env=_TEST_ENV)
    project_name = env_compose_project(ctx, _TEST_ENV)
    selector_env = {"DOCEX_TEST_SELECTOR": selector} if selector else None

    for svc in codebases(ctx):
        key = exec_service_key(ctx, _TEST_ENV, svc)
        rc = docker.compose_run_one_off(
            compose_file, key, ["./test_unit.sh"], build=True,
            no_deps=True,
            env=selector_env,
            env_file=env_file, project_name=project_name,
        )
        if rc != 0:
            print(f"error: ./test_unit.sh for {svc!r} exited {rc}.",
                  file=sys.stderr)
            return rc
    return 0
```

Confirm the imports at the top of the module already include `aggregate`,
`ensure_compiled`, `compose_file_for`, `env_compose_project`, `codebases`,
`exec_service_key` — they do (used by `run_test`). No new imports needed.

---

## Step 4 — Thread `tiers` / `selector` through the job substrate

`src/docex/jobs/commands.py`. The full run and the integration lane are both
durable jobs of `kind="test"` sharing the same lock scope; they differ only in the
`params` recorded on the run and read back inside the vessel.

### 4a. Job bodies receive `params`

Change the three `_JOB_BODIES` bodies to accept a `params` dict, and have
`_run_test_body` use it. check/merge ignore it.

```python
def _run_test_body(ctx, docker, params) -> int:
    from docex.orchestrate.test import run_test

    tiers = tuple(params.get("tiers") or ("unit", "integration"))
    selector = params.get("selector")
    return run_test(ctx, docker, tiers=tiers, selector=selector)


def _run_check_body(ctx, docker, params) -> int:  # params unused
    from docex.git import SubprocessGitClient
    from docex.pipeline.check import run_check
    return run_check(ctx, docker, SubprocessGitClient())


def _run_merge_body(ctx, docker, params) -> int:  # params unused
    from docex.git import SubprocessGitClient
    from docex.pipeline.merge import run_merge
    return run_merge(ctx, docker, SubprocessGitClient())
```

### 4b. `run_in_vessel` passes `meta.params` to the body

In `run_in_vessel` (around line 501), change the body dispatch from
`rc = body(ctx, docker)` to `rc = body(ctx, docker, meta.params)`.

`meta.params` is always a dict (existing `check`/`merge` runs record their
teardown identities there; `test` runs recorded `{}` before this mod). A body that
ignores it is safe. No migration of old records is needed — a stale record's
`params` still deserializes to a dict.

### 4c. `run_test_job` records the tier/selector params

Give `run_test_job` optional `tiers` / `selector` and record them in `params`. Keep
the default = full run so the plain `docex test` path is byte-identical.

```python
def run_test_job(
    ctx, docker, *, detach: bool,
    tiers: tuple[str, ...] = ("unit", "integration"),
    selector: str | None = None,
) -> int:
    """Launch ``docex test`` (or ``docex test integration [subset]``) as a
    durable, container-vessel job. The integration lane shares ``test``'s lock
    scope — both contend over the same ``test`` stack, so they refuse each other.
    """
    label = dns_label(ctx.project.name)
    return _launch_durable_job(
        ctx, docker,
        kind="test",
        scope=f"{label}/test",
        vessel_name=f"{label}-test-runner",
        params={"tiers": list(tiers), "selector": selector},
        detach=detach,
    )
```

No change to `_launch_durable_job`, the vessel, the reaper, or check/merge job
launchers. The `scope` / `vessel_name` are deliberately identical for full and
integration so the lock is shared.

---

## Step 5 — CLI: `docex test [unit|integration] [subset] [--detach]`

`src/docex/__main__.py`, `_cmd_test` (around line 426). Rewrite the parser +
dispatch:

```python
def _cmd_test(args: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="docex test", add_help=True)
    parser.add_argument(
        "tier", nargs="?", choices=["unit", "integration"], default=None,
        help="restrict to one execution mode: 'unit' (no-stack fast lane) or "
             "'integration' (stack-backed). Omit to run both tiers in a fresh "
             "throwaway stack (the formal isolation mode).",
    )
    parser.add_argument(
        "subset", nargs="?", default=None,
        help="optional within-tier selector forwarded to the codebase test shim "
             "as DOCEX_TEST_SELECTOR (a pytest-args fragment for the exemplar "
             "shim: a path and/or -m/-k expression). Omit to run the whole tier.",
    )
    parser.add_argument(
        "--detach", action="store_true",
        help="launch the run detached and print its handle instead of blocking "
             "(not valid for the synchronous 'unit' lane)",
    )
    ns = parser.parse_args(args)

    from docex.context import load_project_context
    ctx = load_project_context(Path(os.getcwd()))
    docker = _require_docker()

    if ns.tier == "unit":
        if ns.detach:
            print(
                "error: 'docex test unit' is a synchronous no-stack run; "
                "--detach does not apply.",
                file=sys.stderr,
            )
            return 64  # EX_USAGE
        from docex.orchestrate.test import run_test_unit
        return run_test_unit(ctx, docker, selector=ns.subset)

    from docex.jobs.commands import run_test_job
    if ns.tier == "integration":
        return run_test_job(
            ctx, docker, detach=ns.detach,
            tiers=("integration",), selector=ns.subset,
        )
    # No tier → the full durable job, unchanged.
    return run_test_job(ctx, docker, detach=ns.detach)
```

Confirm `sys` is imported in `__main__.py` (it is, used elsewhere). If a `subset`
is given without a `tier` (`docex test foo`), argparse assigns it to `tier` and
fails the `choices` check with a clear error — acceptable; the doctrine surface is
`docex test <tier> [subset]`.

Also update the `_HELP_TEXT["test"]` one-liner (around line 37) to mention the two
modes, additively, e.g.:

```python
"test": "Run build-time tests in a fresh test env (durable job; --detach for a "
        "handle). 'test unit [sel]' = no-stack fast lane; 'test integration "
        "[sel]' = stack-backed subset.",
```

---

## Step 6 — Update docex's own fixture shims (keep them a correct exemplar)

Six files, three codebase pairs. Each shim, when `DOCEX_TEST_SELECTOR` is set,
forwards it to pytest as an **unquoted args fragment** (so a multi-token selector
like `tests/unit/foo.py -k bar` word-splits into separate args); when unset it runs
the whole tier folder. The comment must say the var is a pytest-args fragment so a
downstream author does not quote it into a single literal.

### `test_projects/fixed/core/api/test_unit.sh`

```sh
#!/bin/sh
# test_unit.sh — no-infra test tier for the `api` codebase.
# Domain / alogic / adapter-unit tests under tests/unit/ (stub-backed: no
# postgres, no live stack). Globs the folder; the folder is the authority.
#
# DOCEX_TEST_SELECTOR (optional, injected by `docex test unit [subset]`): a
# pytest-args FRAGMENT (a path under tests/unit and/or a -m/-k expression),
# forwarded UNQUOTED so multiple tokens word-split into separate args. When set
# it replaces the default whole-tier target; unset runs the whole tier.
set -eu
if [ -n "${DOCEX_TEST_SELECTOR:-}" ]; then
    # shellcheck disable=SC2086
    exec pytest -q $DOCEX_TEST_SELECTOR
fi
exec pytest -q /service/tests/unit
```

### `test_projects/fixed/core/api/test_integration.sh`

Same pattern; keep the existing header comment, swap the default target to
`/service/tests/integration`:

```sh
#!/bin/sh
# test_integration.sh — stack-backed test tier for the `api` codebase.
# Module-integration / flow / contract tests under tests/integration/, run
# against the live test-env stack (real postgres, sibling core services).
# Globs the folder; the folder is the authority.
#
# DOCEX_TEST_SELECTOR (optional, injected by `docex test integration [subset]`):
# a pytest-args FRAGMENT, forwarded UNQUOTED (see test_unit.sh). Set → replaces
# the default whole-tier target; unset → whole tier.
set -eu
if [ -n "${DOCEX_TEST_SELECTOR:-}" ]; then
    # shellcheck disable=SC2086
    exec pytest -q $DOCEX_TEST_SELECTOR
fi
exec pytest -q /service/tests/integration
```

### `test_projects/elastic/core/api/test_unit.sh` and `test_integration.sh`

Apply the identical two-file pattern (default targets `/service/tests/unit` and
`/service/tests/integration` respectively). Preserve each file's existing header
comment wording where it differs, but add the `DOCEX_TEST_SELECTOR` block + comment.

### `tests/fixtures/sample_project/core/api/test_unit.sh` and `test_integration.sh`

Same pattern. These are terse; keep their existing two-line headers and add the
selector block:

```sh
#!/bin/sh
# test_unit.sh — no-infra test tier for the api core service.
# Exits 0 on pass, non-zero on failure.
# DOCEX_TEST_SELECTOR (optional): a pytest-args fragment, forwarded UNQUOTED;
# set → replaces the whole-tier target.
set -eu
if [ -n "${DOCEX_TEST_SELECTOR:-}" ]; then
    # shellcheck disable=SC2086
    exec pytest -q $DOCEX_TEST_SELECTOR
fi
exec pytest -q /service/tests/unit
```

(and the `/service/tests/integration` variant for `test_integration.sh`.)

Keep every shim executable (they already are; `chmod +x` if any tooling resets
the bit).

---

## Step 7 — Tests (this is the manual-test replacement; must be green)

### 7a. `tests/unit/test_orchestrate_test.py` — the unit fast lane + integration lane

Add tests. Reuse the existing `sample_ctx` / `fake_docker` and `multi_ctx`
fixtures.

**Unit lane — no stack, no migrate, no teardown, `--no-deps`:**

```python
from docex.orchestrate.test import run_test, run_test_unit


def test_unit_lane_brings_up_no_stack(sample_ctx, fake_docker):
    rc = run_test_unit(sample_ctx, fake_docker)
    assert rc == 0
    methods = [c[0] for c in fake_docker.calls]
    # THE no-stack property: never a compose up, never a migrate, never a down.
    assert "compose_up" not in methods
    assert "compose_down" not in methods
    run_calls = [c for c in fake_docker.calls if c[0] == "compose_run_one_off"]
    # Only the unit shim runs — no migrate, no integration shim.
    assert [c[3] for c in run_calls] == [("./test_unit.sh",)]
    # And it ran with --no-deps (the flag that suppresses depends_on backing svcs).
    assert ("compose_run_one_off_no_deps", "sample-test-api-exec",
            ("./test_unit.sh",)) in fake_docker.calls


def test_unit_lane_multi_codebase_no_deps_each(multi_ctx, fake_docker):
    rc = run_test_unit(multi_ctx, fake_docker)
    assert rc == 0
    no_deps = [c for c in fake_docker.calls
               if c[0] == "compose_run_one_off_no_deps"]
    assert [c[1] for c in no_deps] == [
        "sample-test-api-exec", "sample-test-reporter-exec",
    ]
    assert "compose_up" not in [c[0] for c in fake_docker.calls]


def test_unit_lane_injects_selector(sample_ctx, fake_docker):
    rc = run_test_unit(sample_ctx, fake_docker, selector="tests/unit/foo.py -k bar")
    assert rc == 0
    env_calls = [c for c in fake_docker.calls
                 if c[0] == "compose_run_one_off_env"]
    assert env_calls, "selector must be injected as env"
    # side-call shape: (tag, svc, cmd_tuple, sorted_env_items)
    assert env_calls[0][3] == (("DOCEX_TEST_SELECTOR", "tests/unit/foo.py -k bar"),)


def test_unit_lane_no_selector_no_env(sample_ctx, fake_docker):
    rc = run_test_unit(sample_ctx, fake_docker)
    assert rc == 0
    assert [c for c in fake_docker.calls
            if c[0] == "compose_run_one_off_env"] == []


def test_unit_lane_fails_fast_returns_code(multi_ctx, fake_docker):
    fake_docker.exit_codes[
        ("exit", "compose_run_one_off", "sample-test-api-exec",
         ("./test_unit.sh",))
    ] = 7
    rc = run_test_unit(multi_ctx, fake_docker)
    assert rc == 7
    # Fail-fast: the second codebase's unit shim never ran.
    ran = [c[2] for c in fake_docker.calls
           if c[0] == "compose_run_one_off" and c[3] == ("./test_unit.sh",)]
    assert ran == ["sample-test-api-exec"]
```

**Integration lane — stack-backed, integration shim only, selector injected:**

```python
def test_integration_lane_runs_only_integration_with_stack(sample_ctx, fake_docker):
    rc = run_test(sample_ctx, fake_docker, tiers=("integration",),
                  selector="tests/integration/foo.py")
    assert rc == 0
    methods = [c[0] for c in fake_docker.calls]
    assert "compose_up" in methods        # stack-backed
    assert "compose_down" in methods      # torn down
    run_cmds = [c[3] for c in fake_docker.calls if c[0] == "compose_run_one_off"]
    assert ("./migrate.sh",) in run_cmds          # migrate still runs
    assert ("./test_unit.sh",) not in run_cmds    # unit tier skipped
    assert ("./test_integration.sh",) in run_cmds
    # selector injected on the integration shim call
    env_calls = [c for c in fake_docker.calls
                 if c[0] == "compose_run_one_off_env"]
    assert (("DOCEX_TEST_SELECTOR", "tests/integration/foo.py"),) in [
        c[3] for c in env_calls
    ]


def test_full_run_unchanged_no_selector(sample_ctx, fake_docker):
    """Default run: both shims, no DOCEX_TEST_SELECTOR injected."""
    rc = run_test(sample_ctx, fake_docker)
    assert rc == 0
    run_cmds = [c[3] for c in fake_docker.calls if c[0] == "compose_run_one_off"]
    assert ("./test_unit.sh",) in run_cmds
    assert ("./test_integration.sh",) in run_cmds
    assert [c for c in fake_docker.calls
            if c[0] == "compose_run_one_off_env"] == []
```

The existing `test_orchestrate_test.py` cases must remain green unchanged (the
`env=None` default means no `compose_run_one_off_env` side-calls appear on the full
run — verify none of the existing assertions break; they key on the primary tuple
and `_build` side-call only).

### 7b. `tests/unit/test_orchestrate_test.py` note on `_raising_run` stand-in

The existing `test_test_teardown_still_runs_on_python_exception` defines a
`_raising_run` stand-in whose signature must match the client. **Add `no_deps=False`
to that stand-in's signature** (keyword-only, alongside `build`) and forward it in
its passthrough call, or the new param turns the intended RuntimeError into a
TypeError. Update:

```python
def _raising_run(compose_file, service, command, *, env=None,
                 build=False, no_deps=False, env_file=None, project_dir=None,
                 project_name=None):
    if command and command[0] == "./test_integration.sh":
        raise RuntimeError(boom_token)
    return original_run(
        compose_file, service, command, env=env, build=build, no_deps=no_deps,
        env_file=env_file, project_dir=project_dir, project_name=project_name,
    )
```

### 7c. CLI parse test

Add `tests/unit/test_cli_test_command.py` (or extend an existing `__main__`/CLI
test module if one exists — search `tests/unit` for a dispatcher test first). Use
`monkeypatch` to stub `run_test_unit` / `run_test_job` and assert routing without
touching docker:

```python
import docex.__main__ as m


def test_cli_test_unit_routes_synchronous(monkeypatch):
    calls = {}
    monkeypatch.setattr(m, "_require_docker", lambda: object())
    monkeypatch.setattr(
        "docex.context.load_project_context", lambda p: object())
    monkeypatch.setattr(
        "docex.orchestrate.test.run_test_unit",
        lambda ctx, docker, *, selector: calls.setdefault("unit", selector) or 0)
    rc = m._cmd_test(["unit", "tests/unit/foo.py"])
    assert rc == 0
    assert calls["unit"] == "tests/unit/foo.py"


def test_cli_test_unit_detach_is_usage_error(monkeypatch):
    monkeypatch.setattr(m, "_require_docker", lambda: object())
    monkeypatch.setattr(
        "docex.context.load_project_context", lambda p: object())
    rc = m._cmd_test(["unit", "--detach"])
    assert rc == 64


def test_cli_test_integration_routes_to_job(monkeypatch):
    seen = {}
    monkeypatch.setattr(m, "_require_docker", lambda: object())
    monkeypatch.setattr(
        "docex.context.load_project_context", lambda p: object())
    monkeypatch.setattr(
        "docex.jobs.commands.run_test_job",
        lambda ctx, docker, *, detach, tiers=("unit", "integration"),
        selector=None: seen.update(tiers=tiers, selector=selector, detach=detach) or 0)
    rc = m._cmd_test(["integration", "tests/integration/foo.py"])
    assert rc == 0
    assert seen == {"tiers": ("integration",),
                    "selector": "tests/integration/foo.py", "detach": False}
```

Adjust the monkeypatch import targets to the actual import sites if the stubs do
not intercept (the handler imports `run_test_unit` from `docex.orchestrate.test`
and `run_test_job` from `docex.jobs.commands` *inside* the function, so patching
the source module attribute works).

### 7d. Job-body signature test (if one exists)

Search `tests/unit` for tests that call `_JOB_BODIES[...]` or `run_in_vessel`
directly. If any invoke a body with the old `(ctx, docker)` arity, update them to
`(ctx, docker, params)` (pass `{}` or `{"tiers": [...], "selector": ...}`). If a
test drives `run_in_vessel` with a fake record, ensure the fake `meta.params` is a
dict.

---

## Step 8 — Doctrine amendments (approved by C.O.)

These live under `/home/ubuntu/.claude/jean_baudrillard/`. Keep every edit
**additive**; do not restructure.

### 8a. `doctrine/infrastructure/tests.md`

**(i)** Under `## Codebase Tests`, after the paragraph that ends "...invoked by the
[standard build-test step](./cicd.md#build-test-step)." (currently line 17), add a
new subsection:

```markdown
### Two execution modes

The two shims are not only a *classification* — they are two **execution modes**
with different infrastructure needs, and `docex test` exposes each directly:

- **`docex test`** (no argument) is the **formal isolation** mode: it brings up a
  fresh, throwaway `test` stack, runs both tiers in it, and tears it down. This is
  the mode CI/CD and an advance's close-out run — the full suite against clean
  infrastructure.
- **`docex test unit [subset]`** is the **fast lane**: it runs the no-infra unit
  tier in a throwaway container with **no compose stack brought up at all** (the
  `depends_on` backing services are suppressed), so it returns in seconds. It is
  the blessed replacement for hand-rolling a raw `docker run` to iterate on one
  failing unit test.
- **`docex test integration [subset]`** runs the stack-backed integration tier
  against a fresh `test` stack, optionally narrowed to a subset.

The subset — how you run *fewer than a whole tier* — is chosen the doctrine's own
way: the **tier** (`unit` / `integration`) is the primary selector, and an
optional within-tier refinement is carried by the injected variable below. This is
the sanctioned fast inner loop; it is not a way to skip the full run, which a mod
closes on and an advance and CI/CD always run.
```

**(ii)** Extend `### Injected environment` so it also covers the codebase-test
side (it currently documents only the stage tester). After the existing table +
its closing paragraph (currently line 101), add:

```markdown
The **codebase test shims** receive one injected variable on the same one-way,
stable footing:

| Variable | Source | Purpose |
| -------- | ------ | ------- |
| `DOCEX_TEST_SELECTOR` | the `[subset]` argument to `docex test unit`/`integration` | An opaque, runner-native selector the shim forwards to its test runner to narrow the run to a subset of its tier. **Unset ⇒ run the whole tier** (the default). Set ⇒ the shim runs only the named tests. |

The shim decides how to forward it in a way idiomatic to its runner (a `pytest`
shim splices it as an args fragment — a path and/or `-m`/`-k` expression); the
contract fixes only the variable and its meaning, never the runner. Like the stage
injections, this contract is one-way and stable — adding to it (as parallel test
sharding later will, with its own `DOCEX_TEST_*` variables) is a doctrine change,
not a project change.
```

### 8b. `doctrine/infrastructure/docex.md`

**(i)** `### test` (currently lines 175–180). Add the two-mode usage lines and a
paragraph. After the existing `./bin/docex test` / `--detach` usage lines, insert:

```markdown
`./bin/docex test unit [subset]`
`./bin/docex test integration [subset]`
```

And after the durable-job paragraph (line 180), add:

```markdown
`test` has two **execution modes** beyond the full run. `docex test unit [subset]`
runs only the no-infra unit tier in a throwaway container with **no compose stack
brought up** — the fast inner loop for iterating on a failing unit test; it is a
plain **synchronous** run (seconds, no shared infra to contend over, so no lock
and no durable-job vessel — `--detach` does not apply). `docex test integration
[subset]` runs the stack-backed integration tier against a fresh `test` stack and
**is** a durable job, sharing `test`'s lock scope (a full `docex test` and a
`docex test integration` refuse each other — they contend over the same stack). An
optional `[subset]` narrows the run within the chosen tier; docex forwards it to
the codebase's test shim as `DOCEX_TEST_SELECTOR` (see
[tests.md § Injected environment](./tests.md#injected-environment)). Omitting the
subset runs the whole tier.
```

**(ii)** Provided-Tools table `test` row (line 64). Extend additively:

```markdown
| `test` | Run build-time tests (unit, integration, contract) in a fresh `test` environment. A [durable job](#command-lifecycle); `--detach` returns a handle. `test unit [subset]` is a synchronous no-stack fast lane; `test integration [subset]` runs the stack-backed tier, optionally subset. |
```

**(iii)** `## Command Lifecycle`, the paragraph beginning "`test`, `check`, and
`merge` are all durable jobs." (line 47). Append one sentence at its end:

```markdown
 The `docex test unit` fast lane is the deliberate exception: a stackless unit run
touches no shared infra, so it is a plain synchronous run — no vessel, no lock, no
run record — not a durable job.
```

### 8c. `skills/testing/SKILL.md`

**(i)** Description (line 3): a **light, additive** tweak so the skill triggers on
"run one failing test" intent. Append to the existing description, before the final
"Not for..." sentence, a clause such as:

> ...and the two execution modes `docex test` exposes (the no-stack `docex test
> unit` fast lane for iterating on a failing test vs. the fresh-throwaway full
> run), including the `DOCEX_TEST_SELECTOR` subset contract.

Do **not** remove or narrow any existing trigger phrasing.

**(ii)** Add one Thread bullet (after the existing `docex test` durable-job bullet,
line 26), router-style, no duplicated prose:

```markdown
- **Two execution modes + subset.** `docex test unit [subset]` runs the unit tier
  with **no stack** (the fast inner loop); `docex test integration [subset]` runs
  the stack-backed tier; a `[subset]` narrows within the tier and reaches the
  project shim as the injected `DOCEX_TEST_SELECTOR`. Both the modes and the
  injected-variable contract are in [`tests.md § Two execution modes`](../../doctrine/infrastructure/tests.md#two-execution-modes)
  / [§ Injected environment](../../doctrine/infrastructure/tests.md#injected-environment).
```

If this Thread bullet or the description tweak starts to require more than a light
touch (restructuring, trigger-narrowing), STOP and flag it — full skill
trigger-eval is out of scope for this advance.

---

## Step 9 — Verify

From the docex project root:

```sh
python -m pytest tests
```

Must be fully green. Then confirm the two integration invocations still partition
(mod 139 guard) and nothing regressed:

```sh
python -m pytest tests -q
python -m pytest tests -q -m integration
```

Do **not** run the `-m integration` suite concurrently with the default suite
(docex_process § Running the automated tests, point 3).

Do NOT edit any file under `docex/plans/core/` (core planning docs) — those are
reconciled in the mod cycle's Documentation step, not here. Do NOT run
`git commit` — the mod driver handles commits.

---

## Summary of files touched

- `src/docex/docker/client.py` — `no_deps` param (protocol).
- `src/docex/docker/subprocess_client.py` — `no_deps` → `--no-deps`.
- `src/docex/orchestrate/test.py` — `tiers`/`selector` on `run_test`; new
  `run_test_unit`; `_TIER_SHIMS`.
- `src/docex/jobs/commands.py` — body `params` arity; `run_in_vessel` passes
  `meta.params`; `run_test_job` records `{tiers, selector}`.
- `src/docex/__main__.py` — `_cmd_test` tier/subset/detach parsing + routing;
  `_HELP_TEXT["test"]`.
- `tests/conftest.py` — `FakeDockerClient.compose_run_one_off` records `env`,
  accepts `no_deps`.
- `tests/unit/test_orchestrate_test.py` — unit-lane + integration-lane tests;
  `_raising_run` stand-in `no_deps`.
- `tests/unit/test_cli_test_command.py` (new) — CLI routing tests.
- 6 fixture shims under `test_projects/{fixed,elastic}/core/api/` and
  `tests/fixtures/sample_project/core/api/`.
- `doctrine/infrastructure/tests.md`, `doctrine/infrastructure/docex.md`,
  `skills/testing/SKILL.md` — doctrine amendments.
