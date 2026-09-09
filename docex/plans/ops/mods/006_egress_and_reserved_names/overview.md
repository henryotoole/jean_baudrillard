# Mod 006 — Elastic SG egress + populate postgres reserved_names

## Problem

Two gaps surfaced consecutively during the elastic D.7 smoke walk on mod 005:

### Gap A — Non-ALB SGs in `main.tf.j2` deny all egress

`docex release stage` against `test_projects/elastic` provisioned ALB, RDS (after the gap-B rename — see below), ECS task definitions, and ECS services successfully. Then the post-apply migration step (a one-off ECS task definition running `migrate.sh`) failed before the container could start:

```
ResourceInitializationError: unable to retrieve secrets from ssm:
  context deadline exceeded
```

Root cause: `src/docex/emit/templates/main.tf.j2:50-83` emits per-network `aws_security_group` blocks with no `egress { ... }` clause. Terraform's `aws_security_group` resource, when no egress block is specified, **denies all egress** — overriding AWS's default "allow all egress" on the underlying SG. Only the ALB SG (lines 102-107) has explicit egress. Fargate tasks attached to `internal` / `web` therefore have no outbound network and can't reach SSM, ECR, or any other AWS service endpoint. Migration tasks fail at startup; main service tasks would too.

The doctrine in `networks.md` § Implementation by Name doesn't say egress must be denied; the denial is an unintended side effect of how Terraform models `aws_security_group`. The AWS-side default for a fresh SG is "allow all egress, deny all ingress", and the doctrine's intent (ingress-only restrictions per network role, with no further egress constraint) is more closely modeled by `allow all egress`.

### Gap B — `postgres.reserved_names` doesn't include `db`

`docex_smoke_elastic`'s backing service was named `db`. Compile succeeded. Then `tofu apply` of the env-tier `main.tf` rejected RDS creation with:

```
InvalidParameterValue: DBName db cannot be used.
It is a reserved word for this engine
```

The doctrine in `transfer_tables.md § Field reference` says compile-time `reserved_names` validation should catch engine-reserved identifier collisions:

> Names the engine reserves and won't accept as identifiers — e.g. postgres reserves SQL keywords like `select` and `database`. Compile-time validation matches the backing-service name against this list (case-insensitive) so the operator hears about a collision at `docex compile` time instead of at `tofu apply`.

`tables/roles/relational_db.yml` does carry a populated `reserved_names` list (40+ SQL keywords plus a handful of admin names) but `db` isn't in it. AWS rejects `db` as a postgres DBName even though it's not in the SQL standard's reserved-words list — it's an RDS-specific reservation. The doctrine intent (compile-time, not apply-time, failure on reserved names) holds; the list is just incomplete.

The smoke-test walk worked around gap B by renaming the service `db → appdb` in `infra.yml`. Gap A is the immediate blocker on D.7.

## Design

### Fix A — emit allow-all egress on every project-emitted SG

In `src/docex/emit/templates/main.tf.j2`, every `aws_security_group` resource the compiler emits needs an explicit `egress { from_port=0, to_port=0, protocol="-1", cidr_blocks=["0.0.0.0/0"] }` block — matching the AWS-side default and the existing ALB SG's behavior. This applies to:

- The per-network SGs in the `{% for short in networks_sorted %}` loop (lines 50-83).
- The ALB SG already has the right egress (lines 102-107). No change needed there.

Egress is uniform: all non-ALB SGs get the same allow-all block. The doctrine doesn't yet model egress restriction by network — that's a future refinement (defense-in-depth, listed under `infrastructure.md § Deferred` rule 6). Until then, "allow all egress" matches AWS defaults and is the right floor.

### Fix B — extend `postgres.reserved_names` to include RDS-reserved DBName values

In `tables/roles/relational_db.yml`, append to the `reserved_names` block the additional RDS-reserved DBName values the AWS docs and AWS API rejections call out:

- `db`
- `template0`
- `template1`

(`postgres` is already in the list. `rdsadmin` is already there.)

Other AWS-rejected DBNames for postgres engine versions seen in the wild but not in any clean published list: leave them off pending a real example. Smoke walks will surface them.

This is data-only — no code change. The existing `reserved_names` validation logic in the compiler fires automatically against the expanded list.

### Doctrine touchpoints

- `doctrine/infrastructure/specifics/networks.md` — add a brief note under § Implementation by Name that every project-emitted SG carries allow-all egress, with a forward reference to `infrastructure.md § Deferred` for future egress-restriction work.
- `doctrine/infrastructure/specifics/transfer_tables.md` — no schema change. The `reserved_names` block already exists.
- No `cicl.md` or `infrastructure.md` change.

## Five-artifact alignment

| Artifact | Change |
| -------- | ------ |
| `doctrine/.../*.md` | `networks.md` — sentence on SG egress (Fix A). |
| `docex/plans/core/*.md` | No change. |
| `tables/roles/*.yml` | `relational_db.yml` — append `db`, `template0`, `template1` to postgres `reserved_names` (Fix B). |
| `src/docex/**` | `src/docex/emit/templates/main.tf.j2` — add `egress {…}` to the per-network SG resource (Fix A). |
| `tests/**` | Snapshot/integration test: assert every emitted SG in the env `main.tf` contains an `egress` block. Unit test: a transfer table whose backing service name matches an engine's reserved_names fails compile (verify with `db` against the new list). |

## Validation

1. `python3 -m pytest tests/` — green.
2. Recompile `test_projects/elastic`. Inspect any env `main.tf`:
   - `grep -c "egress {" infra/output/stage/main.tf` returns 3 (web SG, internal SG, ALB SG).
3. Author a throwaway `infra.yml` with a backing service named `db`. `./bin/docex compile` exits non-zero with a clear `reserved_names`-related error pointing at the service name.
4. Resume the D.7 walk: `docex release stage` should now drive migration to completion and the stage health endpoint should serve.

## Decisions captured

1. **Allow-all egress, not constrained.** Doctrine doesn't yet model egress policy per network. AWS default matches operator intent for now. Constraining egress is deferred per `infrastructure.md § Deferred` rule 6.
2. **Add only `db`, `template0`, `template1` to postgres reserved_names.** These are the well-known RDS-rejected DBName values beyond what's already in the list. Expanding speculatively (every Postgres extension table name, etc.) risks false-positives. Real walks surface real cases.
3. **No doctrine schema changes.** Both fixes are existing-mechanism enhancements: an egress block (always supported by the SG resource shape) and a longer list (already supported by the loader). Mod 006 is small on purpose — its scope is "wire up what mod 005 left exposed."

## Open questions

(None. Both fixes are unambiguous and confirmed against the failing apply.)
