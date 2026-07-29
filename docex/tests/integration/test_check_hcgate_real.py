"""Real-docker integration test for the mod 051 (Gap I) healthcheck-tooling
gate.

The gate builds a `health_check_path`-declaring web service's `prod`-target
image and probes for `curl`. The boundary it guards is real (a curl-less
base image silently kills the Traefik route), so we exercise it against a
genuine `docker build` + `docker run`: a deliberately curl-less image must
fail the gate, and a curl-carrying image must pass it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from docex.context import load_project_context
from docex.docker import SubprocessDockerClient
from docex.pipeline.check import CheckReport, _gate_healthcheck_tooling


def _make_hc_project(root: Path, dockerfile_body: str) -> Path:
    """Materialize a minimal fixed project whose `api` web service declares
    `health_check_path` and whose Dockerfile is supplied by the caller."""
    (root / "infra").mkdir(parents=True)
    (root / "core" / "api").mkdir(parents=True)
    (root / "project.yml").write_text(
        'name: hc\nversion: "0.1.0"\ndocex_version: "1.0.3"\n'
    )
    (root / "infra" / "infra.yml").write_text(
        'cicl_version: "2"\n'
        "foundation: fixed\n"
        'apex_domain: "example.com"\n'
        'container_registry: "registry.example.com"\n'
        'observability_backend_url: "https://hyperdx.luxrnd.tech"\n'
        "domain_default_process: api.web\n"
        "core_services:\n"
        "  api:\n"
        "    processes:\n"
        "      web:\n"
        "        role: web\n"
        '        command: ["python", "/service/dist/root.py"]\n'
        "        port: 8080\n"
        "        networks: [web, internal]\n"
        "        health_check_path: /health\n"
        "        resources:\n"
        "          cpu: 1.0\n"
        "          memory: 2GB\n"
        "          disk: 20GB\n"
    )
    (root / "core" / "api" / "Dockerfile").write_text(dockerfile_body)
    return root


@pytest.mark.integration
def test_hcgate_real_fails_on_curlless_image(tmp_path: Path):
    root = _make_hc_project(
        tmp_path / "proj",
        # busybox carries no curl; a single prod stage is all the gate needs.
        "FROM busybox:latest AS prod\n",
    )
    ctx = load_project_context(root)
    docker = SubprocessDockerClient()
    report = CheckReport()
    _gate_healthcheck_tooling(root, ctx, docker, report)

    res = next(r for r in report.results if r.name == "healthcheck_tooling")
    assert not res.passed, res.detail
    assert "lacks curl" in res.detail


@pytest.mark.integration
def test_hcgate_real_passes_on_curl_image(tmp_path: Path):
    root = _make_hc_project(
        tmp_path / "proj",
        # Alpine + curl satisfies the requirement.
        "FROM alpine:latest AS prod\nRUN apk add --no-cache curl\n",
    )
    ctx = load_project_context(root)
    docker = SubprocessDockerClient()
    report = CheckReport()
    _gate_healthcheck_tooling(root, ctx, docker, report)

    res = next(r for r in report.results if r.name == "healthcheck_tooling")
    assert res.passed, res.detail
