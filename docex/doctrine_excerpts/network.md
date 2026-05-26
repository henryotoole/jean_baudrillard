# network

Networks scope which services can reach which others. Each service declares a `networks:` list in `infra.yml`; every service must belong to at least one. The compiler creates one project-scoped network per environment per declared name, formatted as `${project}_${env}_${name}`, so environments stay airgapped from each other.

Two foundation realizations:

- **Fixed:** docker networks. Service-to-service communication uses container DNS.
- **Elastic:** AWS security groups within the project VPC. Communication is filtered by SG ingress rules.

A few network names carry special meaning — see `why network_web` and `why network_internal`. Any other name defaults to closed internal networking.

Doctrine reference: `infrastructure/specifics/networks.md`.
