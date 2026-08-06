---
stratum: conditional
---

# Container Registry

For `fixed`-foundation projects, the [doctrine](../shape.md#fixed-foundation) commits to a self-hosted container registry as prerequisite infrastructure. One registry instance serves every `fixed` project on the host: each project's `infra.yml` simply points its `container_registry` field at the registry's URL, and the `containerize` step pushes images to a project-namespaced path within it.

`elastic`-foundation projects do not use this preinfra — they use AWS ECR, which is project-tier infra provisioned by [`./bin/docex projinfra up production`](../specifics/projinfra/elastic_ecr.md). This document covers only the `fixed` case.

## Design

We run an upstream [Docker Registry V2](https://distribution.github.io/distribution/) image as a single docker container on the host machine. It is accessed at `registry.${base_domain}`, where `${base_domain}` is whatever domain the operator has chosen for hosting preinfra on this host (the same `${base_domain}` HyperDX uses, when both live on the same machine).

The registry is treated as its own "project" per [fixed_master_network.md § Adding Preinfra To Machine](./fixed_master_network.md#adding-preinfra-to-machine) — it gets a dedicated `traefik` container that joins both the registry's internal network and `docex-ingress`. The host's HAProxy `web_demux` routes inbound 443/80 traffic to that traefik by SNI/Host header on `registry.${base_domain}`; the traefik terminates TLS and forwards the request to the registry container in cleartext.

Key choices:

1. **Auth: htpasswd basic auth.** Single shared credential, written to a bcrypt htpasswd file on the host and mounted into the registry container. Operators that need to push or pull must run `docker login registry.${base_domain}` from their machine, which writes the credential into that machine's `~/.docker/config.json` (per [credentials.md § Fixed Container Registry](../credentials.md#fixed-container-registry)). Token-based auth was considered and rejected as overkill for the doctrine's solo-operator assumption.
2. **Storage: local volume on the host.** Image blobs land in a docker-named volume mounted at the registry's standard storage path (`/var/lib/registry`). Backups are the operator's responsibility and follow whatever scheme they use for the host. S3 storage was considered and rejected — it would drag AWS credentials into what's meant to be a self-contained `fixed` host.
3. **No retention policy.** Every image version pushed to the registry is kept indefinitely so [`./bin/docex rollback`](../cicd.md#rollback) can always resolve an old version. The registry grows unboundedly with version count; the operator runs [garbage collection](#garbage-collection) manually if and when host disk pressure demands it.

   Deletion is nonetheless **enabled** (`REGISTRY_STORAGE_DELETE_ENABLED: "true"`). The two are independent: the registry expires nothing on its own, but an operator — or a project's `teardown.sh` — must be able to delete a manifest when it asks to. Without the flag every `DELETE /v2/<repo>/manifests/<digest>` returns `405 Method Not Allowed` and [§ Garbage Collection](#garbage-collection)'s first phase is impossible.
4. **HTTP-only inside the container.** TLS is terminated at the dedicated traefik; the registry itself listens on plain HTTP on its internal network. Identical to the HyperDX pattern.

## Implementation

The registry lives under `/opt/docex-preinfra/container_registry` on the host machine. Two compose stacks side by side: a dedicated `traefik` (subdirectory `traefik/`) and the `registry` container itself (subdirectory `registry/`). Both compose stacks share an external docker network `container_registry-internal` so the traefik can reach the registry; the traefik additionally joins `docex-ingress` so HAProxy can reach the traefik.

Layout:

```
/opt/docex-preinfra/container_registry
├── traefik
│   ├── docker-compose.yml
│   ├── traefik.yml
│   └── acme.json            # touched empty, chmod 600
└── registry
    ├── docker-compose.yml
    └── auth
        └── htpasswd         # generated with htpasswd -B
```

### Dedicated traefik

The traefik is structurally identical to HyperDX's dedicated traefik on `fixed` ([telemetry_preinfra.md § Fixed](./telemetry_preinfra.md#fixed) step 4) — it does NOT bind host ports (HAProxy owns 80/443), joins `docex-ingress` and the registry's internal network, and uses ACME HTTP-01 against the canonical `doctrine` cert resolver.

`/opt/docex-preinfra/container_registry/traefik/docker-compose.yml`:

```yaml
services:
  traefik:
    image: traefik:v3
    container_name: registry-traefik
    restart: unless-stopped
    # No host port bindings — HAProxy web_demux owns 80/443 on the host
    # and reaches this traefik over docex-ingress by SNI/Host header.
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - ./acme.json:/acme.json
      - ./traefik.yml:/etc/traefik/traefik.yml:ro
    networks:
      - docex-ingress
      - container_registry-internal

networks:
  docex-ingress:
    external: true
  container_registry-internal:
    external: true
```

The container is named `registry-traefik` to match the `${project_name}-traefik` scheme HAProxy expects when it parses `registry.${base_domain}` into project name `registry` (per [fixed_master_network.md](./fixed_master_network.md#the-web_demux-resource)). The name is what makes `web_demux` routing work without per-project configuration.

`/opt/docex-preinfra/container_registry/traefik/traefik.yml`:

```yaml
entryPoints:
  web:
    address: ":80"
    http:
      redirections:
        entryPoint:
          to: websecure
          scheme: https
  websecure:
    address: ":443"

providers:
  docker:
    exposedByDefault: false
    network: container_registry-internal

certificatesResolvers:
  doctrine:
    acme:
      email: <operator email>
      storage: /acme.json
      httpChallenge:
        entryPoint: web
```

### Registry container

`/opt/docex-preinfra/container_registry/registry/docker-compose.yml`:

```yaml
services:
  registry:
    image: registry:2
    container_name: registry
    restart: unless-stopped
    volumes:
      - registry_data:/var/lib/registry
      - ./auth:/auth:ro
    environment:
      REGISTRY_AUTH: htpasswd
      REGISTRY_AUTH_HTPASSWD_REALM: "Registry"
      REGISTRY_AUTH_HTPASSWD_PATH: /auth/htpasswd
      # Tells the registry to issue redirect Location headers with the
      # external HTTPS host instead of its container-internal hostname,
      # so docker clients follow blob redirects to the right place.
      REGISTRY_HTTP_HOST: https://registry.${BASE_DOMAIN}
      # Required. The registry refuses manifest DELETE with 405 unless
      # deletion is explicitly enabled; § Garbage Collection's first phase
      # and every project's teardown depend on it. Enabling deletion does
      # NOT make the registry delete anything on its own — the no-retention
      # choice below is unaffected.
      REGISTRY_STORAGE_DELETE_ENABLED: "true"
    labels:
      - "traefik.enable=true"
      - "traefik.docker.network=container_registry-internal"
      - "traefik.http.routers.registry.rule=Host(`registry.${BASE_DOMAIN}`)"
      - "traefik.http.routers.registry.entrypoints=websecure"
      - "traefik.http.routers.registry.tls=true"
      - "traefik.http.routers.registry.tls.certresolver=doctrine"
      - "traefik.http.services.registry.loadbalancer.server.port=5000"
    networks:
      - container_registry-internal

volumes:
  registry_data:

networks:
  container_registry-internal:
    external: true
```

Notes:

- `${BASE_DOMAIN}` is supplied via a sibling `.env` file (or shell environment) so the same compose file is operator-portable.
- `REGISTRY_HTTP_HOST` is critical when traefik terminates TLS in front of the registry. Without it, the registry generates blob-redirect `Location` headers from the request's internal `Host`, breaking `docker pull` and `docker push` for layered images. With it set to the external HTTPS URL, redirects route correctly back through traefik.
- `REGISTRY_STORAGE_DELETE_ENABLED` is **not optional**. It is what makes `DELETE /v2/<repo>/manifests/<digest>` return `202 Accepted` instead of `405 Method Not Allowed`. Every `fixed` project's `teardown.sh` deletes its own registry tags at retirement, and [§ Garbage Collection](#garbage-collection)'s first phase cannot start without it. It is a *capability*, not a policy: the registry still expires nothing by itself (see [§ Design](#design) key choice 3). [§ Verifying Reachability](#verifying-reachability) step 4 proves it.
- The volume `registry_data` is a docker-managed named volume. Its on-disk path resolves under `/var/lib/docker/volumes/`; back this up however the host backs up docker volumes.

### htpasswd

The auth file is created on the host with `htpasswd -B` (bcrypt) from `apache2-utils` (or via a one-shot docker run, see [Setup](#setup-instructions) below). One username/password pair is sufficient — every machine that needs registry access uses the same credential.

## Setup Instructions

The procedure assumes the host already has the [fixed master network](./fixed_master_network.md) preinfra in place (HAProxy `web_demux` and the `docex-ingress` bridge network).

1. **Confirm host preinfra is in place.** The host's HAProxy `web_demux` and the `docex-ingress` bridge network must already exist. If not, set them up first per [fixed_master_network.md](./fixed_master_network.md).

2. **Choose the base domain.** Decide on the `${base_domain}` under which preinfra is hosted on this machine. The registry will be reachable at `registry.${base_domain}`. If HyperDX already runs on this host, reuse the same `${base_domain}`.

3. **Route DNS.** Add an `A` record for `registry.${base_domain}` pointing at the host machine's public IP. Ask the operator to add it at the domain registrar's DNS console.

4. **Create the directory layout.**

   ```bash
   mkdir -p /opt/docex-preinfra/container_registry/traefik
   mkdir -p /opt/docex-preinfra/container_registry/registry/auth
   ```

5. **Create the shared internal network.**

   ```bash
   docker network create container_registry-internal
   ```

   `docex-ingress` is preinfra and already exists — do not recreate it.

6. **Set up the dedicated traefik.**

   1. Write `/opt/docex-preinfra/container_registry/traefik/docker-compose.yml` and `traefik.yml` per [Implementation § Dedicated traefik](#dedicated-traefik). Substitute the operator's email into `traefik.yml`.

   2. Create an empty `acme.json` with restricted permissions:

      ```bash
      touch /opt/docex-preinfra/container_registry/traefik/acme.json
      chmod 600 /opt/docex-preinfra/container_registry/traefik/acme.json
      ```

      Traefik refuses to write certificate data to a file with looser permissions.

   3. Bring up traefik:

      ```bash
      cd /opt/docex-preinfra/container_registry/traefik && docker compose up -d
      ```

      `docker logs registry-traefik` will be empty immediately after start — `traefik:v3` produces no stdout at the default INFO level until requests arrive. Confirm health via `docker ps` (status `Up`) rather than by waiting for log output.

   4. Verify traefik is reachable via HAProxy:

      ```bash
      curl -I http://registry.${base_domain}
      ```

      Expect `308 Permanent Redirect` to `https://registry.${base_domain}/`. A connection error means DNS hasn't propagated, HAProxy isn't routing here, or traefik didn't start.

7. **Generate the htpasswd file.** Pick a username and a strong random password (e.g. `openssl rand -base64 32`). Then:

   ```bash
   docker run --rm --entrypoint htpasswd httpd:2 -Bbn <username> '<password>' \
     > /opt/docex-preinfra/container_registry/registry/auth/htpasswd
   ```

   `-B` selects bcrypt. The registry image accepts bcrypt only; older `md5`/`crypt` formats produce an authentication failure that is not obvious from the error message. Record the username and password somewhere safe — they need to be available to every operator who pushes or pulls against this registry.

8. **Set up the registry.**

   1. Write `/opt/docex-preinfra/container_registry/registry/docker-compose.yml` per [Implementation § Registry container](#registry-container).

   2. Create `/opt/docex-preinfra/container_registry/registry/.env` with the base domain:

      ```
      BASE_DOMAIN=<base_domain>
      ```

   3. Bring up the registry:

      ```bash
      cd /opt/docex-preinfra/container_registry/registry && docker compose up -d
      ```

9. **Test reachability.** Follow [Verifying Reachability](#verifying-reachability) below.

10. **Distribute credentials.** Run [Adding Registry Credentials to a Machine](#adding-registry-credentials-to-a-machine) on the development machine and on every `stage`/`prod` host that will pull from this registry.

11. **Wire projects to the registry.** Each `fixed`-foundation project's `infra.yml` needs `container_registry: registry.${base_domain}` (no protocol scheme — the doctrine treats this as a host). The next `./bin/docex compile` picks it up.

## Verifying Reachability

After the stack is up, verify end-to-end reachability before declaring setup complete.

1. **Unauthenticated request → 401.** A bare `GET` against the v2 API should return `401 Unauthorized` (proves TLS, traefik routing, and the registry are all live; just no credentials supplied):

   ```bash
   curl -I https://registry.${base_domain}/v2/
   ```

   Expect `HTTP/2 401` with a `Www-Authenticate: Basic realm="Registry"` header. A connection error or TLS error indicates DNS, HAProxy, traefik, or ACME problems — bisect by curling the HTTP endpoint (which should still 308) and inspecting traefik's logs for ACME failures.

2. **Authenticated request → 200.** With credentials, the same endpoint returns success:

   ```bash
   curl -I -u '<username>:<password>' https://registry.${base_domain}/v2/
   ```

   Expect `HTTP/2 200`. `401` here means the htpasswd file was generated with the wrong hash format (re-do step 7 of [Setup Instructions](#setup-instructions) with `-B`).

3. **Round-trip push and pull.** From a development machine that has [credentials installed](#adding-registry-credentials-to-a-machine):

   ```bash
   docker pull hello-world
   docker tag hello-world registry.${base_domain}/preinfra-smoke/hello:0.0.1
   docker push registry.${base_domain}/preinfra-smoke/hello:0.0.1
   docker rmi registry.${base_domain}/preinfra-smoke/hello:0.0.1
   docker pull registry.${base_domain}/preinfra-smoke/hello:0.0.1
   ```

   Successful push and pull confirms blob upload, redirects (via `REGISTRY_HTTP_HOST`), and auth all work. A push that hangs partway through layers is almost always a missing or wrong `REGISTRY_HTTP_HOST`; a `denied` response is an auth problem.

4. **Manifest deletion → 202.** Resolve the throwaway tag to a digest and delete it:

   ```bash
   digest="$(curl -fsSI -u '<username>:<password>' \
       -H 'Accept: application/vnd.oci.image.index.v1+json' \
       -H 'Accept: application/vnd.docker.distribution.manifest.v2+json' \
       https://registry.${base_domain}/v2/preinfra-smoke/hello/manifests/0.0.1 \
     | awk -F': ' 'tolower($1)=="docker-content-digest" {gsub(/\r/,"",$2); print $2}')"
   curl -fsS -o /dev/null -w '%{http_code}\n' -u '<username>:<password>' \
     -X DELETE "https://registry.${base_domain}/v2/preinfra-smoke/hello/manifests/${digest}"
   ```

   Expect `202`. A `405` means `REGISTRY_STORAGE_DELETE_ENABLED` is missing. An empty `digest` means the `Accept` headers did not cover the manifest type actually pushed — buildx pushes an OCI **index**, so `manifest.v2+json` alone resolves nothing.

   This step also **cleans up** the `preinfra-smoke/hello` tag that step 3 leaves behind, which otherwise sits in the registry catalog forever.

Step 4 is what turns the delete requirement from prose into something the setup walk actually *proves*. Its absence is how a machine-wide misconfiguration survived several releases: no project could delete a registry tag, every `fixed` teardown leaked one per release, and the leak was invisible because the cleanup checks downstream of it could not tell a `405` from a clean registry.

If all four pass, the registry is ready for use by `fixed`-foundation projects.

## Adding Registry Credentials to a Machine

Every machine that pushes or pulls against the registry needs the credential in its `~/.docker/config.json`. The development machine writes images via `./bin/docex containerize`; production hosts pull them via the ansible release playbook. The mechanism is the same:

```bash
docker login registry.${base_domain}
# Username: <username>
# Password: <password>
```

`docker login` writes the credential into `~/.docker/config.json` on that machine, encoded as base64. The credential persists until `docker logout registry.${base_domain}` is run. See [credentials.md § Fixed Container Registry](../credentials.md#fixed-container-registry) for the doctrine pointer.

### Verification by `docex preinfra`

`./bin/docex preinfra production` (fixed) verifies the credential is present on the production host at both paths the release playbook uses — `/home/deploy/.docker/config.json` (image pulls run as the `deploy` user) and `/root/.docker/config.json` (`docker compose up` runs under `become: true`). A missing credential fails the check with the resolution: run `docker login registry.${base_domain}` as both `deploy` and `root` on the host. This is a *presence* check on the operator-managed credential, not a check of registry reachability — registry availability still surfaces naturally at `./bin/docex containerize`.

## Garbage Collection

The registry never deletes images on its own — every version pushed remains available for `./bin/docex rollback`. Disk usage grows linearly with version count, so on a long-lived host the operator may want to reclaim space by deleting old image tags and then running registry GC.

Phase one requires `REGISTRY_STORAGE_DELETE_ENABLED: "true"` on the registry container ([§ Registry container](#registry-container)). Without it, the procedure below cannot start.

Deletion is two-phase: tag/manifest deletion via the registry API (or by removing references), followed by the registry's `garbage-collect` subcommand to actually free blobs:

```bash
docker exec registry registry garbage-collect /etc/docker/registry/config.yml
```

GC is offline-safe by default but can be run while the registry is up; concurrent pushes during GC may be lost, so the doctrine-aligned procedure is to stop the registry container first:

```bash
cd /opt/docex-preinfra/container_registry/registry
docker compose stop registry
docker compose run --rm registry garbage-collect /etc/docker/registry/config.yml
docker compose up -d registry
```

GC is operator-driven, not scheduled — there is no doctrine prescription for how often to run it. Most setups never need to.

**Deleting a repository's last tag does not remove the repository.** The Registry V2 API keeps the repository *entry* in `/v2/_catalog` with a null tag list (`{"tags": null}`) until GC runs. That is expected, not a leftover — a cleanup check (a project's `verify_clean.sh`, for instance) must therefore key on a repository's **tags** rather than on its presence in the catalog, or it will fail permanently against repos that hold nothing.
