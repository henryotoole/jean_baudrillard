"""Integration test: the ec2_traefik project emits HCL that OpenTofu accepts.

Split out of the former tests/integration/test_compile.py (mod 139): that file's
other 60 tests were fast/hermetic and moved to tests/unit/test_compile.py. This is
the one genuine boundary crossing — it shells out to `tofu`.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from docex.cicl.compile import run_compile
from docex.context import load_project_context

_FIXTURE_ELASTIC = (
    Path(__file__).resolve().parent.parent / "fixtures" / "sample_project_elastic"
)


def _copy_fixture(src: Path, tmp_path: Path) -> Path:
    """Copy a fixture into a fresh temp dir and return its root."""
    dest = tmp_path / "project"
    shutil.copytree(src, dest, dirs_exist_ok=False)
    out = dest / "infra" / "output"
    if out.exists():
        shutil.rmtree(out)
    secrets = dest / "infra" / "secrets"
    if secrets.exists():
        shutil.rmtree(secrets)
    return dest


def _compile_elastic_with_reverse_proxy(tmp_path: Path, variant: str) -> Path:
    """Copy the elastic fixture, set `reverse_proxy: <variant>` on its
    infra.yml, compile, and return the project root."""
    root = _copy_fixture(_FIXTURE_ELASTIC, tmp_path)
    infra_yml = root / "infra" / "infra.yml"
    text = infra_yml.read_text()
    assert "reverse_proxy:" not in text
    text = text.replace(
        "foundation: elastic\n",
        f"foundation: elastic\nreverse_proxy: {variant}\n",
        1,
    )
    infra_yml.write_text(text)
    ctx = load_project_context(root)
    rc = run_compile(ctx)
    assert rc == 0
    return root


def _tofu_validate(tf_dir: Path) -> subprocess.CompletedProcess:
    """Run `tofu init -backend=false` + `tofu validate` in tf_dir.

    Returns the validate CompletedProcess (init failure is raised eagerly so
    a bad init doesn't masquerade as a validate pass)."""
    init = subprocess.run(
        ["tofu", "init", "-backend=false", "-input=false", "-no-color"],
        cwd=tf_dir, capture_output=True, text=True,
    )
    assert init.returncode == 0, f"tofu init failed:\n{init.stdout}\n{init.stderr}"
    return subprocess.run(
        ["tofu", "validate", "-no-color"],
        cwd=tf_dir, capture_output=True, text=True,
    )


@pytest.mark.integration
@pytest.mark.skipif(shutil.which("tofu") is None, reason="tofu not installed")
@pytest.mark.parametrize("variant", ["ec2_traefik_eip", "ec2_traefik_pip"])
def test_mod062_ec2_traefik_hcl_is_tofu_valid(tmp_path: Path, variant: str):
    """Every tier of an ec2_traefik project emits HCL that OpenTofu accepts.
    This is the coverage the mod-044 substring tests lacked — it parses the
    emitted HCL rather than string-matching it. Regression for mod 062."""
    root = _compile_elastic_with_reverse_proxy(tmp_path, variant)
    out = root / "infra" / "output"
    for tier in ("project/production", "stage", "prod"):
        res = _tofu_validate(out / tier)
        assert res.returncode == 0, (
            f"[{variant}] tofu validate failed for {tier}:\n"
            f"{res.stdout}\n{res.stderr}"
        )
