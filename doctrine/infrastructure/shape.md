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

**Runtime Shape** - HTTP requests are routed to a [network] in order to interact with the project. [dns] routes a request by domain to the relevant project [network]. [network] machinery and a [reverse_proxy] then work together to terminate TLS with [cert_manager] and route the request to the correct [service] in a specific environment. Within an environment, many different [service]s work together by communicating over one or more [network]s. Any environment may have multiple different [core_service]s or [backing_service]s; but all environments have the same set of roles. `prod` environments may also have multiple containers of one [core_service] running in parallel. How they are load-balanced depends on the network: the [reverse_proxy] balances replicas of a `web` [core_service], because that is the traffic it terminates; replicas on an internal [network] are balanced by [service_discovery] instead, with no proxy in the path. [service]s can communicate directly with each other, so long as they are in the same [network] and environment; [service_discovery] lets them find each other. Telemetry signals originate in [service] containers and are transmitted to [telemetry_sidecar]s, which then export them to the [observability_backend].

**Lifecycle Shape** - Development occurs on the `dev` environment within a clone of the project's [repo]. Formal new [build_image]s are containerized and pushed to a [container_registry]. The `stage` and `prod` environments pull images from the [container_registry] and release them by combining with [environment_config] and [configurable_vars].

### Fixed-Foundation

**Runtime Shape** - [registrar] sets [dns]; [dns] routes requests by domain to the [host_machine]. Here [web_demux] picks up 443/80 requests and forwards them to the relevant project [reverse_proxy] on the basis of domain, where TLS will be terminated with [cert_manager]. [web_demux] and project [reverse_proxy] live on the machine's [master_network], allowing them to communicate. [reverse_proxy] then routes requests to the correct [web_network] and [service] container unencrypted. Core and backing services are all docker containers. In `prod`, a [core_service] may run as several replica containers. Traefik's labels are keyed on the unqualified service name, so N replicas of a `web` [core_service] register as N servers behind one router and [reverse_proxy] balances them. Replicas of a non-`web` [core_service] — a worker, say — are never seen by the proxy at all: they share one docker network alias, and docker DNS round-robins across them. [service]s communicate with each other over shared environment [internal_network]s. [service_discovery] is handled implicitly by docker network DNS. Telemetry signals originate in [service] containers and are transmitted to [telemetry_sidecar]s, which then export them to the [observability_backend].

**Network Egress** - Outbound requests reach the internet via the host machine's Docker-managed `iptables` config. This handles address translation and requires no effort on the part of the developer or `docex` - it *just works*.

