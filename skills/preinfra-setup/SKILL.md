---
name: preinfra-setup
description: Doctrine for setting up and debugging prerequisite infrastructure — the master network (HAProxy demux and docex-ingress on fixed, the master VPC on elastic), the container registry, and the observability backend. Use this whenever you are standing up, verifying, or debugging preinfra for a project, even if the word "preinfra" is never used.
metadata:
  type: thread
---

# preinfra-setup

Prerequisite infrastructure exists outside any single project and must be in place before project-tier infra; read the index, then the per-resource file for what you are setting up — they split by foundation.

## General Information

What preinfra exists and the install layout. **Read this now.**

[`overview.md`](../../doctrine/infrastructure/preinfra/overview.md) — the index of prerequisite-infrastructure resources and the canonical install location; routes to the per-resource files below.

## Specific Information

The per-resource setup procedures. **Read the one(s) you are setting up.**

[`fixed_master_network.md`](../../doctrine/infrastructure/preinfra/fixed_master_network.md) — the fixed-host master network: the HAProxy `web_demux` and the `docex-ingress` bridge.

[`elastic_master_network.md`](../../doctrine/infrastructure/preinfra/elastic_master_network.md) — the shared elastic master VPC: IGW, NAT, subnets, route tables, and the tags docex depends on.

[`container_registry.md`](../../doctrine/infrastructure/preinfra/container_registry.md) — the self-hosted Docker Registry V2 for fixed-foundation projects.

[`telemetry_preinfra.md`](../../doctrine/infrastructure/preinfra/telemetry_preinfra.md) — standing up the self-hosted HyperDX observability backend.

## Thread

- Preinfra is checked before the project tier comes up (`docex projinfra up` refuses if `docex preinfra` fails) — once it is green, continue in `projinfra-setup`.
- The observability backend here is the *destination* for the telemetry designed in `telemetry-design`; the master network is the plane reasoned about in `network-design`.
- Checks and creation run via `./bin/docex preinfra` / `projinfra` — the command reference is [`docex.md`](../../doctrine/infrastructure/docex.md).
