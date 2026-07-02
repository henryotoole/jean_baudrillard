# Mod 070 — ec2_traefik routing via the traefik ECS provider (Path B)

## Problem (campaign bug 6)

`reverse_proxy: ec2_traefik_*` boots and serves (mods 062–067) but
returns **502** for every backend: the EC2-traefik instance lives in the
master VPC but *outside* the ECS mesh, and ECS Service Connect resolution
is mesh-internal (per-task Envoy). The Cloud Map private zone carries no
per-service A-records, so the instance cannot resolve
`<discoveryName>.<namespace>` at all. `ec2_traefik.md § Routing
Discovery`'s DNS premise was simply wrong.

## Decision (approved)

**Path B — the traefik ECS provider.** Traefik's first-party
`providers.ecs` polls the ECS/EC2 control plane for the project's stage
and prod clusters, reads each `RUNNING` Fargate task's ENI private IP
directly, and builds routers/services from container `dockerLabels`.
This is the elastic analog of the fixed-foundation project traefik's
docker provider: routing intent lives on the workloads; release never
touches traefik. Chosen over Path A (Cloud Map Service Discovery
A-records) because it gives real load-balancing + task-health awareness,
removes an entire release-time subsystem (the SSM push + on-instance sync
timer, mod 064), and removes the cross-artifact name-coupling seam. Cost:
a scoped, read-only ECS/EC2 IAM grant on the instance.

The doctrine is already rewritten (committed):
`ec2_traefik.md` (Routing Discovery / Config Delivery / IAM / Failure
Modes / Lifecycle / Projinfra-vs-Envinfra), `shape.md` + `transfer_tables.md`
(the wrong out-of-mesh-DNS claim corrected), `release.md` (label-based
routing). This mod aligns code to that doctrine.

## What changes in code

1. **user_data static config** (`ec2_traefik_user_data.sh.j2`): swap the
   `providers.file` block for a `providers.ecs` block (region + the two
   cluster names + `exposedByDefault: false` + `refreshSeconds: 15`).
   **Delete** the `dynamic.yml` stub, the `docex-traefik-config-sync`
   script, its `.service`/`.timer` units, the synchronous sync run, and
   traefik.service's `After=docex-traefik-config.service`. Everything
   else (EBS attach, IMDSv2, CloudWatch agent, PIP DNS update, traefik
   install) is unchanged.

2. **Task-definition labels** (`emit/hcl.py::render_task_definition`):
   on the `ec2_traefik_*` path, emit `traefik.*` `dockerLabels` on each
   web-network core service's container definition — `traefik.enable`,
   the router rule (from `svc.web_hosts`), entrypoint `websecure`,
   `tls.certresolver=doctrine`, the router→service binding, and the
   service loadbalancer port. Router/service key is `<svc.name>-<env>`
   (env-encoded so the shared instance's stage+prod views don't collide).
   No labels on the `alb` path.

3. **IAM** (`project.tf.j2`): drop the `ssm:GetParameter` config-fetch
   statement; add a read-only ECS/EC2 discovery grant (see § IAM below).

4. **Remove the SSM routing param** (`project.tf.j2`
   `aws_ssm_parameter.project_traefik_config`) and the **release-side
   push** (`pipeline/release.py`, the `ec2_traefik_*` block) and the
   now-dead `emit/traefik.py` (`render_traefik_dynamic_config`).

5. **Tests**: add label-emit + user_data + IAM tests; remove/replace the
   `emit/traefik.py` and SSM-push tests; **fix the stale mod-062 test**
   (`test_mod062_traefik_user_data_hcl_escaped_eip` asserts the pre-mod-065
   `$(curl -sf http://169.254.169.254` form — mod 065 moved to IMDSv2
   tokens and the assertion was never updated; it fails on clean `main`).

## IAM design

The traefik ECS provider needs: `ecs:ListClusters`, `ecs:DescribeClusters`,
`ecs:ListTasks`, `ecs:DescribeTasks`, `ecs:DescribeContainerInstances`,
`ecs:DescribeTaskDefinition`, and (for the SDK's task→ENI path)
`ec2:DescribeInstances`. All read-only. Two statements:

- **Cluster-scoped**: `ListTasks` / `DescribeTasks` /
  `DescribeContainerInstances` / `DescribeServices`, conditioned with
  `ArnEquals ecs:cluster` on the project's two cluster ARNs
  (`arn:aws:ecs:<region>:<acct>:cluster/<project>-stage` and
  `.../<project>-prod`).
- **Unscopeable read-only** (`*`): `ListClusters`, `DescribeClusters`,
  `DescribeTaskDefinition`, `ec2:DescribeInstances` — AWS does not permit
  resource-level scoping on these; granted read-only at `*`.

This matches the IAM table already written into `ec2_traefik.md`.

## Non-goals

- The LE cert (bug 7) is **not** in this mod — it's diagnosed after bug 6
  clears (mod 071, contingent).
- No change to Service Connect (it stays for intra-mesh comms; unaffected).
- No change to the ALB path beyond confirming labels are ec2_traefik-only.
- fixed foundation untouched.

## Risks / watch-items for the walk

- **Router/service naming & binding**: confirm the traefik ECS provider
  binds router `<svc>-<env>` to service `<svc>-<env>` — emit the explicit
  `traefik.http.routers.<key>.service=<key>` label rather than relying on
  auto-binding.
- **Region resolution**: render `region` into the provider block at
  compile time (it's already a Jinja context var in the project template);
  do not rely on IMDS auto-detect.
- **Cross-cluster discovery**: `autoDiscoverClusters: false` + explicit
  `clusters: [stage, prod]` so the provider only looks at this project.
- **Label HCL-safety**: labels go inside `jsonencode([...])`; host rules
  contain backticks + `||` but no `${`, so no HCL-interpolation hazard.
