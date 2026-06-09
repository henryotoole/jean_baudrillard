# Mod 046 — Naming Policy Leak Residuals

First patch mod after the 1.0.0 cut. Closes a set of residual data-plane naming-leak sites missed by mods 030, 040, and 043: emit paths that interpolate `${project_name}` directly without passing the project segment through a naming policy. Surfaced by the post-1.0.0 test-project re-inception while inspecting `infra/output/` against both foundations.

## Why

[`transfer_tables.md § Naming Policies`](../../../../doctrine/infrastructure/specifics/transfer_tables.md#naming-policies) states the rule unambiguously:

> **Anything name-resolvable on the data plane uses hyphens** — Docker containers/networks/volumes, ECS cluster/service/task-def identifiers, ECS Service Connect names, ALB/target-group names, S3 buckets, RDS identifiers, hostnames.

For a project whose `name:` carries underscores (e.g. `docex_smoke_elastic`), the rendered form everywhere on the data plane must therefore be `docex-smoke-elastic-…`. Mod 030 flipped the `docker` and `ecs` policy separators to `hyphen`; mod 040 fixed the env-tier SG name; mod 043 stood up the Service Connect namespace. **But several emit sites do not actually pass the project segment through the policy machinery** — they format names with `f"{project}-{env}-…"` directly. The joiners are hyphens but the project segment's internal underscores survive into the output.

The current 1.0.0 emit, on a project named `docex_smoke_elastic`, produces:

| Site | What gets emitted | Where doctrine says it should land |
| ---- | ----------------- | ---------------------------------- |
| Env-tier compose `networks.<short>.name` | `docex_smoke_elastic-stage-web` | `docex-smoke-elastic-stage-web` |
| Project-tier compose four `-web` networks `name` | `docex_smoke_elastic-stage-web` etc. | hyphenated |
| Project-tier compose project traefik `container_name` | `docex_smoke_elastic-traefik` | `docex-smoke-elastic-traefik` |
| Project-tier compose ACME volume `name` | `docex_smoke_elastic-traefik-acme` | hyphenated |
| Env-tier compose OTel sidecar `container_name` | `docex_smoke_elastic-stage-web-otelcol` | `docex-smoke-elastic-stage-web-otelcol` |
| Project-tier HCL `aws_route53_zone.project.name` | `docex_smoke_elastic.luxrnd.tech` | `docex-smoke-elastic.luxrnd.tech` |
| Project-tier HCL ACM cert `domain_name` + SANs | `*.stage.docex_smoke_elastic.luxrnd.tech` | hyphenated |
| Env-tier HCL Service Connect namespace `name` | `docex_smoke_elastic-stage` | `docex-smoke-elastic-stage` |

### Severity

- **Blocking on elastic** — the Route53 zone, ACM cert, and Service Connect namespace bugs produce RFC-invalid DNS names (`docex_smoke_elastic.luxrnd.tech`). Route53 rejects underscores in zone names outright; ACM rejects underscores in domain names; Cloud Map private DNS namespaces resolve via Route53 and therefore can't carry underscores. `./bin/docex projinfra up production` cannot succeed on any project whose `name:` carries underscores until this is fixed.
- **Soft-failing on fixed** — the compose-side leaks (networks, traefik, sidecar) work as long as references are internally consistent (env-tier compose references `name: docex_smoke_elastic-stage-web` and the project-tier compose declares the same form, so the two match). The HAProxy `web_demux` preinfra (per [`fixed_master_network.md`](../../../../doctrine/infrastructure/preinfra/fixed_master_network.md)) reconstructs the project traefik's container name from the request domain via `domain.split('.')[-2]`, which produces the DNS-labeled (hyphenated) form. So if HAProxy is configured to follow the doctrine, it will look for `docex-smoke-elastic-traefik` and fail to find the actual `docex_smoke_elastic-traefik`. The leak is a latent correctness bug that surfaces the moment HAProxy follows the doctrine spec.

Both kinds matter for the test-project smoke walk: the post-1.0.0 walk against real AWS cannot start until the elastic bugs are fixed, and the fixed walk can't validate HAProxy demux without the compose-side bugs being fixed.

## Root cause

The bugs share a single shape: emit code interpolates `${project_name}` (the raw value from `project.yml`) directly, rather than first passing it through the relevant naming policy. The compile layer (`_global_service_name`) gets this right — it forms the internal join `{project}_{env}_{svc}` and calls `apply_policy(..., engine_policy)`, which translates *every* underscore in the internal form to a hyphen. Emit sites that compose names piecewise (network names that don't carry an engine, structural container names like the traefik) bypass that path.

The fix in every case is to substitute "the DNS-labeled project segment" — `apply_policy(project, http_host)` or equivalently `project.replace('_', '-').lower()` — for the raw `${project_name}` whenever the result needs to be data-plane resolvable. The doctrine has had a helper for this since mod 031 (`_dns_label` in `compile.py`); the leak is that it isn't applied at every site that needs it.

## What's in scope for mod 046

1. **Compose env-tier emit** (`src/docex/emit/compose.py::_network_section`, `_sidecar_block`, and the sidecar pass at `emit_compose`'s second loop).
2. **Compose project-tier emit** (`src/docex/emit/compose.py::emit_project_compose` — all four network names, the traefik container_name, the ACME volume name, the network attachments list).
3. **HCL project-tier emit** (`src/docex/emit/templates/project.tf.j2` — the Route53 zone name, the two ACM cert `domain_name`s and SAN lists).
4. **HCL env-tier emit** (`src/docex/emit/templates/main.tf.j2` — Service Connect namespace `name`).
5. **Tests** — extend existing fixture-driven snapshot tests so every fixed name above is asserted in its hyphenated form. Use a fixture project whose `name:` contains underscores (most existing fixtures already do — `docex_smoke_elastic` and `myproject_underscored` are common) to ensure the regression surface is real.

## What's not in scope

- **Joiner separator changes.** Mod 030 already settled the joiners (hyphen on data plane, underscore on inert AWS record-key identifiers). Mod 046 doesn't revisit any of that.
- **ECR repo names.** Documented as a structural emit that bypasses the policy table (`${project}/${service}` with underscores preserved within each segment). Mod 030 made this explicit; mod 046 doesn't change it.
- **Inert AWS record-key identifiers** (IAM roles, SSM path segments, DDB tables). These correctly preserve underscores via the `iam` / `ssm_path` / `ddb` policies. Mod 046 doesn't touch them.
- **Container backing-service names that already go through `apply_policy(ecs)`** in `compile.py`. Those are already hyphenated correctly — `docex-smoke-elastic-stage-appdb` etc. The leak is only at sites that don't run through the engine-naming policy path.

## Doctrine alignment

This mod surfaces no doctrine changes — every fix lands docex back in alignment with what the doctrine already says. The doctrine's intent (mod 030's prose, mod 031's `_dns_label`, mod 043's Service Connect spec, mod 040's SG fix) was uniform; the implementation was incomplete. Mod 046 finishes the implementation.

If a future audit surfaces other emit sites with the same shape, the principle stated here is sufficient: "any name that ends up on a data-plane resolvable identifier (Docker network, ECS task definition family, DNS hostname, Service Connect discoveryName, etc.) must derive its project segment from `_dns_label(project)`, not from the raw `project_name`."

## Version implication

Patch cut: docex 1.0.1. Per [`docex_process.md § Lifecycle`](../../core/docex_process.md), patch cuts skip the test-project smoke walk — but in this case the patch is *driven by* the smoke-walk preparation, so the smoke walk has to happen anyway as part of the post-cut work. That's fine; the doctrine doesn't prohibit walking after a patch, it just doesn't *require* it.
