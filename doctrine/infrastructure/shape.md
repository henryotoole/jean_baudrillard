---
stratum: conditional
---

# Infrastructure Shape

This file provides a description of the shape infrastructure will tend to take in `fixed` and `elastic` foundations across the various environments.

The "shape" of a project's infrastructure is the fixed topology of a deployed stack: which resources exist, where they live, what depends on what. Most of an `infra.yml`'s content describes services. The shape describes everything *around* those services — the network plane, the reverse proxy, the registry, the DNS — and which of those things is the project's to control versus assumed to be in place. The shape is intentionally static; adding services to `infra.yml` adds content to the shape but does not change its topology.

## Description of Shape

### General

The general shape of an infrastructure is similar, but not identical, from foundation to foundation. There are both symmetries and asymmetries. In the below description, the following notation is used to indicate a distinct infrastructural resource: [resource].

In these sections, [service] is shorthand for "[core_service]s and [backing_service]s". Both [web_network] and [internal_network] are forms of [network].

**Runtime Shape** - HTTP requests are routed to a [network] in order to interact with the codebase. [dns] routes a request by domain to the relevant project [network]. [network] machinery and a [reverse_proxy] then work together to terminate TLS with [cert_manager] and route the request to the correct [service] in a specific environment. Within an environment, many different [service]s work together by communicating over one or more [network]s. Any environment may have multiple different [core_service]s or [backing_service]s; but all environments have the same set of roles. `prod` environments may also have multiple [core_service] containers running in parallel, and in this case the [reverse_proxy] doubles as a load balancer. [service]s can communicate directly with each other, so long as they are in the same [network] and environment; [service_discovery] lets them find each other. Telemetry signals originate in [service] containers and are transmitted to [telemetry_sidecar]s, which then export them to the [observability_backend].

**Lifecycle Shape** - Development occurs on the `dev` environment within a clone of the project's [repo]. Formal new [build_image]s are containerized and pushed to a [container_registry]. The `stage` and `prod` environments pull images from the [container_registry] and release them by combining with [environment_config] and [secrets].

### Fixed-Foundation

**Runtime Shape** - [registrar] sets [dns]; [dns] routes requests by domain to the [host_machine]. Here [web_demux] picks up 443/80 requests and forwards them to the relevant project [reverse_proxy] on the basis of domain, where TLS will be terminated with [cert_manager]. [web_demux] and project [reverse_proxy] live on the machine's [master_network], allowing them to communicate. [reverse_proxy] then routes requests to the correct [web_network] and [service] container unencrypted. Core and backing services are all docker containers. In `prod`, there might be multiple of the same [service] (e.g. multiple workers) per environment - [reverse_proxy] load balances in this case. [service]s communicate with each other over shared environment [internal_network]s. [service_discovery] is handled implicitly by docker network DNS. Telemetry signals originate in [service] containers and are transmitted to [telemetry_sidecar]s, which then export them to the [observability_backend].

**Network Egress** - Outbound requests reach the internet via the host machine's Docker-managed `iptables` config. This handles address translation and requires no effort on behalf of the developer or `docex` - it *just works*.

**Lifecycle Shape** - Development occurs on the `dev` environment within a clone of the project's [repo]. Formal new [build_image]s are containerized and pushed to a [container_registry], which is locally hosted. The `stage` and `prod` environments have [build_image]s pulled to them from [container_registry] with ansible and release them by combining with [environment_config] and [secrets]. 

