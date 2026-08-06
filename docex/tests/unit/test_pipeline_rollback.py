"""Unit tests for ``docex rollback``.

The rollback orchestrator is largely a precondition gauntlet plus a
delegation to ``_release_fixed`` / ``_release_elastic`` with
``skip_migrations=True``. These tests verify the gauntlet and the
delegation shape; the release machinery itself is covered by
``test_pipeline_release.py``.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import pytest


@dataclass
class _StubSSH:
    """Minimal in-module ``SSHClient`` stub (avoids importing the shared
    ``conftest`` fake, which is ambiguous across the repo's two conftests)."""

    capture_out: str = ""
    capture_rc: int = 0
    calls: list = field(default_factory=list)

    def run(self, host, key_path, command, *, user="deploy"):
        self.calls.append(("run", host, str(key_path), command, user))
        return 0

    def capture(self, host, key_path, command, *, user="deploy"):
        self.calls.append(("capture", host, str(key_path), command, user))
        return (self.capture_rc, self.capture_out)

from docex.errors import (
    EnvNotSupported,
    RollbackPreconditionFailed,
    WorkingTreeDirty,
)
from docex.pipeline import rollback as rollback_mod
from docex.pipeline.rollback import run_rollback


# ---------------------------------------------------------------------------
# Shared test scaffolding
# ---------------------------------------------------------------------------


@pytest.fixture
def stub_compile(monkeypatch):
    """Replace the worktree's recompile with a no-op so the test
    doesn't need to actually emit infra config."""
    import docex.cicl.compile as cicl_compile

    monkeypatch.setattr(cicl_compile, "run_compile", lambda *_a, **_kw: 0)


@pytest.fixture
def worktree_populator(sample_ctx, fake_git):
    """Configure ``fake_git`` so worktree_add materializes the sample
    fixture into the worktree path. Returns (ctx, fake_git).

    Mirrors the check-test helper: rollback's worktree+recompile flow
    requires a real project tree at the worktree path.
    """
    fake_git.clean = True
    fake_git.branch = "main"
    fake_git.tags = ["v0.0.5"]

    original_worktree_add = fake_git.worktree_add

    def populating_worktree_add(cwd, path, *, branch=None, ref="HEAD"):
        rc = original_worktree_add(cwd, path, branch=branch, ref=ref)
        if rc == 0:
            for entry in sample_ctx.project_root.iterdir():
                if entry.name == ".docex":
                    continue
                target = Path(path) / entry.name
                if entry.is_dir():
                    shutil.copytree(entry, target, dirs_exist_ok=True)
                else:
                    shutil.copy2(entry, target)
        return rc

    fake_git.worktree_add = populating_worktree_add  # type: ignore[method-assign]
    return sample_ctx, fake_git


@pytest.fixture
def elastic_worktree_populator(elastic_ctx, fake_git):
    """Same shape as worktree_populator but for the elastic fixture."""
    fake_git.clean = True
    fake_git.branch = "main"
    fake_git.tags = ["v0.0.5"]

    original_worktree_add = fake_git.worktree_add

    def populating_worktree_add(cwd, path, *, branch=None, ref="HEAD"):
        rc = original_worktree_add(cwd, path, branch=branch, ref=ref)
        if rc == 0:
            for entry in elastic_ctx.project_root.iterdir():
                if entry.name == ".docex":
                    continue
                target = Path(path) / entry.name
                if entry.is_dir():
                    shutil.copytree(entry, target, dirs_exist_ok=True)
                else:
                    shutil.copy2(entry, target)
        return rc

    fake_git.worktree_add = populating_worktree_add  # type: ignore[method-assign]
    return elastic_ctx, fake_git


def _invoke(
    ctx, fake_git, fake_docker, fake_aws, fake_ansible,
    fake_tofu_init, fake_tofu_apply, fake_tofu_plan,
    *,
    env="prod",
    target_version="0.0.5",
    dry_run=False,
    ssh=None,
):
    return run_rollback(
        ctx,
        env=env,
        target_version=target_version,
        docker=fake_docker,
        git=fake_git,
        aws=fake_aws,
        ansible_runner=fake_ansible,
        tofu_init=fake_tofu_init,
        tofu_apply=fake_tofu_apply,
        tofu_plan=fake_tofu_plan,
        ssh=ssh if ssh is not None else _StubSSH(),
        dry_run=dry_run,
    )


# ---------------------------------------------------------------------------
# Precondition tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("env", ["dev", "test", "nonsense"])
def test_rollback_rejects_unknown_env(
    env, sample_ctx, fake_git, fake_docker, fake_aws, fake_ansible,
    fake_tofu_init, fake_tofu_apply, fake_tofu_plan,
):
    with pytest.raises(EnvNotSupported):
        _invoke(
            sample_ctx, fake_git, fake_docker, fake_aws, fake_ansible,
            fake_tofu_init, fake_tofu_apply, fake_tofu_plan,
            env=env,
        )


def test_rollback_rejects_non_main_branch(
    sample_ctx, fake_git, fake_docker, fake_aws, fake_ansible,
    fake_tofu_init, fake_tofu_apply, fake_tofu_plan,
):
    fake_git.branch = "feature/x"
    fake_git.clean = True
    with pytest.raises(RollbackPreconditionFailed):
        _invoke(
            sample_ctx, fake_git, fake_docker, fake_aws, fake_ansible,
            fake_tofu_init, fake_tofu_apply, fake_tofu_plan,
        )
    # No release runner should have been invoked.
    assert fake_ansible.calls == []
    assert fake_tofu_apply.calls == []


def test_rollback_rejects_dirty_tree(
    sample_ctx, fake_git, fake_docker, fake_aws, fake_ansible,
    fake_tofu_init, fake_tofu_apply, fake_tofu_plan,
):
    fake_git.branch = "main"
    fake_git.clean = False
    with pytest.raises(WorkingTreeDirty):
        _invoke(
            sample_ctx, fake_git, fake_docker, fake_aws, fake_ansible,
            fake_tofu_init, fake_tofu_apply, fake_tofu_plan,
        )


def test_rollback_tolerates_dirt_under_infra_output(
    worktree_populator, fake_docker, fake_aws, fake_ansible,
    fake_tofu_init, fake_tofu_apply, fake_tofu_plan, stub_compile,
):
    """``docex release`` rewrites ``infra/output/`` via its implicit
    compile step, so an emergency operator who just released will have
    legitimate dirt there. Rollback must not refuse on that alone."""
    ctx, fake_git = worktree_populator
    fake_git.clean = True
    fake_git.dirty_paths = {
        "infra/output/prod/docker-compose.yml",
        "infra/output/stage/main.tf",
    }
    rc = _invoke(
        ctx, fake_git, fake_docker, fake_aws, fake_ansible,
        fake_tofu_init, fake_tofu_apply, fake_tofu_plan,
    )
    assert rc == 0


def test_rollback_rejects_dirt_outside_infra_output(
    sample_ctx, fake_git, fake_docker, fake_aws, fake_ansible,
    fake_tofu_init, fake_tofu_apply, fake_tofu_plan,
):
    """Dirt anywhere other than ``infra/output/`` is still a refusal —
    that signals source work in flight that could confuse rollback."""
    fake_git.branch = "main"
    fake_git.clean = True
    fake_git.dirty_paths = {"core/web/src/app.py"}
    fake_git.tags = ["v0.0.5"]
    with pytest.raises(WorkingTreeDirty):
        _invoke(
            sample_ctx, fake_git, fake_docker, fake_aws, fake_ansible,
            fake_tofu_init, fake_tofu_apply, fake_tofu_plan,
        )


def test_rollback_rejects_missing_tag(
    sample_ctx, fake_git, fake_docker, fake_aws, fake_ansible,
    fake_tofu_init, fake_tofu_apply, fake_tofu_plan,
):
    fake_git.branch = "main"
    fake_git.clean = True
    fake_git.tags = []  # no v0.0.5 tag
    with pytest.raises(RollbackPreconditionFailed) as excinfo:
        _invoke(
            sample_ctx, fake_git, fake_docker, fake_aws, fake_ansible,
            fake_tofu_init, fake_tofu_apply, fake_tofu_plan,
        )
    assert "v0.0.5" in str(excinfo.value)
    # Worktree must not have been created.
    methods = [c[0] for c in fake_git.calls]
    assert "worktree_add" not in methods


def test_rollback_rejects_two_minors_back(
    sample_ctx, fake_git, fake_docker, fake_aws, fake_ansible,
    fake_tofu_init, fake_tofu_apply, fake_tofu_plan,
):
    # Bump fixture version to 1.5.2 so a 1.3.0 target is two minors back.
    pyml = sample_ctx.project_root / "project.yml"
    pyml.write_text('name: sample\nversion: "1.5.2"\ndocex_version: "0.11.0"\n')
    from docex.context import load_project_context
    ctx = load_project_context(sample_ctx.project_root)

    fake_git.branch = "main"
    fake_git.clean = True
    fake_git.tags = ["v1.3.0"]
    with pytest.raises(RollbackPreconditionFailed):
        _invoke(
            ctx, fake_git, fake_docker, fake_aws, fake_ansible,
            fake_tofu_init, fake_tofu_apply, fake_tofu_plan,
            target_version="1.3.0",
        )


def test_rollback_rejects_major_crossing(
    sample_ctx, fake_git, fake_docker, fake_aws, fake_ansible,
    fake_tofu_init, fake_tofu_apply, fake_tofu_plan,
):
    pyml = sample_ctx.project_root / "project.yml"
    pyml.write_text('name: sample\nversion: "2.0.0"\ndocex_version: "0.11.0"\n')
    from docex.context import load_project_context
    ctx = load_project_context(sample_ctx.project_root)

    fake_git.branch = "main"
    fake_git.clean = True
    fake_git.tags = ["v1.9.9"]
    with pytest.raises(RollbackPreconditionFailed):
        _invoke(
            ctx, fake_git, fake_docker, fake_aws, fake_ansible,
            fake_tofu_init, fake_tofu_apply, fake_tofu_plan,
            target_version="1.9.9",
        )


@pytest.mark.parametrize("target", ["0.1.0", "0.2.0"])
def test_rollback_rejects_target_equal_or_newer(
    target, sample_ctx, fake_git, fake_docker, fake_aws, fake_ansible,
    fake_tofu_init, fake_tofu_apply, fake_tofu_plan,
):
    # sample fixture is 0.1.0; both 0.1.0 (equal) and 0.2.0 (newer) must fail.
    fake_git.branch = "main"
    fake_git.clean = True
    fake_git.tags = [f"v{target}"]
    with pytest.raises(RollbackPreconditionFailed):
        _invoke(
            sample_ctx, fake_git, fake_docker, fake_aws, fake_ansible,
            fake_tofu_init, fake_tofu_apply, fake_tofu_plan,
            target_version=target,
        )


_TAG = "v0.0.5"
_INFRA = "infra/infra.yml"


def _preflight_git(fake_git, *, content):
    """fake_git configured to pass every precondition ahead of the CICL
    check, with ``content`` scripted as the target tag's infra.yml."""
    fake_git.branch = "main"
    fake_git.clean = True
    fake_git.tags = [_TAG]
    fake_git.file_at_ref[(_TAG, _INFRA)] = content
    return fake_git


def test_rollback_rejects_cicl_v1_target(
    sample_ctx, fake_git, fake_docker, fake_aws, fake_ansible,
    fake_tofu_init, fake_tofu_apply, fake_tofu_plan,
):
    """A target written in CICL v1 cannot be recompiled by this docex, so
    rollback refuses it in pre-flight with a fix-forward message."""
    _preflight_git(fake_git, content='cicl_version: "1"\nfoundation: fixed\n')
    with pytest.raises(RollbackPreconditionFailed) as excinfo:
        _invoke(
            sample_ctx, fake_git, fake_docker, fake_aws, fake_ansible,
            fake_tofu_init, fake_tofu_apply, fake_tofu_plan,
        )
    msg = str(excinfo.value)
    assert "CICL v1→v3 boundary" in msg
    assert "Nothing has been touched" in msg
    assert "Fix forward" in msg
    # The reassurance line is the whole point of the boundary branch, and it
    # must name the CURRENT generation rather than a hard-coded one.
    assert 'Once a second cicl_version "3" release exists' in msg


def test_rollback_cicl_v1_aborts_before_worktree_created(
    sample_ctx, fake_git, fake_docker, fake_aws, fake_ansible,
    fake_tofu_init, fake_tofu_apply, fake_tofu_plan,
):
    """The point of Mod 105: the refusal is pre-flight, so no worktree is
    ever created. A non-zero return is not sufficient evidence."""
    from docex.pipeline._worktree import worktree_path_for

    _preflight_git(fake_git, content='cicl_version: "1"\nfoundation: fixed\n')
    with pytest.raises(RollbackPreconditionFailed):
        _invoke(
            sample_ctx, fake_git, fake_docker, fake_aws, fake_ansible,
            fake_tofu_init, fake_tofu_apply, fake_tofu_plan,
        )
    assert "worktree_add" not in [c[0] for c in fake_git.calls]
    path = worktree_path_for(sample_ctx.project_root, "rollback-0.0.5")
    assert not path.exists()


def test_rollback_cicl_v1_aborts_before_registry_probe(
    sample_ctx, fake_git, fake_docker, fake_aws, fake_ansible,
    fake_tofu_init, fake_tofu_apply, fake_tofu_plan,
):
    """Pins the ordering decision: the CICL check is strictly cheaper and
    strictly more decisive than the image probe, so it runs first and the
    operator is not shown a missing-image list for an impossible rollback."""
    _preflight_git(fake_git, content='cicl_version: "1"\nfoundation: fixed\n')
    with pytest.raises(RollbackPreconditionFailed):
        _invoke(
            sample_ctx, fake_git, fake_docker, fake_aws, fake_ansible,
            fake_tofu_init, fake_tofu_apply, fake_tofu_plan,
        )
    assert "manifest_inspect" not in [c[0] for c in fake_docker.calls]
    assert "ecr_image_exists" not in [c[0] for c in fake_aws.calls]


def test_rollback_v2_target_proceeds_to_release(
    worktree_populator, fake_docker, fake_aws, fake_ansible,
    fake_tofu_init, fake_tofu_apply, fake_tofu_plan, stub_compile,
):
    """The new precondition must not become a false gate: a target that
    explicitly declares the CURRENT cicl_version reaches the release call."""
    ctx, fake_git = worktree_populator
    fake_git.file_at_ref[(_TAG, _INFRA)] = 'cicl_version: "3"\n'
    rc = _invoke(
        ctx, fake_git, fake_docker, fake_aws, fake_ansible,
        fake_tofu_init, fake_tofu_apply, fake_tofu_plan,
    )
    assert rc == 0
    assert len(fake_ansible.calls) == 1


def test_rollback_aborts_when_target_infra_yml_unreadable(
    sample_ctx, fake_git, fake_docker, fake_aws, fake_ansible,
    fake_tofu_init, fake_tofu_apply, fake_tofu_plan,
):
    """A target with no readable infra/infra.yml is not a target rollback
    should apply — and the operator gets a message, not a traceback."""
    _preflight_git(fake_git, content=None)
    with pytest.raises(RollbackPreconditionFailed) as excinfo:
        _invoke(
            sample_ctx, fake_git, fake_docker, fake_aws, fake_ansible,
            fake_tofu_init, fake_tofu_apply, fake_tofu_plan,
        )
    assert excinfo.type is RollbackPreconditionFailed
    msg = str(excinfo.value)
    assert "v0.0.5" in msg
    assert "infra/infra.yml" in msg
    assert "Fix forward" in msg


def test_rollback_aborts_on_unparseable_target_infra_yml(
    sample_ctx, fake_git, fake_docker, fake_aws, fake_ansible,
    fake_tofu_init, fake_tofu_apply, fake_tofu_plan,
):
    """Broken YAML — and a top level that is not a mapping — abort with a
    comprehensible message; no ``yaml.YAMLError`` escapes."""
    import yaml

    _preflight_git(fake_git, content='cicl_version: "2"\n  bad: [unclosed\n')
    with pytest.raises(RollbackPreconditionFailed) as excinfo:
        _invoke(
            sample_ctx, fake_git, fake_docker, fake_aws, fake_ansible,
            fake_tofu_init, fake_tofu_apply, fake_tofu_plan,
        )
    assert not isinstance(excinfo.value, yaml.YAMLError)
    msg = str(excinfo.value)
    assert "v0.0.5" in msg
    assert "not parseable YAML" in msg

    # Same band, sibling branch: parses, but not to a mapping.
    fake_git.calls.clear()
    fake_git.file_at_ref[(_TAG, _INFRA)] = "just a bare string\n"
    with pytest.raises(RollbackPreconditionFailed) as excinfo:
        _invoke(
            sample_ctx, fake_git, fake_docker, fake_aws, fake_ansible,
            fake_tofu_init, fake_tofu_apply, fake_tofu_plan,
        )
    assert "does not parse to a mapping" in str(excinfo.value)


def test_rollback_absent_cicl_version_gets_boundary_message(
    sample_ctx, fake_git, fake_docker, fake_aws, fake_ansible,
    fake_tofu_init, fake_tofu_apply, fake_tofu_plan,
):
    """A document predating the field is by definition an older generation —
    it gets the boundary message, but must not be misreported as declaring a
    version string it does not carry."""
    _preflight_git(
        fake_git, content="foundation: fixed\napex_domain: example.com\n",
    )
    with pytest.raises(RollbackPreconditionFailed) as excinfo:
        _invoke(
            sample_ctx, fake_git, fake_docker, fake_aws, fake_ansible,
            fake_tofu_init, fake_tofu_apply, fake_tofu_plan,
        )
    msg = str(excinfo.value)
    assert "CICL v1→v3 boundary" in msg
    assert "predates the field" in msg
    assert 'declares cicl_version "1"' not in msg


def test_rollback_v2_target_gets_the_boundary_message_not_the_generic_one(
    sample_ctx, fake_git, fake_docker, fake_aws, fake_ansible,
    fake_tofu_init, fake_tofu_apply, fake_tofu_plan,
):
    """Mod 113. Once `CURRENT_CICL_VERSION` moved to "3", every EXISTING tagged
    release declares "2" — so this is the case the operator actually hits, and
    it is a known one-release-cycle condition rather than a mystery.

    The precondition is NOT weakened (rollback still aborts). What this pins is
    that the message is intelligible: it names the target's own generation and
    the current one, and it keeps the reassurance line saying the condition
    clears once a second v3 release exists. Before the generalization a "2"
    target fell into the generic branch, which is accurate but drops exactly
    the reassurance the situation calls for.
    """
    _preflight_git(fake_git, content='cicl_version: "2"\nfoundation: fixed\n')
    with pytest.raises(RollbackPreconditionFailed) as excinfo:
        _invoke(
            sample_ctx, fake_git, fake_docker, fake_aws, fake_ansible,
            fake_tofu_init, fake_tofu_apply, fake_tofu_plan,
        )
    msg = str(excinfo.value)
    assert "CICL v2→v3 boundary" in msg
    assert 'declares cicl_version "2"' in msg
    assert 'Once a second cicl_version "3" release exists' in msg
    assert "Nothing has been touched" in msg


def test_rollback_rejects_unrecognized_cicl_version(
    sample_ctx, fake_git, fake_docker, fake_aws, fake_ansible,
    fake_tofu_init, fake_tofu_apply, fake_tofu_plan,
):
    """An unrecognized generation is not a known one-cycle boundary
    condition, so it gets a distinct message — mirroring rule 21's split."""
    _preflight_git(fake_git, content='cicl_version: "9"\n')
    with pytest.raises(RollbackPreconditionFailed) as excinfo:
        _invoke(
            sample_ctx, fake_git, fake_docker, fake_aws, fake_ansible,
            fake_tofu_init, fake_tofu_apply, fake_tofu_plan,
        )
    msg = str(excinfo.value)
    assert "'9'" in msg
    assert "Fix forward" in msg
    assert "boundary" not in msg


def test_rollback_lists_all_missing_images(
    sample_ctx, fake_git, fake_docker, fake_aws, fake_ansible,
    fake_tofu_init, fake_tofu_apply, fake_tofu_plan,
):
    """All core service images missing → error message lists every ref,
    not just the first."""
    # Add a second core service so we can verify aggregation.
    fake_git.branch = "main"
    fake_git.clean = True
    fake_git.tags = ["v0.0.5"]

    # Mark the api image as missing.
    expected_ref = "registry.example.com/sample/api:0.0.5"
    fake_docker.manifest_inspect_results = {expected_ref: False}

    with pytest.raises(RollbackPreconditionFailed) as excinfo:
        _invoke(
            sample_ctx, fake_git, fake_docker, fake_aws, fake_ansible,
            fake_tofu_init, fake_tofu_apply, fake_tofu_plan,
        )
    msg = str(excinfo.value)
    assert expected_ref in msg
    assert "image(s) missing" in msg


# ---------------------------------------------------------------------------
# Happy-path delegation tests
# ---------------------------------------------------------------------------


def test_rollback_fixed_calls_ansible_with_skip_tags(
    worktree_populator, fake_docker, fake_aws, fake_ansible,
    fake_tofu_init, fake_tofu_apply, fake_tofu_plan, stub_compile,
):
    """Fixed foundation: ansible is invoked once with skip_tags=['migrate']
    and check_mode=False; no tofu or AWS calls."""
    ctx, fake_git = worktree_populator
    rc = _invoke(
        ctx, fake_git, fake_docker, fake_aws, fake_ansible,
        fake_tofu_init, fake_tofu_apply, fake_tofu_plan,
    )
    assert rc == 0
    assert len(fake_ansible.calls) == 1
    call = fake_ansible.calls[0]
    assert call.get("skip_tags") == ["migrate"]
    assert call.get("check_mode") is False
    # No tofu, no AWS-side mutations.
    assert fake_tofu_apply.calls == []
    assert fake_tofu_plan.calls == []
    aws_names = [c[0] for c in fake_aws.calls]
    assert "ssm_put_parameter" not in aws_names
    assert "ecs_run_task" not in aws_names


def test_rollback_elastic_skips_runtask_and_pre_apply(
    elastic_worktree_populator, fake_docker, fake_aws, fake_ansible,
    fake_tofu_init, fake_tofu_apply, fake_tofu_plan, stub_compile,
):
    """Elastic foundation: a single unrestricted tofu_apply with no
    targets, and no RunTask migration."""
    ctx, fake_git = elastic_worktree_populator
    rc = _invoke(
        ctx, fake_git, fake_docker, fake_aws, fake_ansible,
        fake_tofu_init, fake_tofu_apply, fake_tofu_plan,
    )
    assert rc == 0
    aws_names = [c[0] for c in fake_aws.calls]
    assert "ecs_run_task" not in aws_names
    # tofu_apply ran exactly once with no targets.
    assert len(fake_tofu_apply.calls) == 1
    assert fake_tofu_apply.calls[0].get("targets") in (None, [])
    # Ansible is not invoked on the elastic path.
    assert fake_ansible.calls == []


def test_rollback_elastic_reconcile_is_a_noop(
    elastic_worktree_populator, fake_docker, fake_aws, fake_ansible,
    fake_tofu_init, fake_tofu_apply, fake_tofu_plan, stub_compile,
):
    """Mod 109, retriggered by mods 114 and 123.

    What this asserts is the WIRING: the rollback branch runs the reconcile step
    like any other release, with a populated namespace. It does not exercise the
    predicate — the sample elastic fixture declares no core `uses` edge, so
    there is no consumer to judge. The predicate itself is covered in
    `test_service_connect_reconcile.py`.

    Worth asserting rather than assuming: the reconcile is wired into this
    branch deliberately (one code path is easier to reason about than two), and
    a rollback that started force-redeploying consumers would be a surprising
    and expensive regression. The namespace is scripted as *populated*, which
    is the realistic rollback state — an empty script would make the no-op
    vacuous.
    """
    ctx, fake_git = elastic_worktree_populator
    fake_aws.service_connect_endpoint_ages = {
        "sample-prod-api-web": datetime(2026, 8, 5, 20, 40, tzinfo=timezone.utc),
        "sample-prod-appdb": datetime(2026, 8, 5, 20, 40, tzinfo=timezone.utc),
    }
    rc = _invoke(
        ctx, fake_git, fake_docker, fake_aws, fake_ansible,
        fake_tofu_init, fake_tofu_apply, fake_tofu_plan,
    )
    assert rc == 0
    aws_names = [c[0] for c in fake_aws.calls]
    # The namespace read happened (so the wiring is live, not dead code)...
    assert "service_connect_endpoints" in aws_names
    # ...and produced no redeploy and no wait.
    assert "ecs_force_new_deployment" not in aws_names
    assert "ecs_wait_services_stable" not in aws_names
    # Mod 123: no candidate consumer, so the deployment-age read is skipped
    # entirely. This is what proves the candidate filter is doing its job — a
    # converged rollback pays one ListServices and nothing else.
    assert "ecs_primary_deployment_times" not in aws_names


def test_rollback_mirrors_gitignored_creds_into_worktree(
    sample_ctx, fake_git, fake_docker, fake_aws, fake_ansible,
    fake_tofu_init, fake_tofu_apply, fake_tofu_plan, stub_compile,
):
    """Doctrine bootstrap gitignores ``infra/deploy_creds/<env>`` and
    ``infra/secrets/<env>.env`` — ``git worktree add`` does not carry
    them into the worktree, but the release functions read them via
    ``worktree_ctx.project_root``. ``run_rollback`` must copy them in
    before dispatching.

    Regression: the 0.12.0 PRE_CUT_CHECKLIST fixed walk caught
    ``_release_fixed`` aborting with 'expected SSH deploy key at ...'
    because the worktree lacked the gitignored key.
    """
    fake_git.clean = True
    fake_git.branch = "main"
    fake_git.tags = ["v0.0.5"]

    skip_relpaths = {
        Path("infra/deploy_creds") / "prod",
        Path("infra/secrets") / "prod.env",
    }
    original_worktree_add = fake_git.worktree_add

    def populating_worktree_add(cwd, path, *, branch=None, ref="HEAD"):
        rc = original_worktree_add(cwd, path, branch=branch, ref=ref)
        if rc != 0:
            return rc
        # Mirror sample fixture into worktree, but skip the entries that
        # would be gitignored in a real worktree.
        src_root = sample_ctx.project_root
        for src_path in src_root.rglob("*"):
            if src_path.is_dir():
                continue
            rel = src_path.relative_to(src_root)
            if rel.parts[0] == ".docex":
                continue
            if rel in skip_relpaths:
                continue
            dst = Path(path) / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_path, dst)
        return rc

    fake_git.worktree_add = populating_worktree_add  # type: ignore[method-assign]

    rc = _invoke(
        sample_ctx, fake_git, fake_docker, fake_aws, fake_ansible,
        fake_tofu_init, fake_tofu_apply, fake_tofu_plan,
    )
    # rc == 0 proves _release_fixed found both the SSH key AND the
    # secrets file — which only happens if rollback's mirror step
    # copied them from project_root into the worktree.
    assert rc == 0, (
        "rollback failed when worktree lacked gitignored creds/secrets — "
        "the mirror step in run_rollback regressed"
    )
    assert len(fake_ansible.calls) == 1


