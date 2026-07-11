# Mod 090 — Scope the ansible release compose project name

## Problem

The fixed-foundation release playbook brings up stage/prod stacks with an
**unscoped** Compose project name. The three compose invocations in
`emit/templates/playbook.yml.j2` all derive their project name from the host
deploy dir basename (`/opt/<project>/<env>` → `<env>`):

- "Pull all images" (`community.docker.docker_compose_v2`, `project_src`)
- "Bring up the stack" (`docker_compose_v2`, `project_src`)
- "Run migrations" (raw `docker compose run --rm`, `chdir`)

So every fixed project's prod stack is Compose-project `prod` and stage is
`stage` — **not project-scoped**. Two fixed projects on one host collide. This is
the same bug class mod 053 fixed for docex's *own* compose calls
(`env_compose_project` → `<dns_label>-<env>`); the ansible path was missed.

Surfaced by the 1.5.0 pre-cut fixed smoke walk (a single project, so it didn't
break the walk). Rolled into 1.5.0 at the operator's request.

## Design

Emit an explicit, project-scoped Compose project name — `<dns_label>-<env>`,
identical to docex's native `env_compose_project` convention — on all three
invocations:

- `emit/ansible.py` passes `compose_project_name = f"{compiled.project_dns_label}-{compiled.env}"`
  into the playbook render context.
- The two `docker_compose_v2` tasks gain `project_name: "{{ compose_project_name }}"`.
- The migrate `docker compose run` gains `-p {{ compose_project_name }}` so the
  one-off joins the *same* project's network as the stack (they must stay
  consistent, else migrate can't reach the DB).

All three must use the identical name (they do — one context var).

## Upgrade impact (load-bearing)

On an **existing** fixed deployment already running a `<env>`-named stack, the
first 1.5.0 release renames the Compose project to `<dns_label>-<env>`. Because
the compose file sets explicit `container_name`s (side-independent), the new
project's `up` would **collide** on the existing container names (same failure
shape as mod 087's traefik conflict) — not silently orphan. So the first 1.5.0
fixed release requires a one-time manual step: tear the old-named stack down
first. Documented in `upgrades/upgrade_1.5.0.md`. (dev/test are unaffected — they
were already `<dns_label>-<env>` via `docex up`.)

## Artifact alignment

- **Doctrine**: no change (the doctrine never specified the unscoped name; this
  aligns the emit with mod 053's scoping intent).
- **src** (`emit/ansible.py`) + **template** (`playbook.yml.j2`) + **tests**
  (`test_ansible_emitter.py`) + **upgrade guide** (`upgrade_1.5.0.md`).

## Non-goals

- No change to dev/test naming or docex's own compose calls (already scoped).
- No auto-teardown of the old stack in the playbook — the rename is a one-time
  upgrade action, handled by the guide (consistent with doctrine practice).
