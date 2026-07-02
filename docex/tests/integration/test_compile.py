"""Integration tests for ``docex compile`` against the sample fixture.

We compile into a temp directory rather than the fixture in place to
keep tests hermetic. The fixture is copied to ``tmp_path``; outputs
are inspected there.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
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


# ---------------------------------------------------------------------------
# Mod 035 — project-tier output split by side.
# ---------------------------------------------------------------------------


def test_project_tier_development_compose_emitted_for_every_project(tmp_path: Path):
    """Mod 035: every project (fixed and elastic) emits a development-side
    project-tier compose file. The development side is always fixed-style."""
    for fixture in (_FIXTURE_FIXED, _FIXTURE_ELASTIC):
        root = _copy_fixture(fixture, tmp_path / fixture.name)
        ctx = load_project_context(root)
        rc = run_compile(ctx)
        assert rc == 0
        assert (
            root
            / "infra" / "output" / "project" / "development" / "docker-compose.yml"
        ).is_file(), f"missing development-side compose for {fixture.name}"


def test_project_tier_production_compose_emitted_for_fixed_only(tmp_path: Path):
    """Mod 035: fixed-foundation projects emit a production-side compose;
    elastic-foundation projects do not (they emit main.tf instead)."""
    fixed_root = _copy_fixture(_FIXTURE_FIXED, tmp_path / "fixed")
    rc = run_compile(load_project_context(fixed_root))
    assert rc == 0
    assert (
        fixed_root
        / "infra" / "output" / "project" / "production" / "docker-compose.yml"
    ).is_file()

    elastic_root = _copy_fixture(_FIXTURE_ELASTIC, tmp_path / "elastic")
    rc = run_compile(load_project_context(elastic_root))
    assert rc == 0
    assert not (
        elastic_root
        / "infra" / "output" / "project" / "production" / "docker-compose.yml"
    ).exists()


def test_project_tier_production_main_tf_emitted_for_elastic_only(tmp_path: Path):
    """Mod 035: elastic-foundation projects emit a production-side
    main.tf at the new path; fixed-foundation projects do not."""
    elastic_root = _copy_fixture(_FIXTURE_ELASTIC, tmp_path / "elastic")
    rc = run_compile(load_project_context(elastic_root))
    assert rc == 0
    assert (
        elastic_root
        / "infra" / "output" / "project" / "production" / "main.tf"
    ).is_file()

    fixed_root = _copy_fixture(_FIXTURE_FIXED, tmp_path / "fixed")
    rc = run_compile(load_project_context(fixed_root))
    assert rc == 0
    assert not (
        fixed_root
        / "infra" / "output" / "project" / "production" / "main.tf"
    ).exists()


def test_project_tier_compose_declares_four_web_networks(tmp_path: Path):
    """Mod 035 + 036: the project-tier compose file declares the four
    ``${project}-${env}-web`` networks plus the ``docex-ingress``
    external reference."""
    import yaml

    root = _copy_fixture(_FIXTURE_FIXED, tmp_path)
    rc = run_compile(load_project_context(root))
    assert rc == 0

    compose_path = (
        root / "infra" / "output" / "project" / "development" / "docker-compose.yml"
    )
    data = yaml.safe_load(compose_path.read_text())
    networks = data.get("networks", {})
    project = "sample"
    for env in ("dev", "test", "stage", "prod"):
        key = f"{project}-{env}-web"
        assert key in networks, f"missing network {key!r}"
        assert networks[key].get("name") == key
    assert networks.get("docex-ingress") == {"external": True}


def test_project_tier_compose_declares_traefik_service(tmp_path: Path):
    """Mod 036: the project-tier compose emits a ``${project}-traefik``
    service joined to the four ``-web`` networks plus ``docex-ingress``,
    with the doctrine cert resolver name, the acme volume, and the
    operator-supplied DNS-01 env vars wired via compose runtime
    substitution."""
    import yaml

    root = _copy_fixture(_FIXTURE_FIXED, tmp_path)
    rc = run_compile(load_project_context(root))
    assert rc == 0

    project = "sample"
    compose_path = (
        root / "infra" / "output" / "project" / "development" / "docker-compose.yml"
    )
    data = yaml.safe_load(compose_path.read_text())

    services = data.get("services", {})
    traefik_key = f"{project}-traefik"
    assert traefik_key in services, sorted(services)
    svc = services[traefik_key]

    # Container is named explicitly (doctrine requires this exact name).
    assert svc.get("container_name") == traefik_key
    assert svc.get("restart") == "unless-stopped"
    # Image is pinned by digest (mod 036).
    image = svc.get("image", "")
    assert image.startswith("traefik:") and "@sha256:" in image, image

    # Network attachments: all four -web networks + docex-ingress.
    expected_networks = {
        f"{project}-dev-web",
        f"{project}-test-web",
        f"{project}-stage-web",
        f"{project}-prod-web",
        "docex-ingress",
    }
    assert set(svc.get("networks", [])) == expected_networks, svc["networks"]

    # Volumes: docker socket (ro) + acme named volume.
    volumes = svc.get("volumes", [])
    assert "/var/run/docker.sock:/var/run/docker.sock:ro" in volumes
    acme_volume = f"{project}-traefik-acme"
    assert f"{acme_volume}:/letsencrypt" in volumes

    # Command flags: cert resolver name 'doctrine', HTTP-01 enabled
    # (mod 051 Gap A — no DNS-01, no DNS-provider cred), the project-scope
    # constraint (mod 051 Gap B), and the LE account email substitution.
    command = svc.get("command", [])
    assert "--providers.docker=true" in command
    assert "--providers.docker.exposedbydefault=false" in command
    assert "--entrypoints.web.address=:80" in command
    assert "--entrypoints.websecure.address=:443" in command
    assert any(
        "certificatesresolvers.doctrine.acme.httpchallenge=true" in c
        for c in command
    ), command
    assert any(
        "certificatesresolvers.doctrine.acme.httpchallenge.entrypoint=web" in c
        for c in command
    ), command
    assert any(
        "${TRAEFIK_ACME_EMAIL:-}" in c for c in command
    ), command
    # The DNS-01 mechanism is gone entirely.
    assert not any("dnschallenge" in c for c in command), command
    assert not any("TRAEFIK_DNS_PROVIDER" in c for c in command), command
    # Mod 051 Gap B: docker provider constrained to this project's label.
    assert any(
        c == f"--providers.docker.constraints=Label(`docex.project`,`{project}`)"
        for c in command
    ), command
    # And the traefik service itself carries the matching label.
    assert f"docex.project={project}" in (svc.get("labels") or []), svc.get("labels")

    # Top-level acme volume declared.
    assert acme_volume in data.get("volumes", {}), data.get("volumes")


def test_project_tier_compose_identical_on_both_sides_for_fixed(tmp_path: Path):
    """Mod 036 single-machine convergence: a fixed project's
    development-side and production-side compose bodies emit the same
    networks/services/volumes content. When ``projinfra up production``
    runs after ``up development`` on the same daemon, docker compose
    observes no diff and leaves the existing resources alone."""
    import yaml

    root = _copy_fixture(_FIXTURE_FIXED, tmp_path)
    rc = run_compile(load_project_context(root))
    assert rc == 0

    dev = yaml.safe_load(
        (
            root / "infra" / "output" / "project" / "development"
            / "docker-compose.yml"
        ).read_text()
    )
    prod = yaml.safe_load(
        (
            root / "infra" / "output" / "project" / "production"
            / "docker-compose.yml"
        ).read_text()
    )
    # The body content (networks/services/volumes) is what compose
    # diffs against running state — equal content means a no-op second
    # invocation.
    for key in ("networks", "services", "volumes"):
        assert dev.get(key) == prod.get(key), (
            f"project-tier {key!r} differs between sides:\n"
            f"  dev:  {dev.get(key)!r}\n"
            f"  prod: {prod.get(key)!r}"
        )


def test_env_compose_web_network_references_project_tier_external(tmp_path: Path):
    """Mod 036: env-tier compose's ``web`` short-name now references the
    project-tier ``${project}-${env}-web`` network with ``external: true``
    — projinfra owns the network lifecycle; env compose merely attaches."""
    import yaml

    root = _copy_fixture(_FIXTURE_FIXED, tmp_path)
    rc = run_compile(load_project_context(root))
    assert rc == 0

    for env in ("dev", "test", "stage", "prod"):
        path = root / "infra" / "output" / env / "docker-compose.yml"
        doc = yaml.safe_load(path.read_text())
        web = doc["networks"]["web"]
        assert web == {
            "name": f"sample-{env}-web",
            "external": True,
        }, (env, web)


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
    project_tf = (
        proj / "infra" / "output" / "project" / "production" / "main.tf"
    ).read_text()
    assert 'bucket         = "docex-smoke-elastic-tofu-state"' in project_tf
    assert 'dynamodb_table = "docex_smoke_elastic_tofu_locks"' in project_tf
    # Hyphenated underscored form must NOT appear (would be the legacy bug).
    assert "docex_smoke_elastic-tofu-state" not in project_tf


def test_project_tier_ecr_and_iam_names_use_correct_policies(tmp_path: Path):
    proj = _write_underscore_project(tmp_path)
    run_compile(load_project_context(proj))
    project_tf = (
        proj / "infra" / "output" / "project" / "production" / "main.tf"
    ).read_text()
    # ECR repos: structural emit `${project}/${service}` — each segment
    # verbatim, `/` as joiner. No policy applied (transfer_tables.md
    # carve-out).
    assert 'name                 = "docex_smoke_elastic/web"' in project_tf
    # IAM role + inline policy names: underscores preserved. Mod 039
    # collapsed the previous role+attachment+ssm-policy trio into a
    # single combined inline policy that shares the role's name.
    assert 'name = "docex_smoke_elastic_task_execution"' in project_tf
    # SSM resource ARNs: same underscore-preserving form, now scoped
    # per-env (stage + prod) per the doctrine.
    assert "/docex_smoke_elastic/stage/*" in project_tf
    assert "/docex_smoke_elastic/prod/*" in project_tf


def test_project_tier_task_execution_policy_is_project_scoped(tmp_path: Path):
    """Mod 039: the AWS-managed AmazonECSTaskExecutionRolePolicy attachment
    is replaced by a single explicit inline policy scoped to project
    resources only. The five statements (ECR auth, per-repo ECR pull,
    stage SSM, prod SSM, CloudWatch logs) all appear; `kms:Decrypt` does
    not (AWS-managed `aws/ssm` key needs no explicit grant)."""
    proj = _write_underscore_project(tmp_path)
    run_compile(load_project_context(proj))
    project_tf = (
        proj / "infra" / "output" / "project" / "production" / "main.tf"
    ).read_text()

    # --- Absences (old shape gone) ---
    # The AWS-managed-policy attachment is no longer attached (the
    # explanatory comment block in the template references the policy by
    # name to explain *why* it is gone, so we assert on the resource/
    # attachment form rather than the bare name).
    assert (
        "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
        not in project_tf
    )
    assert (
        'resource "aws_iam_role_policy_attachment" "task_execution_managed"'
        not in project_tf
    )
    assert 'resource "aws_iam_role_policy" "task_execution_ssm"' not in project_tf
    assert "kms:Decrypt" not in project_tf

    # --- Presence: single combined policy resource ---
    assert 'resource "aws_iam_role_policy" "task_execution" {' in project_tf

    # --- Statement 1: ECR auth token on * ---
    assert 'Action   = "ecr:GetAuthorizationToken"' in project_tf
    # Auth token must be on * — the `Resource = "*"` line lives in this
    # statement; check it co-occurs.
    auth_idx = project_tf.index('"ecr:GetAuthorizationToken"')
    assert 'Resource = "*"' in project_tf[auth_idx : auth_idx + 200]

    # --- Statement 2: per-repo ECR pull, gated on core_service_names ---
    assert '"ecr:BatchCheckLayerAvailability"' in project_tf
    assert '"ecr:BatchGetImage"' in project_tf
    assert '"ecr:GetDownloadUrlForLayer"' in project_tf
    # Naming-fixture project has a single `web` core service.
    assert "aws_ecr_repository.web.arn" in project_tf

    # --- Statements 3 & 4: SSM, two separate statements ---
    assert (
        'Resource = "arn:aws:ssm:us-east-1:${data.aws_caller_identity'
        ".current.account_id}:parameter/docex_smoke_elastic/stage/*\""
        in project_tf
    )
    assert (
        'Resource = "arn:aws:ssm:us-east-1:${data.aws_caller_identity'
        ".current.account_id}:parameter/docex_smoke_elastic/prod/*\""
        in project_tf
    )

    # --- Statement 5: CloudWatch logs, both env log-group ARNs ---
    assert '"logs:CreateLogStream"' in project_tf
    assert '"logs:PutLogEvents"' in project_tf
    assert "log-group:/docex_smoke_elastic/stage/*" in project_tf
    assert "log-group:/docex_smoke_elastic/prod/*" in project_tf


def test_project_tier_task_execution_policy_empty_core_services(tmp_path: Path):
    """When a project compiles with zero core services, the per-repo ECR
    pull statement must be omitted entirely — AWS rejects policy
    statements with `Resource = []`. The auth-token statement, SSM
    statements, and CloudWatch logs statement still emit."""
    from docex.context import load_project_context as _load
    from docex.emit.hcl import emit_hcl_project

    proj = tmp_path / "p"
    (proj / "infra").mkdir(parents=True)
    (proj / "project.yml").write_text(
        'name: empty_proj\nversion: "0.0.1"\ndocex_version: "0.7.0"\n'
    )
    # Minimal valid CICL with no core services. backing_services likewise
    # omitted — empty-project edge case for the policy's per-repo gate.
    (proj / "infra" / "infra.yml").write_text(
        "cicl_version: \"1\"\n"
        "foundation: elastic\n"
        "apex_domain: example.com\n"
        "observability_backend_url: \"https://obs.example.com\"\n"
        "core_services: {}\n"
        "backing_services: {}\n"
    )
    ctx = _load(proj)
    out = tmp_path / "project.tf"
    emit_hcl_project(
        project="empty_proj",
        project_version="0.0.1",
        apex_domain="example.com",
        core_service_names=[],
        naming_policies=ctx.transfer_tables.naming_policies,
        out_path=out,
    )
    rendered = out.read_text()
    # Auth-token statement still present.
    assert 'Action   = "ecr:GetAuthorizationToken"' in rendered
    # Per-repo statement is omitted entirely — no actions, no empty list.
    assert '"ecr:BatchGetImage"' not in rendered
    assert '"ecr:BatchCheckLayerAvailability"' not in rendered
    assert "aws_ecr_repository." not in rendered  # no repo refs anywhere
    # SSM and logs statements remain.
    assert "/empty_proj/stage/*" in rendered
    assert "/empty_proj/prod/*" in rendered
    assert '"logs:PutLogEvents"' in rendered


def test_env_tier_state_backend_ecs_cluster_names(tmp_path: Path):
    """Stage/prod main.tf state backend names follow the matching policies
    (S3 = hyphen, DDB = underscore).

    Mod 038: the ALB moved to project-tier; its name is asserted in the
    project-tier name test. Mod 071: the ECS clusters also moved to the
    project tier (both stage + prod always exist). The env main.tf no longer
    declares its own cluster resource — it references the project remote-state
    cluster ARN output — and the cluster *names* are asserted at the project
    tier below."""
    proj = _write_underscore_project(tmp_path)
    run_compile(load_project_context(proj))
    for env in ("stage", "prod"):
        tf = (proj / "infra" / "output" / env / "main.tf").read_text()
        # State backend (same names as project tier — points at the same bucket).
        assert 'bucket         = "docex-smoke-elastic-tofu-state"' in tf
        assert 'dynamodb_table = "docex_smoke_elastic_tofu_locks"' in tf
        assert f'bucket = "docex-smoke-elastic-tofu-state"' in tf
        # Mod 071: no env-tier cluster resource; the env references the
        # project-tier cluster ARN via remote state.
        assert 'resource "aws_ecs_cluster" "cluster"' not in tf
        assert (
            f"data.terraform_remote_state.project.outputs.ecs_cluster_{env}_arn"
            in tf
        )

    # Mod 071: cluster names (hyphen — ecs policy is data-plane resolvable)
    # live at the project tier, one resource per env.
    project_tf = (
        proj / "infra" / "output" / "project" / "production" / "main.tf"
    ).read_text()
    for env in ("stage", "prod"):
        assert f'name = "docex-smoke-elastic-{env}"' in project_tf
    assert 'resource "aws_ecs_cluster" "stage"' in project_tf
    assert 'resource "aws_ecs_cluster" "prod"' in project_tf
    assert 'output "ecs_cluster_stage_arn"' in project_tf
    assert 'output "ecs_cluster_prod_arn"' in project_tf


def test_project_tier_alb_name(tmp_path: Path):
    """Mod 038: the project ALB and its SG live at the project tier and
    use the `alb` naming policy (hyphen + case-any + max 32). For a
    project with underscores, the policy hyphenates."""
    proj = _write_underscore_project(tmp_path)
    run_compile(load_project_context(proj))
    project_tf = (
        proj / "infra" / "output" / "project" / "production" / "main.tf"
    ).read_text()
    # ALB name: project + hyphen + "alb".
    assert 'name               = "docex-smoke-elastic-alb"' in project_tf
    # ALB SG name.
    assert 'name        = "docex-smoke-elastic-alb-sg"' in project_tf


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


def test_env_tier_sg_name_uses_hyphen_form(tmp_path: Path):
    """Mod 040: env-tier security-group AWS-side `name` follows the doctrine's
    data-plane convention from `networks.md § Compiled Names`: hyphenated,
    project-then-env-then-short, with the project's underscores translated.
    Locks the regression site at `main.tf.j2:52`, which historically emitted
    `{project}_{env}_{short}` against the doctrine's stated form."""
    proj = _write_underscore_project(tmp_path)
    run_compile(load_project_context(proj))
    for env in ("stage", "prod"):
        tf = (proj / "infra" / "output" / env / "main.tf").read_text()
        # Both env-tier SGs (web, internal) carry the hyphenated name.
        assert f'name        = "docex-smoke-elastic-{env}-web"' in tf
        assert f'name        = "docex-smoke-elastic-{env}-internal"' in tf
        # Old literal-underscore form must not leak through the resource
        # `name` attribute. (Mod 060: the SG's console-ergonomic `Name`
        # *tag* does use the project's underscore form per cicl.md's
        # standard — that's a different field and is expected.)
        assert f'name        = "docex_smoke_elastic_{env}_web"' not in tf
        assert f'name        = "docex_smoke_elastic_{env}_internal"' not in tf


