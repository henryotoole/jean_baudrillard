"""``docex preinfra <side>`` — prerequisite-infrastructure existence
checks. Mod 042.

Replaces mod 034's stub handler with real per-(foundation, side) checks.
The doctrine contract (``docex.md`` § preinfra) is "checks status; does
not fix or create". Every failure is enumerated in a single pass so the
operator sees all problems at once rather than fix-one-rerun-fix-next.

What gets checked, per (foundation, side):

- Any project, ``development`` side
    - The ``docex-ingress`` docker bridge network exists locally.
    - Each ``dev`` web hostname resolves in public DNS (mod 054). `dev`
      is brought up with HTTP-01 cert issuance; an unresolved hostname
      fails the challenge and burns Let's Encrypt's failed-authorization
      rate limit. Skipped when ``infra.yml`` is absent (e.g. the
      inception-step-3 standalone run before infra.yml exists).
    - On a ``fixed`` project with a ``container_registry``: the registry
      accepts a manifest ``DELETE`` (mod 133). Every ``fixed`` project's
      ``teardown.sh`` depends on that capability; without
      ``REGISTRY_STORAGE_DELETE_ENABLED`` the registry answers ``405
      UNSUPPORTED`` and each project leaks one registry tag per release,
      with garbage collection unable to start.

- Fixed project, ``production`` side
    - The ``docex-ingress`` bridge exists locally (single-machine
      fixed). Remote-host fixed prod is deferred multi-machine work.
    - The target host carries the registry credential at both paths the
      release playbook uses (``/home/deploy/.docker/config.json`` and
      ``/root/.docker/config.json``), probed via SSH using the per-env
      ``infra/deploy_creds/<env>`` keys. Catches the first-release 401
      one tier before ``release`` instead of at ``docker compose pull``.

- Elastic project, ``production`` side
    - In addition to ``docex-ingress``: the master VPC exists with the
      doctrine-prescribed tags (mod 041) and has at least 2 public
      subnets (``tier=public``), at least 2 private subnets
      (``tier=private``), and a primary-AZ (``us-east-1a``) private
      subnet that elastic workloads pin to.

What is intentionally NOT checked (per the design):

- HAProxy web demux on the host (operator-managed via the
  docex-preinfra skill; no automation hook yet).
- Observability backend URL reachability (per ``telemetry_infra.md``
  that's a ``docex check`` concern).
- Container registry *availability / reachability*, and whether the
  operator holds a working credential for it. ``docex containerize``
  surfaces both naturally, and ``preinfra development`` is the gate
  ``envinfra up dev`` runs — a dev stack that never touches a registry
  must not be blocked because the operator has not yet logged in.

Mod 133 splits the registry into two questions and keeps only one of
them in scope:

- *Configuration* — does the registry permit manifest deletes? In
  scope, and a confirmed refusal (``405`` carrying the registry's own
  ``UNSUPPORTED`` code) is a **failure**, rc 1. It is prerequisite
  infrastructure not being in the form ``teardown.sh`` requires.
- *Reachability and auth* — no credential, unreachable host, TLS or DNS
  failure, timeout, ``401``/``403``, or any response that cannot be read
  as a verdict (notably a bare ``405`` from a proxy that the registry may
  never have seen). These are the excluded concerns above, so they are
  out of scope rather than unanswered: each is **printed by name in the
  ``Declined`` block with its own resolution, at rc 0**. Declining is
  never silent, but declining an out-of-scope question is a different act
  from failing an in-scope one, and one exit code cannot express both.

The fixed-*production* side separately verifies that the deploy hosts
carry the registry *credential* (see above); that is a distinct concern
from either of the two above.
"""

from __future__ import annotations

from docex.aws.client import AWSClient
from docex.context import ProjectContext
from docex.dns.client import DnsResolver
from docex.docker.client import DockerClient
from docex.naming import dns_label
from docex.registry.client import RegistryClient
from docex.ssh.client import SSHClient

