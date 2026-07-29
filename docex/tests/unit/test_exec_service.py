"""Mod 099 — the per-codebase exec service (compose emission).

``migrate``, ``test`` and ``build`` are per-**codebase** operations that must
land in a container. Process expansion left them picking one process type's
container to ``compose exec`` into. The compiler now emits a container that
*is* the codebase — one ``<codebase>-exec`` block per codebase, in every fixed
env — and the three operations run one-off inside it.

This module covers the emission half. Resolution (``exec_service_key``) and
routing (the three call sites) are Pass 2's.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from docex.cicl.compile import run_compile
from docex.context import load_project_context


_FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
_FIXED = _FIXTURES / "sample_project"
_SCHEDULER_FIXED = _FIXTURES / "sample_project_scheduler_fixed"

# Planted on ONE process type. The whole point of the exec service is that
# this key cannot reach `migrate.sh` / `test.sh` / `build.sh`.
_WEB_ONLY_KEY = "WEB_ONLY_SETTING"
# Declared at the SERVICE level in the fixture — codebase-scoped, so it must
# reach the exec container.
_SERVICE_LEVEL_KEY = "DATABASE_HOST"

_WORKER = {
    "role": "worker",
    "command": ["python", "-m", "entrypoints.worker"],
    "networks": ["internal"],
    "depends_on": ["appdb"],
    "resources": {"cpu": 0.5, "memory": "1GB"},
}


def _multi_process_project(fixture: Path, dest: Path) -> Path:
    root = dest / "project"
    shutil.copytree(fixture, root, dirs_exist_ok=False)
    shutil.rmtree(root / "infra" / "output", ignore_errors=True)
    infra_path = root / "infra" / "infra.yml"
    doc = yaml.safe_load(infra_path.read_text())
    procs = doc["core_services"]["api"]["processes"]
    procs["web"]["env"] = {_WEB_ONLY_KEY: "yes"}
    procs["worker"] = dict(_WORKER)
    infra_path.write_text(yaml.safe_dump(doc, sort_keys=False))
    return root


@pytest.fixture(scope="module")
def fixed_root(tmp_path_factory) -> Path:
    root = _multi_process_project(_FIXED, tmp_path_factory.mktemp("exec_fixed"))
    assert run_compile(load_project_context(root)) == 0
    return root


@pytest.fixture(scope="module")
def scheduler_root(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("exec_sched") / "project"
    shutil.copytree(_SCHEDULER_FIXED, root, dirs_exist_ok=False)
    shutil.rmtree(root / "infra" / "output", ignore_errors=True)
    assert run_compile(load_project_context(root)) == 0
    return root


def _services(root: Path, env: str) -> dict:
    return yaml.safe_load(
        (root / "infra" / "output" / env / "docker-compose.yml").read_text()
    )["services"]


# ---------------------------------------------------------------------------
# 1-2 — one per codebase, inert until run.
# ---------------------------------------------------------------------------


def test_1_one_exec_service_per_codebase(fixed_root: Path):
    """Two process types, one codebase, exactly one exec service — keyed on
    the codebase, never on a compiled identity."""
    for env in ("dev", "test", "stage", "prod"):
        services = _services(fixed_root, env)
        execs = sorted(k for k in services if k.endswith("-exec"))
        assert execs == [f"sample-{env}-api-exec"], (env, sorted(services))


def test_2_exec_service_is_profile_gated_and_nothing_depends_on_it(
    fixed_root: Path,
):
    """`profiles: [exec]` keeps `compose up` from starting it; `compose run`
    implicitly enables the profile of the service it names. Nothing else may
    depend on it, or `up` would drag it in through the back door."""
    for env in ("dev", "test", "stage", "prod"):
        services = _services(fixed_root, env)
        key = f"sample-{env}-api-exec"
        assert services[key]["profiles"] == ["exec"]
        # It is the only profile-gated service; everything else starts on `up`.
        assert [k for k in services if "profiles" in services[k]] == [key]
        for other, block in services.items():
            if other == key:
                continue
            assert key not in (block.get("depends_on") or {}), other


# ---------------------------------------------------------------------------
# 3 — the headline: service-level env only.
# ---------------------------------------------------------------------------


def test_3_exec_env_is_codebase_scoped(fixed_root: Path):
    """The rule with teeth. `migrate.sh`, `test.sh` and `build.sh` may depend
    only on codebase-scoped env — so a process-level `env:` key is not merely
    discouraged in the exec container, it is *absent*.

    Guarded against a vacuous pass at both ends: the planted key must be
    present on its own process's block, and a service-level key must be
    present on the exec block.
    """
    for env in ("dev", "test", "stage", "prod"):
        services = _services(fixed_root, env)
        exec_env = services[f"sample-{env}-api-exec"]["environment"]
        assert _WEB_ONLY_KEY not in exec_env, env
        assert _SERVICE_LEVEL_KEY in exec_env, env
        assert exec_env["PROJECT_VERSION"] == "0.1.0"
        # The process that declared it does see it.
        assert _WEB_ONLY_KEY in services[f"sample-{env}-api-web"]["environment"]
        # ...and its sibling process, which did not declare it, does not.
        assert (
            _WEB_ONLY_KEY
            not in services[f"sample-{env}-api-worker"]["environment"]
        )


def test_3b_exec_telemetry_identity_is_codebase_scoped(fixed_root: Path):
    """Mod 102. The exec container is a per-CODEBASE artifact, so it reports
    `service.name=api` — not the compiled identity of whichever process type
    sorted first. `docex.process_type` is absent, and that absence is the
    signal that this is not a declared process type.

    Anti-vacuity guard in the same test: the sibling app containers DO carry
    the two-segment name and the process attribute. Without it, a change that
    dropped the OTel keys from every surface would pass.
    """
    for env in ("dev", "test", "stage", "prod"):
        services = _services(fixed_root, env)
        exec_env = services[f"sample-{env}-api-exec"]["environment"]
        assert exec_env["OTEL_SERVICE_NAME"] == "api", env
        attrs = exec_env["OTEL_RESOURCE_ATTRIBUTES"]
        assert "docex.core_service=api" in attrs, env
        assert "docex.process_type" not in attrs, (env, attrs)
        # The app containers beside it are process types, and say so.
        for proc in ("web", "worker"):
            app_env = services[f"sample-{env}-api-{proc}"]["environment"]
            assert app_env["OTEL_SERVICE_NAME"] == f"api-{proc}", (env, proc)
            app_attrs = app_env["OTEL_RESOURCE_ATTRIBUTES"]
            assert "docex.core_service=api" in app_attrs, (env, proc)
            assert f"docex.process_type={proc}" in app_attrs, (env, proc)


# ---------------------------------------------------------------------------
# 4-5 — image, build block, bind mounts.
# ---------------------------------------------------------------------------


def test_4_build_block_in_dev_and_test_only(fixed_root: Path):
    """dev/test build locally, stage/prod pull — exactly as the app services
    beside them do. The build block is byte-identical to theirs so Docker's
    layer cache makes the exec image free."""
    for env in ("dev", "test"):
        services = _services(fixed_root, env)
        block = services[f"sample-{env}-api-exec"]
        assert block["build"] == {
            "context": "./core/api",
            "dockerfile": "Dockerfile",
            "target": env,
        }
        assert block["build"] == services[f"sample-{env}-api-web"]["build"]
    for env in ("stage", "prod"):
        services = _services(fixed_root, env)
        assert "build" not in services[f"sample-{env}-api-exec"]


def test_4b_image_matches_the_app_services_in_every_env(fixed_root: Path):
    """One tag, one build. The image ref is codebase-keyed, so it is
    identical across every process type and the exec service alike."""
    for env in ("dev", "test", "stage", "prod"):
        services = _services(fixed_root, env)
        refs = {
            services[k]["image"]
            for k in (
                f"sample-{env}-api-exec",
                f"sample-{env}-api-web",
                f"sample-{env}-api-worker",
            )
        }
        assert len(refs) == 1, (env, refs)
        assert refs.pop() != ""


def test_5_bind_mounts_in_dev_only(fixed_root: Path):
    """Mirrors the app-service rule exactly: `dev` bind-mounts src/dist so
    `docex build` refreshes host-side `dist/`; `test` bakes artifacts into the
    image and stage/prod ship them from the registry."""
    dev = _services(fixed_root, "dev")[f"sample-dev-api-exec"]
    assert dev["volumes"] == [
        "./core/api/src:/service/src",
        "./core/api/dist:/service/dist",
    ]
    for env in ("test", "stage", "prod"):
        assert "volumes" not in _services(fixed_root, env)[f"sample-{env}-api-exec"]


# ---------------------------------------------------------------------------
# 6-7 — networks and depends_on unions.
# ---------------------------------------------------------------------------


def test_6_networks_are_the_non_web_union(fixed_root: Path):
    """The union of the codebase's non-`web` networks. Never `web`: the exec
    container is a one-off operations shell and is never publicly routed —
    even though `api.web` itself is."""
    for env in ("dev", "test", "stage", "prod"):
        services = _services(fixed_root, env)
        # Guard against a vacuous pass: the codebase really is on `web`.
        assert "web" in services[f"sample-{env}-api-web"]["networks"]
        assert services[f"sample-{env}-api-exec"]["networks"] == ["internal"]


def test_7_depends_on_is_long_form_and_health_gated(fixed_root: Path):
    """The union of the codebase's `depends_on`, rewritten by the existing
    second pass — which is why the exec pass runs before it rather than
    duplicating it. `service_healthy` is what makes `docex migrate dev`
    against a torn-down stack bring the database up instead of failing."""
    for env in ("dev", "test", "stage", "prod"):
        block = _services(fixed_root, env)[f"sample-{env}-api-exec"]
        assert block["depends_on"] == {
            f"sample-{env}-appdb": {"condition": "service_healthy"}
        }


def test_7b_exec_service_carries_the_project_label(fixed_root: Path):
    """Mod 051 stamps `docex.project` on every container docex emits on
    fixed, uniformly."""
    for env in ("dev", "test", "stage", "prod"):
        block = _services(fixed_root, env)[f"sample-{env}-api-exec"]
        assert block["labels"] == ["docex.project=sample"]


def test_7c_exec_service_sets_no_container_name_logging_or_command(
    fixed_root: Path,
):
    """`compose run` generates its own container name (a fixed one would be
    ignored or collide), the container is `--rm` so there is no post-hoc log
    to rotate, and the command is supplied at the call site."""
    for env in ("dev", "test", "stage", "prod"):
        block = _services(fixed_root, env)[f"sample-{env}-api-exec"]
        for key in ("container_name", "logging", "command", "restart"):
            assert key not in block, (env, key)


# ---------------------------------------------------------------------------
# 8 — the seam Mod 103 depends on.
# ---------------------------------------------------------------------------


def test_8_scheduler_only_codebase_gets_an_exec_service(scheduler_root: Path):
    """A scheduler-only codebase contributes no long-running container, and
    in `test` contributes nothing at all today (mod 073 drops the Ofelia
    trigger there) — so `docex test` needed a scheduler carve-out
    (`_run_scheduler_tests`) to have anything to run `test.sh` in.

    The exec pass groups compiled services by codebase *before* compose.py's
    `if svc.role == "scheduler": continue` skip, so a scheduler-only codebase
    gets its exec block regardless. **This is the seam Mod 103 removes the
    carve-out against** — pinned here so it cannot regress between the two
    mods.
    """
    dev = _services(scheduler_root, "dev")
    assert "sample-dev-nightly-cleanup-exec" in dev

    test = _services(scheduler_root, "test")
    key = "sample-test-nightly-cleanup-exec"
    assert key in test
    # In `test` it is the ONLY thing the codebase contributes.
    contributed = [
        k for k in test if "nightly" in k or "nightly_cleanup" in k
    ]
    assert contributed == [key], sorted(test)
    # It still builds against the codebase's own source tree and still gets
    # the codebase's readiness edge, both of which `docex test` needs.
    assert test[key]["build"]["context"] == "./core/nightly_cleanup"
    assert test[key]["depends_on"] == {
        "sample-test-appdb": {"condition": "service_healthy"}
    }


# ---------------------------------------------------------------------------
# 21 — every bundled fixture still compiles under the widened rule 5.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fixture",
    [
        "sample_project",
        "sample_project_elastic",
        "sample_project_scheduler_fixed",
        "sample_project_scheduler_elastic",
    ],
)
def test_21_all_fixtures_still_compile(fixture: str, tmp_path: Path):
    """Rule 5's domain grew to the compiler-emitted derivatives. A collision
    sweep was run at design time and found all four fixtures clean; this is
    what keeps them clean."""
    root = tmp_path / "project"
    shutil.copytree(_FIXTURES / fixture, root, dirs_exist_ok=False)
    shutil.rmtree(root / "infra" / "output", ignore_errors=True)
    assert run_compile(load_project_context(root)) == 0