def test_rollback_fixed_mirrors_config_into_worktree(
    sample_ctx, fake_git, fake_docker, fake_aws, fake_ansible,
    fake_tofu_init, fake_tofu_apply, fake_tofu_plan, stub_compile,
):
    """Mod 081: the fixed release recompiles + reads ``infra/config/<env>.env``
    from the worktree, but that file is gitignored so ``git worktree add``
    does not carry it. ``run_rollback`` must mirror it in alongside the
    deploy key + secrets. We prove the mirror by having the worktree
    populator SKIP the config file (as a real worktree would) and asserting
    a recording ansible runner sees it present at invocation time."""
    fake_git.clean = True
    fake_git.branch = "main"
    fake_git.tags = ["v0.0.5"]

    # Give the source a config file with a sentinel value.
    from docex.envfile import write_env_file
    write_env_file(
        sample_ctx.project_root / "infra" / "config" / "prod.env",
        {"PARTNER_URL": "https://partner.example"},
    )

    skip_rel = Path("infra/config") / "prod.env"
    original_worktree_add = fake_git.worktree_add

    def populating_worktree_add(cwd, path, *, branch=None, ref="HEAD"):
        rc = original_worktree_add(cwd, path, branch=branch, ref=ref)
        if rc != 0:
            return rc
        src_root = sample_ctx.project_root
        for src_path in src_root.rglob("*"):
            if src_path.is_dir():
                continue
            rel = src_path.relative_to(src_root)
            if rel.parts[0] == ".docex" or rel == skip_rel:
                continue
            dst = Path(path) / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_path, dst)
        return rc

    fake_git.worktree_add = populating_worktree_add  # type: ignore[method-assign]

    seen: dict[str, bool] = {}

    def recording_runner(playbook, inventory, **kwargs):
        # playbook == <worktree>/infra/output/prod/playbook.yml
        worktree_root = Path(playbook).parents[3]
        seen["config_present"] = (
            worktree_root / "infra" / "config" / "prod.env"
        ).is_file()
        return 0

    rc = _invoke(
        sample_ctx, fake_git, fake_docker, fake_aws, recording_runner,
        fake_tofu_init, fake_tofu_apply, fake_tofu_plan,
    )
    assert rc == 0
    assert seen.get("config_present") is True, (
        "run_rollback did not mirror infra/config/<env>.env into the worktree"
    )


