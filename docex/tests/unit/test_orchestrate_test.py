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

    # Mod 099 test 12: both scripts route through the codebase's exec
    # service as one-off runs, never a `compose exec` into an app container.
    run_calls = [c for c in fake_docker.calls if c[0] == "compose_run_one_off"]
    assert [c[2] for c in run_calls] == [
        "sample-test-api-exec", "sample-test-api-exec",
    ]
    run_cmds = [c[3] for c in run_calls]
    assert ("./migrate.sh",) in run_cmds
    assert ("./test.sh",) in run_cmds
    # Migrate must come before test.
    assert run_cmds.index(("./migrate.sh",)) < run_cmds.index(("./test.sh",))
    assert [c for c in fake_docker.calls if c[0] == "compose_exec"] == []


def test_test_teardown_still_runs_after_test_failure(sample_ctx, fake_docker):
    """The try/finally guarantee: teardown always happens, even on test failure."""
    fake_docker.exit_codes[
        ("exit", "compose_run_one_off", "sample-test-api-exec", ("./test.sh",))
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

    # Patch the one-off runner to raise on the test.sh call.
    original_run = fake_docker.compose_run_one_off
    boom_token = object()

    # ``build`` (Mod 103) must be in this stand-in's signature: ``run_test``
    # passes it at every one-off call site, so omitting it turns the intended
    # RuntimeError into a TypeError from the fake itself.
    def _raising_run(compose_file, service, command, *, env=None,
                     build=False, env_file=None, project_dir=None,
                     project_name=None):
        if command and command[0] == "./test.sh":
            raise RuntimeError(boom_token)
        return original_run(
            compose_file, service, command, env=env, build=build,
            env_file=env_file, project_dir=project_dir,
            project_name=project_name,
        )

    fake_docker.compose_run_one_off = _raising_run  # type: ignore[method-assign]

    with pytest.raises(RuntimeError):
        run_test(sample_ctx, fake_docker)

    methods = [c[0] for c in fake_docker.calls]
    assert "compose_down" in methods, "teardown must run even on Python exception"


def test_test_short_circuits_on_migration_failure(sample_ctx, fake_docker):
    fake_docker.exit_codes[
        ("exit", "compose_run_one_off", "sample-test-api-exec", ("./migrate.sh",))
    ] = 4
    rc = run_test(sample_ctx, fake_docker)
    assert rc == 4

    # No test.sh should have been invoked since migration failed first.
    run_cmds = [c[3] for c in fake_docker.calls if c[0] == "compose_run_one_off"]
    assert ("./test.sh",) not in run_cmds
    # Teardown still ran.
    methods = [c[0] for c in fake_docker.calls]
    assert "compose_down" in methods


def test_run_test_scheduler_only_codebase_uses_its_exec_service(
    scheduler_ctx, fake_docker
):
    """Mod 103: EVERY codebase runs test.sh one way — ``compose run --rm``
    against its own exec service. A scheduler-only codebase included.

    Replaces ``test_run_test_scheduler_uses_one_off``, whose subject was
    ``orchestrate/test.py::_run_scheduler_tests`` — the mod-088 carve-out that
    built the codebase's Dockerfile ``test`` stage directly
    (``build_image(target="test")``) and ran ``test.sh`` through a bare
    ``run_one_shot``, entirely outside compose. It existed because a
    scheduler-only codebase had no exec-able container in the ``test`` stack
    (mod 073 drops the Ofelia trigger there). Mod 099's exec service is emitted
    for every codebase, so the carve-out had nothing left to solve and is
    deleted. Consequence worth naming: the job's tests now get the codebase's
    ``depends_on`` readiness gate and its networks, which the bare one-off had
    neither of. (``git log -S_run_scheduler_tests``.)
    """
    rc = run_test(scheduler_ctx, fake_docker)
    assert rc == 0

    test_services = [
        c[2] for c in fake_docker.calls
        if c[0] == "compose_run_one_off" and c[3] == ("./test.sh",)
    ]
    # `core_services` is sorted, so `api` precedes `nightly_cleanup`.
    assert test_services == [
        "sample-test-api-exec", "sample-test-nightly-cleanup-exec",
    ]

    # The deleted helper's two docker verbs are now unreachable from run_test:
    # no direct stage build, no bare `docker run`.
    assert [c for c in fake_docker.calls if c[0] == "build_image"] == []
    assert [c for c in fake_docker.calls if c[0] == "run_one_shot"] == []


def test_run_test_short_circuits_before_later_codebase(
    scheduler_ctx, fake_docker
):
    """Repurposed from ``test_run_test_scheduler_build_failure_short_circuits``,
    whose literal subject (a failed scheduler test-STAGE build) no longer
    exists. Its real subject — first-failure short-circuit semantics — does,
    so the coverage moves to the surviving path: a failing ``test.sh`` in the
    first codebase must stop the loop before the next codebase's exec service
    is ever run, and teardown must still happen.
    """
    fake_docker.exit_codes[
        ("exit", "compose_run_one_off", "sample-test-api-exec", ("./test.sh",))
    ] = 9

    rc = run_test(scheduler_ctx, fake_docker)
    assert rc == 9

    test_services = [
        c[2] for c in fake_docker.calls
        if c[0] == "compose_run_one_off" and c[3] == ("./test.sh",)
    ]
    assert test_services == ["sample-test-api-exec"]
    # Teardown still ran (try/finally).
    assert "compose_down" in [c[0] for c in fake_docker.calls]


def test_run_test_scheduler_run_failure_returns_code(
    scheduler_ctx, fake_docker
):
    """A failing ``test.sh`` in the scheduler-only codebase's exec service
    surfaces its exit code and still tears down. Same guarantee as before Mod
    103; the failure is keyed on the exec-service one-off rather than on the
    deleted helper's ``run_one_shot``."""
    fake_docker.exit_codes[
        (
            "exit", "compose_run_one_off",
            "sample-test-nightly-cleanup-exec", ("./test.sh",),
        )
    ] = 3

    rc = run_test(scheduler_ctx, fake_docker)
    assert rc == 3
    assert "compose_down" in [c[0] for c in fake_docker.calls]


def test_run_test_one_offs_build_first(sample_ctx, fake_docker):
    """Mod 103: every one-off ``run_test`` issues — migrate AND test — carries
    ``--build``.

    ``compose run`` builds only when the image is ABSENT; it reuses a stale one
    silently. In ``test`` the image *is* the artifact under test, and for a
    codebase with no non-gated compose service nothing else ever refreshes that
    tag, so without this a run after the first tests a stale image.
    """
    rc = run_test(sample_ctx, fake_docker)
    assert rc == 0

    primary = [
        (c[2], c[3]) for c in fake_docker.calls
        if c[0] == "compose_run_one_off"
    ]
    built = [
        (c[1], c[2]) for c in fake_docker.calls
        if c[0] == "compose_run_one_off_build"
    ]
    assert primary  # guard: an empty-vs-empty comparison would pass vacuously
    assert sorted(primary) == sorted(built)
    assert {cmd for _svc, cmd in built} == {("./migrate.sh",), ("./test.sh",)}