# Doctrine-prescribed master VPC tags (Mod 060). Must match the
# `data "aws_vpc" "master"` filter in project.tf.j2. The lookup is on the
# semantic preinfra identity tags (cicl.md § Naming and Tagging), NOT the
# redundant console-only `Name`. The master network is operator-managed
# preinfra, so `managed_by=doctrine-operator`. Subnet lookups still match
# the resource-local `tier=public|private` tags (unchanged).
_MASTER_VPC_TAGS: dict[str, str] = {
    "managed_by": "doctrine-operator",
    "infra_tier": "prerequisite",
    "shape_name": "master_network",
}
_DOCEX_INGRESS_NETWORK = "docex-ingress"
_PRIMARY_AZ = "us-east-1a"

# The manifest-delete probe's target (mod 133). `preinfra-smoke/` is the
# namespace the doctrine already reserves for registry verification; this
# repository does not exist and a 64-zero digest cannot exist, so the
# request is side-effect-free BY CONSTRUCTION — nothing is uploaded and
# nothing can be deleted. That matters because `preinfra development`
# runs as the `envinfra up dev` precondition, against preinfra shared by
# every project on the machine.
_DELETE_PROBE_REPOSITORY = "preinfra-smoke/delete-capability-probe"
_DELETE_PROBE_DIGEST = "sha256:" + "0" * 64
# Registry error codes that prove the delete gate was passed: reaching
# the manifest lookup at all means `deleteEnabled` was not the answer.
_MANIFEST_ABSENT_CODES = frozenset(
    {"MANIFEST_UNKNOWN", "NAME_UNKNOWN", "BLOB_UNKNOWN"}
)


def run_preinfra(
    ctx: ProjectContext,
    docker: DockerClient,
    aws: AWSClient | None,
    *,
    side: str,
    ssh: SSHClient | None = None,
    dns: DnsResolver | None = None,
    registry: RegistryClient | None = None,
) -> int:
    """Check prerequisite infrastructure for ``side``.

    Returns 0 if every expected resource exists, 1 otherwise (after
    enumerating every failure). ``aws`` is required iff the project's
    foundation is elastic and ``side`` is ``production``; callers
    (the dispatcher) construct it lazily for that case only so fixed-
    only operators don't need AWS creds to check the development side.

    ``ssh`` is required iff the project's foundation is fixed and
    ``side`` is ``production`` — the dispatcher constructs it lazily
    for that case (mirroring ``aws``) so the registry-cred probe can
    reach the target host. It stays ``None`` on every other branch.

    ``dns`` is required on the ``development`` side (mod 054); the
    dispatcher always supplies it there so the dev-web-hostname DNS
    check can run. Unused on the production side.

    ``registry`` is required on the ``development`` side of a ``fixed``
    project that declares a ``container_registry`` (mod 133), for the
    manifest-delete capability probe.

    Some outcomes are *declined* rather than failed: printed by name with
    their own resolution, but never affecting the exit code. See the
    module docstring for which questions are in scope and why.
    """
    failures: list[str] = []
    declined: list[str] = []

    # Every side check needs the docker bridge — both fixed envs and
    # elastic dev-side envs run as docker stacks on the operator's
    # local machine.
    if not docker.network_exists(_DOCEX_INGRESS_NETWORK):
        failures.append(
            f"docker bridge network {_DOCEX_INGRESS_NETWORK!r} does "
            f"not exist. Create it via the docex-preinfra skill: "
            f"`docker network create {_DOCEX_INGRESS_NETWORK}`."
        )

    # Development side: every `dev` web hostname must resolve publicly
    # before `envinfra up dev` fires LE HTTP-01. Guarded on `ctx.infra`
    # so the inception-step-3 standalone run (before infra.yml exists)
    # is a no-op — matching every other infra-dependent check here.
    if side == "development" and ctx.infra is not None:
        if dns is None:
            failures.append(
                "development side requires a DNS resolver but none was "
                "provided (this is a dispatcher bug)."
            )
        else:
            failures.extend(_check_dev_dns(ctx, dns))

        # Mod 133: the registry's manifest-delete capability. Elastic, and
        # fixed-without-a-registry, produce NOTHING AT ALL — not even a
        # declination. The question does not apply: elastic uses ECR, where
        # deletion is IAM-governed and teardown removes the repository
        # wholesale. Printing "skipped" on every invocation would be noise
        # that trains the reader to skim.
        if ctx.infra.foundation == "fixed" and ctx.infra.container_registry:
            if registry is None:
                failures.append(
                    "development side requires a registry client but none was "
                    "provided (this is a dispatcher bug)."
                )
            else:
                f, d = _check_registry_manifest_delete(ctx, registry)
                failures.extend(f)
                declined.extend(d)

    # Fixed + production: the target host's registry credential.
    if (
        ctx.infra is not None
        and ctx.infra.foundation == "fixed"
        and side == "production"
    ):
        if ssh is None:
            # Defensive: the dispatcher is responsible for supplying an
            # SSH client on this branch (mirrors the aws-None guard).
            failures.append(
                "fixed production side requires an SSH client but none "
                "was provided (this is a dispatcher bug)."
            )
        else:
            failures.extend(_check_fixed_registry_creds(ctx, ssh))

    # Elastic + production: master VPC and tagged subnets.
    if (
        ctx.infra is not None
        and ctx.infra.foundation == "elastic"
        and side == "production"
    ):
        if aws is None:
            # Defensive: the dispatcher is responsible for supplying
            # an AWS client on this branch. If it didn't, we surface
            # the bug rather than silently skipping the check.
            failures.append(
                "elastic production side requires an AWS client but "
                "none was provided (this is a dispatcher bug)."
            )
        else:
            failures.extend(_check_elastic_master_vpc(aws))

    if failures:
        print(f"preinfra {side} side: {len(failures)} check(s) failed:")
        for f in failures:
            print(f"  - {f}")
    else:
        print(f"preinfra {side} side: all checks passed.")
    # Declinations are an addendum to the verdict, never the verdict — so
    # they print after the pass/fail line and do not touch the exit code.
    # Each is named individually: a *count* of declinations is not a
    # declaration, and the operator must not be left guessing which mode
    # occurred.
    if declined:
        print(
            "Declined — printed, not failures. A verifier may decline to "
            "answer, but not quietly:"
        )
        for d in declined:
            print(f"  - {d}")
    return 1 if failures else 0


