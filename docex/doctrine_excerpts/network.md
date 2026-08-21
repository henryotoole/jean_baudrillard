# network

Networks scope which services can reach which others. Each service declares a `networks:` list in `infra.yml`; every service must belong to at least one. The compiler creates one project-scoped network per environment per declared name, formatted `${project_name}-${env_name}-${network_definition_name}` (hyphenated), so environments stay airgapped from one another.

Two foundation realizations:

- **Fixed:** docker networks. Service-to-service communication uses container DNS.
- **Elastic:** AWS security groups **within the shared master VPC** (see `why master_network`). Communication is filtered by SG ingress rules; there is no per-project VPC.

A few network names carry special meaning — see `why web_network` and `why internal_network`. Any other name defaults to closed internal networking.

Doctrine reference: `infrastructure/specifics/networks.md § CICL Interpretation`.
