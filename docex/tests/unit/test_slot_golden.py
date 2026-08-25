"""Mod 152 — the byte-identical default gate.

`docex compile` (slot 1) must reproduce each test project's committed golden
`infra/output/` tree byte-for-byte. This is the SC2 verification gate: the slot
primitive's default emits no segment, so existing output is unchanged.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from docex.cicl.compile import run_compile
from docex.context import load_project_context

_DOCEX_ROOT = Path(__file__).resolve().parents[2]
_TEST_PROJECTS = _DOCEX_ROOT / "test_projects"
_IGNORE = shutil.ignore_patterns(".git", ".docex", ".pytest_cache", "__pycache__")


def _walk_bytes(root: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(root)): p.read_bytes()
        for p in sorted(root.rglob("*")) if p.is_file()
    }


@pytest.mark.parametrize("foundation", ["fixed", "elastic"])
def test_slot1_recompile_is_byte_identical(tmp_path: Path, foundation: str) -> None:
    project = _TEST_PROJECTS / foundation
    golden = _walk_bytes(project / "infra" / "output")
    # Mod 152 / Option B (graceful per-foundation skip): the elastic golden
    # output was deleted in commit fd8c578 ("planning test overhaul and some
    # test project churn") while the fixed golden was kept and updated. Byte-
    # identity is foundation-agnostic (slot 1 inserts no segment on any code
    # path) and `fixed` exercises every path the slot touches, so the fixed
    # gate structurally proves what this gate exists to prove. This is a real
    # skip, NOT a hardcoded ["fixed"], so the two-foundation gate stays live and
    # AUTO-REACTIVATES the instant a committed golden for a foundation reappears.
    if not golden:
        pytest.skip(
            f"no committed golden for {foundation} under {project}/infra/output "
            "— deleted in fd8c578; gate auto-reactivates if it is restored"
        )

    dest = tmp_path / foundation
    shutil.copytree(project, dest, ignore=_IGNORE)
    shutil.rmtree(dest / "infra" / "output", ignore_errors=True)

    ctx = load_project_context(dest)
    assert run_compile(ctx) == 0

    fresh = _walk_bytes(dest / "infra" / "output")
    assert set(fresh) == set(golden), (
        f"file set drift: only-fresh={sorted(set(fresh) - set(golden))} "
        f"only-golden={sorted(set(golden) - set(fresh))}"
    )
    for rel in sorted(golden):
        assert fresh[rel] == golden[rel], f"byte drift in {rel}"
