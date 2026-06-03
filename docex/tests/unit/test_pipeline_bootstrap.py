"""Unit tests for ``docex bootstrap``.

Verifies:

- On an elastic project, the command creates the S3 bucket + DynamoDB
  table when they're absent, reconciling versioning / encryption /
  block-public-access on every run.
- Idempotence: re-running with both already-present does NOT call
  ``create_bucket`` / ``create_table`` but DOES re-call the reconcile
  setters.
- Project-tier tofu apply runs in two phases: targeted zone-only on
  first invocation, full apply on re-run after the zone is in state.
- Fixed-foundation projects short-circuit with a "no-op" message.
- Any AWS exception is wrapped in :class:`BootstrapFailed`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from docex.cicl.compile import run_compile
from docex.errors import BootstrapFailed
from docex.pipeline import bootstrap as bootstrap_mod
from docex.pipeline.bootstrap import run_bootstrap


def _names(calls: list[tuple]) -> list[str]:
    return [c[0] for c in calls]


@pytest.fixture
def elastic_ctx_compiled(elastic_ctx):
    """Like ``elastic_ctx`` but with the project-tier HCL already on disk.

    bootstrap requires ``infra/output/project/main.tf`` to exist (the
    fixture intentionally clears infra/output, so we re-run compile).
    """
    rc = run_compile(elastic_ctx)
    assert rc == 0
    return elastic_ctx


@pytest.fixture
def stub_tofu(monkeypatch):
    """Replace the tofu runner entrypoints with recording stubs.

    Yields a dict with ``state``, ``output``, ``apply_calls``, and
    ``init_calls``. Tests mutate ``state`` and ``output`` to script the
    fake's responses; they read ``apply_calls`` / ``init_calls`` to
    assert which tofu invocations bootstrap made.
    """
    fake = {
        "state": [],  # initial: nothing in state (phase 1)
        "output": {"zone_name_servers": ["ns-1.example.net", "ns-2.example.net"]},
        "init_calls": [],
        "apply_calls": [],
    }

    def fake_init(workdir, *, backend=True):
        fake["init_calls"].append((Path(workdir), backend))
        return 0

    def fake_state_list(workdir):
        return list(fake["state"])

    def fake_apply(workdir, *, plan_file=None, auto_approve=False, targets=None):
        fake["apply_calls"].append({
            "workdir": Path(workdir),
            "auto_approve": auto_approve,
            "targets": list(targets) if targets else [],
        })
        # Simulate the zone landing in state after a phase 1 apply.
        if targets and "aws_route53_zone.project" in targets:
            if "aws_route53_zone.project" not in fake["state"]:
                fake["state"].append("aws_route53_zone.project")
        return 0

    def fake_output(workdir, name):
        return fake["output"].get(name)

    monkeypatch.setattr(bootstrap_mod, "tofu_init", fake_init)
    monkeypatch.setattr(bootstrap_mod, "tofu_state_list", fake_state_list)
    monkeypatch.setattr(bootstrap_mod, "tofu_apply", fake_apply)
    monkeypatch.setattr(bootstrap_mod, "tofu_output", fake_output)
    return fake


def test_bootstrap_creates_bucket_and_table_when_absent(
    elastic_ctx_compiled, fake_aws, stub_tofu
):
    fake_aws.bucket_exists = False
    fake_aws.table_exists = False
    rc = run_bootstrap(elastic_ctx_compiled, fake_aws)
    assert rc == 0
    names = _names(fake_aws.calls)
    # Existence probe → create → reconciliation calls all happen.
    assert "s3_bucket_exists" in names
    assert "s3_create_bucket" in names
    assert "s3_enable_versioning" in names
    assert "s3_enable_encryption" in names
    assert "s3_block_public_access" in names
    assert "ddb_table_exists" in names
    assert "ddb_create_locking_table" in names
    # Order: create_bucket must precede the reconcile setters.
    assert names.index("s3_create_bucket") < names.index("s3_enable_versioning")


def test_bootstrap_is_idempotent_when_resources_exist(
    elastic_ctx_compiled, fake_aws, stub_tofu
):
    """Re-running with bucket + table already present: no creates, but
    versioning/encryption/block-public-access are still reapplied."""
    fake_aws.bucket_exists = True
    fake_aws.table_exists = True
    rc = run_bootstrap(elastic_ctx_compiled, fake_aws)
    assert rc == 0
    names = _names(fake_aws.calls)
    assert "s3_create_bucket" not in names
    assert "ddb_create_locking_table" not in names
    # But reconciliation setters STILL run (idempotent at AWS layer).
    assert "s3_enable_versioning" in names
    assert "s3_enable_encryption" in names
    assert "s3_block_public_access" in names


def test_bootstrap_fixed_foundation_is_no_op(sample_ctx, fake_aws, capsys):
    rc = run_bootstrap(sample_ctx, fake_aws)
    assert rc == 0
    # No AWS calls at all on the fixed-foundation short-circuit.
    assert fake_aws.calls == []
    assert "no-op" in capsys.readouterr().out


def test_bootstrap_wraps_aws_exception_in_bootstrap_failed(
    elastic_ctx_compiled, fake_aws, stub_tofu
):
    """Any AWS exception in the bootstrap pipeline surfaces as a
    BootstrapFailed for clean error reporting at the dispatcher."""
    fake_aws.bucket_exists = False
    # Make create_bucket raise on first call.
    fake_aws.raise_on["s3_create_bucket"] = RuntimeError("aws down")
    with pytest.raises(BootstrapFailed) as exc_info:
        run_bootstrap(elastic_ctx_compiled, fake_aws)
    assert "aws down" in str(exc_info.value)


def test_bootstrap_uses_project_scoped_resource_names(
    elastic_ctx_compiled, fake_aws, stub_tofu
):
    """Per mod 005: bucket name follows the `s3` policy (hyphen + lower);
    table name follows the `ddb` policy (underscore preserved)."""
    run_bootstrap(elastic_ctx_compiled, fake_aws)
    # The fixture's project name is 'sample' — no underscores to translate,
    # so both end up with the literal joiner each policy prescribes.
    bucket_calls = [c for c in fake_aws.calls if c[0] == "s3_bucket_exists"]
    table_calls = [c for c in fake_aws.calls if c[0] == "ddb_table_exists"]
    assert bucket_calls and bucket_calls[0][1][0] == "sample-tofu-state"
    assert table_calls and table_calls[0][1][0] == "sample_tofu_locks"


# ---------------------------------------------------------------------------
# v0.6.0 — two-phase project-tier apply.
# ---------------------------------------------------------------------------


def test_bootstrap_phase1_targets_only_the_zone(
    elastic_ctx_compiled, fake_aws, stub_tofu
):
    """First run (nothing in state) targets just the Route53 zone, so the
    bootstrap pauses for NS delegation before the cert needs DNS."""
    rc = run_bootstrap(elastic_ctx_compiled, fake_aws)
    assert rc == 0
    assert len(stub_tofu["apply_calls"]) == 1
    call = stub_tofu["apply_calls"][0]
    assert call["targets"] == ["aws_route53_zone.project"]
    assert call["auto_approve"] is True


def test_bootstrap_phase1_prints_ns_records(
    elastic_ctx_compiled, fake_aws, stub_tofu, capsys
):
    """Phase 1 surfaces the zone's NS records and what the operator must do."""
    run_bootstrap(elastic_ctx_compiled, fake_aws)
    out = capsys.readouterr().out
    assert "ns-1.example.net" in out
    assert "ns-2.example.net" in out
    assert "delegate" in out.lower()


