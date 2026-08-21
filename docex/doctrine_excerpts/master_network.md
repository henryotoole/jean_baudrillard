# master_network

The shared ingress/egress network that ties together every project on an infrastructure side. It is **prerequisite infrastructure** — stood up once per machine or account, outside any single project's control — and shared by all projects.

- **Fixed:** a docker bridge network always named `docex-ingress`. The host-wide `web_demux` (see `why web_demux`) and every project's own traefik (see `why reverse_proxy`) attach to it, so the demux can forward a request to the right project's traefik over this shared network.
- **Elastic:** a master **VPC** shared by all projects in the AWS account. It contains a centralized Internet Gateway, a centralized NAT gateway (see `why nat_gateway`), and four subnets — a public/private pair in the default AZ and a redundant public/private pair in a second AZ (present only to satisfy AWS's two-AZ requirement). Per-project and per-env resources (reverse proxies, SGs, ECS tasks, RDS) are placed *inside* this shared VPC rather than in a per-project VPC.

Because it is shared, no project's compiled output creates it; project and env HCL reference it by name via data sources.

Doctrine reference: `infrastructure/preinfra/fixed_master_network.md § The docex-ingress Network`; `infrastructure/preinfra/elastic_master_network.md § Resources`.
