"""Unit tests for ``SubprocessDockerClient`` command-building paths.

These exercise only the pure-Python command assembly — they don't touch
subprocess. Integration coverage of the real docker invocations lives
under ``tests/integration/``.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from docex.docker.subprocess_client import SubprocessDockerClient


def _compose_file(project_root: Path) -> Path:
    return project_root / "infra" / "output" / "dev" / "docker-compose.yml"


def test_compose_base_passes_project_directory_from_explicit_override(tmp_path):
    """When a project_dir is passed explicitly (e.g. docex check's worktree
    override), it wins over the env var and the derived fallback."""
    client = SubprocessDockerClient()
    cmd = client._compose_base(
        _compose_file(tmp_path), env_file=None, project_dir=Path("/explicit/override"),
    )
    assert "--project-directory" in cmd
    assert cmd[cmd.index("--project-directory") + 1] == "/explicit/override"


def test_compose_base_derives_project_directory_from_compose_file(tmp_path):
    """With no explicit override, --project-directory is derived from the
    compose file's location: <root>/infra/output/<env>/docker-compose.yml.
    Under DooD the shim mirrors the host path inside the container, so
    this derived value is simultaneously a valid in-container path (for
    compose's client reads) and a valid host path (for the daemon's
    bind-mount resolution)."""
    client = SubprocessDockerClient()
    cmd = client._compose_base(_compose_file(tmp_path), env_file=None, project_dir=None)
    assert "--project-directory" in cmd
    assert cmd[cmd.index("--project-directory") + 1] == str(tmp_path)


# ---------------------------------------------------------------------------
# Mod 029: manifest_inspect
# ---------------------------------------------------------------------------


def test_manifest_inspect_returns_true_on_zero_exit(monkeypatch):
    client = SubprocessDockerClient()
    fake_run = MagicMock(return_value=MagicMock(returncode=0, stdout="", stderr=""))
    monkeypatch.setattr("docex.docker.subprocess_client.subprocess.run", fake_run)
    assert client.manifest_inspect("registry.example.com/proj/api:0.1.0") is True
    assert fake_run.called
    cmd = fake_run.call_args[0][0]
    assert cmd == ["docker", "manifest", "inspect", "registry.example.com/proj/api:0.1.0"]


def test_manifest_inspect_returns_false_on_nonzero_exit(monkeypatch):
    client = SubprocessDockerClient()
    fake_run = MagicMock(return_value=MagicMock(returncode=1, stdout="", stderr=""))
    monkeypatch.setattr("docex.docker.subprocess_client.subprocess.run", fake_run)
    assert client.manifest_inspect("registry.example.com/proj/api:0.1.0") is False


def test_manifest_inspect_returns_false_when_docker_missing(monkeypatch):
    client = SubprocessDockerClient()

    def boom(*_a, **_kw):
        raise FileNotFoundError("docker not on PATH")

    monkeypatch.setattr("docex.docker.subprocess_client.subprocess.run", boom)
    assert client.manifest_inspect("anything") is False
