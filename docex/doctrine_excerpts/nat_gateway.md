# nat_gateway

The centralized outbound gateway for the **elastic** master network. **Prerequisite infrastructure**: a single AWS NAT gateway living in the shared master VPC (see `why master_network`) and shared by every project in the account — no project provisions its own.

Egress from any private-subnet resource (ECS tasks, RDS) reaching anything outside the master VPC — third-party APIs, the observability backend, ECR pulls not covered by a VPC endpoint — flows through this one NAT gateway and out via the master VPC's Internet Gateway. Inbound traffic does not use it; that arrives via the project's reverse proxy.

This is an elastic-only resource. On a fixed foundation, outbound access is handled by the host's Docker-managed `iptables` NAT and there is no distinct gateway resource.

Doctrine reference: `infrastructure/specifics/networks.md § Egress`; `infrastructure/preinfra/elastic_master_network.md § Resources`.
