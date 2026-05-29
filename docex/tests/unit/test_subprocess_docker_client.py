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
