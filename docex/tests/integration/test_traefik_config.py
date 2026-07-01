"""Mod 064: traefik dynamic-config render + release-side SSM push.

Covers ``docex.emit.traefik.render_traefik_dynamic_config`` (the YAML shape)
and the ``_release_elastic`` push step that pushes it to SSM for ec2_traefik
projects (and skips it for alb projects).

The elastic fixture (``sample_project_elastic``) has core web service ``api``
(port 8080), project ``sample``, apex ``example.com``,
``domain_default_service: api``.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from docex.cicl.compile import compile_env
from docex.cicl.transfer import load_transfer_tables
from docex.context import load_project_context
from docex.emit.traefik import render_traefik_dynamic_config
from docex.pipeline.release import run_release


_FIXTURE_ELASTIC = (
    Path(__file__).resolve().parent.parent
    / "fixtures"
    / "sample_project_elastic"
)


def _compile_envs(root: Path):
    ctx = load_project_context(root)
    tables = load_transfer_tables(root)
    return [
        compile_env(
            ctx.infra, tables, env=e,
            project_name=ctx.project.name,
            project_version=ctx.project.version,
        )
        for e in ("stage", "prod")
    ]


# ---------------------------------------------------------------------------
# 1. Render shape.
# ---------------------------------------------------------------------------


def test_render_traefik_dynamic_config_shape(tmp_path: Path):
    stage, prod = _compile_envs(_FIXTURE_ELASTIC)
    out = render_traefik_dynamic_config([stage, prod])

    doc = yaml.safe_load(out)
    assert "http" in doc
    routers = doc["http"]["routers"]
    services = doc["http"]["services"]

    # A router+service per core web service per env, keyed <svc>-<env>.
    assert set(routers) == {"api-stage", "api-prod"}
    assert set(services) == {"api-stage", "api-prod"}

    # Non-web / backing services (appdb) never route.
    for key in routers:
        assert not key.startswith("appdb")
        assert not key.startswith("worker")

    # Every router pins the doctrine cert resolver.
    for r in routers.values():
        assert r["tls"]["certResolver"] == "doctrine"
        assert r["service"] in services

    # prod carries the bare-project host (domain_default_service alternate);
    # stage carries the canonical per-env host.
    assert "Host(`sample.example.com`)" in routers["api-prod"]["rule"]
    assert (
        "Host(`api.stage.sample.example.com`)"
        in routers["api-stage"]["rule"]
    )

    # Backend URL == Service Connect FQDN on the container port.
    assert services["api-stage"]["loadBalancer"]["servers"] == [
        {"url": "http://sample-stage-api.sample-stage:8080"}
    ]


def test_render_traefik_dynamic_config_empty_when_no_web(tmp_path: Path):
    # An env list with no core web services yields the projinfra stub.
    class _NoSvcEnv:
        env = "stage"
        project_dns_label = "sample"
        services: dict = {}

    out = render_traefik_dynamic_config([_NoSvcEnv()])  # type: ignore[list-item]
    assert out == "http:\n  routers: {}\n  services: {}\n"
    doc = yaml.safe_load(out)
    assert doc["http"]["routers"] == {}
    assert doc["http"]["services"] == {}


# ---------------------------------------------------------------------------
# 2. Release-side push gating.
# ---------------------------------------------------------------------------


def _elastic_ctx_with_rp(tmp_path: Path, variant: str | None):
    """Copy the elastic fixture, optionally set reverse_proxy, load ctx."""
    dest = tmp_path / "project_elastic"
    shutil.copytree(_FIXTURE_ELASTIC, dest, dirs_exist_ok=False)
    out = dest / "infra" / "output"
    if out.exists():
        shutil.rmtree(out)
    if variant is not None:
        infra_yml = dest / "infra" / "infra.yml"
        text = infra_yml.read_text()
        assert "reverse_proxy:" not in text
        text = text.replace(
            "foundation: elastic\n",
            f"foundation: elastic\nreverse_proxy: {variant}\n",
            1,
        )
        infra_yml.write_text(text)
    return load_project_context(dest)


def _ssm_config_calls(fake_aws):
    return [
        c for c in fake_aws.calls
        if c[0] == "ssm_put_parameter"
        and c[1][0].endswith("/ec2_traefik/config.yml")
    ]


def test_release_ec2_traefik_pushes_config_to_ssm(
    tmp_path, fake_aws, fake_tofu_init, fake_tofu_apply
):
    ctx = _elastic_ctx_with_rp(tmp_path, "ec2_traefik_eip")
    rc = run_release(
        ctx,
        env="stage",
        aws=fake_aws,
        tofu_init=fake_tofu_init,
        tofu_apply=fake_tofu_apply,
    )
    assert rc == 0
    pushes = _ssm_config_calls(fake_aws)
    assert len(pushes) == 1, fake_aws.calls
    name, value = pushes[0][1][0], pushes[0][1][1]
    # ssm_path policy preserves underscores; project 'sample' has none here.
    assert name == "/sample/ec2_traefik/config.yml"
    assert pushes[0][2].get("overwrite") is True
    # The pushed body is the real rendered config, not the empty stub.
    doc = yaml.safe_load(value)
    assert set(doc["http"]["routers"]) == {"api-stage", "api-prod"}


def test_release_ec2_traefik_pip_also_pushes(
    tmp_path, fake_aws, fake_tofu_init, fake_tofu_apply
):
    ctx = _elastic_ctx_with_rp(tmp_path, "ec2_traefik_pip")
    rc = run_release(
        ctx,
        env="prod",
        aws=fake_aws,
        tofu_init=fake_tofu_init,
        tofu_apply=fake_tofu_apply,
    )
    assert rc == 0
    assert len(_ssm_config_calls(fake_aws)) == 1


def test_release_alb_does_not_push_traefik_config(
    tmp_path, fake_aws, fake_tofu_init, fake_tofu_apply
):
    # Default (no reverse_proxy) == alb; must NOT push a traefik config.
    ctx = _elastic_ctx_with_rp(tmp_path, None)
    rc = run_release(
        ctx,
        env="stage",
        aws=fake_aws,
        tofu_init=fake_tofu_init,
        tofu_apply=fake_tofu_apply,
    )
    assert rc == 0
    assert _ssm_config_calls(fake_aws) == []
