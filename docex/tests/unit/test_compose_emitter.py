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
    api = _find_core_service_block(services, "api-web")
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
        api = _find_core_service_block(services, "api-web")
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
        api = _find_core_service_block(services, "api-web")
        tmpfs = api.get("tmpfs") or []
        assert tmpfs == ["/tmp:size=20g"], (env, tmpfs)


def test_backing_service_never_gets_core_bind_mounts(tmp_path: Path):
    """Even on dev, backing (non-core) services must not get core bind mounts."""
    root = _copy_fixture(tmp_path)
    ctx = load_project_context(root)
    run_compile(ctx)

    services = _compose_services(root, "dev")
    appdb = _find_core_service_block(services, "appdb")
    volumes = appdb.get("volumes") or []
    for v in volumes:
        assert "/service/src" not in v, v
        assert "/service/dist" not in v, v


def test_web_service_publishes_no_host_ports(tmp_path: Path):
    """web-network services publish no host ports — Traefik routes to them
    over the docker network."""
    root = _copy_fixture(tmp_path)
    ctx = load_project_context(root)
    run_compile(ctx)
    services = _compose_services(root, "dev")
    api = _find_core_service_block(services, "api-web")
    assert "ports" not in api, api.get("ports")


def test_default_web_service_traefik_dual_host(tmp_path: Path):
    """The domain_default_service (api) routes at BOTH the bare env subdomain
    and its per-service host, per the canonical
    <service>.<env>.<project>.<apex_domain> form (mod 031)."""
    root = _copy_fixture(tmp_path)
    ctx = load_project_context(root)
    run_compile(ctx)
    services = _compose_services(root, "dev")
    api = _find_core_service_block(services, "api-web")
    rule = next(l for l in (api.get("labels") or []) if ".rule=" in l)
    assert "Host(`dev.sample.example.com`)" in rule
    assert "Host(`api-web.dev.sample.example.com`)" in rule


def test_prod_default_web_service_traefik_triple_host(tmp_path: Path):
    """Mod 031: in prod, the domain_default_service additionally answers
    at the bare-project host (<project>.<apex_domain>), replacing the old
    `www.<apex>` convention."""
    root = _copy_fixture(tmp_path)
    ctx = load_project_context(root)
    run_compile(ctx)
    services = _compose_services(root, "prod")
    api = _find_core_service_block(services, "api-web")
    rule = next(l for l in (api.get("labels") or []) if ".rule=" in l)
    assert "Host(`api-web.prod.sample.example.com`)" in rule
    assert "Host(`prod.sample.example.com`)" in rule
    assert "Host(`sample.example.com`)" in rule


def test_backing_service_on_web_is_routed(tmp_path: Path):
    """Routing is network-driven: a backing service placed on `web` gets
    Traefik labels too, at its per-service host."""
    root = _copy_fixture(tmp_path)
    infra_yml = root / "infra" / "infra.yml"
    # Put the (ported) appdb on the web network.
    infra_yml.write_text(
        infra_yml.read_text().replace("networks: [internal]", "networks: [web, internal]")
    )
    ctx = load_project_context(root)
    run_compile(ctx)
    services = _compose_services(root, "dev")
    appdb = _find_core_service_block(services, "appdb")
    labels = appdb.get("labels") or []
    assert "traefik.enable=true" in labels
    rule = next(l for l in labels if ".rule=" in l)
    assert "Host(`appdb.dev.sample.example.com`)" in rule


def test_exec_gate_is_service_healthy_and_no_other_block_is_gated(tmp_path: Path):
    """The exec block is the compiler's ONE remaining ordering emission.

    `uses` emits nothing onto a core or backing service's own block (cicl.md
    § Uses Relationships), so `depends_on:` may appear on the `-exec` block and
    nowhere else. The exec gate itself must stay LONG-FORM: `api` uses `appdb`
    (postgres → the engine table declares a healthcheck), so the condition must
    be `service_healthy`, not `service_started` and not a bare list. A
    downgrade here races every first migration against its database and
    surfaces as a flaky migration rather than as a compiler bug.
    """
    root = _copy_fixture(tmp_path)
    ctx = load_project_context(root)
    run_compile(ctx)

    services = _compose_services(root, "dev")

    exec_keys = [k for k in services if k.endswith("-exec")]
    assert exec_keys, sorted(services)
    for key in exec_keys:
        deps = services[key].get("depends_on")
        assert isinstance(deps, dict), (
            f"{key}: expected long-form depends_on map, got {deps!r}"
        )
        appdb_key = next((k for k in deps if k.endswith("appdb")), None)
        assert appdb_key is not None, f"appdb not in {key}.depends_on: {sorted(deps)}"
        assert deps[appdb_key] == {"condition": "service_healthy"}, deps[appdb_key]

    for name, block in services.items():
        if name.endswith("-exec"):
            continue
        assert "depends_on" not in block, (
            f"{name} carries depends_on: {block['depends_on']!r} — `uses` emits "
            f"nothing onto a core or backing service's own block"
        )