def test_bootstrap_state_backend_matches_project_tier(tmp_path: Path):
    """The bucket/table names the bootstrap creates must match the names
    referenced in the project-tier `backend "s3"` block. Drift here is
    exactly the bug mod 005 closes."""
    proj = _write_underscore_project(tmp_path)
    ctx = load_project_context(proj)
    run_compile(ctx)

    project_tf = (
        proj / "infra" / "output" / "project" / "production" / "main.tf"
    ).read_text()
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
    two networks (web, internal) = 2 egress blocks in env main.tf. Mod
    038: the ALB SG moved to the project tier, so it no longer counts
    here. The project-tier ALB SG egress is asserted separately below.
    """
    root = _copy_fixture(_FIXTURE_ELASTIC, tmp_path)
    ctx = load_project_context(root)
    run_compile(ctx)
    for env in ("stage", "prod"):
        tf = (root / "infra" / "output" / env / "main.tf").read_text()
        assert tf.count("egress {") == 2, (
            f"expected 2 egress blocks in {env}/main.tf "
            f"(web SG, internal SG), got {tf.count('egress {')}"
        )
    # Mod 038: the ALB SG's egress block lives at the project tier.
    project_tf = (
        root / "infra" / "output" / "project" / "production" / "main.tf"
    ).read_text()
    assert "egress {" in project_tf, "project-tier ALB SG must declare an egress block"


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


# ---------------------------------------------------------------------------
# Mod 038 — project-tier ALB; listener rules stay env-tier with banded
# priorities (stage [1000, 4999], prod [5000, 9999]).
# ---------------------------------------------------------------------------


def _compile_elastic(tmp_path: Path) -> Path:
    """Compile the elastic fixture into tmp_path; return the project root."""
    root = _copy_fixture(_FIXTURE_ELASTIC, tmp_path)
    ctx = load_project_context(root)
    rc = run_compile(ctx)
    assert rc == 0
    return root


def test_mod038_project_tier_has_alb_resources(tmp_path: Path):
    """Mod 038: the project-tier main.tf declares the ALB set (SG, LB,
    HTTPS listener, listener_certificate for stage SNI, HTTP→HTTPS
    redirect)."""
    root = _compile_elastic(tmp_path)
    tf = (
        root / "infra" / "output" / "project" / "production" / "main.tf"
    ).read_text()
    assert 'resource "aws_security_group" "project_alb"' in tf
    assert 'resource "aws_lb" "project"' in tf
    assert 'resource "aws_lb_listener" "project_https"' in tf
    assert 'resource "aws_lb_listener_certificate" "project_stage"' in tf
    assert 'resource "aws_lb_listener" "project_http"' in tf
    # LB type is application + internet-facing.
    assert 'load_balancer_type = "application"' in tf
    assert "internal           = false" in tf
    # Public ingress on both 80 and 443.
    assert "from_port   = 80" in tf
    assert "from_port   = 443" in tf
    # HTTPS listener default cert is the prod cert; stage cert is the
    # SNI binding.
    assert "certificate_arn   = aws_acm_certificate_validation.prod.certificate_arn" in tf
    assert "certificate_arn = aws_acm_certificate_validation.stage.certificate_arn" in tf
    # HTTP listener performs a 301 redirect to 443.
    assert 'status_code = "HTTP_301"' in tf
    # Mod 041: subnets now resolve from the master VPC data source.
    assert "subnets            = data.aws_subnets.public.ids" in tf
    # The mod-038 placeholder comment is gone.
    assert "mod 041 will switch this to a master VPC data source" not in tf
    # ALB SG hangs off the master VPC.
    assert "vpc_id      = data.aws_vpc.master.id" in tf


def test_mod038_project_tier_alb_outputs(tmp_path: Path):
    """Mod 038: the project-tier main.tf exposes six ALB outputs for
    env-tier remote-state consumption."""
    root = _compile_elastic(tmp_path)
    tf = (
        root / "infra" / "output" / "project" / "production" / "main.tf"
    ).read_text()
    for out_name in (
        "alb_arn",
        "alb_dns_name",
        "alb_zone_id",
        "alb_https_listener_arn",
        "alb_http_listener_arn",
        "alb_security_group_id",
    ):
        assert f'output "{out_name}"' in tf, f"missing project-tier output {out_name!r}"


def test_mod038_env_tier_has_no_alb_resources(tmp_path: Path):
    """Mod 038: env-tier main.tf declares no ALB-defining resources —
    the project ALB SG, the ALB itself, and both listeners all moved
    to the project tier."""
    root = _compile_elastic(tmp_path)
    for env in ("stage", "prod"):
        tf = (root / "infra" / "output" / env / "main.tf").read_text()
        # No ALB-defining resources.
        assert 'resource "aws_lb" "alb"' not in tf
        assert 'resource "aws_lb_listener" "alb_https"' not in tf
        assert 'resource "aws_lb_listener" "alb_http_redirect"' not in tf
        assert 'resource "aws_security_group" "alb"' not in tf
        # No local references to the removed resources.
        assert "aws_lb.alb." not in tf
        assert "aws_security_group.alb.id" not in tf
        assert "aws_lb_listener.alb_https" not in tf


def test_mod038_env_tier_uses_remote_state_for_alb(tmp_path: Path):
    """Mod 038: env-tier references the project ALB exclusively via
    `data.terraform_remote_state.project.outputs.alb_*`.

    Mod 044 update: the per-network SG ingress source is now the
    polymorphic `reverse_proxy_security_group_id` output, not the
    ALB-specific `alb_security_group_id`. The other ALB references
    (dns_name, zone_id, https_listener_arn) remain ALB-only.
    """
    root = _compile_elastic(tmp_path)
    for env in ("stage", "prod"):
        tf = (root / "infra" / "output" / env / "main.tf").read_text()
        # Per-network SG ingress source for the `web` network.
        assert (
            "source_security_group_id = "
            "data.terraform_remote_state.project.outputs.reverse_proxy_security_group_id"
        ) in tf
        # Route53 alias records (env subdomain + wildcard).
        assert (
            "name                   = "
            "data.terraform_remote_state.project.outputs.alb_dns_name"
        ) in tf
        assert (
            "zone_id                = "
            "data.terraform_remote_state.project.outputs.alb_zone_id"
        ) in tf
        # Listener rules for web services.
        assert (
            "listener_arn = "
            "data.terraform_remote_state.project.outputs.alb_https_listener_arn"
        ) in tf


def test_mod038_listener_rule_priorities_banded_by_env(tmp_path: Path):
    """Mod 038: stage and prod share the project ALB's HTTPS listener,
    so listener-rule priorities are banded by env to avoid collisions:
    stage in [1000, 4999], prod in [5000, 9999]."""
    root = _compile_elastic(tmp_path)
    # The elastic fixture has exactly one web core service (`api`), so
    # each env yields a single listener rule at the band's base.
    stage_tf = (root / "infra" / "output" / "stage" / "main.tf").read_text()
    prod_tf = (root / "infra" / "output" / "prod" / "main.tf").read_text()
    assert "priority     = 1000" in stage_tf
    assert "priority     = 5000" in prod_tf
    # The pre-mod-038 base (100) must not appear (regression guard).
    assert "priority     = 100\n" not in stage_tf
    assert "priority     = 100\n" not in prod_tf


def test_mod038_alb_sg_ingress_open_to_internet(tmp_path: Path):
    """Mod 038: the project ALB SG admits 80 and 443 from 0.0.0.0/0
    (public ingress); egress is allow-all."""
    root = _compile_elastic(tmp_path)
    tf = (
        root / "infra" / "output" / "project" / "production" / "main.tf"
    ).read_text()
    sg_start = tf.find('resource "aws_security_group" "project_alb"')
    assert sg_start != -1
    # Scope to the SG block; it's followed by the aws_lb block.
    sg_end = tf.find('resource "aws_lb" "project"', sg_start)
    sg_block = tf[sg_start:sg_end]
    # Two ingress rules and one egress rule.
    assert sg_block.count("ingress {") == 2
    assert sg_block.count("egress {") == 1
    assert 'cidr_blocks = ["0.0.0.0/0"]' in sg_block


# ---------------------------------------------------------------------------
# Mod 044 — EC2-traefik reverse-proxy variant (EIP + PIP).
# ---------------------------------------------------------------------------


def _compile_elastic_with_reverse_proxy(tmp_path: Path, variant: str) -> Path:
    """Copy the elastic fixture, set `reverse_proxy: <variant>` on its
    infra.yml, compile, and return the project root."""
    root = _copy_fixture(_FIXTURE_ELASTIC, tmp_path)
    infra_yml = root / "infra" / "infra.yml"
    text = infra_yml.read_text()
    # Insert the field right after `foundation: elastic`. The elastic
    # fixture has no existing reverse_proxy field.
    assert "reverse_proxy:" not in text
    text = text.replace(
        "foundation: elastic\n",
        f"foundation: elastic\nreverse_proxy: {variant}\n",
        1,
    )
    infra_yml.write_text(text)
    ctx = load_project_context(root)
    rc = run_compile(ctx)
    assert rc == 0
    return root


def test_mod044_default_reverse_proxy_emits_alb(tmp_path: Path):
    """Omitting `reverse_proxy:` on an elastic project defaults to `alb` —
    the project-tier main.tf still carries the ALB resource set."""
    root = _compile_elastic(tmp_path)
    tf = (
        root / "infra" / "output" / "project" / "production" / "main.tf"
    ).read_text()
    assert 'resource "aws_lb" "project"' in tf
    assert 'resource "aws_security_group" "project_alb"' in tf
    # No EC2-traefik resources leak through.
    assert 'resource "aws_instance" "project_traefik"' not in tf
    assert 'resource "aws_eip" "project_traefik"' not in tf


def test_mod044_eip_variant_emits_traefik_resource_set(tmp_path: Path):
    """`reverse_proxy: ec2_traefik_eip` emits the full EC2-traefik resource
    set: instance, EIP, EBS volume, IAM role+policy+profile, SG,
    log group, and the five doctrine A-records pointing at the EIP."""
    root = _compile_elastic_with_reverse_proxy(tmp_path, "ec2_traefik_eip")
    tf = (
        root / "infra" / "output" / "project" / "production" / "main.tf"
    ).read_text()
    # Core compute + storage resources.
    assert 'resource "aws_instance" "project_traefik"' in tf
    assert 'resource "aws_ebs_volume" "project_traefik_acme"' in tf
    assert 'resource "aws_security_group" "project_traefik"' in tf
    # EIP variant specifically: EIP + association.
    assert 'resource "aws_eip" "project_traefik"' in tf
    assert 'resource "aws_eip_association" "project_traefik"' in tf
    # IAM + observability resources.
    assert 'resource "aws_iam_role" "project_traefik"' in tf
    assert 'resource "aws_iam_instance_profile" "project_traefik"' in tf
    assert 'resource "aws_iam_role_policy" "project_traefik"' in tf
    assert 'resource "aws_cloudwatch_log_group" "project_traefik"' in tf
    # Mod 070: no SSM routing param — routing lives on task dockerLabels now.
    assert 'resource "aws_ssm_parameter" "project_traefik_config"' not in tf
    # Five A-records at the project tier, pointing at the EIP public IP.
    for key in (
        "traefik_bare_project",
        "traefik_prod_wildcard",
        "traefik_prod_bare",
        "traefik_stage_wildcard",
        "traefik_stage_bare",
    ):
        assert f'resource "aws_route53_record" "{key}"' in tf
    assert "aws_eip.project_traefik.public_ip" in tf
    # PIP-only target must NOT appear.
    assert "aws_instance.project_traefik.public_ip" not in tf


def test_mod044_eip_variant_omits_alb_resources(tmp_path: Path):
    """`ec2_traefik_eip` projects don't get an ALB or ACM certs."""
    root = _compile_elastic_with_reverse_proxy(tmp_path, "ec2_traefik_eip")
    tf = (
        root / "infra" / "output" / "project" / "production" / "main.tf"
    ).read_text()
    assert 'resource "aws_lb" "project"' not in tf
    assert 'resource "aws_security_group" "project_alb"' not in tf
    assert 'resource "aws_lb_listener" "project_https"' not in tf
    assert 'resource "aws_lb_listener" "project_http"' not in tf
    assert 'resource "aws_lb_listener_certificate" "project_stage"' not in tf
    assert 'resource "aws_acm_certificate" "stage"' not in tf
    assert 'resource "aws_acm_certificate" "prod"' not in tf
    assert 'resource "aws_acm_certificate_validation"' not in tf
    # ALB-specific outputs gated off, but the polymorphic output is present.
    assert 'output "alb_arn"' not in tf
    assert 'output "alb_security_group_id"' not in tf
    assert 'output "stage_cert_arn"' not in tf
    assert 'output "prod_cert_arn"' not in tf
    assert 'output "reverse_proxy_security_group_id"' in tf


