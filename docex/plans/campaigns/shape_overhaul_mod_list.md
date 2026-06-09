# Campaign: Doctrine Shape & Tier Realignment — Mod List

Persistent breakdown of the 16-mod campaign driven by [`../modifications/_campaign_doctrine_shape_and_tiers.md`](../modifications/_campaign_doctrine_shape_and_tiers.md). Written up-front so the chain survives context resets; each mod links to its modification folder once that mod's design pass starts.

## Driving briefs

- `engineer/tmp/tmp_shapechanger.md` — the shape change (centralized AWS egress, decentralized AWS ingress, fixed-side per-project traefik with HAProxy demux upstream).
- `engineer/tmp/change_infra_tier_coherency.md` — the tier and command-surface consolidation (`preinfra`/`projinfra`/`envinfra` replacing `bootstrap`/`up`/`down`).
- The doctrine itself, already updated in `jean_baudrillard/doctrine/`; this campaign brings `docex` back into alignment.

## Sequencing rationale

- **030–032** are foundational data shifts (naming, CICL surface, telemetry). Every later mod assumes hyphenated names, `apex_domain`, and `<svc>-otelcol`, so these land first.
- **033** (Fargate tier rounding) and **034** (command surface) are independent and could land anywhere; placed here so they're done before the new emission surfaces start using them.
- **035–036** introduce the new compiler output layout and fixed-side projinfra — cheap to validate, surfaces conceptual bugs early.
- **037–040** build the elastic projinfra stack from the outside in (zone+certs → ALB → ECR/IAM → env-tier consumes via remote state). Each mod stands alone as a release candidate.
- **041–044** are the long tail (master VPC switchover, preinfra checks, Service Connect refresh, EC2-traefik variant). Mostly independent of one another except 044 depends on 038.
- **045** is the integration verification — required by `docex_process.md` for any minor or major cut.

## The mods

| # | Mod | Scope |
|---|-----|-------|
| 030 | Naming policy unification | `docker`/`ecs` separators flip underscore→hyphen; remove `ecr_repo` policy; ECR repo emission becomes a hardcoded structural emit (`${project}/${service}` with verbatim segments). Largest test churn of the campaign — `global_service_name` flips form. |
| 031 | CICL surface refresh | `domain:`→`apex_domain:` rename + `${env_subdomain}` redefined + new `${apex_domain}`/`${bare_project_subdomain}` magic vars; service-name blacklist (`dev/test/stage/prod/www`); new `reverse_proxy:` field with elastic-only validation; delete `tables/roles/reverse_proxy.yml`; renumber validation rules; update per-web-service Traefik/ALB rule emit for new canonical-form + bare-env/bare-project routing. |
| 032 | Telemetry alignment | `<svc>_otelcol` → `<svc>-otelcol` everywhere (compose, ECS, log paths, error msgs); inject the four `OTEL_*` env vars on every core service. |
| 033 | Fargate tier rounding formalized | Compiler computes `(cpu + sidecar, memory + sidecar)`, rounds up to smallest supported tier, surfaces the rounding, errors on overflow. |
| 034 | Command surface refresh | Drop `bootstrap`; collapse `up`/`down` into `envinfra <direction> <env>`; wire stubs for `preinfra <side>` and `projinfra <direction> <side>`. For elastic, `projinfra up production` initially continues to do what `bootstrap` did (state backend only). `preinfra` is a no-op success. Pure dispatcher / naming change; real behavior arrives in 036/037/042. |
| 035 | Compiler output split + always-on four `-web` networks | New `infra/output/project/{development,production}/...` layout; move existing elastic project main.tf to `production/main.tf`; emit four `-web` external docker networks on every side; env-tier compose files now reference them `external: true`. |
| 036 | Fixed projinfra: per-project traefik + projinfra behavior on fixed | Emit `${project}-traefik` container in both sides' project compose with DNS-01 LE, three-cert resolver named `doctrine`, acme named volume, joined to four `-web` networks + `docex-ingress`. Wire `projinfra up/down <side>` for fixed: local docker for dev, ansible for remote prod, idempotent convergence for single-machine. Refuse `down` if env-tier still up. |
| 037 | Elastic projinfra: Route53 zone + ACM certs + two-phase apply | Emit `aws_route53_zone.project` and two ACM certs (stage + prod, DNS-01-validated against the zone). `projinfra up production` on elastic: ensure state backend → if zone not in state, `tofu apply -target=aws_route53_zone.project` + print NS + exit 0 → else untargeted apply. |
| 038 | Elastic projinfra: ALB (default variant) + project-tier outputs | `aws_lb.project` + ALB SG + 443 listener with both ACM certs as SNI bindings + 80→443 redirect listener. Project outputs: `alb_arn`, `alb_dns_name`, `alb_zone_id`, both `listener_arn`s, `alb_security_group_id`, both `cert_arn`s, `zone_id`, `zone_name_servers`. |
| 039 | ECR + IAM move to project-tier | One `aws_ecr_repository.<svc>` per core service in project main.tf (uses structural `/` emitter from 030); one `aws_iam_role.task_execution` per project with inline policy scoped to project ECR ARNs + `/<project>/{stage,prod}/*` SSM + log-group prefixes. Drop both from env-tier HCL. Outputs: `ecr_repository_<svc>_url/_arn`, `task_execution_role_arn`. |
| 040 | Env-tier HCL refactor: remote state + per-web listener rules | Add `data "terraform_remote_state" "project"` block to every env main.tf. Per-web-service `aws_lb_listener_rule.<svc>` + `aws_lb_target_group.<svc>` emitted env-tier, referencing the project ALB by ARN with deterministic per-env priorities. Env `web` SG ingress source = project ALB SG (via remote state). Allow-all egress on every emitted SG. |
| 041 | Elastic master VPC as preinfra | Env-tier HCL stops declaring per-project VPC/subnets/IGW/NAT; switches to data-sourcing the shared master VPC by tag. Centralized NAT (no per-project emission). Single-AZ commitment (us-east-1a primary; secondary used only for ALB cross-AZ + RDS subnet group). |
| 042 | `preinfra <side>` implementations | Fixed: probe `docex-ingress` bridge + HAProxy web_demux on the relevant host (local or via Ansible). Elastic: probe master VPC + IGW + NAT + subnets exist tagged correctly via AWS API; optionally probe `observability_backend_url`. `projinfra up <side>` and `envinfra up <env>` start refusing on failure. |
| 043 | Service Connect: private DNS + hyphenated namespace | Replace HTTP-namespace Service Connect with `aws_service_discovery_private_dns_namespace.<env>` named `${project}-${env}` (hyphen). Update ECS service `service_connect_configuration` registrations to use discoveryName = `${global_service_name}`. Update `provides.host.elastic` template if needed; EC2-traefik (next mod) will use the FQDN `<discoveryName>.<namespace>` form. |
| 044 | EC2-traefik reverse-proxy variant (EIP + PIP) | Branch projinfra emission on `reverse_proxy: ec2_traefik_{eip,pip}`: EC2 instance (Ubuntu 24.04, t3.nano in public-az-1), EBS cert volume tagged for discovery, IAM instance profile/role (route53/ssm/logs/ec2:AttachVolume scoped), `<project>-traefik` SG, SSM Parameter for config, CloudWatch log group, five route53 A-records, user_data with static traefik config + systemd config-fetch timer + (PIP-only) boot DNS-update unit. Env-tier web SG ingress source flips from ALB SG to `<project>-traefik` SG. Env-tier release rerenders the SSM Parameter. Largest single mod. |
| 045 | Test projects update + smoke walk | Update `test_projects/{fixed,elastic}/infra.yml` (`apex_domain:` rename, add `reverse_proxy: alb` on elastic), recompile, bump inner-repo versions, retag. Walk both per `PRE_CUT_CHECKLIST.md`. Catches any escaped drift across the prior 15 mods. |

