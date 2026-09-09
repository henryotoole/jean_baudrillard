# Mod 007 — Postgres host part + release cluster-name policy

## Problem

Two more gaps surfaced from the elastic D.7 walk after mod 006 unblocked the SG-egress issue:

### Gap A (blocker) — postgres `host` part embeds the port

`tables/roles/relational_db.yml` declares the postgres engine's `host` provided part as:

```yaml
provides:
  host:
    fixed: "${global_service_name}"
    elastic: "@aws_db_instance.${name}.endpoint"
```

The Terraform attribute `aws_db_instance.X.endpoint` returns the connection endpoint **with the port already appended** (`<host>:<port>`). Consumers — including the project's own `migrate.sh` shim and any app composing a `DATABASE_URL` from parts — then concatenate `:${DATABASE_PORT}` themselves, producing a malformed string of the form `host:port:port`. This blocks the elastic D.7 migration with a DNS-resolution failure:

```
Error: dial tcp: lookup
  docex-smoke-elastic-stage-appdb.cgh0y4iw0oa8.us-east-1.rds.amazonaws.com:5432:5432:
  no such host
```

The doctrine's `cicl.md § Provided Fields` is explicit:

> Restrictions with infra providers (particularly AWS SSM) mean that provided fields must be **values**, and can not be strings which are interpolated later. A role never exposes a pre-composed connection string. A consumer that needs a composed handle (e.g. a database url) builds it from the parts at startup.

The current `host` value violates this in spirit (and in practice): `endpoint` is a pre-composed `host:port` masquerading as a host. The correct AWS Terraform attribute is `aws_db_instance.X.address` — the hostname only, no port. Fix is one word.

### Gap B (polish) — `release.py`'s cluster-existence check ignores the ecs naming policy

`src/docex/pipeline/release.py:212` builds the ECS cluster name used for the first-time-release detection probe as a literal:

```python
cluster_name = f"{project_name}-{env}"
```

This uses the old (pre-mod-005) hyphen-join convention. After mod 005, the emitted ECS cluster name flows through the `ecs` naming policy (`underscore` separator), so the live cluster is named e.g. `docex_smoke_elastic_stage`, not `docex_smoke_elastic-stage`. The detector therefore *always* reports the cluster as absent and falls into the first-time-release branch — even on second and subsequent releases.

This is non-breaking because the first-time branch runs `tofu apply` ahead of the migration step rather than after, and `tofu apply` is idempotent on a converged stack. But the log message ("ECS cluster '...' not yet provisioned — first-time release detected") is misleading on every steady-state release, and the ordering swap is wasted work each time. The detector should use the same naming policy the emitter does.

## Design

### Fix A — postgres `host.elastic` = `.address`

In `tables/roles/relational_db.yml`, change one line under `roles.relational_db.postgres.provides.host.elastic`:

```yaml
# was:
elastic: "@aws_db_instance.${name}.endpoint"
# becomes:
elastic: "@aws_db_instance.${name}.address"
```

That's it. The fixed-side resolution (`${global_service_name}`) is correct — docker DNS resolves the bare container name to its IP. The elastic-side `.address` is the hostname, matching the fixed-side semantics: "the host, no port". Consumers compose `host:port` themselves and get the right result.

No other transfer-table changes. The schema is unchanged; the doctrine prose is unchanged (the spirit was always "parts only — never composed handles"; this fixes a violation of that spirit).

### Fix B — `release.py` uses the ecs naming policy

In `src/docex/pipeline/release.py`, replace the literal hyphen-join with a policy-applied form:

```python
# was:
cluster_name = f"{project_name}-{env}"

# becomes:
ecs_policy = ctx.transfer_tables.naming_policies.get("ecs")
cluster_name = apply_policy(f"{project_name}_{env}", ecs_policy)
```

The function already has `ctx` in scope (it's the entry point) and `ctx.transfer_tables` is populated by the standard load. Add the `apply_policy` import from `docex.naming`.

The literal `"ecs"` policy name is hardcoded here in docex code — same pattern as bootstrap.py for the state-backend bucket (mod 005). Structural emitters pick policies by hardcoded name; only engine-level naming refs live in the transfer tables.

### Doctrine touchpoints

- `cicl.md § Provided Fields` already says the right thing (parts-only, no composed handles). No change needed.
- No other doctrine update.

## Five-artifact alignment

| Artifact | Change |
| -------- | ------ |
| `doctrine/.../*.md` | No change. The doctrine already prescribes parts-only; Fix A brings the transfer table back into alignment with it. |
| `docex/plans/core/*.md` | No change. |
| `tables/roles/*.yml` | `relational_db.yml` — one-word change: `endpoint` → `address` (Fix A). |
| `src/docex/**` | `pipeline/release.py` — apply the `ecs` policy when building `cluster_name` (Fix B). |
| `tests/**` | Snapshot/integration: emitted HCL's `DATABASE_HOST` env-entry value is `${aws_db_instance.<svc>.address}`, NOT `.endpoint`. Unit test on release.py's cluster-name computation: given a project named `foo_bar`, the cluster name probed is `foo_bar_stage` (or whatever the ecs policy produces), not `foo-bar-stage`. |

## Validation

1. `python3 -m pytest tests/` — green.
2. Recompile `test_projects/elastic`. Confirm:
   - `grep "aws_db_instance.appdb.address" infra/output/stage/main.tf` returns matches (the DATABASE_HOST env entry).
   - `grep "aws_db_instance.appdb.endpoint" infra/output/stage/main.tf` returns nothing.
3. Resume D.7 walk: `docex release stage` succeeds, migration completes, `https://stage.doctrine-elastic.luxrnd.tech/health` returns 200.

## Decisions captured

1. **`.address`, not a composed handle.** Doctrine is parts-only (per `cicl.md § Provided Fields`). The current `.endpoint` value was a stealth composed handle; `.address` fixes that.
2. **No other postgres part changes.** `port`, `db`, `user`, `password` are all parts as documented. Only `host` was wrong.
3. **Hardcoded policy name in `release.py`.** Consistent with mod 005 pattern for structural emitters (bootstrap.py uses `"s3"` and `"ddb"` the same way). The policy *choice* is doctrine knowledge in code; the policy *body* still comes from `naming_policies:` so it stays reloadable.

## Open questions

(None. Both fixes are unambiguous and directly verified against the failing walk.)
