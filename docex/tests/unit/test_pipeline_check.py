"""Unit tests for ``docex check``.

We use FakeGitClient + FakeDockerClient to exercise the gate-check
machinery without spawning subprocesses. The worktree is "created"
by the FakeGitClient (it mkdir's a real directory at the requested
path), then this test populates the worktree with the sample fixture
contents so the gate checks (contracts, scripts, project.yml read)
have something to look at.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from docex.errors import WorkingTreeDirty
from docex.pipeline import check as check_mod
from docex.pipeline.check import run_check


@pytest.fixture
def stub_test_and_compile(monkeypatch):
    """Replace ``run_test`` + ``run_compile`` + the compose build step
    so check's expensive end-stage steps are no-ops.

    Each test that wants to see check exit successfully needs this so
    the test runner doesn't spawn real docker.
    """
    monkeypatch.setattr(
        check_mod,
        "_compose_build",
        lambda *_a, **_kw: 0,
    )
    # check imports these lazily — patch the locations they reach from.
    import docex.orchestrate.test as orch_test
    import docex.cicl.compile as cicl_compile

    monkeypatch.setattr(orch_test, "run_test", lambda *a, **kw: 0)
    monkeypatch.setattr(cicl_compile, "run_compile", lambda *a, **kw: 0)

    # Mod 019's reachability probe would otherwise hit the real network.
    # Return a fake context-manager response so the gate passes without
    # any DNS / TLS dependency.
    from unittest.mock import MagicMock

    fake_response = MagicMock()
    fake_response.__enter__ = MagicMock(return_value=fake_response)
    fake_response.__exit__ = MagicMock(return_value=False)
    monkeypatch.setattr(
        "docex.pipeline.check.urllib.request.urlopen",
        lambda *_a, **_kw: fake_response,
    )


@pytest.fixture
def worktree_setup(sample_ctx, fake_git, monkeypatch):
    """Wire FakeGitClient so worktree_add materializes the sample
    fixture content into the worktree path (so subsequent gate checks
    find a real project.yml + infra/ tree).

    Returns (ctx, fake_git).
    """
    fake_git.clean = True
    fake_git.branch = "feature/bump-api"
    fake_git.head = "deadbeef1234"
    # Make sure ``list_tags`` returns no existing v0.x tag.
    fake_git.tags = []

    # The default rebase / merge_base return values are fine; merge_base
    # for the latest_main check expects origin/main's sha; set it up
    # to look "fresh" so that gate passes.
    fake_git.merge_bases[("origin/main", "origin/main")] = "origin-main-sha"
    fake_git.merge_bases[("HEAD", "origin-main-sha")] = "origin-main-sha"

    # Make worktree_add populate the worktree path with the sample
    # fixture so the gate checks have content to inspect.
    original_worktree_add = fake_git.worktree_add

    def populating_worktree_add(cwd, path, *, branch=None, ref="HEAD"):
        rc = original_worktree_add(cwd, path, branch=branch, ref=ref)
        if rc == 0:
            # Copy the project content into the worktree.
            for entry in sample_ctx.project_root.iterdir():
                if entry.name == ".docex":
                    continue
                target = path / entry.name
                if entry.is_dir():
                    shutil.copytree(entry, target, dirs_exist_ok=True)
                else:
                    shutil.copy2(entry, target)
        return rc

    fake_git.worktree_add = populating_worktree_add  # type: ignore[method-assign]

    # Stub the _git_show helper to return a "main" project.yml with a
    # lower version so version_bumped passes.
    def fake_git_show(repo, ref, path):
        if path == "project.yml":
            return 'name: sample\nversion: "0.0.1"\ndocex_version: "0.3.0"\n'
        raise RuntimeError(f"unexpected git_show {ref}:{path}")

    monkeypatch.setattr(check_mod, "_git_show", fake_git_show)

    return sample_ctx, fake_git


def test_check_refuses_dirty_tree(sample_ctx, fake_docker, fake_git):
    fake_git.clean = False
    with pytest.raises(WorkingTreeDirty):
        run_check(sample_ctx, fake_docker, fake_git)


def test_check_refuses_on_main(sample_ctx, fake_docker, fake_git):
    fake_git.clean = True
    fake_git.branch = "main"
    rc = run_check(sample_ctx, fake_docker, fake_git)
    assert rc == 1


def test_check_refuses_detached_head(sample_ctx, fake_docker, fake_git):
    fake_git.clean = True
    fake_git.branch = ""
    rc = run_check(sample_ctx, fake_docker, fake_git)
    assert rc == 1


def test_check_creates_and_removes_worktree(
    worktree_setup, fake_docker, stub_test_and_compile
):
    ctx, fake_git = worktree_setup
    rc = run_check(ctx, fake_docker, fake_git)
    # Whether the gates pass or fail, the worktree must be cleaned up.
    worktree_root = ctx.project_root / ".docex" / "worktrees"
    if worktree_root.exists():
        # Any leftover dir would be a leak.
        assert not list(worktree_root.iterdir()), list(worktree_root.iterdir())
    # Both worktree_add and worktree_remove must have been called.
    methods = [c[0] for c in fake_git.calls]
    assert "worktree_add" in methods
    assert "worktree_remove" in methods


def test_check_cleans_up_worktree_on_failure(
    worktree_setup, fake_docker, monkeypatch
):
    """Even when a gate fails, the worktree must be torn down."""
    ctx, fake_git = worktree_setup
    # Bump version backwards so version_bumped gate FAILS — main
    # is "0.0.1" via our git_show stub, project.yml in the fixture is
    # already "0.1.0", so we need to *make* it fail by lowering it.
    pyml = ctx.project_root / "project.yml"
    pyml.write_text('name: sample\nversion: "0.0.0"\ndocex_version: "0.3.0"\n')
    # Reload context so future reads use the new file.
    from docex.context import load_project_context
    ctx = load_project_context(ctx.project_root)

    rc = run_check(ctx, fake_docker, fake_git)
    assert rc == 1
    # Worktree must be gone.
    worktree_root = ctx.project_root / ".docex" / "worktrees"
    if worktree_root.exists():
        assert not list(worktree_root.iterdir())


def test_check_contracts_missing_failure(
    worktree_setup, fake_docker, monkeypatch, stub_test_and_compile
):
    """Deleting the api contract file should surface a contracts_exist failure."""
    ctx, fake_git = worktree_setup
    # The worktree_setup copies project content via worktree_add. We
    # need to delete the contract BEFORE worktree_add runs. The
    # cleanest approach: delete it from the source fixture so the
    # populating copy lacks it.
    contract = ctx.project_root / "infra" / "contracts" / "api.openapi.yml"
    contract.unlink()

    rc = run_check(ctx, fake_docker, fake_git)
    assert rc == 1
    # The error report should mention the missing contract.
    # (we can't easily capture the print output through report; the
    # fact that rc==1 with the contracts gate failing is enough.)


def test_check_health_endpoint_missing_failure(
    worktree_setup, fake_docker, monkeypatch, stub_test_and_compile, capsys
):
    """Missing /health in the contract should fail the health_endpoints gate."""
    ctx, fake_git = worktree_setup
    # Replace the contract with one missing /health.
    contract = ctx.project_root / "infra" / "contracts" / "api.openapi.yml"
    contract.write_text(
        "openapi: '3.0.3'\n"
        "info: { title: api, version: '0.1.0' }\n"
        "paths:\n"
        "  /other: { get: { responses: { '200': { description: ok } } } }\n"
    )
    rc = run_check(ctx, fake_docker, fake_git)
    assert rc == 1
    out = capsys.readouterr().out
    assert "health_endpoints" in out


def test_check_version_already_released(
    worktree_setup, fake_docker, monkeypatch, stub_test_and_compile, capsys
):
    """If ``v<version>`` is already a tag, version_not_released must fail."""
    ctx, fake_git = worktree_setup
    fake_git.tags = [f"v{ctx.project.version}"]
    rc = run_check(ctx, fake_docker, fake_git)
    assert rc == 1
    out = capsys.readouterr().out
    assert "version_not_released" in out


def test_check_happy_path_aggregates_all_passing(
    worktree_setup, fake_docker, stub_test_and_compile, capsys
):
    """All gates pass + no test failures → rc 0."""
    ctx, fake_git = worktree_setup
    rc = run_check(ctx, fake_docker, fake_git)
    assert rc == 0, capsys.readouterr().out
    out = capsys.readouterr().out
    assert "all gates and tests passed" in out


# ---------------------------------------------------------------------------
# Gap I (mod 051): _gate_healthcheck_tooling unit tests.
# ---------------------------------------------------------------------------


def _hc_ctx(tmp_path: Path, *, web_with_hc=True, extra_worker=False, worker_hc=False):
    """Build a ProjectContext whose `api` web service declares
    `health_check_path`. Optionally add a non-web `worker` that the gate
    must skip (no `health_check_path`) or, with ``worker_hc``, one that
    declares `health_check_path` on a non-`web` network — which the gate
    must STILL check (mod 059)."""
    from docex.context import load_project_context

    root = tmp_path / "hcproj"
    (root / "infra").mkdir(parents=True)
    (root / "core" / "api").mkdir(parents=True)
    if extra_worker:
        (root / "core" / "worker").mkdir(parents=True)
    (root / "bin").mkdir(parents=True)
    (root / "project.yml").write_text(
        'name: hc\nversion: "0.1.0"\ndocex_version: "1.0.3"\n'
    )
    hc_line = "    health_check_path: /health\n" if web_with_hc else ""
    worker_block = (
        "  worker:\n"
        "    role: web\n"
        "    networks: [internal]\n"
        + ("    port: 9090\n" if worker_hc else "")
        + ("    health_check_path: /health\n" if worker_hc else "")
        + "    resources:\n"
        "      cpu: 0.5\n"
        "      memory: 512MB\n"
        "      disk: 1GB\n"
    ) if extra_worker else ""
    (root / "infra" / "infra.yml").write_text(
        'cicl_version: "1"\n'
        "foundation: fixed\n"
        'apex_domain: "example.com"\n'
        'container_registry: "registry.example.com"\n'
        'observability_backend_url: "https://hyperdx.luxrnd.tech"\n'
        "domain_default_service: api\n"
        "core_services:\n"
        "  api:\n"
        "    role: web\n"
        "    port: 8080\n"
        "    networks: [web, internal]\n"
        + hc_line +
        "    resources:\n"
        "      cpu: 1.0\n"
        "      memory: 2GB\n"
        "      disk: 20GB\n"
        + worker_block
    )
    return load_project_context(root), root


def test_hcgate_passes_when_curl_present(fake_docker, tmp_path):
    from docex.pipeline.check import CheckReport, _gate_healthcheck_tooling

    ctx, root = _hc_ctx(tmp_path)
    report = CheckReport()
    _gate_healthcheck_tooling(root, ctx, fake_docker, report)

    res = next(r for r in report.results if r.name == "healthcheck_tooling")
    assert res.passed, res.detail
    # Gate built the api prod image and probed for curl.
    assert ("build_image", str(root / "core" / "api"), "prod", "docex-hcgate-api:check") in fake_docker.calls
    assert any(c[0] == "run_one_shot" and "command -v curl" in c[2][-1] for c in fake_docker.calls)


def test_hcgate_fails_when_curl_absent(fake_docker, tmp_path):
    from docex.pipeline.check import CheckReport, _gate_healthcheck_tooling

    ctx, root = _hc_ctx(tmp_path)
    # Script the curl probe to fail.
    tag = "docex-hcgate-api:check"
    fake_docker.exit_codes[("run_one_shot", tag, ("sh", "-c", "command -v curl >/dev/null 2>&1"))] = 1
    report = CheckReport()
    _gate_healthcheck_tooling(root, ctx, fake_docker, report)

    res = next(r for r in report.results if r.name == "healthcheck_tooling")
    assert not res.passed
    assert "lacks curl" in res.detail
    assert "Add curl to its Dockerfile" in res.detail


def test_hcgate_skips_services_without_health_check_path(fake_docker, tmp_path):
    from docex.pipeline.check import CheckReport, _gate_healthcheck_tooling

    # api stays on web but DECLARES NO health_check_path, plus a non-web
    # worker — neither qualifies, so the gate passes without building.
    ctx, root = _hc_ctx(tmp_path, web_with_hc=False, extra_worker=True)
    report = CheckReport()
    _gate_healthcheck_tooling(root, ctx, fake_docker, report)

    res = next(r for r in report.results if r.name == "healthcheck_tooling")
    assert res.passed, res.detail
    assert "nothing to check" in res.detail
    # No image build attempted.
    assert not any(c[0] == "build_image" for c in fake_docker.calls)


def test_hcgate_checks_nonweb_health_check_path_service(fake_docker, tmp_path):
    # Mod 059: a `role: web` service on a NON-`web` network that declares
    # `health_check_path` still gets a curl healthcheck emitted, so the gate
    # must build+probe it even though it is not web-routed. Previously the
    # `on_web` filter skipped it.
    from docex.pipeline.check import CheckReport, _gate_healthcheck_tooling

    ctx, root = _hc_ctx(tmp_path, web_with_hc=False, extra_worker=True, worker_hc=True)
    report = CheckReport()
    _gate_healthcheck_tooling(root, ctx, fake_docker, report)

    res = next(r for r in report.results if r.name == "healthcheck_tooling")
    assert res.passed, res.detail
    # The gate built + probed the non-web worker, not just web services.
    assert (
        "build_image", str(root / "core" / "worker"), "prod",
        "docex-hcgate-worker:check",
    ) in fake_docker.calls


def test_hcgate_reports_build_failure(fake_docker, tmp_path):
    from docex.pipeline.check import CheckReport, _gate_healthcheck_tooling

    ctx, root = _hc_ctx(tmp_path)
    fake_docker.exit_codes[
        ("build_image", str(root / "core" / "api"), "prod", "docex-hcgate-api:check")
    ] = 1
    report = CheckReport()
    _gate_healthcheck_tooling(root, ctx, fake_docker, report)

    res = next(r for r in report.results if r.name == "healthcheck_tooling")
    assert not res.passed
    assert "image build failed" in res.detail
    # Build failed → no curl probe attempted.
    assert not any(c[0] == "run_one_shot" for c in fake_docker.calls)


def test_check_empty_origin_skips_trunk_gates(
    worktree_setup, fake_docker, stub_test_and_compile, capsys
):
    """First release on an empty remote: origin/main doesn't exist yet.
    The trunk-comparing gates can't run, so they're skipped with a
    banner; other gates still run."""
    ctx, fake_git = worktree_setup
    fake_git.refs = set()  # nothing exists on the remote
    rc = run_check(ctx, fake_docker, fake_git)
    assert rc == 0, capsys.readouterr().out
    out = capsys.readouterr().out + capsys.readouterr().err
    # The skipped gates appear as PASS with the "skipped" reason.
    assert "skipped (empty origin/main)" in out
    # rebase MUST NOT have been called — no trunk to rebase onto.
    assert not [c for c in fake_git.calls if c[0] == "rebase"]
