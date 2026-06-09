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


def test_preinfra_dev_dispatches_to_run_preinfra_without_aws(
    monkeypatch, sample_ctx,
):
    """Mod 042: development-side preinfra threads ``aws=None`` and never
    constructs a Boto3AWSClient — fixed-only operators don't need AWS
    creds to check development side."""
    monkeypatch.chdir(sample_ctx.project_root)
    docker_sentinel = _patch_docker_ok(monkeypatch)

    aws_construct_calls = {"count": 0}

    def fake_make_aws():
        aws_construct_calls["count"] += 1
        return object()

    monkeypatch.setattr("docex.__main__._make_aws_client", fake_make_aws)

    captured = {}

    def fake_run_preinfra(ctx, docker, aws, *, side):
        captured["ctx"] = ctx
        captured["docker"] = docker
        captured["aws"] = aws
        captured["side"] = side
        return 0

    monkeypatch.setattr(
        "docex.pipeline.preinfra.run_preinfra", fake_run_preinfra,
    )

    rc = _cmd_preinfra(["development"])
    assert rc == 0
    assert captured["side"] == "development"
    assert captured["docker"] is docker_sentinel
    assert captured["aws"] is None
    assert aws_construct_calls["count"] == 0


def test_preinfra_fixed_prod_dispatches_without_aws(
    monkeypatch, sample_ctx,
):
    """Fixed-foundation production side: still no AWS client built."""
    monkeypatch.chdir(sample_ctx.project_root)
    _patch_docker_ok(monkeypatch)

    aws_construct_calls = {"count": 0}

    def fake_make_aws():
        aws_construct_calls["count"] += 1
        return object()

    monkeypatch.setattr("docex.__main__._make_aws_client", fake_make_aws)

    captured = {}

    def fake_run_preinfra(ctx, docker, aws, *, side):
        captured["aws"] = aws
        return 0

    monkeypatch.setattr(
        "docex.pipeline.preinfra.run_preinfra", fake_run_preinfra,
    )

    rc = _cmd_preinfra(["production"])
    assert rc == 0
    assert captured["aws"] is None
    assert aws_construct_calls["count"] == 0


def test_preinfra_elastic_prod_dispatches_with_aws(
    monkeypatch, elastic_ctx,
):
    """Elastic-foundation production side: lazy AWS client constructed
    and threaded to ``run_preinfra``."""
    monkeypatch.chdir(elastic_ctx.project_root)
    _patch_docker_ok(monkeypatch)

    aws_sentinel = object()
    monkeypatch.setattr(
        "docex.__main__._make_aws_client", lambda: aws_sentinel,
    )

    captured = {}

    def fake_run_preinfra(ctx, docker, aws, *, side):
        captured["aws"] = aws
        captured["side"] = side
        return 0

    monkeypatch.setattr(
        "docex.pipeline.preinfra.run_preinfra", fake_run_preinfra,
    )

    rc = _cmd_preinfra(["production"])
    assert rc == 0
    assert captured["aws"] is aws_sentinel
    assert captured["side"] == "production"


def test_preinfra_elastic_dev_dispatches_without_aws(
    monkeypatch, elastic_ctx,
):
    """Even elastic projects don't need AWS for the development side."""
    monkeypatch.chdir(elastic_ctx.project_root)
    _patch_docker_ok(monkeypatch)

    aws_construct_calls = {"count": 0}

    def fake_make_aws():
        aws_construct_calls["count"] += 1
        return object()

    monkeypatch.setattr("docex.__main__._make_aws_client", fake_make_aws)

    captured = {}

    def fake_run_preinfra(ctx, docker, aws, *, side):
        captured["aws"] = aws
        return 0

    monkeypatch.setattr(
        "docex.pipeline.preinfra.run_preinfra", fake_run_preinfra,
    )

    rc = _cmd_preinfra(["development"])
    assert rc == 0
    assert captured["aws"] is None
    assert aws_construct_calls["count"] == 0


