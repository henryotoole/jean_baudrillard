# Mod 036 — Fixed Projinfra: Per-Project Traefik + Projinfra Behavior on Fixed

Seventh mod of the [doctrine-shape-and-tier campaign](../../campaigns/shape_overhaul_mod_list.md). Replaces the obsolete "machine-wide traefik" model with the new per-project traefik that joins the four `-web` networks, and wires `projinfra <up|down> <side>` to actually bring those resources up and down on fixed projects.

## The Doctrine Change

From [`projinfra/fixed_reverse_proxy.md`](../../../../doctrine/infrastructure/specifics/projinfra/fixed_reverse_proxy.md) and [`projinfra/overview.md`](../../../../doctrine/infrastructure/specifics/projinfra/overview.md):

**Per-project traefik replaces the machine-wide traefik.** Each project gets one traefik container per side, named `${project}-traefik`, joined to all four `${project}-${env}-web` networks plus the host-wide `docex-ingress` bridge. It terminates TLS via Let's Encrypt (DNS-01 preferred, HTTP-01 fallback), uses cert resolver name `doctrine`, persists certs in a named volume.

**Env-tier services on the `web` network reference the project-tier networks** (`${project}-${env}-web`) as `external: true`, joining whatever traefik instance happens to span them. They no longer own the network.

**`projinfra <direction> <side>` wires up to runtime behavior**: `up <side>` runs `docker compose -f infra/output/project/<side>/docker-compose.yml up -d` and converges. `down <side>` refuses if any env-tier for this project is still up (`projinfra` is the foundation env-tier sits on). Preserves the projinfra named volume on `down` so cert state survives.

## Scope of mod 036 — single-machine fixed only

