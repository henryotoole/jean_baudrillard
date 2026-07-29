"""Mod 099 — resolving a codebase to its exec service, and the deletions.

The emission half lives in ``test_exec_service.py``; the routing half is
asserted in the four ``test_orchestrate_*`` suites. This module covers the
resolver itself (``exec_service_key``) and pins the two functions Mod 099
deleted so nothing quietly grows a fourth consumer.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from docex.cicl.compile import run_compile
from docex.context import load_project_context
from docex.errors import InfraFileError
from docex.orchestrate._common import exec_service_key


_FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
_FIXED = _FIXTURES / "sample_project"

# A second codebase whose *name* collides with the first codebase's process
# type. This is the shape the deleted suffix scan got wrong.
_WEB_CODEBASE = {
    "processes": {
        "web": {
            "role": "web",
            "command": ["python", "/service/dist/root.py"],
            "port": 8081,
            "networks": ["web", "internal"],
            "resources": {"cpu": 0.5, "memory": "1GB"},
        }
    }
}


@pytest.fixture(scope="module")
def colliding_root(tmp_path_factory) -> Path:
    """``sample`` with codebases ``api`` (process ``web``) and ``web``
    (process ``web``) side by side."""
    root = tmp_path_factory.mktemp("exec_collide") / "project"
    shutil.copytree(_FIXED, root, dirs_exist_ok=False)
    shutil.rmtree(root / "infra" / "output", ignore_errors=True)
    infra_path = root / "infra" / "infra.yml"
    doc = yaml.safe_load(infra_path.read_text())
    doc["core_services"]["web"] = {
        k: (dict(v) if isinstance(v, dict) else v)
        for k, v in _WEB_CODEBASE.items()
    }
    infra_path.write_text(yaml.safe_dump(doc, sort_keys=False))
    assert run_compile(load_project_context(root)) == 0
    return root


def _ctx(root: Path):
    return load_project_context(root)


# ---------------------------------------------------------------------------
# 9 — the wrong-container bug.
# ---------------------------------------------------------------------------


def test_9_codebase_named_web_resolves_to_its_own_exec_service(
    colliding_root: Path,
):
    """**The live bug this mod retires.** The deleted resolver scanned the
    emitted compose file for a key ending in ``-<codebase>-<primary process>``.
    For a codebase literally named ``web`` that suffix is ``web-web``, but the
    scan also accepted a key merely *ending* in the codebase name — so
    ``sample-dev-api-web``, a **different codebase's** container, matched
    first and won, silently, with no error. `migrate`/`test`/`build` for
    codebase ``web`` then ran inside codebase ``api``.

    ``exec_service_key`` constructs the key from the codebase and verifies it
    exists, so there is no scan left to mis-resolve.
    """
    ctx = _ctx(colliding_root)
    services = yaml.safe_load(
        (colliding_root / "infra" / "output" / "dev" / "docker-compose.yml")
        .read_text()
    )["services"]
    # Guard against a vacuous pass: the container the old scan would have
    # picked really is in the file, and really is a different codebase's.
    assert "sample-dev-api-web" in services
    assert "sample-dev-web-web" in services

    assert exec_service_key(ctx, "dev", "web") == "sample-dev-web-exec"
    assert exec_service_key(ctx, "dev", "api") == "sample-dev-api-exec"
    # And no codebase resolves onto another codebase's app container.
    for codebase in ("api", "web"):
        assert exec_service_key(ctx, "dev", codebase) not in (
            "sample-dev-api-web", "sample-dev-web-web",
        )


def test_9b_exec_key_is_derived_not_scanned(colliding_root: Path):
    """The key is well-defined even with no compiled output on disk — the
    verification step is a *check*, not the derivation. (Deleting the compose
    file is how we prove the scan is really gone.)"""
    ctx = _ctx(colliding_root)
    for env in ("dev", "test", "stage", "prod"):
        compose = ctx.project_root / "infra" / "output" / env / "docker-compose.yml"
        body = compose.read_text()
        compose.unlink()
        try:
            assert exec_service_key(ctx, env, "web") == f"sample-{env}-web-exec"
        finally:
            compose.write_text(body)


# ---------------------------------------------------------------------------
# 10 — it raises rather than guessing.
# ---------------------------------------------------------------------------


def test_10_missing_exec_service_raises_and_lists_the_near_misses(
    colliding_root: Path, tmp_path: Path,
):
    """Never a silent fallback to a bare name. The message must list the
    ``-exec`` keys that *are* present: that is what turns a stale compile or a
    naming-policy mismatch from a mystery into a diagnosis."""
    root = tmp_path / "stale"
    shutil.copytree(colliding_root, root, dirs_exist_ok=False)
    compose = root / "infra" / "output" / "dev" / "docker-compose.yml"
    doc = yaml.safe_load(compose.read_text())
    del doc["services"]["sample-dev-web-exec"]
    compose.write_text(yaml.safe_dump(doc, sort_keys=False))

    with pytest.raises(InfraFileError) as excinfo:
        exec_service_key(_ctx(root), "dev", "web")
    msg = str(excinfo.value)
    assert "sample-dev-web-exec" in msg
    # The near miss is named, so the operator can see what DID get emitted.
    assert "sample-dev-api-exec" in msg
    assert "docex compile" in msg


def test_10b_unknown_codebase_raises(colliding_root: Path):
    """A codebase that isn't in infra.yml has no derivable key at all."""
    with pytest.raises(InfraFileError):
        exec_service_key(_ctx(colliding_root), "dev", "nosuch")