def test_rollback_fixed_threads_ssh_to_release(
    worktree_populator, fake_docker, fake_aws, fake_ansible,
    fake_tofu_init, fake_tofu_apply, fake_tofu_plan, stub_compile,
):
    """The injected SSH client reaches the fixed release path: the host TTE
    store is read via ``capture`` during rollback (host-authoritative)."""
    ctx, fake_git = worktree_populator
    ssh = _StubSSH(capture_out="POSTGRES_PASSWORD=live\n")
    rc = _invoke(
        ctx, fake_git, fake_docker, fake_aws, fake_ansible,
        fake_tofu_init, fake_tofu_apply, fake_tofu_plan,
        ssh=ssh,
    )
    assert rc == 0
    assert any(c[0] == "capture" and "tte.env" in c[3] for c in ssh.calls)


def test_rollback_elastic_still_pushes_ssm(
    elastic_worktree_populator, fake_docker, fake_aws, fake_ansible,
    fake_tofu_init, fake_tofu_apply, fake_tofu_plan, stub_compile,
):
    """Elastic foundation: SSM push still happens for every secret in
    the .env file (rollback re-aligns SSM with the recompiled HCL's
    expectations)."""
    ctx, fake_git = elastic_worktree_populator
    rc = _invoke(
        ctx, fake_git, fake_docker, fake_aws, fake_ansible,
        fake_tofu_init, fake_tofu_apply, fake_tofu_plan,
    )
    assert rc == 0
    # The elastic fixture's stage.env carries at least one secret.
    ssm_pushes = [c for c in fake_aws.calls if c[0] == "ssm_put_parameter"]
    assert ssm_pushes, "expected at least one SSM push during elastic rollback"