The doctrine describes three topologies (single-machine fixed, split-machine fixed, elastic) and ansible artifacts at project tier for the split-machine case. Per [`infrastructure.md § Deferred`](../../../../doctrine/infrastructure/infrastructure.md#deferred):

> 1. Multi-machine `fixed` foundation. We will one day support multiple machines, but this will involve docker-swarm and some other complexities. We assume only one machine for now, hosting all environments.

Mod 036 supports **single-machine fixed only**. The ansible artifacts at project tier (`infra/output/project/production/{playbook,inventory,ansible.cfg}.yml`) emitted only when "prod side is a remote host" are part of the deferred multi-machine work. Not emitted in mod 036.

Single-machine fixed means `projinfra up development` and `projinfra up production` converge to the same set of docker resources on the operator's local machine; running either after the other is idempotent.

## Concrete file surface

### Update `emit_project_compose` — add the traefik service

`src/docex/emit/compose.py:emit_project_compose` (added in mod 035) currently emits networks only. Add:

```python
services:
  ${project}-traefik:
    image: traefik:<digest-pinned-via-OTEL_COLLECTOR_IMAGE-style-constant>
    container_name: ${project}-traefik
    restart: unless-stopped
    networks:
      - ${project}-dev-web
      - ${project}-test-web
      - ${project}-stage-web
      - ${project}-prod-web
      - docex-ingress
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - ${project}-traefik-acme:/letsencrypt
    command:
      - --providers.docker=true
      - --providers.docker.exposedbydefault=false
      - --entrypoints.web.address=:80
      - --entrypoints.websecure.address=:443
      - --certificatesresolvers.doctrine.acme.email=${TRAEFIK_ACME_EMAIL:-}
      - --certificatesresolvers.doctrine.acme.storage=/letsencrypt/acme.json
      - --certificatesresolvers.doctrine.acme.dnschallenge=true
      - --certificatesresolvers.doctrine.acme.dnschallenge.provider=${TRAEFIK_DNS_PROVIDER:-}

volumes:
  ${project}-traefik-acme: {}
```

Notes:
- **Image pin**: add a `TRAEFIK_IMAGE` constant in `src/docex/__init__.py` next to `OTEL_COLLECTOR_IMAGE`, pinned by digest. Pick a current LTS traefik tag (e.g. `traefik:v3.3`) and resolve its digest. The doctrine treats this the same way as the OTel sidecar — base-layer drift absorbed at the doctrine layer, not at the project layer.
- **DNS-01 provider and operator email**: the doctrine doesn't specify where these come from. Use compose runtime substitution syntax (`${VAR:-}`) so they're set via operator-supplied env vars (e.g. operator's shell or `.env` file). For the smoke projects and ordinary use, leaving them empty means LE issuance fails but the container starts and routing works. **Real LE issuance config is operator-supplied, not docex-prescribed.** Mark this as a deferred-detail in the doctrine.
- **No host port publishing**: the docex-ingress bridge brings traffic in via the host's HAProxy web demux; traefik doesn't bind 80/443 on the host directly.

### Flip env compose's `_network_section`

`src/docex/emit/compose.py:_network_section` currently emits the `web` short name as a bare external `web` network:

```python
if short == "web":
    out[short] = {"name": "web", "external": True}
```

This is the OLD doctrine (machine-wide traefik on a host-wide `web` bridge). Replace with the new doctrine — `${project}-${env}-web`, `external: true`:

```python
if short == "web":
    out[short] = {
        "name": f"{compiled.project}-{compiled.env}-web",
        "external": True,
    }
```

Non-`web` networks stay project-scoped and `internal: true` (owned by env).

After mod 036, env compose references the projinfra-owned `-web` network by name; projinfra creates and owns it. Running env compose without projinfra up'd first will fail with `network not found` — that's intentional, and the new precondition behavior in `projinfra` enforces it.

### Wire `projinfra <up|down> <side>` for fixed

Edit `src/docex/__main__.py:_cmd_projinfra` (the stub from mod 034). The fixed branch:

- **`up <side>`**: run `docker compose -f infra/output/project/<side>/docker-compose.yml up -d`. Use the existing `DockerClient` interface (extend if needed) — `docker compose up` is a subprocess invocation.
- **`down <side>`**: check whether any env-tier compose for this project is still up; if yes, refuse with a clear error. Otherwise run `docker compose -f infra/output/project/<side>/docker-compose.yml down`. **Do NOT pass `--volumes`** — acme volume should survive.

Elastic on production side stays at the existing `run_bootstrap` for now. Other elastic stubs unchanged.

### Env-tier still-up detection

`projinfra down` refuses if any env for this project is still up. Implementation: `docker compose ls --format json` and filter for compose projects whose name matches the project's expected env-compose-project-name. Or `docker network inspect` each `${project}-${env}-internal` network — if it exists, the env is up.

Either approach works. The implementer should pick the simpler one.

A new method on `DockerClient` may be appropriate, e.g. `list_compose_projects(filter_name_substr) -> list[str]`. Add as needed.

### Single-machine convergence

A single-machine fixed project has `projinfra up development` and `projinfra up production` operate on the same docker daemon. The two compose files are emitted at different paths but declare the same set of networks (`${project}-{dev,test,stage,prod}-web`). When the second `up` runs after the first, docker idempotently observes "network already exists, nothing to do."

The two traefik containers, however, would collide on `container_name: ${project}-traefik`. Same name, two compose files, would fail.

This is a real issue. Two options:
1. **Side-suffix the container name** — `${project}-traefik-development`, `${project}-traefik-production`. But the doctrine specifies `${project}-traefik` (unscoped). And only one traefik per project per host makes sense.
2. **One traefik per host, applied by whichever side comes up first** — when the second side runs, docker sees the container already exists, does nothing. The container's networks list (in compose) needs to be the union of all four `-web` networks regardless of side, which the mod-035 emission already does. ✓

Option 2 matches the doctrine's "one traefik per project per side" — on a single-machine project, dev side and prod side are the same machine, the two sides converge.

But option 2 needs `docker compose up -d` to be idempotent in this specific way. Compose's idempotency contract: if a service is `Running` and its current config matches the file, do nothing. The two side compose files emit identical content (same name, same image, same networks list, same volumes, same command). So compose should see no diff and leave the existing container alone. ✓

To be safe, the implementer should verify this assumption with a quick test: run `up development`, then `up production`, then check that `docker ps` shows exactly one `${project}-traefik` container.

### Tests

- `tests/unit/test_compose_emitter.py`: assertion that env compose's `web` network is now `${project}-${env}-web` with `external: true`.
- `tests/integration/test_compile.py`: assertion that project-tier compose includes the `${project}-traefik` service block with the right networks list, volumes, command flags.
- New `tests/unit/test_pipeline_projinfra.py` (or extend `test_dispatcher.py`): exercises the fixed projinfra-up/down dispatch — mock DockerClient and verify the right `docker compose` commands are issued. The env-still-up refusal also testable here.

## Ramifications

### Compiled-output diff

Every fixed-foundation project's env compose changes shape for the `web` network reference. Every project's project-tier compose grows a `${project}-traefik` service block.

Per campaign-wide deferral, no test-project recompile in this mod.

### Doctrine for cert config

The doctrine specifies the cert resolver name and the DNS-01 challenge type but doesn't specify how operator email + DNS provider config flow. Mod 036 uses compose runtime substitution (`${VAR:-}`) to delegate to operator-supplied env vars. This is a small doctrine gap — flagging it for a future doctrine update.

### `docex-ingress` preinfra

The traefik container joins `docex-ingress` (declared `external: true`). If preinfra isn't set up, `docker compose up` fails with `network docex-ingress not found`. That's the right behavior — preinfra is a precondition. `projinfra up` already refuses when `preinfra <side>` fails per the doctrine, but `preinfra` is still a stub from mod 034 (mod 042 makes it real). For mod 036, the precondition check stays stub-passes-always; the docker-compose-up will fail at the network-attach step if `docex-ingress` is missing. That's actually informative enough.

## Operator Decisions

1. **Traefik image pinned by digest.** Add `TRAEFIK_IMAGE` constant in `src/docex/__init__.py`, pinned per the OTel sidecar convention. Implementer picks a current `v3.x` digest.
2. **Single-machine only.** Skip ansible-at-project-tier artifacts (`playbook.yml`, `inventory.yml`, `ansible.cfg` at project tier). Multi-machine fixed is deferred.
3. **DNS-01 with operator-supplied vars.** Emit DNS-01 config; `${TRAEFIK_ACME_EMAIL:-}` and `${TRAEFIK_DNS_PROVIDER:-}` come from the operator's env. Out-of-box LE issuance fails until operator wires them — that's accepted, aligns with the doctrine's wildcard preference.
4. **No preinfra precondition in mod 036.** `projinfra up` runs `docker compose up` directly; missing `docex-ingress` surfaces as a docker error rather than a pre-flight refusal. Mod 042 wires real preinfra.
5. **Env-still-up detection** — implementer's discretion. Either `docker compose ls` filter or `docker network inspect` works.

## What This Mod Is NOT

- **No elastic projinfra changes** beyond what mod 034 already wired. Mods 037–039 own elastic projinfra.
- **No multi-machine fixed support** — ansible-at-project-tier deferred.
- **No `preinfra` real checks** — mod 042.
- **No EC2-traefik variant** — mod 044.
- **No env-tier release flow changes** — release still runs against the env's compose file, which now joins projinfra-owned networks.
- **No operator-credential management for LE DNS providers** — operator-supplied env vars; doctrine doesn't prescribe storage.
- **No `test_projects/{fixed,elastic}/` edits.**
