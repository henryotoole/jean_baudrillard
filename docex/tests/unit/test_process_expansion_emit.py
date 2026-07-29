"""Mod 096 — process nesting: the emit half.

The headline assertion of the mod: **one** core service with **three**
process types (``web`` / ``worker`` / ``nightly_cleanup``) expands into three
compiled services on both foundations, while everything that is keyed on the
*codebase* — the image, the build context, the ECR repo, the migrate task
definition — stays singular.

The three-process project is built once here rather than spread across the
existing emitter modules, so the fixture and the assertions that depend on
its exact shape stay in one place. Schema and validation coverage lives in
``test_process_nesting.py``.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest
import yaml

from docex.cicl.compile import run_compile
from docex.context import load_project_context
from docex.errors import TransferTableError


_FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
_FIXED = _FIXTURES / "sample_project"
_ELASTIC = _FIXTURES / "sample_project_elastic"


# A process-level `env:` key on the schema carrier (`web`, the lowest-sorted
# non-scheduler process). It must appear in the app container's env and NOT
# in the migrate task definition's — that is the codebase-scoped-env rule.
_WEB_ONLY_KEY = "WEB_ONLY_SETTING"

# `depends_on: [appdb]` on EVERY process type: the fixture declares its
# DATABASE_* magic refs at the SERVICE level, and a service-level ref obliges
# every process type of that codebase to carry the readiness edge (rule 7,
# cicl.md § Consumes Relationships § Three clarifications).
_WORKER = {
    "role": "worker",
    "command": ["python", "-m", "entrypoints.worker"],
    "networks": ["internal"],
    "depends_on": ["appdb"],
    "resources": {"cpu": 0.5, "memory": "1GB", "disk": "25GB"},
}
_NIGHTLY = {
    "role": "scheduler",
    "schedule": "0 3 * * *",
    "command": ["python", "-m", "jobs.cleanup"],
    "networks": ["internal"],
    "depends_on": ["appdb"],
    "resources": {"cpu": 0.25, "memory": "512MB", "disk": "25GB"},
}


def _three_process_project(fixture: Path, tmp_path: Path) -> Path:
    root = tmp_path / "project"
    shutil.copytree(fixture, root, dirs_exist_ok=False)
    shutil.rmtree(root / "infra" / "output", ignore_errors=True)

    infra_path = root / "infra" / "infra.yml"
    doc = yaml.safe_load(infra_path.read_text())
    procs = doc["core_services"]["api"]["processes"]
    procs["web"]["env"] = {_WEB_ONLY_KEY: "yes"}
    procs["worker"] = dict(_WORKER)
    procs["nightly_cleanup"] = dict(_NIGHTLY)
    infra_path.write_text(yaml.safe_dump(doc, sort_keys=False))
    return root


@pytest.fixture(scope="module")
def fixed_root(tmp_path_factory) -> Path:
    root = _three_process_project(_FIXED, tmp_path_factory.mktemp("fixed"))
    assert run_compile(load_project_context(root)) == 0
    return root


@pytest.fixture(scope="module")
def elastic_root(tmp_path_factory) -> Path:
    root = _three_process_project(_ELASTIC, tmp_path_factory.mktemp("elastic"))
    assert run_compile(load_project_context(root)) == 0
    return root


def _compose(root: Path, env: str) -> dict:
    return yaml.safe_load(
        (root / "infra" / "output" / env / "docker-compose.yml").read_text()
    )


def _hcl(root: Path, env: str) -> str:
    return (root / "infra" / "output" / env / "main.tf").read_text()


def _resources(hcl: str, kind: str) -> list[str]:
    return re.findall(rf'^resource "{kind}" "([^"]+)" \{{', hcl, flags=re.M)


def _slice(hcl: str, kind: str, name: str) -> str:
    marker = f'resource "{kind}" "{name}" {{'
    idx = hcl.index(marker)
    rest = hcl[idx:]
    return rest[: rest.index("\n}\n") + 2]


# ---------------------------------------------------------------------------
# 26-30 — fixed foundation.
# ---------------------------------------------------------------------------


def test_26_fixed_emits_one_service_per_long_running_process(fixed_root: Path):
    services = _compose(fixed_root, "dev")["services"]
    assert "sample-dev-api-web" in services
    assert "sample-dev-api-worker" in services
    # A scheduler runs nothing continuously — no long-running service block,
    # just the paired ofelia container that fires it.
    assert "sample-dev-api-nightly_cleanup" not in services
    assert "sample-dev-api-nightly_cleanup-scheduler" in services


def test_27_fixed_emits_one_sidecar_per_long_running_process(fixed_root: Path):
    services = _compose(fixed_root, "dev")["services"]
    sidecars = sorted(k for k in services if k.endswith("-otelcol"))
    assert sidecars == ["sample-dev-api-web-otelcol", "sample-dev-api-worker-otelcol"]


def test_28_fixed_all_processes_share_one_image(fixed_root: Path):
    services = _compose(fixed_root, "dev")["services"]
    core = [services[k] for k in ("sample-dev-api-web", "sample-dev-api-worker")]
    assert {b["image"] for b in core} == {"sample/api:0.1.0"}
    # The ofelia job image is the same one — the scheduler runs the same
    # artifact through a different command.
    ini = _compose(fixed_root, "dev")["configs"]["ofelia_api-nightly_cleanup"]["content"]
    assert "image = sample/api:0.1.0" in ini


def test_29_fixed_one_build_context_and_codebase_bind_mounts(fixed_root: Path):
    services = _compose(fixed_root, "dev")["services"]
    contexts = [
        b["build"]["context"] for b in services.values() if isinstance(b.get("build"), dict)
    ]
    assert contexts.count("./core/api") == 2  # web + worker, one codebase
    assert set(contexts) == {"./core/api"}
    for key in ("sample-dev-api-web", "sample-dev-api-worker"):
        vols = services[key]["volumes"]
        assert "./core/api/src:/service/src" in vols
        assert "./core/api/dist:/service/dist" in vols


def test_30_fixed_core_processes_publish_no_host_ports(fixed_root: Path):
    """Ruling 5: a core process type never publishes. Two codebases' workers
    sharing a health port would otherwise collide in `dev` on day one."""
    services = _compose(fixed_root, "dev")["services"]
    for key in ("sample-dev-api-web", "sample-dev-api-worker"):
        assert "ports" not in services[key]


# ---------------------------------------------------------------------------
# 31-36 — elastic foundation.
# ---------------------------------------------------------------------------


def test_31_elastic_resource_counts(elastic_root: Path):
    hcl = _hcl(elastic_root, "stage")
    tds = _resources(hcl, "aws_ecs_task_definition")
    # Exactly one per process type, plus the single codebase-keyed migrate.
    assert sorted(n for n in tds if not n.endswith("_migrate")) == [
        "api-nightly_cleanup", "api-web", "api-worker",
    ]
    # No ECS service for the scheduler; no target group for anything but web.
    assert sorted(_resources(hcl, "aws_ecs_service")) == ["api-web", "api-worker"]
    assert _resources(hcl, "aws_lb_target_group") == ["api-web"]


def test_32_elastic_all_task_defs_reference_one_image(elastic_root: Path):
    hcl = _hcl(elastic_root, "stage")
    refs = set()
    for name in ("api-web", "api-worker", "api-nightly_cleanup"):
        body = _slice(hcl, "aws_ecs_task_definition", name)
        refs.update(re.findall(r"image = \"([^\"]+)\"", body))
    # The sidecar image is in there too; the app image must be singular.
    app_refs = {r for r in refs if "ecr_repository" in r}
    assert len(app_refs) == 1
    assert "ecr_repository_api_url" in app_refs.pop()


def test_33_elastic_exactly_one_migrate_task_definition(elastic_root: Path):
    hcl = _hcl(elastic_root, "stage")
    migrates = [n for n in _resources(hcl, "aws_ecs_task_definition") if "migrate" in n]
    assert migrates == ["api_migrate"]
    body = _slice(hcl, "aws_ecs_task_definition", "api_migrate")
    # Codebase-keyed: no process segment.
    assert 'family                   = "sample-stage-api-migrate"' in body


def test_34_elastic_migrate_env_is_codebase_scoped(elastic_root: Path):
    """`migrate.sh` may depend only on codebase-scoped env, so the migrate
    task definition consumes `service_env` — the service-level `env:` block —
    and never a process type's overlay."""
    hcl = _hcl(elastic_root, "stage")
    body = _slice(hcl, "aws_ecs_task_definition", "api_migrate")
    names = set(re.findall(r'name = "([A-Z_]+)"', body))
    assert "DATABASE_HOST" in names       # service-level env
    assert "PROJECT_VERSION" in names     # doctrine-injected
    assert _WEB_ONLY_KEY not in names     # process-level overlay — excluded
    # Guard against a vacuous pass: the carrier's own container DOES have it.
    app = _slice(hcl, "aws_ecs_task_definition", "api-web")
    assert _WEB_ONLY_KEY in app


