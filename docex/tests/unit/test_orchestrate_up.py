"""Unit tests for ``docex up``."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from docex.context import load_project_context
from docex.errors import EnvNotSupported
from docex.orchestrate.up import run_up


_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.fixture
def scheduler_ctx(tmp_path):
    """A fixed-foundation project fixture that includes a scheduler
    (``nightly_cleanup``, project ``sample`` v0.1.0)."""
    fixture = (
        _REPO_ROOT / "tests" / "fixtures" / "sample_project_scheduler_fixed"
    )
    dest = tmp_path / "sched"
    shutil.copytree(fixture, dest, dirs_exist_ok=False)
    out = dest / "infra" / "output"
    if out.exists():
        shutil.rmtree(out)
    return load_project_context(dest)


def test_up_dev_builds_scheduler_only_codebase_image_from_dev_stage(
    scheduler_ctx, fake_docker
):
    """Mod 103: ``up dev`` builds a scheduler-only codebase's image from the
    Dockerfile ``dev`` stage, tagged the dev-local codebase ref.

    Replaces ``test_up_dev_builds_scheduler_image_from_prod_stage``, which
    pinned mod 074's ``prod``-stage build of the same tag. docex still has to
    build this tag itself — a scheduler-only codebase has no non-gated compose
    service, so nothing in the compose graph builds it — but the STAGE changed,
    because the tag is codebase-keyed (Mod 096) and Mod 099's exec service
    builds it at ``target: dev``.
    """
    rc = run_up(scheduler_ctx, fake_docker, env="dev")
    assert rc == 0
    assert (
        "build_image",
        str(scheduler_ctx.project_root / "core" / "nightly_cleanup"),
        "dev",
        "sample/nightly_cleanup:0.1.0",
    ) in fake_docker.calls


def test_up_dev_builds_no_prod_stage_image(scheduler_ctx, fake_docker):
    """The mod-074 deletion pin, worth its own name: a ``prod``-stage image
    sitting on the dev codebase tag is precisely the state that broke
    ``docex build dev``.

    ``compose run`` builds only when the image is absent, so the exec service —
    which ``build`` / ``test`` / ``migrate`` all run inside — reused mod 074's
    ``prod``-stage image, and the doctrinal ``prod`` stage carries neither
    ``build.sh`` nor ``test.sh``. Nothing in ``up dev`` may build a ``prod``
    stage.
    """
    rc = run_up(scheduler_ctx, fake_docker, env="dev")
    assert rc == 0
    prod_builds = [
        c for c in fake_docker.calls
        if c[0] == "build_image" and c[2] == "prod"
    ]
    assert prod_builds == []


def test_up_dev_does_not_rebuild_a_long_running_codebases_image(
    scheduler_ctx, fake_docker
):
    """Mod 103 scoped the build loop from ``scheduler_services`` to
    ``scheduler_only_services``. ``api`` declares a ``web`` core service, so
    ``compose up --build`` builds its tag at the same ``dev`` target — docex
    building it again would be a redundant cache-hit build.

    Asserted on ``target == "dev"`` only: ``api`` still gets its
    ``target="build"`` call from ``_ensure_initial_dev_build``.
    """
    rc = run_up(scheduler_ctx, fake_docker, env="dev")
    assert rc == 0
    dev_builds = [
        c for c in fake_docker.calls
        if c[0] == "build_image" and c[2] == "dev"
    ]
    assert [c for c in dev_builds if c[1].endswith("/core/api")] == []
    # Guard: the loop did run — the scheduler-only codebase is still built.
    assert [c for c in dev_builds if c[1].endswith("/core/nightly_cleanup")]


def test_up_test_migrate_builds_but_up_dev_does_not(sample_ctx, fake_docker):
    """Mod 103: ``up``'s post-up migrate one-off carries ``--build`` in ``test``
    and NOT in ``dev``.

    The dev half is as load-bearing as the test half. In ``test`` the image *is*
    the artifact under test and ``compose run`` silently reuses a stale one; in
    ``dev`` the source arrives by bind mount and the ``dev`` stage exists so
    ``build.sh`` can be re-invoked without an image rebuild, so ``--build``
    there would slow the hot loop for nothing.
    """
    rc = run_up(sample_ctx, fake_docker, env="test")
    assert rc == 0
    assert [
        c for c in fake_docker.calls if c[0] == "compose_run_one_off_build"
    ] == [("compose_run_one_off_build", "sample-test-api-exec", ("./migrate.sh",))]

    fake_docker.calls.clear()
    rc = run_up(sample_ctx, fake_docker, env="dev")
    assert rc == 0
    # Guard: the migrate one-off DID happen; it just didn't ask for a build.
    assert [
        c for c in fake_docker.calls
        if c[0] == "compose_run_one_off" and c[3] == ("./migrate.sh",)
    ]
    assert [
        c for c in fake_docker.calls if c[0] == "compose_run_one_off_build"
    ] == []


def test_up_dev_passes_abs_secrets_env_file(scheduler_ctx, fake_docker):
    """Mod 075/080: ``up`` passes DOCEX_SECRETS_ENV_FILE (absolute path) to
    compose_up so Compose can interpolate it into the scheduler's ofelia INI
    mount source. Mod 080: the path is now the derived aggregate
    (``.docex/agg/<env>.env`` = TTE ∪ secrets ∪ config), not the raw secrets
    file — the scheduler job needs the minted TTE credentials too."""
    run_up(scheduler_ctx, fake_docker, env="dev")
    abs_env = str(scheduler_ctx.project_root / ".docex" / "agg" / "dev.env")
    extra_env_calls = [
        c for c in fake_docker.calls if c[0] == "compose_up_extra_env"
    ]
    assert extra_env_calls == [
        ("compose_up_extra_env", (("DOCEX_SECRETS_ENV_FILE", abs_env),))
    ]


def test_up_dev_skips_initial_build_for_scheduler(scheduler_ctx, fake_docker):
    """The scheduler is skipped in the bind-mount initial-dev-build path —
    no ``target=build`` image is built for it."""
    run_up(scheduler_ctx, fake_docker, env="dev")
    build_stage_for_sched = [
        c for c in fake_docker.calls
        if c[0] == "build_image"
        and c[2] == "build"
        and c[1].endswith("nightly_cleanup")
    ]
    assert build_stage_for_sched == []


def test_up_rejects_stage(sample_ctx, fake_docker):
    with pytest.raises(EnvNotSupported):
        run_up(sample_ctx, fake_docker, env="stage")


def test_up_rejects_prod(sample_ctx, fake_docker):
    with pytest.raises(EnvNotSupported):
        run_up(sample_ctx, fake_docker, env="prod")


def test_up_passes_env_tier_project_name(sample_ctx, fake_docker):
    """Mod 053: ``up`` passes the explicit env-tier compose project name
    (``<dns_label>-<env>``) to compose_up so the stack is named
    deterministically and matches what ``any_env_compose_up`` looks for."""
    rc = run_up(sample_ctx, fake_docker, env="dev")
    assert rc == 0
    name_calls = [
        c for c in fake_docker.calls if c[0] == "compose_up_project_name"
    ]
    assert name_calls == [("compose_up_project_name", "sample-dev")]


def test_up_calls_compose_up_then_migrate(sample_ctx, fake_docker):
    """Mod 099 test 14: the post-up migrate is a one-off run against the
    codebase's exec service, after ``compose up``."""
    rc = run_up(sample_ctx, fake_docker, env="dev")
    assert rc == 0

    methods = [c[0] for c in fake_docker.calls]
    # The order matters: compose_up must happen before the migration.
    assert "compose_up" in methods
    assert "compose_run_one_off" in methods
    assert methods.index("compose_up") < methods.index("compose_run_one_off")

    # migrate.sh for the api codebase (it owns the appdb schema), in the
    # per-codebase exec service — not a core service's app container.
    migrate_calls = [
        c for c in fake_docker.calls
        if c[0] == "compose_run_one_off" and "migrate.sh" in " ".join(c[3])
    ]
    assert len(migrate_calls) == 1
    assert migrate_calls[0][2] == "sample-dev-api-exec"
    assert [c for c in fake_docker.calls if c[0] == "compose_exec"] == []


