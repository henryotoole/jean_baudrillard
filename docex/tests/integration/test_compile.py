"""Integration tests for ``docex compile`` against the sample fixture.

We compile into a temp directory rather than the fixture in place to
keep tests hermetic. The fixture is copied to ``tmp_path``; outputs
are inspected there.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from docex.cicl.compile import run_compile
from docex.context import load_project_context
from docex.errors import ValidationError


_FIXTURE_FIXED = Path(__file__).resolve().parent.parent / "fixtures" / "sample_project"
_FIXTURE_ELASTIC = (
    Path(__file__).resolve().parent.parent / "fixtures" / "sample_project_elastic"
)


def _copy_fixture(src: Path, tmp_path: Path) -> Path:
    """Copy a fixture into a fresh temp dir and return its root."""
    dest = tmp_path / "project"
    shutil.copytree(src, dest, dirs_exist_ok=False)
    # Remove any pre-existing output so we can assert it gets created.
    out = dest / "infra" / "output"
    if out.exists():
        shutil.rmtree(out)
    secrets = dest / "infra" / "secrets"
    if secrets.exists():
        shutil.rmtree(secrets)
    return dest


def test_compile_fixed_produces_all_expected_files(tmp_path: Path):
    root = _copy_fixture(_FIXTURE_FIXED, tmp_path)
    ctx = load_project_context(root)
    exit_code = run_compile(ctx)
    assert exit_code == 0

    output = root / "infra" / "output"
    assert (output / "dev" / "docker-compose.yml").is_file()
    assert (output / "test" / "docker-compose.yml").is_file()
    for env in ("stage", "prod"):
        for fname in ("docker-compose.yml", "playbook.yml", "inventory.yml", "ansible.cfg"):
            assert (output / env / fname).is_file(), f"{env}/{fname} missing"

    # example.env is always emitted.
    assert (root / "infra" / "secrets" / "example.env").is_file()


def test_compile_elastic_produces_main_tf(tmp_path: Path):
    root = _copy_fixture(_FIXTURE_ELASTIC, tmp_path)
    ctx = load_project_context(root)
    exit_code = run_compile(ctx)
    assert exit_code == 0

    output = root / "infra" / "output"
    # dev/test stay fixed -> compose.
    assert (output / "dev" / "docker-compose.yml").is_file()
    assert (output / "test" / "docker-compose.yml").is_file()
    # stage/prod elastic -> main.tf.
    assert (output / "stage" / "main.tf").is_file()
    assert (output / "prod" / "main.tf").is_file()
    # No compose for stage/prod on elastic.
    assert not (output / "prod" / "docker-compose.yml").is_file()


def test_compile_is_deterministic(tmp_path: Path):
    """Compiling twice produces byte-identical output."""
    root1 = _copy_fixture(_FIXTURE_FIXED, tmp_path / "first")
    ctx1 = load_project_context(root1)
    run_compile(ctx1)
    root2 = _copy_fixture(_FIXTURE_FIXED, tmp_path / "second")
    ctx2 = load_project_context(root2)
    run_compile(ctx2)

    for relpath in [
        "infra/output/dev/docker-compose.yml",
        "infra/output/test/docker-compose.yml",
        "infra/output/stage/docker-compose.yml",
        "infra/output/stage/playbook.yml",
        "infra/output/prod/docker-compose.yml",
        "infra/secrets/example.env",
    ]:
        a = (root1 / relpath).read_bytes()
        b = (root2 / relpath).read_bytes()
        assert a == b, f"{relpath} differs between runs"


def test_compile_resolves_magic_ref_in_env(tmp_path: Path):
    """The api service's DATABASE_* magic refs resolve to the postgres
    engine's discrete parts (parts-only model — no composed url)."""
    root = _copy_fixture(_FIXTURE_FIXED, tmp_path)
    ctx = load_project_context(root)
    run_compile(ctx)
    compose = (root / "infra" / "output" / "dev" / "docker-compose.yml").read_text()
    # host part resolves to the project-scoped service name.
    assert "DATABASE_HOST" in compose
    assert "sample-dev-appdb" in compose
    # secret parts: compose runtime form uses ${VAR}, never $[VAR].
    assert "DATABASE_USER" in compose
    assert "${POSTGRES_USER}" in compose
    assert "${POSTGRES_PASSWORD}" in compose
    assert "$[POSTGRES_USER]" not in compose
    # The composed url part is gone entirely.
    assert "DATABASE_URL" not in compose
    assert "postgres://" not in compose


