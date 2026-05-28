"""Real ``tofu validate`` against the compiled elastic fixture.

This is the regression guard for the six Phase 4 HCL emitter fixes
(see ``implementation/phase_4.md`` § Step 4). Without this test,
someone could break the HCL emission and unit tests would still
pass — because the structural correctness of HCL is precisely what
OpenTofu's parser checks.

The test:

  1. Copies the elastic fixture to a tmp dir.
  2. Runs ``docex compile``.
  3. Runs ``tofu init -backend=false`` (no state-backend wiring needed
     for validate).
  4. Runs ``tofu validate``.
  5. Asserts exit 0.

Skipped if ``tofu`` is not in PATH.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from docex.cicl.compile import run_compile
from docex.context import load_project_context


_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_FIXTURE_ELASTIC = (
    _REPO_ROOT / "tests" / "fixtures" / "sample_project_elastic"
)


def _tofu_available() -> bool:
    try:
        res = subprocess.run(
            ["tofu", "version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except FileNotFoundError:
        return False
    return res.returncode == 0


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _tofu_available(), reason="tofu not in PATH"),
]


@pytest.fixture
def compiled_elastic(tmp_path: Path) -> Path:
    """Copy the elastic fixture into tmp_path and compile it.

    Returns the env-tier output directory for ``prod``.
    """
    dest = tmp_path / "project"
    # ``symlinks=True`` preserves the fixture's ``core`` symlink without
    # following it, but the fixture's symlink is relative; we need to
    # materialize it for the temp dir.
    shutil.copytree(_FIXTURE_ELASTIC, dest, symlinks=False, dirs_exist_ok=False)
    ctx = load_project_context(dest)
    rc = run_compile(ctx)
    assert rc == 0, "compile must succeed before tofu validate"
    return dest / "infra" / "output" / "prod"


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def test_tofu_validate_passes_on_elastic_prod(compiled_elastic: Path):
    """``tofu validate`` exits 0 against the emitted prod main.tf.

    This locks in the six Step 4 HCL emitter fixes: any future change
    that reintroduces semicolon-in-block syntax, malformed secrets[]
    blocks, or other parse-time errors will fail this test.
    """
    init = _run(
        ["tofu", "init", "-backend=false", "-input=false"],
        cwd=compiled_elastic,
    )
    assert init.returncode == 0, (
        f"tofu init failed:\nstdout: {init.stdout}\nstderr: {init.stderr}"
    )

    validate = _run(["tofu", "validate"], cwd=compiled_elastic)
    assert validate.returncode == 0, (
        f"tofu validate failed:\nstdout: {validate.stdout}\nstderr: {validate.stderr}"
    )


def test_tofu_validate_passes_on_project_main_tf(tmp_path: Path):
    """``tofu validate`` exits 0 against the project-tier main.tf.

    Regression guard for v0.6.0's project-tier provisioning: the HCL must
    parse and its references must resolve before bootstrap will accept it.
    """
    dest = tmp_path / "project"
    shutil.copytree(_FIXTURE_ELASTIC, dest, symlinks=False, dirs_exist_ok=False)
    ctx = load_project_context(dest)
    rc = run_compile(ctx)
    assert rc == 0
    project_dir = dest / "infra" / "output" / "project"

    init = _run(
        ["tofu", "init", "-backend=false", "-input=false"],
        cwd=project_dir,
    )
    assert init.returncode == 0, (
        f"tofu init failed:\nstdout: {init.stdout}\nstderr: {init.stderr}"
    )

    validate = _run(["tofu", "validate"], cwd=project_dir)
    assert validate.returncode == 0, (
        f"tofu validate failed:\nstdout: {validate.stdout}\nstderr: {validate.stderr}"
    )


def test_tofu_validate_passes_on_elastic_stage(tmp_path: Path):
    """Same regression guard but for stage env."""
    dest = tmp_path / "project"
    shutil.copytree(_FIXTURE_ELASTIC, dest, symlinks=False, dirs_exist_ok=False)
    ctx = load_project_context(dest)
    rc = run_compile(ctx)
    assert rc == 0
    stage_dir = dest / "infra" / "output" / "stage"

    init = _run(
        ["tofu", "init", "-backend=false", "-input=false"],
        cwd=stage_dir,
    )
    assert init.returncode == 0, (
        f"tofu init failed:\nstdout: {init.stdout}\nstderr: {init.stderr}"
    )

    validate = _run(["tofu", "validate"], cwd=stage_dir)
    assert validate.returncode == 0, (
        f"tofu validate failed:\nstdout: {validate.stdout}\nstderr: {validate.stderr}"
    )
