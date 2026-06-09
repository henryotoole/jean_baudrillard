# Networks

This file describes **env-tier per-service network attachment** — which docker networks a container joins on fixed, which security groups a service joins on elastic, and how the `internal` default behaves. It is intentionally narrow: the project-tier `-web` network surface (and the reverse proxy that spans those networks) lives in [`projinfra/`](./projinfra/overview.md); the master networks live in [`preinfra/`](../preinfra/overview.md).

This is documentation for the implementer of `docex` and the curious developer; it is not meant to be force-loaded as general doctrine context.

## Where Each Network Tier Lives

| Tier | Resource | Documented in |
| ---- | -------- | ------------- |
| Preinfra | The master network (`docex-ingress` bridge on fixed; master VPC on elastic) | [preinfra/fixed_master_network.md](../preinfra/fixed_master_network.md), [preinfra/elastic_master_network.md](../preinfra/elastic_master_network.md) |
| Projinfra | The four per-project `-web` networks; the per-project reverse proxy that spans them | [projinfra/fixed_reverse_proxy.md](./projinfra/fixed_reverse_proxy.md), [projinfra/elastic_alb.md](./projinfra/elastic_alb.md), [projinfra/ec2_traefik.md](./projinfra/ec2_traefik.md) |
| Envinfra | Per-env `internal` (and any other non-`web`) networks; per-service network attachment | This file |

This file is concerned with the third row. Per-service network attachment is what the compiler decides on the basis of each service's `networks:` list in `infra.yml`.

## CICL Interpretation

The *number* of non-`web` networks needed is inferred from `infra.yml` simply by looking at what the services request. The *configuration* of those networks is inferred entirely from the name. Certain network names carry literal meaning:

**Special Network Names**
1. `web` — A service on the `web` network is reachable from the public internet over HTTP/S. The `-web` networks themselves are project-tier; only the per-service attachment to them is env-tier.

Any network not given a special name simply defaults to an `internal` network.

## Compiled Names

Networks are given short, meaningful names in `infra.yml` like `web`, `internal`, etc. The compiler scopes those names by project and env on both foundations:

```
${project_name}-${env_name}-${network_definition_name}
```

The same form applies whether the underlying resource is a Docker network (fixed) or an AWS security group (elastic). There are no special exceptions — `web` compiles to `${project}-${env}-web` just like any other network.

## Per-Service Attachment by Name

### `networks: [web]`

A service on the `web` network is reachable from the public internet over HTTP/S, at the [domain](../cicl.md#domain) derived from its name, env, and project. Routing is **network-driven**: any service on `web`, regardless of role, is routed; the compiler generates the routing config from network membership, not from the service's role.

`web`-network services **do not publish host ports**. The project's reverse proxy reaches them over the project network on their declared `port`, so there's nothing to bind on the host. (This is why a `web` service may use any port — including 80 — and why two web services never collide.)

- **Fixed:** the container gets Traefik discovery labels (`traefik.enable=true`, a `Host(…)` router rule covering the service's domain, `loadbalancer.server.port=<port>`, `tls.certresolver=doctrine`, etc.) and joins the project-tier `${project}-${env}-web` docker network (declared `external: true` in the env's compose file). The project traefik, already running and spanning every `-web` network, picks up the labels and routes accordingly. See [`projinfra/fixed_reverse_proxy.md`](./projinfra/fixed_reverse_proxy.md).

- **Elastic (ALB):** the (core) service is registered as an ALB target group with a listener rule matching its domain at a unique priority. The project's ALB (project-tier) handles TLS termination using the ACM certs; the env-tier rules direct traffic to env-tier target groups. The service is attached to the `${project}-${env}-web` security group within the master VPC; that SG accepts ingress only from the ALB's security group (looked up via project remote state). See [`projinfra/elastic_alb.md`](./projinfra/elastic_alb.md).

- **Elastic (EC2-traefik):** when the project declares `reverse_proxy: ec2_traefik_eip` or `ec2_traefik_pip`, the routing surface changes — the EC2 instance running traefik replaces the ALB and ACM certs. The env-tier ingress source on the `${project}-${env}-web` SG becomes the project's `<project>-traefik` SG instead of the ALB SG. The SG-membership rule for `web`-tagged services is otherwise unchanged. See [`projinfra/ec2_traefik.md`](./projinfra/ec2_traefik.md).

Managed backing services (RDS, S3, ElastiCache) on `web` are not ALB targets — they're reached at their own AWS endpoints; their `web` membership affects only the security group.

### `networks: [internal]` (and any other non-special name)

A service on a non-`web` network is reachable only from other services on the same network. These networks are **env-tier** — declared inside each env's compiled output, torn up and down with the env. The doctrine has no notion of a per-project shared `internal` network; if two services need to talk, they declare the same network name in the same env.

- **Fixed:** the container joins the `${project}-${env}-${network}` docker network, declared inside the env's compose file (not `external: true` — owned by the env). Other containers on the same network reach it by container name, which equals `${global_service_name}`. Docker enforces network isolation.
- **Elastic:** the service is attached to the `${project}-${env}-${network}` security group within the master VPC. That SG accepts ingress only from itself — i.e., from other services attached to the same SG. Cross-project isolation in the shared master VPC is enforced exclusively at the SG layer; there is no L3 subnet boundary between projects.

## Egress

- **Fixed:** outbound requests leave each container via Docker's normal `iptables`-managed NAT through the host's default route. Nothing project-specific or doctrine-emitted is involved.

- **Elastic:** every project-emitted SG carries an allow-all egress rule (`0.0.0.0/0`, all ports, all protocols). This matches the AWS-side default for a freshly-created SG; Terraform's `aws_security_group` resource otherwise denies egress when no `egress` block is specified, which would prevent Fargate tasks from reaching SSM, ECR, and other AWS service endpoints they need to start. Outbound packets then flow from the private subnet through the master VPC's centralized NAT gateway and out via the IGW — both prerequisite resources shared across every project in the AWS account.

  Constraining egress per network — restricting traffic to specific AWS service endpoints or to other project SGs — is deferred. See [infrastructure.md § Deferred](../infrastructure.md#deferred).
