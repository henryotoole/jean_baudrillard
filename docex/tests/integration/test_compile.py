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
    """The api service's DATABASE_URL magic ref must resolve to the
    postgres-engine fixed URL template."""
    root = _copy_fixture(_FIXTURE_FIXED, tmp_path)
    ctx = load_project_context(root)
    run_compile(ctx)
    compose = (root / "infra" / "output" / "dev" / "docker-compose.yml").read_text()
    assert "DATABASE_URL: postgres://" in compose
    # Compose runtime form uses ${VAR} not $[VAR].
    assert "${POSTGRES_USER}" in compose
    assert "$[POSTGRES_USER]" not in compose
    # Hostname is the project-scoped service name.
    assert "sample-dev-database" in compose


def test_example_env_includes_postgres_keys(tmp_path: Path):
    root = _copy_fixture(_FIXTURE_FIXED, tmp_path)
    ctx = load_project_context(root)
    run_compile(ctx)
    example = (root / "infra" / "secrets" / "example.env").read_text()
    assert "POSTGRES_USER=" in example
    assert "POSTGRES_PASSWORD=" in example
    assert "# database" in example


def test_compose_depends_on_uses_global_service_keys(tmp_path: Path):
    """``depends_on`` in compose must reference compose service keys
    (global names like ``sample-dev-database``), not the simple names
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
        edge["from"] == "api" and edge["to"] == "database"
        for edge in parsed["edges"]
    )