def test_mod044_pip_variant_no_eip_uses_instance_ip(tmp_path: Path):
    """`reverse_proxy: ec2_traefik_pip` skips EIP allocation, lets AWS
    auto-assign a public IP, and Route53 A-records point at the
    instance's `public_ip` attribute (boot-time DNS-update unit
    handles changes after stop/start)."""
    root = _compile_elastic_with_reverse_proxy(tmp_path, "ec2_traefik_pip")
    tf = (
        root / "infra" / "output" / "project" / "production" / "main.tf"
    ).read_text()
    # PIP variant: no EIP allocation, no association.
    assert 'resource "aws_eip" "project_traefik"' not in tf
    assert 'resource "aws_eip_association" "project_traefik"' not in tf
    # Instance still exists, with auto-assigned public IP enabled.
    assert 'resource "aws_instance" "project_traefik"' in tf
    assert "associate_public_ip_address = true" in tf
    # Route53 records point at the instance's public_ip directly.
    assert "aws_instance.project_traefik.public_ip" in tf
    # EIP-only target must NOT appear.
    assert "aws_eip.project_traefik.public_ip" not in tf


def test_mod044_pip_variant_user_data_has_dns_update_unit(tmp_path: Path):
    """The PIP variant ships a doctrine systemd unit
    (`docex-traefik-dns-update.service`) that re-batches Route53 records
    to the current public IP on boot."""
    root = _compile_elastic_with_reverse_proxy(tmp_path, "ec2_traefik_pip")
    tf = (
        root / "infra" / "output" / "project" / "production" / "main.tf"
    ).read_text()
    # The unit definition is heredoc'd into user_data; assert by name.
    assert "docex-traefik-dns-update.service" in tf
    assert "docex-traefik-dns-update" in tf
    # ChangeResourceRecordSets reference confirms the batch logic shipped.
    assert "change-resource-record-sets" in tf


