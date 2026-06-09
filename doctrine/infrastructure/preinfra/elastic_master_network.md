# Elastic Master Network

On elastic, we are going to switch to the widely used "centralized egress" model for AWS. We will also be moving away from the per-project VPC model - instead, there will be one "master" VPC which all projects, the NAT gateway, and main IGW live within. Project network space subdivisions will still be handled by security groups analogous to the new per-project networks described below for `fixed`.

To be clear, the order of nesting goes something like this, for a project with `web` and `internal` networks:

## Master VPC

The elastic master network takes the form of one big VPC which contains all projects, an IGW, NAT for egress, and four standard subnets.

Note that two AZ's are required per AWS mandate for ALB's and RDS deploys. The below structure two subnets per AZ, and two AZ's, but the secondary AZ's are effectively unused. See [this](../reasoning/ingress_and_egress.md#elastic-azs) for reasoning.

1. Master VPC
	1. IGW
	2. "public" Subnet (AZ 1), routes 0.0.0.0/0 to IGW
		2. NAT
		3. Per-project ALB (or EC2 self-hosting traefik)
	3. "private" Subnet (AZ 1), routes 0.0.0.0/0 to NAT in public subnet AZ 1
		1. SG for `web`
			1. `web`-network services
		2. SG for `internal`
			1. `internal`-network services.
	4. "public" subnet (AZ 2), routes 0.0.0.0/0 to IGW
		- Nothing in here
	5. "private" subnet (AZ 2), routes 0.0.0.0/0 to NAT in public subnet AZ 1
		- Nothing in here

NOTE: SG's live at the VPC level; the diagram shows where the *services* attached to those SGs run.

EGRESS: We'll have one IGW and NAT. Outbound signals get address translated in NAT, and pass to internet thru IGW.

INGRESS: Will not be centralized. Instead, signals will be routed via Route53 down to the relevant "reverse proxy". There will be one reverse proxy / load balancer / TLS terminator per project, which will either be an ALB or EC2 instance performing the same role (more on that later).

TODO Add more once this has been done for the first time.