# Mod 007 — Implementation Steps

Read `overview.md` in this folder first. You are running in a fresh context. Work through the steps in order. Run tests. Leave everything uncommitted.

## Scope

Two narrow surgical fixes:

- **Fix A**: change one word in `tables/roles/relational_db.yml` — postgres `provides.host.elastic` from `@aws_db_instance.${name}.endpoint` to `@aws_db_instance.${name}.address`. `.endpoint` returns `host:port`, which produced malformed `host:port:port` DSNs at consumer-side composition. `.address` is hostname only, matching the parts-only doctrine and the fixed-side resolution semantics.

- **Fix B**: thread the `ecs` naming policy through `src/docex/pipeline/release.py:212` so the first-time-release cluster-existence check probes the actual cluster name (underscore-joined per mod 005's `ecs` policy), not a stale hyphen-joined literal.

## Step 1 — Fix A

File: `tables/roles/relational_db.yml`.

Find the block:

```yaml
roles:
  relational_db:
    postgres:
      ...
      provides:
        host:
          fixed: "${global_service_name}"
          elastic: "@aws_db_instance.${name}.endpoint"
```

Change exactly one line:

```yaml
          elastic: "@aws_db_instance.${name}.address"
```

That's the whole fix. Don't touch the `port`, `db`, `user`, `password` parts. Don't touch the `fixed` side.

## Step 2 — Fix B

File: `src/docex/pipeline/release.py`.

Add the import near the top (group with other docex imports):

```python
from docex.naming import apply_policy
```

Find the line (around 212):

```python
cluster_name = f"{project_name}-{env}"
```

Replace with:

```python
ecs_policy = ctx.transfer_tables.naming_policies.get("ecs")
cluster_name = apply_policy(f"{project_name}_{env}", ecs_policy)
```

`ctx` is in scope (it's the function's first argument; check the signature to confirm the exact attribute path — it's `ctx.transfer_tables` per the loader and per how `bootstrap.py` and `compile.py` reach the same field).

Note: the surrounding comment block (lines ~207-211) says:

> ``cluster_name = f"{project_name}-{env}"`` — first-time-release detection.

After your change, the comment becomes stale. Tighten it:

```python
# First-time-release detection: the env's ECS cluster (named per
# the ``ecs`` naming policy on the project/env pair) is created by
# tofu apply. If it isn't there yet, the migrate step would error
# with "no ACTIVE ECS cluster" before tofu had a chance to create it.
```

Keep the comment short. Match the existing tone.

## Step 3 — Tests

### 3a. HCL emitter snapshot/integration

Find the existing integration test that compiles `test_projects/elastic` (or a sample-project fixture) and asserts on the env `main.tf` content (`tests/integration/test_compile.py` per mod 005/006 history). Add or extend:

- Assert that for stage/prod main.tf, the string `aws_db_instance.appdb.address` appears in the DATABASE_HOST env-entry value.
- Assert that `aws_db_instance.appdb.endpoint` does NOT appear in the same file (regression guard against re-introducing the bug).

Sketch:

```python
def test_db_host_uses_address_not_endpoint(...):
    for env in ("stage", "prod"):
        tf = (out_dir / env / "main.tf").read_text()
        assert "aws_db_instance.appdb.address" in tf
        assert "aws_db_instance.appdb.endpoint" not in tf
```

Adjust to the test file's existing fixture conventions. If the elastic sample-project fixture uses a different backing-service name, adapt accordingly.

### 3b. release.py unit test for cluster-name computation

Find or extend `tests/unit/test_pipeline_release.py`. Add a test that exercises the cluster-name computation:

- Stub the AWS client's `ecs_cluster_exists` to record what `cluster_name` argument it received.
- Run release for a project named `foo_bar` in env `stage`.
- Assert the probe was called with `"foo_bar_stage"` (ecs policy = underscore), not `"foo-bar-stage"`.

If the existing test file already mocks the AWS client, extend that fixture. If not, write the minimal mock.

## Step 4 — Run the suite

```
cd /home/ubuntu/.claude/jean_baudrillard/docex
python3 -m pytest tests/unit/
python3 -m pytest tests/
```

All must pass. Snapshot fixtures referencing `aws_db_instance.X.endpoint` need updating (read the diff, confirm it's the `.address` swap, update).

## Step 5 — Leave uncommitted

Per the mod process, the design-context LLM reviews the diff. Don't commit.

## Hand-off report

In ≤150 words:
- Files changed (this should be a short list).
- Test counts and any fixture updates.
- Any decisions beyond what's in this file.

## Out of scope

- Adding CloudWatch logging to task definitions (the operator has a separate logging-doctrine plan; gap #5 is deferred to its own cycle).
- Rebuilding the docex image or recompiling test_projects (cut-time steps).
- The actual D.7 re-walk (operator does this post-cut).
- Touching the postgres engine's other parts (`port`, `db`, `user`, `password`) — already correct.