def _check_dev_dns(ctx: ProjectContext, dns: DnsResolver) -> list[str]:
    """Verify every ``dev`` web hostname resolves in public DNS.

    ``dev`` is brought up with HTTP-01 cert issuance; unresolved
    hostnames trip LE's failed-authorization limit. We check ``dev``
    only — ``test`` is no longer routed/TLS'd (mod 054), and stage/prod
    resolve at release time.
    """
    from docex.cicl.compile import web_hostnames_for_env

    hosts = web_hostnames_for_env(
        ctx.infra, ctx.project.name, "dev", ctx.transfer_tables.naming_policies
    )
    failures: list[str] = []
    for host in hosts:
        try:
            ok = dns.resolves(host)
        except Exception as exc:  # noqa: BLE001 — surface, don't crash
            # A transient/network resolver error is "couldn't check",
            # which is distinct from a confirmed non-resolution.
            failures.append(
                f"could not check DNS for dev host {host!r} ({exc}); "
                f"resolve transient resolver issues and re-run."
            )
            continue
        if not ok:
            failures.append(
                f"dev host {host!r} does not resolve in public DNS. "
                f"Route it to the dev machine (registrar or Route53) "
                f"before `envinfra up dev` — unresolved dev hosts trip "
                f"Let's Encrypt's failed-authorization rate limit. See "
                f"inception.md PART III."
            )
    return failures


