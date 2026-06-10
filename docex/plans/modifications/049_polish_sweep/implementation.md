# Mod 049 — Implementation Steps

Fresh-context implementation guide for the three polish items in [`overview.md`](./overview.md). Read the overview first for the *why*; this file is the *how*. Patch cut **1.0.3 → 1.0.4**. No doctrine or transfer-table changes.

**Do not** update core planning docs from these steps (that's the design agent's later pass). **Do** update `CHANGELOG.md` + version files (step 4). No core-service contracts change in this mod.

Client interfaces follow a consistent three-place pattern — add any new method to all three:
1. The Protocol in `src/docex/{git,docker}/client.py`.
2. The concrete impl in `src/docex/{git,docker}/subprocess_client.py`.
3. The test fake(s) in `tests/conftest.py`.

---

## Step 1 — Gap C: no-`origin` path in `docex merge`

### 1a. Add `GitClient.remote_exists`

- **Protocol** (`src/docex/git/client.py`): add
  ```python
  def remote_exists(self, cwd: Path, remote: str = "origin") -> bool:
      """True iff the named git remote is configured."""
      ...
  ```
- **Concrete** (`src/docex/git/subprocess_client.py`): implement by running `git remote get-url <remote>` and returning `True` iff exit code 0 (mirror the existing exit-code-boolean helpers like `ref_exists`). Suppress stderr.
- **Fake** (`tests/conftest.py`): the fake `GitClient` gains a `remote_exists` returning a configurable flag (default `True`, so existing tests are unaffected). Add a constructor kwarg / attribute (e.g. `has_origin: bool = True`).

### 1b. Branch `run_merge` on remote presence

In `src/docex/pipeline/merge.py::run_merge`, restructure step 3 (currently the unconditional `git.fetch` at line ~59):

```python
has_origin = git.remote_exists(project_root, "origin")

if has_origin:
    rc = git.fetch(project_root, remote="origin")
    if rc != 0:
        print(f"error: 'git fetch origin' exited {rc}.", file=sys.stderr)
        return rc
    trunk_ref = "origin/main"
else:
    print(
        "merge: no 'origin' remote — performing local merge only "
        "(no fetch/push).",
        file=sys.stderr,
    )
    trunk_ref = "main"
```

Then generalize the existing seed-vs-rebase decision. Currently it keys off `empty_origin = not git.ref_exists(project_root, "origin/main")`. Replace with a check against the resolved `trunk_ref`:

```python
trunk_missing = not git.ref_exists(project_root, trunk_ref)
if trunk_missing:
    # seed: ff a fresh main to the feature tip (existing empty-origin logic)
    ...
else:
    rc = git.rebase(project_root, trunk_ref)   # was hardcoded "origin/main"
    ...
    rc = git.fast_forward(project_root, "main", feature)
    ...
```

- The no-remote + local-`main`-exists case (the test-project case) lands in the `else` branch: rebase onto local `main`, ff, tag. ✔ matches the walker's manual `merge --ff-only`.
- The no-remote + no-`main` case lands in the seed branch. ✔
- Rename the `empty_origin` local to `trunk_missing` throughout (it now covers both the empty-`origin/main` and no-`main` cases). The remote-delete guard at step 7 (line ~144) should skip when **either** `not has_origin` **or** `trunk_missing` — i.e. guard on `has_origin and not trunk_missing` is wrong; use: only attempt the remote branch delete `if has_origin and not trunk_missing`. Keep the local branch delete unconditional.

### 1c. Guard the push (step 6)

Wrap the `git.push` at line ~122 in `if has_origin:`. When no origin, skip silently (the one-line note at 1b already told the operator). The success message at the end is unchanged.

### 1d. Tests

`tests/` — add a test module (or extend the merge test module) that exercises `run_merge` with a fake `GitClient` whose `has_origin=False`:
- Asserts `fetch` and `push` are **not** called.
- Asserts `rebase` is called with `"main"` (not `"origin/main"`) when local main exists.
- Asserts `tag` is still called.
- Asserts the local branch delete runs and the remote branch delete does **not**.

A real-git integration test (tmp `git init` repo, a feature branch, no remote) is appropriate here since the git boundary is real — mark it `@pytest.mark.integration` consistent with existing integration tests.

---

## Step 2 — Gap J: dns-label display strings

### 2a. Promote `_dns_label` to a shared helper

`_dns_label` currently lives module-private in `src/docex/cicl/compile.py:330`. Promote it so non-compile code can use it without reaching into a private compile symbol:

- Add to `src/docex/naming.py`:
  ```python
  def dns_label(name: str) -> str:
      """A name as a DNS label (underscores → hyphens, lowercased)."""
      return name.replace("_", "-").lower()
  ```
- In `compile.py`, replace the local `_dns_label` body with a re-export/delegate (`from docex.naming import dns_label as _dns_label`) so there's a single source of truth. Leave all existing `_dns_label(...)` call sites in compile.py as-is.

### 2b. Fix `bootstrap.py` display strings

In `src/docex/pipeline/bootstrap.py::_print_delegation_instructions` (line ~178):

```python
from docex.naming import dns_label
...
project_subdomain = f"{dns_label(project)}.{apex_domain}"
```

so line ~181 prints the hyphenated zone name matching the actual emitted resource.

**Leave correct uses alone.** `bootstrap.py:165` (`project {project!r} fully bootstrapped`) refers to the project's machine name and stays raw. Do not touch SSM/IAM/DDB display strings (those resources legitimately keep underscores).

### 2c. Sweep for other leaks

