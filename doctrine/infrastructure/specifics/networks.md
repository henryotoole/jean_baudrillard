# Networks

This file goes over the exact nature of networks on `fixed` v `elastic` foundations. This is not intended to be force-loaded with doctrine context; these details get encoded into the compiler. It exists rather as documentation, both for the compiler or the developer who wishes to know more.

## CICL Interpretation

The *number* of networks needed is inferred from `infra.yml` simply by looking at what the services request. The *configuration* of those networks is inferred entirely from the name. Certain network names carry literal meaning:
**Special Network Names**
1. `web` - A service on the `web` network is reachable from the public internet over HTTP/S.

Any network not given a special name simply defaults to an `internal` network.

## Compiler Implementation

This section defines the implementation means the compiler will choose for networks for a given name and foundation.

### Network Definition Name vs. Compiled Name
Networks are given short, meaningful names in the `infra.yml` file like `web`, `internal`, etc. However, the compiler must actually create four different networks per `infra.yml`-defined network name: one for each environment. This ensures our environments stay airgapped.

Therefore, the compiled name must be interpolated to ensure scope-uniqueness. The format is always `compiled_name = ${project}_${env}_${network_definition_name}`, whether it applies to a docker network name or an AWS SG.

**Exception: fixed-foundation `web`.** When compiling fixed-foundation output, the network named `web` compiles to a bare external network named `web` rather than `${project}_${env}_web`. This is the single shared public-routing plane that the machine-wide [reverse_proxy] attaches to; project-scoping it would force per-project reverse-proxy instances. See [`Implementation by Name § networks: [web]`](#networks-web) for the rationale. The exception applies only to fixed-foundation Docker networks — `web` in elastic-foundation output still compiles to a per-env, per-project security group named `${project}_${env}_web` for clarity in the AWS console.

### Implementation by Name

#### `networks: [web]`

A service on the `web` network is reachable from the public internet over HTTP/S, at the [per-service subdomain(s)](../cicl.md#per-service-subdomains) derived from its name — `${service}.${env}.${domain}`, plus the bare `${env}.${domain}` for the `domain_default_service`. Routing is **network-driven**: any service on `web`, regardless of role, is routed; the compiler generates the routing config from network membership, not from the service's role. The `reverse_proxy` role is the one exception — it *is* the edge router, not a routed target.

`web`-network services **do not publish host ports**. The reverse proxy reaches them over the project network on their declared `port`, so there's nothing to bind on the host. (This is why a `web` service may use any port — including 80 — and why two web services never collide.)

- **Fixed:** the container gets Traefik discovery labels (`traefik.enable=true`, a `Host(…)` router rule covering the service's subdomain(s), `loadbalancer.server.port=<port>`, `tls.certresolver=doctrine`, etc.) and joins the bare external `web` docker network, which the machine-wide Traefik is also attached to. Traefik terminates TLS — using the resolver named `doctrine`, which the operator configures with DNS-01 against Let's Encrypt (HTTP-01 cannot issue the per-env wildcard certs this scheme requires) — and routes each subdomain to the container over the network. The `web` network is shared across all fixed-foundation projects on the host: it is the public-routing plane, and service-level authentication is the right defense against cross-tenant exposure on it.
- **Elastic:** the (core) service is registered as an ALB target group with a listener rule matching its subdomain(s) at a unique priority. The env's ALB listens on 443 (and 80, redirecting), terminates TLS using the project's ACM cert, and forwards to the task. The service's security group accepts ingress only from the ALB's security group. Managed backing services (RDS, S3, ElastiCache) on `web` are not ALB targets — they're reached at their own AWS endpoints; their `web` membership affects only the security group.

#### `networks: [internal]` (DEFAULT FOR ALL NON-SPECIAL-NAMED NETWORKS)

A service on a non-`web` network is reachable only from other services on the same network.

- **Fixed:** the container joins the `{project}_{env}_{network}` docker network. Other containers on the same network reach it by container name, which equals `${global_service_name}`. Docker enforces network isolation.
- **Elastic:** the service is attached to the `{project}_{env}_{network}` security group. That SG accepts ingress only from itself — i.e., from other services attached to the same SG.

#### Egress

Every project-emitted SG on the elastic foundation carries an allow-all egress rule (`0.0.0.0/0`, all ports, all protocols). This matches the AWS-side default for a freshly-created SG; Terraform's `aws_security_group` resource otherwise denies egress when no `egress` block is specified, which would prevent Fargate tasks from reaching SSM, ECR, and other AWS service endpoints they need to start.

Constraining egress per network — restricting traffic to specific AWS service endpoints or to other project SGs — is deferred. See [infrastructure.md § Deferred](../infrastructure.md#deferred) rule 6.