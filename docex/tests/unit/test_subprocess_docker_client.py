"""Unit tests for ``SubprocessDockerClient`` command-building paths.

These exercise only the pure-Python command assembly — they don't touch
subprocess. Integration coverage of the real docker invocations lives
under ``tests/integration/``.
"""

from __future__ import annotations

from pathlib import Path

from docex.docker.subprocess_client import SubprocessDockerClient


def _compose_file(project_root: Path) -> Path:
    return project_root / "infra" / "output" / "dev" / "docker-compose.yml"


def test_compose_base_does_not_pass_project_directory(tmp_path):
    # Under DooD, passing ``--project-directory`` would override
    # COMPOSE_PROJECT_DIR set by the shim and resolve to the
    # in-container ``/project`` on the host's docker daemon. We
    # rely on COMPOSE_PROJECT_DIR instead. Regression for v0.5.0,
    # which leaked an in-container path into spawned compose calls.
    client = SubprocessDockerClient()
    cmd = client._compose_base(_compose_file(tmp_path), env_file=None)
    assert "--project-directory" not in cmd


def test_compose_env_honors_existing_compose_project_dir(monkeypatch, tmp_path):
    # The bin/docex shim sets COMPOSE_PROJECT_DIR to the host project
    # root before launching docex. We must not overwrite it.
    monkeypatch.setenv("COMPOSE_PROJECT_DIR", "/host/project/path")
    client = SubprocessDockerClient()
    env = client._compose_env(_compose_file(tmp_path))
    assert env["COMPOSE_PROJECT_DIR"] == "/host/project/path"


def test_compose_env_falls_back_to_derived_root(monkeypatch, tmp_path):
    # Direct (non-shim) use: no COMPOSE_PROJECT_DIR in the env, so we
    # derive it from the compose file location.
    monkeypatch.delenv("COMPOSE_PROJECT_DIR", raising=False)
    client = SubprocessDockerClient()
    env = client._compose_env(_compose_file(tmp_path))
    assert env["COMPOSE_PROJECT_DIR"] == str(tmp_path)
