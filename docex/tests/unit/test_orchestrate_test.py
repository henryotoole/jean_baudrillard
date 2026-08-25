"""Unit tests for ``docex test``."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from docex.context import load_project_context
from docex.orchestrate.test import run_test, run_test_unit


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
    # compose_up, then migrate.sh, then test_unit.sh, then
    # test_integration.sh, then compose_down.
    assert methods[0] == "compose_up"
    assert methods[-1] == "compose_down"

    # Validate the teardown was with preserve_volumes=False.
    down_calls = [c for c in fake_docker.calls if c[0] == "compose_down"]
    assert len(down_calls) == 1
    assert down_calls[0][2] is False, "test teardown must delete volumes"

    # Mod 099 test 12: every script routes through the codebase's exec
    # service as one-off runs, never a `compose exec` into an app container.
    run_calls = [c for c in fake_docker.calls if c[0] == "compose_run_one_off"]
    assert [c[2] for c in run_calls] == [
        "sample-test-api-exec", "sample-test-api-exec", "sample-test-api-exec",
    ]
    run_cmds = [c[3] for c in run_calls]
    assert ("./migrate.sh",) in run_cmds
    assert ("./test_unit.sh",) in run_cmds
    assert ("./test_integration.sh",) in run_cmds
    # Migrate before the unit tier before the integration tier (mod 147).
    assert (
        run_cmds.index(("./migrate.sh",))
        < run_cmds.index(("./test_unit.sh",))
        < run_cmds.index(("./test_integration.sh",))
    )
    assert [c for c in fake_docker.calls if c[0] == "compose_exec"] == []


def test_test_teardown_still_runs_after_test_failure(sample_ctx, fake_docker):
    """The try/finally guarantee: teardown always happens, even on test failure."""
    fake_docker.exit_codes[
        ("exit", "compose_run_one_off", "sample-test-api-exec",
         ("./test_integration.sh",))
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

    # Patch the one-off runner to raise on the test_integration.sh call.
    original_run = fake_docker.compose_run_one_off
    boom_token = object()

    # ``build`` (Mod 103) must be in this stand-in's signature: ``run_test``
    # passes it at every one-off call site, so omitting it turns the intended
    # RuntimeError into a TypeError from the fake itself.
    def _raising_run(compose_file, service, command, *, env=None,
                     build=False, no_deps=False, env_file=None, project_dir=None,
                     project_name=None):
        if command and command[0] == "./test_integration.sh":
            raise RuntimeError(boom_token)
        return original_run(
            compose_file, service, command, env=env, build=build, no_deps=no_deps,
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

    # Neither test shim should have been invoked since migration failed first.
    run_cmds = [c[3] for c in fake_docker.calls if c[0] == "compose_run_one_off"]
    assert ("./test_unit.sh",) not in run_cmds
    assert ("./test_integration.sh",) not in run_cmds
    # Teardown still ran.
    methods = [c[0] for c in fake_docker.calls]
    assert "compose_down" in methods


def test_run_test_every_codebase_uses_its_own_exec_service(
    multi_ctx, fake_docker
):
    """EVERY codebase runs each test shim exactly one way — ``compose run
    --rm`` against its OWN exec service — phased by tier: the whole unit
    phase (all codebases' ``test_unit.sh``) precedes the whole integration
    phase (all codebases' ``test_integration.sh``).
    """
    rc = run_test(multi_ctx, fake_docker)
    assert rc == 0

    run_calls = [c for c in fake_docker.calls if c[0] == "compose_run_one_off"]
    unit_services = [c[2] for c in run_calls if c[3] == ("./test_unit.sh",)]
    integ_services = [
        c[2] for c in run_calls if c[3] == ("./test_integration.sh",)
    ]
    # `codebases` is sorted, so `api` precedes `reporter` within each phase.
    assert unit_services == [
        "sample-test-api-exec", "sample-test-reporter-exec",
    ]
    assert integ_services == [
        "sample-test-api-exec", "sample-test-reporter-exec",
    ]

    # The whole unit phase precedes the whole integration phase (mod 147).
    cmds = [c[3] for c in run_calls]
    last_unit = max(
        i for i, cmd in enumerate(cmds) if cmd == ("./test_unit.sh",)
    )
    first_integ = min(
        i for i, cmd in enumerate(cmds) if cmd == ("./test_integration.sh",)
    )
    assert last_unit < first_integ

    # No other docker verb is reachable from `run_test`: no direct stage
    # build, no bare `docker run`.
    assert [c for c in fake_docker.calls if c[0] == "build_image"] == []
    assert [c for c in fake_docker.calls if c[0] == "run_one_shot"] == []


def test_run_test_short_circuits_before_later_codebase(
    multi_ctx, fake_docker
):
    """First-failure short-circuit: a failing ``test_unit.sh`` in the FIRST
    codebase stops the unit phase before the next codebase's exec service is
    ever run, and — because the cheap tier gates the expensive one — no
    ``test_integration.sh`` runs at all. Teardown still happens. Needs two
    codebases to state at all.
    """
    fake_docker.exit_codes[
        ("exit", "compose_run_one_off", "sample-test-api-exec",
         ("./test_unit.sh",))
    ] = 9

    rc = run_test(multi_ctx, fake_docker)
    assert rc == 9

    run_calls = [c for c in fake_docker.calls if c[0] == "compose_run_one_off"]
    unit_services = [c[2] for c in run_calls if c[3] == ("./test_unit.sh",)]
    assert unit_services == ["sample-test-api-exec"]
    # Fail-fast in the unit phase: the integration phase never started.
    integ_calls = [c for c in run_calls if c[3] == ("./test_integration.sh",)]
    assert integ_calls == []
    # Teardown still ran (try/finally).
    assert "compose_down" in [c[0] for c in fake_docker.calls]


def test_run_test_second_codebase_failure_returns_its_code(
    multi_ctx, fake_docker
):
    """A failing ``test_unit.sh`` in the SECOND codebase's exec service
    surfaces its exit code and still tears down — the loop's exit code is the
    failing codebase's, not the last one's."""
    fake_docker.exit_codes[
        (
            "exit", "compose_run_one_off",
            "sample-test-reporter-exec", ("./test_unit.sh",),
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
    assert {cmd for _svc, cmd in built} == {
        ("./migrate.sh",), ("./test_unit.sh",), ("./test_integration.sh",),
    }


# ---------------------------------------------------------------------------
# Mod 151: the no-stack unit fast lane + the stack-backed integration lane.
# ---------------------------------------------------------------------------


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