def _check_registry_manifest_delete(
    ctx: ProjectContext, registry: RegistryClient,
) -> tuple[list[str], list[str]]:
    """Probe whether the registry will accept a manifest ``DELETE``.

    Returns ``(failures, declined)``. One request, zero bytes uploaded, no
    side effects: a ``DELETE`` of a nonexistent digest under a nonexistent
    repository.

    WHY that suffices, and what it infers: ``registry:2`` checks
    ``deleteEnabled`` *before* any manifest lookup, so a delete-disabled
    registry answers ``405 UNSUPPORTED`` without a manifest needing to
    exist. Reaching the lookup instead — ``404 MANIFEST_UNKNOWN`` — proves
    the gate was passed. That reading is an inference, and it is pinned by
    a test rather than trusted: `tests/integration/
    test_preinfra_registry_delete_real.py` brings up the doctrine-pinned
    image with the flag off and asserts ABSENT, so a registry version that
    ever stops discriminating turns that test red instead of silently
    turning this probe into a rubber stamp.
    """
    host = ctx.infra.container_registry
    result = registry.delete_manifest(
        host, _DELETE_PROBE_REPOSITORY, _DELETE_PROBE_DIGEST
    )
    prefix = "registry manifest-delete probe"

    # An explicit ladder ending in a catch-all declination. The rule this
    # whole check exists to honour: "capability present" may be produced
    # ONLY by an observation that positively proves it, so there is no
    # implicit fall-through — only the two `return [], []` rows below.
    if result.failure == "no_credential":
        return [], [
            f"{prefix}: no credential to probe with — {result.detail}. "
            f"Run `docker login {host}` if you want this checked; `dev` "
            f"builds locally and does not need it, so this does not block "
            f"bring-up."
        ]
    if result.failure == "bad_credential_store":
        return [], [
            f"{prefix}: credential is held by an external helper — "
            f"{result.detail}. docex will not invoke a "
            f"credsStore/credHelpers helper; the capability is unverified "
            f"until an inline auth entry exists for {host!r}."
        ]
    if result.failure == "transport":
        return [], [
            f"{prefix}: no response — {result.detail}. Registry "
            f"reachability is out of scope here (`docex containerize` "
            f"surfaces it); the delete capability is unverified."
        ]
    if result.failure is not None:
        # A failure mode this ladder does not name yet. Declining is the
        # only safe reading: an unrecognized failure must never reach the
        # status rungs below, where `status is None` would otherwise be
        # described as a response.
        return [], [
            f"{prefix}: could not complete the probe "
            f"({result.failure!r}) — {result.detail}. The delete "
            f"capability is unverified."
        ]
    if result.status == 405 and result.error_code == "UNSUPPORTED":
        return [
            f"registry {host!r} refuses manifest DELETE (405 UNSUPPORTED) "
            f"— the delete capability is disabled. Set "
            f'REGISTRY_STORAGE_DELETE_ENABLED: "true" in the registry\'s '
            f"environment "
            f"(/opt/docex-preinfra/container_registry/registry/"
            f"docker-compose.yml) and restart it. Without it every `fixed` "
            f"project's `teardown.sh` leaks one registry tag per release "
            f"and registry garbage collection cannot start."
        ], []
    if result.status == 405:
        # The false-positive arm. A reverse proxy can reject the method
        # before the registry ever sees it; reporting that as a
        # delete-disabled registry invents a misconfiguration.
        return [], [
            f"{prefix}: 405 from {host!r} but WITHOUT the registry's own "
            f"UNSUPPORTED error code (got {result.error_code!r}) — "
            f"something between docex and the registry rejected the "
            f"method, and the registry may never have seen it. Not "
            f"reported as a delete-disabled registry; check for a reverse "
            f"proxy that blocks DELETE."
        ]
    if result.status in (401, 403):
        return [], [
            f"{prefix}: credential rejected or lacks delete scope (HTTP "
            f"{result.status}) from {host!r}. Every DELETE gets a 401 "
            f"regardless of the delete setting — the auth middleware runs "
            f"ahead of the handler — so this is no verdict either way. "
            f"Re-run `docker login {host}`. Auth is out of scope here."
        ]
    if result.status == 404 and result.error_code in _MANIFEST_ABSENT_CODES:
        # PASS: the delete gate was passed and the manifest lookup reached.
        return [], []
    if result.status == 202:
        # PASS: the capability was directly observed.
        return [], []
    if result.status == 404:
        return [], [
            f"{prefix}: 404 from {host!r} with no registry error code — "
            f"that is a proxy 404, not the registry answering. Verify "
            f"{host!r} routes /v2/ to the registry."
        ]
    return [], [
        f"{prefix}: unexpected response from {host!r} (HTTP "
        f"{result.status}, error code {result.error_code!r}) — no verdict "
        f"can be read from it. {result.detail}"
    ]


