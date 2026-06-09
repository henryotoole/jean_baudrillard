# Implementation — Mod 048 — Elastic Walk Polish

## Context

Bugs surfaced during the post-1.0.2 elastic-foundation smoke walk on the test project. Fixes for bugs 6 and 7 landed in source mid-walk so the walk could finish (same pattern as mod 047). Bug 5 and the project-side teardown bug (path layout) are handled by this mod's code changes; the test project's `teardown.sh` already got its fix in the same walk.

This document records where each fix landed, so a future reader can find the diff site directly.

## Changes shipped

### 1. `projinfra up development` no longer stubs on elastic (bug 5)

**File:** `src/docex/pipeline/projinfra.py`

The dispatcher's `(foundation=elastic, direction=up, side=development)` branch was a stub returning "real behavior lands in mods 037-039 (elastic)". The dev-side of an elastic project is mechanically identical to a fixed dev side (per [`projinfra/overview.md § Why all four web networks live on every side`](../../../../doctrine/infrastructure/specifics/projinfra/overview.md#why-all-four--web-networks-live-on-every-side)) — both emit the same `infra/output/project/development/docker-compose.yml`. Route the elastic-dev-side case to the same compose-up path the fixed-dev-side uses.

> **TODO (mid-fix-window):** confirm the dispatcher file path before editing — the actual layout in `src/docex/pipeline/` may be `projinfra.py` or it may be split per `(foundation, side)`. Adapt the fix accordingly. Either way, the goal is "elastic-dev-side does what fixed-dev-side does."

### 2. Migration RunTask lookups (bug 6)

**File:** `src/docex/orchestrate/migrate.py` (and `tests/conftest.py`)

Already landed in the smoke-walk fix window. Concretely:

- `_lookup_project_vpc(aws, project)` → `_lookup_master_vpc(aws)`. Filter changed from `tag:project=<name>` to `tag:Name=docex-master-vpc, tag:managed_by=docex-preinfra`. Mod 041 had switched every elastic project onto the shared master VPC; the migrate lookup was the last per-project-VPC reference.
- `sg_name` formed as `f"{project_dns}-{env}-internal"` where `project_dns = project.replace("_", "-").lower()`. Matches mod 040's hyphenated env-tier SG names.
- `tests/conftest.py::FakeAWSClient.lookup_project_vpc` → `.lookup_master_vpc()`. Tests still pass (445/445 green after the rename).

### 3. Bare-project A-record on prod ALB emit (bug 7)

**File:** `src/docex/emit/templates/main.tf.j2`

Already partially specified in mod 048's overview. Concretely:

Add a third `aws_route53_record` resource inside the `{% if reverse_proxy == "alb" %}` block, gated on `env == "prod"`:

```hcl
{% if env == "prod" %}
# Bare-project A-record: <project>.<apex_domain> -> project ALB. Per
# `cicl.md § Domain`, the bare-project host routes to prod's
# domain_default_service for user-URL ergonomics. Only emitted on prod
# since the bare-project resolves to prod's `domain_default_service`
# regardless of which env declared the field.
resource "aws_route53_record" "bare_project" {
  zone_id = data.terraform_remote_state.project.outputs.zone_id
  name    = "{{ bare_project_subdomain }}"
  type    = "A"
  alias {
    name                   = data.terraform_remote_state.project.outputs.alb_dns_name
    zone_id                = data.terraform_remote_state.project.outputs.alb_zone_id
    evaluate_target_health = false
  }
}
{% endif %}
```

`bare_project_subdomain` is already in the template context via `compiled.bare_project_subdomain` — no `tpl.render(...)` arg change needed.

### 4. Test-project teardown.sh updated for mod-035 path layout (project-side, already landed)

**File:** `test_projects/elastic/teardown.sh`

Tear-down loop was looking at `infra/output/$layer/main.tf` (pre-mod-035 single-side path). Post-mod-035 the project HCL is at `infra/output/project/production/main.tf`. The loop was rewritten with an explicit per-layer path map. Lands as part of `docex_smoke_elastic v0.0.5` (the post-walk version bump).

This is project-side, not docex code, but worth flagging here so future test-project incepters know to walk the new layout. The fixed test project doesn't have this bug because its teardown.sh doesn't iterate tofu layers (fixed teardown is compose-only).

## Tests

No new tests in this mod. The bugs are runtime-class — RunTask against real AWS, Route53 record creation, dispatcher conditional branches. Unit tests catch shape, not "does the deploy pipeline actually succeed against AWS." The smoke walk is the validation.

Existing unit suite (445 tests) re-run against the bug-6 fix: 445/445 pass. Bug 5 and 7 require their own dispatcher / template fixes to also re-run; will confirm post-cut.

## Verification

End-to-end via the elastic smoke walk against docex 1.0.2 + in-source patches: D.1 (projinfra two-phase) → D.4 (envinfra up dev) → D.5 (test) → D.8 (check + containerize) → D.9 (release stage first-time) → D.10 (stagetest) → D.11 (release prod first-time, all three hosts return 200 with version 0.0.3, POST /pings returns 201, ECS service steady) → D.12 (rollback 0.0.4 → 0.0.3 successful, dry-run successful) → D.13 (teardown + verify_clean.sh green after manual cleanup of project-tier resources).

The "manual cleanup" caveat at D.13 is the project-side teardown.sh bug — the loop skipped the project tier because the layer path didn't match the new mod-035 layout. Fix landed in the project's teardown.sh (separate from this docex mod) but mentioned here as the source of the verify_clean failure.

## Walker notes for the next walker

- The smoke walker also needs to create the NS delegation record in the parent zone manually between projinfra phase 1 and phase 2 — that's already in PRE_CUT_CHECKLIST § A.4.2 and D.3. Not a bug.
- The smoke walker has to clean up the bare-project A-record manually before D.13 if they walk against pre-fix docex; against this mod's fix, tofu owns the record and destroy handles it.
- The smoke walker's verify_clean.sh teardown path requires the project-tier `tofu destroy` to land before the state bucket is destroyed in step 6 of teardown. Bug 8 (project-side) violated this order because the project-tier destroy was being silently skipped — making step 6 fire first and leaving project-tier resources orphaned. Fix in the project's teardown.sh handled both: the loop now walks project-tier, and step 6 runs after step 4 as before.

## Out of scope

- **Project traefik AWS-cred propagation.** Still open from mod 047. Future mod.
- **ECS task-def `logConfiguration`.** Open from `release_flow.md § Common failure modes`. Future mod.
- **`projinfra down development` for elastic.** Symmetric to bug 5 (down-side likely has the same stub). This mod fixes the up-side; the down-side fix is a one-liner — should land at the same time but if missed by the implementer, surface in the next walk.