def test_web_network_is_project_env_external_and_others_are_project_scoped(tmp_path: Path):
    """Mod 036 flip: env compose's ``web`` short-name now references the
    project-tier ``${project}-${env}-web`` network with ``external: true``;
    every other network keeps ``${project}-${env}-${name}`` scoping and is
    a plain project-scoped bridge — no ``internal: true`` (mod 110). The
    per-project traefik (owned by projinfra) spans all four ``-web``
    networks."""
    root = _copy_fixture(tmp_path)
    ctx = load_project_context(root)
    run_compile(ctx)

    for env in ("dev", "test", "stage", "prod"):
        path = root / "infra" / "output" / env / "docker-compose.yml"
        doc = yaml.safe_load(path.read_text())
        networks = doc["networks"]

        # The project's name in the sample fixture is "sample".
        assert networks["web"] == {
            "name": f"sample-{env}-web",
            "external": True,
        }, (env, networks["web"])
        # `internal` (or any other CICL-defined network) stays
        # project-scoped, as a plain bridge.
        internal = networks["internal"]
        assert internal["name"] == f"sample-{env}-internal", internal
        # Mod 110: no ``internal: true``. It buys no ingress protection
        # (inter-bridge isolation and the absent published ports already
        # give that) and its only real effect is killing egress, which
        # contradicts networks.md § Egress and elastic's allow-all SG.
        assert "internal" not in internal, internal


def test_non_web_only_service_is_not_egress_isolated(tmp_path: Path):
    """A service attached only to non-``web`` networks must still reach the
    internet. Docker's ``internal: true`` strips the bridge's masquerade
    rule, so any network carrying it denies egress to every container whose
    only attachment is that network. Two concrete breakages that caused
    (mod 110):

    1. A ``worker``/``clock`` core service's paired OTel sidecar shares
       its partner's netns via ``network_mode: service:<container>``, so a
       ``[internal]``-only partner stranded the sidecar with no route to
       ``OBSERVABILITY_BACKEND_URL`` — Class-1 telemetry silently dead in
       fixed ``stage``/``prod``.
    2. A ``worker`` calling a third-party API simply could not reach it.

    Assert against the whole ``networks:`` block rather than the ``internal``
    short-name alone, so a project declaring further non-``web`` networks is
    covered too.
    """
    root = _copy_fixture(tmp_path)
    ctx = load_project_context(root)
    run_compile(ctx)

    for env in ("dev", "test", "stage", "prod"):
        path = root / "infra" / "output" / env / "docker-compose.yml"
        doc = yaml.safe_load(path.read_text())
        for short, block in (doc.get("networks") or {}).items():
            assert "internal" not in block, (env, short, block)


def test_web_router_emits_certresolver_doctrine(tmp_path: Path):
    """Per doctrine transfer_tables.md § Foundation Invariants §
    Per-container (fixed), web-network services must carry a
    tls.certresolver=doctrine label so Traefik knows which resolver to
    use for cert acquisition."""
    root = _copy_fixture(tmp_path)
    ctx = load_project_context(root)
    run_compile(ctx)

    services = _compose_services(root, "dev")
    api = _find_core_service_block(services, "api-web")
    labels = api.get("labels") or []
    # Must include the certresolver label keyed by the service's global name.
    expected_suffix = ".tls.certresolver=doctrine"
    assert any(l.endswith(expected_suffix) for l in labels), labels


def test_exec_gate_is_service_started_when_target_has_no_healthcheck(tmp_path: Path):
    """A gate target without a healthcheck must get service_started. We add
    a project-local transfer table for a custom no-healthcheck backing
    role and point api at it via `uses`. (Mod 031 removed the bundled
    `reverse_proxy` role that used to serve this purpose.)"""
    import yaml as _yaml
    root = _copy_fixture(tmp_path)
    # Project-local transfer table defining a no-healthcheck role.
    tt_dir = root / "infra" / "transfer_tables"
    tt_dir.mkdir(parents=True, exist_ok=True)
    (tt_dir / "no_health.yml").write_text(_yaml.safe_dump({
        "roles": {
            "no_health": {
                "noop": {
                    "foundation": "fixed",
                    "emits": {"fixed": ["compose_service"]},
                    "defaults": {"fixed": {"image": "busybox:latest"}},
                    "provides": {"host": {"fixed": "${global_service_name}"}},
                    "naming": "docker",
                },
            },
        },
    }))
    infra_yml = root / "infra" / "infra.yml"
    original = infra_yml.read_text()
    modified = original.replace(
        "    uses: [appdb]",
        "    uses: [appdb, proxy]",
        1,
    ) + (
        "\n  proxy:\n"
        "    role: no_health\n"
        "    engine: noop\n"
        "    networks: [web]\n"
        "    port: 80\n"
    )
    infra_yml.write_text(modified)

    ctx = load_project_context(root)
    run_compile(ctx)

    services = _compose_services(root, "dev")
    exec_key = next(k for k in services if k.endswith("-api-exec"))
    deps = services[exec_key].get("depends_on")
    assert isinstance(deps, dict), f"expected long-form depends_on map, got {deps!r}"
    proxy_key = next((k for k in deps if k.endswith("proxy")), None)
    assert proxy_key is not None, f"proxy not in {exec_key}.depends_on: {sorted(deps)}"
    # Confirm the proxy block really has no healthcheck (guards the test
    # against silently degrading if a future doctrine change adds one).
    proxy_block = services[proxy_key]
    assert "healthcheck" not in proxy_block, proxy_block
    assert deps[proxy_key] == {"condition": "service_started"}, deps[proxy_key]


