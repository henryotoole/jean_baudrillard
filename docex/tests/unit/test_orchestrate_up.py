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


def test_up_dev_builds_scheduler_image_from_prod_stage(
    scheduler_ctx, fake_docker
):
    """Mod 074: ``up dev`` builds each scheduler's self-contained job
    image from the Dockerfile ``prod`` stage, tagged the dev-local ref
    (byte-identical to Ofelia's INI ``image =``)."""
    rc = run_up(scheduler_ctx, fake_docker, env="dev")
    assert rc == 0
    prod_builds = [
        c for c in fake_docker.calls
        if c[0] == "build_image" and c[2] == "prod"
    ]
    assert ("build_image", str(
        scheduler_ctx.project_root / "core" / "nightly_cleanup"
    ), "prod", "sample/nightly_cleanup:0.1.0") in prod_builds


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
    rc = run_up(sample_ctx, fake_docker, env="dev")
    assert rc == 0

    methods = [c[0] for c in fake_docker.calls]
    # The order matters: compose_up must happen before the migration exec.
    assert "compose_up" in methods
    assert "compose_exec" in methods
    assert methods.index("compose_up") < methods.index("compose_exec")

    # Migration exec is the migrate.sh for the api service (it owns the
    # appdb schema). The compose key is the project-scoped global
    # name (sample-dev-api), not the simple name (api).
    migrate_calls = [
        c for c in fake_docker.calls
        if c[0] == "compose_exec" and "migrate.sh" in " ".join(c[3])
    ]
    assert len(migrate_calls) == 1
    assert migrate_calls[0][2].endswith("api")


def test_up_short_circuits_on_migration_failure(sample_ctx, fake_docker):
    # Script the api migrate.sh exec to fail. The compose service key
    # is the project-scoped global name, not the simple name.
    fake_docker.exit_codes[
        ("exit", "compose_exec", "sample-dev-api", ("./migrate.sh",))
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
        if c[0] == "compose_exec" and "migrate.sh" in " ".join(c[3])
    ]
    assert migrate_calls == []


# --- Gap K: partial-bring-up diagnostics ----------------------------


def test_up_diagnoses_unhealthy_core_service(sample_ctx, fake_docker, capsys):
    """When compose up fails and a core service is unhealthy, emit a
    per-service diagnostic naming the healthcheck cause."""
    fake_docker.exit_codes[("exit", "compose_up")] = 5
    fake_docker.ps_status = {"sample-dev-api": "unhealthy"}

    rc = run_up(sample_ctx, fake_docker, env="dev")
    assert rc == 5

    err = capsys.readouterr().err
    assert "envinfra up: service 'api'" in err
    assert "healthcheck" in err
    # No teardown — diagnosis only.
    assert "compose_down" not in [c[0] for c in fake_docker.calls]


def test_up_diagnoses_restarting_core_service(sample_ctx, fake_docker, capsys):
    """A restart-looping core service gets the restart-loop diagnostic."""
    fake_docker.exit_codes[("exit", "compose_up")] = 5
    fake_docker.ps_status = {"sample-dev-api": "restarting"}

    rc = run_up(sample_ctx, fake_docker, env="dev")
    assert rc == 5

    err = capsys.readouterr().err
    assert "envinfra up: service 'api'" in err
    assert "restart-looping" in err


def test_up_diagnoses_on_migration_failure(sample_ctx, fake_docker, capsys):
    """A migration failure also triggers the scan — a half-up stack is
    the likely culprit."""
    fake_docker.exit_codes[
        ("exit", "compose_exec", "sample-dev-api", ("./migrate.sh",))
    ] = 17
    fake_docker.ps_status = {"sample-dev-api": "exited"}

    rc = run_up(sample_ctx, fake_docker, env="dev")
    assert rc == 17

    err = capsys.readouterr().err
    assert "envinfra up: service 'api'" in err
    assert "exited" in err


def test_up_no_diagnostic_when_all_running(sample_ctx, fake_docker, capsys):
    """Happy path: every service running → no diagnostic lines."""
    fake_docker.ps_status = {"sample-dev-api": "running"}
    rc = run_up(sample_ctx, fake_docker, env="dev")
    assert rc == 0
    err = capsys.readouterr().err
    assert "envinfra up: service" not in err
