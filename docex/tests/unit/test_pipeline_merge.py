"""Unit tests for ``docex merge``.

Merge depends on ``check`` (defensive recheck) plus a sequence of
git operations. We stub ``run_check`` to a no-op so the merge tests
focus on merge's own state machine.
"""

from __future__ import annotations

import pytest

from docex.errors import VersionAlreadyReleased
from docex.pipeline import merge as merge_mod
from docex.pipeline.merge import run_merge


@pytest.fixture
def patched_check(monkeypatch):
    """Replace ``run_check`` with a sink that just returns 0.

    Each test that needs to exercise a check-failure path overrides
    this by reassigning ``merge_mod.run_check`` to a different stub.
    """
    monkeypatch.setattr(merge_mod, "run_check", lambda *a, **kw: 0)
    return monkeypatch


def test_merge_happy_path(sample_ctx, fake_docker, fake_git, patched_check):
    fake_git.branch = "feature/x"
    rc = run_merge(sample_ctx, fake_docker, fake_git)
    assert rc == 0
    methods = [c[0] for c in fake_git.calls]
    # Fetch, rebase, fast-forward, tag, push, two delete_branch.
    assert "fetch" in methods
    assert "rebase" in methods
    assert "fast_forward" in methods
    assert "tag" in methods
    assert "push" in methods


def test_merge_runs_defensive_check_first(sample_ctx, fake_docker, fake_git, monkeypatch):
    """The defensive recheck must run before any mutating git op."""
    order: list[str] = []

    def fake_check(*_a, **_kw):
        order.append("check")
        return 0

    monkeypatch.setattr(merge_mod, "run_check", fake_check)

    # Wrap rebase so we know when it runs.
    original_rebase = fake_git.rebase

    def tracking_rebase(*a, **kw):
        order.append("rebase")
        return original_rebase(*a, **kw)

    fake_git.rebase = tracking_rebase  # type: ignore[method-assign]
    fake_git.branch = "feature/x"

    rc = run_merge(sample_ctx, fake_docker, fake_git)
    assert rc == 0
    assert order.index("check") < order.index("rebase")


def test_merge_aborts_when_defensive_check_fails(
    sample_ctx, fake_docker, fake_git, monkeypatch
):
    """If the defensive check fails, no git mutations should run."""
    monkeypatch.setattr(merge_mod, "run_check", lambda *a, **kw: 7)
    fake_git.branch = "feature/x"
    rc = run_merge(sample_ctx, fake_docker, fake_git)
    assert rc == 7
    # No mutating call should have happened.
    mutating = {c[0] for c in fake_git.calls} & {
        "fetch", "rebase", "fast_forward", "tag", "push", "delete_branch",
    }
    assert mutating == set(), fake_git.calls


def test_merge_aborts_on_rebase_failure(sample_ctx, fake_docker, fake_git, patched_check):
    fake_git.branch = "feature/x"
    fake_git.exit_codes[("rebase", "origin/main")] = 1
    rc = run_merge(sample_ctx, fake_docker, fake_git)
    assert rc == 1
    # rebase_abort must have run.
    assert ("rebase_abort", str(sample_ctx.project_root)) in fake_git.calls
    # No push should have happened.
    assert not any(c[0] == "push" for c in fake_git.calls)


def test_merge_tag_uses_project_version(sample_ctx, fake_docker, fake_git, patched_check):
    fake_git.branch = "feature/x"
    rc = run_merge(sample_ctx, fake_docker, fake_git)
    assert rc == 0
    tag_calls = [c for c in fake_git.calls if c[0] == "tag"]
    assert len(tag_calls) == 1
    # (method, cwd, name, ref)
    assert tag_calls[0][2] == f"v{sample_ctx.project.version}"
    assert tag_calls[0][3] == "main"


def test_merge_push_includes_main_and_tag(sample_ctx, fake_docker, fake_git, patched_check):
    fake_git.branch = "feature/x"
    rc = run_merge(sample_ctx, fake_docker, fake_git)
    assert rc == 0
    push_calls = [c for c in fake_git.calls if c[0] == "push"]
    assert len(push_calls) == 1
    refs = push_calls[0][3]  # (method, cwd, remote, refs_tuple)
    assert "main" in refs
    assert f"v{sample_ctx.project.version}" in refs


