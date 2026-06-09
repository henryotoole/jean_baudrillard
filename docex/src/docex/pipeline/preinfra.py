"""``docex preinfra <side>`` — prerequisite-infrastructure existence
checks. Mod 042.

Replaces mod 034's stub handler with real per-(foundation, side) checks.
The doctrine contract (``docex.md`` § preinfra) is "checks status; does
not fix or create". Every failure is enumerated in a single pass so the
operator sees all problems at once rather than fix-one-rerun-fix-next.

What gets checked, per (foundation, side):

- Any project, ``development`` side
    - The ``docex-ingress`` docker bridge network exists locally.

- Fixed project, ``production`` side
    - Same: the ``docex-ingress`` bridge exists locally (single-machine
      fixed). Remote-host fixed prod is deferred multi-machine work.

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
- Container registry availability (``docex containerize`` surfaces
  registry issues naturally).
"""

from __future__ import annotations

from docex.aws.client import AWSClient
from docex.context import ProjectContext
from docex.docker.client import DockerClient

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
) -> int:
    """Check prerequisite infrastructure for ``side``.

    Returns 0 if every expected resource exists, 1 otherwise (after
    enumerating every failure). ``aws`` is required iff the project's
    foundation is elastic and ``side`` is ``production``; callers
    (the dispatcher) construct it lazily for that case only so fixed-
    only operators don't need AWS creds to check the development side.
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
