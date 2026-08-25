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
    _cmd_job,
    _cmd_preinfra,
    _cmd_projinfra,
    _cmd_test,
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
    # Configuration group — both secrets (Mod 083) and config (Mod 084).
    for cmd in ("secrets", "config"):
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

    def fake_run_preinfra(ctx, docker, aws, *, side, ssh=None, dns=None,
                          registry=None):
        captured["ctx"] = ctx
        captured["docker"] = docker
        captured["aws"] = aws
        captured["side"] = side
        captured["registry"] = registry
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
    # Mod 133: the fixed development side needs a registry client for the
    # manifest-delete probe. Without this assertion a dropped call site
    # would only surface as a "dispatcher bug" failure at runtime.
    assert captured["registry"] is not None


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

    def fake_run_preinfra(ctx, docker, aws, *, side, ssh=None, dns=None,
                          registry=None):
        captured["aws"] = aws
        captured["registry"] = registry
        return 0

    monkeypatch.setattr(
        "docex.pipeline.preinfra.run_preinfra", fake_run_preinfra,
    )

    rc = _cmd_preinfra(["production"])
    assert rc == 0
    assert captured["aws"] is None
    assert aws_construct_calls["count"] == 0
    # Mod 133: the manifest-delete probe is development-side only, so the
    # production side builds no registry client.
    assert captured["registry"] is None


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

    def fake_run_preinfra(ctx, docker, aws, *, side, ssh=None, dns=None,
                          registry=None):
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

    def fake_run_preinfra(ctx, docker, aws, *, side, ssh=None, dns=None,
                          registry=None):
        captured["aws"] = aws
        captured["registry"] = registry
        return 0

    monkeypatch.setattr(
        "docex.pipeline.preinfra.run_preinfra", fake_run_preinfra,
    )

    rc = _cmd_preinfra(["development"])
    assert rc == 0
    assert captured["aws"] is None
    assert aws_construct_calls["count"] == 0
    # Mod 133: an ELASTIC project's development side has no registry
    # question to ask (ECR governs deletion via IAM), so `docex preinfra`
    # builds no client for it — and the probe's own gate would not fire.
    assert captured["registry"] is None


def test_preinfra_propagates_nonzero(monkeypatch, sample_ctx):
    """When ``run_preinfra`` returns non-zero, dispatcher propagates."""
    monkeypatch.chdir(sample_ctx.project_root)
    _patch_docker_ok(monkeypatch)
    monkeypatch.setattr(
        "docex.pipeline.preinfra.run_preinfra",
        lambda ctx, docker, aws, *, side, ssh=None, dns=None, registry=None: 1,
    )
    rc = _cmd_preinfra(["development"])
    assert rc == 1


def test_every_development_side_preinfra_call_site_supplies_a_registry(
    monkeypatch, sample_ctx,
):
    """Mod 133: all three dispatcher paths that can pass
    ``side="development"`` must supply a registry client.

    A forgotten call site is caught by ``run_preinfra``'s dispatcher-bug
    guard at runtime, but nothing would catch it in CI — so each site is
    asserted here. ``run_preinfra`` is stubbed to pass; this test is about
    the arguments, not the checks.
    """
    monkeypatch.chdir(sample_ctx.project_root)
    _patch_docker_ok(monkeypatch)

    seen: list[tuple[str, object]] = []

    def fake_run_preinfra(ctx, docker, aws, *, side, ssh=None, dns=None,
                          registry=None):
        seen.append((side, registry))
        return 0

    monkeypatch.setattr(
        "docex.pipeline.preinfra.run_preinfra", fake_run_preinfra,
    )
    monkeypatch.setattr(
        "docex.orchestrate.up.run_up", lambda ctx, docker, *, env: 0,
    )
    monkeypatch.setattr(
        "docex.pipeline.projinfra.run_projinfra_fixed_up",
        lambda ctx, docker, *, side: 0,
    )

    assert _cmd_preinfra(["development"]) == 0        # site 2
    assert _cmd_envinfra(["up", "dev"]) == 0          # site 1
    assert _cmd_projinfra(["up", "development"]) == 0  # site 3

    assert len(seen) == 3
    for side, registry in seen:
        assert side == "development"
        assert registry is not None


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
        lambda ctx, docker, aws, *, side, ssh=None, dns=None, registry=None: 0,
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
        lambda ctx, docker, aws, *, side, ssh=None, dns=None, registry=None: 1,
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

    def fake_preinfra(ctx, docker, aws, *, side, ssh=None, dns=None,
                      registry=None):
        called["preinfra"] = True
        return 1

    def fake_run_down(ctx, docker, *, env, **kwargs):
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

    def fake_run_down(ctx, docker, *, env, **kwargs):
        captured["env"] = env
        captured["docker"] = docker
        return 0

    monkeypatch.setattr("docex.orchestrate.down.run_down", fake_run_down)

    rc = _cmd_envinfra(["down", "test"])
    assert rc == 0
    assert captured["env"] == "test"
    assert captured["docker"] is docker_sentinel


