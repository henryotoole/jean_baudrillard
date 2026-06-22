---
name: network-design
description: Doctrine for designing and justifying a project's network plane — ingress, egress, web vs. internal networks, and the master-network topology on fixed and elastic. Use this whenever you are deciding network membership, reasoning about reachability or egress, or justifying the ingress topology — even without the word "network".
metadata:
  type: thread
---

# network-design

The network plane is best understood rationale-first: why the topology is shaped this way, then how a service's networks compile; read the reasoning and the picture, and descend into the compilation detail when wiring a specific service.

## General Information

Why the network topology is the way it is. **Read these now.**

[`ingress_and_egress.md`](../../doctrine/infrastructure/reasoning/ingress_and_egress.md) — the rationale: decentralized ingress, centralized egress and NAT, single-AZ, and the cost and service-limit tradeoffs behind those choices.

[`ing.md`](../../doctrine/charts/ing.md) — the elastic ingress/egress diagram: master VPC, IGW and NAT, per-project reverse proxies, and per-env/per-project security groups.

## Specific Information

How `networks:` compiles to attachment. **Read on demand.**

[`networks.md`](../../doctrine/infrastructure/specifics/networks.md) — per-service network attachment: docker networks (fixed) vs. security groups (elastic), `web` routing, and egress defaults. Shared with `infra-compile`.

## Thread

- Authoring the `networks:` field on a service is `infra-compile`; this skill is for *designing and justifying* the plane.
- The network *resources* live in the infra tiers: the master network is `preinfra-setup`; the reverse proxy (ALB, EC2-traefik, or project traefik) is `projinfra-setup`.
