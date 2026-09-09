# Mod 028 — Robust elastic teardown

## Problem

The elastic smoke-project `teardown.sh` already disables RDS `deletion_protection` before running `tofu destroy` (its step 1). But during the 0.11.0 PRE_CUT_CHECKLIST walk, `verify_clean.sh` still found both RDS instances `available` (not even `deleting`) after teardown ran. Manual cleanup with `aws rds delete-db-instance --skip-final-snapshot` worked instantly.

The real blocker isn't deletion_protection — it's `skip_final_snapshot`. The doctrine's postgres engine on elastic sets:

```yaml
# tables/roles/relational_db.yml — postgres.defaults.elastic
deletion_protection: true
backup_retention_period: 7
```

…and leaves `skip_final_snapshot` at the terraform-aws-provider default, which is **false**. When `tofu destroy` reaches `aws_db_instance.appdb`, the AWS API demands a `final_snapshot_identifier`; none is set; the delete is rejected. Tofu then continues with the rest of the destroy graph, exits 0 with the RDS still alive, and the smoke-project teardown declares "complete" — leaving the RDS, its ENIs, and the VPC orphaned.

This is the **right** doctrine default. Real prod projects want a final snapshot before destruction; flipping it to true in the transfer table would silently turn off a safety net every prod project relies on.

The fix is at the smoke-project level: teardown.sh needs to bypass tofu for RDS (using AWS API directly with `--skip-final-snapshot`), then let tofu destroy reconcile state for everything else.

## Scope

In scope:

1. **`test_projects/elastic/teardown.sh`**: between the deletion_protection-disable step and the `tofu destroy` loop, add a step that:
   - Issues `aws rds delete-db-instance --skip-final-snapshot --delete-automated-backups` for each project RDS.
   - Polls until each instance is fully gone (status `deleted`, i.e. describe-db-instances returns empty).
   - Only then proceeds to the existing `tofu destroy` loop, which will reconcile state (RDS gone from AWS → tofu removes from state) and continue to the project tier without hitting the ENI-detach race.
2. **`docex/plans/core/test_projects.md`**: add a paragraph noting this pattern — smoke-project teardowns bypass tofu for RDS specifically because the doctrine's prod-safe `skip_final_snapshot=false` default would otherwise block destroy. The doctrine default stays correct; smoke-project teardown overrides at retirement time.
3. **`test_projects/elastic/CHANGELOG.md`**: project-level entry bumping to `0.0.7`.
4. **`test_projects/elastic/project.yml`**: bump `0.0.6` → `0.0.7`.
5. **Inner repo commit + tag move** per `test_projects.md § Commit cadence`.

Out of scope:

- The fixed smoke-project teardown. It uses docker-compose with named volumes; no RDS, no AWS API surface. Unaffected.
- The transfer table default for `skip_final_snapshot`. Stays at provider-default `false` for prod safety.
- A docex code change. None needed.
- Cutting a new docex version. The change is at the smoke-project layer; docex stays at `0.11.0`.

## Design

### `teardown.sh` change

The existing structure:

```
1. Disable RDS deletion_protection (poll until landed)
2. Purge ECR
3. tofu destroy per layer (prod, stage, project)
4. SSM cleanup
5. State backend cleanup
6. Compiled output cleanup
```

New step 2 (renumbering the others):

```
1. Disable RDS deletion_protection (existing)
2. Direct-delete RDS via AWS API (new)
3. Purge ECR (was 2)
4. tofu destroy per layer (was 3)
...
```

Concretely, the new step:

