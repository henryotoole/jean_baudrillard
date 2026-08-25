---
stratum: conditional
---

# Fixed Reverse Proxy (Per-Project Traefik)

This file describes the per-project Traefik container — the project-tier reverse proxy for any side that uses docker-compose to host envs. That covers:

1. **All fixed-foundation projects** on both the development and production sides.
2. **Elastic-foundation projects on the development side** — dev/test are always fixed-style per [shape.md § Shape and Environment](../../shape.md#shape-and-environment), so the dev machine of an elastic project hosts a fixed-style project traefik alongside its dev/test envs.

This is documentation for the implementer of `docex` and the curious developer; it is not meant to be force-loaded as general doctrine context.

## Role

A single traefik container per project, per side, performs three roles together:

1. **TLS terminator.** Inbound 443 traffic is decrypted using certs issued by the container's built-in Let's Encrypt client. This is the project's only TLS termination point on the docker side — the upstream [`web_demux`](../../preinfra/fixed_master_network.md) HAProxy intentionally does SNI pass-through without decrypting.
2. **Reverse proxy.** Decrypted requests are routed by hostname (the per-service domain or one of the bare-env / bare-project forms — see [cicl.md § Domain](../../cicl.md#domain)) to the appropriate env-tier core service container.
3. **Load balancer.** When `prod` has multiple replica containers for the same service, traefik balances across them by container name resolution within the relevant `-web` network.

It is **project-tier**, not env-tier: one container per project per side, shared across every env that lives on that side. It must exist before any of the project's envs can serve traffic.

## Resources

A complete fixed-side projinfra set, on either side, consists of:

| Resource | Form | Name |
| -------- | ---- | ---- |
| Project traefik container | docker container | `${project_name}-traefik` |
| Dev-env web network | external docker bridge network | `${project_name}-dev-web` |
| Stage-env web network | external docker bridge network | `${project_name}-stage-web` |
| Prod-env web network | external docker bridge network | `${project_name}-prod-web` |

The traefik container joins **all three** `-web` networks plus the host-wide `docex-ingress` bridge from [preinfra](../../preinfra/fixed_master_network.md). All three `-web` networks are always present on every side, even on sides where some envs will never run — see [projinfra.md § Why all three `-web` networks live on every side](./projinfra.md#why-all-three--web-networks-live-on-every-side).

There is deliberately **no `test`-env web network here.** The `test` env is never TLS'd or routed through traefik ([mod 054](../../cicl.md#tls-implications)), so as of mod 153 its `web` network is **env-tier, not projinfra**: a plain, non-external, per-slot docker bridge the env's own `compose.yml` creates and tears down (`${project_name}-test${slot_seg}-web`), exactly like the `internal` network. This removes `test`'s last projinfra dependency — `docex test` runs without `projinfra up`. See [networks.md](../networks.md) and [projinfra.md § Why all three `-web` networks live on every side](./projinfra.md#why-all-three--web-networks-live-on-every-side).

The three `-web` networks are declared `external: true` in each env's `compose.yml` so that env-tier services can join them without ownership ambiguity — projinfra owns the network lifecycle; env compose files merely attach. (The `test` env is the exception per the note above: it owns its own web bridge.)

## Compiled Output

`./bin/docex compile` emits:

```
infra/output/project/development/
  docker-compose.yml        # 3 -web networks + project traefik

infra/output/project/production/
  docker-compose.yml        # 3 -web networks + project traefik (or HCL on elastic prod)
  playbook.yml              # only when prod side is a remote host
  inventory.yml             # only when prod side is a remote host
  ansible.cfg               # only when prod side is a remote host
```

The same `docker-compose.yml` shape is used for both sides on a fixed project — only the application target differs (local docker daemon for `development`, the remote host for `production`).

Both sides' compose files are emitted on every project, regardless of foundation. An elastic-foundation project still produces `infra/output/project/development/docker-compose.yml` for the operator's dev machine; only the `production/` artifact differs (HCL instead of compose). See [`elastic_alb.md`](./elastic_alb.md) and [`ec2_traefik.md`](./ec2_traefik.md) for the elastic production-side reverse-proxy resources.

### `docker-compose.yml` shape

The emitted compose file declares the three external networks and the traefik service. Illustrative shape (actual emit lives in `src/docex/emit/compose.py`):

```yml
networks:
  ${project_name}-dev-web:
    name: ${project_name}-dev-web
  ${project_name}-stage-web:
    name: ${project_name}-stage-web
  ${project_name}-prod-web:
    name: ${project_name}-prod-web
  docex-ingress:
    external: true   # owned by preinfra

services:
  ${project_name}-traefik:
    image: traefik:<digest>
    container_name: ${project_name}-traefik
    restart: unless-stopped
    networks:
      - ${project_name}-dev-web
      - ${project_name}-stage-web
      - ${project_name}-prod-web
      - docex-ingress
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - ${project_name}-traefik-acme:/letsencrypt
    command:
      - --providers.docker=true
      - --providers.docker.exposedbydefault=false
      - --providers.docker.constraints=Label(`docex.project`,`${project_name}`)
      - --entrypoints.web.address=:80
      - --entrypoints.websecure.address=:443
      - --certificatesresolvers.doctrine.acme.email=...
      - --certificatesresolvers.doctrine.acme.storage=/letsencrypt/acme.json
      - --certificatesresolvers.doctrine.acme.httpchallenge=true
      - --certificatesresolvers.doctrine.acme.httpchallenge.entrypoint=web
    labels: ...    # see Cert resolver name handling below

volumes:
  ${project_name}-traefik-acme: {}
```

The traefik container itself listens only inside docker (no published host ports) — the upstream `web_demux` HAProxy reaches it via the `docex-ingress` bridge, selecting it by container name reconstructed from the request's domain per [preinfra/fixed_master_network.md](../../preinfra/fixed_master_network.md).

## TLS and Cert Handling

Traefik's built-in Let's Encrypt client issues and renews certs via the ACME **HTTP-01** challenge: when a router for a new service hostname appears, traefik obtains a **per-host** cert by serving the challenge token on its `:80` (`web`) entrypoint, which the upstream HAProxy web demux forwards by Host header. **No DNS-provider credentials are required** — this is what keeps the fixed cert path provider-agnostic (it works with any registrar/DNS). The cost relative to wildcards is one cert per service hostname rather than one per env; at the doctrine's scale this is immaterial (LE limits are per registered domain per week, well clear of a typical project's host count), and per-host certs preserve dev↔prod cert airgapping for free — separate hostnames yield separate certs.

Each `web`-network core service gets its own cert keyed to its domain (`<codebase>-<service>.<env>.<project>.<apex_domain>`), plus the bare-env (and, in prod, bare-project) host certs for the `domain_default_service` — see [cicl.md § Fixed TLS](../../cicl.md#fixed-tls). The `test` env is the exception: its web services are not routed by traefik and get no certs (per [cicl.md § TLS Implications](../../cicl.md#tls-implications), `test` is not accessed over TLS), so `docex` emits no traefik discovery labels for them. On a fixed-foundation project, the single per-project traefik issues all such certs across `dev`/`stage`/`prod`. On an elastic-foundation project, the dev-side traefik issues only the `dev` certs; `stage` and `prod` terminate TLS at the ACM-backed elastic reverse proxy (see [cicl.md § Elastic TLS](../../cicl.md#elastic-tls)).

### Cert resolver name

The resolver is always named `doctrine` — a fixed handle that `docex` references in the per-service traefik discovery labels emitted alongside each env-tier service. The container is configured with that exact name; service labels include `traefik.http.routers.<svc>.tls.certresolver=doctrine`. See [transfer_tables.md § Per-container (fixed)](../transfer_tables.md#per-container-fixed) for the label set.

Decoupling the *handle* (`doctrine`) from the *implementation* (LE + HTTP-01) lets the doctrine evolve the underlying mechanism without changing what env-tier compose files emit.

### Cert persistence across restarts

The traefik container mounts a named docker volume `${project_name}-traefik-acme` at `/letsencrypt`. The volume holds traefik's `acme.json` (cert material + LE account key) and survives container restarts, image upgrades, and `./bin/docex projinfra down/up <side>` cycles. The volume is declared in the projinfra compose file, not in any env's compose file — it belongs to the project, not the env.

LE rate limits (notably the per-registered-domain weekly cert limit, plus a duplicate-certificate limit on identical reissues) are generous relative to a typical project's host count; they only bite if the volume itself is destroyed and every per-host cert is reissued from scratch within a week. `./bin/docex projinfra down <side>` does *not* destroy named volumes by default; the operator must `docker volume rm ${project_name}-traefik-acme` explicitly if they want to start cert state fresh.

## How Env-Tier Services Get Routed

The compiled env-tier `compose.yml` files emit each `web`-network core service with traefik discovery labels (see [transfer_tables.md § Per-container (fixed)](../transfer_tables.md#per-container-fixed)) and have the service join the matching `${project}-${env}-web` external network. The project traefik, which already spans every `-web` network, picks the labels up via its docker provider and adds a router for the service. No manual routing config; no per-env traefik config file.

The docker provider is **constrained to this project**: the traefik command carries `--providers.docker.constraints=Label(\`docex.project\`,\`${project_name}\`)`, and `docex` stamps a matching `docex.project=${project_name}` label on **every** container it emits (env-tier core and backing services, their OTel sidecars, and the traefik container itself). Without the constraint, the project traefik's docker provider would also see *other* projects' containers sharing the host-wide `docex-ingress` bridge — registering routers it can't reach and spamming ACME failures for foreign hosts on every reconcile. The constraint scopes the provider to this project's own labelled containers; routing remains internally identical, and the cross-project log noise disappears.

Because traefik joins every `-web` network even on sides where the corresponding env won't run, a side change (e.g., moving the prod host to a new machine, or splitting a single-machine project into two machines) requires no reconfiguration of the traefik container — only that the relevant env starts running on the new side.

## Lifecycle

The project traefik comes up with `./bin/docex projinfra up <side>` and stays up across env-tier deploys. `./bin/docex envinfra up <env>` and `./bin/docex release <env>` do *not* touch the traefik container — they bring env-tier services into existing `-web` networks, where traefik's docker provider notices them and routes accordingly.

When the operator runs `./bin/docex projinfra down <side>`:
- The traefik container is stopped and removed.
- The three `-web` networks are removed (they're owned by the projinfra compose file, declared with no external owner). The `test` env's web bridge is *not* among them — it is env-tier and comes down with the `test` stack (mod 153).
- The `${project_name}-traefik-acme` named volume is **preserved** by default (docker compose's default behavior; the volume is not part of the `down` action unless `--volumes` is passed).

Projinfra refuses to run `down` if any env-tier infra is still attached to its networks — see [projinfra.md § `./bin/docex projinfra <direction> <side>`](./projinfra.md#bindocex-projinfra-direction-side).

## Failure Modes

| Symptom | Probable cause | Where to look |
| ------- | -------------- | ------------- |
| 502/504 from clients, traefik logs show "no available servers" | Env-tier service is down or not on the expected `-web` network | `docker compose ps` on the env stack; confirm the service joined `${project}-${env}-web` |
| Cert issuance fails | HTTP-01 challenge can't complete — port 80 not reaching this traefik via the web_demux, or DNS for the service host not yet pointing at the host machine | `docker logs ${project}-traefik`; check the LE resolver config and that HAProxy is forwarding `:80` Host-header traffic for the service domain to this traefik |
| New routes not appearing | Env-tier service compose labels malformed or container not running | `docker compose ps`; inspect labels with `docker inspect <container>` |
| LE rate limit hit | acme volume was destroyed and certs reissued multiple times in a week | `docker volume inspect ${project}-traefik-acme` to confirm volume identity; check LE rate-limit page for the specific limit hit |
| Traefik container won't start | Misconfigured command-line args or missing acme volume | `docker logs ${project}-traefik`; the rendered compose file is in `infra/output/project/<side>/` |

## What's Projinfra-Created vs. Envinfra-Created

The split between project-tier and env-tier emissions on fixed:

**Projinfra (`infra/output/project/<side>/docker-compose.yml`):**
- The three `-web` external networks (`dev`/`stage`/`prod`; the `test` env's web network is env-tier per mod 153)
- The project traefik container with its acme volume and LE resolver config
- Reference (`external: true`) to the preinfra `docex-ingress` bridge

**Envinfra (`infra/output/<env>/docker-compose.yml`):**
- The env's `internal` (and any other non-`web`) networks — **and, in the `test` env only, its own non-external `web` bridge** (`${project}-test${slot_seg}-web`, mod 153)
- Per-service core and backing containers, with traefik discovery labels on `web`-network services (except `test`, which is not routed)
- `external: true` references to the projinfra-owned `-web` networks (in `dev`/`stage`/`prod`; `test`'s web network is owned by this file, not projinfra)

A reader looking at any one compose file can tell at a glance who owns what: networks declared without `external: true` are owned by that file; networks declared with `external: true` were created by something further up the tier hierarchy.
