# Campaign: make `reverse_proxy: ec2_traefik_*` actually work

## Origin

An operator tried `reverse_proxy: ec2_traefik` for the first time on a real
project and it didn't work. mod 062 fixed the first bug (compile-time HCL
crash). To prove the fix, we ran the **first-ever end-to-end elastic smoke walk
with `reverse_proxy: ec2_traefik_eip`** against real AWS (account
256071447730, us-east-1). That walk revealed the `ec2_traefik` path has **three
independent bugs**; mod 062 fixed only the first. This campaign fixes the
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

> **Sequential discovery.** Bugs 2 → 4 are all in the user_data and were masked
> one behind another: each fix let the script run further and hit the next.
> mod 065's re-walk is the point where user_data should finally complete.

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

## Peripheral gaps found during the walk (fold into the campaign)

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
