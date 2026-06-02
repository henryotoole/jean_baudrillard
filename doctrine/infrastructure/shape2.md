# Infrastructure Shape

This file provides a description of the shape infrastructure will tend to take in `fixed` and `elastic` foundations across the various environments.

The "shape" of a project's infrastructure is the fixed topology of a deployed stack: which resources exist, where they live, what depends on what. Most of an `infra.yml`'s content describes services. The shape describes everything *around* those services — the network plane, the reverse proxy, the registry, the DNS — and which of those things is the project's to control versus assumed to be in place. The shape is intentionally static; adding services to `infra.yml` adds content to the shape but does not change its topology.

## Description of Shape

### General

The general shape of an infrastructure is similar, but not identical, from foundation to foundation. There are both symmetries and asymmetries. In the below description, the following notation is used to indicate a distinct infrastructural resource: [resource].

In these sections, [service] is shorthand for "[core_service]s and [backing_service]s.

**Runtime Shape** - HTTP requests are routed to a [network] in order to interact with the codebase. [dns] routes a request by domain to the relevant project [network]. [network] machinery and a [reverse_proxy] then work together to terminate TLS with [cert_manager] and route the request to the correct [service] in a specific environment. Within an environment, many different [service]s work together by communicating over one or more [network]s. Any environment may have multiple different [core_service]s or [backing_service]s; but all environments have the same set of roles. `prod` environments may also have multiple [core_service] containers running in parallel, and in this case the [reverse_proxy] doubles as a load balancer. [service]s can communicate directly with each other, so long as they are in the same [network] and environment; [service_discovery] lets them find each other.

**Lifecycle Shape** - Development occurs on the `dev` environment within a clone of the project's [repo]. Formal new [build_image]s are containerized and pushed to a [container_registry]. The `stage` and `prod` environments pull images from the [container_registry] and release them by combining with [environment_config] and [secrets].

### Fixed-Foundation

**Runtime Shape** - [registrar] and its [dns] routes requests by domain to the [host_machine], where a singular [reverse_proxy] will pick it up and terminate TLS with [cert_manager]. [reverse_proxy] then routes it to the correct [network] and [service] container unencrypted. Core and backing services are all docker containers. In `prod`, there might be multiple of the same [service] (e.g. multiple workers) per environment - [reverse_proxy] load balances in this case. [service]s communicate with each other over shared environment [network]s. [service_discovery] is handled implicitly by docker network DNS.

**Lifecycle Shape** - Development occurs on the `dev` environment within a clone of the project's [repo]. Formal new [build_image]s are containerized and pushed to a [container_registry], which is locally hosted. The `stage` and `prod` environments have [build_image]s pulled to them from [container_registry] with ansible and release them by combining with [environment_config] and [secrets]. 

| Name | Infrastructure Tier | Means | Description |
| ---- | ------------------- | ----- | ----------- |
| registrar | prerequisite | NameSilo, GoDaddy, etc. | A domain registrar. |
| dns | prerequisite | NameSilo, GoDaddy, etc. | A registrar's DNS configuration tool. |
| host_machine | prerequisite | An on-prem server | The primary discrete machine that forms part or all of the `fixed` fleet of machines. Will have docker and always be linux-based. It is "primary" because DNS routes to it and it runs the [reverse_proxy]. |
| reverse_proxy | prerequisite | traefik | Acts as reverse proxy, load balancer, and TLS terminator. Routes requests to containers. |
| cert_manager | prerequisite | Traefik | Built into traefik, enabled in traefik config. Uses Let's Encrypt for automatic cert provisioning and renewal. |
| container_registry | prerequisite | Docker Registry V2 | A self-hosted registry on a [host_machine], used across many projects and outside of single-project control scope. |
| repo | prerequisite | github, gitlab, etc. | The repository in which project code, docs, infra declarations, etc. are stored. |
| service_discovery | project | Docker network DNS | This *just works* when containers are placed on a docker network. |
| build_image | project | Docker container images | Image built for release, has passed unit and integration tests. |
| network | environment | Docker network | A standard docker network, configured by compiler rules. |
| core_service | environment | Docker container | A container running the project's own code (one of the project's [build_image]s). |
| backing_service | environment | Docker container | A container running pre-packaged third-party software (postgres, redis, minio, etc.). |
| environment_config | environment | docker-compose config files | The `compose.yml` files which allow docker to orchestrate containers. |
| secrets | environment | `.env` file | Stored in `$pr/infra/secrets/${environment}.env`. Used directly from there in `dev` and `test`; pushed by ansible to `stage` and `prod`. |

### Elastic-Foundation

**Runtime Shape** - A [registrar] is configured such that our [dns] routes requests by domain to the env's [reverse_proxy]. The [reverse_proxy] terminates TLS with [cert_manager] and forwards each request to the correct [service] within that environment based on host or path rules. In `prod`, [core_service]s can have multiple replicas; the [reverse_proxy] load-balances across them. [service]s communicate over shared environment [network]s, which on elastic are AWS security groups within the project [vpc]. [service_discovery] (ECS Service Connect) allows [service]s to find each other by name; reachability remains gated by SG rules.

**Lifecycle Shape** - Development occurs on the `dev` environment within a clone of the project's [repo]. Formal new [build_image]s are containerized and pushed to a [container_registry]. The `stage` and `prod` environments reference these images in their ECS task definitions and release them by combining with [environment_config] applied via OpenTofu and [secrets] pushed to AWS SSM Parameter Store.

