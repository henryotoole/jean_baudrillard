"""Tests for the clock role (mod 115).

Covers the `schedules:` validation rules, the fixed (compose) and elastic
(HCL) delivery of the schedule table through `DOCEX_SCHEDULES_YAML`, the
elastic stop-then-start deployment percentages, and the `schedules.yml`
visibility artifact.

The delivery assertions are written against the **emitted files**, never
against `render_schedule_table`'s return value: the claim under test is that
the table reaches the container, not that a renderer returns a string.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest
import yaml

from docex.cicl.compile import compile_env, run_compile
from docex.cicl.model import CICLDocument
from docex.cicl.transfer import load_transfer_tables
from docex.cicl.validate import validate_document
from docex.context import load_project_context
from docex.emit.compose import emit_compose


_FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
_FIXED = _FIXTURES / "sample_project_clock_fixed"
_ELASTIC = _FIXTURES / "sample_project_clock_elastic"
_NO_CLOCK = _FIXTURES / "sample_project"

# What both fixtures declare, and therefore what must come back out of every
# delivery path.
_JOBS = {"nightly_cleanup": "0 3 * * *", "hourly_rollup": "0 * * * *"}


def _copy(fixture: Path, tmp_path: Path) -> Path:
    dest = tmp_path / "project"
    shutil.copytree(fixture, dest, dirs_exist_ok=False)
    out = dest / "infra" / "output"
    if out.exists():
        shutil.rmtree(out)
    return dest


def _compile(fixture: Path, tmp_path: Path) -> Path:
    root = _copy(fixture, tmp_path)
    assert run_compile(load_project_context(root)) == 0
    return root


@pytest.fixture(scope="module")
def fixed_project(tmp_path_factory) -> Path:
    return _compile(_FIXED, tmp_path_factory.mktemp("clock_fixed"))


@pytest.fixture(scope="module")
def elastic_project(tmp_path_factory) -> Path:
    return _compile(_ELASTIC, tmp_path_factory.mktemp("clock_elastic"))


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _tables():
    return load_transfer_tables(project_root=None)


def _doc(src: str) -> CICLDocument:
    return CICLDocument.model_validate(yaml.safe_load(src))


_VALID = """
cicl_version: "3"
foundation: fixed
apex_domain: example.com
observability_backend_url: "https://obs.example.com"
container_registry: registry.example.com
codebases:
  api:
    core_services:
      clock:
        role: clock
        command: ["python", "-m", "entrypoints.clock"]
        port: 8082
        networks: [internal]
        health_check_path: /health
        resources:
          cpu: 0.25
          memory: 512MB
        schedules:
          nightly_cleanup: "0 3 * * *"
          hourly_rollup: "0 * * * *"
"""

_SCHEDULES_BLOCK = (
    '        schedules:\n'
    '          nightly_cleanup: "0 3 * * *"\n'
    '          hourly_rollup: "0 * * * *"\n'
)


def _rules(src: str) -> list[str]:
    return [i.rule for i in validate_document(_doc(src), _tables())]


def test_valid_clock_passes():
    assert validate_document(_doc(_VALID), _tables()) == []


def test_clock_without_schedules_errors():
    src = _VALID.replace(_SCHEDULES_BLOCK, "")
    assert "rule_clock_schedules_required" in _rules(src)


def test_clock_with_empty_schedules_errors():
    src = _VALID.replace(_SCHEDULES_BLOCK, "        schedules: {}\n")
    assert "rule_clock_schedules_required" in _rules(src)


@pytest.mark.parametrize("value", ["[a, b]", '"0 3 * * *"'])
def test_clock_with_non_mapping_schedules_errors(value: str):
    """A list or a bare string is not a job map — same rule, because the
    author's mistake is the same one."""
    src = _VALID.replace(_SCHEDULES_BLOCK, f"        schedules: {value}\n")
    assert "rule_clock_schedules_required" in _rules(src)


@pytest.mark.parametrize("bad_name", ["nightly-cleanup", "2fast"])
def test_clock_invalid_job_name_errors(bad_name: str):
    """One issue per offending job. Job names are dispatch keys, so they must
    be valid identifiers."""
    src = _VALID.replace("nightly_cleanup:", f"{bad_name}:")
    rules = _rules(src)
    assert rules.count("rule_clock_job_name_invalid") == 1
    assert "rule_clock_cron_invalid" not in rules


