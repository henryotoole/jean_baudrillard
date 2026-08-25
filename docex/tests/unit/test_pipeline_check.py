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

import pytest

from docex.errors import WorkingTreeDirty
from docex.pipeline import check as check_mod
from docex.pipeline import check_record
from docex.pipeline.check import run_check


def _stub_expensive_steps(monkeypatch, *, stub_compile: bool) -> None:
    """No-op check's expensive end-stage steps.

    ``stub_compile=False`` leaves ``run_compile`` REAL, which is what
    ``test_check_reaches_compile_when_a_surface_is_skipped`` needs: it asserts
    that compile is reached, so it cannot be the thing that is stubbed out.
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
    # Mod 155: the build step now compiles the reserved slot before building.
    # Insulate it exactly as run_compile / _compose_build / run_test are.
    monkeypatch.setattr(cicl_compile, "compile_slot", lambda *a, **kw: None)
    if stub_compile:
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
def stub_test_and_compile(monkeypatch):
    """Replace ``run_test`` + ``run_compile`` + the compose build step
    so check's expensive end-stage steps are no-ops.

    Each test that wants to see check exit successfully needs this so
    the test runner doesn't spawn real docker.
    """
    _stub_expensive_steps(monkeypatch, stub_compile=True)


@pytest.fixture
def stub_test_only(monkeypatch):
    """Like ``stub_test_and_compile`` but ``run_compile`` runs for real."""
    _stub_expensive_steps(monkeypatch, stub_compile=False)


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
    contract = (
        ctx.project_root / "infra" / "contracts" / "api.web.rest.openapi.yml"
    )
    contract.unlink()

    rc = run_check(ctx, fake_docker, fake_git)
    assert rc == 1
    # The error report should mention the missing contract.
    # (we can't easily capture the print output through report; the
    # fact that rc==1 with the contracts gate failing is enough.)


def test_check_contract_health_path_failure(
    worktree_setup, fake_docker, monkeypatch, stub_test_and_compile, capsys
):
    """Missing the declared health_check_path in the contract should fail the
    contract_health_path gate."""
    ctx, fake_git = worktree_setup
    # Replace the contract with one missing /health.
    contract = (
        ctx.project_root / "infra" / "contracts" / "api.web.rest.openapi.yml"
    )
    contract.write_text(
        "openapi: '3.0.3'\n"
        "info: { title: api, version: '0.1.0' }\n"
        "paths:\n"
        "  /other: { get: { responses: { '200': { description: ok } } } }\n"
    )
    rc = run_check(ctx, fake_docker, fake_git)
    assert rc == 1
    out = capsys.readouterr().out
    assert "contract_health_path" in out


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
    """All gates pass + no test failures → rc 0, and the ROSTER is exactly the
    nine gates mod 126 left behind plus mod 137's contract_spec_version gate."""
    ctx, fake_git = worktree_setup
    rc = run_check(ctx, fake_docker, fake_git)
    # One readouterr() only — a second call returns the drained-and-empty
    # remainder, not the same text.
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "all gates and tests passed" in out
    assert "all 10 gate(s) passed" in out
    assert "contract_health_path" in out
    assert "contract_spec_version" in out
    assert "health_endpoints" not in out
    assert "healthcheck_tooling" not in out


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


# ---------------------------------------------------------------------------
# Mod 126: the gates-before-compile ordering, and health.sh as the fourth shim.
# ---------------------------------------------------------------------------


def test_check_reaches_compile_when_a_surface_is_skipped(
    worktree_setup, fake_docker, stub_test_only
):
    """`_expected_contracts` skips a mixed-format surface ONLY because
    `run_compile` is reachable in the same command.

    Every gate passes on this document — the skip sees to that — and the project
    still fails `docex check`, at the compile step, with
    `rule_29_mixed_contract_formats`: the message that names the actual problem
    instead of a missing filename the author could never have produced.

    What this pins is REACHABILITY, not gate ORDER, and the distinction matters
    because the obvious reading is wrong: moving the gates after `run_compile`
    leaves this test green, since compile raises either way. The hole opens if
    `run_compile` stops being called (a `--gates-only` flag, an early return) or
    stops validating — delete the `run_compile` call from `run_check` and this
    test goes red with `DID NOT RAISE`.
    """
    from docex.errors import ValidationError

    ctx, fake_git = worktree_setup
    infra = ctx.project_root / "infra" / "infra.yml"
    infra.write_text(
        infra.read_text().replace(
            "          rest:\n            api_styles: [rest]\n",
            "          rest:\n            api_styles: [rest]\n"
            "          mixed:\n            api_styles: [rest, rpc]\n",
        )
    )

    with pytest.raises(ValidationError) as excinfo:
        run_check(ctx, fake_docker, fake_git)
    assert "rule_29_mixed_contract_formats" in str(excinfo.value)


def test_check_requires_health_sh(
    worktree_setup, fake_docker, stub_test_and_compile, capsys
):
    """`health.sh` is the fourth codebase shim (cicd.md § Check Step 3.1)."""
    ctx, fake_git = worktree_setup
    (ctx.project_root / "core" / "api" / "health.sh").unlink()
    rc = run_check(ctx, fake_docker, fake_git)
    out = capsys.readouterr().out
    assert rc == 1, out
    assert "codebase_scripts" in out


