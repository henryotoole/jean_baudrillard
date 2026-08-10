# network: web

A service declaring `networks: [web, ...]` is reachable from the public internet over HTTP/S.

- **Fixed:** the container gets Traefik discovery labels (`traefik.enable=true`, host rules, TLS entry-point) and joins the `{project}_{env}_web` docker network, which the **project's own** traefik watches (one per project, at the project tier — see `why reverse_proxy`). That traefik routes requests for the env's subdomain to the container.
- **Elastic:** the compiler emits an ALB target group + listener rule pointing at the service. The service's security group accepts ingress only from the ALB's SG; the ALB terminates TLS using the project's ACM cert and forwards inward.

The doctrine reserves `web` as a *special* name precisely so the same `infra.yml` declaration produces the right thing on either foundation without per-foundation knobs.

Doctrine reference: `infrastructure/specifics/networks.md` § `networks: [web]`.