def test_mod044_eip_variant_user_data_omits_dns_update_unit(tmp_path: Path):
    """The EIP variant has stable IPs — the boot-time DNS-update unit must
    NOT appear in its user_data."""
    root = _compile_elastic_with_reverse_proxy(tmp_path, "ec2_traefik_eip")
    tf = (
        root / "infra" / "output" / "project" / "production" / "main.tf"
    ).read_text()
    assert "docex-traefik-dns-update.service" not in tf
    assert "change-resource-record-sets" not in tf


def test_mod044_traefik_variant_env_tier_skips_alb_route53_records(tmp_path: Path):
    """EC2-traefik puts the five A-records at the project tier — env-tier
    main.tf must NOT emit the alb-alias `aws_route53_record.env` /
    `env_wildcard` resources."""
    root = _compile_elastic_with_reverse_proxy(tmp_path, "ec2_traefik_eip")
    for env in ("stage", "prod"):
        tf = (root / "infra" / "output" / env / "main.tf").read_text()
        assert 'resource "aws_route53_record" "env"' not in tf
        assert 'resource "aws_route53_record" "env_wildcard"' not in tf
        # The env-tier should not reference ALB DNS outputs at all.
        assert "outputs.alb_dns_name" not in tf
        assert "outputs.alb_zone_id" not in tf