| Name | Infrastructure Tier | Means | Description |
| ---- | ------------------- | ----- | ----------- |
| registrar | prerequisite | NameSilo, GoDaddy, etc. | A domain registrar. |
| dns | prerequisite | NameSilo, GoDaddy, Route53, Cloudflare. | A registrar's DNS configuration tool and NS-delegated DNS service. |
| host_machine | prerequisite | An on-prem server | The primary discrete machine that forms part or all of the `fixed` fleet of machines. Will have docker and always be linux-based. It is "primary" because DNS routes to it and it runs the [web_demux]. |
| web_demux | prerequisite | HAProxy | Uses SNI routing for 443 traffic and HTTP routing for 80 traffic to send traffic to the correct project [reverse_proxy] on the basis of domain. |
| master_network | prerequisite | Docker bridge network | Always named `docex-ingress`. Ties ingress together. |
| container_registry | prerequisite | Docker Registry V2 | A self-hosted registry on a [host_machine], used across many projects and outside of single-project control scope. |
| repo | prerequisite | github, gitlab, etc. | The repository in which project code, docs, infra declarations, etc. are stored. |
| observability_backend | prerequisite | HyperDX | A backend / application stack, either self-hosted or cloud-managed, which collects, indexes, and displays telemetry data. |
| reverse_proxy | project | traefik | Acts as reverse proxy, load balancer, and TLS terminator. Routes requests to containers. Always named `${project_name}-traefik`. |
| cert_manager | project | Traefik | Built into traefik, enabled in traefik config. Uses Let's Encrypt for automatic cert provisioning and renewal. Uses HTTP-01 and produces one cert per web-service and env as described [here](./cicl.md#fixed-tls) |
| service_discovery | project | Docker network DNS | This *just works* when containers are placed on a docker network. |
| build_image | project | Docker container images | Image built for release, has passed unit and integration tests. |
| web_network | project | Docker network | A standard docker network scoping access between [service]s for a given environment and `infra.yml`-defined network. `web` networks are joined by the [reverse_proxy] to the [master_network]. |
| internal_network | environment | Docker network | A standard docker network scoping access between [service]s for a given environment and `infra.yml`-defined network. Confined to one environment. |
| core_service | environment | Docker container | A container running the project's own code (one of the project's [build_image]s). |
| backing_service | environment | Docker container | A container running pre-packaged third-party software (postgres, redis, minio, etc.). |
| environment_config | environment | docker-compose config files | The `compose.yml` files which allow docker to orchestrate containers. |
| secrets | environment | `.env` file | Stored in `$pr/infra/secrets/${environment}.env`. Used directly from there in `dev` and `test`; pushed by ansible to `stage` and `prod`. |
| telemetry_sidecar | environment | OTel Collector | Collector sidecar, distinct compose container for each [service] sharing at least one of its networks. Accepts telemetry signals from the [service] and forwards to [observability_backend] |

### Elastic-Foundation

**Runtime Shape** - [registrar] sets [dns]; [dns] routes requests by domain to the project's [reverse_proxy] within the [master_network]. The [reverse_proxy] terminates TLS with [cert_manager]. [reverse_proxy] then routes requests to the correct [network] and [service] container unencrypted based on host or path rules. In `prod`, [core_service]s can have multiple replicas; the [reverse_proxy] load-balances across them. [service]s communicate over shared environment [network]. [service_discovery] allows [service]s to find each other by name; reachability remains gated by SG rules. Telemetry signals originate in [service] containers and are transmitted to [telemetry_sidecar]s, which then export them to the [observability_backend].

**Network Egress** - Outbound requests reach the internet by traveling through the [master_network]'s [nat_gateway] service and IGW.

**Lifecycle Shape** - Development occurs on the `dev` environment within a clone of the project's [repo]. Formal new [build_image]s are containerized and pushed to a [container_registry]. The `stage` and `prod` environments reference these images in their ECS task definitions and release them by combining with [environment_config] applied via OpenTofu and [secrets] pushed to AWS SSM Parameter Store.