| Name | Infrastructure Tier | Means | Description |
| ---- | ------------------- | ----- | ----------- |
| aws_account | prerequisite | An AWS account | The AWS account in which all elastic resources are provisioned. The doctrine assumes one project per account; multi-tenant accounts are out of scope. |
| registrar | prerequisite | NameSilo, GoDaddy, etc. + NS delegation | A registrar's DNS configuration, with nameservers delegated to our [dns] (AWS Route53) so the project controls its own records. The operator performs this delegation between the two phases of [`./bin/docex bootstrap`](./specifics/elastic_bootstrap.md#two-phase-project-tier-apply), using the NS records printed by phase 1. |
| repo | prerequisite | github, gitlab, etc. | The repository in which project code, docs, infra declarations, etc. are stored. |
| dns | project | AWS Route53 | DNS handling which project can drive. `docex` creates one hosted zone per project for its `domain:`; the operator NS-delegates to it from the parent. |
| vpc | project | AWS VPC | The project's private network space, shared across all elastic environments. Contains the subnets, IGW, and NAT gateways needed by every environment. |
| cert_manager | project | AWS ACM certificate | TLS certificate covering `*.${domain}` **and** `*.${env}.${domain}` for each env (`*.dev.${domain}`, `*.test.${domain}`, `*.stage.${domain}`, `*.www.${domain}`), so per-service subdomains like `backend.dev.${domain}` are covered. Used by environment [reverse_proxy]s. |
| container_registry | project | AWS ECR | The project's container registry, holding [build_image]s. |
| build_image | project | Docker container images | Image built for release, has passed unit and integration tests. |
| network | environment | AWS security group | A security group within the project [vpc], scoping access between [service]s. |
| service_discovery | environment | ECS Service Connect over a Cloud Map HTTP namespace | Each ECS task carries an injected Envoy sidecar that resolves peer services by name. The namespace is named `${project}_${env}` and lives at the env tier. Services with a declared `port` register as discoverable; services without (e.g. a port-less worker) participate as clients only. Reachability remains gated by SG rules — Service Connect provides resolution, not authorization. |
| core_service | environment | AWS ECS Fargate task | A Fargate container running one of the project's [build_image]s from ECR. Rolled by ECS on image updates. |
| backing_service | environment | AWS-native service (RDS, S3, ElastiCache, etc.) | A managed AWS service standing in for what would be a third-party container in `fixed`. The specific AWS resource depends on the service's role. |
| reverse_proxy | environment | AWS ALB | One ALB per environment, in the env's public subnets. Terminates TLS via [cert_manager] and forwards to [service]s. Doubles as a load balancer for replicated [core_service]s in `prod`. |
| environment_config | environment | OpenTofu HCL files | The `main.tf` per env which OpenTofu applies to provision env resources. |
| secrets | environment | AWS SSM Parameter Store entries | Source of truth is `$pr/infra/secrets/${environment}.env`; pushed at release time to `/${project}/${env}/${KEY}` as a `SecureString`. |

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
domain: "example.com"
domain_default_service: api
container_registry: "registry.example.com"
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

A `docker-compose.yml` at the project root containing:

- Two networks: `myproject_dev_web`, `myproject_dev_internal`
- A named volume: `myproject_dev_database_data`
- An `api` container on both networks (no published host port), with Traefik labels routing both `dev.example.com` (it's the `domain_default_service`) and `api.dev.example.com` to it, plus `DATABASE_*` env for internally constructing the db url
- A `database` container on the internal network, postgres 15 image, env vars and healthcheck per the transfer table

Traefik (machine-wide, outside scope) discovers `api` and routes `dev.example.com` and `api.dev.example.com` to it over the docker network. The developer accesses the project at those subdomains on the dev machine.

### Compiled for `prod` (elastic shape)

HCL files describing:

**Project infrastructure (emitted once for the project):**
- VPC `myproject` (`10.0.0.0/16`), IGW, 2× NAT gateways
- Route53 zone for `example.com`
- ACM cert for `*.example.com` plus the per-env wildcards `*.dev.example.com`, `*.test.example.com`, `*.stage.example.com`, `*.www.example.com`
- ECR repo for the `api` image

**Environment infrastructure (emitted for `prod`):**
- 4 subnets: `myproject_prod_public_a`, `_public_b`, `_private_a`, `_private_b`
- 2 SGs: `myproject_prod_web`, `myproject_prod_internal`
- 1 ALB `myproject-prod-alb` in the public subnets, listening on 443 with the project ACM cert
- 1 ECS cluster + 1 ECS service for `api`, attached to both SGs, registered as an ALB target
- 1 RDS instance for `database` (identifier `myproject-prod-database`), in the private subnets, attached only to the `internal` SG
- 2 Route53 A-records: `www.example.com` and the wildcard `*.www.example.com` → `myproject-prod-alb` (the bare host serves the `domain_default_service`; the wildcard serves every `${service}.www.example.com`)

The `api` service runs in private subnets, attached to both the `web` SG (so the ALB can reach it) and the `internal` SG (so it can reach `database`). The `database` runs in private subnets, attached only to the `internal` SG. The two are wired together by the discrete connection parts the postgres engine's `provides:` block defines: `host` resolves to the live RDS hostname (an `@aws_db_instance.database.address` pass-through), while `user`/`password` arrive as ECS `secrets[]` sourced from SSM. `api` composes its own connection string from those parts at startup.