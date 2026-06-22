---
stratum: conditional
---

# Overview

This folder `preinfra` contains information for *setting up* and *maintaining* prerequisite infrastructure. All this is outside of project scope and is not part of the mainline doctrine - these are details only to be consulted when they are needed by an operator or LLM agent to work with prerequisite infra.

This directory is not exhaustive. Instructions currently exist for:
1. [The Observability Backend](./telemetry_preinfra.md) - HyperDX.
2. [The Master Network (Fixed)](./fixed_master_network.md) - HAProxy and Docker Networks.
3. [The Master Network (Elastic)](./elastic_master_network.md) - VPC, NAT, Subnets, and IGW.
4. [The Container Registry (Fixed)](./container_registry.md) - Docker Registry V2.

## Install Location

When we install prerequisite infrastructure on an actual machine (whether it be a fixed host or an EC2 instance), preinfra **always** goes in the `/opt/docex-preinfra` folder. This makes it easy to discover what preinfra has been installed on a machine.