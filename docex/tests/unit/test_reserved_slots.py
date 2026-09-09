"""Mod 155 — the reserved-slot band (Goal 4 SC4).

Proves that ``check``/``merge`` run their defensive test/check at reserved slots
above the ``docex test --slots N`` band, so their compiled ``test``-env physical
names (esp. the DB volume ``name:``) are deterministically name-disjoint from any
``docex test`` run and from each other — closing the ``--project-name`` DB-volume
collision. The disjointness is a pure function of the compiled names; the
name-derivation assertions below pin it exactly (no real docker).
"""
from __future__ import annotations

import inspect
import shutil
from pathlib import Path

import pytest
import yaml

from docex.cicl.compile import compile_slot
from docex.context import load_project_context
from docex.orchestrate._common import (
    CHECK_BASE,
    CHECK_SLOT,
    MAX_TEST_SLOTS,
    MERGE_BASE,
    MERGE_SLOT,
    band_slots,
    env_compose_project,
    exec_service_key,
)

_DOCEX_ROOT = Path(__file__).resolve().parents[2]
_FIXED = _DOCEX_ROOT / "test_projects" / "fixed"
_IGNORE = shutil.ignore_patterns(".git", ".docex", ".pytest_cache", "__pycache__")


def _ctx(tmp_path: Path):
    dest = tmp_path / "fixed"
    shutil.copytree(_FIXED, dest, ignore=_IGNORE)
    shutil.rmtree(dest / "infra" / "output", ignore_errors=True)
    return load_project_context(dest), dest


def _appdb_volume_name(compose_text: str) -> str:
    """The DB volume's global ``name:`` from an emitted compose file."""
    doc = yaml.safe_load(compose_text) or {}
    vols = doc.get("volumes") or {}
    names = [
        (v or {}).get("name")
        for n, v in vols.items()
        if "appdb_data" in n
    ]
    assert len(names) == 1, (names, list(vols))
    return names[0]


# ---------------------------------------------------------------------------
# 1. Band constants
# ---------------------------------------------------------------------------


def test_band_constants_are_disjoint():
    assert CHECK_SLOT > MAX_TEST_SLOTS
    assert MERGE_SLOT > MAX_TEST_SLOTS
    assert CHECK_SLOT != MERGE_SLOT
    # Mod 174: reserved BANDS, each MAX_TEST_SLOTS wide, derived from the ceiling
    # so test/check/merge stay disjoint by construction if MAX_TEST_SLOTS retunes.
    assert CHECK_BASE == MAX_TEST_SLOTS + 1
    assert MERGE_BASE == 2 * MAX_TEST_SLOTS + 1
    # The base of a gate's band doubles as its single-stack slot.
    assert CHECK_SLOT == CHECK_BASE
    assert MERGE_SLOT == MERGE_BASE


def test_bands_are_pairwise_disjoint_at_full_width():
    """test (1..8) ∪ check (9..16) ∪ merge (17..24) are pairwise disjoint at the
    full band width, and the highest slot is exactly 3*MAX_TEST_SLOTS."""
    test = set(band_slots(1, MAX_TEST_SLOTS))
    check = set(band_slots(CHECK_BASE, MAX_TEST_SLOTS))
    merge = set(band_slots(MERGE_BASE, MAX_TEST_SLOTS))
    assert test & check == set()
    assert test & merge == set()
    assert check & merge == set()
    assert max(test | check | merge) == 3 * MAX_TEST_SLOTS


# ---------------------------------------------------------------------------
# 2. Compiled DB-volume disjointness — the core SC4 proof
# ---------------------------------------------------------------------------


def test_compiled_db_volume_names_pairwise_disjoint(tmp_path):
    ctx, dest = _ctx(tmp_path)
    texts = {}
    vols = {}
    for k in (1, 2, CHECK_SLOT, MERGE_SLOT):
        out_dir = compile_slot(ctx, "test", k)
        texts[k] = (out_dir / "docker-compose.yml").read_text()
        vols[k] = _appdb_volume_name(texts[k])

    # Each slot's DB volume carries the expected segment.
    assert vols[1] == "docex-smoke-fixed-test-appdb_data"
    assert "-test-s" not in vols[1]
    assert vols[2] == "docex-smoke-fixed-test-s2-appdb_data"
    assert vols[CHECK_SLOT] == "docex-smoke-fixed-test-s9-appdb_data"
    assert vols[MERGE_SLOT] == "docex-smoke-fixed-test-s17-appdb_data"

    # All four volume names are distinct (the collision is closed).
    assert len(set(vols.values())) == 4

    # The reserved-slot names appear in NEITHER the slot-1 nor slot-2 compose.
    for reserved in (vols[CHECK_SLOT], vols[MERGE_SLOT]):
        assert reserved not in texts[1]
        assert reserved not in texts[2]

    # The same disjointness holds for container_name: — the -exec container
    # carries the right segment per slot (mirrors test_slot_primitive).
    assert "docex-smoke-fixed-test-s9-api-exec" in texts[CHECK_SLOT]
    assert "docex-smoke-fixed-test-s17-api-exec" in texts[MERGE_SLOT]
    assert "docex-smoke-fixed-test-s9-" not in texts[1]
    assert "docex-smoke-fixed-test-s17-" not in texts[2]


