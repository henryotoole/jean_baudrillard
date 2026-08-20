"""Tests for the `worker` role.

Covers the role table's shape, the fixed (compose) healthcheck emit, the
elastic (ECS container-level healthCheck) emit and its deliberate absence of a
target group, and — in `test_container_definition_emits_no_resource` and
`test_merge_target_leaves_no_gap_when_not_last` alone — the no-op
`container_definition` destination (mod 095). That destination is no longer the
probe's delivery path and no shipped field routes to it; it remains a declared,
available merge target.

Mod 125: rule 28 (`health_check_path` obliges a `port`) is RETIRED and its
three tests are gone with it, along with `_WORKER_DOC`. Rule 33 confines
`health_check_path` to `web`-network core services and rule 15 already requires
a `port` on those, so there is no document left in which rule 28 could fire;
rule 33's own coverage lives in `test_validate.py`.

Mod 127: the injected worker declares no `health_check_path` — rule 33 forbids
it — and gets a probe anyway, because the probe is a role-table DEFAULT rather
than a field translation. The field is now gone from the worker table
entirely, so rule 4 rejects it there (asserted below).

Unit tests only — nothing here crosses docker, AWS, or git.

The shared fixtures are NOT modified. Each compile test copies
``sample_project`` / ``sample_project_elastic`` into ``tmp_path`` and injects
a ``worker`` **core service** onto the copy's ``api`` core service. Adding a
permanent core service to the shared fixtures would churn unrelated emitter
tests.

Mod 096: the injection moved from a flat sibling *service* to a second
core service of the *same codebase*, which is the shape the worker role was
always for — one image, two ways to invoke it. The compiled identities are
therefore ``api-web`` and ``api-worker``, and both reference
``sample/api:0.1.0``.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

import yaml

from docex.cicl.compile import run_compile
from docex.cicl.model import CICLDocument
from docex.cicl.transfer import load_transfer_tables
from docex.cicl.validate import validate_document
from docex.context import load_project_context
from docex.emit.hcl import _DESTINATION_RENDERERS, render_container_definition


_FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
_FIXED = _FIXTURES / "sample_project"
_ELASTIC = _FIXTURES / "sample_project_elastic"


_WORKER: dict[str, Any] = {
    "role": "worker",
    "command": ["python", "-m", "entrypoints.worker"],
    # Rule 33 forbids `health_check_path` off the `web` network, so the injected
    # worker declares none. `port: 8090` stays: the injected worker is nobody's
    # `uses` target, so rule 32 is silent on it (the declined asymmetry, filed as
    # 008_housekeeping/references/rule_32_unused_target_port.md).
    "port": 8090,
    "networks": ["internal"],
    "uses": ["appdb"],
    "resources": {"cpu": 0.5, "memory": "1GB", "disk": "25GB"},
}


def _copy(fixture: Path, tmp_path: Path) -> Path:
    dest = tmp_path / "project"
    shutil.copytree(fixture, dest, dirs_exist_ok=False)
    out = dest / "infra" / "output"
    if out.exists():
        shutil.rmtree(out)
    return dest


def _inject_worker(root: Path) -> None:
    """Add a ``worker`` core service to the fixture's ``api`` codebase.

    Mod 096: no ``core/worker/`` folder is created, and that is the point —
    the worker shares ``api``'s build artifact, so the compose build context
    and the image ref stay ``./core/api`` / ``sample/api:0.1.0``.
    """
    infra_path = root / "infra" / "infra.yml"
    doc = yaml.safe_load(infra_path.read_text())
    doc["codebases"]["api"]["core_services"]["worker"] = dict(_WORKER)
    infra_path.write_text(yaml.safe_dump(doc, sort_keys=False))


def _compile_with_worker(
    fixture: Path, tmp_path: Path, *, emits_elastic: list[str] | None = None
) -> Path:
    root = _copy(fixture, tmp_path)
    _inject_worker(root)
    if emits_elastic is not None:
        # Project-local tables deep-merge over the bundled ones, and a list
        # value is replaced wholesale — so this reorders the worker's elastic
        # emit destinations without touching tables/roles/worker.yml.
        tt = root / "infra" / "transfer_tables"
        tt.mkdir(parents=True, exist_ok=True)
        (tt / "worker_order.yml").write_text(yaml.safe_dump(
            {"roles": {"worker": {"container": {
                "emits": {"elastic": emits_elastic},
            }}}}
        ))
    run_compile(load_project_context(root))
    return root


def _dev_compose(root: Path) -> dict:
    return yaml.safe_load(
        (root / "infra" / "output" / "dev" / "docker-compose.yml").read_text()
    )


def _stage_hcl(root: Path) -> str:
    return (root / "infra" / "output" / "stage" / "main.tf").read_text()


def _slice_td(hcl: str, td_name: str) -> str:
    marker = f'resource "aws_ecs_task_definition" "{td_name}" {{'
    idx = hcl.index(marker)
    rest = hcl[idx:]
    return rest[: rest.index("\n}\n") + 2]


def _container_block(hcl: str, td_name: str, container_name: str) -> str:
    """Return the text of one container entry inside a task definition.

    The `container_definitions = jsonencode([...])` body is HCL object
    syntax (unquoted keys, `=` separators), not JSON, so it is sliced
    textually. Entries sit at indent 4 and are comma-separated.
    """
    body = _slice_td(hcl, td_name)
    start = body.index("container_definitions = jsonencode([\n")
    start += len("container_definitions = jsonencode([\n")
    end = body.index("\n  ])", start)
    for chunk in body[start:end].split("\n    },\n"):
        if f'name = "{container_name}"' in chunk:
            return chunk
    raise AssertionError(
        f"container {container_name!r} not found in task definition {td_name!r}"
    )


def _tables():
    return load_transfer_tables(project_root=None)


def _doc(src: str) -> CICLDocument:
    return CICLDocument.model_validate(yaml.safe_load(src))


# ---------------------------------------------------------------------------
# 1. Role table shape
# ---------------------------------------------------------------------------


def test_worker_role_table_shape():
    tables = _tables()
    entry = tables.engine("worker", "container")
    assert entry.foundation == "both"
    assert entry.emits["fixed"] == ["compose_service"]
    assert entry.emits["elastic"] == [
        "task_definition",
        "ecs_service",
        "container_definition",
    ]
    assert "target_group" not in entry.emits["elastic"]
    assert entry.default_port is None
    assert set(entry.provides) == {"host", "port"}
    assert entry.naming == "ecs"


# ---------------------------------------------------------------------------
# 2-3. Fixed (compose) emit
# ---------------------------------------------------------------------------


def test_worker_fixed_compose_healthcheck(tmp_path: Path):
    """A worker's compose probe is `./health.sh worker`, declaring NOTHING.

    The probe is a role-table default, so the worker gets one without
    declaring any field at all — which is the whole point of the move. The
    injected worker declares no `health_check_path` (rule 33 forbids it off
    the `web` network) and still gets a probe.

    Asserted on the LITERAL rather than on presence: the command must name
    this core service (`${service}` -> `worker`), because the shim is invoked
    per core service and a probe naming the wrong one would answer the wrong
    question while looking healthy.
    """
    doc = _dev_compose(_compile_with_worker(_FIXED, tmp_path))
    svc = doc["services"]["sample-dev-api-worker"]
    hc = svc["healthcheck"]
    assert hc["test"] == ["CMD", "./health.sh", "worker"]
    assert hc["interval"] == "30s"
    assert hc["timeout"] == "5s"
    assert hc["retries"] == 3
    # One codebase, one image: the worker runs `api`'s artifact.
    assert svc["image"] == "sample/api:0.1.0"
    assert svc["command"] == ["python", "-m", "entrypoints.worker"]


def test_worker_fixed_no_traefik_labels(tmp_path: Path):
    """A worker is not on the `web` network, so it carries no traefik
    router/service labels."""
    doc = _dev_compose(_compile_with_worker(_FIXED, tmp_path))
    labels = doc["services"]["sample-dev-api-worker"].get("labels", [])
    flat = labels if isinstance(labels, list) else list(labels)
    assert not any("traefik" in str(l) for l in flat)


# ---------------------------------------------------------------------------
# 4-7. Elastic (HCL) emit
# ---------------------------------------------------------------------------


def test_worker_elastic_container_healthcheck(tmp_path: Path):
    """A worker's ECS container `healthCheck` is `./health.sh worker`.

    **It does NOT arrive via `container_definition`.** `defaults:` cannot route
    to a non-default target (transfer_tables.md), so the probe lands on the
    engine's default elastic target — `task_definition` — and is lifted onto the
    container by an explicit named read in `render_task_definition`. A reader who
    assumes the merge target will look in the wrong place when this breaks. See
    `plans/modifications/127_probe_becomes_a_command/overview.md` § 2.

    `startPeriod` is elastic-only: ECS kills and replaces a task whose essential
    container fails, so the start grace prevents a wedged-looking container being
    killed before it has written its first tick (overview.md Q2).
    """
    hcl = _stage_hcl(_compile_with_worker(_ELASTIC, tmp_path))
    assert 'resource "aws_ecs_task_definition" "api-worker" {' in hcl
    assert 'resource "aws_ecs_service" "api-worker" {' in hcl

    app = _container_block(hcl, "api-worker", "api-worker")
    assert "healthCheck" in app, app
    assert '["CMD", "./health.sh", "worker"]' in app, app
    assert "startPeriod" in app, app
    # `CMD`, not the retired `CMD-SHELL` curl wrapper: a command probe needs
    # no shell and no `|| exit 1` exit-code laundering.
    assert "CMD-SHELL" not in app, app
    assert "curl" not in app, app


def test_worker_elastic_no_target_group(tmp_path: Path):
    hcl = _stage_hcl(_compile_with_worker(_ELASTIC, tmp_path))
    assert 'resource "aws_lb_target_group" "api-worker"' not in hcl
    assert 'resource "aws_lb_listener_rule" "api-worker"' not in hcl
    # Guard against a vacuous pass: the web service's own target group and
    # listener rule must still be emitted.
    assert 'resource "aws_lb_target_group" "api-web"' in hcl
    assert 'resource "aws_lb_listener_rule" "api-web"' in hcl


def test_worker_elastic_sidecar_has_no_healthcheck(tmp_path: Path):
    """The merge lands on the app container only — never on the paired
    OTel collector sidecar."""
    hcl = _stage_hcl(_compile_with_worker(_ELASTIC, tmp_path))
    sidecar = _container_block(hcl, "api-worker", "api-worker-otelcol")
    assert "healthCheck" not in sidecar


def test_container_definition_emits_no_resource(tmp_path: Path):
    """`container_definition` is a merge target: it contributes no HCL
    resource block and no defensive `# unknown destination` comment."""
    hcl = _stage_hcl(_compile_with_worker(_ELASTIC, tmp_path))
    assert "unknown destination" not in hcl
    # No resource block whose type derives from the destination name. (The
    # bare string `container_definitions` does appear — it is the ECS task
    # definition's own argument, not a resource.)
    types = set(re.findall(r'^resource "([a-z0-9_]+)" ', hcl, flags=re.M))
    assert not any("container_definition" in t for t in types)
    assert 'resource "aws_ecs_task_definition" "api-worker" {' in hcl
    # The destination is registered in the dispatch table (so it never hits
    # the defensive branch) and renders nothing, which `render_service` then
    # skips rather than appending as a blank gap.
    assert _DESTINATION_RENDERERS["container_definition"] is (
        render_container_definition
    )
    assert render_container_definition(None, None) == ""  # type: ignore[arg-type]


def test_merge_target_leaves_no_gap_when_not_last(tmp_path: Path):
    """A merge-target destination emits no blank gap wherever it sits.

    `container_definition` is last in the bundled worker table, where the
    dispatch loop's trailing `.rstrip()` would hide a stray append. Reorder
    it into the middle so the skip-empty branch in `render_service` is the
    only thing standing between the task definition and the ECS service.
    """
    hcl = _stage_hcl(_compile_with_worker(
        _ELASTIC, tmp_path,
        emits_elastic=["task_definition", "container_definition", "ecs_service"],
    ))
    assert '}\n\nresource "aws_ecs_service" "api-worker" {' in hcl


# ---------------------------------------------------------------------------
# 8. Rule 12 — a `target: container_definition` must be declared in emits
# ---------------------------------------------------------------------------


_ELASTIC_DOC = """
cicl_version: "3"
foundation: elastic
apex_domain: example.com
observability_backend_url: "https://obs.example.com"
codebases:
  api:
    core_services:
      web:
        role: web
        command: ["python", "/service/dist/root.py"]
        networks: [web, internal]
        port: 8080
        uses: [appdb]
        resources:
          cpu: 1.0
          memory: 2GB