## Progress tracking

When a mod's design pass starts, link its folder here.

- [x] 030 — Naming policy unification ([mod folder](../modifications/030_naming_policy_unification/))
- [x] 031 — CICL surface refresh ([mod folder](../modifications/031_cicl_surface_refresh/))
- [x] 032 — Telemetry alignment ([mod folder](../modifications/032_telemetry_alignment/))
- [x] 033 — Fargate tier rounding formalized ([mod folder](../modifications/033_fargate_tier_rounding/))
- [x] 034 — Command surface refresh ([mod folder](../modifications/034_command_surface_refresh/))
- [x] 035 — Compiler output split + always-on four `-web` networks ([mod folder](../modifications/035_compiler_output_split/))
- [ ] 036 — Fixed projinfra: per-project traefik + projinfra behavior on fixed
- [ ] 037 — Elastic projinfra: Route53 zone + ACM certs + two-phase apply
- [ ] 038 — Elastic projinfra: ALB (default variant) + project-tier outputs
- [ ] 039 — ECR + IAM move to project-tier
- [ ] 040 — Env-tier HCL refactor: remote state + per-web listener rules
- [ ] 041 — Elastic master VPC as preinfra
- [ ] 042 — `preinfra <side>` implementations
- [ ] 043 — Service Connect: private DNS + hyphenated namespace
- [ ] 044 — EC2-traefik reverse-proxy variant (EIP + PIP)
- [ ] 045 — Test projects update + smoke walk

## Cut implications

The minimum semver bump after landing 030–045 is **major** — naming-policy unification alone is a breaking change for every existing project's compiled output (`global_service_name` flips underscore→hyphen on Docker and ECS). Even projects pinned to the prior `docex_version` keep their old output, but the next pinned upgrade for any consumer will require recompile + redeploy.

Per `docex_process.md`, a major cut additionally requires a full re-inception of the test projects (mod 045 only covers the smoke walk; re-inception is operator work after this campaign closes).