| Name | Infrastructure Tier | Means | Description |
| ---- | ------------------- | ----- | ----------- |
| aws_account | prerequisite | An AWS account | The AWS account in which all elastic resources are provisioned. Multiple projects may exist under one account. |
| registrar | prerequisite | NameSilo, GoDaddy, etc. + NS delegation | A registrar's DNS configuration, with nameservers delegated to our [dns] so the project controls its own records. |
| repo | prerequisite | github, gitlab, etc. | The repository in which project code, docs, infra declarations, etc. are stored. |
| observability_backend | prerequisite | HyperDX | A backend / application stack, either self-hosted or cloud-managed, which collects, indexes, and displays telemetry data. |
| master_network | prerequisite | AWS VPC | A master VPC shared by all projects. Contains centralized IGW, NAT, and four subnets: a public-private pair in the default AZ and a redundant public-private pair in a secondary AZ. The redundant pair is included only to satisfy the two-AZ requirement. |
| nat_gateway | prerequisite | AWS NAT | Centralized NAT gateway shared by all projects. |
| reverse_proxy | project | AWS ALB or EC2-with-traefik | Each project gets its own reverse proxy. This is project-configured either as an ALB or a small EC2 instance with traefik. Terminates TLS via [cert_manager] and forwards to [service]s. Doubles as a load balancer for replicated [core_service]s in `prod`. |
| cert_manager | project | AWS ACM certificate (ALB) or traefik (EC2) | ALB: Uses ACM certs. Traefik: Uses built-in Let's Encrypt; enabled with config. Both employ DNS-01 and the two cert system defined [here](./cicl.md#elastic-tls) |
| dns | project | AWS Route53 | DNS handling which project can drive. `docex` creates one hosted zone per project for its `apex_domain:`; the operator NS-delegates to it from the parent. |
| container_registry | project | AWS ECR | The project's container registry, holding [build_image]s. |
| build_image | project | Docker container images | Image built for release, has passed unit and integration tests. |
| network | environment | AWS security group | A security group within the [master_network], scoping access between [service]s for a given environment and `infra.yml`-defined network.  |
| service_discovery | environment | ECS Service Connect over a Cloud Map private DNS namespace | Each ECS task carries an injected Envoy sidecar that resolves peer services by name. The namespace is named `${project}-${env}`, associated with the master VPC, and lives at the env tier. From inside the namespace (ECS tasks with Service Connect injected), services resolve by discoveryName alone (e.g. `myproject-prod-api`); from elsewhere in the master VPC (e.g. the EC2-traefik instance), they resolve as `<discoveryName>.<namespace>` (e.g. `myproject-prod-api.myproject-prod`) via the namespace's auto-created private hosted zone. Services with a declared `port` register as discoverable; services without (e.g. a port-less worker) participate as clients only. Reachability remains gated by SG rules — Service Connect provides resolution, not authorization. |
| core_service | environment | AWS ECS Fargate task | A Fargate container running one of the project's [build_image]s from ECR. Rolled by ECS on image updates. |
| backing_service | environment | AWS-native service (RDS, S3, ElastiCache, etc.) | A managed AWS service standing in for what would be a third-party container in `fixed`. The specific AWS resource depends on the service's role. |
| environment_config | environment | OpenTofu HCL files | The `main.tf` per env which OpenTofu applies to provision env resources. |
| secrets | environment | AWS SSM Parameter Store entries | Source of truth is `$pr/infra/secrets/${environment}.env`; pushed at release time to `/${project}/${env}/${KEY}` as a `SecureString`. |
| telemetry_sidecar | environment | OTel Collector | Collector sidecar, paired with a [service] in a task definition. Accepts telemetry signals from the [service] and forwards to [observability_backend] |

## Shape and Environment

A project's foundation declaration in `infra.yml` applies *only* to the `stage` and `prod` environments. `test` and `dev` are always fixed, regardless of the "production" foundation. Furthermore, `test` and `dev` never have "replica" containers - only one container per role, per environment.

| Environment | Compilation in fixed-foundation project | Compilation in elastic-foundation project | Replicas |
| ----------- | --------------------------------------- | ----------------------------------------- | -------- |
| `dev` | fixed | fixed | no |
| `test` | fixed | fixed | no |
| `stage` | fixed | elastic | no |
| `prod` | fixed | elastic | yes |

## Concrete Example

It always helps to round off abstract discussion with a concrete example. 

Consider a project with the following minimal `infra.yml`:

```yml
cicl_version: "1"
foundation: elastic
apex_domain: "example.com"
domain_default_service: api
repo_url: "https://github.com/owner_account/project_name"

core_services:
	api:
		role: web
		port: 8080
		networks: [web, internal]
		env:
			DATABASE_HOST: ${backing_services.database.host}
			DATABASE_PORT: ${backing_services.database.port}
			DATABASE_NAME: ${backing_services.database.db}
			DATABASE_USER: ${backing_services.database.user}
			DATABASE_PASSWORD: ${backing_services.database.password}
		resources:
			cpu: 1.0
			memory: 2GB
			disk: 20GB

backing_services:
	database:
		role: relational_db
		engine: postgres
		version: "15"
		networks: [internal]
```

### Compiled for `dev` (fixed shape, even though project is elastic)

`compose.yml` files describing:

