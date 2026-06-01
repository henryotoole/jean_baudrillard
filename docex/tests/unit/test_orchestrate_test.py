"""Unit tests for ``docex test``."""

from __future__ import annotations

import pytest

from docex.orchestrate.test import run_test


def test_test_runs_migrate_then_test_then_teardown(sample_ctx, fake_docker):
    rc = run_test(sample_ctx, fake_docker)
    assert rc == 0

    methods = [c[0] for c in fake_docker.calls]
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
        ("exit", "compose_exec", "sample_test_api", ("./test.sh",))
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

    def _raising_exec(compose_file, service, command, *, env_file=None, project_dir=None):
        if command and command[0] == "./test.sh":
            raise RuntimeError(boom_token)
        return original_exec(
            compose_file, service, command,
            env_file=env_file, project_dir=project_dir,
        )

    fake_docker.compose_exec = _raising_exec  # type: ignore[method-assign]

    with pytest.raises(RuntimeError):
        run_test(sample_ctx, fake_docker)

    methods = [c[0] for c in fake_docker.calls]
    assert "compose_down" in methods, "teardown must run even on Python exception"


def test_test_short_circuits_on_migration_failure(sample_ctx, fake_docker):
    fake_docker.exit_codes[
        ("exit", "compose_exec", "sample_test_api", ("./migrate.sh",))
    ] = 4
    rc = run_test(sample_ctx, fake_docker)
    assert rc == 4

    # No test.sh should have been invoked since migration failed first.
    exec_cmds = [c[3] for c in fake_docker.calls if c[0] == "compose_exec"]
    assert ("./test.sh",) not in exec_cmds
    # Teardown still ran.
    methods = [c[0] for c in fake_docker.calls]
    assert "compose_down" in methods
