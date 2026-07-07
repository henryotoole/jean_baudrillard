---
name: infra-compile
description: Doctrine for authoring a project's infra.yml and the transfer tables that compile it into per-foundation infrastructure. Use this whenever you are writing or changing infra.yml, adding a service/role/engine, or extending docex with a project-local transfer table for an engine it doesn't ship — and whenever reasoning about how CICL compiles to docker-compose or OpenTofu, even if you never name CICL or transfer tables.
metadata:
  type: thread
---

# infra-compile

Designing infrastructure means writing CICL (`infra.yml`) against the shape you are targeting, then understanding how the transfer tables compile it; read the language and the shape first, and descend into the compilation tables when you need the mechanism.

## General Information

What you are authoring and what it compiles toward. **Read these now.**

[`cicl.md`](../../doctrine/infrastructure/cicl.md) — the CICL format: services, fields, magic refs, networks, domains, and validation rules. The language `infra.yml` is written in.

[`shape.md`](../../doctrine/infrastructure/shape.md) — the fixed and elastic infrastructure shapes your `infra.yml` resolves into; the topology you are designing toward.

## Specific Information

How the compiler turns CICL into provider-ready output. **Read on demand.**

[`transfer_tables.md`](../../doctrine/infrastructure/specifics/transfer_tables.md) — how each role/engine compiles per foundation: substitution grammar, naming policies, provides/env/fields, and resources translation. Read when adding an engine, writing project-local tables, or debugging a compile.

[`networks.md`](../../doctrine/infrastructure/specifics/networks.md) — how a service's `networks:` list becomes docker attachment (fixed) or security-group membership (elastic). Shared with `network-design`.

[`scheduler.md`](../../doctrine/infrastructure/specifics/scheduler.md) — the `scheduler` role: 5-field cron authoring, per-foundation translation (Ofelia on fixed, EventBridge Scheduler → ECS `RunTask` on elastic), and env/secret delivery to one-off jobs. Read when adding a cron-style scheduled service.

## Thread

- Writing project-local transfer tables (the former `docex-transfer-table` activity, now folded here) goes in `infra/transfer_tables/`.
- The network plane in depth — *why* ingress/egress is shaped as it is — is `network-design`; come here to *author* a service's networks, go there to *design* the plane.
- Compiled output is consumed downstream by `cicd-pipeline` (containerize/release) and realized by `preinfra-setup` and `projinfra-setup`, the infra tiers around the services.