def test_core_service_compose_environment_carries_project_version(tmp_path: Path):
    """Every core service's compose `environment:` block carries
    PROJECT_VERSION sourced from project.yml.version, on every env
    (dev/test/stage/prod). Mod 011."""
    root = _copy_fixture(tmp_path)
    ctx = load_project_context(root)
    run_compile(ctx)
    expected_version = ctx.project.version

    for env in ("dev", "test", "stage", "prod"):
        services = _compose_services(root, env)
        api = _find_core_service_block(services, "api-web")
        environment = api.get("environment") or {}
        assert environment.get("PROJECT_VERSION") == expected_version, (
            env, environment
        )


def test_core_service_carries_docex_project_label(tmp_path: Path):
    """Mod 051 (Gap B): every web core service appends the docex.project
    label to its existing Traefik discovery labels (one labels key, not two)."""
    root = _copy_fixture(tmp_path)
    ctx = load_project_context(root)
    run_compile(ctx)

    services = _compose_services(root, "dev")
    api = _find_core_service_block(services, "api-web")
    labels = api.get("labels") or []
    assert "docex.project=sample" in labels, labels
    # Discovery labels are still present alongside it — appended, not replaced.
    assert "traefik.enable=true" in labels, labels


def test_test_env_web_service_has_no_traefik_labels(tmp_path: Path):
    """Mod 054: a `test`-env web service keeps the docex.project label but
    carries NO traefik.* discovery labels (no router, no tls, no
    certresolver) — `test` is excluded from web routing entirely so its
    bring-up never fires an LE HTTP-01 challenge. dev/stage/prod keep the
    full traefik label set."""
    root = _copy_fixture(tmp_path)
    ctx = load_project_context(root)
    run_compile(ctx)

    # `test`: docex.project present, but no traefik labels at all.
    test_api = _find_core_service_block(_compose_services(root, "test"), "api-web")
    test_labels = test_api.get("labels") or []
    assert "docex.project=sample" in test_labels, test_labels
    assert not any(l.startswith("traefik.") for l in test_labels), test_labels

    # dev/stage/prod: full traefik discovery set still present alongside
    # the docex.project label.
    for env in ("dev", "stage", "prod"):
        api = _find_core_service_block(_compose_services(root, env), "api-web")
        labels = api.get("labels") or []
        assert "docex.project=sample" in labels, (env, labels)
        assert "traefik.enable=true" in labels, (env, labels)
        assert any(l.endswith(".tls.certresolver=doctrine") for l in labels), (
            env, labels,
        )


def test_backing_service_carries_docex_project_label(tmp_path: Path):
    """Mod 051 (Gap B): a non-web backing service gets a fresh labels list
    with just the docex.project label."""
    root = _copy_fixture(tmp_path)
    ctx = load_project_context(root)
    run_compile(ctx)

    services = _compose_services(root, "dev")
    appdb = _find_core_service_block(services, "appdb")
    labels = appdb.get("labels") or []
    assert "docex.project=sample" in labels, labels
    # A purely-internal backing service carries no Traefik discovery labels.
    assert not any(l.startswith("traefik.enable") for l in labels), labels


def test_sidecar_carries_docex_project_label(tmp_path: Path):
    """Mod 051 (Gap B): the OTel sidecar carries the docex.project label too."""
    root = _copy_fixture(tmp_path)
    ctx = load_project_context(root)
    run_compile(ctx)

    services = _compose_services(root, "dev")
    sidecar = next(
        (services[k] for k in services if k.endswith("-otelcol")), None
    )
    assert sidecar is not None, sorted(services)
    assert "docex.project=sample" in (sidecar.get("labels") or []), sidecar.get("labels")


def test_backing_service_compose_environment_lacks_project_version(tmp_path: Path):
    """Backing services do NOT receive PROJECT_VERSION — they run
    third-party software that doesn't consume it. Mod 011."""
    root = _copy_fixture(tmp_path)
    ctx = load_project_context(root)
    run_compile(ctx)

    for env in ("dev", "test", "stage", "prod"):
        services = _compose_services(root, env)
        appdb = _find_core_service_block(services, "appdb")
        environment = appdb.get("environment") or {}
        assert "PROJECT_VERSION" not in environment, (env, environment)
