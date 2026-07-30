# Advance: make `reverse_proxy: ec2_traefik_*` actually work

> **Status correction (retrospective).** This advance **shipped as patch
> `1.4.3`**, not `1.5.0`. It was briefly planned as a minor (`1.5.0`) — hence the
> `1.5.0` references throughout the sections below — but was reclassified to a
> patch and cut as `1.4.3` (see `CHANGELOG.md`). There is **no `1.5.0` release**.
> The planning text below is left intact as a historical record; read every
> `1.5.0` in it as "the release that became `1.4.3`."

## Origin

An operator tried `reverse_proxy: ec2_traefik` for the first time on a real
project and it didn't work. mod 062 fixed the first bug (compile-time HCL
crash). To prove the fix, we ran the **first-ever end-to-end elastic smoke walk
with `reverse_proxy: ec2_traefik_eip`** against real AWS (account
256071447730, us-east-1). That walk revealed the `ec2_traefik` path has **three
independent bugs**; mod 062 fixed only the first. This advance fixes the
other two (and some peripheral gaps) and re-walks to green before 1.5.0 cuts.

The `alb` path is unaffected by all of this — it has been walked before and all
three bugs are confined to the `ec2_traefik_*` branch.

## The three bugs

| # | Bug | Where | Status |
| - | --- | ----- | ------ |
| 1 | HCL heredoc `${…}`/`%{…}` interpolation collides with the bash user_data → compile/`tofu` parse failure | `emit/hcl.py::emit_hcl_project` | **FIXED — mod 062** |
| 2 | user_data `apt-get install … awscli amazon-cloudwatch-agent` fails on Ubuntu 24.04 (noble) — neither package is in the apt repos — and `set -euo pipefail` aborts the whole script → traefik never installs/starts | `emit/templates/ec2_traefik_user_data.sh.j2` | mod 063 |
| 3 | docex never renders/pushes the traefik dynamic routing config; the SSM param `/<project>/ec2_traefik/config.yml` is created as a static empty stub by projinfra and never updated → traefik has zero routes even when running | `pipeline/release.py` (missing step) | mod 064 |
| 4 | user_data fetches EC2 metadata with raw token-less curls; the Ubuntu 24.04 AMI enforces IMDSv2 (`HttpTokens=required`) so they 401 → `set -e` aborts user_data (surfaced only after mod 063 got past the package install) | `emit/templates/ec2_traefik_user_data.sh.j2` | mod 065 |
| 5 | `ec2:AttachVolume` IAM grant conditions on `purpose=ec2_traefik_acme` for both the volume AND the instance ARN, but the instance isn't tagged with it → AttachVolume AccessDenied → user_data aborts at the EBS attach (never reached before mod 065) | `emit/templates/project.tf.j2` (instance tags) | mod 066 |

> **Sequential discovery.** Bugs 2 → 5 are all on the boot path and were masked
> one behind another: each fix let the script run further and hit the next
> (package install → IMDS → EBS attach → …). This is the signature of code that
> was never runtime-tested.

## Introspection blocker (why the walk is paused)

After mod 066 the next unverified boot steps are: EBS mkfs/mount, traefik
download+install, LE cert issuance (DNS-01 via Route53), the SSM config-sync
timer, and finally routing. Any of these could hide bug 6+. Confirming them
requires reading the instance's `/var/log/docex-user-data.log` — but in this AWS
account:

- **SSM Session Manager / `SendCommand` is denied** by an org SCP
  (`p-hakk9t13`), and the ec2_traefik IAM role lacks `AmazonSSMManagedInstanceCore`
  anyway.
- **The Nitro serial console (`get-console-output`) is not populating** — it
  returned empty repeatedly, so it can't be relied on for user_data logs.
- The traefik SG opens only 80/443, so no SSH / EC2 Instance Connect.