def test_mod044_traefik_variant_env_tier_skips_listener_rules(tmp_path: Path):
    """EC2-traefik routes via the traefik ECS provider (task dockerLabels,
    mod 070) — env-tier `aws_lb_listener_rule` resources must NOT emit."""
    root = _compile_elastic_with_reverse_proxy(tmp_path, "ec2_traefik_pip")
    for env in ("stage", "prod"):
        tf = (root / "infra" / "output" / env / "main.tf").read_text()
        assert 'resource "aws_lb_listener_rule"' not in tf
        assert 'resource "aws_lb_target_group"' not in tf
        # ECS service no longer carries a load_balancer { } attachment.
        assert "load_balancer {" not in tf
        # The polymorphic SG output is still consumed by env-tier `web` SGs.
        assert "outputs.reverse_proxy_security_group_id" in tf


def test_mod044_alb_variant_keeps_alb_specific_outputs(tmp_path: Path):
    """The default `alb` variant continues to emit every ALB-specific
    output (alb_arn, alb_security_group_id, stage_cert_arn, etc.) — this
    is a regression guard so the variant-gating doesn't accidentally drop
    them."""
    root = _compile_elastic(tmp_path)
    tf = (
        root / "infra" / "output" / "project" / "production" / "main.tf"
    ).read_text()
    for out_name in (
        "alb_arn",
        "alb_dns_name",
        "alb_zone_id",
        "alb_https_listener_arn",
        "alb_http_listener_arn",
        "alb_security_group_id",
        "stage_cert_arn",
        "prod_cert_arn",
        "reverse_proxy_security_group_id",
    ):
        assert f'output "{out_name}"' in tf, f"missing alb-variant output {out_name!r}"