@pytest.mark.parametrize("env", ["stage", "prod"])
def test_envinfra_down_allows_stage_and_prod(monkeypatch, elastic_ctx, env):
    """Mod 052 (Gap F): ``down`` now accepts stage/prod. The dispatcher
    threads aws + the tofu runners through to ``run_down``."""
    monkeypatch.chdir(elastic_ctx.project_root)
    _patch_docker_ok(monkeypatch)
    monkeypatch.setattr("docex.__main__._make_aws_client", lambda: object())

    captured = {}

    def fake_run_down(ctx, docker, *, env, aws=None, tofu_init=None,
                      tofu_destroy=None):
        captured["env"] = env
        captured["aws"] = aws
        captured["tofu_init"] = tofu_init
        captured["tofu_destroy"] = tofu_destroy
        return 0

    monkeypatch.setattr("docex.orchestrate.down.run_down", fake_run_down)

    rc = _cmd_envinfra(["down", env])
    assert rc == 0
    assert captured["env"] == env
    assert captured["aws"] is not None
    assert captured["tofu_init"] is not None
    assert captured["tofu_destroy"] is not None


@pytest.mark.parametrize("env", ["stage", "prod"])
def test_envinfra_up_refuses_stage_and_prod(monkeypatch, capsys, sample_ctx, env):
    """Mod 052 (Gap F): ``up`` stays dev/test-only — stage/prod up is
    `release`'s job. The rejection is a clean exit-1 with a clear message
    (not an argparse error, since `down` accepts stage/prod)."""
    monkeypatch.chdir(sample_ctx.project_root)
    rc = _cmd_envinfra(["up", env])
    assert rc == 1
    out = capsys.readouterr().out
    assert "docex release" in out
    assert env in out


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
        lambda ctx, docker, aws, *, side, ssh=None, dns=None, registry=None: 0,
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
        lambda ctx, docker, aws, *, side, ssh=None, dns=None, registry=None: 1,
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
    "direction,side",
    [
        # Mod 048: elastic's DEVELOPMENT side (up + down) is mechanically
        # identical to fixed dev-side projinfra (same emit shape per
        # `projinfra/projinfra.md § Why all three web networks live on
        # every side`). Both directions route to the fixed-style code
        # path now — no longer stubs.
        ("up", "development"),
        ("down", "development"),
    ],
)
def test_projinfra_elastic_dev_side_routes_fixed_style(
    monkeypatch, capsys, elastic_ctx, direction, side,
):
    """Mod 048: elastic dev-side projinfra dispatches to the fixed-style
    runner."""
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

    def fake_run_preinfra(ctx, docker, aws, *, side, ssh=None, dns=None,
                          registry=None):
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
    # Up runs preinfra gate then fixed-style up; down runs only fixed-style down.
    if direction == "up":
        assert called["run_preinfra"] is True
        assert called["run_projinfra_fixed_up"] is True
    else:
        assert called["run_projinfra_fixed_down"] is True


