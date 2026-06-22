# vpc

The project's private network space on elastic foundation. **Project-tier infrastructure** — one VPC per project, shared across `stage` and `prod` environments. (The `dev` and `test` environments are always fixed and do not use the VPC.)

The VPC contains:

- A `/16` CIDR (e.g. `10.0.0.0/16`).
- An Internet Gateway and one NAT Gateway per AZ for outbound from private subnets.
- Per-env subnets: `${project}_${env}_public_a`, `_public_b`, `_private_a`, `_private_b`. Public subnets host the ALB; private subnets host ECS tasks and RDS.
- Per-env security groups (one per network name declared in `infra.yml`), all within this VPC.

Subnet/SG layout is doctrine-derived; `infra.yml` does not control it. See `infrastructure/shape.md § Elastic-Foundation` for the full topology.