So each remaining bug can only be found by a blind fix → re-provision → observe
cycle (~10 min + real AWS spend each), with no visibility into *why* a boot
failed. That is inefficient and expensive. **Recommended before resuming:** give
the instance a debuggable path — e.g. temporarily relax the SCP to allow SSM +
attach `AmazonSSMManagedInstanceCore` to the traefik role, or open 22 + add an
SSH key / EC2 Instance Connect — so the remaining chain can be walked and fixed
in one pass instead of N blind cycles.

## Walk #3 results (mod 067 breadcrumb gave visibility)

mod 067 added a CloudWatch breadcrumb (user_data ships `/var/log/docex-user-data.log`
to the `/<project>/ec2_traefik` log group on EXIT — safe, uses IAM the role
already has, no SSH / no SCP change). It immediately unblocked diagnosis. The
breadcrumb log showed **user_data now runs to completion**: AWS CLI v2 ✓, CW
agent ✓, **EBS volume attached ✓ (mod 066)**, filesystem made+mounted ✓, all
systemd units enabled ✓. Confirmed live: traefik serves — `:80 → 301`
(HTTP→HTTPS redirect), `:443 → 404` (TLS up, no route matched pre-release).
After a full `release stage`, the SSM config carried the real routers (mod 064),
the router matched (`-k` curl got past 404), and ECS web was `RUNNING`/healthy.

**So mods 062–066 are now all VERIFIED on real AWS.** Two problems remain:

| # | Bug | Nature | Status |
| - | --- | ------ | ------ |
| 6 | **Backend unreachable (502).** traefik routes the request but can't resolve the backend `<discoveryName>.<namespace>`. The Cloud Map **DNS_PRIVATE** zone (`docex-smoke-elastic-stage.`, associated with the master VPC) contains **only NS+SOA — no service A-records.** ECS **Service Connect** resolution is mesh-internal (Envoy sidecar in each task); it does **not** publish VPC-DNS-resolvable records. The EC2-traefik instance is *outside* the mesh, so the name never resolves for it. `ec2_traefik.md § Routing Discovery`'s core assumption is wrong. | **Architectural** — needs a design change (register web services via ECS **Service Discovery** / Cloud Map DNS `service_registries` so the private zone gets A-records, *in addition to or instead of* Service Connect), a doctrine correction, and a compile/emit change. | open |
| 7 | **LE cert not issued.** traefik serves its `TRAEFIK DEFAULT CERT` for the domain (so `https://…` without `-k` fails the handshake → the `/health` poll saw 000). Whether this is just "needs more time / needs a router to exist first" or a real DNS-01 problem is **unconfirmed** — bug 6 (502) meant no successful request ever exercised the cert path fully. | Unconfirmed — re-diagnose after bug 6 is fixed. | open |

## Update — 2026-07-02: Path B chosen; mods 069–070 landed (code + tests green, walk pending)

Bug 6 resolved in **code** via **Path B — the traefik ECS provider**, not
the Service Discovery / Cloud Map A-records design floated below. Operator
weighed both and chose B: it removes the release-time SSM push + the
on-instance sync timer entirely (`release` never touches traefik — the
elastic analog of the fixed docker provider), gives real load-balancing +
task-health awareness, at the cost of a scoped read-only ECS/EC2 IAM grant.
The old `ec2_traefik.md` "no ECS provider" line was documentative, not
prophetic — removed and replaced with current-state docs.

- **Doctrine** (committed): `ec2_traefik.md` (Routing Discovery / Config
  Delivery / IAM / Failure Modes / Lifecycle / Projinfra-vs-Envinfra
  rewritten), `shape.md` + `transfer_tables.md` (wrong out-of-mesh-DNS
  claim corrected), `release.md` (label-based routing).
- **mod 070** (committed): `providers.ecs` in user_data; `traefik.*`
  `dockerLabels` on web-service task defs; ECS/EC2 discovery IAM; removed
  the SSM routing param + release push + `emit/traefik.py`; `_hcl_value`
  now quotes dotted object keys (found via `tofu validate`). Fixed the
  stale mod-062 test (IMDSv2 curl form).
