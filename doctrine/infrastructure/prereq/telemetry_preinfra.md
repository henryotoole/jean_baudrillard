# Telemetry Infrastructure Maintenance

This document goes over the standards and practices needed by the LLM agent or operator to setup and maintain the prerequisite portion of doctrine-prescribed telemetry infrastructure. This is entirely out of the scope of a specific project.

The only prerequisite infrastructure component is the [observability backend](../telemetry.md#observability-backend). This can either be self-hosted or a paid, managed cloud service. This guide is only concerned with the self-hosted version as the cloud service is maintained by a third party.

## Setup

The shape of the self-hosted HyperDX is pretty similar whether on fixed or common. The main difference is whether HyperDX is built on an EC2 instance or a `fixed` server.

`fixed`: A dedicated directory is chosen on the main fixed server. The HyperDX directory is cloned into it and run as a stack of containers with docker-compose. It ties into the machine-wide traefik instance, which handles SSL termination and routing. Data is stored onto mounted volumes.

`elastic`: An EC2 instance with sufficient performance is requisitioned and exposed to the internet with an Elastic IP. The HyperDX directory is cloned into it and run as a stack of containers with docker-compose. A traefik compose container is setup to handle SSL termination and routing. Data is stored onto mounted volumes, which themselves are backed by EBS storage.

### Common

The HyperDX docker-compose stack itself runs identically on both foundations. The differences in the foundation-specific sections below — directory location, which traefik instance discovers HyperDX, where DNS is managed — are operator-environment concerns, not stack-config concerns.

#### HyperDX Installation

HyperDX is installed by cloning its self-hosted repository and configuring the bundled docker-compose stack. The canonical repo URL has changed over HyperDX's lifecycle (especially around its ClickHouse-acquisition phase); verify the current location before cloning. As of writing, [github.com/hyperdxio/hyperdx](https://github.com/hyperdxio/hyperdx) is the right starting point.

1. **Clone the repo** into the operator's chosen directory:

   ```bash
   git clone https://github.com/hyperdxio/hyperdx.git .
   ```

   **Pin to a specific tagged release**, not `main`. New releases occasionally introduce breaking config or schema changes; tracking `main` makes routine updates risky and makes the doctrine's "what the operator deployed" question harder to answer.

   HyperDX's repo is a multi-package monorepo and tags each package separately — there is no single `v2.28.0`-style root tag. Expect tags like `@hyperdx/api@2.28.0`, `@hyperdx/app@2.28.0`, `@hyperdx/otel-collector@2.28.0`, and `@hyperdx/common-utils@0.20.0`. When released together they resolve to the same commit; pin by checking out any one of them (or the shared commit directly).

2. **Configure the bundled `.env` / config file** with operator-supplied values. Required values typically include an admin password, encryption keys, and database credentials. Use long random values for all secrets — they live on the prerequisite-infrastructure machine and aren't expected to rotate. The full list of required env vars varies by HyperDX version; refer to HyperDX's setup documentation for the current set.

   Two values are easy to miss and worth calling out explicitly:

   - **`IMAGE_VERSION`.** Upstream's bundled `.env` defaults to a floating major-version tag (e.g. `IMAGE_VERSION=2`), which pulls whatever `:2` resolves to at the moment. Override with the exact patch version of the pinned release (e.g. `IMAGE_VERSION=2.28.0`) so the deployed image is reproducible alongside the pinned source.
   - **`EXPRESS_SESSION_SECRET`.** Required for production per upstream's `DEPLOY.md` but not present in the default `.env`. Add it with a long random value (e.g. `openssl rand -hex 32`).

3. **Add traefik integration to the HyperDX UI service.** HyperDX must be reachable via the foundation-appropriate traefik instance — the machine-wide traefik on fixed, the dedicated EC2-resident traefik on elastic (see [Fixed](#fixed) and [Elastic](#elastic) below for which applies). The integration pattern is the same in both cases: add traefik discovery labels and an external-network attachment to the HyperDX UI compose service.

   **Apply this customization via a `docker-compose.override.yml` next to the upstream `docker-compose.yml`** rather than editing the upstream file. Compose auto-merges the override; the upstream compose file stays clean against the pinned tag, and future version upgrades become a `git pull` + retag + restart rather than a hand-merge.

   ```yaml
   labels:
     - "traefik.enable=true"
     - "traefik.docker.network=web"
     - "traefik.http.routers.hyperdx.rule=Host(`hyperdx.${BASE_DOMAIN}`)"
     - "traefik.http.routers.hyperdx.entrypoints=websecure"
     - "traefik.http.routers.hyperdx.tls=true"
     - "traefik.http.routers.hyperdx.tls.certresolver=doctrine"
     - "traefik.http.services.hyperdx.loadbalancer.server.port=<HYPERDX_UI_PORT>"
   networks:
     - web
     - <hyperdx's internal network>
   ```

   `<HYPERDX_UI_PORT>` is the port HyperDX's UI service listens on inside its container — verify against the running compose file (typical values are `8080` or `3000`, depending on version). The `web` network is the same external docker network the foundation's traefik instance is attached to. In HyperDX 2.x, the UI lives on the `app` service in upstream's `docker-compose.yml`; these labels go on that service.

   The explicit `traefik.docker.network=web` label disambiguates which network's IP traefik picks when the target container is attached to multiple docker networks (which a HyperDX service always is — it needs `internal` for its DB / ClickHouse peers and `web` for traefik). It's redundant when the traefik provider config already pins `network: web` (as in step 4.4 below for elastic), but explicit beats implicit if labels ever get copied somewhere with different provider config.

   The cert resolver name `doctrine` is the canonical handle the doctrine prescribes (see [networks.md § `networks: [web]`](../specifics/networks.md#networks-web) and [transfer_tables.md § Per-container (fixed)](../specifics/transfer_tables.md#per-container-fixed)) — the operator's traefik configures the actual cert provider under that name; the doctrine references it the same way everywhere.

4. **Expose the OTLP ingestion endpoint via traefik.** HyperDX's bundled otel-collector listens on `4318` (HTTP) and `4317` (gRPC). The doctrine sidecars use HTTP/protobuf only (per [telemetry_infra.md § Pipeline Shape](../specifics/telemetry_infra.md#pipeline-shape)), so only `4318` needs to be reachable from the open internet. Add traefik labels for the OTLP path on whichever container actually receives OTLP traffic — **in HyperDX 2.x this is the `otel-collector` service, distinct from the `app` service that hosts the UI**, so these labels go on a different service from step 3's UI labels:

   ```yaml
   labels:
     - "traefik.enable=true"
     - "traefik.docker.network=web"
     - "traefik.http.routers.hyperdx_otlp.rule=Host(`hyperdx.${BASE_DOMAIN}`) && PathPrefix(`/v1/`)"
     - "traefik.http.routers.hyperdx_otlp.entrypoints=websecure"
     - "traefik.http.routers.hyperdx_otlp.tls=true"
     - "traefik.http.routers.hyperdx_otlp.tls.certresolver=doctrine"
     - "traefik.http.services.hyperdx_otlp.loadbalancer.server.port=4318"
   networks:
     - web
     - <hyperdx's internal network>
   ```

   The OTLP HTTP path-prefix `/v1/` is OTel-standard (`/v1/traces`, `/v1/logs`, `/v1/metrics`). Same hostname, path-based routing splits UI traffic from ingestion. Traefik priorities favour the longer rule (the UI router's `Host(...)` rule is shorter than OTLP's `Host(...) && PathPrefix(/v1/)`), so `/v1/*` routes to OTLP and everything else to the UI.

5. **Configure storage retention** to match the doctrine's commits in [telemetry.md § Storage Window](../telemetry.md#storage-window):

   - Logs: 7 days
   - Traces: 7 days
   - Sessions: 7 days
   - Metrics: 90 days

   HyperDX stores all signals in ClickHouse. Retention is enforced via per-table TTLs.

   **As of HyperDX 2.x, the schema ships with doctrine-aligned TTLs baked in** — `+ toIntervalDay(7)` on `otel_logs`, `otel_traces`, and `hyperdx_sessions`; `+ toIntervalDay(90)` on every `otel_metrics_*` table. The operator's job is therefore to **verify**, not blindly apply; only issue ALTERs if a table's existing TTL is missing or wrong.

   Verify by inspecting every signal table:

   ```bash
   for t in otel_logs otel_traces hyperdx_sessions \
            otel_metrics_sum otel_metrics_gauge otel_metrics_histogram \
            otel_metrics_exponential_histogram otel_metrics_summary; do
     printf '%-40s ' "$t"
     docker compose exec -T ch-server clickhouse-client \
       --query="SHOW CREATE TABLE default.${t} FORMAT TSVRaw" \
       | grep -oE 'TTL [^,]*toIntervalDay\([0-9]+\)' | head -1
   done
   ```

   If a TTL is missing or doesn't match, apply via `ALTER TABLE ... MODIFY TTL`. Be careful with column types — `TimestampTime` is `DateTime` and needs no cast, while `Timestamp` (traces) and `TimeUnix` (metrics) are `DateTime64` and need a `toDateTime()` cast:

   ```sql
   ALTER TABLE default.otel_logs                          MODIFY TTL TimestampTime + INTERVAL 7  DAY;
   ALTER TABLE default.otel_traces                        MODIFY TTL toDateTime(Timestamp) + INTERVAL 7  DAY;
   ALTER TABLE default.hyperdx_sessions                   MODIFY TTL TimestampTime + INTERVAL 7  DAY;
   ALTER TABLE default.otel_metrics_sum                   MODIFY TTL toDateTime(TimeUnix) + INTERVAL 90 DAY;
   ALTER TABLE default.otel_metrics_gauge                 MODIFY TTL toDateTime(TimeUnix) + INTERVAL 90 DAY;
   ALTER TABLE default.otel_metrics_histogram             MODIFY TTL toDateTime(TimeUnix) + INTERVAL 90 DAY;
   ALTER TABLE default.otel_metrics_exponential_histogram MODIFY TTL toDateTime(TimeUnix) + INTERVAL 90 DAY;
   ALTER TABLE default.otel_metrics_summary               MODIFY TTL toDateTime(TimeUnix) + INTERVAL 90 DAY;
   ```

   ClickHouse normalizes `+ INTERVAL N DAY` to `+ toIntervalDay(N)` when it stores the clause, so subsequent `SHOW CREATE TABLE` output displays the `toIntervalDay()` form regardless of which form you issued.

   ClickHouse runs the cleanup automatically on its merge schedule once TTL is set; the operator doesn't schedule recurring jobs. The TTL is part of the table's metadata, so it survives HyperDX restarts and re-deploys — but it does NOT survive a wholesale schema reset (e.g., dropping and recreating tables across a HyperDX major-version upgrade). Re-verify after any operation that touches the schema.

6. **Bring up the stack:**

   ```bash
   docker compose up -d
   ```

   On first start, HyperDX initializes its ClickHouse schema and waits for the operator to create the first admin account via the UI. The schema initialization is what creates the tables you'll verify in step 5 — that step has to happen *after* the first successful `docker compose up`.

   **HyperDX 2.x runs its bundled OTel collector under an OpAMP supervisor.** The `otel-collector` container is actually a thin supervisor process; the real collector subprocess inherits its config from HyperDX's `app` service via OPAMP at `http://app:4320`. On a fresh stack, the supervised collector starts with no receivers configured — **port `4318` (OTLP HTTP) is NOT bound until the operator has created the admin account, defined at least one team, and configured a source in the UI**. The reachability-verification probe in [Verifying Reachability § OTLP ingestion](#verifying-reachability) will return `502 Bad Gateway` from traefik until UI source setup completes. This is expected first-launch behaviour, not a misconfiguration of the reverse proxy or networks.

#### DNS

The base domain used for HyperDX will depend on both *what* and *which* infrastructure foundation is used. Elastic-foundation projects that share a single AWS account will all use the same HyperDX instance and domain. However, this doctrine is used for many projects across many different AWS accounts. The base domain used for the instance will depend on this operating circumstance and can not be deterministically chosen in advance. Always ask the operator what base domain to use when setting this up.

We can, however, specify that all HyperDX traffic go through a consistent *subdomain*: `hyperdx`.

Therefore, the actual domain at which HyperDX will be accessed is: `hyperdx.${base_domain}`

#### Verifying Reachability

After the stack is up, the operator (or LLM agent) verifies that HyperDX is reachable end-to-end before declaring setup complete. The procedure is the same on both foundations.

1. **UI reachability.** In a browser, navigate to `https://hyperdx.${base_domain}`. Expect the HyperDX login or onboarding page. Likely failures and their meanings:
   - Connection refused / timeout → DNS hasn't propagated, the security group isn't open, or traefik isn't running.
   - TLS error (invalid cert, untrusted issuer) → cert resolver hasn't completed an ACME challenge; check traefik's logs for ACME failures.
   - 404 or 502 from traefik → traefik labels are misconfigured or HyperDX's UI service isn't running; check `docker compose ps` for service health.

2. **Admin account.** Complete HyperDX's onboarding flow to create the initial admin account. Save the password — it isn't recoverable without operator access to the ClickHouse database.

3. **OTLP ingestion.** Create a test team in HyperDX, retrieve its ingestion API key, and emit a probe trace via curl:

   ```bash
   curl -X POST "https://hyperdx.${base_domain}/v1/traces" \
     -H "Content-Type: application/json" \
     -H "Authorization: <API_KEY>" \
     -d '{
       "resourceSpans": [{
         "resource": { "attributes": [
           { "key": "service.name", "value": { "stringValue": "reachability-probe" } }
         ]},
         "scopeSpans": [{ "spans": [{
           "traceId": "00000000000000000000000000000001",
           "spanId":  "0000000000000001",
           "name":    "probe",
           "startTimeUnixNano": "<current unix nano>",
           "endTimeUnixNano":   "<current unix nano>"
         }]}]
       }]
     }'
   ```

   A `2xx` response indicates ingestion succeeded — HyperDX 2.x's collector responds with `HTTP 200` and body `{"partialSuccess":{}}`. Then navigate to the HyperDX UI's traces view; the probe span should appear within seconds, attributed to `service.name=reachability-probe`. A `401` means the API key was wrong; a `404` means the OTLP router isn't matching `/v1/traces` (re-check the path-prefix rule from step 4); a `502` means traefik can route but the target backend isn't accepting on `4318`. In HyperDX 2.x, the **overwhelmingly most common cause of a 502 on a fresh install is the OpAMP-supervisor sequencing covered in [HyperDX Installation § step 6](#hyperdx-installation)** — verify the operator has finished UI admin and source setup before chasing network or label issues.

4. **Retention.** Confirm the TTL was set correctly by querying the schema:

   ```bash
   docker compose exec clickhouse clickhouse-client \
     --query="SHOW CREATE TABLE otel_logs"
   ```

   The output should include a `TTL ... + toIntervalDay(7)` clause (90 for metrics). ClickHouse normalizes `INTERVAL N DAY` to `toIntervalDay(N)` in stored DDL, so this is the form that displays once persisted, regardless of which form the ALTER used. Repeat against every signal table listed in [HyperDX Installation § step 5](#hyperdx-installation) to confirm full coverage.

If all four pass, the instance is ready for project sidecars to connect.

### Fixed

The following describes how to setup HyperDX in fixed-foundation projects.

1. **Choose Base Directory** for the HyperDX instance to live in. Default is `~/preinfra/hyperdx`.

2. **Route DNS.** Determine the appropriate records to route `hyperdx.${base_domain}` to the fixed machine's IP, and then ask the operator to add those records to the domain registrar's DNS.

3. **Setup HyperDX.** Follow the [common instructions](#hyperdx-installation). For the traefik integration step, the relevant traefik instance is the **machine-wide** traefik already running on the fixed server (per [shape2.md § Fixed-Foundation](../shape2.md#fixed-foundation)). The external `web` network in the compose file is the same machine-wide `web` docker network that traefik is attached to; HyperDX is discovered automatically once labels are applied.

4. **Test Reachability.** Follow the [common verification procedure](#verifying-reachability).

### Elastic

The following describes how to setup HyperDX for elastic-foundation projects.

1. **Double check that there's not already an EC2 instance setup that does this.** The easiest way is to check for infrastructure components with the tag `prerequisite-infrastructure-telemetry`. If a HyperDX instance has already been setup, don't create a redundant duplicate! Alert the operator and await instruction.

2. **Requisition the server.** An EC2 instance (4GB RAM or more: `t3a.medium`) is needed with the current stable release of Ubuntu Server and an elastic IP assigned to it. The instance should be setup to be accessed via SSH so that developers have terminal access. Docker and Docker Compose shall be installed on it.

   The instance should be backed with 100GB of general purpose EBS storage. Currently this is `gp3` on AWS.

   Total costs will be about $35/mo (at time of writing).

   The instance and EBS volume should both be tagged with `prerequisite-infrastructure-telemetry`.

   The instance's security group must allow inbound traffic on:
   - `22` from the operator's IP (or a sane CIDR) for SSH
   - `80` from `0.0.0.0/0` for Let's Encrypt HTTP-01 challenges and the HTTPS redirect
   - `443` from `0.0.0.0/0` for HTTPS UI access and OTLP ingestion from project sidecars

3. **Route DNS.** Use Route53 to route `hyperdx.${base_domain}` to the EC2 instance's elastic IP. A single `A` record is sufficient.

4. **Setup Traefik.** Unlike on fixed (where the machine-wide traefik is already running), elastic-foundation HyperDX needs a dedicated traefik on the EC2 instance to handle SSL termination and routing. Procedure:

   1. Create the external `web` docker network that traefik and HyperDX will share:

      ```bash
      docker network create web
      ```

   2. Make a directory at `~/traefik` on the EC2 instance.

   3. Create `~/traefik/docker-compose.yml`:

      ```yaml
      services:
        traefik:
          image: traefik:v3
          container_name: traefik
          restart: unless-stopped
          ports:
            - "80:80"
            - "443:443"
          volumes:
            - /var/run/docker.sock:/var/run/docker.sock:ro
            - ./acme.json:/acme.json
            - ./traefik.yml:/etc/traefik/traefik.yml:ro
          networks:
            - web

      networks:
        web:
          external: true
      ```

   4. Create `~/traefik/traefik.yml`:

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
          network: web

      certificatesResolvers:
        doctrine:
          acme:
            email: <operator email>
            storage: /acme.json
            httpChallenge:
              entryPoint: web
      ```

      The cert resolver is named `doctrine` to match the canonical handle prescribed elsewhere in the doctrine. HTTP-01 is sufficient because we route only a single subdomain (`hyperdx.${base_domain}`), not a wildcard.

   5. Create an empty `acme.json` with restricted permissions:

      ```bash
      touch ~/traefik/acme.json && chmod 600 ~/traefik/acme.json
      ```

      Traefik refuses to write certificate data to a file with looser permissions.

   6. Bring up traefik:

      ```bash
      cd ~/traefik && docker compose up -d
      ```

   7. Verify traefik is up by curling its HTTP entrypoint:

      ```bash
      curl -I http://hyperdx.${base_domain}
      ```

      Expect a `308 Permanent Redirect` to `https://hyperdx.${base_domain}/` — the `web` entrypoint config from step 4.4 redirects all HTTP traffic to HTTPS unconditionally, before any routing happens, so the redirect itself is what proves traefik is reachable even with no service registered yet. A connection error means DNS hasn't propagated, the security group is closed, or traefik didn't start. (A `404` would only appear via HTTPS once a `Host` rule fails to match — not relevant at this step.)

5. **Setup HyperDX.** Follow the [common instructions](#hyperdx-installation). The traefik instance HyperDX integrates with is the dedicated one from step 4, attached to the same external `web` network created in step 4.1.

6. **Test Reachability.** Follow the [common verification procedure](#verifying-reachability).