def test_rollback_dry_run_fixed_uses_check_mode(
    worktree_populator, fake_docker, fake_aws, fake_ansible,
    fake_tofu_init, fake_tofu_apply, fake_tofu_plan, stub_compile,
):
    """Fixed + --dry-run: ansible is invoked with check_mode=True."""
    ctx, fake_git = worktree_populator
    rc = _invoke(
        ctx, fake_git, fake_docker, fake_aws, fake_ansible,
        fake_tofu_init, fake_tofu_apply, fake_tofu_plan,
        dry_run=True,
    )
    assert rc == 0
    assert len(fake_ansible.calls) == 1
    assert fake_ansible.calls[0].get("check_mode") is True
    assert fake_ansible.calls[0].get("skip_tags") == ["migrate"]


def test_rollback_dry_run_elastic_uses_plan_skips_ssm(
    elastic_worktree_populator, fake_docker, fake_aws, fake_ansible,
    fake_tofu_init, fake_tofu_apply, fake_tofu_plan, stub_compile,
):
    """Elastic + --dry-run: tofu_plan runs; SSM push is NOT performed
    (dry-run must be side-effect-free); tofu_apply is NOT invoked."""
    ctx, fake_git = elastic_worktree_populator
    rc = _invoke(
        ctx, fake_git, fake_docker, fake_aws, fake_ansible,
        fake_tofu_init, fake_tofu_apply, fake_tofu_plan,
        dry_run=True,
    )
    assert rc == 0
    assert len(fake_tofu_plan.calls) == 1
    assert fake_tofu_apply.calls == []
    aws_names = [c[0] for c in fake_aws.calls]
    assert "ssm_put_parameter" not in aws_names