def test_clock_non_string_job_name_errors():
    """YAML turns a bare `2024:` into an INT key. It is still an invalid
    dispatch key, and a mixed-type key set must not crash the validator."""
    src = _VALID.replace("nightly_cleanup:", "2024:")
    assert "rule_clock_job_name_invalid" in _rules(src)


@pytest.mark.parametrize("bad_cron", ["0 3 * *", "0 99 * * *"])
def test_clock_invalid_cron_errors(bad_cron: str):
    """Too few fields, and an out-of-range field. One issue each."""
    src = _VALID.replace('"0 3 * * *"', f'"{bad_cron}"')
    rules = _rules(src)
    assert rules.count("rule_clock_cron_invalid") == 1


def test_clock_reports_one_issue_per_offending_job():
    """An author who writes three bad crons should see three messages."""
    src = _VALID.replace(
        _SCHEDULES_BLOCK,
        '        schedules:\n'
        '          a: "0 3 * *"\n'
        '          b: "0 99 * * *"\n'
        '          c: "bogus * * * *"\n',
    )
    assert _rules(src).count("rule_clock_cron_invalid") == 3


def test_schedules_on_worker_rejected_by_rule_4():
    """`schedules` is declared only on the clock role, so on a worker the
    EXISTING rule 4 rejects it — no new rule is needed for the doctrine's
    'rejected on every other role'."""
    src = """
cicl_version: "3"
foundation: fixed
apex_domain: example.com
observability_backend_url: "https://obs.example.com"
container_registry: registry.example.com
codebases:
  api:
    core_services:
      worker:
        role: worker
        command: ["python", "-m", "entrypoints.worker"]
        networks: [internal]
        resources:
          cpu: 0.25
          memory: 512MB
        schedules:
          nightly_cleanup: "0 3 * * *"
"""
    assert "tt_rule_4_undeclared_field" in _rules(src)


def test_replicas_on_clock_rejected():
    src = _VALID.replace(
        "        role: clock\n", "        role: clock\n        replicas: 2\n"
    )
    assert "rule_26_replicas_on_clock" in _rules(src)


def test_web_network_on_clock_rejected():
    src = _VALID.replace("networks: [internal]", "networks: [web, internal]")
    assert "rule_27_web_network_on_non_web_role" in _rules(src)


def test_project_may_not_declare_the_delivery_variable():
    """Rule 20: `DOCEX_SCHEDULES_YAML` is doctrine-injected and reserved."""
    src = _VALID.replace(
        "        role: clock\n",
        "        role: clock\n"
        "        env:\n"
        '          DOCEX_SCHEDULES_YAML: "mine"\n',
    )
    assert "rule_reserved_env_key" in _rules(src)


# ---------------------------------------------------------------------------
# Fixed emit
# ---------------------------------------------------------------------------


def _compose(root: Path, env: str = "dev") -> dict:
    return yaml.safe_load(
        (root / "infra" / "output" / env / "docker-compose.yml").read_text()
    )


def test_fixed_clock_is_an_ordinary_compose_service(fixed_project: Path):
    """A clock is a long-running container with every ordinary attribute —
    command, image, build context and healthcheck, exactly as a `worker`."""
    doc = _compose(fixed_project)
    block = doc["services"]["sample-dev-api-clock"]
    assert block["command"] == ["python", "-m", "entrypoints.clock"]
    assert block["image"] == "sample/api:0.1.0"
    assert block["build"]["context"] == "./core/api"
    assert block["healthcheck"]["test"] == [
        "CMD", "curl", "-f", "http://localhost:8082/health",
    ]
    assert block["restart"] == "unless-stopped"
    assert block["labels"] == ["docex.project=sample"]
    assert block["logging"]["driver"] == "json-file"
    assert block["networks"] == ["internal"]


def test_fixed_clock_has_a_paired_sidecar(fixed_project: Path):
    doc = _compose(fixed_project)
    assert "sample-dev-api-clock-otelcol" in doc["services"]


def _undouble(value: str) -> str:
    """Undo compose's `$$` escaping, as compose itself does at read time."""
    return value.replace("$$", "$")


def test_fixed_schedule_table_reaches_the_container(fixed_project: Path):
    """Read the COMPILED FILE, undo the `$$` doubling, parse, compare. This
    is the delivery claim; the renderer's return value is not consulted."""
    doc = _compose(fixed_project)
    raw = doc["services"]["sample-dev-api-clock"]["environment"][
        "DOCEX_SCHEDULES_YAML"
    ]
    assert yaml.safe_load(_undouble(raw)) == _JOBS