def test_dev_test_images_are_registry_less(tmp_path: Path):
    """dev/test build locally, so the image is a registry-less local tag —
    never the container_registry host, never the <project-ecr> placeholder."""
    root = _copy_fixture(_FIXTURE_FIXED, tmp_path)
    ctx = load_project_context(root)
    run_compile(ctx)
    for env in ("dev", "test"):
        compose = (root / "infra" / "output" / env / "docker-compose.yml").read_text()
        assert "image: sample/api:0.1.0" in compose
        assert "registry.example.com/sample/api" not in compose
        assert "<project-ecr>" not in compose


def test_stage_prod_images_use_registry(tmp_path: Path):
    """Fixed stage/prod pull from the registry — the image carries the
    full container_registry host."""
    root = _copy_fixture(_FIXTURE_FIXED, tmp_path)
    ctx = load_project_context(root)
    run_compile(ctx)
    for env in ("stage", "prod"):
        compose = (root / "infra" / "output" / env / "docker-compose.yml").read_text()
        assert "image: registry.example.com/sample/api:0.1.0" in compose


def test_backing_service_port_defaults_from_engine(tmp_path: Path):
    """A backing service that omits `port:` still resolves its `.port`
    magic ref — from the engine's transfer-table default_port (postgres
    → 5432)."""
    import yaml

    root = _copy_fixture(_FIXTURE_FIXED, tmp_path)
    infra_yml = root / "infra" / "infra.yml"
    # Drop the explicit `port: 5432` from the database backing service.
    text = "\n".join(
        line for line in infra_yml.read_text().splitlines()
        if line.strip() != "port: 5432"
    )
    infra_yml.write_text(text)
    ctx = load_project_context(root)
    run_compile(ctx)
    compose = (root / "infra" / "output" / "dev" / "docker-compose.yml").read_text()
    doc = yaml.safe_load(compose)
    api = next(b for k, b in doc["services"].items() if k.endswith("api"))
    assert str(api["environment"]["DATABASE_PORT"]) == "5432"


def test_backing_service_compiled_port_falls_back_to_engine_default(tmp_path: Path):
    """Companion to test_backing_service_port_defaults_from_engine.
    The above verifies the substitution context (the ${port} variable
    used in provides templates); this verifies the CompiledService.port
    field that downstream emitters (task-def portMappings, ECS Service
    Connect service block) read directly.

    The two paths diverged before docex 0.10.0's smoke walk surfaced the
    gap: omitting `port:` left CompiledService.port = None, which broke
    Service Connect's `service` block emission (no port_name to
    reference) and the task definition's portMappings (entirely absent).
    Fixed by falling back to engine.default_port on CompiledService.port.
    """
    from docex.cicl.compile import compile_env
    from docex.cicl.transfer import load_transfer_tables
    from docex.context import load_project_context

    root = _copy_fixture(_FIXTURE_FIXED, tmp_path)
    infra_yml = root / "infra" / "infra.yml"
    text = "\n".join(
        line for line in infra_yml.read_text().splitlines()
        if line.strip() != "port: 5432"
    )
    infra_yml.write_text(text)
    ctx = load_project_context(root)
    tables = load_transfer_tables(root)
    env = compile_env(
        ctx.infra, tables,
        env="dev",
        project_name=ctx.project.name,
        project_version=ctx.project.version,
    )
    db = next(s for s in env.services.values() if not s.is_core)
    assert db.port == 5432, (
        f"CompiledService.port should fall back to postgres engine's "
        f"default_port (5432) when infra.yml omits `port:`. Got {db.port}."
    )


def test_composed_secret_in_env_fails_compile(tmp_path: Path):
    """Embedding a secret part inside a composed env value violates the
    parts-only rule and must fail compile (on any foundation)."""
    root = _copy_fixture(_FIXTURE_FIXED, tmp_path)
    infra_yml = root / "infra" / "infra.yml"
    text = infra_yml.read_text().replace(
        "      DATABASE_USER: ${backing_services.appdb.user}",
        "      DATABASE_USER: ${backing_services.appdb.user}\n"
        "      DATABASE_URL: postgres://${backing_services.appdb.user}@h/db",
    )
    infra_yml.write_text(text)
    ctx = load_project_context(root)
    with pytest.raises(ValidationError):
        run_compile(ctx)