# ---------------------------------------------------------------------------
# 3. Derivation identities
# ---------------------------------------------------------------------------


def test_env_compose_project_reserved_slots(tmp_path):
    ctx, _ = _ctx(tmp_path)
    assert env_compose_project(ctx, "test", slot=CHECK_SLOT) == \
        "docex-smoke-fixed-test-s9"
    assert env_compose_project(ctx, "test", slot=MERGE_SLOT) == \
        "docex-smoke-fixed-test-s17"
    # slot=1 is byte-identical to the no-slot call, and disjoint from the band.
    assert env_compose_project(ctx, "test", slot=1) == \
        env_compose_project(ctx, "test")
    names = {
        env_compose_project(ctx, "test", slot=1),
        env_compose_project(ctx, "test", slot=2),
        env_compose_project(ctx, "test", slot=CHECK_SLOT),
        env_compose_project(ctx, "test", slot=MERGE_SLOT),
    }
    assert len(names) == 4


def test_exec_service_key_reserved_slots(tmp_path):
    ctx, _ = _ctx(tmp_path)
    # Compile the slot files so exec_service_key's verify path has real files.
    compile_slot(ctx, "test", CHECK_SLOT)
    compile_slot(ctx, "test", MERGE_SLOT)
    k9 = exec_service_key(ctx, "test", "api", slot=CHECK_SLOT)
    k17 = exec_service_key(ctx, "test", "api", slot=MERGE_SLOT)
    assert k9 == "docex-smoke-fixed-test-s9-api-exec"
    assert k17 == "docex-smoke-fixed-test-s17-api-exec"
    assert k9 != k17


# ---------------------------------------------------------------------------
# 4. check threads CHECK_SLOT / merge threads MERGE_SLOT
# ---------------------------------------------------------------------------


def _project_names(fake, tag: str) -> set[str]:
    return {c[1] for c in fake.calls if c[0] == tag}


@pytest.mark.parametrize("slot,expected_project,seg", [
    (CHECK_SLOT, "docex-smoke-fixed-test-s9", "-test-s9-"),
    (MERGE_SLOT, "docex-smoke-fixed-test-s17", "-test-s17-"),
])
def test_run_test_threads_reserved_slot(tmp_path, fake_docker, slot,
                                        expected_project, seg):
    """Driving ``run_test(..., slot=k)`` (the check/merge mechanism) brings up
    the reserved-slot stack: the reserved project name + slotted exec keys."""
    import docex.orchestrate.test as test_mod

    ctx, _ = _ctx(tmp_path)
    from docex.orchestrate.test import run_test

    rc = run_test(ctx, fake_docker, slot=slot)
    assert rc == 0

    # compose up + the pre-up reap + teardown all address the reserved project.
    assert _project_names(fake_docker, "compose_up_project_name") == \
        {expected_project}
    assert expected_project in _project_names(
        fake_docker, "compose_down_project_name"
    )

    # Every exec one-off ran in a slot-segmented exec container.
    execs = [
        c for c in fake_docker.calls
        if c[0] == "compose_run_one_off"
    ]
    assert execs, fake_docker.calls
    assert all(seg in c[2] for c in execs), execs

    # The compose file used is the gitignored slotted tree, never infra/output.
    assert all(
        f"/.docex/slots/test/{slot}/" in c[1]
        for c in fake_docker.calls
        if c[0] == "compose_up"
    )


def test_run_check_default_base_slot_is_check_base():
    """check's defensive band defaults to CHECK_BASE; slots defaults to 1."""
    from docex.pipeline.check import run_check

    params = inspect.signature(run_check).parameters
    assert params["base_slot"].default == CHECK_BASE
    assert params["slots"].default == 1
    # The old single `slot` param is gone — the band base doubles as the slot.
    assert "slot" not in params


def test_merge_defensive_check_runs_at_merge_base(
    sample_ctx, fake_docker, fake_git, monkeypatch
):
    """merge's in-process defensive check threads MERGE_BASE into run_check."""
    from docex.pipeline import merge as merge_mod

    recorded = {}

    def spy(ctx, docker, git, *, base_slot=CHECK_BASE, slots=1):
        recorded["base_slot"] = base_slot
        recorded["slots"] = slots
        return 0

    monkeypatch.setattr(merge_mod, "run_check", spy)
    # Force the defensive recheck (no trusted record present by default).
    fake_git.branch = "feature/x"
    rc = merge_mod.run_merge(sample_ctx, fake_docker, fake_git)
    assert rc == 0
    assert recorded["base_slot"] == MERGE_BASE
    assert recorded["slots"] == 1