# ---------------------------------------------------------------------------
# 22 — deletion pins.
# ---------------------------------------------------------------------------

# WHY assembled from parts rather than written out: Mod 099's completion gate
# is `grep -rn "primary_"+"process\|compose_"+"service_key" src/ tests/`
# returning NOTHING — the two names must survive nowhere in the tree, not even
# as the subject of a test. Splitting them keeps that gate meaningful while
# still pinning the deletion.
_DELETED = [
    ("docex.cicl.model", "primary_" + "process"),
    ("docex.orchestrate._common", "compose_" + "service_key"),
]


@pytest.mark.parametrize("module_name, attr", _DELETED)
def test_22_deleted_bridges_are_gone(module_name: str, attr: str):
    """The two bridges Mod 096 planted and Mod 099 pulled.

    1. ``cicl/model.py``'s "pick one process type to stand in for the
       codebase" helper. Both of its consumers are gone — migration sizing is
       the per-dimension max across the codebase's process types, and
       container selection is the exec service.
    2. ``orchestrate/_common.py``'s suffix-scanning codebase → app-container
       resolver, replaced by :func:`exec_service_key`.

    Importing either must fail, so nothing quietly grows a fourth consumer.
    """
    import importlib

    module = importlib.import_module(module_name)
    assert not hasattr(module, attr)
    with pytest.raises(ImportError):
        exec(f"from {module_name} import {attr}")


# ---------------------------------------------------------------------------
# Mod 103 — deletion pins, co-located with Mod 099's above.
# ---------------------------------------------------------------------------

_DELETED_103 = [
    ("docex.orchestrate.test", "_run_scheduler_tests"),
    ("docex.orchestrate._common", "scheduler_services"),
]


@pytest.mark.parametrize("module_name, attr", _DELETED_103)
def test_mod_074_and_the_scheduler_test_carveout_are_gone(
    module_name: str, attr: str
):
    """The two functions Mod 103 deleted, once ``scheduler`` became a process
    type rather than its own species of service.

    1. ``orchestrate/test.py::_run_scheduler_tests`` — the ``docex test``
       carve-out that built a scheduler-only codebase's Dockerfile ``test``
       stage directly and ran ``test.sh`` outside compose. Mod 099's exec
       service is emitted for every codebase, so it had nothing left to solve.
    2. ``orchestrate/_common.py::scheduler_services`` — "codebases with AT
       LEAST ONE scheduler process type", whose sole consumer was mod 074's
       self-contained job-image build. That build is gone (its ``prod``-stage
       image on the codebase's dev tag is what broke ``docex build dev``), and
       what replaced it is scoped to ``scheduler_only_services``.

    Importing either must fail, so neither grows a quiet second consumer.
    """
    import importlib

    module = importlib.import_module(module_name)
    assert not hasattr(module, attr)
    with pytest.raises(ImportError):
        exec(f"from {module_name} import {attr}")
