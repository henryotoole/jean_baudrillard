# Overview

This folder `preinfra` contains information for *setting up* and *maintaining* prerequisite infrastructure. All this is outside of project scope and is not part of the mainline doctrine - these are details only to be consulted when the are needed by an operator or LLM agent to work with prerequisite infra.

This directory is not exhaustive. Instructions currently exist for:
1. [The Observability Backend](./telemetry_preinfra.md) - HyperDX.
2. [The Master Network (Fixed)](./fixed_master_network.md) - HAProxy and Docker Networks.
3. [The Master Network (Elastic)](./elastic_master_network.md) - VPC, NAT, Subnets, and IGW.
4. [The Container Registry (Fixed)](./container_registry.md) - Docker Registry V2.