- **mod 069** (committed, unrelated ALB fix bundled into this cut):
  naming-policy `overflow: hash_truncate` so ALB/target-group/SG `name`
  identifiers fit AWS's 32-char cap; full name preserved in the `Name` tag.
- **Tests**: 653 unit/non-integration + 65 offline compile (incl.
  ec2_traefik `tofu validate` on eip/pip) all green.

**Still pending — the real-AWS re-walk** (targets 1.5.0). Bug 6 is fixed in
code but **not yet verified end-to-end on AWS**. Bug 7 (LE cert) remains
open and is only diagnosable once bug 6 clears on a live walk (→ mod 071,
contingent). Operator authorized adding a temporary SSH ingress to the
traefik SG for hands-on debugging during the walk (revert before the cut).

### Bug 6 is the crux — and it's a doctrine design flaw

The EC2-traefik path's entire backend-resolution premise (`ec2_traefik.md §
Routing Discovery`: "resolved at runtime via the Cloud Map private DNS namespace
… `<discoveryName>.<namespace>`") does not hold for a client outside the ECS
mesh. Service Connect ≠ DNS. The likely fix: on the ec2_traefik path, emit an
`aws_service_discovery_service` (Cloud Map, A-record DnsConfig) per web service
and wire it via the ECS service's `service_registries`, so the private zone
carries real A-records the EC2 instance can resolve. This is a doctrine change
(operator sign-off required) + a compile change + another walk — a distinct
sub-advance, not a quick fix. **Paused here for operator design input.**

## Verified-so-far vs. unverified

- **Verified against real AWS:** mod 062 (projinfra applies the instance), mod
  064 (release pushes correct routers/services to SSM — inspected the param),
  the full release path (ECS/RDS/EFS/migrate) on ec2_traefik.
- **Code-confirmed + unit-tested, walk-unverified:** mods 063, 065, 066 (they
  fix definite bugs proven by console logs / code inspection, but the instance
  never reached a serving state to confirm end-to-end).

### Bug 1 evidence (fixed, confirmed on real AWS)

`docex projinfra up production` (ec2_traefik_eip) applied cleanly — 19 resources
including `aws_instance.project_traefik`. Before mod 062 this HCL wouldn't parse.
Confirmed the applied `project/production/main.tf` carries the escaped
`$${PROJECT}` form.

### Bug 2 evidence

EC2 console log (`aws ec2 get-console-output`) on the traefik instance:

```
E: Package 'awscli' has no installation candidate
E: Unable to locate package amazon-cloudwatch-agent
cloud-init: Failed to run module scripts_user ... failed
```

On Ubuntu 24.04 the `awscli` apt package was dropped (upstream wants snap or the
AWS CLI v2 bundle), and `amazon-cloudwatch-agent` was never in the Ubuntu repos
(it's an AWS-hosted `.deb`). The install line at
`ec2_traefik_user_data.sh.j2:16-17` therefore fails, and because line 9 sets
`set -euo pipefail`, user_data aborts before installing traefik. Result: nothing
listening on :80/:443 (direct `curl` to the EIP returned `000`).

### Bug 3 evidence

- `aws ssm get-parameter --name /docex_smoke_elastic/ec2_traefik/config.yml`
  returned the empty stub `http:\n  routers: {}\n  services: {}\n`.
- Source audit: the only writers of that SSM path are `project.tf.j2:448-452`
  (creates it empty at projinfra) and the user_data sync timer (reads it).
  **No code in `pipeline/`, `emit/`, or `orchestrate/` ever renders the routing
  rules and calls `ssm_put_parameter` for it.** `ec2_traefik.md § Config
  Delivery` documents this push as `release` behavior; it was never implemented.

## Fix designs (see per-mod overview.md)

- **mod 063** — rewrite the user_data package install so it works on the pinned
  Ubuntu 24.04 AMI: install AWS CLI v2 via the official bundle
  (`curl … awscli-exe-linux-<arch>.zip` → `./aws/install`), and either install
  the CloudWatch agent from its AWS-hosted `.deb` or make its absence non-fatal.
  Harden so an optional-tool failure can't abort the whole script. The script
  needs `awscli` (SSM config sync, EBS attach, route53 for pip) — that one is
  load-bearing and must succeed; the CloudWatch agent is best-effort.

- **mod 064** — implement the missing release-side config push. On
  `release <stage|prod>` for an `ec2_traefik_*` project, render the traefik
  dynamic config (`http.routers` + `http.services`) for **every web-network
  service across BOTH stage and prod** (the single instance serves both envs —
  see the two-router example in `ec2_traefik.md § Routing Discovery`), then
  `aws.ssm_put_parameter("/<project>/ec2_traefik/config.yml", yaml, overwrite=True)`.
  Seam: `pipeline/release.py::_release_elastic` (mirror `_push_secrets`).
  Reuse the per-service host-rule logic that the ALB path uses for
  `host_header` (`emit/hcl.py` listener-rule renderer, ~line 617, plus the
  `bare_project_subdomain` / `env_subdomain` domain fields on `CompiledEnv`) so
  the traefik `Host(...)` rules match the ALB rules exactly (including the
  bare-project / bare-env alternates for the `domain_default_service`). Backend
  URL per service: `http://<global_service_name>.<project_dns_label>-<env>:<port>`
  (Service Connect FQDN — `ec2_traefik.md § Routing Discovery`). Gate the whole
  step on `foundation == elastic and reverse_proxy in ec2_traefik_*`. Add a new
  emit helper (e.g. `emit/traefik.py::render_traefik_dynamic_config`) with unit
  tests, plus a release-level test asserting the push happens for ec2_traefik
  and does NOT happen for alb.