def _check_fixed_registry_creds(ctx: ProjectContext, ssh: SSHClient) -> list[str]:
    """Verify both deploy hosts carry the registry credential at the two
    paths the release playbook uses. Probes stage AND prod (the
    'production side' covers both); for a single shared fixed host the
    two probes harmlessly hit the same machine.

    The release playbook pulls as ``deploy`` and runs ``compose up``
    under ``become: true`` (root), so both ``~/.docker/config.json``
    paths must exist. A local ``Path.is_file()`` can't read under the
    mode-700 ``/root`` from the operator's non-root process, so we probe
    over SSH exactly as release reaches the host.
    """
    failures: list[str] = []
    registry = ctx.infra.container_registry or "<registry>"
    label = dns_label(ctx.project.name)
    # stage → stage.<label>.<apex>; prod → bare-project host <label>.<apex>
    # (per release.md § Inventory).
    hosts = {
        "stage": f"stage.{label}.{ctx.infra.apex_domain}",
        "prod": f"{label}.{ctx.infra.apex_domain}",
    }
    # One probe verifying both config paths: deploy's own and root's
    # (the latter via passwordless sudo, which release already assumes).
    probe = (
        "test -f /home/deploy/.docker/config.json "
        "&& sudo -n test -f /root/.docker/config.json"
    )
    for env in ("stage", "prod"):
        key = ctx.project_root / "infra" / "deploy_creds" / env
        if not key.is_file():
            failures.append(
                f"infra/deploy_creds/{env} missing — needed to reach the "
                f"{env} host to verify registry creds."
            )
            continue
        host = hosts[env]
        rc = ssh.run(host, key, probe)
        if rc == 0:
            continue
        if rc == 255:
            failures.append(
                f"could not reach {env} host {host!r} via "
                f"infra/deploy_creds/{env} (SSH connect failed); cannot "
                f"verify registry creds."
            )
        else:
            failures.append(
                f"registry credentials not found on {env} host {host!r} "
                f"(checked /home/deploy/.docker/config.json and "
                f"/root/.docker/config.json). Run `docker login {registry}` "
                f"as both `deploy` and `root` on the host."
            )
    return failures


def _check_elastic_master_vpc(aws: AWSClient) -> list[str]:
    """Verify the master VPC and its tagged subnets exist."""
    failures: list[str] = []
    vpc_id = aws.find_vpc_by_tags(_MASTER_VPC_TAGS)
    if vpc_id is None:
        # No point probing subnets without the VPC; bail with one
        # actionable failure rather than spamming N follow-ons.
        return [
            f"master VPC not found in account. Required tags: "
            f"{_MASTER_VPC_TAGS}. Create via the docex-preinfra skill."
        ]
    public = aws.find_subnet_ids(vpc_id=vpc_id, tags={"tier": "public"})
    if len(public) < 2:
        failures.append(
            f"master VPC {vpc_id} has {len(public)} public subnet(s) "
            f"tagged tier=public; expected at least 2 (AWS requires "
            f"two AZs for ALB)."
        )
    private = aws.find_subnet_ids(vpc_id=vpc_id, tags={"tier": "private"})
    if len(private) < 2:
        failures.append(
            f"master VPC {vpc_id} has {len(private)} private subnet(s) "
            f"tagged tier=private; expected at least 2."
        )
    primary = aws.find_subnet_ids(
        vpc_id=vpc_id,
        tags={"tier": "private"},
        availability_zone=_PRIMARY_AZ,
    )
    if not primary:
        failures.append(
            f"no private subnet found in {_PRIMARY_AZ} (the primary "
            f"AZ). ECS workloads pin here; required."
        )
    return failures
