# Implementation — Mod 042 — `preinfra <side>` Implementations

## Context for fresh-context implementer

You are executing mod 042. Read [`overview.md`](./overview.md) first.

Invoke the `docex-edit` skill via Skill.

Authoritative doctrine reading:
- [`docex.md § preinfra`](../../../../doctrine/infrastructure/docex.md#preinfra) — command contract.
- [`shape.md`](../../../../doctrine/infrastructure/shape.md) — both foundations' preinfra resource lists.
- The master VPC tag scheme set by mod 041 (`Name = "docex-master-vpc"`, `managed_by = "docex-preinfra"`, subnet `tier = public|private`).

## Operator decisions binding on this implementation

Per [`overview.md § Operator Decisions`](./overview.md#operator-decisions):

- Enumerate every failure in one pass.
- Lazy AWS client construction.
- `docker network inspect` for `network_exists`.

## Step-by-step plan

### Step 1 — Extend `DockerClient` with `network_exists`

`src/docex/docker/client.py` (Protocol) and `src/docex/docker/subprocess_client.py`:

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

### Step 2 — Extend `AWSClient` with VPC + subnet lookups

`src/docex/aws/client.py` (Protocol) and `src/docex/aws/boto3_client.py`:

```python
def find_vpc_by_tags(self, tags: dict[str, str]) -> str | None:
    """Return the first VPC ID matching every (key, value) in tags, or
    None if no match. Operator setup should produce exactly one."""

def find_subnet_ids(
    self, *, vpc_id: str, tags: dict[str, str],
    availability_zone: str | None = None,
) -> list[str]:
    """Return subnet IDs in vpc_id matching all tags. If availability_zone
    is set, also filter by it. Empty list if none match."""
```

boto3 impl: use `ec2.describe_vpcs(Filters=[{"Name": "tag:Key", "Values": [Value]}, ...])` and `ec2.describe_subnets(...)` similarly.

### Step 3 — Create `src/docex/pipeline/preinfra.py`

Per [`overview.md § New module src/docex/pipeline/preinfra.py`](./overview.md#new-module-srcdocexpipelinepreinfrapy). Key shapes:
- Module-level constants for the master VPC tags and `docex-ingress` network name.
- `run_preinfra(ctx, docker, aws, *, side)` accumulates failures from every check, then either returns 0 with success message or 1 with the enumerated failure list.
- `_check_elastic_master_vpc(aws)` returns a list of failure strings (empty = OK).

### Step 4 — Wire `_cmd_preinfra` to real behavior

Replace the stub body in `src/docex/__main__.py`:

```python
def _cmd_preinfra(args: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="docex preinfra", add_help=True)
    parser.add_argument("side", choices=["development", "production"])
    ns = parser.parse_args(args)

    from docex.context import load_project_context
    from docex.pipeline.preinfra import run_preinfra

    ctx = load_project_context(Path(os.getcwd()))
    docker = _require_docker()
    aws = (
        _make_aws_client()
        if ctx.infra.foundation == "elastic" and ns.side == "production"
        else None
    )
    return run_preinfra(ctx, docker, aws, side=ns.side)
```

### Step 5 — Gate `projinfra up <side>` on preinfra

Edit `src/docex/pipeline/projinfra.py:run_projinfra_fixed_up`:

```python
def run_projinfra_fixed_up(ctx, docker, *, side):
    from docex.pipeline.preinfra import run_preinfra
    rc = run_preinfra(ctx, docker, aws=None, side=side)
    if rc != 0:
        print(f"error: preinfra {side} failed; aborting projinfra up.")
        return rc
    # ... existing body
```

Note: `run_projinfra_fixed_up` is fixed-only, so `aws=None` is correct (preinfra fixed-side doesn't need AWS).

For the elastic projinfra branch in `_cmd_projinfra` (which currently runs `run_bootstrap` for `up production`):

```python
if (ctx.infra.foundation == "elastic" and ns.direction == "up"
        and ns.side == "production"):
    from docex.pipeline.preinfra import run_preinfra
    aws = _make_aws_client()
    rc = run_preinfra(ctx, docker, aws, side="production")
    if rc != 0:
        print("error: preinfra production failed; aborting projinfra up.")
        return rc
    from docex.pipeline.bootstrap import run_bootstrap
    return run_bootstrap(ctx, aws)
```

### Step 6 — Gate `envinfra up <env>` on preinfra

Edit `src/docex/__main__.py:_cmd_envinfra`. Before dispatching to `run_up`:

```python
if ns.direction == "up":
    from docex.pipeline.preinfra import run_preinfra
    # envinfra is dev/test only; always development side; never needs AWS.
    rc = run_preinfra(ctx, docker, aws=None, side="development")
    if rc != 0:
        print(f"error: preinfra development failed; aborting envinfra up.")
        return rc
    from docex.orchestrate.up import run_up
    return run_up(ctx, docker, env=ns.env)
```

Don't gate `envinfra down` — preinfra existence isn't a precondition for teardown.

### Step 7 — Tests

#### `tests/conftest.py`

Extend `FakeDockerClient`:
- `network_exists(name) -> bool` returning a scripted-result attribute `network_exists_results: dict[str, bool]` (default True if not in dict, OR default False — pick the safer default; recommend False to require explicit setup in tests).

Extend `FakeAWSClient` (create if not present):
- `find_vpc_by_tags(tags) -> str | None` returning a scripted attribute.
- `find_subnet_ids(...) -> list[str]` returning a scripted attribute (a dict keyed by some signature, or just a list that the test sets).

#### `tests/unit/test_pipeline_preinfra.py` (new)

Cover:
- Dev side passes when bridge exists; fails (exit 1) when missing.
- Elastic prod passes when VPC + 4 subnets + primary-AZ subnet all exist.
- Elastic prod fails when VPC missing.
- Elastic prod fails when < 2 public or < 2 private subnets.
- Elastic prod fails when no primary-AZ private subnet.
- Multi-failure case: bridge missing AND VPC missing → both reported.

Use `capsys` to capture stdout and assert on substring matches.

#### `tests/unit/test_pipeline_projinfra.py`

Update existing `test_projinfra_fixed_up_runs_compose_up` to stub `network_exists=True` so preinfra passes. Add a new `test_projinfra_fixed_up_refuses_when_preinfra_fails` that scripts `network_exists=False` and asserts exit 1 before any compose call.

#### `tests/unit/test_dispatcher.py`

The existing `_cmd_preinfra` tests probably assert on the "stub" message. Flip them:
- `test_preinfra_dev_dispatches_to_run_preinfra`: mock `run_preinfra`, dispatch `docex preinfra development`, assert called with `aws=None`.
- `test_preinfra_elastic_prod_dispatches_with_aws_client`: ditto with elastic context, assert AWS client is provided.
- `test_preinfra_fixed_prod_no_aws_client`: fixed context + production → no AWS client.

### Step 8 — Run tests

```bash
cd ~/.claude/jean_baudrillard/docex
pytest tests/unit -x
pytest tests/integration -x -m "not integration"
```

### Step 9 — Sanity sweep

```bash
# No "(stub)" preinfra message
grep -rn 'preinfra.*stub\|stub.*preinfra' src/

# preinfra module exists and is the only home for the check logic
ls src/docex/pipeline/preinfra.py
grep -n 'run_preinfra' src/docex/__main__.py src/docex/pipeline/

# Gates wired
grep -n 'run_preinfra' src/docex/pipeline/projinfra.py src/docex/__main__.py
```

First sweep: zero hits. Others: hits as expected (new module imports + gates).

## Out of scope

- **No HAProxy web demux check** — operator-side via docex-preinfra skill.
- **No observability URL probe** — `docex check` concern per telemetry_infra.md.
- **No container registry probe.**
- **No remote-host fixed prod checks** — multi-machine deferred.
- **No EC2-traefik variant preinfra** — mod 044.
- **No `test_projects/{fixed,elastic}/` edits.**
- **No precondition gating for `envinfra down`** — teardown doesn't need preinfra.

## Done criteria

- [ ] `DockerClient.network_exists` added (Protocol + subprocess impl).
- [ ] `AWSClient.find_vpc_by_tags` + `find_subnet_ids` added (Protocol + boto3 impl).
- [ ] `src/docex/pipeline/preinfra.py` new module with `run_preinfra` enumerating all failures.
- [ ] `_cmd_preinfra` wired to `run_preinfra` (lazy AWS construction).
- [ ] `projinfra up <side>` (fixed and elastic) gated on preinfra; `envinfra up <env>` gated.
- [ ] Test coverage per Step 7.
- [ ] `pytest tests/unit -x` and offline `tests/integration -x -m "not integration"` both green.
- [ ] No `test_projects/{fixed,elastic}/` edits.
- [ ] Sanity sweeps clean — no "(stub)" preinfra message left.

Working tree dirty when finished. Do not commit.