# ---------------------------------------------------------------------------
# Worktree lifecycle tests
# ---------------------------------------------------------------------------


def test_rollback_worktree_cleaned_up_on_success(
    worktree_populator, fake_docker, fake_aws, fake_ansible,
    fake_tofu_init, fake_tofu_apply, fake_tofu_plan, stub_compile,
):
    ctx, fake_git = worktree_populator
    rc = _invoke(
        ctx, fake_git, fake_docker, fake_aws, fake_ansible,
        fake_tofu_init, fake_tofu_apply, fake_tofu_plan,
    )
    assert rc == 0
    methods = [c[0] for c in fake_git.calls]
    assert "worktree_add" in methods
    assert "worktree_remove" in methods
    # The worktree directory should be gone.
    worktree_root = ctx.project_root / ".docex" / "worktrees"
    if worktree_root.exists():
        assert not list(worktree_root.iterdir())


def test_rollback_worktree_cleaned_up_on_recompile_failure(
    worktree_populator, fake_docker, fake_aws, fake_ansible,
    fake_tofu_init, fake_tofu_apply, fake_tofu_plan, monkeypatch,
):
    """If recompile fails, the worktree must still be torn down."""
    ctx, fake_git = worktree_populator
    import docex.cicl.compile as cicl_compile
    monkeypatch.setattr(cicl_compile, "run_compile", lambda *_a, **_kw: 7)

    rc = _invoke(
        ctx, fake_git, fake_docker, fake_aws, fake_ansible,
        fake_tofu_init, fake_tofu_apply, fake_tofu_plan,
    )
    assert rc == 7
    methods = [c[0] for c in fake_git.calls]
    assert "worktree_remove" in methods