## Peripheral gaps found during the walk (fold into the advance)

- **P1 — stale checklist prose.** `docex/test_projects/PRE_CUT_CHECKLIST.md`
  § A.3.2 says the master VPC is tagged `Name=docex-master-vpc` /
  `managed_by=docex-preinfra`. The actual `docex preinfra production` probe
  (`pipeline/preinfra.py:64-66`) matches `managed_by=doctrine-operator` +
  `shape_name=master_network`. Update the checklist to match the code.
- **P2 — `verify_clean.sh` misses ec2_traefik resources.** The elastic
  `verify_clean.sh` checks VPC/ECS/RDS/ALB/ECR/SSM/Route53/ACM/IAM/state/DDB but
  NOT the standalone EC2 instance, EIP, or the ACME EBS volume. On an
  ec2_traefik project those can linger and bill. Add checks (and confirm
  `teardown.sh` destroys the ACME EBS volume, which has
  `delete_on_termination=false` and is designed to survive instance destroy).
  During walk #1, tofu destroy DID remove the volume/EIP/instance (manually
  confirmed), but the tooling should cover them.
- **P3 — SSM Session Manager can't introspect the instance.** An org SCP
  (`p-hakk9t13`) explicitly denies `ssm:SendCommand`, and the ec2_traefik IAM
  role lacks `AmazonSSMManagedInstanceCore` anyway. `ec2_traefik.md § Logging`
  claims journald is reachable via SSM Session Manager — not true in this
  environment. Debugging fell back to `aws ec2 get-console-output`. Consider
  documenting the console-output fallback; SCP is environment-specific and not a
  docex bug.

## Cut plan (task #9)

After 063 + 064 land with tests green: rebuild `docex:1.5.0`, re-run the elastic
ec2_traefik walk to green (routing through traefik with a real LE cert, both
stage and prod, then teardown + verify_clean), then finalize the 1.5.0 cut
(changelog roll incl. an honest mod-062/063/064 story, upgrade guide, tag
`v1.5.0`, image already built). 1.5.0 also carries the flow-tests doctrine
addition (already committed).

## Version note

VERSION and the three tracked artifacts were bumped to 1.5.0 during walk #1 prep
(uncommitted). Kept as the target. The formal cut (changelog roll, tag, commit)
happens only after the re-walk is green — the release is **held** per operator
decision.
