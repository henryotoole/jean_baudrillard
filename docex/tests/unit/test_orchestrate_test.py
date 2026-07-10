"""Unit tests for ``docex test``."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from docex.context import load_project_context
from docex.orchestrate.test import run_test


_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.fixture
def scheduler_ctx(tmp_path):
    """A fixed-foundation project fixture that includes a scheduler
    (``nightly_cleanup``, alongside web service ``api``; project ``sample``
    v0.1.0)."""
    fixture = (
        _REPO_ROOT / "tests" / "fixtures" / "sample_project_scheduler_fixed"
    )
    dest = tmp_path / "sched"
    shutil.copytree(fixture, dest, dirs_exist_ok=False)
    out = dest / "infra" / "output"
    if out.exists():
        shutil.rmtree(out)
    return load_project_context(dest)


def test_test_runs_migrate_then_test_then_teardown(sample_ctx, fake_docker):
    rc = run_test(sample_ctx, fake_docker)
    assert rc == 0

    # Filter out the metadata entries (``*_project_dir`` / ``*_project_name``)
    # the fake appends after each primary call so the ordering assertions
    # read against real docker operations.
    methods = [
        c[0] for c in fake_docker.calls
        if not c[0].endswith("_project_dir") and not c[0].endswith("_project_name")
    ]
    # compose_up, then exec migrate.sh, then exec test.sh, then compose_down.
    assert methods[0] == "compose_up"
    assert methods[-1] == "compose_down"

    # Validate the teardown was with preserve_volumes=False.
    down_calls = [c for c in fake_docker.calls if c[0] == "compose_down"]
    assert len(down_calls) == 1
    assert down_calls[0][2] is False, "test teardown must delete volumes"

    # Migrate and test scripts both invoked for api.
    exec_cmds = [c[3] for c in fake_docker.calls if c[0] == "compose_exec"]
    assert ("./migrate.sh",) in exec_cmds
    assert ("./test.sh",) in exec_cmds
    # Migrate must come before test.
    migrate_idx = exec_cmds.index(("./migrate.sh",))
    test_idx = exec_cmds.index(("./test.sh",))
    assert migrate_idx < test_idx


def test_test_teardown_still_runs_after_test_failure(sample_ctx, fake_docker):
    """The try/finally guarantee: teardown always happens, even on test failure."""
    fake_docker.exit_codes[
        ("exit", "compose_exec", "sample-test-api", ("./test.sh",))
    ] = 1
    rc = run_test(sample_ctx, fake_docker)
    assert rc == 1

    methods = [c[0] for c in fake_docker.calls]
    assert "compose_down" in methods, "teardown must run on test failure"

    # And teardown must still be preserve_volumes=False.
    down_calls = [c for c in fake_docker.calls if c[0] == "compose_down"]
    assert down_calls[-1][2] is False


def test_test_teardown_still_runs_on_python_exception(sample_ctx, fake_docker):
    """A Python exception inside the try block still triggers teardown."""

    # Patch compose_exec to raise on the test.sh call.
    original_exec = fake_docker.compose_exec
    boom_token = object()

    def _raising_exec(compose_file, service, command, *, env_file=None,
                      project_dir=None, project_name=None):
        if command and command[0] == "./test.sh":
            raise RuntimeError(boom_token)
        return original_exec(
            compose_file, service, command,
            env_file=env_file, project_dir=project_dir,
            project_name=project_name,
        )

    fake_docker.compose_exec = _raising_exec  # type: ignore[method-assign]

    with pytest.raises(RuntimeError):
        run_test(sample_ctx, fake_docker)

    methods = [c[0] for c in fake_docker.calls]
    assert "compose_down" in methods, "teardown must run even on Python exception"


def test_test_short_circuits_on_migration_failure(sample_ctx, fake_docker):
    fake_docker.exit_codes[
        ("exit", "compose_exec", "sample-test-api", ("./migrate.sh",))
    ] = 4
    rc = run_test(sample_ctx, fake_docker)
    assert rc == 4

    # No test.sh should have been invoked since migration failed first.
    exec_cmds = [c[3] for c in fake_docker.calls if c[0] == "compose_exec"]
    assert ("./test.sh",) not in exec_cmds
    # Teardown still ran.
    methods = [c[0] for c in fake_docker.calls]
    assert "compose_down" in methods


def test_run_test_scheduler_uses_one_off(scheduler_ctx, fake_docker):
    """Mod 088: a scheduler service's test.sh runs via a one-off container
    (``build_image(target="test")`` + ``run_one_shot(["./test.sh"])``),
    never via ``compose_exec`` (no exec-able scheduler container exists in
    the ``test`` stack). Non-scheduler services still use ``compose_exec``."""
    rc = run_test(scheduler_ctx, fake_docker)
    assert rc == 0

    svc_dir = str(scheduler_ctx.project_root / "core" / "nightly_cleanup")
    tag = "docex-test-sample-nightly_cleanup:latest"

    # The scheduler was built from the test stage and run as a one-off.
    assert ("build_image", svc_dir, "test", tag) in fake_docker.calls
    one_shots = [
        c for c in fake_docker.calls
        if c[0] == "run_one_shot" and c[1] == tag and c[2] == ("./test.sh",)
    ]
    assert len(one_shots) == 1

    # The scheduler never went through compose_exec (nor was it exec'd under
    # any bare/fallback key).
    exec_test_services = [
        c[2] for c in fake_docker.calls
        if c[0] == "compose_exec" and c[3] == ("./test.sh",)
    ]
    assert all("nightly_cleanup" not in s for s in exec_test_services)

    # The non-scheduler web service still runs test.sh via compose_exec.
    assert any(s.endswith("api") for s in exec_test_services)


def test_run_test_scheduler_build_failure_short_circuits(
    scheduler_ctx, fake_docker
):
    """A failed scheduler test-image build returns that exit code and skips
    the one-off run."""
    tag = "docex-test-sample-nightly_cleanup:latest"
    svc_dir = str(scheduler_ctx.project_root / "core" / "nightly_cleanup")
    fake_docker.exit_codes[("build_image", svc_dir, "test", tag)] = 9

    rc = run_test(scheduler_ctx, fake_docker)
    assert rc == 9

    # The build failed, so no one-off run.sh should have fired.
    one_shots = [
        c for c in fake_docker.calls
        if c[0] == "run_one_shot" and c[1] == tag
    ]
    assert one_shots == []
    # Teardown still ran (try/finally).
    assert "compose_down" in [c[0] for c in fake_docker.calls]


def test_run_test_scheduler_run_failure_returns_code(
    scheduler_ctx, fake_docker
):
    """A failed scheduler one-off ``test.sh`` run surfaces its exit code."""
    tag = "docex-test-sample-nightly_cleanup:latest"
    fake_docker.exit_codes[("run_one_shot", tag, ("./test.sh",))] = 3

    rc = run_test(scheduler_ctx, fake_docker)
    assert rc == 3
    assert "compose_down" in [c[0] for c in fake_docker.calls]
