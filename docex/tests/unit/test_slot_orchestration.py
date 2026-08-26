"""Mod 154 — ``docex test --slots N`` orchestration, seams, and injection.

Covers, with a fake docker (no real containers):
  * the slot-aware seams (``env_compose_project`` / ``exec_service_key`` /
    ``_migration_task_family``) — slot=1 byte-identical, slot=k carries ``-s{k}``;
  * the sharded orchestrator (``_run_test_sharded`` / ``_run_one_slot``) —
    N slots each running the whole suite (``test.sh``) with per-slot injection,
    keep-failed-up teardown;
  * the byte-identical default (``slots=1`` never touches a slot>1 file and
    never injects ``DOCEX_TEST_SLOT``).
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from docex.context import load_project_context
from docex.orchestrate._common import (
    env_compose_project,
    exec_service_key,
    slot_compose_file,
)
from docex.orchestrate.migrate import _migration_task_family
from docex.orchestrate.test import run_test

_DOCEX_ROOT = Path(__file__).resolve().parents[2]
_FIXED = _DOCEX_ROOT / "test_projects" / "fixed"
_ELASTIC = _DOCEX_ROOT / "test_projects" / "elastic"
_IGNORE = shutil.ignore_patterns(".git", ".docex", ".pytest_cache", "__pycache__")


def _copy_ctx(src: Path, tmp_path: Path):
    dest = tmp_path / src.name
    shutil.copytree(src, dest, ignore=_IGNORE)
    shutil.rmtree(dest / "infra" / "output", ignore_errors=True)
    return load_project_context(dest)


# ---------------------------------------------------------------------------
# H1 — slot-aware seam identities
# ---------------------------------------------------------------------------


def test_env_compose_project_slot_segment(tmp_path):
    ctx = _copy_ctx(_FIXED, tmp_path)
    # slot 1 is byte-identical to the no-kwarg call.
    assert env_compose_project(ctx, "test", slot=1) == env_compose_project(
        ctx, "test"
    )
    assert env_compose_project(ctx, "test") == "docex-smoke-fixed-test"
    # slot k appends -s{k}.
    assert env_compose_project(ctx, "test", slot=2) == "docex-smoke-fixed-test-s2"
    assert env_compose_project(ctx, "test", slot=5) == "docex-smoke-fixed-test-s5"


def test_slot_compose_file_layout(tmp_path):
    ctx = _copy_ctx(_FIXED, tmp_path)
    assert slot_compose_file(ctx, "test", 1) == (
        ctx.project_root / "infra" / "output" / "test" / "docker-compose.yml"
    )
    assert slot_compose_file(ctx, "test", 3) == (
        ctx.project_root / ".docex" / "slots" / "test" / "3" / "docker-compose.yml"
    )


def test_exec_service_key_slot_verifies_against_slot_file(tmp_path):
    """slot=2 derives the slotted exec key AND verifies against the *slot-2*
    compiled compose file (not slot 1)."""
    from docex.cicl.compile import compile_slot

    ctx = _copy_ctx(_FIXED, tmp_path)
    # Compile slot 2 so the verify path in exec_service_key has a real file.
    compile_slot(ctx, "test", 2)

    k1 = exec_service_key(ctx, "test", "api")
    k1_explicit = exec_service_key(ctx, "test", "api", slot=1)
    assert k1 == k1_explicit  # slot=1 identical to the no-kwarg call.

    k2 = exec_service_key(ctx, "test", "api", slot=2)
    assert k2 == "docex-smoke-fixed-test-s2-api-exec"
    assert "-test-s2-" in k2 and k2.endswith("-exec")


def test_migration_task_family_slot(tmp_path):
    """The elastic migrate task-family threads the slot; slot=1 unchanged."""
    ctx = _copy_ctx(_ELASTIC, tmp_path)
    project = ctx.project.name

    fam1 = _migration_task_family(ctx, project=project, env="test", svc="api")
    fam1_explicit = _migration_task_family(
        ctx, project=project, env="test", svc="api", slot=1
    )
    assert fam1 == fam1_explicit

    fam2 = _migration_task_family(
        ctx, project=project, env="test", svc="api", slot=2
    )
    assert "-test-s2-" in fam2 and fam2.endswith("-migrate")
    # slot=2 is exactly slot=1 with the -s2 segment spliced in.
    assert fam2 == fam1.replace("-test-", "-test-s2-", 1)


# ---------------------------------------------------------------------------
# H2 — sharded orchestration with a fake docker
# ---------------------------------------------------------------------------


@pytest.fixture
def sharded_env(tmp_path, monkeypatch):
    """A fixed-project ctx with the non-orchestration collaborators stubbed so
    the sharded path is exercised hermetically (no real compile / aggregate).
    ``exec_service_key`` still derives real slotted names; with no compiled slot
    file present it skips verification and returns the derivation.
    """
    import docex.cicl.compile as compile_mod
    import docex.orchestrate.test as test_mod

    ctx = _copy_ctx(_FIXED, tmp_path)

    monkeypatch.setattr(test_mod, "ensure_compiled", lambda _ctx: None)
    monkeypatch.setattr(
        test_mod, "aggregate", lambda _ctx, *, env: tmp_path / "agg.env"
    )
    compiled_slots: list[int] = []
    monkeypatch.setattr(
        compile_mod, "compile_slot",
        lambda _ctx, _env, k: compiled_slots.append(k),
    )
    return ctx, compiled_slots


def _suite_env_calls(fake):
    return [
        c for c in fake.calls
        if c[0] == "compose_run_one_off_env" and c[2] == ("./test.sh",)
    ]


def _down_project_names(fake):
    return [c[1] for c in fake.calls if c[0] == "compose_down_project_name"]


def test_sharded_three_slots_run_whole_suite(sharded_env, fake_docker):
    from docex.orchestrate.test import _run_test_sharded

    ctx, compiled_slots = sharded_env
    rc = _run_test_sharded(ctx, fake_docker, selector=None, slots=3)
    assert rc == 0

    # Each slot 1..3 was compiled.
    assert sorted(compiled_slots) == [1, 2, 3]

    # Each slot's project name + compose file are the slotted forms.
    projects = {env_compose_project(ctx, "test", slot=k) for k in (1, 2, 3)}
    up_projects = {
        c[1] for c in fake_docker.calls if c[0] == "compose_up_project_name"
    }
    assert up_projects == projects

    # The suite shim carries DOCEX_TEST_SLOT=k / DOCEX_TEST_SLOTS=3 for each of
    # the three slots (and NOT a selector — none was set).
    env_calls = _suite_env_calls(fake_docker)
    assert len(env_calls) == 3
    slot_values = set()
    for _tag, _svc, _cmd, items in env_calls:
        d = dict(items)
        assert d["DOCEX_TEST_SLOTS"] == "3"
        assert "DOCEX_TEST_SELECTOR" not in d
        slot_values.add(d["DOCEX_TEST_SLOT"])
    assert slot_values == {"1", "2", "3"}

    # migrate.sh one-offs never carry the slot injection.
    mig_env = [
        c for c in fake_docker.calls
        if c[0] == "compose_run_one_off_env" and c[2] == ("./migrate.sh",)
    ]
    assert mig_env == []

    # All slots passed -> each stack torn down (pre-up down + success down = 2).
    downs = _down_project_names(fake_docker)
    for proj in projects:
        assert downs.count(proj) == 2


def test_sharded_selector_composes_with_slot(sharded_env, fake_docker):
    from docex.orchestrate.test import _run_test_sharded

    ctx, _slots = sharded_env
    rc = _run_test_sharded(
        ctx, fake_docker, selector="tests/foo.py", slots=2,
    )
    assert rc == 0
    for _tag, _svc, _cmd, items in _suite_env_calls(fake_docker):
        d = dict(items)
        assert d["DOCEX_TEST_SELECTOR"] == "tests/foo.py"
        assert d["DOCEX_TEST_SLOTS"] == "2"


def test_sharded_failed_slot_left_up_passing_torn_down(sharded_env, fake_docker):
    from docex.orchestrate.test import _run_test_sharded

    ctx, _slots = sharded_env
    slot2_key = exec_service_key(ctx, "test", "api", slot=2)
    # Slot 2's suite shim fails (finer per-(svc,cmd) scripting).
    fake_docker.exit_codes[
        ("exit", "compose_run_one_off", slot2_key, ("./test.sh",))
    ] = 5

    rc = _run_test_sharded(ctx, fake_docker, selector=None, slots=3)
    # Lowest-numbered failing slot's code.
    assert rc == 5

    downs = _down_project_names(fake_docker)
    p1 = env_compose_project(ctx, "test", slot=1)
    p2 = env_compose_project(ctx, "test", slot=2)
    p3 = env_compose_project(ctx, "test", slot=3)
    # Passing slots: pre-up down + success teardown = 2 each.
    assert downs.count(p1) == 2
    assert downs.count(p3) == 2
    # Failed slot: pre-up down ONLY, left up for debugging (no teardown).
    assert downs.count(p2) == 1


# ---------------------------------------------------------------------------
# H4 — byte-identical default (slots=1)
# ---------------------------------------------------------------------------


def test_slots1_takes_single_stack_path_no_injection(sample_ctx, fake_docker):
    """slots=1 (default) must never touch a slot>1 compose file and never
    inject DOCEX_TEST_SLOT — behavior-identical to today."""
    rc = run_test(sample_ctx, fake_docker, slots=1)
    assert rc == 0

    # No compose call ever referenced a .docex/slots/ (slot>1) file.
    slot_paths = [
        c for c in fake_docker.calls
        if len(c) > 1 and isinstance(c[1], str) and "/.docex/slots/" in c[1]
    ]
    assert slot_paths == []

    # No DOCEX_TEST_SLOT / DOCEX_TEST_SLOTS injected anywhere.
    for c in fake_docker.calls:
        if c[0] == "compose_run_one_off_env":
            keys = {k for k, _v in c[3]}
            assert "DOCEX_TEST_SLOT" not in keys
            assert "DOCEX_TEST_SLOTS" not in keys
