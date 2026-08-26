"""Unit tests for ``docex test``."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from docex.context import load_project_context
from docex.orchestrate.test import run_test


_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.fixture
def multi_ctx(tmp_path):
    """A fixed-foundation TWO-CODEBASE project (``api`` + ``reporter``;
    project ``sample`` v0.1.0). The suite's only multi-codebase fixture —
    see its `infra.yml` header."""
    fixture = (
        _REPO_ROOT / "tests" / "fixtures" / "sample_project_multi_fixed"
    )
    dest = tmp_path / "multi"
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


def test_run_test_every_codebase_uses_its_own_exec_service(
    multi_ctx, fake_docker
):
    """EVERY codebase runs ``test.sh`` exactly one way — ``compose run --rm``
    against its OWN exec service — so the fan-out is one one-off per codebase
    and nothing else.
    """
    rc = run_test(multi_ctx, fake_docker)
    assert rc == 0

    test_services = [
        c[2] for c in fake_docker.calls
        if c[0] == "compose_run_one_off" and c[3] == ("./test.sh",)
    ]
    # `codebases` is sorted, so `api` precedes `reporter`.
    assert test_services == [
        "sample-test-api-exec", "sample-test-reporter-exec",
    ]

    # No other docker verb is reachable from `run_test`: no direct stage
    # build, no bare `docker run`.
    assert [c for c in fake_docker.calls if c[0] == "build_image"] == []
    assert [c for c in fake_docker.calls if c[0] == "run_one_shot"] == []


def test_run_test_short_circuits_before_later_codebase(
    multi_ctx, fake_docker
):
    """First-failure short-circuit: a failing ``test.sh`` in the FIRST
    codebase stops the loop before the next codebase's exec service is ever
    run, and teardown still happens. Needs two codebases to state at all.
    """
    fake_docker.exit_codes[
        ("exit", "compose_run_one_off", "sample-test-api-exec", ("./test.sh",))
    ] = 9

    rc = run_test(multi_ctx, fake_docker)
    assert rc == 9

    test_services = [
        c[2] for c in fake_docker.calls
        if c[0] == "compose_run_one_off" and c[3] == ("./test.sh",)
    ]
    assert test_services == ["sample-test-api-exec"]
    # Teardown still ran (try/finally).
    assert "compose_down" in [c[0] for c in fake_docker.calls]


def test_run_test_second_codebase_failure_returns_its_code(
    multi_ctx, fake_docker
):
    """A failing ``test.sh`` in the SECOND codebase's exec service surfaces
    its exit code and still tears down — the loop's exit code is the failing
    codebase's, not the last one's."""
    fake_docker.exit_codes[
        (
            "exit", "compose_run_one_off",
            "sample-test-reporter-exec", ("./test.sh",),
        )
    ] = 3

    rc = run_test(multi_ctx, fake_docker)
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


# ---------------------------------------------------------------------------
# Mod 151 (kept): the optional within-suite selector, forwarded to the shim
# as DOCEX_TEST_SELECTOR. Whole-suite runs inject nothing.
# ---------------------------------------------------------------------------


def test_run_injects_selector(sample_ctx, fake_docker):
    rc = run_test(sample_ctx, fake_docker, selector="tests/foo.py -k bar")
    assert rc == 0
    env_calls = [c for c in fake_docker.calls
                 if c[0] == "compose_run_one_off_env"]
    assert env_calls, "selector must be injected as env"
    # side-call shape: (tag, svc, cmd_tuple, sorted_env_items)
    assert (("DOCEX_TEST_SELECTOR", "tests/foo.py -k bar"),) in [
        c[3] for c in env_calls
    ]
    # Injected on the test.sh call, not migrate.
    sel_cmds = {c[2] for c in env_calls}
    assert ("./test.sh",) in sel_cmds
    assert ("./migrate.sh",) not in sel_cmds


def test_full_run_no_selector(sample_ctx, fake_docker):
    """Default run: one test.sh per codebase, no DOCEX_TEST_SELECTOR injected."""
    rc = run_test(sample_ctx, fake_docker)
    assert rc == 0
    run_cmds = [c[3] for c in fake_docker.calls if c[0] == "compose_run_one_off"]
    assert ("./test.sh",) in run_cmds
    assert [c for c in fake_docker.calls
            if c[0] == "compose_run_one_off_env"] == []
