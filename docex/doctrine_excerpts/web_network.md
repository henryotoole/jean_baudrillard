# network: web

A service declaring `networks: [web, ...]` is reachable from the public internet over HTTP/S.

- **Fixed:** the container gets Traefik discovery labels (`traefik.enable=true`, host rules, TLS entry-point) and joins the `${project}-${env}-web` docker network, which the **project's own** traefik watches (one per project, at the project tier — see `why reverse_proxy`). That traefik routes requests for the env's subdomain to the container.
- **Elastic:** the project's reverse proxy fronts the service — an ALB target group + listener rule, or the EC2-traefik equivalent (see `why reverse_proxy`). The service's security group accepts ingress only from the reverse proxy; TLS terminates there on the project's cert and traffic forwards inward.

The doctrine reserves `web` as a *special* name precisely so the same `infra.yml` declaration produces the right thing on either foundation without per-foundation knobs.

Doctrine reference: `infrastructure/specifics/networks.md § networks: [web]`.