**Lifecycle Shape** - Development occurs on the `dev` environment within a clone of the project's [repo]. Formal new [build_image]s are containerized and pushed to a [container_registry], which is locally hosted. The `stage` and `prod` environments have [build_image]s pulled to them from [container_registry] with ansible and release them by combining with [environment_config] and [configurable_vars]. 

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
| core_service | environment | Docker container | A container running the project's own code (one of the project's [build_image]s). One container per [core service](./cicl.md#core-services), not per codebase — a codebase's core services all run the same image with different `command`s. In `prod`, one container per replica. |
| backing_service | environment | Docker container | A container running pre-packaged third-party software (postgres, redis, minio, etc.). |
| environment_config | environment | docker-compose config files | The `compose.yml` files which allow docker to orchestrate containers. |
| configurable_vars | environment | `.env` files | Sourced from TTE vars, secrets, and config `<env>.env` files; aggregated and injected by `docex`. |
| telemetry_sidecar | environment | OTel Collector | Collector sidecar, one distinct compose container per *emitted* [core_service] container — i.e. one per [core_service], and per replica. It is paired by network namespace (`network_mode: service:<container>`), not by shared network, so it always reaches its partner on loopback. Accepts telemetry signals from the [core_service] and forwards to [observability_backend] |

### Elastic-Foundation

**Runtime Shape** - [registrar] sets [dns]; [dns] routes requests by domain to the project's [reverse_proxy] within the [master_network]. The [reverse_proxy] terminates TLS with [cert_manager]. [reverse_proxy] then routes requests to the correct [network] and [service] container unencrypted based on host or path rules. In `prod`, a [core_service] can have multiple replicas (ECS `desired_count`). The [reverse_proxy] load-balances the replicas of a `web` [core_service] via its target group; replicas of an internal [core_service] are balanced by [service_discovery], with no proxy involved. [service]s communicate over shared environment [network]s. [service_discovery] allows [service]s to find each other by name; reachability remains gated by SG rules. Telemetry signals originate in [service] containers and are transmitted to [telemetry_sidecar]s, which then export them to the [observability_backend].

**Network Egress** - Outbound requests reach the internet by traveling through the [master_network]'s [nat_gateway] service and IGW.

**Lifecycle Shape** - Development occurs on the `dev` environment within a clone of the project's [repo]. Formal new [build_image]s are containerized and pushed to a [container_registry]. The `stage` and `prod` environments reference these images in their ECS task definitions and release them by combining with [environment_config] applied via OpenTofu and [configurable_vars] pushed to AWS SSM Parameter Store.

| Name | Infrastructure Tier | Means | Description |
| ---- | ------------------- | ----- | ----------- |
| aws_account | prerequisite | An AWS account | The AWS account in which all elastic resources are provisioned. Multiple projects may exist under one account. |
| registrar | prerequisite | NameSilo, GoDaddy, etc. + NS delegation | A registrar's DNS configuration, with nameservers delegated to our [dns] so the project controls its own records. |
| repo | prerequisite | github, gitlab, etc. | The repository in which project code, docs, infra declarations, etc. are stored. |
| observability_backend | prerequisite | HyperDX | A backend / application stack, either self-hosted or cloud-managed, which collects, indexes, and displays telemetry data. |
| master_network | prerequisite | AWS VPC | A master VPC shared by all projects. Contains centralized IGW, NAT, and four subnets: a public-private pair in the default AZ and a redundant public-private pair in a secondary AZ. The redundant pair is included only to satisfy the two-AZ requirement. |
| nat_gateway | prerequisite | AWS NAT | Centralized NAT gateway shared by all projects. |
| reverse_proxy | project | AWS ALB or EC2-with-traefik | Each project gets its own reverse proxy. This is project-configured either as an ALB or a small EC2 instance with traefik. Terminates TLS via [cert_manager] and forwards to [service]s. Doubles as a load balancer for a replicated `web` [core_service] in `prod`; internal [core_service]s are balanced by [service_discovery] instead. |
| cert_manager | project | AWS ACM certificate (ALB) or traefik (EC2) | ALB: Uses ACM certs. Traefik: Uses built-in Let's Encrypt; enabled with config. Both employ DNS-01 and the two cert system defined [here](./cicl.md#elastic-tls) |
| dns | project | AWS Route53 | DNS handling which the project can drive. `docex` creates one hosted zone per project for its `apex_domain:`; the operator NS-delegates to it from the parent. |
| container_registry | project | AWS ECR | The project's container registry, holding [build_image]s. |
| build_image | project | Docker container images | Image built for release, has passed unit and integration tests. |
| ecs_cluster | project | AWS ECS cluster | One empty cluster per production-side env (`${project}-stage`, `${project}-prod`), provisioned at the project tier so both always exist before any env release. Env-tier release attaches [core_service] tasks/services into the env's cluster. Project-tier (not env-tier) because the [reverse_proxy] must be able to rely on both clusters existing regardless of which env has been released — the EC2-traefik ECS provider fails *all* route-building if any configured cluster is absent (see [`projinfra/ec2_traefik.md`](./specifics/projinfra/ec2_traefik.md)). Empty clusters incur no cost. |
| network | environment | AWS security group | A security group within the [master_network], scoping access between [service]s for a given environment and `infra.yml`-defined network.  |
| service_discovery | environment | ECS Service Connect over a Cloud Map private DNS namespace | Each ECS task carries an injected Envoy sidecar that resolves peer services by name. The namespace is named `${project}-${env}`, associated with the master VPC, and lives at the env tier. Service Connect resolution is **mesh-internal only**: from inside the namespace (ECS tasks with Service Connect injected) services resolve by discoveryName (e.g. `myproject-prod-api-web`). The namespace's private hosted zone carries **no per-service A-records**, so a client *outside* the mesh — an EC2-traefik instance is in the master VPC but in no task's network namespace — cannot resolve services by name via DNS; the EC2-traefik path discovers backends through the traefik ECS provider instead (see [`projinfra/ec2_traefik.md`](./specifics/projinfra/ec2_traefik.md)). Services with a declared `port` register as discoverable; services without (e.g. a port-less worker) participate as clients only. Reachability remains gated by SG rules — Service Connect provides resolution, not authorization. |
| core_service | environment | AWS ECS Fargate task | A Fargate container running one of the project's [build_image]s from ECR. One ECS service and task definition per [core service](./cicl.md#core-services), all referencing the codebase's single image; `desired_count` carries the replica count in `prod`. Rolled by ECS on image updates. |
| backing_service | environment | AWS-native service (RDS, S3, ElastiCache, etc.) | A managed AWS service standing in for what would be a third-party container in `fixed`. The specific AWS resource depends on the service's role. |
| environment_config | environment | OpenTofu HCL files | The `main.tf` per env which OpenTofu applies to provision env resources. |
| configurable_vars | environment | AWS SSM Parameter Store entries | Sourced from TTE vars, secrets, and config `<env>.env` files; aggregated and pushed at release time to SSM `/${project}/${env}/${KEY}`. |
| telemetry_sidecar | environment | OTel Collector | Collector sidecar, one container inside each task definition that also runs an ECS service — so one per [core_service], and one per running replica. Accepts telemetry signals from the [core_service] and forwards to [observability_backend] |

## Shape and Environment

A project's foundation declaration in `infra.yml` applies *only* to the `stage` and `prod` environments. `test` and `dev` are always fixed, regardless of the "production" foundation. Furthermore, `test` and `dev` never have "replica" containers - only one container per [core service](./cicl.md#core-services), per environment.

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
cicl_version: "3"
foundation: elastic
apex_domain: "example.com"
domain_default_service: api.web
repo_url: "https://github.com/owner_account/project_name"
observability_backend_url: "https://hyperdx.example.com"

codebases:
  api:
    env:
      DATABASE_HOST: ${backing_services.appdb.host}
      DATABASE_PORT: ${backing_services.appdb.port}
      DATABASE_NAME: ${backing_services.appdb.db}
      DATABASE_USER: ${backing_services.appdb.user}
      DATABASE_PASSWORD: ${backing_services.appdb.password}
    core_services:
      web:
        role: web
        command: ["python", "-m", "entrypoints.http"]
        port: 8080
        networks: [web, internal]
        health_check_path: /health
        surfaces:
          rest:
            api_styles: [rest]
        uses: [appdb]
        resources:
          cpu: 1.0
          memory: 2GB
          disk: 20GB

backing_services:
  appdb:
    role: relational_db
    engine: postgres
    version: "15"
    networks: [internal]
    schema_owned_by: api
```

### Compiled for `dev` (fixed shape, even though project is elastic)

`compose.yml` files describing:

**Development-side project infrastructure:**
- Four "external" web networks: `myproject-dev-web`, `myproject-test-web`, `myproject-stage-web`, `myproject-prod-web`. (All four are created even though not all are used).
- A traefik container spanning all four web networks and the master network `docex-ingress`.

**Environment infrastructure:**
- One internal network: `myproject-dev-internal`
- A named volume: `myproject-dev-appdb_data`
- An `api-web` container on both networks (no published host port), with Traefik labels routing both `dev.myproject.example.com` (it's the `domain_default_service`) and `api-web.dev.myproject.example.com` to it, plus `DATABASE_*` env for internally constructing the db url
- An `api-exec` container, profile-gated so `up` never starts it — the per-codebase one-off container `build`, `test`, and `migrate` run inside (see [exec_service.md](./specifics/exec_service.md))
- An `appdb` container on the internal network, postgres 15 image, env vars and healthcheck per the transfer table

The project traefik (project-tier, listed above) spans the `-web` networks and `docex-ingress`; it picks up the `api-web` container's labels so that `dev.myproject.example.com` and `api-web.dev.myproject.example.com` both actually get routed to it. The developer accesses the project at `dev.myproject.example.com` on the dev machine.

### Compiled for `prod` (elastic shape)

The master VPC, IGW, NAT gateway, four subnets, and VPC endpoints are all prerequisite infrastructure shared across every elastic project in the AWS account, so nothing about them appears in this project's HCL. The project- and env-tier files reference them by name via data sources.

HCL files describing:

**Production-side project infrastructure:**
- Route53 zone for `myproject.example.com`, NS-delegated from the parent `example.com` zone by the operator
- Two ACM certs: one with three SANs (`myproject.example.com`, `prod.myproject.example.com`, `*.prod.myproject.example.com`) and one with two SANs (`*.stage.myproject.example.com`, `stage.myproject.example.com`). Dev and test envs are always fixed and never reach the ALB, so their domains are not on these certs.
- ECR repo for the `api` image (one repo per codebase, shared by every core service)
- 1 ALB `myproject-alb` in the master VPC's two public subnets, listening on 443 with the project ACM certs. One ALB serves both stage and prod via host-based listener rules.
- 1 IAM task-execution role for ECS to pull from ECR and read SSM secrets
- 2 ECS clusters `myproject-stage` and `myproject-prod`, created empty; env-tier release attaches services into the matching one

(If the project had declared `reverse_proxy: ec2_traefik_eip`, the ALB and ACM certs would be replaced by a single EC2 instance with an elastic IP, running traefik with built-in Let's Encrypt for the same cert / SAN structure. Same ingress shape from outside, different mechanism.)

**Environment infrastructure:**
- 2 SGs in the master VPC: `myproject-prod-web`, `myproject-prod-internal`
- 1 ECS service for `api-web` (in the project-tier `myproject-prod` cluster), in the master VPC's primary-AZ private subnet, attached to both SGs
- 1 migration ECS task definition for the `api` codebase (family `myproject-prod-api-migrate`), run as a one-off `RunTask` at release
- 1 ALB target group for the prod `api-web` core service, plus 1 listener rule on the project ALB whose host-header condition matches the explicit set `api-web.prod.myproject.example.com`, `prod.myproject.example.com`, and `myproject.example.com` pointed at that target group.
- 1 RDS instance for `appdb` (identifier `myproject-prod-appdb`), in the master VPC's primary-AZ private subnet, attached only to the `internal` SG. The RDS subnet group references both private subnets (primary and secondary AZ) to satisfy AWS's multi-AZ requirement; the instance is pinned to the primary AZ.
- 5 Route53 A-records (alias) in the project's zone:
    - `<project>.<apex_domain>` (bare project)
    - `*.prod.<project>.<apex_domain>` (prod wildcard)
    - `prod.<project>.<apex_domain>` (prod ergonomic)
    - `*.stage.<project>.<apex_domain>` (stage wildcard)
    - `stage.<project>.<apex_domain>` (stage ergonomic)

The `api-web` service runs in the master VPC's primary-AZ private subnet, attached to both the `web` SG (so the ALB can reach it) and the `internal` SG (so it can reach `appdb`). The `appdb` runs in the same private subnet, attached only to the `internal` SG. The two are wired together by the discrete connection parts the postgres engine's `provides:` block defines: `host` resolves to the live RDS hostname (an `@aws_db_instance.appdb.address` pass-through), while `user`/`password` arrive as ECS `secrets[]` sourced from SSM. `api-web` composes its own connection string from those parts at startup.

Egress to anything outside the master VPC (third-party API calls, HyperDX, ECR pulls when no VPC endpoint covers them) flows from the private subnet through the master VPC's centralized NAT gateway and out via the IGW. The ALB reaches the open internet directly via the IGW from the public subnets.