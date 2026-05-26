"""Unit tests for the compose emitter.

Specifically covers Phase 2's bind-mount decoration: dev compose must
get per-core-service ``volumes:`` bind mounts for ``src/`` and ``dist/``,
while test/stage/prod compose must NOT.
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


def _compose_services(root: Path, env: str) -> dict:
    path = root / "infra" / "output" / env / "docker-compose.yml"
    doc = yaml.safe_load(path.read_text())
    return doc["services"]


def _find_core_service_block(services: dict, simple_name: str) -> dict:
    """Find a service by suffix match (services keys are project-scoped)."""
    for key, block in services.items():
        if key.endswith(simple_name):
            return block
    raise AssertionError(
        f"no service ending with {simple_name!r} in {sorted(services)}"
    )


def test_dev_compose_has_core_bind_mounts(tmp_path: Path):
    root = _copy_fixture(tmp_path)
    ctx = load_project_context(root)
    run_compile(ctx)

    services = _compose_services(root, "dev")
    api = _find_core_service_block(services, "api")
    volumes = api.get("volumes") or []
    # The two doctrinal bind mounts must both be present.
    assert "./core/api/src:/service/src" in volumes, volumes
    assert "./core/api/dist:/service/dist" in volumes, volumes


def test_non_dev_compose_has_no_core_bind_mounts(tmp_path: Path):
    """Test/stage/prod must not get host bind mounts on core services."""
    root = _copy_fixture(tmp_path)
    ctx = load_project_context(root)
    run_compile(ctx)

    for env in ("test", "stage", "prod"):
        services = _compose_services(root, env)
        api = _find_core_service_block(services, "api")
        volumes = api.get("volumes") or []
        for v in volumes:
            assert "/service/src" not in v, (
                f"{env} compose has src bind mount on api: {v!r}"
            )
            assert "/service/dist" not in v, (
                f"{env} compose has dist bind mount on api: {v!r}"
            )


def test_disk_translates_to_docker_tmpfs_size(tmp_path: Path):
    """Phase 3 Step 1: ``disk: 20GB`` must produce ``/tmp:size=20g``.

    docker's tmpfs ``size=`` option does not accept the ``B``-suffix
    form (``GB``/``MB``). The compose emitter has to lower-case the
    suffix and drop the trailing ``B``.
    """
    root = _copy_fixture(tmp_path)
    ctx = load_project_context(root)
    run_compile(ctx)

    for env in ("dev", "test"):
        services = _compose_services(root, env)
        api = _find_core_service_block(services, "api")
        tmpfs = api.get("tmpfs") or []
        assert tmpfs == ["/tmp:size=20g"], (env, tmpfs)


def test_backing_service_never_gets_core_bind_mounts(tmp_path: Path):
    """Even on dev, backing (non-core) services must not get core bind mounts."""
    root = _copy_fixture(tmp_path)
    ctx = load_project_context(root)
    run_compile(ctx)

    services = _compose_services(root, "dev")
    database = _find_core_service_block(services, "database")
    volumes = database.get("volumes") or []
    for v in volumes:
        assert "/service/src" not in v, v
        assert "/service/dist" not in v, v