def test_projinfra_elastic_down_production_dispatches_to_elastic_down(
    monkeypatch, elastic_ctx,
):
    """Mod 052 (Gap F): elastic ``down production`` now dispatches to
    ``run_projinfra_elastic_down`` (replacing the manual teardown stub),
    threading the AWS client and tofu runners."""
    monkeypatch.chdir(elastic_ctx.project_root)
    aws_sentinel = object()
    monkeypatch.setattr("docex.__main__._make_aws_client", lambda: aws_sentinel)

    captured = {}

    def fake_elastic_down(ctx, aws, *, tofu_init, tofu_destroy):
        captured["aws"] = aws
        captured["tofu_init"] = tofu_init
        captured["tofu_destroy"] = tofu_destroy
        return 0

    monkeypatch.setattr(
        "docex.pipeline.projinfra.run_projinfra_elastic_down",
        fake_elastic_down,
    )

    rc = _cmd_projinfra(["down", "production"])
    assert rc == 0
    assert captured["aws"] is aws_sentinel
    assert captured["tofu_init"] is not None
    assert captured["tofu_destroy"] is not None


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
        lambda ctx, docker, aws, *, side, ssh=None, dns=None, registry=None: 0,
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
        lambda ctx, docker, aws, *, side, ssh=None, dns=None, registry=None: 1,
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


# ---------------------------------------------------------------------------
# Mod 148: `docex test --detach`, the `job` command, and the hidden
# `__run-job` in-vessel entrypoint.
# ---------------------------------------------------------------------------


def test_test_detach_flag_parses_and_routes(monkeypatch, sample_ctx):
    monkeypatch.chdir(sample_ctx.project_root)
    _patch_docker_ok(monkeypatch)

    captured = {}

    def fake_run_test_job(ctx, docker, *, detach, slots=1):
        captured["detach"] = detach
        captured["slots"] = slots
        return 0

    monkeypatch.setattr("docex.jobs.commands.run_test_job", fake_run_test_job)

    assert _cmd_test(["--detach"]) == 0
    assert captured["detach"] is True
    assert captured["slots"] == 1  # default omitted → byte-identical path
    assert _cmd_test([]) == 0
    assert captured["detach"] is False


def test_cli_test_unit_routes_synchronous(monkeypatch, sample_ctx):
    """Mod 151: `docex test unit [subset]` → synchronous run_test_unit."""
    monkeypatch.chdir(sample_ctx.project_root)
    _patch_docker_ok(monkeypatch)

    calls = {}
    monkeypatch.setattr(
        "docex.orchestrate.test.run_test_unit",
        lambda ctx, docker, *, selector: calls.update(unit=selector) or 0,
    )
    rc = _cmd_test(["unit", "tests/unit/foo.py"])
    assert rc == 0
    assert calls["unit"] == "tests/unit/foo.py"


def test_cli_test_unit_detach_is_usage_error(monkeypatch, sample_ctx):
    monkeypatch.chdir(sample_ctx.project_root)
    _patch_docker_ok(monkeypatch)
    rc = _cmd_test(["unit", "--detach"])
    assert rc == 64


def test_cli_test_integration_routes_to_job(monkeypatch, sample_ctx):
    monkeypatch.chdir(sample_ctx.project_root)
    _patch_docker_ok(monkeypatch)

    seen = {}
    monkeypatch.setattr(
        "docex.jobs.commands.run_test_job",
        lambda ctx, docker, *, detach, tiers=("unit", "integration"),
        selector=None, slots=1: seen.update(
            tiers=tiers, selector=selector, detach=detach, slots=slots
        ) or 0,
    )
    rc = _cmd_test(["integration", "tests/integration/foo.py"])
    assert rc == 0
    assert seen == {"tiers": ("integration",),
                    "selector": "tests/integration/foo.py", "detach": False,
                    "slots": 1}