def test_merge_refuses_existing_tag(sample_ctx, fake_docker, fake_git, patched_check):
    """If the tag already exists, refuse rather than overwrite."""
    fake_git.branch = "feature/x"
    fake_git.tags.append(f"v{sample_ctx.project.version}")
    with pytest.raises(VersionAlreadyReleased):
        run_merge(sample_ctx, fake_docker, fake_git)


def test_merge_deletes_feature_branch_local_and_remote(
    sample_ctx, fake_docker, fake_git, patched_check
):
    fake_git.branch = "feature/x"
    rc = run_merge(sample_ctx, fake_docker, fake_git)
    assert rc == 0
    deletes = [c for c in fake_git.calls if c[0] == "delete_branch"]
    # One local + one remote.
    assert any(c[3] is False for c in deletes), deletes  # local
    assert any(c[3] is True for c in deletes), deletes  # remote


def test_merge_fails_when_origin_main_absent(
    sample_ctx, fake_docker, fake_git, patched_check
):
    """First release with origin present but no origin/main: merge must
    fail loudly (inception should have established main) rather than seed
    a trunk. No rebase, no tag, no push."""
    fake_git.branch = "feature/x"
    fake_git.refs = set()  # origin present (default), but empty — no origin/main
    rc = run_merge(sample_ctx, fake_docker, fake_git)
    assert rc != 0
    methods = {c[0] for c in fake_git.calls}
    assert "rebase" not in methods, fake_git.calls
    assert "fast_forward" not in methods, fake_git.calls
    assert "tag" not in methods, fake_git.calls
    assert "push" not in methods, fake_git.calls


def test_merge_fails_when_no_origin_and_no_local_main(
    sample_ctx, fake_docker, fake_git, patched_check
):
    """No origin AND no local main: nothing to rebase onto. Merge fails
    loudly instead of seeding a trunk."""
    fake_git.branch = "feature/x"
    fake_git.has_origin = False
    fake_git.refs = {"HEAD"}  # neither origin/main nor main exist
    rc = run_merge(sample_ctx, fake_docker, fake_git)
    assert rc != 0
    methods = {c[0] for c in fake_git.calls}
    assert "rebase" not in methods, fake_git.calls
    assert "fast_forward" not in methods, fake_git.calls
    assert "tag" not in methods, fake_git.calls


# --- Gap C: no-`origin` remote --------------------------------------


def test_merge_no_origin_skips_fetch_and_push(
    sample_ctx, fake_docker, fake_git, patched_check
):
    """A repo with no ``origin`` performs a local-only merge: no fetch,
    no push, rebase onto local ``main``, but the tag still lands."""
    fake_git.branch = "feature/x"
    fake_git.has_origin = False
    # Local main exists (the test-project case); origin/main is irrelevant.
    fake_git.refs = {"main", "HEAD"}

    rc = run_merge(sample_ctx, fake_docker, fake_git)
    assert rc == 0

    methods = [c[0] for c in fake_git.calls]
    assert "fetch" not in methods, fake_git.calls
    assert "push" not in methods, fake_git.calls

    # Rebase targets local ``main``, not ``origin/main``.
    rebases = [c for c in fake_git.calls if c[0] == "rebase"]
    assert len(rebases) == 1
    assert rebases[0][2] == "main"

    # Tag still happens.
    assert "tag" in methods


# --- Mod 146: remote preflight -------------------------------------


