# Mod 119 — Implementation

Repo root for every path below: `/home/ubuntu/.claude/jean_baudrillard/docex`.
Branch: `005_process_type_solidification`. Read `overview.md` in this folder
first — it carries the diagnosis these steps assume.

Five files change:

| File | Change |
| --- | --- |
| `src/docex/orchestrate/build.py` | the fix — clear `dist/` inside the container |
| `tests/unit/test_orchestrate_build.py` | 2 edited tests, 2 new |
| `tests/integration/test_build_real.py` | 1 new regression test |
| `tests/integration/conftest.py` | new reclamation fixture |
| `pyproject.toml` | `tmp_path_retention_policy = "failed"` |

**Do not touch** anything under `test_projects/`, `doctrine/`,
`doctrine_excerpts/`, `plans/core/`, or `PRE_CUT_CHECKLIST.md`. Core planning
docs are updated by the mod's documentation step, not by you.

---

## Step 1 — `src/docex/orchestrate/build.py`

### 1a. Module docstring

The docstring's numbered list (lines 8-15) states step 2 as "Clear
`$pr/core/<codebase>/dist/` on the host." Replace steps 2 and 3 with:

```
  2. Ensure ``$pr/core/<codebase>/dist/`` exists on the host.
  3. ``compose run --rm`` the codebase's exec service, which clears
     ``/service/dist`` and then runs ``./build.sh`` (Mod 099; Mod 119
     moved the clear inside the container).
  4. Assert ``dist/`` is non-empty afterward.
```

(renumbering the existing step 4 to 5).

### 1b. Drop the `shutil` import

`shutil` is used only at the line being deleted. Remove `import shutil`.

### 1c. Add the command constant

Below `_BUILD_ENV = "dev"`:

