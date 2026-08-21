# reverse_proxy

The doctrine handles HTTP/S ingress asymmetrically across foundations because the natural primitive on each is different.

- **Fixed: Traefik.** One traefik **per project**, at the project tier — brought up by `docex projinfra up development` and named `${project_dns_label}-traefik` — sitting behind a single host-wide HAProxy `web_demux` (see `why web_demux`) that reads the request domain and forwards to the right project's traefik over the shared `docex-ingress` network. (Preinfra services that are not projects — the container registry and the observability backend — run their own dedicated traefiks.) Per-project rather than host-wide is what gives blast-radius protection: one project cannot misconfigure another's routing. Each traefik watches the docker socket, auto-discovers containers carrying the doctrinal `traefik.enable=true` labels, and routes each env's subdomain to the right container. TLS terminates at the project's traefik via Let's Encrypt (see `why cert_manager`), so each project owns its own certs.

- **Elastic: AWS ALB or EC2-with-traefik.** Each project gets its **own** reverse proxy, chosen in `infra.yml` via `reverse_proxy:` (`alb`, `ec2_traefik_eip`, or `ec2_traefik_pip` — elastic only). It lives in the shared master VPC (see `why master_network`). **One reverse proxy per project serves both `stage` and `prod`** via host-based listener rules — not one per environment. An ALB terminates TLS with the project's ACM certs; an EC2-traefik instance uses built-in Let's Encrypt (see `why cert_manager`). Either doubles as the load balancer for a replicated `web` core service in `prod`; internal core services are balanced by service discovery instead. Doctrine-provisioned — not declared as a service in `infra.yml`.

The two answer the same question — "how do requests reach the right container?" — using the primitives each foundation already offers natively, rather than forcing a single cross-foundation abstraction.

Doctrine reference: `infrastructure/shape.md § Elastic-Foundation`; `infrastructure/cicl.md § Reverse Proxy`.
