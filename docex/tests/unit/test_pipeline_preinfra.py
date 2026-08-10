"""Unit tests for ``docex.pipeline.preinfra``.

Mod 042 replaces the mod 034 stub with real per-(foundation, side)
checks. The runner enumerates every failure in one pass and only
needs an AWS client when the project is elastic and the side is
production.
"""

from __future__ import annotations

import pytest

from docex.pipeline.preinfra import (
    _DOCEX_INGRESS_NETWORK,
    _MASTER_VPC_TAGS,
    _PRIMARY_AZ,
    run_preinfra,
)


def _seed_deploy_keys(ctx, *, envs=("stage", "prod")) -> dict[str, str]:
    """Create ``infra/deploy_creds/<env>`` private keys in ``ctx`` and
    return the apex-derived host for each env (fixed registry probe)."""
    from docex.naming import dns_label

    creds = ctx.project_root / "infra" / "deploy_creds"
    creds.mkdir(parents=True, exist_ok=True)
    label = dns_label(ctx.project.name)
    hosts: dict[str, str] = {}
    for env in envs:
        (creds / env).write_text("PRIVATE KEY")
        if env == "stage":
            hosts[env] = f"stage.{label}.{ctx.infra.apex_domain}"
        else:
            hosts[env] = f"{label}.{ctx.infra.apex_domain}"
    return hosts


# ---------------------------------------------------------------------------
# Helpers — script the FakeAWSClient into a "healthy master VPC" state.
# ---------------------------------------------------------------------------


def _script_healthy_master_vpc(
    fake_aws, *, vpc_id: str = "vpc-master-001",
    public_subnets: list[str] | None = None,
    private_subnets: list[str] | None = None,
    primary_subnet: str | None = "subnet-priv-a",
) -> None:
    """Populate ``fake_aws`` so the elastic-prod preinfra path passes."""
    public_subnets = public_subnets or ["subnet-pub-a", "subnet-pub-b"]
    private_subnets = private_subnets or ["subnet-priv-a", "subnet-priv-b"]
    fake_aws.find_vpc_by_tags_result = vpc_id
    fake_aws.find_subnet_ids_results = {
        (vpc_id, (("tier", "public"),), None): public_subnets,
        (vpc_id, (("tier", "private"),), None): private_subnets,
        (vpc_id, (("tier", "private"),), _PRIMARY_AZ):
            [primary_subnet] if primary_subnet else [],
    }


# ---------------------------------------------------------------------------
# Development side (any foundation)
# ---------------------------------------------------------------------------


