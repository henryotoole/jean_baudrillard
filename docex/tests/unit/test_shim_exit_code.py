"""Regression tests for the ``bin/docex`` shim's exit-code propagation.

The shim wraps ``docker run docex:<v> "$@"`` and MUST return docex's own exit
code unchanged — on both the fast path and the per-call git-credential
passthrough path (mod 068). A bug in the passthrough path's cleanup let the
EXIT trap re-fire on the explicit ``exit`` and run its ``kill`` a second time
against an already-dead responder; under ``set -e`` that failed ``kill`` became
the shell's exit status, so *every* command reported failure on success. These
tests pin the contract: the shim returns exactly what ``docker run`` returned,
with or without ``DOCEX_GIT_CREDENTIAL_PASSTHROUGH`` set.

They exercise the real shim as a subprocess with a fake ``docker`` on PATH, so
no image or daemon is needed.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

_SHIM = Path(__file__).resolve().parents[2] / "bin" / "docex"

pytestmark = pytest.mark.skipif(
    not all(shutil.which(t) for t in ("bash", "git", "python3")),
    reason="shim test needs bash, git, and python3 on PATH",
)


def _project(tmp_path: Path, fake_docker_rc: int) -> tuple[Path, dict]:
    """A minimal project dir (project.yml + https-origin git repo) and an env
    whose PATH front-loads a fake ``docker`` that exits ``fake_docker_rc``."""
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "project.yml").write_text(
        'name: shimtest\nversion: "0.0.1"\ndocex_version: "0.0.0-test"\n'
    )
    subprocess.run(["git", "init", "-q"], cwd=proj, check=True)
    # HTTPS origin is what arms the shim's credential-passthrough branch.
    subprocess.run(
        ["git", "remote", "add", "origin", "https://example.invalid/x.git"],
        cwd=proj, check=True,
    )
    fakebin = tmp_path / "fakebin"
    fakebin.mkdir()
    docker = fakebin / "docker"
    # Only ``docker run`` is invoked by the shim; exit with the scripted code.
    docker.write_text('#!/usr/bin/env bash\nexit %d\n' % fake_docker_rc)
    docker.chmod(0o755)
    env = dict(os.environ, PATH=f"{fakebin}:{os.environ['PATH']}")
    return proj, env


def _run_shim(proj: Path, env: dict) -> int:
    return subprocess.run(
        [str(_SHIM), "--version"], cwd=proj, env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    ).returncode


@pytest.mark.parametrize("rc", [0, 7])
def test_shim_propagates_exit_code_fast_path(tmp_path: Path, rc: int) -> None:
    """Without the passthrough env var, the shim ``exec``s docker run — its exit
    code must be docex's (the fake docker's)."""
    proj, env = _project(tmp_path, rc)
    env.pop("DOCEX_GIT_CREDENTIAL_PASSTHROUGH", None)
    assert _run_shim(proj, env) == rc


@pytest.mark.parametrize("rc", [0, 7])
def test_shim_propagates_exit_code_credential_path(tmp_path: Path, rc: int) -> None:
    """With ``DOCEX_GIT_CREDENTIAL_PASSTHROUGH`` set (the runner's config), the
    shim takes its credential branch. It must still return docex's exit code —
    in particular rc=0 on success (the mod-068 EXIT-trap double-kill regression)."""
    proj, env = _project(tmp_path, rc)
    env["DOCEX_GIT_CREDENTIAL_PASSTHROUGH"] = "1"
    assert _run_shim(proj, env) == rc