def test_mod044_traefik_iam_route53_scoped_to_project_zone(tmp_path: Path):
    """The traefik instance's IAM policy scopes
    `route53:ChangeResourceRecordSets` to the project's own hosted zone
    only — a compromised instance can't manipulate sibling-project DNS."""
    root = _compile_elastic_with_reverse_proxy(tmp_path, "ec2_traefik_eip")
    tf = (
        root / "infra" / "output" / "project" / "production" / "main.tf"
    ).read_text()
    # Policy resource references the project zone (an interpolation HCL
    # literal); the exact arn string contains aws_route53_zone.project.zone_id.
    policy_start = tf.find('resource "aws_iam_role_policy" "project_traefik"')
    assert policy_start != -1
    policy_end = tf.find('resource "aws_cloudwatch_log_group" "project_traefik"', policy_start)
    policy_block = tf[policy_start:policy_end]
    assert '"route53:ChangeResourceRecordSets"' in policy_block
    assert "aws_route53_zone.project.zone_id" in policy_block
    # Mod 071: lego's route53 DNS-01 provider calls ListHostedZonesByName to
    # discover the zone; its absence 403'd LE cert issuance on the real-AWS
    # walk even after AWS_REGION was set.
    assert '"route53:ListHostedZonesByName"' in policy_block


def test_mod070_traefik_iam_grants_ecs_discovery_not_ssm(tmp_path: Path):
    """The traefik instance's IAM policy grants read-only ECS/EC2 discovery
    (for the ECS provider) scoped to the project's two clusters, and no
    longer grants `ssm:GetParameter*` (routing left SSM in mod 070)."""
    root = _compile_elastic_with_reverse_proxy(tmp_path, "ec2_traefik_eip")
    tf = (
        root / "infra" / "output" / "project" / "production" / "main.tf"
    ).read_text()
    policy_start = tf.find('resource "aws_iam_role_policy" "project_traefik"')
    assert policy_start != -1
    policy_end = tf.find(
        'resource "aws_cloudwatch_log_group" "project_traefik"', policy_start
    )
    policy_block = tf[policy_start:policy_end]
    # Cluster-scoped discovery actions, conditioned on the two cluster ARNs.
    for action in (
        '"ecs:ListTasks"',
        '"ecs:DescribeTasks"',
        '"ecs:DescribeServices"',
        '"ecs:DescribeContainerInstances"',
    ):
        assert action in policy_block, action
    assert "ArnEquals" in policy_block
    assert '"ecs:cluster"' in policy_block
    assert "cluster/sample-stage" in policy_block
    assert "cluster/sample-prod" in policy_block
    # Unscopeable read-only discovery calls.
    for action in (
        '"ecs:ListClusters"',
        '"ecs:DescribeClusters"',
        '"ecs:DescribeTaskDefinition"',
        '"ec2:DescribeInstances"',
    ):
        assert action in policy_block, action
    # The mod-064 SSM config-fetch grant is gone.
    assert "ssm:GetParameter" not in policy_block


