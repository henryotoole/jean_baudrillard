"""Unit tests for the docex CLI dispatcher.

Covers the three new command surface entries added in mod 034:

- ``preinfra <side>`` — stub returning 0 with a side-tagged notice.
- ``envinfra <direction> <env>`` — dispatches to existing ``run_up`` /
  ``run_down`` for dev/test only.
- ``projinfra <direction> <side>`` — stub for every case except
  elastic + up + production, which runs the existing ``run_bootstrap``.

Also asserts the help text reflects the purpose-based grouping (no
``Phase N`` labels) and that the handler table contains the new surface
without the dropped ``up`` / ``down`` / ``bootstrap`` commands.
"""

from __future__ import annotations

import pytest

from docex.__main__ import (
    _GROUPS,
    _HELP_TEXT,
    _build_handler_table,
    _cmd_envinfra,
    _cmd_preinfra,
    _cmd_projinfra,
    _format_usage,
)


# ---------------------------------------------------------------------------
# Handler table / help surface
# ---------------------------------------------------------------------------


def test_handler_table_has_new_surface_and_drops_old():
    table = _build_handler_table()
    # New commands present.
    for cmd in ("preinfra", "projinfra", "envinfra"):
        assert cmd in table
    # Old standalone commands removed.
    for cmd in ("up", "down", "bootstrap"):
        assert cmd not in table


def test_help_text_groups_by_purpose():
    usage = _format_usage()
    # Purpose-based group headings.
    for heading in ("Introspection:", "Infrastructure:",
                    "Development:", "Pipeline:"):
        assert heading in usage
    # No legacy phase headings remain.
    for stale in ("Phase 1", "Phase 2", "Phase 3", "Phase 4", "Phase 5",
                  "Reference:"):
        assert stale not in usage
    # New commands appear in the listing.
    for cmd in ("preinfra", "projinfra", "envinfra"):
        assert cmd in usage
    # Dropped commands do not.
    assert "  up " not in usage
    assert "  down " not in usage
    assert "  bootstrap " not in usage


def test_groups_data_matches_help_entries():
    # Every command in ``_GROUPS`` must have help text.
    for _title, cmds in _GROUPS:
        for cmd in cmds:
            assert cmd in _HELP_TEXT


# ---------------------------------------------------------------------------
# preinfra
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("side", ["development", "production"])
def test_preinfra_stub_returns_zero(capsys, side):
    rc = _cmd_preinfra([side])
    assert rc == 0
    out = capsys.readouterr().out
    assert "stub" in out
    assert side in out


def test_preinfra_rejects_unknown_side(capsys):
    with pytest.raises(SystemExit) as excinfo:
        _cmd_preinfra(["invalid"])
    # argparse exits with code 2 on argument errors.
    assert excinfo.value.code == 2


def test_preinfra_rejects_missing_argument():
    with pytest.raises(SystemExit) as excinfo:
        _cmd_preinfra([])
    assert excinfo.value.code == 2


# ---------------------------------------------------------------------------
# envinfra
# ---------------------------------------------------------------------------


def _patch_docker_ok(monkeypatch):
    """Patch ``_require_docker`` so envinfra doesn't actually hit dockerd."""
    sentinel = object()
    monkeypatch.setattr("docex.__main__._require_docker", lambda: sentinel)
    return sentinel


def test_envinfra_up_dispatches_to_run_up(monkeypatch, sample_ctx):
    docker_sentinel = _patch_docker_ok(monkeypatch)
    monkeypatch.chdir(sample_ctx.project_root)

    captured = {}

    def fake_run_up(ctx, docker, *, env):
        captured["ctx"] = ctx
        captured["docker"] = docker
        captured["env"] = env
        return 0

    monkeypatch.setattr("docex.orchestrate.up.run_up", fake_run_up)

    rc = _cmd_envinfra(["up", "dev"])
    assert rc == 0
    assert captured["env"] == "dev"
    assert captured["docker"] is docker_sentinel


def test_envinfra_down_dispatches_to_run_down(monkeypatch, sample_ctx):
    docker_sentinel = _patch_docker_ok(monkeypatch)
    monkeypatch.chdir(sample_ctx.project_root)

    captured = {}

    def fake_run_down(ctx, docker, *, env):
        captured["env"] = env
        captured["docker"] = docker
        return 0

    monkeypatch.setattr("docex.orchestrate.down.run_down", fake_run_down)

    rc = _cmd_envinfra(["down", "test"])
    assert rc == 0
    assert captured["env"] == "test"
    assert captured["docker"] is docker_sentinel