def test_merge_preflight_fails_fast_on_broken_auth(
    sample_ctx, fake_docker, fake_git, monkeypatch
):
    # run_check must be a spy we can prove is NEVER called.
    called = []
    monkeypatch.setattr(
        merge_mod, "run_check",
        lambda *a, **kw: (called.append(True), 0)[1],
    )
    fake_git.branch = "feature/x"
    fake_git.exit_codes[("ls_remote_sha", "origin")] = 128

    rc = run_merge(sample_ctx, fake_docker, fake_git)

    assert rc == 128
    assert called == [], "defensive check ran despite failed preflight"
    # No mutating git op — and no fetch — may have run.
    mutating = {c[0] for c in fake_git.calls} & {
        "fetch", "rebase", "fast_forward", "tag", "push", "delete_branch",
    }
    assert mutating == set(), fake_git.calls
    # The preflight itself must have run.
    assert any(c[0] == "ls_remote_sha" for c in fake_git.calls)


def test_merge_preflight_runs_before_check(
    sample_ctx, fake_docker, fake_git, monkeypatch
):
    order: list[str] = []
    monkeypatch.setattr(
        merge_mod, "run_check",
        lambda *a, **kw: (order.append("check"), 0)[1],
    )
    # ls_remote_sha records into fake_git.calls; capture its relative order.
    original_ls = fake_git.ls_remote_sha

    def tracking_ls(*a, **kw):
        order.append("ls_remote_sha")
        return original_ls(*a, **kw)

    fake_git.ls_remote_sha = tracking_ls  # type: ignore[method-assign]
    fake_git.branch = "feature/x"

    rc = run_merge(sample_ctx, fake_docker, fake_git)
    assert rc == 0
    assert order.index("ls_remote_sha") < order.index("check")


def test_merge_no_origin_skips_preflight(
    sample_ctx, fake_docker, fake_git, patched_check
):
    fake_git.branch = "feature/x"
    fake_git.has_origin = False
    # A scripted ls_remote_sha failure must be irrelevant when there's no origin.
    fake_git.exit_codes[("ls_remote_sha", "origin")] = 128
    rc = run_merge(sample_ctx, fake_docker, fake_git)
    assert rc == 0
    assert not any(c[0] == "ls_remote_sha" for c in fake_git.calls)
    # Local-only merge still integrates + tags.
    assert any(c[0] == "tag" for c in fake_git.calls)


def test_merge_preflight_passes_then_merges(
    sample_ctx, fake_docker, fake_git, patched_check
):
    fake_git.branch = "feature/x"
    rc = run_merge(sample_ctx, fake_docker, fake_git)
    assert rc == 0
    ls_calls = [c for c in fake_git.calls if c[0] == "ls_remote_sha"]
    assert len(ls_calls) == 1
    assert ls_calls[0] == (
        "ls_remote_sha", str(sample_ctx.project_root), "refs/heads/main", "origin"
    )


def test_merge_no_origin_deletes_local_branch_only(
    sample_ctx, fake_docker, fake_git, patched_check
):
    """No-origin merge deletes the local feature branch but never
    attempts a remote delete (there is no remote)."""
    fake_git.branch = "feature/x"
    fake_git.has_origin = False
    fake_git.refs = {"main", "HEAD"}

    rc = run_merge(sample_ctx, fake_docker, fake_git)
    assert rc == 0

    deletes = [c for c in fake_git.calls if c[0] == "delete_branch"]
    assert any(c[3] is False for c in deletes), deletes  # local
    assert not any(c[3] is True for c in deletes), deletes  # no remote


# --- Mod 150: trust-forward recheck skip + every forced-recheck reason ------
#
# The default fake_git has head == "abc1234", remote_main_sha == "abc1234",
# clean == True, branch == "feature/x". A "matching" record is one whose
# feature_tip == head, origin_main == remote_main_sha, and docex_version ==
# the ctx's docex_version — everything the skip predicate compares.


def _matching_record(sample_ctx, fake_git, **overrides):
    from docex.pipeline.check_record import CheckRecord

    base = dict(
        feature_tip=fake_git.head,
        origin_main=fake_git.remote_main_sha,
        merged_tree_sha="tree000abc",
        checked_at="2026-08-25T00:00:00+00:00",
        docex_version=sample_ctx.project.docex_version,
    )
    base.update(overrides)
    return CheckRecord(**base)