def test_preinfra_dev_passes_when_bridge_exists(
    sample_ctx, fake_docker, fake_dns, fake_registry, capsys,
):
    fake_docker.network_exists_results[_DOCEX_INGRESS_NETWORK] = True
    rc = run_preinfra(
        sample_ctx, fake_docker, aws=None, side="development", dns=fake_dns,
        registry=fake_registry,
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "all checks passed" in out


def test_preinfra_dev_fails_when_bridge_missing(
    sample_ctx, fake_docker, fake_dns, fake_registry, capsys,
):
    fake_docker.network_exists_results[_DOCEX_INGRESS_NETWORK] = False
    rc = run_preinfra(
        sample_ctx, fake_docker, aws=None, side="development", dns=fake_dns,
        registry=fake_registry,
    )
    assert rc == 1
    out = capsys.readouterr().out
    assert _DOCEX_INGRESS_NETWORK in out
    assert "docker network create" in out


def test_preinfra_dev_does_not_call_aws(
    sample_ctx, fake_docker, fake_aws, fake_dns, fake_registry,
):
    """Even when aws is provided, dev side never invokes AWS methods —
    the foundation+side gate short-circuits."""
    fake_docker.network_exists_results[_DOCEX_INGRESS_NETWORK] = True
    rc = run_preinfra(
        sample_ctx, fake_docker, aws=fake_aws, side="development",
        dns=fake_dns, registry=fake_registry,
    )
    assert rc == 0
    # No AWS call recorded.
    aws_method_names = [c[0] for c in fake_aws.calls]
    assert "find_vpc_by_tags" not in aws_method_names
    assert "find_subnet_ids" not in aws_method_names


# ---------------------------------------------------------------------------
# Development side — dev-web-hostname DNS check (mod 054)
# ---------------------------------------------------------------------------


# The sample fixture: project `sample`, apex `example.com`, `api` is the
# web + domain_default_service. So `dev` web hosts are the per-service host
# plus the bare-env host (api is the default service).
_DEV_HOSTS = ["api-web.dev.sample.example.com", "dev.sample.example.com"]


def test_preinfra_dev_dns_all_resolve_passes(
    sample_ctx, fake_docker, fake_dns, fake_registry, capsys,
):
    """Every dev web host resolves → no DNS failure; resolver was asked
    about exactly the dev hosts (never test/stage/prod)."""
    fake_docker.network_exists_results[_DOCEX_INGRESS_NETWORK] = True
    fake_dns.default = True
    rc = run_preinfra(
        sample_ctx, fake_docker, aws=None, side="development", dns=fake_dns,
        registry=fake_registry,
    )
    assert rc == 0
    assert "all checks passed" in capsys.readouterr().out
    assert set(fake_dns.asked) == set(_DEV_HOSTS)


def test_preinfra_dev_dns_unresolved_host_fails(
    sample_ctx, fake_docker, fake_dns, fake_registry, capsys,
):
    """A non-resolving dev host → that host enumerated as a failure and
    run_preinfra returns 1."""
    fake_docker.network_exists_results[_DOCEX_INGRESS_NETWORK] = True
    fake_dns.results = {"api-web.dev.sample.example.com": False}
    rc = run_preinfra(
        sample_ctx, fake_docker, aws=None, side="development", dns=fake_dns,
        registry=fake_registry,
    )
    assert rc == 1
    out = capsys.readouterr().out
    assert "api-web.dev.sample.example.com" in out
    assert "does not resolve in public DNS" in out


def test_preinfra_dev_dns_only_asks_about_dev_hosts(
    sample_ctx, fake_docker, fake_dns, fake_registry,
):
    """The resolver is only ever asked about `dev` hosts — no `test`,
    `stage`, or `prod` hostnames leak into the check."""
    fake_docker.network_exists_results[_DOCEX_INGRESS_NETWORK] = True
    run_preinfra(
        sample_ctx, fake_docker, aws=None, side="development", dns=fake_dns,
        registry=fake_registry,
    )
    for host in fake_dns.asked:
        assert ".dev.sample.example.com" in host or host == "dev.sample.example.com"
        for env in ("test", "stage", "prod"):
            assert f".{env}.sample" not in host


def test_preinfra_dev_dns_skipped_when_infra_absent(
    sample_ctx, fake_docker, fake_dns, fake_registry, capsys,
):
    """With no infra.yml (ctx.infra is None) the dev-side infra checks are
    skipped entirely — neither resolver nor registry is called (the
    inception-step-3 no-op). Mod 133 inherits this by living inside the
    same `ctx.infra is not None` block."""
    sample_ctx.infra = None
    fake_docker.network_exists_results[_DOCEX_INGRESS_NETWORK] = True
    rc = run_preinfra(
        sample_ctx, fake_docker, aws=None, side="development", dns=fake_dns,
        registry=fake_registry,
    )
    assert rc == 0
    assert fake_dns.asked == []
    assert fake_registry.calls == []
    out = capsys.readouterr().out
    assert "registry" not in out.lower()
    assert "Declined" not in out


def test_preinfra_dev_dns_resolver_error_surfaced_not_crashed(
    sample_ctx, fake_docker, fake_dns, fake_registry, capsys,
):
    """A resolver that raises is surfaced as a 'could not check' failure,
    not propagated as a crash."""
    fake_docker.network_exists_results[_DOCEX_INGRESS_NETWORK] = True
    fake_dns.raise_on = {"api-web.dev.sample.example.com"}
    rc = run_preinfra(
        sample_ctx, fake_docker, aws=None, side="development", dns=fake_dns,
        registry=fake_registry,
    )
    assert rc == 1
    out = capsys.readouterr().out
    assert "could not check DNS" in out
    assert "api-web.dev.sample.example.com" in out


def test_preinfra_dev_dns_enumerates_per_web_core_service(
    sample_ctx, fake_docker, fake_dns, fake_registry,
):
    """A codebase with TWO web core service has TWO dev hosts checked.

    Mod 104. The check delegates to `web_hostnames_for_env`, which is
    per-core service since Mod 096 — but every other test in this module runs
    against the one-core service sample fixture, so a regression that collapsed
    the enumeration back to one host per CODEBASE would pass all of them. This
    test fails against such an implementation.
    """
    import yaml
    from docex.context import load_project_context

    infra_path = sample_ctx.project_root / "infra" / "infra.yml"
    doc = yaml.safe_load(infra_path.read_text())
    doc["codebases"]["api"]["core_services"]["admin"] = {
        "role": "web",
        "command": ["python", "/service/dist/admin.py"],
        "port": 8081,
        "networks": ["web", "internal"],
        # Rule 7: the fixture's DATABASE_* refs are declared at the SERVICE
        # level, so every core service of `api` owes the readiness edge.
        "uses": ["appdb"],
        "resources": {"cpu": 0.5, "memory": "1GB", "disk": "20GB"},
    }
    infra_path.write_text(yaml.safe_dump(doc, sort_keys=False))
    ctx = load_project_context(sample_ctx.project_root)

    fake_docker.network_exists_results[_DOCEX_INGRESS_NETWORK] = True
    fake_dns.default = True
    rc = run_preinfra(
        ctx, fake_docker, aws=None, side="development", dns=fake_dns,
        registry=fake_registry,
    )
    assert rc == 0
    # Both web core service of the ONE codebase, plus the bare-env host that
    # `api.web` earns as `domain_default_service`.
    assert set(fake_dns.asked) == {
        "api-web.dev.sample.example.com",
        "api-admin.dev.sample.example.com",
        "dev.sample.example.com",
    }


def test_preinfra_dev_dns_none_resolver_reports_bug(
    sample_ctx, fake_docker, fake_registry, capsys,
):
    """The dispatcher must supply a resolver on the development side; if
    it doesn't, preinfra surfaces it as an explicit bug (mirrors aws/ssh)."""
    fake_docker.network_exists_results[_DOCEX_INGRESS_NETWORK] = True
    rc = run_preinfra(
        sample_ctx, fake_docker, aws=None, side="development",
        registry=fake_registry,
    )
    assert rc == 1
    out = capsys.readouterr().out
    assert "requires a DNS resolver" in out
    assert "dispatcher bug" in out


# ---------------------------------------------------------------------------
# Development side — registry manifest-delete probe (mod 133)
# ---------------------------------------------------------------------------
#
# The four tests immediately below are the mod's red-before-green arms
# (design Part 5): the honest failure plus three can't-answer modes. Each
# was observed failing against a verdict function that had not yet learned
# to distinguish them — see `red_before_green.md` in the mod folder.


def _dev_registry_rc(ctx, fake_docker, fake_dns, fake_registry, result):
    """Run a development-side preinfra with one scripted probe result."""
    fake_docker.network_exists_results[_DOCEX_INGRESS_NETWORK] = True
    fake_registry.result = result
    return run_preinfra(
        ctx, fake_docker, aws=None, side="development",
        dns=fake_dns, registry=fake_registry,
    )


def test_preinfra_dev_registry_delete_disabled_fails(
    sample_ctx, fake_docker, fake_dns, fake_registry, capsys,
):
    """RED-BEFORE-GREEN arm 1 — the honest failure.

    ``405`` carrying the registry's own ``UNSUPPORTED`` code is the registry
    itself refusing a real delete: rc 1, and the resolution names the env
    var that fixes it.
    """
    from docex.registry.client import ManifestDeleteResult

    rc = _dev_registry_rc(
        sample_ctx, fake_docker, fake_dns, fake_registry,
        ManifestDeleteResult(status=405, error_code="UNSUPPORTED"),
    )
    assert rc == 1
    out = capsys.readouterr().out
    assert "REGISTRY_STORAGE_DELETE_ENABLED" in out
    assert "registry.example.com" in out
    assert "teardown.sh" in out


def test_preinfra_dev_registry_401_declines_without_verdict(
    sample_ctx, fake_docker, fake_dns, fake_registry, capsys,
):
    """RED-BEFORE-GREEN arm 2 — the trap that hid the original defect.

    A ``401`` arrives for every DELETE regardless of the delete flag (the
    auth middleware runs ahead of the handler), so it can be read as
    neither a pass nor the finding. It must be a named declination at
    rc 0, and the output must claim nothing about the capability.
    """
    from docex.registry.client import ManifestDeleteResult

    rc = _dev_registry_rc(
        sample_ctx, fake_docker, fake_dns, fake_registry,
        ManifestDeleteResult(status=401, detail="401 from registry.example.com"),
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "Declined" in out
    assert "credential rejected" in out
    # Neither verdict may be claimed: not the finding...
    assert "REGISTRY_STORAGE_DELETE_ENABLED" not in out
    # ...and not a capability-present claim. The pass arm appends nothing,
    # so no line may assert the capability was verified.
    for claim in (
        "capability present",
        "accepts a manifest delete",
        "delete capability verified",
    ):
        assert claim not in out.lower()


def test_preinfra_dev_registry_no_credential_declines(
    sample_ctx, fake_docker, fake_dns, fake_registry, capsys,
):
    """RED-BEFORE-GREEN arm 3 — the most likely real-world mode.

    A fixed project before its first ``docker login``: dev builds locally
    and never touches the registry, so this must not block `envinfra up
    dev`. rc 0, named, with `docker login` as the resolution.
    """
    from docex.registry.client import ManifestDeleteResult

    rc = _dev_registry_rc(
        sample_ctx, fake_docker, fake_dns, fake_registry,
        ManifestDeleteResult(
            failure="no_credential",
            detail="no auths entry for 'registry.example.com' in /x/config.json",
        ),
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "Declined" in out
    assert "no credential" in out.lower()
    assert "docker login registry.example.com" in out
    assert "REGISTRY_STORAGE_DELETE_ENABLED" not in out


def test_preinfra_dev_registry_405_without_code_declines(
    sample_ctx, fake_docker, fake_dns, fake_registry, capsys,
):
    """RED-BEFORE-GREEN arm 4 — the false-positive arm.

    A reverse proxy can reject DELETE with a bare ``405`` the registry
    never saw. Reporting that as a delete-disabled registry is a checker
    inventing a violation, so it declines and must NOT name the env var.
    """
    from docex.registry.client import ManifestDeleteResult

    rc = _dev_registry_rc(
        sample_ctx, fake_docker, fake_dns, fake_registry,
        ManifestDeleteResult(status=405, error_code=None),
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "Declined" in out
    assert "405" in out
    assert "UNSUPPORTED" in out  # names what was MISSING from the response
    assert "REGISTRY_STORAGE_DELETE_ENABLED" not in out


# --- the two passing observations ------------------------------------------


def test_preinfra_dev_registry_404_manifest_unknown_passes(
    sample_ctx, fake_docker, fake_dns, fake_registry, capsys,
):
    """The inferred pass: reaching the manifest lookup proves the delete
    gate was passed. Nothing is appended — no failure, no declination."""
    from docex.registry.client import ManifestDeleteResult

    rc = _dev_registry_rc(
        sample_ctx, fake_docker, fake_dns, fake_registry,
        ManifestDeleteResult(status=404, error_code="MANIFEST_UNKNOWN"),
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "all checks passed" in out
    assert "Declined" not in out


@pytest.mark.parametrize("code", ["MANIFEST_UNKNOWN", "NAME_UNKNOWN", "BLOB_UNKNOWN"])
def test_preinfra_dev_registry_404_absent_codes_all_pass(
    sample_ctx, fake_docker, fake_dns, fake_registry, capsys, code,
):
    """All three "the thing isn't there" codes prove the same thing: the
    request got past `deleteEnabled` to a lookup."""
    from docex.registry.client import ManifestDeleteResult

    rc = _dev_registry_rc(
        sample_ctx, fake_docker, fake_dns, fake_registry,
        ManifestDeleteResult(status=404, error_code=code),
    )
    assert rc == 0
    assert "Declined" not in capsys.readouterr().out


def test_preinfra_dev_registry_202_passes(
    sample_ctx, fake_docker, fake_dns, fake_registry, capsys,
):
    """A 202 is the capability directly observed rather than inferred
    (what `registry:3` returns). Also a pass."""
    from docex.registry.client import ManifestDeleteResult

    rc = _dev_registry_rc(
        sample_ctx, fake_docker, fake_dns, fake_registry,
        ManifestDeleteResult(status=202),
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "all checks passed" in out
    assert "Declined" not in out


# --- the rest of the can't-answer enumeration (design Part 3) --------------


@pytest.mark.parametrize(
    "result_kwargs,needle",
    [
        # 3. The credential lives in an external helper docex won't invoke.
        ({"failure": "bad_credential_store", "detail": "held by a helper"},
         "external helper"),
        # 6-9. DNS failure, connection refused, TLS failure, timeout — all
        # arrive as one transport failure with a specific detail.
        ({"failure": "transport", "detail": "Name or service not known"},
         "no response"),
        # 10. 403 — distinguished from "no credential"; the resolutions differ.
        ({"status": 403}, "lacks delete scope"),
        # 12. A proxy 404 with no registry error code.
        ({"status": 404, "error_code": None}, "proxy 404"),
        # 13. Any other status, including a malformed probe.
        ({"status": 400, "error_code": "DIGEST_INVALID"}, "unexpected response"),
        ({"status": 500}, "unexpected response"),
        # 14. A body that is not JSON, or JSON without a code, reaches the
        # mapping as error_code=None — on a status with no verdict, declined.
        ({"status": 418, "error_code": None}, "unexpected response"),
        # A failure mode the ladder does not name yet must still decline
        # rather than fall through to a status rung with status=None.
        ({"failure": "some_future_mode", "detail": "who knows"},
         "could not complete the probe"),
    ],
)
def test_preinfra_dev_registry_cant_answer_modes_are_named_and_rc_zero(
    sample_ctx, fake_docker, fake_dns, fake_registry, capsys,
    result_kwargs, needle,
):
    """Every can't-answer mode: rc 0, individually named in the Declined
    block, and never the ABSENT finding.

    A *count* of declinations is not a declaration — each mode must be
    identifiable, so each asserts its own distinguishing phrase.
    """
    from docex.registry.client import ManifestDeleteResult

    rc = _dev_registry_rc(
        sample_ctx, fake_docker, fake_dns, fake_registry,
        ManifestDeleteResult(**result_kwargs),
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "Declined" in out
    assert needle in out
    assert "REGISTRY_STORAGE_DELETE_ENABLED" not in out


def test_preinfra_dev_registry_declination_does_not_suppress_pass_line(
    sample_ctx, fake_docker, fake_dns, fake_registry, capsys,
):
    """A declination is an addendum, not a verdict: the pass line still
    prints and the exit code is still 0."""
    from docex.registry.client import ManifestDeleteResult

    rc = _dev_registry_rc(
        sample_ctx, fake_docker, fake_dns, fake_registry,
        ManifestDeleteResult(failure="transport", detail="connection refused"),
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "all checks passed" in out
    assert out.index("all checks passed") < out.index("Declined")


def test_preinfra_dev_registry_declination_does_not_mask_a_real_failure(
    sample_ctx, fake_docker, fake_dns, fake_registry, capsys,
):
    """A declined registry probe alongside a genuine failure: rc 1 from the
    failure, and the declination still printed rather than swallowed."""
    from docex.registry.client import ManifestDeleteResult

    fake_docker.network_exists_results[_DOCEX_INGRESS_NETWORK] = False
    fake_registry.result = ManifestDeleteResult(
        failure="no_credential", detail="no Docker config",
    )
    rc = run_preinfra(
        sample_ctx, fake_docker, aws=None, side="development",
        dns=fake_dns, registry=fake_registry,
    )
    assert rc == 1
    out = capsys.readouterr().out
    assert "1 check(s) failed" in out   # the bridge, not the registry
    assert "Declined" in out
    assert "no credential" in out.lower()


# --- the side-effect-free contract, and the scope gate ---------------------


def test_preinfra_dev_registry_probe_targets_reserved_repo_and_zero_digest(
    sample_ctx, fake_docker, fake_dns, fake_registry,
):
    """Pins the side-effect-free contract: the probe must aim at the
    doctrine-reserved `preinfra-smoke/` namespace and a digest that cannot
    exist. A probe that ever pushed or targeted a real tag would mutate
    preinfra shared by every project on the machine.
    """
    from docex.pipeline.preinfra import (
        _DELETE_PROBE_DIGEST,
        _DELETE_PROBE_REPOSITORY,
    )

    fake_docker.network_exists_results[_DOCEX_INGRESS_NETWORK] = True
    run_preinfra(
        sample_ctx, fake_docker, aws=None, side="development",
        dns=fake_dns, registry=fake_registry,
    )
    assert fake_registry.calls == [(
        "delete_manifest", "registry.example.com",
        "preinfra-smoke/delete-capability-probe",
        "sha256:" + "0" * 64,
    )]
    assert _DELETE_PROBE_REPOSITORY.startswith("preinfra-smoke/")
    assert _DELETE_PROBE_DIGEST == "sha256:" + "0" * 64


def test_preinfra_dev_registry_not_probed_on_elastic(
    elastic_ctx, fake_docker, fake_dns, fake_registry, capsys,
):
    """Elastic is silent, not declined: ECR governs deletion via IAM and
    teardown removes the repository wholesale, so the question does not
    apply (design Q3). Printing a skip line on every invocation would be
    noise that trains the reader to skim."""
    fake_docker.network_exists_results[_DOCEX_INGRESS_NETWORK] = True
    rc = run_preinfra(
        elastic_ctx, fake_docker, aws=None, side="development",
        dns=fake_dns, registry=fake_registry,
    )
    assert rc == 0
    assert fake_registry.calls == []
    out = capsys.readouterr().out
    assert "Declined" not in out
    assert "manifest-delete" not in out


def test_preinfra_dev_registry_not_probed_when_no_container_registry(
    sample_ctx, fake_docker, fake_dns, fake_registry, capsys,
):
    """A fixed project that declares no `container_registry` — same silent
    not-applicable as elastic."""
    sample_ctx.infra.container_registry = None
    fake_docker.network_exists_results[_DOCEX_INGRESS_NETWORK] = True
    rc = run_preinfra(
        sample_ctx, fake_docker, aws=None, side="development",
        dns=fake_dns, registry=fake_registry,
    )
    assert rc == 0
    assert fake_registry.calls == []
    out = capsys.readouterr().out
    assert "Declined" not in out
    assert "manifest-delete" not in out


def test_preinfra_dev_registry_not_probed_on_production_side(
    sample_ctx, fake_docker, fake_ssh, fake_registry,
):
    """The probe is a development-side check only — the production side has
    its own (SSH) registry-credential check and must not fire this one."""
    fake_docker.network_exists_results[_DOCEX_INGRESS_NETWORK] = True
    hosts = _seed_deploy_keys(sample_ctx)
    fake_ssh.results = {h: 0 for h in hosts.values()}
    run_preinfra(
        sample_ctx, fake_docker, aws=None, side="production",
        ssh=fake_ssh, registry=fake_registry,
    )
    assert fake_registry.calls == []


def test_preinfra_dev_registry_none_client_reports_dispatcher_bug(
    sample_ctx, fake_docker, fake_dns, capsys,
):
    """A forgotten dispatcher call site must be LOUD — a failure, matching
    the aws/ssh/dns guards — never a silently skipped check.

    This is the one registry-shaped outcome besides ABSENT that is rc 1,
    and deliberately so: it is a bug in docex, not a question about the
    operator's infrastructure.
    """
    fake_docker.network_exists_results[_DOCEX_INGRESS_NETWORK] = True
    rc = run_preinfra(
        sample_ctx, fake_docker, aws=None, side="development", dns=fake_dns,
    )
    assert rc == 1
    out = capsys.readouterr().out
    assert "requires a registry client" in out
    assert "dispatcher bug" in out


# ---------------------------------------------------------------------------
# Fixed production side
# ---------------------------------------------------------------------------


def test_preinfra_fixed_prod_checks_docker_not_aws(
    sample_ctx, fake_docker, fake_aws, fake_ssh,
):
    """Fixed-foundation production side never performs AWS lookups
    (the registry-cred probe goes over SSH, not AWS)."""
    fake_docker.network_exists_results[_DOCEX_INGRESS_NETWORK] = True
    hosts = _seed_deploy_keys(sample_ctx)
    fake_ssh.results = {h: 0 for h in hosts.values()}
    rc = run_preinfra(
        sample_ctx, fake_docker, aws=fake_aws, side="production", ssh=fake_ssh,
    )
    assert rc == 0
    aws_method_names = [c[0] for c in fake_aws.calls]
    assert "find_vpc_by_tags" not in aws_method_names


def test_preinfra_fixed_prod_fails_when_bridge_missing(
    sample_ctx, fake_docker, fake_ssh, capsys,
):
    fake_docker.network_exists_results[_DOCEX_INGRESS_NETWORK] = False
    hosts = _seed_deploy_keys(sample_ctx)
    fake_ssh.results = {h: 0 for h in hosts.values()}
    rc = run_preinfra(
        sample_ctx, fake_docker, aws=None, side="production", ssh=fake_ssh,
    )
    assert rc == 1
    out = capsys.readouterr().out
    assert _DOCEX_INGRESS_NETWORK in out


# ---------------------------------------------------------------------------
# Fixed production side — registry-cred SSH probe (Gap G, mod 050)
# ---------------------------------------------------------------------------


def test_preinfra_fixed_prod_registry_creds_present(
    sample_ctx, fake_docker, fake_ssh, capsys,
):
    """Both hosts report the cred present → no registry failure, and
    both stage and prod hosts were probed."""
    fake_docker.network_exists_results[_DOCEX_INGRESS_NETWORK] = True
    hosts = _seed_deploy_keys(sample_ctx)
    fake_ssh.results = {h: 0 for h in hosts.values()}
    rc = run_preinfra(
        sample_ctx, fake_docker, aws=None, side="production", ssh=fake_ssh,
    )
    assert rc == 0
    probed_hosts = {c[1] for c in fake_ssh.calls if c[0] == "run"}
    assert probed_hosts == set(hosts.values())


def test_preinfra_fixed_prod_registry_creds_missing(
    sample_ctx, fake_docker, fake_ssh, capsys,
):
    """A non-zero (≠255) exit → 'registry credentials not found … run
    docker login' failure."""
    fake_docker.network_exists_results[_DOCEX_INGRESS_NETWORK] = True
    hosts = _seed_deploy_keys(sample_ctx)
    # stage host healthy, prod host reports cred missing (exit 1).
    fake_ssh.results = {hosts["stage"]: 0, hosts["prod"]: 1}
    rc = run_preinfra(
        sample_ctx, fake_docker, aws=None, side="production", ssh=fake_ssh,
    )
    assert rc == 1
    out = capsys.readouterr().out
    assert "registry credentials not found" in out
    assert "docker login" in out
    assert hosts["prod"] in out


def test_preinfra_fixed_prod_host_unreachable(
    sample_ctx, fake_docker, fake_ssh, capsys,
):
    """SSH connect failure (255) → distinct 'could not reach … host'
    failure."""
    fake_docker.network_exists_results[_DOCEX_INGRESS_NETWORK] = True
    hosts = _seed_deploy_keys(sample_ctx)
    fake_ssh.results = {hosts["stage"]: 0, hosts["prod"]: 255}
    rc = run_preinfra(
        sample_ctx, fake_docker, aws=None, side="production", ssh=fake_ssh,
    )
    assert rc == 1
    out = capsys.readouterr().out
    assert "could not reach" in out
    assert hosts["prod"] in out


def test_preinfra_fixed_prod_deploy_key_absent(
    sample_ctx, fake_docker, fake_ssh, capsys,
):
    """A missing ``infra/deploy_creds/<env>`` → 'missing … needed to
    reach' failure, and that env's host is not probed over SSH."""
    fake_docker.network_exists_results[_DOCEX_INGRESS_NETWORK] = True
    # Seed only the stage key; remove the prod key the sample fixture ships.
    (sample_ctx.project_root / "infra" / "deploy_creds" / "prod").unlink()
    hosts = _seed_deploy_keys(sample_ctx, envs=("stage",))
    fake_ssh.results = {hosts["stage"]: 0}
    rc = run_preinfra(
        sample_ctx, fake_docker, aws=None, side="production", ssh=fake_ssh,
    )
    assert rc == 1
    out = capsys.readouterr().out
    assert "infra/deploy_creds/prod missing" in out
    # The prod host was skipped — only the stage host was probed.
    probed_hosts = {c[1] for c in fake_ssh.calls if c[0] == "run"}
    prod_host = f"{sample_ctx.project.name}.{sample_ctx.infra.apex_domain}".replace("_", "-").lower()
    assert prod_host not in probed_hosts


def test_preinfra_fixed_prod_with_none_ssh_reports_bug(
    sample_ctx, fake_docker, capsys,
):
    """The dispatcher must construct an SSH client on this branch; if it
    doesn't, preinfra surfaces it as an explicit bug (mirrors aws)."""
    fake_docker.network_exists_results[_DOCEX_INGRESS_NETWORK] = True
    rc = run_preinfra(sample_ctx, fake_docker, aws=None, side="production")
    assert rc == 1
    out = capsys.readouterr().out
    assert "dispatcher bug" in out


# ---------------------------------------------------------------------------
# Elastic production side
# ---------------------------------------------------------------------------


def test_preinfra_elastic_prod_passes(
    elastic_ctx, fake_docker, fake_aws, capsys,
):
    fake_docker.network_exists_results[_DOCEX_INGRESS_NETWORK] = True
    _script_healthy_master_vpc(fake_aws)
    rc = run_preinfra(elastic_ctx, fake_docker, aws=fake_aws, side="production")
    assert rc == 0
    out = capsys.readouterr().out
    assert "all checks passed" in out
    # VPC + 3 subnet lookups were performed.
    aws_method_names = [c[0] for c in fake_aws.calls]
    assert aws_method_names.count("find_vpc_by_tags") == 1
    assert aws_method_names.count("find_subnet_ids") == 3
    # The VPC lookup used the doctrine-prescribed tag set.
    vpc_call = next(c for c in fake_aws.calls if c[0] == "find_vpc_by_tags")
    assert vpc_call[1][0] == _MASTER_VPC_TAGS


def test_preinfra_elastic_prod_fails_when_vpc_missing(
    elastic_ctx, fake_docker, fake_aws, capsys,
):
    fake_docker.network_exists_results[_DOCEX_INGRESS_NETWORK] = True
    fake_aws.find_vpc_by_tags_result = None
    rc = run_preinfra(elastic_ctx, fake_docker, aws=fake_aws, side="production")
    assert rc == 1
    out = capsys.readouterr().out
    assert "master VPC not found" in out
    # Bails on VPC lookup — no subnet lookups attempted.
    aws_method_names = [c[0] for c in fake_aws.calls]
    assert "find_subnet_ids" not in aws_method_names


def test_preinfra_elastic_prod_fails_when_insufficient_public_subnets(
    elastic_ctx, fake_docker, fake_aws, capsys,
):
    fake_docker.network_exists_results[_DOCEX_INGRESS_NETWORK] = True
    _script_healthy_master_vpc(fake_aws, public_subnets=["subnet-pub-a"])
    rc = run_preinfra(elastic_ctx, fake_docker, aws=fake_aws, side="production")
    assert rc == 1
    out = capsys.readouterr().out
    assert "public subnet" in out
    assert "at least 2" in out


def test_preinfra_elastic_prod_fails_when_insufficient_private_subnets(
    elastic_ctx, fake_docker, fake_aws, capsys,
):
    fake_docker.network_exists_results[_DOCEX_INGRESS_NETWORK] = True
    _script_healthy_master_vpc(
        fake_aws,
        private_subnets=["subnet-priv-a"],
        # Primary still resolves so we isolate the count-shortfall message.
        primary_subnet="subnet-priv-a",
    )
    rc = run_preinfra(elastic_ctx, fake_docker, aws=fake_aws, side="production")
    assert rc == 1
    out = capsys.readouterr().out
    assert "private subnet" in out
    assert "at least 2" in out


def test_preinfra_elastic_prod_fails_when_no_primary_az_subnet(
    elastic_ctx, fake_docker, fake_aws, capsys,
):
    fake_docker.network_exists_results[_DOCEX_INGRESS_NETWORK] = True
    _script_healthy_master_vpc(fake_aws, primary_subnet=None)
    rc = run_preinfra(elastic_ctx, fake_docker, aws=fake_aws, side="production")
    assert rc == 1
    out = capsys.readouterr().out
    assert _PRIMARY_AZ in out
    assert "primary AZ" in out


def test_preinfra_elastic_prod_enumerates_multiple_failures(
    elastic_ctx, fake_docker, fake_aws, capsys,
):
    """Bridge missing AND insufficient subnets → both reported in one pass."""
    fake_docker.network_exists_results[_DOCEX_INGRESS_NETWORK] = False
    _script_healthy_master_vpc(
        fake_aws,
        public_subnets=["subnet-pub-a"],   # short
        private_subnets=["subnet-priv-a"], # short
        primary_subnet=None,               # primary missing
    )
    rc = run_preinfra(elastic_ctx, fake_docker, aws=fake_aws, side="production")
    assert rc == 1
    out = capsys.readouterr().out
    # 4 failures: bridge + 2x subnet shortage + primary AZ missing.
    assert "4 check(s) failed" in out


def test_preinfra_elastic_prod_with_none_aws_reports_bug(
    elastic_ctx, fake_docker, capsys,
):
    """The dispatcher is supposed to construct an AWS client on this
    branch; if it doesn't, preinfra surfaces it as an explicit bug
    rather than silently skipping the elastic checks."""
    fake_docker.network_exists_results[_DOCEX_INGRESS_NETWORK] = True
    rc = run_preinfra(elastic_ctx, fake_docker, aws=None, side="production")
    assert rc == 1
    out = capsys.readouterr().out
    assert "dispatcher bug" in out


# ---------------------------------------------------------------------------
# Doctrine-prescribed tag scheme guard
# ---------------------------------------------------------------------------


def test_master_vpc_tag_scheme_matches_doctrine():
    """Mod 060: project.tf.j2's `data "aws_vpc" "master"` filters on these
    exact semantic tags (cicl.md § Naming and Tagging preinfra block) — NOT
    the redundant `Name`. Drift here would break the elastic prod
    data-source lookup."""
    assert _MASTER_VPC_TAGS == {
        "managed_by": "doctrine-operator",
        "infra_tier": "prerequisite",
        "shape_name": "master_network",
    }
    assert _PRIMARY_AZ == "us-east-1a"
    assert _DOCEX_INGRESS_NETWORK == "docex-ingress"