def test_mod070_traefik_user_data_uses_ecs_provider(tmp_path: Path):
    """The user_data's static traefik config uses the ECS provider (region,
    both cluster names, exposedByDefault: false, refreshSeconds: 15) and no
    longer carries the file provider / dynamic.yml / SSM config-sync timer."""
    root = _compile_elastic_with_reverse_proxy(tmp_path, "ec2_traefik_eip")
    tf = (
        root / "infra" / "output" / "project" / "production" / "main.tf"
    ).read_text()
    # ECS provider block, keyed under providers.ecs.
    assert "providers:" in tf
    assert "ecs:" in tf
    assert "region: us-east-1" in tf
    assert "autoDiscoverClusters: false" in tf
    assert "- sample-stage" in tf
    assert "- sample-prod" in tf
    assert "exposedByDefault: false" in tf
    assert "refreshSeconds: 15" in tf
    # Mod 071 (bug 7): the traefik.service systemd unit sets AWS_REGION so
    # lego's LE DNS-01 route53 provider can resolve the Route53 endpoint.
    assert "Environment=AWS_REGION=us-east-1" in tf
    assert "Environment=AWS_DEFAULT_REGION=us-east-1" in tf
    # The removed mod-064 file-provider subsystem must be entirely gone.
    assert "docex-traefik-config" not in tf
    assert "dynamic.yml" not in tf
    assert "providers.file" not in tf
    assert "filename: /etc/traefik/dynamic.yml" not in tf


def test_mod070_ec2_traefik_task_def_emits_traefik_labels(tmp_path: Path):
    """On the ec2_traefik path, a web-network core service's task-definition
    container carries the traefik.* dockerLabels the ECS provider reads:
    enable, the router rule (from web_hosts), entrypoint, cert resolver, the
    router->service binding, and the loadbalancer port. Router key <svc>-<env>.
    """
    root = _compile_elastic_with_reverse_proxy(tmp_path, "ec2_traefik_eip")
    for env, expected_host in (
        ("stage", "Host(`api.stage.sample.example.com`)"),
        ("prod", "Host(`api.prod.sample.example.com`)"),
    ):
        tf = (root / "infra" / "output" / env / "main.tf").read_text()
        key = f"api-{env}"
        assert "dockerLabels = {" in tf
        assert '"traefik.enable" = "true"' in tf
        assert f'"traefik.http.routers.{key}.rule" = ' in tf
        assert expected_host in tf
        assert (
            f'"traefik.http.routers.{key}.entrypoints" = "websecure"' in tf
        )
        assert (
            f'"traefik.http.routers.{key}.tls.certresolver" = "doctrine"'
            in tf
        )
        assert f'"traefik.http.routers.{key}.service" = "{key}"' in tf
        # The fixture's `api` service listens on 8080.
        assert (
            f'"traefik.http.services.{key}.loadbalancer.server.port" = "8080"'
            in tf
        )


def test_mod070_alb_task_def_has_no_traefik_labels(tmp_path: Path):
    """The default `alb` path routes via listener rules — task definitions
    must NOT carry any traefik.* dockerLabels."""
    root = _compile_elastic(tmp_path)
    for env in ("stage", "prod"):
        tf = (root / "infra" / "output" / env / "main.tf").read_text()
        assert "dockerLabels" not in tf
        assert "traefik." not in tf


def test_mod044_traefik_ebs_volume_tagged_for_attach_discovery(tmp_path: Path):
    """The ACME EBS volume is tagged so the instance's user_data can
    discover it via `aws ec2 describe-volumes --filters` at boot."""
    root = _compile_elastic_with_reverse_proxy(tmp_path, "ec2_traefik_eip")
    tf = (
        root / "infra" / "output" / "project" / "production" / "main.tf"
    ).read_text()
    vol_start = tf.find('resource "aws_ebs_volume" "project_traefik_acme"')
    assert vol_start != -1
    # Scope to the volume block; an aws_instance or aws_eip follows.
    vol_end = tf.find('resource "aws_instance" "project_traefik"', vol_start)
    if vol_end == -1:
        vol_end = tf.find('resource "aws_eip"', vol_start)
    vol_block = tf[vol_start:vol_end]
    # Mod 060: standard projinfra block PLUS the load-bearing `purpose` tag
    # (the IAM AttachVolume grant is conditioned on purpose + project).
    assert 'purpose = "ec2_traefik_acme"' in vol_block
    assert 'project = "sample"' in vol_block
    assert 'shape_name = "reverse_proxy"' in vol_block
    assert 'descriptor = "acme-ebs"' in vol_block


def test_mod044_traefik_user_data_renders_project_name(tmp_path: Path):
    """The user_data shell script is rendered with `{{ project }}`
    substituted; the rendered output must reference the project name."""
    root = _compile_elastic_with_reverse_proxy(tmp_path, "ec2_traefik_eip")
    tf = (
        root / "infra" / "output" / "project" / "production" / "main.tf"
    ).read_text()
    # Project literal is set as a shell variable at the top of the
    # user_data and then referenced by `${PROJECT}` throughout. The
    # CloudWatch log-group path elsewhere in the HCL carries the literal too.
    assert 'PROJECT="sample"' in tf
    assert "/sample/ec2_traefik" in tf


def test_mod062_traefik_user_data_hcl_escaped_eip(tmp_path: Path):
    """The EC2-traefik user_data is HCL-escaped before entering the heredoc:
    every bash ${VAR} appears as $${VAR} so OpenTofu doesn't parse it as an
    interpolation. Regression for mod 062 (invalid HCL on the ec2_traefik
    path)."""
    root = _compile_elastic_with_reverse_proxy(tmp_path, "ec2_traefik_eip")
    tf = (
        root / "infra" / "output" / "project" / "production" / "main.tf"
    ).read_text()
    # Escaped forms present.
    assert "$${PROJECT}" in tf
    assert "$${VOLUME_ID//-/}" in tf
    assert "$${TRAEFIK_VERSION}" in tf
    # No bare (unescaped) bash expansions survive — a `${` preceded by a
    # non-`$` is what HCL would parse as an interpolation and reject. Every
    # `${` in the emitted file must be the escaped `$${` form. (A plain
    # substring check can't express this: "$${PROJECT}" contains
    # "${PROJECT}" as a substring, so we match on the preceding char.)
    for name in ("PROJECT", "VOLUME_ID", "TRAEFIK_VERSION",
                 "DEVICE_NAME", "REGION"):
        bare = re.search(r"(?<!\$)\$\{" + name + r"\b", tf)
        assert bare is None, (
            f"unescaped ${{{name}}} would break HCL parsing"
        )
    # Bash command substitution stays un-doubled (only ${/%{ are escaped).
    # Mod 065 moved metadata fetches to IMDSv2 token curls; assert the token
    # PUT survives verbatim (the pre-065 token-less GET form is gone).
    assert (
        '$(curl -sf -X PUT "http://169.254.169.254/latest/api/token"' in tf
    )


