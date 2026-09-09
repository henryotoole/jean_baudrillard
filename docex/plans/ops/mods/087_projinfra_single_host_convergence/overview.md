# Mod 087 — Fixed projinfra single-host convergence

## Problem

On a single-machine fixed project (dev box also hosts prod), the doctrine
requires the two projinfra sides to **converge**:

> **Single-machine fixed.** One machine hosts every env. Dev side and prod side
> are the same physical thing. `projinfra up development` and `projinfra up
> production` converge on the same docker-resource set; running either is
> idempotent with the other.
> — `doctrine/infrastructure/specifics/projinfra/projinfra.md` §35, restated §96

The implementation violates this. `docex projinfra up production` after `up
development` fails:

```
Container docex-smoke-fixed-traefik  Error ... Conflict. The container name
"/docex-smoke-fixed-traefik" is already in use by container ...
error: `docker compose up` failed with exit code 1
```

Surfaced by the 1.5.0 pre-cut fixed smoke walk (PRE_CUT_CHECKLIST C.1).

## Root cause

`pipeline/projinfra.py::_project_compose_project` returns a **per-side** Compose
project name — `${dns_label(project)}-projinfra-${side}`. But the project-tier
compose file declares a **side-independent** traefik `container_name`
(`<project>-traefik`) and ACME volume (`<project>-traefik-acme`). On a single
docker daemon, the second `up` runs under a *different* Compose project
(`-projinfra-production`) and cannot adopt resources owned by the first
(`-projinfra-development`), so it collides on the shared container name. The
`run_projinfra_fixed_up` docstring already *claims* the second up is a "no-op" —
that claim is false as implemented.

Introduced by mod 053 (which correctly replaced the fragile path-derived
Compose name `infra` with an explicit `--project-name`, but chose a per-side
suffix). Pre-existing and orthogonal to envmageddon; folded into the 1.5.0 cut
because the pre-cut smoke walk cannot go green until it is fixed.

## Design

Make the fixed project-tier Compose project name **side-independent**:
`${dns_label(project)}-projinfra`.

- Preserves mod 053's actual fix (an explicit, stable, project-scoped name — not
  the path-derived `infra` that leaked the four `-web` networks on `down`).
- Restores single-host convergence: `up production` after `up development` runs
  under the same Compose project against an identical compose file, so Compose
  adopts the existing resources and reconciles to a genuine no-op.
- Split-machine fixed is unaffected: the two sides are distinct docker daemons,
  each independently owning the one `${dns_label}-projinfra` project.
- `down` is symmetric: both sides target the same name, so on a single host
  either `down` removes the one converged stack (idempotent); on split machines
  each daemon removes its own.

No behavior change is needed anywhere else — the elastic projinfra path uses a
different mechanism, and env-tier stacks keep their existing `${dns_label}-<env>`
names.

## Doctrine / artifact alignment

- **Doctrine** (`projinfra.md`) already states the correct *behavior*
  (converge, idempotent). No doctrine wording change is required.
- **docex core doc** (`plans/core/masterplan.md`, DooD §4) currently cites the
  project-tier name as `<project_dns_label>-projinfra-<side>` — update to the
  side-independent form and note *why* (single-host convergence).
- **src** + **tests** as below.

## Non-goals

- No change to env-tier compose naming.
- No change to elastic projinfra.
- No attempt to model split-machine host detection — the shared name is correct
  for both topologies without detection.