def test_up_short_circuits_on_migration_failure(sample_ctx, fake_docker):
    # Script the api migrate.sh one-off run to fail.
    fake_docker.exit_codes[
        ("exit", "compose_run_one_off", "sample-dev-api-exec", ("./migrate.sh",))
    ] = 17

    rc = run_up(sample_ctx, fake_docker, env="dev")
    assert rc == 17

    # The failed migration exec must have been called, and no others
    # should have been called after it (no compose_down — up doesn't
    # auto-tear-down on failure).
    methods = [c[0] for c in fake_docker.calls]
    assert "compose_down" not in methods


def test_up_short_circuits_on_compose_up_failure(sample_ctx, fake_docker):
    fake_docker.exit_codes[("exit", "compose_up")] = 5
    rc = run_up(sample_ctx, fake_docker, env="dev")
    assert rc == 5
    # No migration should have been attempted.
    migrate_calls = [
        c for c in fake_docker.calls
        if c[0] == "compose_run_one_off" and "migrate.sh" in " ".join(c[3])
    ]
    assert migrate_calls == []


# --- Gap K: partial-bring-up diagnostics ----------------------------


def test_up_diagnoses_unhealthy_core_service(sample_ctx, fake_docker, capsys):
    """When compose up fails and a core service is unhealthy, emit a
    per-service diagnostic naming the healthcheck cause.

    Mod 099: the line is keyed on the **compose key**, which is the name the
    operator hands to ``docker logs``, rather than the codebase key."""
    fake_docker.exit_codes[("exit", "compose_up")] = 5
    fake_docker.ps_status = {"sample-dev-api-web": "unhealthy"}

    rc = run_up(sample_ctx, fake_docker, env="dev")
    assert rc == 5

    err = capsys.readouterr().err
    assert "envinfra up: service 'sample-dev-api-web'" in err
    assert "healthcheck" in err
    # No teardown — diagnosis only.
    assert "compose_down" not in [c[0] for c in fake_docker.calls]