@pytest.mark.parametrize("env", ["dev", "test", "stage", "prod"])
def test_fixed_schedule_table_delivered_in_every_env(
    fixed_project: Path, env: str
):
    """Nothing about a clock is suppressed anywhere (clock.md): the schedule
    table is delivered in all four envs, `test` included."""
    doc = _compose(fixed_project, env)
    block = doc["services"][f"sample-{env}-api-clock"]
    assert yaml.safe_load(
        _undouble(block["environment"]["DOCEX_SCHEDULES_YAML"])
    ) == _JOBS


def test_fixed_non_clock_services_carry_no_schedule_env(fixed_project: Path):
    doc = _compose(fixed_project)
    for key in ("sample-dev-api-web", "sample-dev-api-worker"):
        assert "DOCEX_SCHEDULES_YAML" not in doc["services"][key].get(
            "environment", {}
        )


def test_fixed_adds_no_compose_config_entry(fixed_project: Path):
    """This mod delivers by env var alone — the `configs:` block is untouched
    and still carries only the otelcol config."""
    doc = _compose(fixed_project)
    assert list(doc["configs"]) == ["otelcol_config"]


def test_fixed_dollar_in_payload_is_doubled(tmp_path: Path):
    """The `$` round-trip. Compose interpolates `environment:` values, so an
    unescaped `$` would reach the container mangled.

    The `$` is injected post-compile because validation forbids one in an
    authored cron expression — which is exactly why this hazard would go
    unnoticed until some future job name or expression grammar admitted one.
    The escaping is emitter behaviour and is pinned as such.
    """
    root = _copy(_FIXED, tmp_path)
    ctx = load_project_context(root)
    compiled = compile_env(
        ctx.infra, ctx.transfer_tables, env="dev",
        project_name=ctx.project.name, project_version=ctx.project.version,
    )
    compiled.services["api-clock"].schedules = {"dollar_job": "0 3 * * $X"}
    out = tmp_path / "compose.yml"
    emit_compose(compiled, out)

    raw = yaml.safe_load(out.read_text())["services"]["sample-dev-api-clock"][
        "environment"
    ]["DOCEX_SCHEDULES_YAML"]
    assert "$$X" in raw, "the emitted value must carry `$$` where the source had `$`"
    assert yaml.safe_load(_undouble(raw)) == {"dollar_job": "0 3 * * $X"}


# ---------------------------------------------------------------------------
# Elastic emit
# ---------------------------------------------------------------------------


def _hcl(root: Path, env: str = "prod") -> str:
    return (root / "infra" / "output" / env / "main.tf").read_text()


def _ecs_service_block(hcl: str, name: str) -> str:
    marker = f'resource "aws_ecs_service" "{name}" {{'
    rest = hcl[hcl.index(marker):]
    return rest[: rest.index("\n}\n") + 2]


def test_elastic_clock_emits_a_service_not_a_schedule(elastic_project: Path):
    hcl = _hcl(elastic_project)
    assert 'resource "aws_ecs_task_definition" "api-clock" {' in hcl
    assert 'resource "aws_ecs_service" "api-clock" {' in hcl
    assert 'resource "aws_lb_target_group" "api-clock"' not in hcl


def _hcl_unescape(value: str) -> str:
    """Undo `_hcl_value`'s escaping, as terraform does at parse time."""
    return (
        value.replace('\\"', '"')
             .replace("\\n", "\n")
             .replace("\\r", "\r")
             .replace("\\t", "\t")
             .replace("$$", "$")
             .replace("\\\\", "\\")
    )


def _td_env_value(hcl: str, td_name: str, key: str) -> str:
    marker = f'resource "aws_ecs_task_definition" "{td_name}" {{'
    rest = hcl[hcl.index(marker):]
    td = rest[: rest.index("\n}\n") + 2]
    m = re.search(
        r'name = "%s"\n\s*value = "((?:[^"\\]|\\.)*)"' % re.escape(key), td
    )
    assert m is not None, f"{key} not found in task definition {td_name}"
    return m.group(1)