**Development-side project infrastructure:**
- Four "external" web networks: `myproject-dev-web`, `myproject-test-web`, `myproject-stage-web`, `myproject-prod-web`. (All four are created even though not all are used).
- A traefik container spanning all four web networks and the master network `docex-ingress`.

**Environment infrastructure:**
- One internal network: `myproject-dev-internal`
- A named volume: `myproject-dev-database-data`
- An `api` container on both networks (no published host port), with Traefik labels routing both `dev.myproject.example.com` (it's the `domain_default_service`) and `api.dev.myproject.example.com` to it, plus `DATABASE_*` env for internally constructing the db url
- A `database` container on the internal network, postgres 15 image, env vars and healthcheck per the transfer table
- Definition of the project's `traefik` container. This container sits on the `docex-ingress` network and its relevant project networks (`myproject-dev-web`, `myproject-dev-internal`). It ensures that `dev.myproject.example.com` and `api.dev.myproject.example.com` both actually get routed to the `api` service container.

The developer accesses the project at `dev.myproject.example.com` on the dev machine.

### Compiled for `prod` (elastic shape)

The master VPC, IGW, NAT gateway, four subnets, and VPC endpoints are all prerequisite infrastructure shared across every elastic project in the AWS account, so nothing about them appears in this project's HCL. The project- and env-tier files reference them by name via data sources.

HCL files describing:

**Production-side project infrastructure:**
- Route53 zone for `myproject.example.com`, NS-delegated from the parent `example.com` zone by the operator
- Two ACM certs: one with three SANs (`myproject.example.com`, `prod.myproject.example.com`, `*.prod.myproject.example.com`) and one with two SANs (`*.stage.myproject.example.com`, `stage.myproject.example.com`). Dev and test envs are always fixed and never reach the ALB, so their domains are not on these certs.
- ECR repo for the `api` image
- 1 ALB `myproject-alb` in the master VPC's two public subnets, listening on 443 with the project ACM certs. One ALB serves both stage and prod via host-based listener rules.
- 1 IAM task-execution role for ECS to pull from ECR and read SSM secrets

(If the project had declared `reverse_proxy: ec2_traefik_eip`, the ALB and ACM certs would be replaced by a single EC2 instance with an elastic IP, running traefik with built-in Let's Encrypt for the same cert / SAN structure. Same ingress shape from outside, different mechanism.)

**Environment infrastructure:**
- 2 SGs in the master VPC: `myproject-prod-web`, `myproject-prod-internal`
- 1 ECS cluster + 1 ECS service for `api`, in the master VPC's primary-AZ private subnet, attached to both SGs
- 1 ALB target group for the prod `api` service, plus 1 listener rule on the project ALB whose host-header condition matches the explicit set `api.prod.myproject.example.com`, `prod.myproject.example.com`, and `myproject.example.com` pointed at that target group.
- 1 RDS instance for `database` (identifier `myproject-prod-database`), in the master VPC's primary-AZ private subnet, attached only to the `internal` SG. The RDS subnet group references both private subnets (primary and secondary AZ) to satisfy AWS's multi-AZ requirement; the instance is pinned to the primary AZ.
- 5 Route53 A-records (alias) in the project's zone:
    - `<project>.<apex_domain>` (bare project)
    - `*.prod.<project>.<apex_domain>` (prod wildcard)
    - `prod.<project>.<apex_domain>` (prod ergonomic)
    - `*.stage.<project>.<apex_domain>` (stage wildcard)
    - `stage.<project>.<apex_domain>` (stage ergonomic)

The `api` service runs in the master VPC's primary-AZ private subnet, attached to both the `web` SG (so the ALB can reach it) and the `internal` SG (so it can reach `database`). The `database` runs in the same private subnet, attached only to the `internal` SG. The two are wired together by the discrete connection parts the postgres engine's `provides:` block defines: `host` resolves to the live RDS hostname (an `@aws_db_instance.database.address` pass-through), while `user`/`password` arrive as ECS `secrets[]` sourced from SSM. `api` composes its own connection string from those parts at startup.

Egress to anything outside the master VPC (third-party API calls, HyperDX, ECR pulls when no VPC endpoint covers them) flows from the private subnet through the master VPC's centralized NAT gateway and out via the IGW. The ALB reaches the open internet directly via the IGW from the public subnets.