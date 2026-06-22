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
- Container registry *availability / reachability* — whether the
  registry itself is up and serving (``docex containerize`` surfaces
  that naturally). The fixed-production side does verify that the
  target host carries the registry *credential* (see above); that is a
  distinct concern from registry reachability.
"""

from __future__ import annotations

from docex.aws.client import AWSClient
from docex.context import ProjectContext
from docex.dns.client import DnsResolver
from docex.docker.client import DockerClient
from docex.naming import dns_label
from docex.ssh.client import SSHClient

# Doctrine-prescribed master VPC tags. Must match the data-source
# lookups in mod 041's project.tf.j2.
_MASTER_VPC_TAGS: dict[str, str] = {
    "Name": "docex-master-vpc",
    "managed_by": "docex-preinfra",
}
_DOCEX_INGRESS_NETWORK = "docex-ingress"
_PRIMARY_AZ = "us-east-1a"


def run_preinfra(
    ctx: ProjectContext,
    docker: DockerClient,
    aws: AWSClient | None,
    *,
    side: str,
    ssh: SSHClient | None = None,
    dns: DnsResolver | None = None,
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
    """
    failures: list[str] = []

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
        return 1
    print(f"preinfra {side} side: all checks passed.")
    return 0


def _check_dev_dns(ctx: ProjectContext, dns: DnsResolver) -> list[str]:
    """Verify every ``dev`` web hostname resolves in public DNS.

    ``dev`` is brought up with HTTP-01 cert issuance; unresolved
    hostnames trip LE's failed-authorization limit. We check ``dev``
    only — ``test`` is no longer routed/TLS'd (mod 054), and stage/prod
    resolve at release time.
    """
    from docex.cicl.compile import web_hostnames_for_env

    hosts = web_hostnames_for_env(ctx.infra, ctx.project.name, "dev")
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
