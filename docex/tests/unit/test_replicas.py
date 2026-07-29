"""Mod 100 — replicas: the emission half.

`replicas: N` was declared, range-checked and carried onto
``CompiledService`` by Mod 096 and read by no emitter. This module covers the
two emissions it now drives, which share exactly one rule (the ``prod``-only
clamp) and nothing else:

- **elastic** sets a count — one ``aws_ecs_service`` with
  ``desired_count = N``;
- **fixed** cannot set a count (the collector sidecar pairs by netns, and
  Compose has no replica-to-replica pairing), so it unrolls into N distinct
  compose services keyed ``{global_name}-{i}``.

The headline guard is :func:`test_6_dev_test_stage_compose_bytes_unchanged`:
``replicas`` applies in ``prod`` only, so every other env must be
byte-identical to a compile of the same project that declares no ``replicas``
at all. If that test fails, the unroll has leaked into the N == 1 path.

Rule 5's replica seeding (the validator half) is at the bottom, driven off a
source string in ``test_process_nesting.py``'s style rather than off a project
on disk.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest
import yaml

from docex.cicl.compile import CompiledService, effective_replicas, run_compile
from docex.cicl.model import CICLDocument
from docex.cicl.transfer import load_transfer_tables
from docex.cicl.validate import validate_document
from docex.context import load_project_context


_FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
_FIXED = _FIXTURES / "sample_project"
_ELASTIC = _FIXTURES / "sample_project_elastic"

_WEB_REPLICAS = 2
_WORKER_REPLICAS = 4

# The three-process project from `test_process_expansion_emit.py`: one
# codebase, one web process, one worker, one scheduler. The worker is
# single-network (`internal`) and the web process is multi-network
# (`web` + `internal`) — which is what lets test 3 pin "the alias goes on
# EVERY network" rather than on the only network there happens to be.
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


def _project(fixture: Path, tmp_path: Path, *, replicas: bool) -> Path:
    """The three-process project, with or without the `replicas:` keys.

    The two variants differ by exactly those two keys, which is what makes a
    byte-level diff of their non-`prod` output meaningful.
    """
    root = tmp_path / "project"
    shutil.copytree(fixture, root, dirs_exist_ok=False)
    shutil.rmtree(root / "infra" / "output", ignore_errors=True)

    infra_path = root / "infra" / "infra.yml"
    doc = yaml.safe_load(infra_path.read_text())
    procs = doc["core_services"]["api"]["processes"]
    procs["worker"] = dict(_WORKER)
    procs["nightly_cleanup"] = dict(_NIGHTLY)
    if replicas:
        procs["web"]["replicas"] = _WEB_REPLICAS
        procs["worker"]["replicas"] = _WORKER_REPLICAS
    infra_path.write_text(yaml.safe_dump(doc, sort_keys=False))
    return root


def _compiled(fixture: Path, tmp_path: Path, *, replicas: bool) -> Path:
    root = _project(fixture, tmp_path, replicas=replicas)
    assert run_compile(load_project_context(root)) == 0
    return root


@pytest.fixture(scope="module")
def fixed_root(tmp_path_factory) -> Path:
    return _compiled(_FIXED, tmp_path_factory.mktemp("fixed"), replicas=True)


@pytest.fixture(scope="module")
def fixed_plain_root(tmp_path_factory) -> Path:
    return _compiled(
        _FIXED, tmp_path_factory.mktemp("fixed_plain"), replicas=False
    )


@pytest.fixture(scope="module")
def elastic_root(tmp_path_factory) -> Path:
    return _compiled(_ELASTIC, tmp_path_factory.mktemp("elastic"), replicas=True)


@pytest.fixture(scope="module")
def elastic_plain_root(tmp_path_factory) -> Path:
    return _compiled(
        _ELASTIC, tmp_path_factory.mktemp("elastic_plain"), replicas=False
    )


def _compose_path(root: Path, env: str) -> Path:
    return root / "infra" / "output" / env / "docker-compose.yml"


def _compose(root: Path, env: str) -> dict:
    return yaml.safe_load(_compose_path(root, env).read_text())


def _hcl(root: Path, env: str) -> str:
    return (root / "infra" / "output" / env / "main.tf").read_text()


def _resources(hcl: str, kind: str) -> list[str]:
    return re.findall(rf'^resource "{kind}" "([^"]+)" \{{', hcl, flags=re.M)


def _slice(hcl: str, kind: str, name: str) -> str:
    marker = f'resource "{kind}" "{name}" {{'
    idx = hcl.index(marker)
    rest = hcl[idx:]
    return rest[: rest.index("\n}\n") + 2]


_WORKER_KEYS = [
    f"sample-prod-api-worker-{i}" for i in range(1, _WORKER_REPLICAS + 1)
]
_WEB_KEYS = [f"sample-prod-api-web-{i}" for i in range(1, _WEB_REPLICAS + 1)]


# ---------------------------------------------------------------------------
# 1-10 — fixed emission.
# ---------------------------------------------------------------------------


def test_1_prod_unrolls_into_n_distinct_services(fixed_root: Path):
    services = _compose(fixed_root, "prod")["services"]
    for key in _WORKER_KEYS + _WEB_KEYS:
        assert key in services
    # The unqualified name belongs to no container any more — it is carried
    # by the network alias (test 3) instead.
    assert "sample-prod-api-worker" not in services
    assert "sample-prod-api-web" not in services


def test_2_container_name_matches_the_compose_key(fixed_root: Path):
    services = _compose(fixed_root, "prod")["services"]
    for key in _WORKER_KEYS + _WEB_KEYS:
        assert services[key]["container_name"] == key


@pytest.mark.parametrize(
    "keys,unqualified,nets",
    [
        (_WORKER_KEYS, "sample-prod-api-worker", {"internal"}),
        (_WEB_KEYS, "sample-prod-api-web", {"internal", "web"}),
    ],
)
def test_3_every_network_carries_the_shared_alias(
    fixed_root: Path, keys: list[str], unqualified: str, nets: set[str],
):
    """`provides.host` still resolves to "the process type" after the unroll,
    because the unqualified name is a Docker DNS alias on all N replicas.

    The alias is on EVERY network the process type joins — a consumer resolves
    the target over whichever network the two share, so restricting it to
    non-`web` networks would break a web→web reference for no gain.
    """
    services = _compose(fixed_root, "prod")["services"]
    for key in keys:
        networks = services[key]["networks"]
        assert isinstance(networks, dict), "unroll must use map form"
        assert set(networks) == nets
        for net in nets:
            assert networks[net] == {"aliases": [unqualified]}


def test_4_one_sidecar_per_replica_paired_by_netns(fixed_root: Path):
    services = _compose(fixed_root, "prod")["services"]
    sidecars = sorted(k for k in services if k.endswith("-otelcol"))
    assert sidecars == sorted(
        f"{k}-otelcol" for k in _WORKER_KEYS + _WEB_KEYS
    )
    for key in _WORKER_KEYS + _WEB_KEYS:
        sidecar = services[f"{key}-otelcol"]
        assert sidecar["network_mode"] == f"service:{key}"
        assert sidecar["container_name"] == f"{key}-otelcol"
    # The app side of the pairing is untouched: still loopback, still the
    # same on every replica and every foundation.
    endpoints = {
        services[k]["environment"]["OTEL_EXPORTER_OTLP_ENDPOINT"]
        for k in _WORKER_KEYS + _WEB_KEYS
    }
    assert endpoints == {"http://localhost:4318"}


def test_5_replicas_declare_one_traefik_router_and_one_service(
    fixed_root: Path,
):
    """Traefik aggregates the replicas into one backend because every replica
    emits the SAME labels, keyed on the unqualified name. Qualifying them per
    replica would produce N routers fighting over one Host() rule.
    """
    services = _compose(fixed_root, "prod")["services"]
    label_sets = [services[k]["labels"] for k in _WEB_KEYS]
    assert label_sets[0] == label_sets[1]
    routers, svcs = set(), set()
    for label in label_sets[0]:
        if m := re.search(r"traefik\.http\.routers\.([^.]+)\.", label):
            routers.add(m.group(1))
        if m := re.search(r"traefik\.http\.services\.([^.]+)\.", label):
            svcs.add(m.group(1))
    assert routers == {"sample-prod-api-web"}
    assert svcs == {"sample-prod-api-web"}


@pytest.mark.parametrize("env", ["dev", "test", "stage"])
def test_6_dev_test_stage_compose_bytes_unchanged(
    fixed_root: Path, fixed_plain_root: Path, env: str,
):
    """The blast-radius guard. `replicas` applies in `prod` only, so every
    other env must emit exactly what it emitted before this mod — no alias
    map, no `-1` suffix, no extra sidecar, no moved key or changed spacing.

    Compared as BYTES, not as parsed YAML: the point is that nothing about
    ordering, quoting or key set moved either.
    """
    assert (
        _compose_path(fixed_root, env).read_text()
        == _compose_path(fixed_plain_root, env).read_text()
    )


def test_7_prod_top_level_sections_unchanged(
    fixed_root: Path, fixed_plain_root: Path,
):
    """The `_named_volumes` guard: that helper walks `compiled.services`, not
    the emitted ones, so a volume introduced by a derived compose service
    would never be declared top-level. The unroll introduces none — each
    replica copies the compiled body — and this pins it.
    """
    got = _compose(fixed_root, "prod")
    want = _compose(fixed_plain_root, "prod")
    assert got.get("networks") == want.get("networks")
    assert got.get("volumes") == want.get("volumes")


def test_8_no_host_ports_on_any_replica(fixed_root: Path):
    """The property that makes the unroll viable at all: no core process type
    publishes a host port, so N copies cannot collide on one."""
    services = _compose(fixed_root, "prod")["services"]
    for key in _WORKER_KEYS + _WEB_KEYS:
        assert "ports" not in services[key]


def test_9_depends_on_second_pass_reaches_derived_services(fixed_root: Path):
    services = _compose(fixed_root, "prod")["services"]
    for key in _WORKER_KEYS + _WEB_KEYS:
        assert services[key]["depends_on"] == {
            "sample-prod-appdb": {"condition": "service_healthy"}
        }


def test_10_exec_service_does_not_multiply(fixed_root: Path):
    """The exec service is per CODEBASE. Four worker replicas are still one
    codebase, one image, one operations container."""
    services = _compose(fixed_root, "prod")["services"]
    assert [k for k in services if k.endswith("-exec")] == [
        "sample-prod-api-exec"
    ]


# ---------------------------------------------------------------------------
# 11-13 — elastic emission: a count, never an unroll.
# ---------------------------------------------------------------------------


def test_11_prod_desired_count_is_the_declared_replicas(elastic_root: Path):
    hcl = _hcl(elastic_root, "prod")
    assert f"  desired_count   = {_WORKER_REPLICAS}" in _slice(
        hcl, "aws_ecs_service", "api-worker"
    )
    assert f"  desired_count   = {_WEB_REPLICAS}" in _slice(
        hcl, "aws_ecs_service", "api-web"
    )
    # No unroll on elastic: one service and one task definition per process
    # type, exactly as before the mod.
    assert sorted(_resources(hcl, "aws_ecs_service")) == ["api-web", "api-worker"]
    assert sorted(
        n for n in _resources(hcl, "aws_ecs_task_definition")
        if not n.endswith("_migrate")
    ) == ["api-nightly_cleanup", "api-web", "api-worker"]


def test_12_stage_clamps_to_one(elastic_root: Path):
    hcl = _hcl(elastic_root, "stage")
    for name in ("api-web", "api-worker"):
        assert "  desired_count   = 1" in _slice(hcl, "aws_ecs_service", name)


@pytest.mark.parametrize("env", ["stage", "prod"])
def test_13_undeclared_replicas_emit_the_pre_mod_line_verbatim(
    elastic_plain_root: Path, env: str,
):
    """A project that declares no `replicas` gets the literal pre-mod line
    back, three-space alignment included."""
    hcl = _hcl(elastic_plain_root, env)
    names = _resources(hcl, "aws_ecs_service")
    assert names, "fixture emits no ECS services — test would be vacuous"
    for name in names:
        assert "  desired_count   = 1\n" in _slice(hcl, "aws_ecs_service", name)


# ---------------------------------------------------------------------------
# 14 — the clamp itself.
# ---------------------------------------------------------------------------


def _svc(*, is_core: bool, replicas: int) -> CompiledService:
    return CompiledService(
        name="api-worker", role="worker" if is_core else "relational_db",
        engine="python" if is_core else "postgres", foundation="fixed",
        is_core=is_core, global_name="sample-prod-api-worker", body={},
        networks=["internal"], depends_on=[], port=None, env={},
        replicas=replicas,
    )


@pytest.mark.parametrize("env", ["dev", "test", "stage"])
def test_14a_clamped_to_one_outside_prod(env: str):
    assert effective_replicas(_svc(is_core=True, replicas=4), env) == 1


def test_14b_declared_count_applies_in_prod():
    assert effective_replicas(_svc(is_core=True, replicas=4), "prod") == 4


def test_14c_backing_services_never_replicate():
    assert effective_replicas(_svc(is_core=False, replicas=4), "prod") == 1


# ---------------------------------------------------------------------------
# 15-16 — rule 5 gains the replica index.
# ---------------------------------------------------------------------------


_HEAD = """
cicl_version: "2"
foundation: fixed
apex_domain: example.com
observability_backend_url: "https://obs.example.com"
container_registry: registry.example.com
"""


def _issues(src: str) -> list:
    doc = CICLDocument.model_validate(yaml.safe_load(src))
    return validate_document(doc, load_transfer_tables(project_root=None))


def _collision_doc(replicas: int) -> str:
    """`api` with process types `web` (replicas: N) and `web-1`.

    Replica 1 of `web` renders `api-web-1`, byte-identical to the `web-1`
    process type's own compiled identity — one compose key in prod-fixed, one
    container silently clobbering the other.
    """
    return _HEAD + f"""
core_services:
  api:
    processes:
      web:
        role: worker
        replicas: {replicas}
        command: ["python", "-m", "x"]
        networks: [internal]
        resources:
          cpu: 0.5
          memory: 512MB
      web-1:
        role: worker
        command: ["python", "-m", "x"]
        networks: [internal]
        resources:
          cpu: 0.5
          memory: 512MB
"""


def test_15_replica_index_collision_rejected():
    issues = [
        i for i in _issues(_collision_doc(3))
        if i.rule == "rule_5_rendered_identity_collision"
    ]
    assert len(issues) == 1
    message = issues[0].message
    # The author never wrote a service called "replica 1 of api.web"; the
    # message has to name the derivative or it reads as a bug in docex.
    assert "replica 1" in message
    assert "'api-web-1'" in message


def test_16_replicas_one_is_not_a_collision():
    """The rule does not forbid a name that collides with nothing: with a
    count of 1 the `-1` suffix is never emitted by anything."""
    assert [
        i for i in _issues(_collision_doc(1))
        if i.rule == "rule_5_rendered_identity_collision"
    ] == []
