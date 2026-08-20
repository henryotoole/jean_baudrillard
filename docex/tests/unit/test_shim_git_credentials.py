"""Regression tests for the ``bin/docex`` shim's git-credential *content*.

Nothing tested the credential request the shim configures — which is exactly why
the git-creds bug (mod 136) survived three versions. The per-call passthrough
branch (``DOCEX_GIT_CREDENTIAL_PASSTHROUGH``) forced
``credential.useHttpPath=false``, stripping the repository path from the request;
a path-scoped host helper (a per-repo broker) then saw no repo and failed closed,
so ``docex merge`` died at its first fetch.

Two gates can strip the path. Gate 1 is the in-container git config the shim
injects into ``docker run`` — pinned here by capturing the recorded argv of a fake
``docker``. Gate 2 is the host-side ``git credential fill`` the responder drives —
pinned here by a config-isolated ``git credential fill`` against a recording helper
(no container, no network).
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


def _project(tmp_path: Path, record: Path) -> tuple[Path, dict]:
    """A minimal project dir (project.yml + https-origin git repo) and an env
    whose PATH front-loads a fake ``docker`` that records its argv to ``record``
    and exits 0."""
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
    docker.write_text(
        '#!/usr/bin/env bash\nprintf "%%s\\n" "$@" > %r\nexit 0\n' % str(record)
    )
    docker.chmod(0o755)
    env = dict(os.environ, PATH=f"{fakebin}:{os.environ['PATH']}")
    return proj, env


def test_shim_forces_usehttppath_true_in_passthrough(tmp_path: Path) -> None:
    """Gate-1 regression: in the passthrough branch the shim must inject
    ``credential.useHttpPath=true`` into the container — never ``false``, which
    stripped the repo path and broke path-scoped host helpers (mod 136)."""
    record = tmp_path / "argv.txt"
    proj, env = _project(tmp_path, record)
    env["DOCEX_GIT_CREDENTIAL_PASSTHROUGH"] = "1"
    subprocess.run(
        [str(_SHIM), "--version"], cwd=proj, env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    argv = record.read_text().splitlines()
    assert "GIT_CONFIG_VALUE_2=true" in argv
    assert "GIT_CONFIG_VALUE_2=false" not in argv
    assert "GIT_CONFIG_KEY_2=credential.useHttpPath" in argv


def _isolated_git_env() -> dict:
    """Isolate hard from the real machine's git config, or the machine's own
    helper could answer and print a real token."""
    return dict(
        os.environ,
        GIT_CONFIG_GLOBAL="/dev/null",
        GIT_CONFIG_SYSTEM="/dev/null",
        GIT_TERMINAL_PROMPT="0",
    )


def _recording_helper_repo(tmp_path: Path, request_dump: Path) -> Path:
    """A temp git repo whose credential.helper is a shell stand-in that dumps
    the request git hands it (on stdin) to ``request_dump``."""
    proj = tmp_path / "gitproj"
    proj.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=proj, check=True,
                   env=_isolated_git_env())
    helper = tmp_path / "helper.sh"
    helper.write_text('#!/usr/bin/env bash\ncat > %r\n' % str(request_dump))
    helper.chmod(0o755)
    subprocess.run(
        ["git", "config", "credential.helper", str(helper)],
        cwd=proj, check=True, env=_isolated_git_env(),
    )
    return proj


_REQUEST = "protocol=https\nhost=github.com\npath=owner/repo.git\n\n"


def test_git_credential_fill_preserves_path_with_usehttppath_true(
    tmp_path: Path,
) -> None:
    """Gate-2 behavior: the responder's ``-c credential.useHttpPath=true`` keeps
    the repo path through git's request normalization before the host helper sees
    it — no container involved."""
    dump = tmp_path / "request.txt"
    proj = _recording_helper_repo(tmp_path, dump)
    subprocess.run(
        ["git", "-C", str(proj), "-c", "credential.useHttpPath=true",
         "credential", "fill"],
        input=_REQUEST.encode(), stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, env=_isolated_git_env(),
    )
    assert "path=owner/repo.git" in dump.read_text()


def test_git_credential_fill_strips_path_by_default(tmp_path: Path) -> None:
    """Companion control: without the ``-c`` flag git's default
    (``useHttpPath=false``) drops the path — showing the flag is exactly what
    preserves it."""
    dump = tmp_path / "request.txt"
    proj = _recording_helper_repo(tmp_path, dump)
    subprocess.run(
        ["git", "-C", str(proj), "credential", "fill"],
        input=_REQUEST.encode(), stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, env=_isolated_git_env(),
    )
    assert "path=" not in dump.read_text()