def test_elastic_schedule_table_reaches_the_container(elastic_project: Path):
    """Same claim as the fixed side, against `main.tf`, and under the SAME
    variable name — one name on both foundations is the point of the ruling."""
    raw = _td_env_value(_hcl(elastic_project), "api-clock", "DOCEX_SCHEDULES_YAML")
    assert yaml.safe_load(_hcl_unescape(raw)) == _JOBS


def test_elastic_non_clock_services_carry_no_schedule_env(elastic_project: Path):
    hcl = _hcl(elastic_project)
    for td in ("api-web", "api-worker"):
        marker = f'resource "aws_ecs_task_definition" "{td}" {{'
        rest = hcl[hcl.index(marker):]
        assert "DOCEX_SCHEDULES_YAML" not in rest[: rest.index("\n}\n")]


def test_elastic_clock_service_forces_stop_then_start(elastic_project: Path):
    """All three attributes together — the interaction is the point. 0/100
    makes the deploy a recreate; `wait_for_steady_state` still converges on
    it, because the zero-task window is a state DURING the deployment."""
    block = _ecs_service_block(_hcl(elastic_project), "api-clock")
    assert "deployment_minimum_healthy_percent = 0" in block
    assert "deployment_maximum_percent         = 100" in block
    assert "wait_for_steady_state = true" in block


def test_elastic_percentages_are_clock_only(elastic_project: Path):
    hcl = _hcl(elastic_project)
    for name in ("api-web", "api-worker"):
        block = _ecs_service_block(hcl, name)
        assert "wait_for_steady_state = true" in block
        assert "deployment_minimum_healthy_percent" not in block
        assert "deployment_maximum_percent" not in block


def test_elastic_clock_has_a_sidecar(elastic_project: Path):
    hcl = _hcl(elastic_project)
    marker = 'resource "aws_ecs_task_definition" "api-clock" {'
    rest = hcl[hcl.index(marker):]
    td = rest[: rest.index("\n}\n") + 2]
    assert 'name = "api-clock-otelcol"' in td


# ---------------------------------------------------------------------------
# The schedules.yml visibility artifact
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("env", ["dev", "test", "stage", "prod"])
def test_schedules_artifact_written_for_every_env_fixed(
    fixed_project: Path, env: str
):
    path = fixed_project / "infra" / "output" / env / "schedules.yml"
    assert path.exists()
    assert yaml.safe_load(path.read_text()) == {"api.clock": _JOBS}


@pytest.mark.parametrize("env", ["dev", "test", "stage", "prod"])
def test_schedules_artifact_written_for_every_env_elastic(
    elastic_project: Path, env: str
):
    path = elastic_project / "infra" / "output" / env / "schedules.yml"
    assert path.exists()
    assert yaml.safe_load(path.read_text()) == {"api.clock": _JOBS}


def test_schedules_artifact_keyed_by_dotted_clock_ref(fixed_project: Path):
    """File shape != payload shape, deliberately: the FILE is keyed by dotted
    clock ref, the DELIVERED payload is the bare job map."""
    text = (fixed_project / "infra" / "output" / "dev" / "schedules.yml").read_text()
    assert "api.clock:" in text
    delivered = _compose(fixed_project)["services"]["sample-dev-api-clock"][
        "environment"
    ]["DOCEX_SCHEDULES_YAML"]
    assert "api.clock" not in delivered


def test_project_with_no_clock_emits_no_schedules_file(tmp_path: Path):
    root = _compile(_NO_CLOCK, tmp_path)
    for env in ("dev", "test", "stage", "prod"):
        assert not (root / "infra" / "output" / env / "schedules.yml").exists()


def test_schedules_artifact_carries_a_generated_by_header(fixed_project: Path):
    text = (fixed_project / "infra" / "output" / "dev" / "schedules.yml").read_text()
    assert text.startswith("# Generated by `docex compile`. Do not edit by hand.")
    assert "# project: sample v0.1.0" in text
    assert "# env: dev (foundation: fixed)" in text


# ---------------------------------------------------------------------------
# Role table
# ---------------------------------------------------------------------------


def test_clock_role_loads_from_the_bundled_tables():
    tables = _tables()
    assert "clock" in tables.by_role
    engine = tables.engine("clock", "container")
    assert engine.emits["fixed"] == ["compose_service"]
    assert engine.emits["elastic"] == [
        "task_definition", "ecs_service", "container_definition",
    ]
    # No target_group: a clock takes no ingress.
    assert "target_group" not in engine.emits["elastic"]
    assert json.dumps(engine.fields["schedules"]) is not None