backing_services:
  appdb:
    role: relational_db
    engine: postgres
    version: "15"
    networks: [internal]
    port: 5432
    schema_owned_by: api
"""


_FIXED_WORKER_DOC = """
cicl_version: "3"
foundation: fixed
apex_domain: example.com
container_registry: registry.example.com
observability_backend_url: "https://obs.example.com"
codebases:
  api:
    core_services:
      worker:
        role: worker
        command: ["python", "-m", "entrypoints.worker"]
        networks: [internal]
        health_check_path: /health
        resources:
          cpu: 0.25
          memory: 512MB
"""


def test_health_check_path_on_worker_rejected_by_rule_4():
    """Mod 127 deleted `health_check_path` from the worker role table entirely.

    Rule 4 (`tt_rule_4_undeclared_field`) therefore rejects it on a worker,
    which is how rule 33's NEGATIVE arm — the field is confined to `web`-network
    core services — is enforced at the table layer with no second rule. The same
    mechanism `clock.yml` already documents for `schedules`.

    Membership, not exclusivity: rule 33 fires here too, and asserting a single
    rule id would make the test brittle against the aggregation the validator is
    built on.
    """
    issues = validate_document(_doc(_FIXED_WORKER_DOC), _tables())
    assert "tt_rule_4_undeclared_field" in [i.rule for i in issues]


def test_field_target_container_definition_undeclared_rejected(tmp_path: Path):
    """Routing a field to `target: container_definition` without declaring
    the destination in the engine's `emits.elastic` fails rule 12."""
    proj = tmp_path / "proj"
    (proj / "infra" / "transfer_tables").mkdir(parents=True)
    override = {
        "roles": {
            "relational_db": {
                "postgres": {
                    "fields": {
                        "version": {
                            "elastic": {
                                # postgres's emits.elastic omits it.
                                "target": "container_definition",
                                "engine_version": "${field_value}",
                            },
                        },
                    },
                }
            }
        }
    }
    (proj / "infra" / "transfer_tables" / "override.yml").write_text(
        yaml.safe_dump(override)
    )
    tables = load_transfer_tables(project_root=proj)
    issues = validate_document(_doc(_ELASTIC_DOC), tables)
    assert "FIELD_TARGET_UNDECLARED" in [i.rule for i in issues]
