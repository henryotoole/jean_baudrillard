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

### Implementation by Name

#### `networks: [web]`

A service on the `web` network is reachable from the public internet over HTTP/S.

- **Fixed:** the container gets Traefik discovery labels (`traefik.enable=true`, `traefik.http.routers.{service}.rule=Host(…)`, etc.) and joins the `{project}_{env}_web` docker network, which Traefik watches. Traefik routes requests for the env's subdomain to the container.
- **Elastic:** the service is registered as an ALB target group. The env's ALB listens on 443 (and 80, redirecting), terminates TLS using the project's ACM cert, and forwards to the service. The service's security group accepts ingress only from the ALB's security group.

#### `networks: [internal]` (DEFAULT FOR ALL NON-SPECIAL-NAMED NETWORKS)

A service on a non-`web` network is reachable only from other services on the same network.

- **Fixed:** the container joins the `{project}_{env}_{network}` docker network. Other containers on the same network reach it by container name, which equals `${global_service_name}`. Docker enforces network isolation.
- **Elastic:** the service is attached to the `{project}_{env}_{network}` security group. That SG accepts ingress only from itself — i.e., from other services attached to the same SG.