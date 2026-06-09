# Mod 048 — Elastic Walk Polish (Bug Bundle)

Patch mod bundling three runtime bugs surfaced during the post-1.0.2 elastic-foundation smoke walk on the test project. Like mod 047, none were caught by unit tests — they only surfaced once `projinfra up production` + `release stage` + `release prod` actually ran against real AWS. Like mod 047, the fixes already landed in source during the walk because each bug blocked progress; the cut + re-walk-each-time cost was prohibitive.

The walk against docex 1.0.2 ran through D.13 teardown after the fixes were in place. The bug-finding cadence of two walks (fixed → mod 047; elastic → mod 048) is the doctrine working as intended: the smoke walks are *for* finding the integration-class bugs that nothing else catches.

## Bug 5 — `projinfra up development` stubbed on elastic projects

**Symptom:** `./bin/docex projinfra up development` on the elastic project printed `projinfra up development (stub): real behavior lands in mods 037-039 (elastic). Returning success.` and exited 0 without standing up the project-tier compose (the four `-web` networks + the per-project traefik). The subsequent `envinfra up dev` then failed: `network docex-smoke-elastic-dev-web declared as external, but could not be found`.

**Root cause:** Mod 034 wired stubs for `projinfra` while real behavior landed in 036 (fixed) and 037–039 (elastic prod side). The elastic-foundation **dev-side** path never landed because dev-side is mechanically identical to fixed (same compose, same per-project traefik) — but the stub for `(foundation=elastic, direction=up, side=development)` was never removed, so it short-circuits to the success message.