def test_merge_slots_flows_into_defensive_check_at_merge_band(
    sample_ctx, fake_docker, fake_git, monkeypatch
):
    """A `merge --slots N` flows N into the in-process run_check, still at the
    merge band base."""
    from docex.pipeline import merge as merge_mod

    recorded = {}

    def spy(ctx, docker, git, *, base_slot=CHECK_BASE, slots=1):
        recorded["base_slot"] = base_slot
        recorded["slots"] = slots
        return 0

    monkeypatch.setattr(merge_mod, "run_check", spy)
    fake_git.branch = "feature/x"
    rc = merge_mod.run_merge(sample_ctx, fake_docker, fake_git, slots=3)
    assert rc == 0
    assert recorded == {"base_slot": MERGE_BASE, "slots": 3}


# ---------------------------------------------------------------------------
# 5. CLI ceiling
# ---------------------------------------------------------------------------


def test_cli_slots_above_ceiling_is_usage_error(monkeypatch, sample_ctx):
    """`docex test --slots (MAX_TEST_SLOTS+1)` is a usage error (exit 64), and
    no job is launched."""
    from docex import __main__ as main_mod

    monkeypatch.chdir(sample_ctx.project_root)
    monkeypatch.setattr(main_mod, "_require_docker", lambda: object())
    launched: list[int] = []
    monkeypatch.setattr(
        "docex.jobs.commands.run_test_job",
        lambda *a, **kw: launched.append(1) or 0,
    )
    assert main_mod._cmd_test(["--slots", str(MAX_TEST_SLOTS + 1)]) == 64
    assert launched == []


def test_cli_slots_at_ceiling_is_accepted(monkeypatch, sample_ctx):
    """`--slots MAX_TEST_SLOTS` is accepted (does not trip the ceiling guard)."""
    from docex import __main__ as main_mod

    monkeypatch.chdir(sample_ctx.project_root)
    monkeypatch.setattr(main_mod, "_require_docker", lambda: object())
    seen = {}
    monkeypatch.setattr(
        "docex.jobs.commands.run_test_job",
        lambda ctx, docker, *, detach, selector=None, slots=1: seen.update(
            slots=slots
        ) or 0,
    )
    assert main_mod._cmd_test(["--slots", str(MAX_TEST_SLOTS)]) == 0
    assert seen == {"slots": MAX_TEST_SLOTS}


# ---------------------------------------------------------------------------
# 5b. Mod 174 — `--slots` on check / merge: capped, and forwarded to the job
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("cmd", ["_cmd_check", "_cmd_merge"])
def test_gate_cli_slots_above_ceiling_is_usage_error(monkeypatch, sample_ctx, cmd):
    """`docex check/merge --slots (MAX+1)` is a usage error (exit 64); no job
    launched. The guard fires before any context/docker load."""
    from docex import __main__ as main_mod

    monkeypatch.chdir(sample_ctx.project_root)
    launched: list[int] = []
    monkeypatch.setattr(
        "docex.jobs.commands.run_check_job",
        lambda *a, **kw: launched.append(1) or 0,
    )
    monkeypatch.setattr(
        "docex.jobs.commands.run_merge_job",
        lambda *a, **kw: launched.append(1) or 0,
    )
    fn = getattr(main_mod, cmd)
    assert fn(["--slots", str(MAX_TEST_SLOTS + 1)]) == 64
    assert launched == []


@pytest.mark.parametrize("cmd,job_name", [
    ("_cmd_check", "run_check_job"),
    ("_cmd_merge", "run_merge_job"),
])
def test_gate_cli_slots_forwarded(monkeypatch, sample_ctx, cmd, job_name):
    """`--slots MAX` is accepted on check/merge and forwarded to the job."""
    from docex import __main__ as main_mod

    monkeypatch.chdir(sample_ctx.project_root)
    monkeypatch.setattr(main_mod, "_require_docker", lambda: object())
    monkeypatch.setattr(main_mod, "_require_git", lambda: object())
    seen = {}
    monkeypatch.setattr(
        f"docex.jobs.commands.{job_name}",
        lambda ctx, docker, git, *, detach, slots=1: seen.update(slots=slots) or 0,
    )
    fn = getattr(main_mod, cmd)
    assert fn(["--slots", str(MAX_TEST_SLOTS)]) == 0
    assert seen == {"slots": MAX_TEST_SLOTS}