def test_check_requires_health_sh_executable(
    worktree_setup, fake_docker, stub_test_and_compile, capsys
):
    """Present but non-executable is the same failure — the compiler invokes it
    as `./health.sh <service>`."""
    ctx, fake_git = worktree_setup
    (ctx.project_root / "core" / "api" / "health.sh").chmod(0o644)
    rc = run_check(ctx, fake_docker, fake_git)
    out = capsys.readouterr().out
    assert rc == 1, out
    assert "codebase_scripts" in out


def test_check_requires_test_unit_sh(
    worktree_setup, fake_docker, stub_test_and_compile, capsys
):
    """`test_unit.sh` is one of the two mandatory test shims (mod 147)."""
    ctx, fake_git = worktree_setup
    (ctx.project_root / "core" / "api" / "test_unit.sh").unlink()
    rc = run_check(ctx, fake_docker, fake_git)
    out = capsys.readouterr().out
    assert rc == 1, out
    assert "codebase_scripts" in out


def test_check_requires_test_unit_sh_executable(
    worktree_setup, fake_docker, stub_test_and_compile, capsys
):
    """Present but non-executable is the same failure — docex invokes it as
    `./test_unit.sh`."""
    ctx, fake_git = worktree_setup
    (ctx.project_root / "core" / "api" / "test_unit.sh").chmod(0o644)
    rc = run_check(ctx, fake_docker, fake_git)
    out = capsys.readouterr().out
    assert rc == 1, out
    assert "codebase_scripts" in out


def test_check_requires_test_integration_sh(
    worktree_setup, fake_docker, stub_test_and_compile, capsys
):
    """`test_integration.sh` is the other mandatory test shim (mod 147)."""
    ctx, fake_git = worktree_setup
    (ctx.project_root / "core" / "api" / "test_integration.sh").unlink()
    rc = run_check(ctx, fake_docker, fake_git)
    out = capsys.readouterr().out
    assert rc == 1, out
    assert "codebase_scripts" in out


def test_check_requires_test_integration_sh_executable(
    worktree_setup, fake_docker, stub_test_and_compile, capsys
):
    """Present but non-executable is the same failure — docex invokes it as
    `./test_integration.sh`."""
    ctx, fake_git = worktree_setup
    (ctx.project_root / "core" / "api" / "test_integration.sh").chmod(0o644)
    rc = run_check(ctx, fake_docker, fake_git)
    out = capsys.readouterr().out
    assert rc == 1, out
    assert "codebase_scripts" in out


# ---------------------------------------------------------------------------
# Mod 136: `check` treats a fetch failure the way `merge` does — fatal, not a
# warning that then misfires first-release mode.
# ---------------------------------------------------------------------------


def test_check_fetch_failure_is_fatal(
    worktree_setup, fake_docker, stub_test_and_compile, capsys
):
    """A failed `git fetch origin` is fatal (origin present). It must NOT be
    downgraded to a warning and masquerade as an empty origin/main — that false
    green is exactly what let the git-creds bug land mid-pipeline (mod 136)."""
    ctx, fake_git = worktree_setup
    fake_git.exit_codes[("fetch", "origin")] = 128
    rc = run_check(ctx, fake_docker, fake_git)
    assert rc == 128
    captured = capsys.readouterr()
    out = captured.out + captured.err
    assert "skipped (empty origin/main)" not in out
    assert "first-release" not in out
    # The fetch aborts at step 2, before the worktree is ever created.
    assert not [c for c in fake_git.calls if c[0] == "worktree_add"]


def test_check_no_origin_skips_fetch(
    worktree_setup, fake_docker, stub_test_and_compile, capsys
):
    """No `origin` remote (the test projects): skip the fetch entirely, no error.
    First-release mode is reached via absent origin/main, as before — now without
    the spurious fetch-failure warning."""
    ctx, fake_git = worktree_setup
    fake_git.has_origin = False
    fake_git.refs = {"main", "HEAD"}
    rc = run_check(ctx, fake_docker, fake_git)
    captured = capsys.readouterr()
    out = captured.out + captured.err
    assert rc == 0, out
    assert not [c for c in fake_git.calls if c[0] == "fetch"]
    assert "no 'origin' remote" in out


# ---------------------------------------------------------------------------
# Mod 150: `check` writes the `.docex/checks/` provenance record on success.
# ---------------------------------------------------------------------------


def test_check_writes_record_on_success(
    worktree_setup, fake_docker, stub_test_and_compile, capsys
):
    """A fully-green check records what it validated for `merge` to trust."""
    ctx, fake_git = worktree_setup
    fake_git.rev_parse_map["origin/main"] = "trunkdeadbeef99"
    rc = run_check(ctx, fake_docker, fake_git)
    assert rc == 0, capsys.readouterr().out

    rec = check_record.read_check_record(ctx.project_root)
    assert rec is not None
    assert rec.feature_tip == fake_git.head  # "deadbeef1234"
    assert rec.origin_main == "trunkdeadbeef99"
    assert rec.docex_version == ctx.project.docex_version


def test_check_writes_no_record_on_failure(
    worktree_setup, fake_docker, stub_test_and_compile
):
    """A failed check (a gate fails before the green path) records nothing."""
    ctx, fake_git = worktree_setup
    # Lower the feature version below main's (0.0.1 via the git_show stub) so
    # the version_bumped gate FAILS and run_check returns before the write.
    pyml = ctx.project_root / "project.yml"
    pyml.write_text('name: sample\nversion: "0.0.0"\ndocex_version: "0.5.0"\n')
    from docex.context import load_project_context
    ctx = load_project_context(ctx.project_root)

    rc = run_check(ctx, fake_docker, fake_git)
    assert rc == 1
    assert check_record.read_check_record(ctx.project_root) is None