def test_up_diagnoses_restarting_core_service(sample_ctx, fake_docker, capsys):
    """A restart-looping core service gets the restart-loop diagnostic."""
    fake_docker.exit_codes[("exit", "compose_up")] = 5
    fake_docker.ps_status = {"sample-dev-api-web": "restarting"}

    rc = run_up(sample_ctx, fake_docker, env="dev")
    assert rc == 5

    err = capsys.readouterr().err
    assert "envinfra up: service 'sample-dev-api-web'" in err
    assert "restart-looping" in err


def test_up_diagnoses_unhealthy_backing_service(sample_ctx, fake_docker, capsys):
    """Mod 099 test 14b — the case the old form could not report at all.

    ``_diagnose_unhealthy`` used to iterate *core codebases* and derive a
    compose key for each, so a sick backing service — an unhealthy postgres
    being the single likeliest reason ``up`` fails — never appeared in the
    output of the function whose entire job is diagnosing ``up`` failures.
    It now reports whatever the status map contains.
    """
    fake_docker.exit_codes[("exit", "compose_up")] = 5
    fake_docker.ps_status = {
        "sample-dev-api-web": "running",
        "sample-dev-appdb": "unhealthy",
    }

    rc = run_up(sample_ctx, fake_docker, env="dev")
    assert rc == 5

    err = capsys.readouterr().err
    assert "envinfra up: service 'sample-dev-appdb'" in err
    assert "healthcheck" in err
    # The healthy core service is not reported.
    assert "sample-dev-api-web" not in err


def test_up_diagnoses_on_migration_failure(sample_ctx, fake_docker, capsys):
    """A migration failure also triggers the scan — a half-up stack is
    the likely culprit."""
    fake_docker.exit_codes[
        ("exit", "compose_run_one_off", "sample-dev-api-exec", ("./migrate.sh",))
    ] = 17
    fake_docker.ps_status = {"sample-dev-api-web": "exited"}

    rc = run_up(sample_ctx, fake_docker, env="dev")
    assert rc == 17

    err = capsys.readouterr().err
    assert "envinfra up: service 'sample-dev-api-web'" in err
    assert "exited" in err


def test_up_no_diagnostic_when_all_running(sample_ctx, fake_docker, capsys):
    """Happy path: every service running → no diagnostic lines."""
    fake_docker.ps_status = {"sample-dev-api-web": "running"}
    rc = run_up(sample_ctx, fake_docker, env="dev")
    assert rc == 0
    err = capsys.readouterr().err
    assert "envinfra up: service" not in err