`grep -rn "ctx.project.name\|\bproject\b" src/docex/__main__.py src/docex/pipeline/` and inspect each display/log statement: if it names a **DNS / docker / ECS / ECR** resource and interpolates the raw (underscored) project name, route it through `dns_label(...)`. If it names the project itself or an underscore-policy resource (IAM/SSM/DDB), leave it. List every site changed in the mod's eventual CHANGELOG line.

### 2d. Tests

`tests/` — unit test asserting `_print_delegation_instructions` (or a thin extracted helper that builds `project_subdomain`) produces `docex-smoke-elastic.luxrnd.tech` for project name `docex_smoke_elastic` + apex `luxrnd.tech`. If the string is currently only produced inside a print, extract the subdomain construction into a tiny testable helper or capture stdout via `capsys`.

---

## Step 3 — Gap K: partial-bring-up diagnostic in `docex envinfra up dev`

### 3a. Add a container-state query to `DockerClient`

`compose_ps` returns only running service *names* — insufficient for diagnosis. Add:

- **Protocol** (`src/docex/docker/client.py`):
  ```python
  def compose_ps_status(
      self,
      compose_file: Path,
      *,
      env_file: Path | None = None,
      project_dir: Path | None = None,
  ) -> dict[str, str]:
      """Map each service to a coarse state: one of
      'running' | 'restarting' | 'unhealthy' | 'exited' | 'created'.
      Empty dict means nothing is up."""
      ...
  ```
- **Concrete** (`src/docex/docker/subprocess_client.py`): implement via `docker compose ps --format json`. Each line/record carries `Service`, `State`, and `Health`. Map: `Health == "unhealthy"` → `"unhealthy"`; else use `State` (`running`/`restarting`/`exited`/`created`). Handle both the JSON-lines and JSON-array shapes compose v2 emits across versions.
- **Fake** (`tests/conftest.py`): the fake `DockerClient` gains `compose_ps_status` returning a configurable dict (default empty / all-running so existing tests are unaffected).

### 3b. Emit per-service diagnostics in `run_up`

In `src/docex/orchestrate/up.py::run_up`, after the `compose_up` call (line ~103) — both on its failure path and before the migrations loop — query `compose_ps_status` for the env and inspect each **core** service (`core_services(ctx)`, using the compose service key from `compose_service_key`). For any service not `running`, print one diagnostic line:

```python
DIAGNOSTICS = {
    "restarting": "container is restart-looping — check `docker logs {name}`; "
                  "common causes: missing env var, crash on startup.",
    "unhealthy":  "healthcheck never passed — verify the healthcheck "
                  "endpoint/tooling is present in the image.",
    "exited":     "container exited — check `docker logs {name}`.",
}
```

Print to stderr, one line per unhealthy/restarting/exited core service, prefixed `envinfra up: service <name>: <diagnostic>`. **Diagnosis only — no auto-fix, no teardown** (preserve `up.py`'s existing "half-up stack is what the developer needs" contract). The function's return code is unchanged (still the first non-zero from compose/migrate, or 0).

Placement detail: run the diagnostic scan whenever `compose_up` returns non-zero **and** also after a migration `compose_exec` fails — both are points where a partial/unhealthy stack is the likely culprit. Factor the scan into a small local helper `_diagnose_unhealthy(ctx, docker, env, compose_file, env_file)` called from both spots.

### 3c. Tests

`tests/` — unit test on `run_up` with a fake `DockerClient` where `compose_up` succeeds but `compose_ps_status` reports a core service `"unhealthy"` (and another `"restarting"`); assert the matching diagnostic lines are emitted (capture via `capsys`). A second test: all services `running` → no diagnostic lines.

---

## Step 4 — Version bump + changelog

- `pyproject.toml`: `version = "1.0.4"`.
- `src/docex/__init__.py`: `__version__ = "1.0.4"`.
- `CHANGELOG.md`: move `[Unreleased]` → `[1.0.4]` (dated), with entries summarizing Gaps C, J, K. List the concrete display-string sites changed in 2c. Keep the `[Unreleased]` skeleton above.

(The CHANGELOG/version step is part of implementation here, not a separate cut step — the actual image rebuild + tag happens in the cut, after the design agent's review and core-doc update.)

---

## Step 5 — Run the test suite

From `docex/`:

```bash
pytest -q                      # unit suite must pass
pytest -q -m integration       # integration suite (Gap C real-git test) must pass
```

All green is the exit condition for the implementation. Do **not** cut the version (no `docker build`, no git tag) — that's the design agent's post-review step per `docex_process.md § Cutting a version`.

---

## Files expected to change

| File | Why |
| ---- | --- |
| `src/docex/git/client.py` | `remote_exists` Protocol method |
| `src/docex/git/subprocess_client.py` | `remote_exists` impl |
| `src/docex/pipeline/merge.py` | no-remote branch (1b/1c) |
| `src/docex/naming.py` | public `dns_label` helper |
| `src/docex/cicl/compile.py` | delegate `_dns_label` to `naming.dns_label` |
| `src/docex/pipeline/bootstrap.py` | hyphenated subdomain display |
| `src/docex/__main__.py` (+ other pipeline files if the 2c sweep finds leaks) | display-string fixes |
| `src/docex/docker/client.py` | `compose_ps_status` Protocol method |
| `src/docex/docker/subprocess_client.py` | `compose_ps_status` impl |
| `src/docex/orchestrate/up.py` | partial-bring-up diagnostic |
| `tests/conftest.py` | fake-client new methods |
| `tests/**` | new tests for C, J, K |
| `pyproject.toml`, `src/docex/__init__.py`, `CHANGELOG.md` | version bump + changelog |
