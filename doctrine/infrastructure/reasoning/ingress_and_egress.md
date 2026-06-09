# Ingress and Egress

## Centralized v Decentralized

All this is primarily driven by the `elastic` case. We can do whatever we want on `fixed` infra. `elastic` imposes rules and costs.

### Centralized Ingress (Why Not)

It would be ideal to centralize ingress. However, aside from the "softer" reasons not to pursue this (like bottleneck risk) there are hard limits to scale:
1. Listener rules - Cap of 100 / ALB. We need one of these per endpoint (service and env) which gets exhausted fast. Even with raising the rule max, we'd only get about 50 projects max.
2. Listener certs - These cap out too, somewhat more harshly. Also limits us.

These restrictions mean that we can't really expect to have one ALB for all projects in an AWS account.

### Decentralized Ingress (Why)

Decentralized ingress dodges the limits of a single ALB. However, it incurs its own costs:
- $70 per year base price
- $10 to $70 for LCU attachment (scales with usage)
- $44 per attached public IP (and two are required to hit the AWS 2-AZ ALB mandate)

Total is *at least* $158/yr. This is low enough to be acceptable for some projects, but unacceptable for others.

The solution is to allow a different resource to plug into the reverse proxy slot - an EC2 instance running traefik. It's not as robust as a real ALB and has some maintenance cost, but it's half the fixed cost (about $90 / yr) and has *no* scaling costs. That's because it *cannot scale*, which may be a problem for some projects. Ultimately which to use is a design decision, and the doctrine provides both routes.

### Centralized Egress (Why)

Decentralized egress is very expensive. It involves giving each project its own NAT, which consumes both an EIP (finite resource) and costs about $400 / yr.

### Decentralized Egress (Why Not)

Decentralized egress is simply too costly. It requires a NAT gateway for each project, which is pretty expensive.

### Decentralized Project Networks

AWS VPC's aren't costly, but connecting them to a Transit Gateway (and then to a NAT) is almost as expensive as a NAT itself. The solution is one big "master network"; a main VPC with a NAT and all projects in its scope.

## Elastic AZ's.

To reduce complexity and costs, we operate with only one AZ. This makes us vulnerable to an outage within an AZ - this is an acceptable price to pay.