def test_35_elastic_one_ecr_repo_per_codebase(elastic_root: Path):
    project_tf = (
        elastic_root / "infra" / "output" / "project" / "production" / "main.tf"
    ).read_text()
    assert _resources(project_tf, "aws_ecr_repository") == ["api"]
    assert project_tf.count('output "ecr_repository_api_url"') == 1


def test_36_elastic_envinfra_tags_split_service_and_process(elastic_root: Path):
    hcl = _hcl(elastic_root, "stage")
    svc = _slice(hcl, "aws_ecs_service", "api-web")
    assert 'service = "api"' in svc
    assert 'process = "web"' in svc
    assert 'Name = "sample_stage_api_web"' in svc
    # A backing service has no process dimension, so the key is omitted
    # entirely and its tag block is byte-identical to its pre-expansion form.
    db = _slice(hcl, "aws_db_instance", "appdb")
    assert "process =" not in db
    assert 'Name = "sample_stage_appdb"' in db


# ---------------------------------------------------------------------------
# 37-40 — cross-cutting.
# ---------------------------------------------------------------------------


def test_37_otel_service_name_is_per_process(fixed_root: Path):
    services = _compose(fixed_root, "dev")["services"]
    assert services["sample-dev-api-web"]["environment"]["OTEL_SERVICE_NAME"] == "api-web"
    assert (
        services["sample-dev-api-worker"]["environment"]["OTEL_SERVICE_NAME"]
        == "api-worker"
    )