def test_example_env_includes_postgres_keys(tmp_path: Path):
    root = _copy_fixture(_FIXTURE_FIXED, tmp_path)
    ctx = load_project_context(root)
    run_compile(ctx)
    example = (root / "infra" / "secrets" / "example.env").read_text()
    assert "POSTGRES_USER=" in example
    assert "POSTGRES_PASSWORD=" in example
    assert "# appdb" in example


_SECRET_INFRA = """\
cicl_version: "1"
foundation: __FND__
apex_domain: example.com
observability_backend_url: "https://obs.example.com"
container_registry: reg.example.com
domain_default_service: api
core_services:
  api:
    role: web
    port: 8080
    networks: [web, internal]
    secrets:
      BESPOKE_API_KEY: "key for the bespoke API"
    resources:
      cpu: 1.0
      memory: 2GB
      disk: 25GB
"""


def _write_scratch(tmp_path: Path, foundation: str) -> Path:
    proj = tmp_path / "p"
    (proj / "infra").mkdir(parents=True)
    (proj / "project.yml").write_text('name: p\nversion: "0.1.0"\ndocex_version: "0.4.0"\n')
    (proj / "infra" / "infra.yml").write_text(_SECRET_INFRA.replace("__FND__", foundation))
    return proj


def test_core_secret_in_example_env_and_compose(tmp_path: Path):
    """A core service's `secrets:` key surfaces in example.env (grouped under
    the service) and is wired into the container as a runtime secret."""
    proj = _write_scratch(tmp_path, "fixed")
    run_compile(load_project_context(proj))
    example = (proj / "infra" / "secrets" / "example.env").read_text()
    assert "# api (core service)" in example
    assert "BESPOKE_API_KEY=" in example
    compose = (proj / "infra" / "output" / "dev" / "docker-compose.yml").read_text()
    # Delivered via compose ${VAR} substitution, never the literal $[VAR].
    assert "${BESPOKE_API_KEY}" in compose
    assert "$[BESPOKE_API_KEY]" not in compose


def test_core_secret_becomes_ecs_secret_on_elastic(tmp_path: Path):
    """On elastic the same secret becomes an ECS secrets[] entry sourced from
    SSM under its own key."""
    proj = _write_scratch(tmp_path, "elastic")
    run_compile(load_project_context(proj))
    tf = (proj / "infra" / "output" / "prod" / "main.tf").read_text()
    assert 'name = "BESPOKE_API_KEY"' in tf
    assert "/prod/BESPOKE_API_KEY" in tf


def test_compose_depends_on_uses_global_service_keys(tmp_path: Path):
    """``depends_on`` in compose must reference compose service keys
    (global names like ``sample-dev-appdb``), not the simple names
    used in infra.yml. Docker compose rejects the file otherwise.
    """
    import yaml

    root = _copy_fixture(_FIXTURE_FIXED, tmp_path)
    ctx = load_project_context(root)
    run_compile(ctx)
    compose_path = root / "infra" / "output" / "dev" / "docker-compose.yml"
    doc = yaml.safe_load(compose_path.read_text())
    service_keys = set(doc["services"].keys())
    for name, block in doc["services"].items():
        for dep in block.get("depends_on", []) or []:
            assert dep in service_keys, (
                f"{name}.depends_on references {dep!r}, not a compose "
                f"service key. Service keys are: {sorted(service_keys)}"
            )


def test_compose_has_logging_anchor(tmp_path: Path):
    root = _copy_fixture(_FIXTURE_FIXED, tmp_path)
    ctx = load_project_context(root)
    run_compile(ctx)
    compose = (root / "infra" / "output" / "dev" / "docker-compose.yml").read_text()
    assert "x-logging: &default-logging" in compose
    assert "logging: *default-logging" in compose


# ---------------------------------------------------------------------------
# Mod 005 — naming policies sweep across project/env HCL output.
# ---------------------------------------------------------------------------