```py
# The dev-iteration clear + build, run as ONE command inside the codebase's
# exec service.
#
# WHY the clear is not host-side (Mod 119): `core/<codebase>/dist/` is a
# container-owned tree. Everything that writes into it writes as root through
# the bind mount — `up.py::_ensure_initial_dev_build`'s cp, `build.sh` under
# `compose run`, and the dev core service's `__pycache__` on import. The host
# owns the directory node (docex mkdir'd it) and nothing inside. Unlink
# permission comes from the *parent* directory, so the host uid can delete a
# root-owned `dist/app.py` but not anything inside a root-owned
# `dist/__pycache__/` — which is exactly what `shutil.rmtree` used to hit,
# with PermissionError. It was self-regenerating: `run_up` created the residue
# its own `run_build` then could not delete. The container is root and can,
# so the clear goes where the writer is. This also means a checkout that
# already has residue self-heals on the next build with no operator `sudo`.
#
# WHY one command rather than a separate clear container: `docex build` IS the
# hot iteration loop — the same reason this path deliberately does not pass
# `build=True` (see the note in `_build_one`). A second container start is pure
# added latency on the one command whose purpose is to be cheap.
#
# WHY `find -mindepth 1 -delete` rather than `rm -rf dist/*`: the bind-mount
# point itself cannot be removed, and glob-based deletion misses dotfiles
# without a cryptic `./.[!.]* ./..?*` incantation. It is also the idiom the
# doctrine's own sample `build.sh` uses, for this same reason.
#
# DEPENDENCY: the dev stage image must carry `sh` and `find`. `sh` was already
# required (`build.sh` is `#!/bin/sh` and is invoked as `./build.sh`); `find`
# is in both coreutils and busybox, so any base carrying a build toolchain has
# it. Deliberately NOT a doctrine rule: the doctrine's one image requirement
# (`curl`) is backed by a `docex check` gate, and an unenforced image
# requirement is a claim in the rule of record that nothing verifies. The
# failure mode here is loud anyway — `find: not found`, non-zero exit, build
# fails immediately.
_CLEAR_AND_BUILD = (
    "set -e; cd /service; mkdir -p dist; "
    "find dist -mindepth 1 -delete; exec ./build.sh"
)
```

### 1d. Replace the host-side clear

Delete the whole `# Step 2: clear host-side dist/.` block (the
`if dist_dir.exists(): ... else: ...` at lines ~124-135) and put in its place:

```py
    # Step 2: ensure the host-side dist/ directory node exists. Its
    # *contents* are cleared inside the container — see _CLEAR_AND_BUILD.
    dist_dir = ctx.project_root / "core" / codebase / "dist"
    dist_dir.mkdir(parents=True, exist_ok=True)
```

### 1e. Change the command passed to the container

```py
    rc = docker.compose_run_one_off(
        compose_file, service_key, ["sh", "-c", _CLEAR_AND_BUILD],
        env_file=env_file, project_dir=ctx.project_root,
        project_name=project_name,
    )
```

Update the failure message immediately below, since a non-zero exit can now
come from the clear as well as from `build.sh`:

```py
        print(
            f"error: clear+build for codebase {codebase!r} exited {rc} "
            "(ran in the codebase's exec service).",
            file=sys.stderr,
        )
```

Leave the `WHY no build=True here` comment block and step 4 exactly as they are.
Step 4 only calls `exists()` / `iterdir()` — reads, which the host may do.

---

## Step 2 — `tests/unit/test_orchestrate_build.py`

### 2a. A fake that behaves like the real container

Add near the top (needs `import shutil`):

```py
def _container_like_run(dist: Path, *, honor_clear: bool = True):
    """A ``compose_run_one_off`` stand-in that does what the command says.

    The real exec container is root and executes the command string it is
    handed — so this fake clears ``dist/`` **only if the command actually
    contains the clear**, and writes an artifact only if it invokes
    ``build.sh``.

    That derivation is the point. Mod 119 moved the clear from the host into
    the container, so ``docex`` no longer deletes anything itself. The lazy
    way to keep the old assertion green would be to make this fake clear
    unconditionally — which would pin nothing at all. Deriving the behavior
    from the command keeps the assertion load-bearing: drop the clear from
    ``build.py`` and the fake stops clearing, the stale file survives, and
    the test fails.
    """
    def _run(compose_file, service, command, *, env=None, build=False,
             env_file=None, project_dir=None, project_name=None):
        script = " ".join(command)
        if honor_clear and "find dist -mindepth 1 -delete" in script:
            for child in dist.iterdir():
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink()
        if "build.sh" in script:
            (dist / "fresh.py").write_text("print('hi')")
        return 0
    return _run
```

### 2b. Rewrite `test_build_clears_dist_before_running_build_sh`

Keep the test name, keep both assertions (`stale.txt` gone, `fresh.py`
present), keep the `seen == ["sample-dev-api-exec"]` check. Swap its inline
`_run_side_effect` for `_container_like_run`, capturing the service name:

```py
def test_build_clears_dist_before_running_build_sh(sample_ctx, fake_docker):
    """Mod 099 test 13, updated by Mod 119: ``build.sh`` runs in the
    codebase's exec service, and ``dist/`` is still cleared before it and
    asserted non-empty after — but the clear now happens *inside* that
    container, because the tree is root-owned and the host uid cannot
    unlink inside a root-owned subdirectory."""
    fake_docker.ps_services = ["sample-dev-api-web"]
    dist = _seed_dist(sample_ctx, "api", {"stale.txt": "old"})
    assert (dist / "stale.txt").is_file()

    seen: list[str] = []
    inner = _container_like_run(dist)

    def _run(compose_file, service, command, **kwargs):
        seen.append(service)
        return inner(compose_file, service, command, **kwargs)

    fake_docker.compose_run_one_off = _run  # type: ignore[method-assign]

    assert run_build(sample_ctx, fake_docker, codebase="api") == 0
    assert seen == ["sample-dev-api-exec"]
    assert not (dist / "stale.txt").exists()
    assert (dist / "fresh.py").is_file()
```

### 2c. Repoint `test_build_returns_failure_exit_code_from_build_sh`

Its `exit_codes` key is `("exit", "compose_run_one_off", "sample-dev-api-exec",
("./build.sh",))`, which no longer matches the command tuple. Import the
constant and rebuild the key:

```py
from docex.orchestrate.build import _CLEAR_AND_BUILD, run_build
...
    fake_docker.exit_codes[
        ("exit", "compose_run_one_off", "sample-dev-api-exec",
         ("sh", "-c", _CLEAR_AND_BUILD))
    ] = 3
```

Nothing else in that test changes; it must still assert `rc == 3`.

### 2d. NEW — pin the command shape

```py
def test_build_command_clears_dist_inside_the_container(sample_ctx, fake_docker):
    """Mod 119. The clear must be in the command handed to the exec
    service, and must precede ``build.sh``."""
    fake_docker.ps_services = ["sample-dev-api-web"]
    # Seeded so step 4's non-empty assertion passes without the fake
    # writing anything (the default fake records and returns 0).
    _seed_dist(sample_ctx, "api", {"stale.txt": "old"})

    assert run_build(sample_ctx, fake_docker, codebase="api") == 0

    runs = [c for c in fake_docker.calls if c[0] == "compose_run_one_off"]
    assert len(runs) == 1
    cmd = runs[0][3]
    assert cmd[0] == "sh" and cmd[1] == "-c"
    script = cmd[2]
    assert "find dist -mindepth 1 -delete" in script
    assert "./build.sh" in script
    assert script.index("-delete") < script.index("./build.sh")
```

### 2e. NEW — pin that docex does not mutate host `dist/`

```py
def test_build_does_not_delete_inside_host_dist(sample_ctx, fake_docker):
    """Mod 119. ``dist/`` is container-owned: everything in it is written as
    root through a bind mount, and a root-owned subdirectory's contents are
    unlinkable by the host uid. ``docex`` may create, list and stat that
    directory; it must never delete inside it from the host.

    Proof by absence: with a container that does nothing, a seeded file is
    still there after ``run_build``. If a host-side clear ever comes back,
    this fails."""
    fake_docker.ps_services = ["sample-dev-api-web"]
    dist = _seed_dist(sample_ctx, "api", {"stale.txt": "old"})

    assert run_build(sample_ctx, fake_docker, codebase="api") == 0
    assert (dist / "stale.txt").is_file()
```

---

## Step 3 — `tests/integration/test_build_real.py`

Add the regression test. It must **fail against pre-mod code** with the
production `PermissionError`; verify that by stashing the `build.py` change and
running it once (see Step 6).

```py
@pytest.mark.integration
def test_build_clears_root_owned_residue(fresh_project, docker_client):
    """Mod 119 regression. Pre-mod, ``run_build`` cleared ``dist/`` from the
    host with ``shutil.rmtree`` and died with ``PermissionError`` on the
    root-owned ``__pycache__`` the dev stack itself had just created.

    The residue is manufactured here with a throwaway root container rather
    than left to arise from the app's import behavior, so the test pins the
    bug deterministically. That is the same mechanism the bug has in the
    field — a container writing through a bind mount as root — and it needs
    no privileges on the host.

    Note the root-owned **directory**: a root-owned *file* directly in
    ``dist/`` is removable by the host uid, because unlink permission comes
    from the parent. The directory is what blocks it.
    """
    ctx = load_project_context(fresh_project)
    dist = fresh_project / "core" / "api" / "dist"
    try:
        assert run_up(ctx, docker_client, env="dev") == 0

        dist.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["docker", "run", "--rm", "-v", f"{dist}:/d", "alpine:latest",
             "sh", "-c",
             "mkdir -p /d/__pycache__ && touch /d/__pycache__/residue.pyc"],
            check=True,
        )
        residue = dist / "__pycache__" / "residue.pyc"
        assert residue.is_file()
        assert residue.stat().st_uid == 0, "residue must be root-owned to pin the bug"

        assert run_build(ctx, docker_client, codebase="api") == 0
        assert not (dist / "__pycache__").exists(), (
            "the in-container clear must remove root-owned directories"
        )
        assert any(dist.iterdir())

        # Second run, no cleanup in between: the self-regeneration path.
        # dist/ is now full of root-owned artifacts written by build.sh, and
        # the build must still be repeatably green against them. This is the
        # property that manual `sudo rm -rf` never bought — it fixed one run.
        assert run_build(ctx, docker_client, codebase="api") == 0
        assert any(dist.iterdir())
    finally:
        run_down(ctx, docker_client, env="dev")
        subprocess.run(
            ["docker", "compose", "-f", str(
                fresh_project / "infra" / "output" / "dev" / "docker-compose.yml"
            ), "--project-directory", str(fresh_project),
             "--env-file", str(fresh_project / "infra" / "secrets" / "dev.env"),
             "down", "-v"],
            check=False,
        )
```

**Do not** assert "no root-owned files remain under `dist/`". After a build the
artifact itself is root-owned — `build.sh` runs as root in the exec container,
by design. The invariant is narrower and is what the assertions above encode:
no root-owned *directory* survives the clear, and the build is repeatably green.

---

## Step 4 — `tests/integration/conftest.py`

Add `import os` to the imports, then add this fixture after
`_isolate_shared_stacks`:

```py
@pytest.fixture(autouse=True)
def _reclaim_root_owned_residue(tmp_path: Path):
    """Return ownership of the test's tmp tree to the host uid at teardown.

    WHY (Mod 119): every integration test leaves root-owned paths behind,
    because containers run as root against bind mounts —
    ``dist/__pycache__`` and ``dist/app.py`` from the dev stack,
    ``.pytest_cache`` and ``infra/stage/tests/__pycache__`` from the
    stagetest container. A root-owned *directory* makes its contents
    unlinkable by the host uid, so pytest's own tmp cleanup (it keeps the
    last 3 ``pytest-N`` roots and ``rm_rf``s the rest) raises
    PermissionError and abandons the whole root — pinning the gigabytes of
    OpenTofu AWS provider binaries the ``tofu validate`` tests download.
    Measured before this mod: 20 tiny root-owned paths holding 5.9 GB
    hostage. It surfaced as unrelated tests failing on
    ``no space left on device``.

    Two of those producers are outside ``dist/`` entirely, which is why the
    fix in ``orchestrate/build.py`` does not make this fixture redundant:
    nothing in ``build.py`` can reach ``.pytest_cache``. Do not delete this
    as duplicative of the product fix.

    ``chown``, not ``rm``: with ``tmp_path_retention_policy = "failed"`` the
    trees that survive are the failing ones, and those are exactly the ones
    someone wants to read.

    Depends on ``tmp_path`` so it finalizes *before* pytest's own
    ``tmp_path`` finalizer, which is what does the deleting.

    Best-effort: reclamation failing must never redden a green test.
    """
    yield
    if not _docker_available():
        return
    subprocess.run(
        ["docker", "run", "--rm", "-v", f"{tmp_path}:/work", "alpine:latest",
         "chown", "-R", f"{os.getuid()}:{os.getgid()}", "/work"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
    )
```

---

## Step 5 — `pyproject.toml`

In `[tool.pytest.ini_options]`, after `norecursedirs`:

```toml
# Mod 119: keep a test's tmp tree only when it fails. Integration tests
# download ~676 MB of OpenTofu AWS provider per copy and pytest retains the
# last 3 run roots, so "keep everything" is ~18 GB of steady state. The
# retention given up is for *passing* tests, which nobody inspects; a
# failing test keeps its whole tree (and `_reclaim_root_owned_residue`
# chowns it so it is readable). To get a green run's tree back for
# debugging: `pytest --tmp-path-retention-policy=all`.
tmp_path_retention_policy = "failed"
```

---

## Step 6 — Verification, in this order

1. **Prove the new integration test fails pre-fix.** With Step 1 reverted only
   (`git stash push src/docex/orchestrate/build.py` or equivalent), run
   `pytest -m integration tests/integration/test_build_real.py`. Expect
   `test_build_clears_root_owned_residue` to fail with `PermissionError`.
   Restore the fix. **Record the exact error text for the report.**
2. `pytest tests/unit` — expect green. Baseline was **986**; expect **988**
   (2 new). Report the actual number and explain any other delta.
3. `du -sh /tmp/pytest-of-ubuntu` — **record this number.**
4. `pytest -m integration` — expect **20 passed / 0 failed** (19 pre-existing,
   1 new). The brief's target of 19 predates the new test.
5. `du -sh /tmp/pytest-of-ubuntu` again — **record this number.** Also run
   `find /tmp/pytest-of-ubuntu -uid 0 | wc -l`; expect 0.
6. **Manual double-build against the fixture**, outside pytest, to show the
   self-regeneration path is closed end to end. Copy
   `tests/fixtures/sample_project` to a scratch dir, then via the docex CLI or
   a short python driver: `run_up(dev)` → `run_build` → `run_build`. After
   each build report `find <dist> -uid 0 -type d | wc -l` (expect 0) and
   confirm both builds returned 0. Tear the stack down afterwards.

Report all six results. The claim of this mod is a number going to roughly zero
and staying there, not a test turning green.

## Out of scope — do not do these

- `test_projects/PRE_CUT_CHECKLIST.md` D.6's `sudo find … -exec rm -rf`
  workaround is now obsolete, but that file belongs to Mod 117. Leave it.
- `plans/core/compiler.md` gets the `find` dependency note in this mod's
  documentation step. Not yours.
- A shared `TF_PLUGIN_CACHE_DIR` would cut the ~6 GB per integration run to
  ~700 MB. Logged forward; not this mod.