```bash
# -- 2. Direct-delete RDS instances ------------------------------------
# The doctrine's postgres engine sets `deletion_protection: true` on
# elastic (for prod safety) but leaves `skip_final_snapshot` at the
# terraform-aws-provider default (false). Step 1 disables deletion
# protection but tofu destroy still asks AWS for a final snapshot
# identifier when destroying aws_db_instance — none is set; AWS
# rejects the delete; tofu silently moves on. The downstream
# project-tier destroy then trips on RDS-managed ENIs that haven't
# released.
#
# Smoke projects always retire — bypass tofu for RDS using the AWS
# API directly with --skip-final-snapshot. Once each RDS is fully
# gone, the subsequent tofu destroy reconciles state (resource
# absent from AWS → removed from state) and proceeds cleanly.
if [[ "${#project_dbs[@]}" -gt 0 ]]; then
  echo "-- direct-delete RDS instances (--skip-final-snapshot)"
  for db in "${project_dbs[@]}"; do
    echo "   RDS: $db (deleting)"
    aws rds delete-db-instance \
      --db-instance-identifier "$db" \
      --skip-final-snapshot \
      --delete-automated-backups >/dev/null 2>&1 || true
  done

  echo "   waiting for RDS instances to fully delete..."
  for db in "${project_dbs[@]}"; do
    # RDS deletion takes a few minutes. Poll for up to ~10 minutes.
    for attempt in $(seq 1 60); do
      status=$(aws rds describe-db-instances \
                 --db-instance-identifier "$db" \
                 --query "DBInstances[0].DBInstanceStatus" \
                 --output text 2>&1)
      # describe returns DBInstanceNotFound once gone.
      if echo "$status" | grep -q "DBInstanceNotFound"; then
        echo "   RDS: $db gone"
        break
      fi
      sleep 10
    done
  done
fi
```

`project_dbs` is already populated by step 1's `aws rds describe-db-instances ... | DBInstanceIdentifier` loop. Reuse it.

### Doctrine docs note

Add a short subsection to `docex/plans/core/test_projects.md` (right after § Resource cleanup discipline) titled "Smoke-project safety overrides", noting:

- Doctrine RDS defaults (`deletion_protection: true`, implicit `skip_final_snapshot: false`) are correct for real projects.
- Smoke projects always retire to clean state; teardown.sh bypasses these defaults using direct AWS API calls with `--skip-final-snapshot` etc.
- This pattern lives in `test_projects/<foundation>/teardown.sh` rather than in the transfer table because the override is specifically about "this project is being retired" semantics, not "this project doesn't need snapshots."

### Commit cadence

Per `test_projects.md § Commit cadence`:

1. Inner-repo commit in `test_projects/elastic/.git`: message `"Bump 0.0.7: teardown direct-deletes RDS to bypass skip_final_snapshot"`.
2. Force-move `v0.0.7` tag at the new inner HEAD.
3. Outer-repo commit (mod 028) wraps the modifications/028_*/ docs, the doctrine doc edit, and the test-project snapshot.

## Five-artifact alignment

| Artifact | Change |
| -------- | ------ |
| `doctrine/.../*.md` | None. The transfer table default stays prod-safe. Operator-side docs unchanged. |
| `docex/plans/core/*.md` | `test_projects.md` gets a "Smoke-project safety overrides" paragraph. |
| `tables/roles/*.yml` | None. |
| `src/docex/**` | None. |
| `tests/**` | None — teardown.sh is operator-driven, no unit-test surface. The next elastic smoke walk verifies behaviorally. |

## Risk and rollback

- **Risk:** if `aws rds delete-db-instance` fails (e.g. transient AWS error), the script logs nothing and continues. The subsequent tofu destroy would then re-attempt destroy via tofu — and fail silently for the same reason it did before. Net result: same as before the mod, not worse.
- **Recovery:** if a future smoke walk hits this, manual cleanup via `aws rds delete-db-instance --skip-final-snapshot` works (as I confirmed during the 0.11.0 walk).
- **Rollback:** revert. Teardown goes back to its 0.11.0 form.

## What this mod does NOT do

- Does not change the transfer table.
- Does not change docex source code.
- Does not bump docex version.
- Does not change the fixed smoke project.
- Does not add unit tests (no docex code surface changed).
