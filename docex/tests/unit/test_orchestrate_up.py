"""Unit tests for ``docex up``."""

from __future__ import annotations

import pytest

from docex.errors import EnvNotSupported
from docex.orchestrate.up import run_up


def test_up_rejects_stage(sample_ctx, fake_docker):
    with pytest.raises(EnvNotSupported):
        run_up(sample_ctx, fake_docker, env="stage")


def test_up_rejects_prod(sample_ctx, fake_docker):
    with pytest.raises(EnvNotSupported):
        run_up(sample_ctx, fake_docker, env="prod")


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
    # name (sample_dev_api), not the simple name (api).
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
        ("exit", "compose_exec", "sample_dev_api", ("./migrate.sh",))
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
