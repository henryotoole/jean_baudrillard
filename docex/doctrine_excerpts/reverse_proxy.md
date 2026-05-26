# reverse_proxy

The doctrine handles HTTP/S ingress asymmetrically across foundations because the natural primitive on each is different.

- **Fixed: Traefik.** Exactly one traefik instance per host machine — *not* one per project. Traefik watches the docker socket, auto-discovers containers carrying the doctrinal `traefik.enable=true` labels, and routes each env's subdomain to the right container. TLS terminates here via Let's Encrypt (see `why cert_manager`). Treating traefik as host-wide prerequisite infrastructure rather than per-project keeps fixed setups simple: one traefik, one cert manager, however many projects.

- **Elastic: AWS ALB.** One ALB per environment in the env's public subnets, listening on 443 with the project's ACM cert. Doctrine-provisioned (not declared in `infra.yml`) — `docex compile` emits the ALB when any service declares `networks: [web, ...]`. Doubles as a load balancer for replicated core services in `prod`.

The two answer the same question — "how do requests reach the right container?" — using the primitives each foundation already offers natively, rather than forcing a single cross-foundation abstraction.

Doctrine reference: `infrastructure/shape2.md`; `infrastructure/specifics/networks.md`.