_NAMING_INFRA = """\
cicl_version: "1"
foundation: elastic
apex_domain: example.com
observability_backend_url: "https://obs.example.com"
domain_default_service: web
core_services:
  web:
    role: web
    port: 8080
    networks: [web, internal]
    depends_on: [appdb]
    env:
      DATABASE_HOST: ${backing_services.appdb.host}
      DATABASE_PORT: ${backing_services.appdb.port}
      DATABASE_NAME: ${backing_services.appdb.db}
      DATABASE_USER: ${backing_services.appdb.user}
      DATABASE_PASSWORD: ${backing_services.appdb.password}
    resources:
      cpu: 0.25
      memory: 512MB
      disk: 25GB
backing_services:
  appdb:
    role: relational_db
    engine: postgres
    version: "15"
    networks: [internal]
    schema_owned_by: web
"""


def _write_underscore_project(tmp_path: Path) -> Path:
    """A project whose name carries underscores — surfaces every policy
    site where the doctrine hyphen-translates for data-plane resolvable
    identifiers (S3, RDS, ALB, ECS, Docker, http_host) and where it
    preserves underscores for inert AWS record-key identifiers (DDB,
    IAM, SSM path)."""
    proj = tmp_path / "p"
    (proj / "infra").mkdir(parents=True)
    (proj / "project.yml").write_text(
        'name: docex_smoke_elastic\nversion: "0.0.1"\ndocex_version: "0.7.0"\n'
    )
    (proj / "infra" / "infra.yml").write_text(_NAMING_INFRA)
    return proj


def test_project_tier_state_backend_names_translated(tmp_path: Path):
    """Per mod 005: the project-tier S3 bucket name is hyphen-translated
    (the `s3` policy); the DynamoDB lock table preserves underscores
    (the `ddb` policy)."""
    proj = _write_underscore_project(tmp_path)
    run_compile(load_project_context(proj))
    project_tf = (proj / "infra" / "output" / "project" / "main.tf").read_text()
    assert 'bucket         = "docex-smoke-elastic-tofu-state"' in project_tf
    assert 'dynamodb_table = "docex_smoke_elastic_tofu_locks"' in project_tf
    # Hyphenated underscored form must NOT appear (would be the legacy bug).
    assert "docex_smoke_elastic-tofu-state" not in project_tf


def test_project_tier_ecr_and_iam_names_use_correct_policies(tmp_path: Path):
    proj = _write_underscore_project(tmp_path)
    run_compile(load_project_context(proj))
    project_tf = (proj / "infra" / "output" / "project" / "main.tf").read_text()
    # ECR repos: structural emit `${project}/${service}` — each segment
    # verbatim, `/` as joiner. No policy applied (transfer_tables.md
    # carve-out).
    assert 'name                 = "docex_smoke_elastic/web"' in project_tf
    # IAM role + inline SSM policy names: underscores preserved.
    assert 'name = "docex_smoke_elastic_task_execution"' in project_tf
    assert 'name = "docex_smoke_elastic_task_execution_ssm"' in project_tf
    # SSM resource ARN: same underscore-preserving form.
    assert "/docex_smoke_elastic/*" in project_tf


def test_env_tier_state_backend_alb_ecs_cluster_names(tmp_path: Path):
    """Stage/prod main.tf state backend + ALB + ECS cluster names follow
    the matching policies (S3 = hyphen, DDB = underscore, ALB = hyphen,
    ECS = hyphen)."""
    proj = _write_underscore_project(tmp_path)
    run_compile(load_project_context(proj))
    for env in ("stage", "prod"):
        tf = (proj / "infra" / "output" / env / "main.tf").read_text()
        # State backend (same names as project tier — points at the same bucket).
        assert 'bucket         = "docex-smoke-elastic-tofu-state"' in tf
        assert 'dynamodb_table = "docex_smoke_elastic_tofu_locks"' in tf
        assert f'bucket = "docex-smoke-elastic-tofu-state"' in tf
        # ALB: hyphen + lower not enforced (case=any); the project string still
        # hyphenates because the alb policy uses `separator: hyphen`.
        assert f'name               = "docex-smoke-elastic-{env}-alb"' in tf
        # ECS cluster: hyphen (ecs policy is data-plane resolvable).
        assert f'name = "docex-smoke-elastic-{env}"' in tf