# ---------------------------------------------------------------------------
# Version validator (one-minor-back)
# ---------------------------------------------------------------------------


def test_validate_one_minor_back_accepts_same_minor_older_patch():
    from docex.pipeline._worktree import validate_one_minor_back
    assert validate_one_minor_back("1.5.2", "1.5.0") is None


def test_validate_one_minor_back_accepts_one_minor_behind():
    from docex.pipeline._worktree import validate_one_minor_back
    assert validate_one_minor_back("1.5.2", "1.4.7") is None


def test_validate_one_minor_back_rejects_two_minors_behind():
    from docex.pipeline._worktree import validate_one_minor_back
    assert validate_one_minor_back("1.5.2", "1.3.0") is not None


def test_validate_one_minor_back_rejects_major_crossing():
    from docex.pipeline._worktree import validate_one_minor_back
    assert validate_one_minor_back("2.0.0", "1.9.9") is not None


def test_validate_one_minor_back_rejects_equal_version():
    from docex.pipeline._worktree import validate_one_minor_back
    assert validate_one_minor_back("1.5.2", "1.5.2") is not None


def test_validate_one_minor_back_rejects_newer_target():
    from docex.pipeline._worktree import validate_one_minor_back
    assert validate_one_minor_back("1.5.2", "1.6.0") is not None


# Silence the unused-name warning by referencing the imported module.
_ = rollback_mod
