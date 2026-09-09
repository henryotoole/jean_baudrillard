# Mod 071 — ec2_traefik walk fixes (bugs 7 + 8)

The mod-070 real-AWS walk (1.5.0 candidate, elastic, `ec2_traefik_eip`)
proved **bug 6 is fixed**: once the ECS clusters resolved, traefik's ECS
provider discovered the Fargate task and routed — `GET /health` returned
`200 {"version":"0.0.10"}` through traefik. The walk then surfaced two
follow-on bugs, both diagnosed from the traefik CloudWatch logs.

## Bug 8 (new) — traefik builds zero routes at a first-release

**Symptom.** After `release stage`, every request got traefik's own
`404 page not found`; no router was built even though the stage web task
was RUNNING/HEALTHY.

**Root cause.** traefik log:
```
ERR Provider error, retrying ... error="failed to get ECS configuration:
listing tasks: ClusterNotFoundException: Cluster not found." providerName=ecs
```
The instance's static `providers.ecs` config lists **both**
`<project>-stage` and `<project>-prod` clusters (the single instance serves
both envs). traefik's ECS provider treats a `ListTasks` error on **any**
listed cluster as fatal for the *entire* refresh — so when only `stage`
has been released (prod cluster absent), it discards even the stage
cluster's discovered services and builds nothing. Confirmed by manually
creating an empty `<project>-prod` cluster: within one refresh, routing
returned 200.

**Fix (proposed — needs sign-off; touches the ALB path too).** Make the
two ECS clusters **project-tier** so the provider's explicit cluster list
always resolves (empty ECS clusters are free). This mirrors the ALB model
(project-tier proxy; env-tier attachments):

- **Emit** `aws_ecs_cluster.stage` + `aws_ecs_cluster.prod` at the project
  tier (`emit_hcl_project` / `project.tf.j2`), with project-tier outputs
  (`ecs_cluster_stage_arn`, `ecs_cluster_prod_arn`).
- **Env-tier** (`main.tf.j2`): drop `aws_ecs_cluster.cluster`; reference
  the env's cluster via
  `data.terraform_remote_state.project.outputs.ecs_cluster_<env>_arn`.
  The env-tier Service Connect namespace stays env-tier (unchanged).
- **First-release detector** (`pipeline/release.py::_release_elastic`):
  today it keys off `ecs_cluster_exists` — which is always true once
  clusters are project-tier. Switch to an env-scoped signal: the env
  cluster has **no services** (`ecs_list_services(cluster)` empty) ⇒
  first release. Add `AWSClient.ecs_list_services` (or `ecs_service_exists`).
- **Teardown**: clusters are destroyed at `projinfra down production` now,
  not `envinfra down <env>`. Confirm `teardown.sh` order (env destroy →
  project destroy) still ends clean; empty clusters destroy fine once
  services are gone.

This is uniform across both reverse_proxy paths (simpler than branching
compile/detector on `reverse_proxy`). The ALB path is functionally
unaffected — its walk pass will confirm.

**Doctrine impact.** The ECS cluster's tier moves env → project. Needs a
note in `shape.md` (the `core_service` / cluster shape rows) and/or a
projinfra doc, plus a line in `ec2_traefik.md` explaining *why* both
clusters must pre-exist (the provider's all-clusters-must-resolve
behavior). Operator sign-off on wording required before editing.

## Bug 7 — LE cert never issues (route53 DNS-01 "Missing Region")

**Symptom.** traefik served `TRAEFIK DEFAULT CERT`; `curl` without `-k`
failed the handshake even after routing worked.

**Root cause.** traefik log:
```
acme: error presenting token: route53: failed to determine hosted zone ID:
Route 53: ListHostedZonesByName, ... Invalid Configuration: Missing Region
```
traefik's LE **DNS-01 route53 provider** (lego) resolves the Route53 API
endpoint from `AWS_REGION`/`AWS_DEFAULT_REGION` in its environment. The
`traefik.service` systemd unit doesn't set it, and lego's endpoint
resolution does not fall back to IMDS region. (The ECS provider was
unaffected because docex renders `region:` directly into *its* config
block.)

**Fix (trivial, no doctrine change).** Add
`Environment=AWS_REGION=<region>` (rendered, e.g. `us-east-1`) to the
`[Service]` section of the `traefik.service` unit in
`ec2_traefik_user_data.sh.j2`. Optionally also `AWS_DEFAULT_REGION`. This
is a user_data implementation detail; `ec2_traefik.md` already states
DNS-01-via-route53 is the mechanism.

## Sequencing

Both fixes ride the 1.5.0 candidate. After they land: rebuild
`docex:1.5.0`, re-walk `ec2_traefik_eip` to a green end-to-end (routing +
real LE cert, stage), then the `alb` confirmation pass, then teardown +
`verify_clean`, then finalize the 1.5.0 cut.

## Status

- Bug 6: **fixed & verified on real AWS** (mod 070).
- Bug 8: diagnosed; fix approach pending operator sign-off (project-tier
  clusters).
- Bug 7: diagnosed; fix is a one-line user_data env var.
- Stage stack from the mod-070 walk: **torn down** after diagnosis.