@pytest.mark.parametrize("env", ["stage", "prod"])
def test_envinfra_refuses_stage_and_prod(env):
    # argparse rejects stage/prod from the choices.
    with pytest.raises(SystemExit) as excinfo:
        _cmd_envinfra(["up", env])
    assert excinfo.value.code == 2


def test_envinfra_rejects_unknown_direction():
    with pytest.raises(SystemExit) as excinfo:
        _cmd_envinfra(["sideways", "dev"])
    assert excinfo.value.code == 2


# ---------------------------------------------------------------------------
# projinfra
# ---------------------------------------------------------------------------


def test_projinfra_elastic_up_production_runs_bootstrap(
    monkeypatch, capsys, elastic_ctx,
):
    monkeypatch.chdir(elastic_ctx.project_root)

    aws_sentinel = object()
    monkeypatch.setattr("docex.__main__._make_aws_client", lambda: aws_sentinel)

    captured = {}

    def fake_run_bootstrap(ctx, aws):
        captured["ctx"] = ctx
        captured["aws"] = aws
        return 0

    monkeypatch.setattr("docex.pipeline.bootstrap.run_bootstrap",
                        fake_run_bootstrap)

    rc = _cmd_projinfra(["up", "production"])
    assert rc == 0
    assert captured["aws"] is aws_sentinel
    # No "(stub)" notice on the real branch.
    assert "(stub)" not in capsys.readouterr().out


@pytest.mark.parametrize(
    "direction,side",
    [
        ("up", "development"),
        ("down", "development"),
        ("down", "production"),
    ],
)
def test_projinfra_elastic_other_invocations_are_stubs(
    monkeypatch, capsys, elastic_ctx, direction, side,
):
    monkeypatch.chdir(elastic_ctx.project_root)

    called = {"run_bootstrap": False}

    def fake_run_bootstrap(ctx, aws):
        called["run_bootstrap"] = True
        return 0

    monkeypatch.setattr("docex.pipeline.bootstrap.run_bootstrap",
                        fake_run_bootstrap)

    rc = _cmd_projinfra([direction, side])
    assert rc == 0
    assert called["run_bootstrap"] is False
    out = capsys.readouterr().out
    assert "(stub)" in out
    assert direction in out
    assert side in out


@pytest.mark.parametrize(
    "direction,side",
    [
        ("up", "development"),
        ("up", "production"),
        ("down", "development"),
        ("down", "production"),
    ],
)
def test_projinfra_fixed_all_invocations_dispatch_to_real_runners(
    monkeypatch, capsys, sample_ctx, direction, side,
):
    """Mod 036: every fixed-foundation projinfra invocation dispatches
    to the real ``run_projinfra_fixed_*`` runner — none is a stub, and
    ``run_bootstrap`` (elastic only) is never touched."""
    monkeypatch.chdir(sample_ctx.project_root)

    docker_sentinel = _patch_docker_ok(monkeypatch)

    called = {"run_bootstrap": False, "up": None, "down": None}

    def fake_run_bootstrap(ctx, aws):
        called["run_bootstrap"] = True
        return 0

    def fake_up(ctx, docker, *, side):
        called["up"] = (ctx, docker, side)
        return 0

    def fake_down(ctx, docker, *, side):
        called["down"] = (ctx, docker, side)
        return 0

    monkeypatch.setattr("docex.pipeline.bootstrap.run_bootstrap",
                        fake_run_bootstrap)
    monkeypatch.setattr(
        "docex.pipeline.projinfra.run_projinfra_fixed_up", fake_up,
    )
    monkeypatch.setattr(
        "docex.pipeline.projinfra.run_projinfra_fixed_down", fake_down,
    )

    rc = _cmd_projinfra([direction, side])
    assert rc == 0
    assert called["run_bootstrap"] is False
    out = capsys.readouterr().out
    assert "(stub)" not in out

    if direction == "up":
        assert called["up"] is not None
        assert called["down"] is None
        assert called["up"][1] is docker_sentinel
        assert called["up"][2] == side
    else:
        assert called["down"] is not None
        assert called["up"] is None
        assert called["down"][1] is docker_sentinel
        assert called["down"][2] == side


def test_projinfra_rejects_unknown_direction():
    with pytest.raises(SystemExit) as excinfo:
        _cmd_projinfra(["sideways", "development"])
    assert excinfo.value.code == 2


def test_projinfra_rejects_unknown_side():
    with pytest.raises(SystemExit) as excinfo:
        _cmd_projinfra(["up", "neither"])
    assert excinfo.value.code == 2