def test_env_tier_rds_and_ecs_service_names(tmp_path: Path):
    """RDS identifier uses the `rds` policy (hyphen + lower); ECS service
    name follows the web role's `ecs` policy (hyphen)."""
    proj = _write_underscore_project(tmp_path)
    run_compile(load_project_context(proj))
    for env in ("stage", "prod"):
        tf = (proj / "infra" / "output" / env / "main.tf").read_text()
        # RDS instance identifier (postgres → rds policy).
        assert f'identifier = "docex-smoke-elastic-{env}-appdb"' in tf
        # ECS service + task family (web → ecs policy, hyphen).
        assert f'name            = "docex-smoke-elastic-{env}-web"' in tf
        assert f'family                   = "docex-smoke-elastic-{env}-web"' in tf
        # Migration task family.
        assert f'family                   = "docex-smoke-elastic-{env}-web-migrate"' in tf


def test_bootstrap_state_backend_matches_project_tier(tmp_path: Path):
    """The bucket/table names the bootstrap creates must match the names
    referenced in the project-tier `backend "s3"` block. Drift here is
    exactly the bug mod 005 closes."""
    proj = _write_underscore_project(tmp_path)
    ctx = load_project_context(proj)
    run_compile(ctx)

    project_tf = (proj / "infra" / "output" / "project" / "main.tf").read_text()
    policies = ctx.transfer_tables.naming_policies
    from docex.naming import apply_policy
    bucket = apply_policy("docex_smoke_elastic_tofu_state", policies.get("s3"))
    table = apply_policy("docex_smoke_elastic_tofu_locks", policies.get("ddb"))
    assert f'bucket         = "{bucket}"' in project_tf
    assert f'dynamodb_table = "{table}"' in project_tf


# ---------------------------------------------------------------------------
# Mod 006 — SG egress on elastic env main.tf.
# ---------------------------------------------------------------------------


def test_every_emitted_sg_has_egress(tmp_path: Path):
    """Mod 006: every project-emitted SG in an elastic env main.tf carries
    an egress block. Without it, Terraform's aws_security_group denies all
    egress and Fargate can't reach SSM/ECR. The elastic fixture declares
    two networks (web, internal); plus the ALB SG = 3 egress blocks total.
    """
    root = _copy_fixture(_FIXTURE_ELASTIC, tmp_path)
    ctx = load_project_context(root)
    run_compile(ctx)
    for env in ("stage", "prod"):
        tf = (root / "infra" / "output" / env / "main.tf").read_text()
        assert tf.count("egress {") == 3, (
            f"expected 3 egress blocks in {env}/main.tf "
            f"(web SG, internal SG, ALB SG), got {tf.count('egress {')}"
        )


# ---------------------------------------------------------------------------
# Mod 007 — postgres host part uses RDS `.address`, not `.endpoint`.
# ---------------------------------------------------------------------------


def test_db_host_uses_address_not_endpoint(tmp_path: Path):
    """The postgres engine's `host` provided part must resolve to
    ``aws_db_instance.<svc>.address`` — the hostname only. ``.endpoint``
    embeds ``:port``, which produces malformed ``host:port:port`` DSNs at
    consumer-side composition. Regression guard for mod 007."""
    root = _copy_fixture(_FIXTURE_ELASTIC, tmp_path)
    ctx = load_project_context(root)
    run_compile(ctx)
    for env in ("stage", "prod"):
        tf = (root / "infra" / "output" / env / "main.tf").read_text()
        assert "aws_db_instance.appdb.address" in tf
        assert "aws_db_instance.appdb.endpoint" not in tf


def test_describe_dag_and_llm(tmp_path: Path):
    """describe command runs end-to-end and the LLM form parses as JSON."""
    from docex.describe import run_describe
    import io
    import contextlib

    root = _copy_fixture(_FIXTURE_FIXED, tmp_path)
    ctx = load_project_context(root)

    # DAG: just check it produces text mentioning known names.
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        run_describe(ctx, env="prod", fmt="dag")
    out = buf.getvalue()
    assert "sample" in out
    assert "depends_on" in out

    # LLM: must be valid JSON.
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        run_describe(ctx, env="prod", fmt="llm")
    parsed = json.loads(buf.getvalue())
    assert parsed["env"] == "prod"
    assert parsed["foundation"] == "fixed"
    assert any(
        edge["from"] == "api" and edge["to"] == "appdb"
        for edge in parsed["edges"]
    )
