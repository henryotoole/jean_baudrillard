# cert_manager

TLS certificate provisioning and rotation.

- **Fixed:** built into the project's own traefik (one per project, at the project tier — see `why reverse_proxy`), so each project owns its certs. Traefik uses Let's Encrypt over **HTTP-01**, issuing one cert per `web`-network service per env, fetched lazily as new subdomains appear in its router config and renewed on its own schedule. Zero project-side configuration.
- **Elastic:** a project-tier resource whose mechanism follows the chosen `reverse_proxy`. With an **ALB**, TLS terminates on AWS **ACM** certs; with **`ec2_traefik`**, on traefik's built-in Let's Encrypt. Both use **DNS-01** and provision **two** certs per project — a `stage` cert (`*.stage.<project>.<apex>`, `stage.<project>.<apex>`) and a distinct `prod` cert (`*.prod.<project>.<apex>`, `prod.<project>.<apex>`, `<project>.<apex>`) — keeping production airgapped from staging. Renewal is automatic.

Both paths satisfy the doctrinal guarantee that no project embeds a private key in its repo or treats cert expiry as an operational concern.

Doctrine reference: `infrastructure/cicl.md § Elastic TLS`; `infrastructure/cicl.md § Fixed TLS`.