def test_mod062_traefik_user_data_hcl_escaped_pip(tmp_path: Path):
    """Same escaping guarantee on the pip variant, whose user_data carries
    the additional boot-time DNS-update block."""
    root = _compile_elastic_with_reverse_proxy(tmp_path, "ec2_traefik_pip")
    tf = (
        root / "infra" / "output" / "project" / "production" / "main.tf"
    ).read_text()
    assert "$${PROJECT}" in tf
    for name in ("PROJECT", "VOLUME_ID", "TRAEFIK_VERSION"):
        bare = re.search(r"(?<!\$)\$\{" + name + r"\b", tf)
        assert bare is None


def _tofu_validate(tf_dir: Path) -> subprocess.CompletedProcess:
    """Run `tofu init -backend=false` + `tofu validate` in tf_dir.

    Returns the validate CompletedProcess (init failure is raised eagerly so
    a bad init doesn't masquerade as a validate pass)."""
    init = subprocess.run(
        ["tofu", "init", "-backend=false", "-input=false", "-no-color"],
        cwd=tf_dir, capture_output=True, text=True,
    )
    assert init.returncode == 0, f"tofu init failed:\n{init.stdout}\n{init.stderr}"
    return subprocess.run(
        ["tofu", "validate", "-no-color"],
        cwd=tf_dir, capture_output=True, text=True,
    )


@pytest.mark.integration
@pytest.mark.skipif(shutil.which("tofu") is None, reason="tofu not installed")
@pytest.mark.parametrize("variant", ["ec2_traefik_eip", "ec2_traefik_pip"])
def test_mod062_ec2_traefik_hcl_is_tofu_valid(tmp_path: Path, variant: str):
    """Every tier of an ec2_traefik project emits HCL that OpenTofu accepts.
    This is the coverage the mod-044 substring tests lacked — it parses the
    emitted HCL rather than string-matching it. Regression for mod 062."""
    root = _compile_elastic_with_reverse_proxy(tmp_path, variant)
    out = root / "infra" / "output"
    for tier in ("project/production", "stage", "prod"):
        res = _tofu_validate(out / tier)
        assert res.returncode == 0, (
            f"[{variant}] tofu validate failed for {tier}:\n"
            f"{res.stdout}\n{res.stderr}"
        )


@pytest.mark.parametrize("variant", ["ec2_traefik_eip", "ec2_traefik_pip"])
def test_mod063_user_data_installs_awscli_v2_not_apt(tmp_path: Path, variant: str):
    """The ec2_traefik user_data must NOT apt-install `awscli` /
    `amazon-cloudwatch-agent` (neither exists on Ubuntu 24.04, which aborts
    user_data under `set -e`). It installs AWS CLI v2 from the official bundle
    (load-bearing) and the CloudWatch agent best-effort. Regression for mod 063.
    """
    root = _compile_elastic_with_reverse_proxy(tmp_path, variant)
    tf = (
        root / "infra" / "output" / "project" / "production" / "main.tf"
    ).read_text()
    # The apt line only installs packages that exist on noble.
    assert (
        "apt-get install -y --no-install-recommends curl ca-certificates unzip jq"
        in tf
    )
    # The broken apt package list is gone.
    assert "jq awscli" not in tf
    # AWS CLI v2 bundle install (load-bearing path).
    assert "awscli-exe-linux-" in tf
    assert "/tmp/aws/install" in tf
    # CloudWatch agent is best-effort — its install path can't abort user_data.
    assert "amazon-cloudwatch-agent.deb" in tf
    assert "dpkg -i /tmp/cwagent.deb || apt-get install -f -y || true" in tf


@pytest.mark.parametrize("variant", ["ec2_traefik_eip", "ec2_traefik_pip"])
def test_mod065_user_data_uses_imdsv2_token(tmp_path: Path, variant: str):
    """The user_data must fetch an IMDSv2 session token and pass it on every
    metadata request — the Ubuntu 24.04 AMI enforces token-required IMDS, so a
    raw metadata curl 401s and aborts user_data under `set -e`. Regression for
    mod 065."""
    root = _compile_elastic_with_reverse_proxy(tmp_path, variant)
    tf = (
        root / "infra" / "output" / "project" / "production" / "main.tf"
    ).read_text()
    # A token is fetched via PUT.
    assert "latest/api/token" in tf
    assert "X-aws-ec2-metadata-token-ttl-seconds" in tf
    # Metadata fetches carry the token header.
    assert "X-aws-ec2-metadata-token:" in tf
    # No token-less raw metadata GET survives (every metadata line has a token).
    for line in tf.splitlines():
        if "169.254.169.254/latest/meta-data" in line:
            assert "X-aws-ec2-metadata-token:" in line, (
                f"token-less IMDS fetch would 401 on IMDSv2: {line.strip()}"
            )


@pytest.mark.parametrize("variant", ["ec2_traefik_eip", "ec2_traefik_pip"])
def test_mod066_traefik_instance_carries_acme_purpose_tag(tmp_path: Path, variant: str):
    """The traefik EC2 instance must carry `purpose=ec2_traefik_acme` (like the
    ACME volume). The IAM AttachVolume grant conditions on purpose+project for
    BOTH the volume and instance resources; without the tag on the instance,
    AttachVolume is AccessDenied and user_data aborts before traefik starts.
    Regression for mod 066."""
    root = _compile_elastic_with_reverse_proxy(tmp_path, variant)
    tf = (
        root / "infra" / "output" / "project" / "production" / "main.tf"
    ).read_text()
    # Both the volume and the instance carry the HCL purpose tag.
    assert tf.count('purpose = "ec2_traefik_acme"') == 2, (
        "expected purpose tag on BOTH the acme volume and the traefik instance"
    )
    # Specifically, within the aws_instance block.
    inst = tf.split('resource "aws_instance" "project_traefik"', 1)[1]
    inst_block = inst.split("\nresource ", 1)[0]
    assert 'purpose = "ec2_traefik_acme"' in inst_block


@pytest.mark.parametrize("variant", ["ec2_traefik_eip", "ec2_traefik_pip"])
def test_mod067_user_data_ships_bringup_log_to_cloudwatch(tmp_path: Path, variant: str):
    """user_data installs an EXIT trap that ships its log to the project's
    CloudWatch group, so a failed boot isn't a black box (serial console is
    unreliable on Nitro; SSM may be SCP-denied). Best-effort. Regression for
    mod 067."""
    root = _compile_elastic_with_reverse_proxy(tmp_path, variant)
    tf = (
        root / "infra" / "output" / "project" / "production" / "main.tf"
    ).read_text()
    assert "trap _ship_bringup_log EXIT" in tf
    assert "aws logs put-log-events" in tf
    # Ships to the project's ec2_traefik log group.
    assert "/ec2_traefik" in tf
    # Best-effort: the put must not abort (|| true guards on the shipping path).
    assert "put-log-events" in tf and "|| true" in tf
