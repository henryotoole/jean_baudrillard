# cert_manager

TLS certificate provisioning and rotation.

- **Fixed:** built into the machine-wide traefik. Traefik talks Let's Encrypt ACME, fetches certs lazily as new subdomains appear in its router config, and renews them on its own schedule. Zero project-side configuration.
- **Elastic:** AWS ACM, a project-tier resource. One wildcard cert (`*.<domain>`) covers every env's ALB listener. ACM handles renewal automatically.

Both paths satisfy the doctrinal guarantee that no project ever embeds a private key in its repo or worries about cert expiry as an operational concern.

Doctrine reference: `infrastructure/shape2.md`.