def test_cli_test_slots_routes_to_job(monkeypatch, sample_ctx):
    """Mod 154: `--slots N` threads N into run_test_job; `test integration
    --slots N` threads it on the integration lane too."""
    monkeypatch.chdir(sample_ctx.project_root)
    _patch_docker_ok(monkeypatch)

    seen = {}
    monkeypatch.setattr(
        "docex.jobs.commands.run_test_job",
        lambda ctx, docker, *, detach, tiers=("unit", "integration"),
        selector=None, slots=1: seen.update(tiers=tiers, slots=slots) or 0,
    )
    assert _cmd_test(["--slots", "3"]) == 0
    assert seen == {"tiers": ("unit", "integration"), "slots": 3}

    seen.clear()
    assert _cmd_test(["integration", "--slots", "4"]) == 0
    assert seen == {"tiers": ("integration",), "slots": 4}


def test_cli_test_unit_slots_is_usage_error(monkeypatch, sample_ctx):
    monkeypatch.chdir(sample_ctx.project_root)
    _patch_docker_ok(monkeypatch)
    assert _cmd_test(["unit", "--slots", "2"]) == 64


def test_cli_test_slots_below_one_is_usage_error(monkeypatch, sample_ctx):
    monkeypatch.chdir(sample_ctx.project_root)
    _patch_docker_ok(monkeypatch)
    assert _cmd_test(["--slots", "0"]) == 64


def test_job_ls_routes(monkeypatch, sample_ctx):
    monkeypatch.chdir(sample_ctx.project_root)
    _patch_docker_ok(monkeypatch)

    called = {}

    def fake_ls(ctx, docker):
        called["ls"] = True
        return 0

    monkeypatch.setattr("docex.jobs.commands.run_job_ls", fake_ls)
    assert _cmd_job(["ls"]) == 0
    assert called.get("ls") is True


def test_job_status_routes_with_handle(monkeypatch, sample_ctx):
    monkeypatch.chdir(sample_ctx.project_root)
    _patch_docker_ok(monkeypatch)

    captured = {}

    def fake_status(ctx, docker, handle):
        captured["handle"] = handle
        return 0

    monkeypatch.setattr("docex.jobs.commands.run_job_status", fake_status)
    assert _cmd_job(["status", "abc123"]) == 0
    assert captured["handle"] == "abc123"


def test_job_wait_routes_with_timeout(monkeypatch, sample_ctx):
    monkeypatch.chdir(sample_ctx.project_root)
    _patch_docker_ok(monkeypatch)

    captured = {}

    def fake_wait(ctx, docker, handle, *, timeout):
        captured["handle"] = handle
        captured["timeout"] = timeout
        return 0

    monkeypatch.setattr("docex.jobs.commands.run_job_wait", fake_wait)
    assert _cmd_job(["wait", "abc", "--timeout", "2.5"]) == 0
    assert captured["handle"] == "abc"
    assert captured["timeout"] == 2.5


def test_job_logs_routes_with_follow(monkeypatch, sample_ctx):
    monkeypatch.chdir(sample_ctx.project_root)

    captured = {}

    def fake_logs(ctx, handle, *, follow):
        captured["handle"] = handle
        captured["follow"] = follow
        return 0

    monkeypatch.setattr("docex.jobs.commands.run_job_logs", fake_logs)
    assert _cmd_job(["logs", "abc", "-f"]) == 0
    assert captured["handle"] == "abc"
    assert captured["follow"] is True


def test_job_result_routes(monkeypatch, sample_ctx):
    monkeypatch.chdir(sample_ctx.project_root)

    captured = {}

    def fake_result(ctx, handle):
        captured["handle"] = handle
        return 0

    monkeypatch.setattr("docex.jobs.commands.run_job_result", fake_result)
    assert _cmd_job(["result", "abc"]) == 0
    assert captured["handle"] == "abc"


def test_job_requires_a_subcommand():
    with pytest.raises(SystemExit) as excinfo:
        _cmd_job([])
    assert excinfo.value.code == 2


def test_run_job_hidden_from_usage_but_reachable_in_table():
    table = _build_handler_table()
    # The hidden in-vessel entrypoint is reachable...
    assert "__run-job" in table
    # ...and the visible job command is present.
    assert "job" in table
    usage = _format_usage()
    # ...but __run-job never appears in help/usage.
    assert "__run-job" not in usage
    # The visible `job` command and its group heading do.
    assert "Jobs:" in usage
    assert "\n    job " in usage or "  job " in usage