def test_preinfra_propagates_nonzero(monkeypatch, sample_ctx):
    """When ``run_preinfra`` returns non-zero, dispatcher propagates."""
    monkeypatch.chdir(sample_ctx.project_root)
    _patch_docker_ok(monkeypatch)
    monkeypatch.setattr(
        "docex.pipeline.preinfra.run_preinfra",
        lambda ctx, docker, aws, *, side: 1,
    )
    rc = _cmd_preinfra(["development"])
    assert rc == 1


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
    # Mod 042: preinfra gate fires before ``run_up``. Stub it to pass
    # so this test stays focused on the ``run_up`` dispatch.
    monkeypatch.setattr(
        "docex.pipeline.preinfra.run_preinfra",
        lambda ctx, docker, aws, *, side: 0,
    )

    rc = _cmd_envinfra(["up", "dev"])
    assert rc == 0
    assert captured["env"] == "dev"
    assert captured["docker"] is docker_sentinel


def test_envinfra_up_refuses_when_preinfra_fails(
    monkeypatch, capsys, sample_ctx,
):
    """Mod 042: failing preinfra short-circuits envinfra up before
    ``run_up`` ever runs."""
    monkeypatch.chdir(sample_ctx.project_root)
    _patch_docker_ok(monkeypatch)

    called = {"run_up": False}

    def fake_run_up(ctx, docker, *, env):
        called["run_up"] = True
        return 0

    monkeypatch.setattr("docex.orchestrate.up.run_up", fake_run_up)
    monkeypatch.setattr(
        "docex.pipeline.preinfra.run_preinfra",
        lambda ctx, docker, aws, *, side: 1,
    )

    rc = _cmd_envinfra(["up", "dev"])
    assert rc == 1
    assert called["run_up"] is False
    out = capsys.readouterr().out
    assert "preinfra" in out and "aborting envinfra up" in out


def test_envinfra_down_not_gated_by_preinfra(
    monkeypatch, sample_ctx,
):
    """Mod 042: teardown is not gated. ``envinfra down`` proceeds even
    when ``run_preinfra`` would fail."""
    monkeypatch.chdir(sample_ctx.project_root)
    _patch_docker_ok(monkeypatch)

    called = {"preinfra": False, "run_down": False}

    def fake_preinfra(ctx, docker, aws, *, side):
        called["preinfra"] = True
        return 1

    def fake_run_down(ctx, docker, *, env):
        called["run_down"] = True
        return 0

    monkeypatch.setattr(
        "docex.pipeline.preinfra.run_preinfra", fake_preinfra,
    )
    monkeypatch.setattr("docex.orchestrate.down.run_down", fake_run_down)

    rc = _cmd_envinfra(["down", "dev"])
    assert rc == 0
    assert called["preinfra"] is False
    assert called["run_down"] is True


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
    _patch_docker_ok(monkeypatch)

    aws_sentinel = object()
    monkeypatch.setattr("docex.__main__._make_aws_client", lambda: aws_sentinel)

    # Mod 042: preinfra gate fires before bootstrap. Stub it to pass so
    # this test stays focused on the bootstrap dispatch.
    monkeypatch.setattr(
        "docex.pipeline.preinfra.run_preinfra",
        lambda ctx, docker, aws, *, side: 0,
    )

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


def test_projinfra_elastic_up_production_refuses_when_preinfra_fails(
    monkeypatch, capsys, elastic_ctx,
):
    """Mod 042: failing preinfra short-circuits projinfra up before
    ``run_bootstrap`` ever runs."""
    monkeypatch.chdir(elastic_ctx.project_root)
    _patch_docker_ok(monkeypatch)
    monkeypatch.setattr(
        "docex.__main__._make_aws_client", lambda: object(),
    )
    monkeypatch.setattr(
        "docex.pipeline.preinfra.run_preinfra",
        lambda ctx, docker, aws, *, side: 1,
    )

    called = {"bootstrap": False}

    def fake_run_bootstrap(ctx, aws):
        called["bootstrap"] = True
        return 0

    monkeypatch.setattr("docex.pipeline.bootstrap.run_bootstrap",
                        fake_run_bootstrap)

    rc = _cmd_projinfra(["up", "production"])
    assert rc == 1
    assert called["bootstrap"] is False
    out = capsys.readouterr().out
    assert "preinfra" in out and "aborting projinfra up" in out


