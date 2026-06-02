# Telemetry Infrastructure Maintenance

This document goes over the standards and practices needed by the LLM agent or operator to setup and maintain the prerequisite portion of doctrine-prescribed telemetry infrastructure. This is entirely out of the scope of a specific project.

The only prerequisite infrastructure component is the [observability backend](TODO). This can either be self-hosted or a paid, managed cloud service. This guide is only concerned with the self-hosted version as the cloud service is maintained by a third party.

## Setup

The shape of the self-hosted HyperDX is pretty similar whether on fixed or common. The main difference is whether HyperDX is built on an EC2 instance or a `fixed` server.

`fixed`: A dedicated directory is chosen on the main fixed server. The HyperDX directory is cloned into it and run as a stack of containers with docker-compose. It ties into the machine-wide traefik instance, which handles SSL termination and routing. Data is stored onto mounted volumes.

`elastic`: An EC2 instance with sufficient performance is requisitioned and exposed to the internet with an Elastic IP. The HyperDX directory is cloned into it and run as a stack of containers with docker-compose. A traefik compose container is setup to handle SSL termination and routing. Data is stored onto mounted volumes, which themselves are backed by EBS storage.

### Common

Configuration of the docker-compose stack is identical across both foundations.
TODO Setup max size possible in storage

#### HyperDX Installation

TODO Config to be reachable from machine traefik
TODO Setup max size possible in storage

#### DNS

The base domain used for HyperDX will depend on both *what* and *which* infrastructure foundation is used. Elastic-foundation projects that share a single AWS account will all use the same HyperDX instance and domain. However, this doctrine is used for many projects across many different AWS accounts. The base domain used for the instance will depend on this operating circumstance and can not be deterministically chosen in advance. Always ask the operator what base domain to use when setting this up.

We can, however, specify that all HyperDX traffic go through a consistent *subdomain*: `hyperdx`.

Therefore, the actual domain at which HyperDX will be accessed is: `hyperdx.${base_domain}`

### Fixed

The following describes how to setup HyperDX in fixed-foundation projects.

1. Choose Base Directory
- For the HyperDX instance to live in. Default is `~/preinfra/hyperdx`.

2. Route DNS

Determine the appropriate records to route `hyperdx.${base_domain}` to the fixed machine's IP, and then ask the operator to add those records to the domain registrar's DNS.

3. Setup HyperDX

Follow the [common instructions](#hyperdx-installation).

4. Test Reachability

TODO


### Elastic

The following describes how to setup HyperDX for elastic-foundation projects.

1. Double check that there's not already an EC2 instance setup that does this. The easiest way is to check for infrastructure components with the tag `prerequisite-infrastructure-telemetry`. If a HyperDX instance has already been setup, don't create a redundant duplicate! Alert the operator and await instruction.

2. Requisition the server

An EC2 instance (4GB RAM or more: `t3a.medium`) is needed with the current stable release of Ubuntu Server and an elastic IP assigned to it. The instance should be setup to be accessed via SSH so that developers have terminal access. Docker and Docker Compose shall be installed on it.

The instance should be backed with 100GB of general purpose EBS storage. Currently this is `gp3` on AWS.

Total costs will be about $35/mo (at time of writing).

The instance and EBS volume should both be tagged with `prerequisite-infrastructure-telemetry`.

3. Route DNS

Use Route53 to route `hyperdx.${base_domain}` to the EC2 instance.

4. Setup Traefik

Make a directory at `~/traefik`. Install traefik.
TODO include further details when we come up with them.
Ports needed:
UI + API 8080
OTEL HTTP 4318
OTEL gRPC 4317

5. Setup HyperDX

Follow the [common instructions](#hyperdx-installation).

6. Test Reachability

TODO