def test_38_web_hostnames_are_per_process(fixed_root: Path):
    from docex.cicl.compile import web_hostnames_for_env

    ctx = load_project_context(fixed_root)
    hosts = web_hostnames_for_env(
        ctx.infra, ctx.project.name, "dev", ctx.transfer_tables.naming_policies
    )
    assert "api-web.dev.sample.example.com" in hosts
    assert not any(h.startswith("api-worker.") for h in hosts)
    assert not any(h.startswith("api-nightly_cleanup.") for h in hosts)


def test_39_migration_task_family_matches_codebase_global_name(elastic_root: Path):
    """`orchestrate/migrate.py` reconstructs the family independently of the
    compiler. Assert against a real compile rather than a hand-written
    string, so the two cannot drift apart silently."""
    from docex.cicl.compile import compile_env
    from docex.orchestrate.migrate import _migration_task_family

    ctx = load_project_context(elastic_root)
    compiled = compile_env(
        ctx.infra, ctx.transfer_tables, env="stage",
        project_name=ctx.project.name, project_version=ctx.project.version,
    )
    carrier = next(
        s for s in compiled.services.values() if s.is_core and s.schema_owned_by_db
    )
    assert _migration_task_family(
        ctx, project=ctx.project.name, env="stage", svc="api"
    ) == f"{carrier.codebase_global_name}-migrate"


def test_40_ansible_emits_one_migration_task_per_codebase(fixed_root: Path):
    """Regression for the silent failure Mod 096 fixed: `emit_ansible` used
    to compare `schema_owned_by` (a codebase key) against the compiled
    identity, which never matched — the playbook emitted ZERO migrate tasks
    and still reported success."""
    playbook = yaml.safe_load(
        (fixed_root / "infra" / "output" / "stage" / "playbook.yml").read_text()
    )
    names = [t.get("name") for t in playbook[0]["tasks"]]
    migrations = [n for n in names if n and n.startswith("Run migrations for")]
    assert migrations == ["Run migrations for api-web"]


# ---------------------------------------------------------------------------
# 25 — the `iam` policy's overflow is a clean compile error.
# ---------------------------------------------------------------------------


def test_25_iam_overflow_fails_compile_with_the_policys_message(tmp_path: Path):
    """`iam` is `max_len: 64, overflow: error`, and the scheduler role name
    is `apply_policy(f"{global_name}_scheduler", iam)`. With a fourth
    segment that can now hard-fail at compile — the doctrine's stated
    preference over silent truncation."""
    root = _three_process_project(_ELASTIC, tmp_path)
    project_yml = root / "project.yml"
    project_yml.write_text(
        project_yml.read_text().replace(
            "name: sample", "name: tactical_lifecycle_testbed_alpha", 1
        )
    )
    infra_path = root / "infra" / "infra.yml"
    doc = yaml.safe_load(infra_path.read_text())
    doc["core_services"]["api"]["processes"]["nightly_reconciliation_sweep"] = (
        doc["core_services"]["api"]["processes"].pop("nightly_cleanup")
    )
    infra_path.write_text(yaml.safe_dump(doc, sort_keys=False))

    with pytest.raises(TransferTableError) as exc:
        run_compile(load_project_context(root))
    msg = str(exc.value)
    assert "policy 'iam' max_len 64" in msg
    assert "nightly_reconciliation_sweep_scheduler" in msg