@pytest.mark.parametrize(
    "direction,side,routes_to_fixed",
    [
        # Mod 048: elastic's DEVELOPMENT side (up + down) is mechanically
        # identical to fixed dev-side projinfra (same emit shape per
        # `projinfra/overview.md § Why all four web networks live on
        # every side`). Both directions route to the fixed-style code
        # path now — no longer stubs.
        ("up", "development", True),
        ("down", "development", True),
        # `down production` on elastic remains operator-driven (run
        # teardown.sh) — dispatcher prints a "no automated path yet"
        # message and exits 0.
        ("down", "production", False),
    ],
)
def test_projinfra_elastic_dev_side_routes_fixed_style(
    monkeypatch, capsys, elastic_ctx, direction, side, routes_to_fixed,
):
    """Mod 048: elastic dev-side projinfra now dispatches to the
    fixed-style runner. Production-side down still informs and exits."""
    monkeypatch.chdir(elastic_ctx.project_root)

    called = {
        "run_bootstrap": False,
        "run_projinfra_fixed_up": False,
        "run_projinfra_fixed_down": False,
        "run_preinfra": False,
    }

    def fake_run_bootstrap(ctx, aws):
        called["run_bootstrap"] = True
        return 0

    def fake_run_projinfra_fixed_up(ctx, docker, *, side):
        called["run_projinfra_fixed_up"] = True
        return 0

    def fake_run_projinfra_fixed_down(ctx, docker, *, side):
        called["run_projinfra_fixed_down"] = True
        return 0

    def fake_run_preinfra(ctx, docker, aws, *, side):
        called["run_preinfra"] = True
        return 0

    monkeypatch.setattr("docex.pipeline.bootstrap.run_bootstrap",
                        fake_run_bootstrap)
    monkeypatch.setattr(
        "docex.pipeline.projinfra.run_projinfra_fixed_up",
        fake_run_projinfra_fixed_up,
    )
    monkeypatch.setattr(
        "docex.pipeline.projinfra.run_projinfra_fixed_down",
        fake_run_projinfra_fixed_down,
    )
    monkeypatch.setattr("docex.pipeline.preinfra.run_preinfra",
                        fake_run_preinfra)

    rc = _cmd_projinfra([direction, side])
    assert rc == 0
    assert called["run_bootstrap"] is False
    if routes_to_fixed:
        # Up runs preinfra gate then fixed-style up; down runs only fixed-style down.
        if direction == "up":
            assert called["run_preinfra"] is True
            assert called["run_projinfra_fixed_up"] is True
        else:
            assert called["run_projinfra_fixed_down"] is True
    else:
        # Elastic + down + production: fall-through message.
        out = capsys.readouterr().out
        assert "no automated path yet" in out
        assert direction in out and side in out


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
    # Mod 042: preinfra gate runs before the ``up`` runner on both
    # sides. Stub it to pass so this test stays focused on dispatch.
    monkeypatch.setattr(
        "docex.pipeline.preinfra.run_preinfra",
        lambda ctx, docker, aws, *, side: 0,
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


def test_projinfra_fixed_up_refuses_when_preinfra_fails(
    monkeypatch, capsys, sample_ctx,
):
    """Mod 042: failing preinfra short-circuits fixed projinfra up
    before the runner ever runs."""
    monkeypatch.chdir(sample_ctx.project_root)
    _patch_docker_ok(monkeypatch)

    called = {"up": False}

    def fake_up(ctx, docker, *, side):
        called["up"] = True
        return 0

    monkeypatch.setattr(
        "docex.pipeline.projinfra.run_projinfra_fixed_up", fake_up,
    )
    monkeypatch.setattr(
        "docex.pipeline.preinfra.run_preinfra",
        lambda ctx, docker, aws, *, side: 1,
    )

    rc = _cmd_projinfra(["up", "development"])
    assert rc == 1
    assert called["up"] is False
    out = capsys.readouterr().out
    assert "preinfra" in out and "aborting projinfra up" in out


def test_projinfra_rejects_unknown_direction():
    with pytest.raises(SystemExit) as excinfo:
        _cmd_projinfra(["sideways", "development"])
    assert excinfo.value.code == 2


def test_projinfra_rejects_unknown_side():
    with pytest.raises(SystemExit) as excinfo:
        _cmd_projinfra(["up", "neither"])
    assert excinfo.value.code == 2