def _install_spy(monkeypatch, rec):
    """Point the reader at ``rec`` (or None) and install a run_check spy.

    Returns the ``called`` list — non-empty iff the defensive recheck ran.
    """
    called: list[bool] = []
    monkeypatch.setattr(
        merge_mod.check_record, "read_check_record", lambda _root: rec
    )
    monkeypatch.setattr(
        merge_mod, "run_check",
        lambda *a, **kw: (called.append(True), 0)[1],
    )
    return called


def test_merge_skips_recheck_when_record_matches(
    sample_ctx, fake_docker, fake_git, monkeypatch
):
    """Matching record + clean tree + version match → recheck skipped, but the
    merge still proceeds through rebase/tag/push."""
    fake_git.branch = "feature/x"
    fake_git.clean = True
    called = _install_spy(monkeypatch, _matching_record(sample_ctx, fake_git))

    rc = run_merge(sample_ctx, fake_docker, fake_git)
    assert rc == 0
    assert called == [], "defensive recheck ran despite a matching record"
    methods = {c[0] for c in fake_git.calls}
    assert "rebase" in methods
    assert "tag" in methods
    assert "push" in methods


def test_merge_forces_recheck_when_no_record(
    sample_ctx, fake_docker, fake_git, monkeypatch
):
    fake_git.branch = "feature/x"
    called = _install_spy(monkeypatch, None)
    rc = run_merge(sample_ctx, fake_docker, fake_git)
    assert rc == 0
    assert called == [True], "recheck must run when there is no record"


def test_merge_forces_recheck_when_trunk_moved(
    sample_ctx, fake_docker, fake_git, monkeypatch
):
    fake_git.branch = "feature/x"
    rec = _matching_record(sample_ctx, fake_git, origin_main="OLDTRUNK")
    called = _install_spy(monkeypatch, rec)
    rc = run_merge(sample_ctx, fake_docker, fake_git)
    assert rc == 0
    assert called == [True], "recheck must run when the trunk moved"


def test_merge_forces_recheck_when_feature_moved(
    sample_ctx, fake_docker, fake_git, monkeypatch
):
    fake_git.branch = "feature/x"
    rec = _matching_record(sample_ctx, fake_git, feature_tip="OLDFEAT")
    called = _install_spy(monkeypatch, rec)
    rc = run_merge(sample_ctx, fake_docker, fake_git)
    assert rc == 0
    assert called == [True], "recheck must run when the feature tip moved"


def test_merge_forces_recheck_when_tree_dirty(
    sample_ctx, fake_docker, fake_git, monkeypatch
):
    fake_git.branch = "feature/x"
    fake_git.clean = False  # matching record but the working tree is dirty
    called = _install_spy(monkeypatch, _matching_record(sample_ctx, fake_git))
    rc = run_merge(sample_ctx, fake_docker, fake_git)
    assert rc == 0
    assert called == [True], "recheck must run when the tree is dirty"


def test_merge_forces_recheck_on_corrupt_record(
    sample_ctx, fake_docker, fake_git, monkeypatch
):
    """The real degrade-safe reader path, end-to-end: a corrupt on-disk record
    reads as None → recheck forced."""
    from docex.pipeline import check_record

    fake_git.branch = "feature/x"
    check_record.checks_dir(sample_ctx.project_root).mkdir(parents=True)
    check_record.record_path(sample_ctx.project_root).write_text("{ not json")

    # Do NOT monkeypatch the reader — exercise it for real.
    called: list[bool] = []
    monkeypatch.setattr(
        merge_mod, "run_check",
        lambda *a, **kw: (called.append(True), 0)[1],
    )
    rc = run_merge(sample_ctx, fake_docker, fake_git)
    assert rc == 0
    assert called == [True], "recheck must run when the record is corrupt"


def test_merge_forces_recheck_on_version_mismatch(
    sample_ctx, fake_docker, fake_git, monkeypatch
):
    fake_git.branch = "feature/x"
    rec = _matching_record(sample_ctx, fake_git, docex_version="0.0.0-old")
    called = _install_spy(monkeypatch, rec)
    rc = run_merge(sample_ctx, fake_docker, fake_git)
    assert rc == 0
    assert called == [True], "recheck must run on a docex-version mismatch"
