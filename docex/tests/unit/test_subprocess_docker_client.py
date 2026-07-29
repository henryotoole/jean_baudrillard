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
    """With no explicit override and no project.yml above the compose file,
    --project-directory falls back to the historical env-tier derivation:
    <root>/infra/output/<env>/docker-compose.yml → <root> (the "up 4")."""
    client = SubprocessDockerClient()
    cmd = client._compose_base(_compose_file(tmp_path), env_file=None, project_dir=None)
    assert "--project-directory" in cmd
    assert cmd[cmd.index("--project-directory") + 1] == str(tmp_path)


# ---------------------------------------------------------------------------
# Mod 053 (Cluster 1): --project-directory resolves to the true project
# root for BOTH env-tier and project-tier compose paths (the off-by-one
# fix), and --project-name is threaded explicitly.
# ---------------------------------------------------------------------------


def _make_project(tmp_path: Path) -> Path:
    """Create a project root with a project.yml so _resolve_project_dir's
    walk-up finds it (instead of the historical parent-count fallback)."""
    (tmp_path / "project.yml").write_text('name: sample\nversion: "0.0.1"\n')
    return tmp_path


def test_resolve_project_dir_env_tier_resolves_to_project_root(tmp_path):
    """An env-tier compose path (<root>/infra/output/<env>/...) resolves
    to <root> by walking up to project.yml."""
    root = _make_project(tmp_path)
    compose_file = root / "infra" / "output" / "dev" / "docker-compose.yml"
    client = SubprocessDockerClient()
    assert client._resolve_project_dir(compose_file, None) == str(root)


def test_resolve_project_dir_project_tier_resolves_to_project_root(tmp_path):
    """Regression for the off-by-one: a project-tier compose path
    (<root>/infra/output/project/<side>/...) nests one level deeper than
    env-tier. The old fixed "up 4" landed on <root>/infra (compose name
    'infra'); walking up to project.yml resolves to the true <root>."""
    root = _make_project(tmp_path)
    compose_file = (
        root / "infra" / "output" / "project" / "development" / "docker-compose.yml"
    )
    client = SubprocessDockerClient()
    resolved = client._resolve_project_dir(compose_file, None)
    assert resolved == str(root)
    # The off-by-one bug would have produced <root>/infra.
    assert resolved != str(root / "infra")


def test_compose_base_includes_project_name_when_passed(tmp_path):
    client = SubprocessDockerClient()
    cmd = client._compose_base(
        _compose_file(tmp_path), env_file=None, project_dir=Path("/x"),
        project_name="sample-dev",
    )
    assert "--project-name" in cmd
    assert cmd[cmd.index("--project-name") + 1] == "sample-dev"
    # --project-name must precede the subcommand (none here) and sit after
    # --project-directory per the v2 CLI; just assert it's before any 'up'.
    assert cmd.index("--project-name") > cmd.index("--project-directory")


def test_compose_base_omits_project_name_when_none(tmp_path):
    client = SubprocessDockerClient()
    cmd = client._compose_base(
        _compose_file(tmp_path), env_file=None, project_dir=Path("/x"),
        project_name=None,
    )
    assert "--project-name" not in cmd


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


# ---------------------------------------------------------------------------
# Mod 053: any_env_compose_up DNS-labels the project name so its targets
# match the explicit env-tier --project-name form (<dns_label>-<env>).
# ---------------------------------------------------------------------------


def test_any_env_compose_up_matches_dns_labeled_env_stack(monkeypatch):
    """An underscored project name (docex_smoke_elastic) must match a
    running stack named by the DNS-labeled env form
    (docex-smoke-elastic-dev), not the underscored form."""
    client = SubprocessDockerClient()
    import json
    payload = json.dumps([{"Name": "docex-smoke-elastic-dev", "Status": "running"}])
    fake_run = MagicMock(return_value=MagicMock(returncode=0, stdout=payload, stderr=""))
    monkeypatch.setattr("docex.docker.subprocess_client.subprocess.run", fake_run)
    assert client.any_env_compose_up("docex_smoke_elastic") is True


def test_any_env_compose_up_false_when_no_matching_stack(monkeypatch):
    client = SubprocessDockerClient()
    import json
    payload = json.dumps([{"Name": "some-other-project-dev", "Status": "running"}])
    fake_run = MagicMock(return_value=MagicMock(returncode=0, stdout=payload, stderr=""))
    monkeypatch.setattr("docex.docker.subprocess_client.subprocess.run", fake_run)
    assert client.any_env_compose_up("docex_smoke_elastic") is False


# ---------------------------------------------------------------------------
# Mod 099: `compose run` is non-interactive, like `compose exec`.
# ---------------------------------------------------------------------------


def test_compose_run_one_off_is_non_interactive(monkeypatch, tmp_path):
    """``run`` allocates a TTY by default where ``exec`` does not, and every
    docex call site is non-interactive (``docex check`` runs the whole test
    cycle unattended). Mod 099 routed migrate/test/build through ``run``, so
    the two must agree on ``-T``."""
    client = SubprocessDockerClient()
    fake_run = MagicMock(return_value=MagicMock(returncode=0, stdout="", stderr=""))
    monkeypatch.setattr("docex.docker.subprocess_client.subprocess.run", fake_run)

    client.compose_run_one_off(
        _compose_file(tmp_path), "sample-dev-api-exec", ["./migrate.sh"],
    )
    cmd = fake_run.call_args[0][0]
    # -T must sit between the flags and the service name.
    assert cmd[cmd.index("run"):] == [
        "run", "--rm", "-T", "sample-dev-api-exec", "./migrate.sh",
    ]
    assert cmd[cmd.index("-T") + 1] == "sample-dev-api-exec"
    assert cmd[-1] == "./migrate.sh"


def test_compose_run_one_off_env_flags_precede_the_service(monkeypatch, tmp_path):
    """``-e`` pairs are ``run`` options, so they must come before the service
    name; anything after it is the container's own argv."""
    client = SubprocessDockerClient()
    fake_run = MagicMock(return_value=MagicMock(returncode=0, stdout="", stderr=""))
    monkeypatch.setattr("docex.docker.subprocess_client.subprocess.run", fake_run)

    client.compose_run_one_off(
        _compose_file(tmp_path), "sample-dev-api-exec", ["./build.sh"],
        env={"FOO": "bar"},
    )
    cmd = fake_run.call_args[0][0]
    assert cmd[cmd.index("-e") + 1] == "FOO=bar"
    assert cmd.index("-e") < cmd.index("sample-dev-api-exec")
