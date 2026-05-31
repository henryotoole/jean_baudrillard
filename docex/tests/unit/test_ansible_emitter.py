"""Unit tests for the ansible emitter.

Covers the emitted ``ansible.cfg`` and ``playbook.yml`` for stage/prod
fixed envs — specifically the mod 003 fixes to the migration task and
the deprecated stdout_callback.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import yaml

from docex.cicl.compile import run_compile
from docex.context import load_project_context


_FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "sample_project"


def _copy_fixture(tmp_path: Path) -> Path:
    dest = tmp_path / "project"
    shutil.copytree(_FIXTURE, dest, dirs_exist_ok=False)
    out = dest / "infra" / "output"
    if out.exists():
        shutil.rmtree(out)
    return dest


def _playbook_doc(root: Path, env: str) -> list:
    path = root / "infra" / "output" / env / "playbook.yml"
    return yaml.safe_load(path.read_text())


def _find_migration_task(root: Path, env: str, svc_name: str) -> dict:
    """Locate the 'Run migrations for <svc>' task in the env's playbook."""
    doc = _playbook_doc(root, env)
    tasks = doc[0]["tasks"]
    needle = f"Run migrations for {svc_name}"
    for task in tasks:
        if task.get("name") == needle:
            return task
    raise AssertionError(
        f"no task named {needle!r} in {env} playbook; got {[t.get('name') for t in tasks]}"
    )


def test_ansible_cfg_uses_modern_result_format(tmp_path: Path):
    """Per mod 003: emitted ansible.cfg uses stdout_callback = default
    + result_format = yaml (the ansible-core-native equivalent), not the
    deprecated community.general yaml callback."""
    root = _copy_fixture(tmp_path)
    ctx = load_project_context(root)
    run_compile(ctx)

    content = (root / "infra" / "output" / "stage" / "ansible.cfg").read_text()
    assert "stdout_callback = default" in content, content
    assert "result_format = yaml" in content, content
    assert "stdout_callback = yaml" not in content, content


def test_playbook_migration_uses_compose_run(tmp_path: Path):
    """Per mod 003: migration tasks use `docker compose run --rm
    <service> /service/migrate.sh` via ansible.builtin.command, so the
    one-off migration container inherits the application service's full
    environment (image, env vars, networks, env_file)."""
    root = _copy_fixture(tmp_path)
    ctx = load_project_context(root)
    run_compile(ctx)

    task = _find_migration_task(root, "stage", "api")
    assert "ansible.builtin.command" in task, task
    cmd = task["ansible.builtin.command"]["cmd"]
    # The compose service KEY is the global name (project-scoped),
    # not the short name. Using `api` here would fail at runtime with
    # `no such service: api` because the compose file declares
    # `sample-stage-api:` etc. The cmd must reference that global form.
    assert cmd == "docker compose run --rm sample-stage-api /service/migrate.sh", cmd


def test_playbook_migration_does_not_use_auto_remove(tmp_path: Path):
    """Per mod 003: migration tasks must NOT set auto_remove: true,
    which masks the exit code on failure. The compose-run approach
    handles cleanup via --rm and captures the exit code naturally."""
    root = _copy_fixture(tmp_path)
    ctx = load_project_context(root)
    run_compile(ctx)

    content = (root / "infra" / "output" / "stage" / "playbook.yml").read_text()
    assert "auto_remove" not in content, content