**Fix:** Treat the dev side of elastic projects as a fixed-style projinfra. In `src/docex/pipeline/projinfra.py` (or wherever the dispatcher lives), the `(elastic, development)` case should call into the same code path as `(fixed, development)` — `emit_project_compose` already emits the same shape for both foundations on the development side (per [`projinfra/overview.md § Why all four web networks live on every side`](../../../../doctrine/infrastructure/specifics/projinfra/overview.md#why-all-four--web-networks-live-on-every-side)). The dispatcher's stub for elastic-dev-side is the only thing in the way.

Smoke-walker workaround (already in walk history): bring up the dev-side compose by hand with `docker compose --project-directory . -f infra/output/project/development/docker-compose.yml up -d`.

## Bug 6 — `migrate.py` uses pre-mod-041/040 lookups

**Symptom:** `docex release stage` succeeded at `tofu apply` (25 resources created) but the subsequent migration RunTask aborted with `error: no VPC tagged project='docex_smoke_elastic'; was the project-tier VPC provisioned?`.

**Root cause:** Two stale lookups in `src/docex/orchestrate/migrate.py`:

1. `_lookup_project_vpc` filters `describe_vpcs` by `tag:project=<project>`. That tag scheme existed pre-mod-041, when each project had its own VPC. Mod 041 switched every elastic project onto a shared **master VPC** tagged `Name=docex-master-vpc, managed_by=docex-preinfra`. The lookup never finds anything against the new scheme.
2. `sg_name = f"{project}_{env}_internal"` — pre-mod-040 underscore form. Mod 040 hyphenated env-tier SG names to match the doctrine's data-plane-naming-uses-hyphens rule. The lookup would 0-match even if (1) were fixed.

**Fix:**

- Rename `_lookup_project_vpc` → `_lookup_master_vpc`. Filter by `Name=docex-master-vpc, managed_by=docex-preinfra`. Add the same fake-shim on `tests/conftest.py::FakeAWSClient` (`lookup_master_vpc()`).
- Compute `sg_name` via `f"{project_dns}-{env}-internal"` where `project_dns = project.replace("_", "-").lower()`. Matches what mod 040's `main.tf.j2` emit produces.

Both changes are in `src/docex/orchestrate/migrate.py`. The full unit suite (445 tests) passes against the patched code — no test regressions to triage.

## Bug 7 — Bare-project A-record missing on prod env-tier ALB emit

**Symptom:** After `docex release prod` succeeded and ECS reached steady state, the canonical-host (`web.prod.<project>.<apex>`) and bare-env (`prod.<project>.<apex>`) routes returned 200 with version, but the **bare-project** host (`<project>.<apex>`) — which `cicl.md § Domain` says routes to prod's `domain_default_service` for user-URL ergonomics — returned NXDOMAIN. No A-record existed in Route53 for the bare-project host.

**Root cause:** `src/docex/emit/templates/main.tf.j2` env-tier emit (gated on `reverse_proxy == "alb"`) emits only two A-records per env: `<env>.<project>.<apex>` and `*.<env>.<project>.<apex>`. The doctrine ([`elastic_route53_zone.md`](../../../../doctrine/infrastructure/specifics/projinfra/elastic_route53_zone.md)) commits to **five** records on prod:

- `<project>.<apex_domain>` (bare project — **missing**)
- `prod.<project>.<apex_domain>` ✓
- `*.prod.<project>.<apex_domain>` ✓
- `stage.<project>.<apex_domain>` ✓ (in stage env's emit)
- `*.stage.<project>.<apex_domain>` ✓ (in stage env's emit)

The bare-project record is special: it only exists on prod (since the bare-project routes to prod's `domain_default_service`). The current template doesn't emit it at all.

Listener rules are correctly emitted: the prod-env web service's listener rule has `host_header values = ["web.prod.<project>.<apex>", "prod.<project>.<apex>", "<project>.<apex>"]` — so the ALB will route the bare-project host correctly **if** DNS gets the traffic there. The gap is purely on the Route53 side.

**Fix:** Extend `main.tf.j2`'s env-tier ALB emit to also emit an `aws_route53_record.bare_project` when `env == "prod"` and `bare_project_subdomain` is non-empty. Pseudo-shape:

```hcl
{% if reverse_proxy == "alb" and env == "prod" %}
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

The template already has `bare_project_subdomain` in its context (rendered via `compiled.bare_project_subdomain`), so no `tpl.render` arg change is needed.

Smoke-walker workaround (already in walk history): create the bare-project A-record by hand via `aws route53 change-resource-record-sets`.

## What lands in this mod

| Change | File(s) |
| ------ | ------- |
| `projinfra up development` stops stubbing on elastic; dispatches to fixed-style emit | `src/docex/pipeline/projinfra.py` |
| `migrate.py` VPC lookup updated; SG name hyphenated | `src/docex/orchestrate/migrate.py` |
| `FakeAWSClient` renamed shim | `tests/conftest.py` |
| Bare-project A-record on prod ALB emit | `src/docex/emit/templates/main.tf.j2` |
| Mod-048 design + impl docs (this folder) | `plans/modifications/048_elastic_walk_polish/` |
| CHANGELOG entry + version bump (1.0.2 → 1.0.3) | `CHANGELOG.md`, `pyproject.toml`, `src/docex/__init__.py` |

## Out of scope

- **Project traefik AWS-cred propagation.** Still open from mod 047. The smoke project worked around with `httpx.Client(verify=False)` on the fixed side; on the elastic side the ALB serves real ACM certs so the issue didn't surface. The doctrine gap (dev-side traefik on elastic projects ALSO needs the creds) remains for a future mod.
- **ECS task-def `logConfiguration`.** Worker container has no log group; checking ping processing through CloudWatch isn't possible. Noted in [`release_flow.md § Common failure modes`](../../core/release_flow.md#common-failure-modes); not blocking the walk.
- **`docex projinfra down development` for elastic.** Symmetric stub to bug 5; same fix applies.

## Cut shape

Patch cut: docex 1.0.3. Mod 047 was the fixed-side walk's bug bundle; mod 048 is the elastic side's. Smoke walks on both foundations against 1.0.3 should now run clean from D.1 through D.13 (the rebuild-source-mid-walk pattern won't be needed if 1.0.3 is the starting pin).