def test_bootstrap_phase2_runs_full_apply_when_zone_in_state(
    elastic_ctx_compiled, fake_aws, stub_tofu
):
    """Subsequent run (zone already in state) runs the full project apply."""
    stub_tofu["state"] = ["aws_route53_zone.project"]
    rc = run_bootstrap(elastic_ctx_compiled, fake_aws)
    assert rc == 0
    assert len(stub_tofu["apply_calls"]) == 1
    call = stub_tofu["apply_calls"][0]
    assert call["targets"] == []  # untargeted = full apply
    assert call["auto_approve"] is True


def test_bootstrap_requires_compile_output(elastic_ctx, fake_aws):
    """Without ``docex compile`` first, project main.tf is missing — bootstrap
    must point the operator at the right next step rather than hang in tofu."""
    with pytest.raises(BootstrapFailed) as exc_info:
        run_bootstrap(elastic_ctx, fake_aws)
    assert "docex compile" in str(exc_info.value).lower()


def test_bootstrap_underscored_project_hyphenates_s3_bucket(
    tmp_path, fake_aws, stub_tofu
):
    """Mod 005 regression — a project name with underscores
    (``docex_smoke_elastic``) must compile its S3 bucket name to the
    hyphenated form (``docex-smoke-elastic-tofu-state``) so AWS accepts
    it. The DDB table preserves underscores."""
    from docex.context import load_project_context

    proj = tmp_path / "p"
    (proj / "infra").mkdir(parents=True)
    (proj / "project.yml").write_text(
        'name: docex_smoke_elastic\nversion: "0.0.1"\ndocex_version: "0.7.0"\n'
    )
    (proj / "infra" / "infra.yml").write_text(
        'cicl_version: "1"\n'
        'foundation: elastic\n'
        'domain: example.com\n'
        'observability_backend_url: "https://obs.example.com"\n'
        'domain_default_service: web\n'
        'core_services:\n'
        '  web:\n'
        '    role: web\n'
        '    port: 8080\n'
        '    networks: [web, internal]\n'
        '    resources:\n'
        '      cpu: 0.25\n'
        '      memory: 512MB\n'
        '      disk: 25GB\n'
    )
    ctx = load_project_context(proj)
    rc = run_compile(ctx)
    assert rc == 0

    rc = run_bootstrap(ctx, fake_aws)
    assert rc == 0
    bucket_calls = [c for c in fake_aws.calls if c[0] == "s3_create_bucket"]
    table_calls = [c for c in fake_aws.calls if c[0] == "ddb_create_locking_table"]
    assert bucket_calls, fake_aws.calls
    assert bucket_calls[0][1][0] == "docex-smoke-elastic-tofu-state"
    assert table_calls and table_calls[0][1][0] == "docex_smoke_elastic_tofu_locks"


def test_bootstrap_phase2_surfaces_tofu_apply_failure(
    elastic_ctx_compiled, fake_aws, stub_tofu, monkeypatch, capsys
):
    """A failed full apply (e.g. ACM validation hang) returns the tofu exit
    code and prints a hint about NS delegation."""
    stub_tofu["state"] = ["aws_route53_zone.project"]

    def failing_apply(workdir, *, plan_file=None, auto_approve=False, targets=None):
        stub_tofu["apply_calls"].append({
            "workdir": Path(workdir),
            "auto_approve": auto_approve,
            "targets": list(targets) if targets else [],
        })
        return 1

    monkeypatch.setattr(bootstrap_mod, "tofu_apply", failing_apply)
    rc = run_bootstrap(elastic_ctx_compiled, fake_aws)
    assert rc == 1
    out = capsys.readouterr().out
    assert "delegat" in out.lower()
