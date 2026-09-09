# Mod 042 — `preinfra <side>` Implementations

Thirteenth mod of the [doctrine-shape-and-tier advance](../../advances/shape_overhaul_mod_list.md). Replaces mod 034's stub `preinfra` handler with real per-foundation checks.

## The Doctrine Change

From [`docex.md § preinfra`](../../../../doctrine/infrastructure/docex.md#preinfra):

> Checks that the necessary prerequisite infrastructure resources exist for this project to launch on the indicated infrastructure side. Command does not fix or create preinfra. It only checks status.

And the precondition contract from `docex.md`:

> `projinfra up <side>` and `envinfra up <env>` refuse to run if `preinfra <side>` fails.

## What gets checked, per (foundation, side)

| (Foundation, Side) | Checks |
| ------------------ | ------ |
| Any, development | `docex-ingress` docker bridge exists on local docker |
| Fixed, production | `docex-ingress` docker bridge exists on local docker (single-machine fixed; remote-host case is deferred multi-machine work) |
| Elastic, production | Master VPC exists in AWS with the doctrine-prescribed tags from mod 041 (`Name = "docex-master-vpc"`, `managed_by = "docex-preinfra"`); both public subnets exist (tag `tier = public`); both private subnets exist (tag `tier = private`); primary-AZ private subnet exists (us-east-1a) |

Mod 042 explicitly does NOT check:
- HAProxy web demux on the host (no automation hook yet; the operator's docex-preinfra skill setup covers it manually).
- Observability backend URL reachability (per `telemetry_infra.md` that's a `docex check` concern, not preinfra).
- Container registry availability (covered by `docex containerize`'s push step naturally).

## Concrete file surface

### `src/docex/__main__.py:_cmd_preinfra`

Replace the stub body. New shape:

```python
def _cmd_preinfra(args: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="docex preinfra", add_help=True)
    parser.add_argument("side", choices=["development", "production"])
    ns = parser.parse_args(args)

    from docex.context import load_project_context
    from docex.pipeline.preinfra import run_preinfra

    ctx = load_project_context(Path(os.getcwd()))
    docker = _require_docker()
    aws = _make_aws_client() if (
        ctx.infra.foundation == "elastic" and ns.side == "production"
    ) else None
    return run_preinfra(ctx, docker, aws, side=ns.side)
```

`_make_aws_client` only called when AWS is actually needed (elastic production).

### New module `src/docex/pipeline/preinfra.py`

```python
"""Prerequisite-infrastructure existence checks. Mod 042."""
from __future__ import annotations

from docex.context import ProjectContext
from docex.docker.client import DockerClient
from docex.aws.client import AWSClient

# Doctrine-prescribed master VPC tags. Must match the data-source
# lookups in project.tf.j2 (mod 041).
_MASTER_VPC_TAGS = {
    "Name": "docex-master-vpc",
    "managed_by": "docex-preinfra",
}
_DOCEX_INGRESS_NETWORK = "docex-ingress"


def run_preinfra(
    ctx: ProjectContext,
    docker: DockerClient,
    aws: AWSClient | None,
    *,
    side: str,
) -> int:
    """Check prerequisite infrastructure for the given side. Returns 0
    if all expected resources exist; non-zero on the first failure.

    Implemented for:
    - Any project (development side): docex-ingress docker bridge.
    - Fixed project (production side): docex-ingress docker bridge
      (single-machine; multi-machine fixed deferred per
      infrastructure.md § Deferred).
    - Elastic project (production side): master VPC and its 4 subnets,
      tag-discovered per mod 041's data-source filters.
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

    # Elastic production: also check master VPC + subnets.
    if ctx.infra.foundation == "elastic" and side == "production":
        if aws is None:
            failures.append(
                "elastic production side requires AWS client but none "
                "was provided (this is a bug)."
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
    """Verify the master VPC and its 4 subnets exist tagged correctly."""
    failures: list[str] = []
    vpc_id = aws.find_vpc_by_tags(_MASTER_VPC_TAGS)
    if vpc_id is None:
        return [
            f"master VPC not found in account. Required tags: "
            f"{_MASTER_VPC_TAGS}. Create via the docex-preinfra skill."
        ]
    # Subnet checks — counts only (existence + tag filter).
    pub = aws.find_subnet_ids(vpc_id=vpc_id, tags={"tier": "public"})
    if len(pub) < 2:
        failures.append(
            f"master VPC has {len(pub)} public subnet(s) tagged "
            f"tier=public; expected at least 2 (AWS requires two AZs "
            f"for ALB)."
        )
    priv = aws.find_subnet_ids(vpc_id=vpc_id, tags={"tier": "private"})
    if len(priv) < 2:
        failures.append(
            f"master VPC has {len(priv)} private subnet(s) tagged "
            f"tier=private; expected at least 2."
        )
    primary = aws.find_subnet_ids(
        vpc_id=vpc_id, tags={"tier": "private"},
        availability_zone="us-east-1a",
    )
    if not primary:
        failures.append(
            "no private subnet found in us-east-1a (the primary AZ). "
            "ECS workloads pin here; required."
        )
    return failures
```

### Extend `DockerClient`

Add to `src/docex/docker/client.py` (Protocol) and `src/docex/docker/subprocess_client.py`:

```python
def network_exists(self, name: str) -> bool:
    """True iff the named docker network exists on the local daemon."""
    ...
```

Subprocess impl:

```python
def network_exists(self, name: str) -> bool:
    result = subprocess.run(
        ["docker", "network", "inspect", name],
        capture_output=True, text=True, check=False,
    )
    return result.returncode == 0
```

### Extend `AWSClient`

Add to `src/docex/aws/client.py` (Protocol) and `src/docex/aws/boto3_client.py`:

```python
def find_vpc_by_tags(self, tags: dict[str, str]) -> str | None:
    """Return the VPC ID that carries every (key, value) pair in tags,
    or None if no such VPC exists. If multiple match, returns the first
    (operator setup should produce exactly one)."""
    ...

def find_subnet_ids(
    self, *, vpc_id: str, tags: dict[str, str],
    availability_zone: str | None = None,
) -> list[str]:
    """Return subnet IDs in the given VPC matching all tags (and AZ if
    set). Empty list if none match."""
    ...
```

boto3 impl uses `ec2.describe_vpcs(Filters=[...])` / `describe_subnets(Filters=[...])` with tag filters in the `tag:Key` / `tag:Value` form AWS uses.

### Wire `projinfra up <side>` and `envinfra up <env>` precondition checks

Per the doctrine, these commands refuse if `preinfra` fails. Mod 036 explicitly deferred this; mod 042 lands it.

`src/docex/pipeline/projinfra.py:run_projinfra_fixed_up`:

```python
def run_projinfra_fixed_up(ctx, docker, aws=None, *, side):
    # Precondition: preinfra must pass.
    from docex.pipeline.preinfra import run_preinfra
    rc = run_preinfra(ctx, docker, aws, side=side)
    if rc != 0:
        print(f"error: preinfra {side} failed; aborting projinfra up.")
        return rc
    # ... existing body ...
```

Similar gate on elastic projinfra (the `run_bootstrap` branch in `_cmd_projinfra`) and on `envinfra up`.

The dispatcher passes `aws` only when needed (or just always — `_make_aws_client` is cheap; preinfra-fixed-development doesn't actually call it). Implementer's discretion.

### Tests

`tests/unit/test_pipeline_preinfra.py` (new):

- `test_preinfra_dev_passes_when_bridge_exists`: stub DockerClient returning `network_exists=True`; assert exit 0.
- `test_preinfra_dev_fails_when_bridge_missing`: assert exit 1 with the right message substring.
- `test_preinfra_elastic_prod_checks_aws`: stub AWSClient returning valid VPC + 2+2 subnets + primary; assert exit 0.
- `test_preinfra_elastic_prod_fails_when_vpc_missing`: assert exit 1.
- `test_preinfra_elastic_prod_fails_when_subnets_insufficient`: assert exit 1 per shortage.
- `test_preinfra_elastic_prod_fails_when_no_primary_az_subnet`: assert exit 1.
- `test_preinfra_dispatcher_passes_aws_only_when_needed`: dispatcher test that `_make_aws_client` isn't called for dev side.

`tests/unit/test_pipeline_projinfra.py` (existing): update existing tests so `run_projinfra_fixed_up` is now gated on preinfra. Add a precondition-fail test.

`tests/unit/test_dispatcher.py`: update `_cmd_preinfra` tests to reflect non-stub behavior (the old assertion that it prints "stub" needs to flip to checking real behavior or be deleted).

### `tests/conftest.py`

Extend `FakeDockerClient` with `network_exists` (scripted-result attribute, like `any_env_compose_up`).

Extend `FakeAWSClient` (if it exists; if not, add one) with `find_vpc_by_tags` and `find_subnet_ids` scripted-result attributes.

## Ramifications

### Lazy AWS client construction

The dispatcher should only construct an AWS client when actually needed (elastic + production). Otherwise a fixed-only operator without AWS creds in `~/.aws/credentials` would hit an unnecessary error when running `preinfra development`.

### Failure listing

The current stub returns 0 unconditionally with a single line. The new implementation enumerates *every* failure, not just the first — better for the operator who'd otherwise have to fix one thing, re-run, fix the next, etc. List all of them in one pass.

### `projinfra` and `envinfra` precondition gating

After mod 042, missing preinfra cleanly aborts `projinfra up` and `envinfra up` with a pointer at the failing check. Mod 036 deferred this; mod 042 closes the loop.

## Operator Decisions Needed

1. **Failure enumeration vs. fail-fast** — enumerate all failures in one pass (recommended) or stop at first? Enumerate is friendlier; cost is small.

2. **AWS client construction** — lazy (only when needed) vs. always. Recommend lazy: avoids surfacing AWS-cred issues to fixed-only operators.

3. **`network_exists` Docker check** — `docker network inspect` returns non-zero when the network doesn't exist. That's the simplest detection. Confirm.

## What This Mod Is NOT

- **No HAProxy web demux check** — the operator manages that out-of-band via docex-preinfra skill. No automation hook in mod 042.
- **No observability backend URL probe** — per `telemetry_infra.md` that's a `docex check` concern.
- **No container registry probe** — `docex containerize` surfaces registry issues naturally.
- **No fixed-foundation remote prod host check** — multi-machine fixed deferred.
- **No EC2-traefik variant preinfra** — mod 044 introduces the variant.
- **No `test_projects/{fixed,elastic}/` edits.**
