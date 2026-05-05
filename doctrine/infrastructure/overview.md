# Infrastructure Overview

This file describes all infrastructure at a very high level. This guide also assumes that AWS as the cloud provider.

## Structure

Infrastructure describes the machine(s) and services that are required for a project's code to actually run. The infrastructure needed for a given project will range in complexity. The goal of this doctrine is to prescribe a general framework into which all projects will fit.

There are three "Tiers" of infrastructure, ranging from low to high complexity:

| Tier | Name | Backing Services | HTTP Routing | DNS | Infrastructure management |
| ---- | ---- | ---------------- | ------------ | --- | ------------------------- |
| 1 | Single Server | All run by docker-compose. | Traefik | Registrar managed | docker-compose |
| 2 | Vertical Scaling | Some or all are outsourced to cloud. | Traefik | AWS managed | docker-compose + terraform |
| 3 | Horizontal Scaling | All cloud or dedicated ECS containers | ALB + Route53 | docker-compose (for dev) + terraform (prod) |

The following topics are the same no matter which tier of infrastructure is chosen:
1. **Git-tracked config** - Whether via docker or terraform, infrastructure configuration should always be git tracked.
2. **Versioning and Release** - All methods use the same [version control](./version_control.md) and [release patterns](./releases.md).
3. **Dockerized Application Code** - All methods fundamentally use Docker to containerize application code.
4. **Docker Compose Architecture** - All methods will use and maintain good [docker compose architecture](./docker_architecture.md). Some aspects of the compose stack may end up unused in higher tiers (like `prod` and traefik) but the bulk will still be needed for development and testing in all tiers.

Notably, [deployment](./deployment.md) is NOT the same across infrastructure stacks.

Right now **only Tier 1** is actually finished in the doctrine. Tier 2 and Tier 3 are somewhat incomplete.

### Tier 1 
[Further Info](./stacks/t1_single_server.md)
The single-server infrastructure stack is the simplest possible stack. All code and backing services run in a docker-compose project stack on one, singular machine. This machine might be a physical computer or a virtual machine (like an EC2 instance or Digital Ocean droplet), but no services outside of the machine and its docker-compose stack are used. 

Tier 1 is the most flexible infrastructure stack. It can run with or without a cloud service on almost any machine.

All HTTP routing (and HTTPS certs) are handled by a traefik container running on the machine. DNS is routed manually via the registrar.

### Tier 2
[Further Info](./stacks/t2_vertical_scaling.md)
Tier 2 opens the door to cloud-type services but does not break the idea of a single, "central" instance that fundamentally can only scale vertically. Some or all of the backing services are outsourced to the cloud - S3 is used instead of minio; an RDS server might be used instead of postgres. Services outside of the central instance must be configured with terraform, but that configuration should be pretty simple.

HTTP routing is still done with traefik, but the cloud provider's backing services won't be tied into the traefik networks.

The catch of Tier 2 is that it can only scale vertically. The non-outsourced docker stack runs on an EC2 instance. This instance can be scaled larger, but can not be split out into multiple instances.

### Tier 3
[Further Info](./stacks/t3_horizontal_scaling.md)
Tier 3 is full cloud scalability with infrastructure as code. There is no single "central" instance. Application (or core service) containers (like "backend") are hosted across ECS behind a load balancer (ALB). All backing service are cloud services - S3 instead of minio; a dedicated redis instance, etc. Keeping these services coordinated requires infrastructure-as-code, which will be terraform. Docker-compose is still used to run things in development, but in production all is governed by terraform.

HTTP routing is done with Route53, the ALB, and cloudfront.

Tier 3 is the most complex, but can truly scale horizontally.