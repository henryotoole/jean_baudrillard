# reverse_proxy

The doctrine handles HTTP/S ingress asymmetrically across foundations because the natural primitive on each is different.

- **Fixed: Traefik.** One traefik **per project**, at the project tier — brought up by `docex projinfra up development` and named `${project_dns_label}-traefik` — sitting behind a single host-wide HAProxy `web_demux` that reads the request domain and forwards to the right project's traefik over the shared `docex-ingress` network. (Preinfra services that are not projects — the container registry and the observability backend — run their own dedicated traefiks.) Per-project rather than host-wide is what gives blast-radius protection: one project cannot misconfigure another's routing. Each traefik watches the docker socket, auto-discovers containers carrying the doctrinal `traefik.enable=true` labels, and routes each env's subdomain to the right container. TLS terminates at the project's traefik via Let's Encrypt (see `why cert_manager`), so each project owns its own certs.

- **Elastic: AWS ALB.** One ALB per environment in the env's public subnets, listening on 443 with the project's ACM cert. Doctrine-provisioned (not declared in `infra.yml`) — `docex compile` emits the ALB when any service declares `networks: [web, ...]`. Doubles as a load balancer for replicated core services in `prod`.

The two answer the same question — "how do requests reach the right container?" — using the primitives each foundation already offers natively, rather than forcing a single cross-foundation abstraction.

Doctrine reference: `infrastructure/shape.md`; `infrastructure/specifics/networks.md`.
