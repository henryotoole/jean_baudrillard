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
    one-off migration container inherits the codebase's full environment
    (image, env vars, networks, env_file).

    Mod 099: the target is now the per-codebase EXEC service, not an app
    service. Fixed production migration therefore reads codebase-scoped env
    only — the half of the codebase-scoped-env rule a dev/test-only exec
    service would have left open."""
    root = _copy_fixture(tmp_path)
    ctx = load_project_context(root)
    run_compile(ctx)

    task = _find_migration_task(root, "stage", "api")
    assert "ansible.builtin.command" in task, task
    cmd = task["ansible.builtin.command"]["cmd"]
    # The compose service KEY is the global name (project-scoped),
    # not the short name. Using `api` here would fail at runtime with
    # `no such service: api` because the compose file declares
    # `sample-stage-api-web:` etc. The cmd must reference that global form.
    # (Per mod 030: docker policy is hyphen for data-plane resolvability.)
    # Mod 090: the migrate one-off passes `-p <dns_label>-<env>` so it joins
    # the SAME project-scoped Compose stack (else it can't reach the DB).
    assert cmd == "docker compose -p sample-stage run --rm sample-stage-api-exec /service/migrate.sh", cmd
    # The exec service is a real key in the env's compose file, or the
    # playbook fails at deploy time with "no such service".
    compose = yaml.safe_load(
        (root / "infra" / "output" / "stage" / "docker-compose.yml").read_text()
    )
    assert "sample-stage-api-exec" in compose["services"]


def test_playbook_compose_tasks_are_project_scoped(tmp_path: Path):
    """Mod 090: the release playbook's compose invocations pass an explicit,
    project-scoped `project_name` (`<dns_label>-<env>`) instead of letting
    Compose derive the unscoped `<env>` from the deploy-dir basename — else two
    fixed projects on one host collide. All three sites (pull, bring-up,
    migrate) must use the identical scoped name."""
    root = _copy_fixture(tmp_path)
    ctx = load_project_context(root)
    run_compile(ctx)

    for env in ("stage", "prod"):
        scoped = f"sample-{env}"
        pull = _find_task(root, env, "Pull all images")
        assert pull["community.docker.docker_compose_v2"]["project_name"] == scoped, pull
        up = _find_task(root, env, "Bring up the stack")
        assert up["community.docker.docker_compose_v2"]["project_name"] == scoped, up
        migrate = _find_migration_task(root, env, "api")
        assert f"docker compose -p {scoped} run --rm" in migrate["ansible.builtin.command"]["cmd"]


def _find_task(root: Path, env: str, name: str) -> dict:
    doc = _playbook_doc(root, env)
    for task in doc[0]["tasks"]:
        if task.get("name") == name:
            return task
    raise AssertionError(
        f"no task named {name!r} in {env} playbook; "
        f"got {[t.get('name') for t in doc[0]['tasks']]}"
    )


def test_playbook_renders_env_from_aggregate(tmp_path: Path):
    """Mod 081: the '.env' copy task sources the release aggregate handed in
    as the ``agg_env_file`` extra-var, not the raw operator secrets file."""
    root = _copy_fixture(tmp_path)
    ctx = load_project_context(root)
    run_compile(ctx)

    task = _find_task(root, "stage", "Render .env onto host")
    copy = task["ansible.builtin.copy"]
    assert copy["src"] == "{{ agg_env_file }}", copy
    assert copy["dest"].endswith("/.env"), copy
    # The old raw-secrets src must be gone.
    content = (root / "infra" / "output" / "stage" / "playbook.yml").read_text()
    assert "/../../secrets/" not in content, content


def test_playbook_has_tte_store_copy_task(tmp_path: Path):
    """Mod 081: a task renders the staged host-TTE superset onto the host at
    ``<deploy_root>/tte.env`` from the ``tte_store_file`` extra-var."""
    root = _copy_fixture(tmp_path)
    ctx = load_project_context(root)
    run_compile(ctx)

    task = _find_task(root, "stage", "Render TTE store onto host")
    copy = task["ansible.builtin.copy"]
    assert copy["src"] == "{{ tte_store_file }}", copy
    assert copy["dest"].endswith("/tte.env"), copy
    # Neither copy task carries the migrate tag (so `--tags migrate` skips
    # them and never renders the extra-var paths).
    assert "migrate" not in (task.get("tags") or [])
    env_task = _find_task(root, "stage", "Render .env onto host")
    assert "migrate" not in (env_task.get("tags") or [])


def test_playbook_env_render_tasks_guarded_for_dryrun(tmp_path: Path):
    """Mod 093: the two extra-var-dependent render tasks are gated on their
    variable being defined, so a dry-run (``--check`` with no extra-vars) skips
    them instead of failing on an undefined ``tte_store_file`` / ``agg_env_file``.
    The real release always supplies both, so the tasks run unchanged."""
    root = _copy_fixture(tmp_path)
    ctx = load_project_context(root)
    run_compile(ctx)

    tte = _find_task(root, "stage", "Render TTE store onto host")
    assert tte.get("when") == "tte_store_file is defined", tte
    env = _find_task(root, "stage", "Render .env onto host")
    assert env.get("when") == "agg_env_file is defined", env


def test_playbook_migration_does_not_use_auto_remove(tmp_path: Path):
    """Per mod 003: migration tasks must NOT set auto_remove: true,
    which masks the exit code on failure. The compose-run approach
    handles cleanup via --rm and captures the exit code naturally."""
    root = _copy_fixture(tmp_path)
    ctx = load_project_context(root)
    run_compile(ctx)

    content = (root / "infra" / "output" / "stage" / "playbook.yml").read_text()
    assert "auto_remove" not in content, content
