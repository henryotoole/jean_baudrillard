---
stratum: conditional
---

# Fixed Master Network

On `fixed` foundations, the per-machine `master_network` is a single Docker bridge — `docex-ingress` — shared by every project's traefik container. It can't route traffic on its own: paired with it is the `web_demux` HAProxy container that owns host :443 and :80 and forwards inbound requests onto the bridge by domain. This file covers both — the `docex-ingress` bridge itself and the `web_demux` tooling it depends on — since together they're the operator-managed prerequisite that lets multiple projects coexist on a single host without colliding on the public ports.

This file applies to **every machine that hosts at least one doctrine project's env stack** — that's typically the operator's dev machine and (separately) any remote prod host. Each gets its own copy of both; they're independent.

## The `web_demux` Resource

`web_demux` attaches to the fixed host machine's ports 443 and 80. It routes requests on the basis of domain down to the relevant project traefik container instance.

### Design

We will perform this routing with HAProxy. SNI-routing is used for 443 traffic without decrypting, and plain old HTTP routing for 80 traffic.

The `web_demux` can infer routing target entirely from the domain of the request, which can come in three forms:
1. `<codebase>-<service>.<env>.<project_name>.<apex_domain>` 
2. `<env>.<project_name>.<apex_domain>`
3. `<project_name>.<apex_domain>`

All of the above domains should be routed to the correct project traefik instance, which is the same for all three forms. HAProxy must determine project name; this is easy to do with simple string parsing as long as valid TLDs are known from a public suffix list. Once the TLD is removed from the domain (e.g. `dev.myproject.example.com` -> `dev.myproject.example`), the project name can be found by splitting the string on ".":
```py
project_name = domain_str_without_tld.split('.')[-2]
```

This is convenient because HAProxy never needs to have any further knowledge of projects or their configuration - simply knowing the doctrine-standard domain format is enough.

Project traefik instances share a consistent naming scheme: `${project_name}-traefik`. These traefik containers will be on the `docex-ingress` network alongside the HAProxy container itself, so requests can be forwarded directly to them by reconstructing their names from the domain-interpreted project name.

The doctrine canonical form puts the project segment in DNS-labeled form (underscores → hyphens, lowercased — see [`cicl.md § Domain`](../cicl.md#domain)), so for an underscored project name `my_proj` the request will arrive carrying `my-proj` in the project segment. HAProxy parses out `my-proj` and forwards to a container named `my-proj-traefik`, which is exactly what `docex projinfra up <side>` emits. The DNS-label translation is the project's responsibility; HAProxy just forwards what it's parsed.

### Implementation

HAProxy runs as a Docker container — `haproxy:lts-alpine` is the doctrine pick (small image, well-maintained LTS line). It binds host ports 443 and 80 (single occupant per host), joins the `docex-ingress` bridge, and mounts a config file from the host. Lua scripting handles the SNI-to-project parse; the resolved container name is then looked up via Docker's embedded DNS on `docex-ingress`.

The container lives under `/opt/docex-preinfra/web_demux/` on the host (a doctrine-suggested path; the operator may put it elsewhere as long as `docker compose up -d` runs cleanly). Compose, config, and Lua script all live alongside each other so the operator can git-version the directory if they want.

Suggested directory layout:

```
/opt/docex-preinfra/web_demux/
├── docker-compose.yml
├── haproxy/
│   ├── haproxy.cfg
│   └── project_resolver.lua
```

### Setup Instructions

#### Prerequisites

- Docker engine running on the host (version 24+ recommended for predictable Docker-DNS behavior on user-defined bridges).
- Host ports 80 and 443 free (nothing else binding them — see the "Migrating from a legacy machine-wide traefik" note below if a pre-1.0.0 doctrine machine-wide traefik currently owns them).
- The `docex-ingress` bridge network created on the host (see [§ The `docex-ingress` Network § Setup Instructions](#setup-instructions-1) below). Stand up the bridge before bringing the `web_demux` up.

#### Stand-up

1. Create the working directory and config files:

```bash
sudo mkdir -p /opt/docex-preinfra/web_demux/haproxy
cd /opt/docex-preinfra/web_demux

# Fetch the Public Suffix List the project resolver uses to find each
# request's TLD (so .co.uk-style multi-label apexes parse correctly).
# Slow-changing data — refresh it occasionally (e.g. when adding a project
# on a TLD published after this was last fetched), not on every stand-up.
curl -fsSL https://publicsuffix.org/list/public_suffix_list.dat \
  -o haproxy/public_suffix_list.dat
```

2. Write `docker-compose.yml`:

```yaml
# /opt/docex-preinfra/web_demux/docker-compose.yml
services:
  web_demux:
    image: haproxy:lts-alpine
    container_name: web_demux
    restart: unless-stopped
    networks:
      - docex-ingress
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./haproxy/haproxy.cfg:/usr/local/etc/haproxy/haproxy.cfg:ro
      - ./haproxy/project_resolver.lua:/usr/local/etc/haproxy/project_resolver.lua:ro
      - ./haproxy/public_suffix_list.dat:/usr/local/etc/haproxy/public_suffix_list.dat:ro

networks:
  docex-ingress:
    external: true
```

3. Write `haproxy/project_resolver.lua`:

```lua
-- /opt/docex-preinfra/web_demux/haproxy/project_resolver.lua
--
-- Doctrine-prescribed SNI/Host-header -> project-name parse.
-- The canonical doctrine forms are:
--   <codebase>-<service>.<env>.<project>.<apex_domain>
--   <env>.<project>.<apex_domain>
--   <project>.<apex_domain>
--
-- The parse does not actually count them. It is right-anchored and has no
-- opinion about how many labels sit to the LEFT of the project, which is why
-- the service label gaining a core-service segment needed no change here.
--
-- Returns the project segment regardless of which form arrived, for ANY
-- TLD. The apex (registrable domain the operator owns) is the public
-- suffix plus one label; the project is the label immediately to its
-- left. We find the public suffix with the Public Suffix List, so this
-- works identically for single-label TLDs (`.com`, `.tech`) and
-- multi-label ones (`.co.uk`, `.com.au`). The PSL is mounted into the
-- container and loaded once at startup (see docker-compose.yml + the
-- download step in the setup instructions).
--
-- See doctrine/infrastructure/preinfra/fixed_master_network.md.

local PSL_PATH = "/usr/local/etc/haproxy/public_suffix_list.dat"

-- PSL rules loaded at init. Plain rules ("co.uk") and the two special
-- rule kinds: wildcards ("*.ck" -> key "ck") and exceptions ("!www.ck"
-- -> key "www.ck"). Exceptions win over wildcards per the PSL algorithm.
local psl_rules, psl_wildcards, psl_exceptions = {}, {}, {}

local function load_psl(path)
    local f = io.open(path, "r")
    if not f then
        core.Alert("project_resolver: cannot open PSL at " .. path)
        return
    end
    for line in f:lines() do
        line = line:gsub("%s+$", "")
        -- Skip blanks and `//` comments. Unicode rules are irrelevant to
        -- our ASCII doctrine domains; they load harmlessly as plain keys.
        if line ~= "" and line:sub(1, 2) ~= "//" then
            if line:sub(1, 1) == "!" then
                psl_exceptions[line:sub(2)] = true
            elseif line:sub(1, 2) == "*." then
                psl_wildcards[line:sub(3)] = true
            else
                psl_rules[line] = true
            end
        end
    end
    f:close()
end

load_psl(PSL_PATH)

-- Number of labels in the public suffix of the label array `parts`,
-- per the PSL algorithm (exceptions win; else longest matching plain or
-- wildcard rule; else the default `*` rule = one label).
local function public_suffix_label_count(parts)
    local n = #parts
    -- Exceptions first, longest candidate (i=1) to shortest.
    for i = 1, n do
        if psl_exceptions[table.concat(parts, ".", i, n)] then
            -- public suffix = the exception rule minus its leftmost label
            return (n - i + 1) - 1
        end
    end
    local best = 0
    for i = 1, n do
        local labels_in = n - i + 1
        if psl_rules[table.concat(parts, ".", i, n)] then
            if labels_in > best then best = labels_in end
        elseif i < n and psl_wildcards[table.concat(parts, ".", i + 1, n)] then
            -- "*.<rest>" matches: the label at i is the wildcard.
            if labels_in > best then best = labels_in end
        end
    end
    if best == 0 then best = 1 end   -- default rule "*"
    return best
end

local function project_from_host(host)
    if not host or host == "" then return nil end
    -- Strip any trailing dot (FQDN form), lowercase, split on '.'.
    host = host:gsub("%.$", ""):lower()
    local parts = {}
    for p in string.gmatch(host, "[^.]+") do
        table.insert(parts, p)
    end
    local n = #parts
    -- apex (registrable domain) = public suffix + 1 label; project is the
    -- label immediately to its left.
    local project_index = n - (public_suffix_label_count(parts) + 1)
    if project_index < 1 then return nil end
    return parts[project_index]
end

-- TCP path (https, SNI). Fetched as a string returning the resolved
-- backend container hostname, e.g. "my-proj-traefik". Uses `req_ssl_sni`
-- (NOT `ssl_fc_sni`) — `ssl_fc_sni` only returns a value when the
-- frontend itself terminates TLS, which web_demux deliberately does not
-- do. The per-project traefik downstream is what terminates TLS; here
-- we parse the SNI from the L4 ClientHello in TCP pass-through.
core.register_fetches("project_traefik_from_sni", function(txn)
    local sni = txn.f:req_ssl_sni()
    local proj = project_from_host(sni)
    if not proj then return nil end
    return proj .. "-traefik"
end)

-- HTTP path (port 80, Host header). Same shape.
core.register_fetches("project_traefik_from_host_hdr", function(txn)
    local host_hdr = txn.f:req_hdr("Host")
    -- Strip any :port suffix
    if host_hdr then host_hdr = host_hdr:gsub(":.*$", "") end
    local proj = project_from_host(host_hdr)
    if not proj then return nil end
    return proj .. "-traefik"
end)
```

4. Write `haproxy/haproxy.cfg`:

```haproxy
# /opt/docex-preinfra/web_demux/haproxy/haproxy.cfg

global
    log stdout format raw local0
    # Opt into modern HAProxy 3.1+ Lua boolean-sample semantics. Silences
    # a startup warning under the `lts-alpine` tag (currently 3.x).
    # Must appear before any `lua-load` directive.
    tune.lua.bool-sample-conversion normal
    lua-load /usr/local/etc/haproxy/project_resolver.lua

# Docker's embedded DNS resolves <project>-traefik container names on the
# docex-ingress bridge. 127.0.0.11 is the standard Docker DNS endpoint
# inside user-defined bridge networks. The `resolvers` section is a
# top-level block — it cannot be nested inside `global`.
resolvers docker_dns
    nameserver dockerd 127.0.0.11:53
    resolve_retries 3
    timeout retry 1s
    hold valid 10s
    hold nx 5s

defaults
    log global
    timeout connect 5s
    timeout client 60s
    timeout server 60s

# -----------------------------------------------------------------------
# HTTPS (443) — SNI pass-through. No TLS termination; per-project traefik
# handles that. Parse <project>-traefik hostname from SNI via Lua,
# resolve to an IP through docker_dns, then rewrite the per-connection
# destination IP. Fully dynamic — no per-project static list and no new
# Lua action needed beyond the parser the doctrine prescribes.
# -----------------------------------------------------------------------
frontend https_in
    bind *:443
    mode tcp
    option tcplog
    tcp-request inspect-delay 5s
    tcp-request content reject if !{ req_ssl_hello_type 1 }
    tcp-request content reject if !{ req_ssl_sni -m found }

    tcp-request content set-var(sess.proj_host) lua.project_traefik_from_sni
    tcp-request content reject if !{ var(sess.proj_host) -m found }
    tcp-request content do-resolve(sess.target_ip,docker_dns,ipv4) var(sess.proj_host)
    tcp-request content reject if !{ var(sess.target_ip) -m found }
    tcp-request content set-dst var(sess.target_ip)

    use_backend project_pool_tcp

backend project_pool_tcp
    mode tcp
    # Destination IP is replaced per-connection by `set-dst` above; this
    # line only contributes the port (443) for the upstream connection.
    server target 0.0.0.0:443

# -----------------------------------------------------------------------
# HTTP (80) — plain HTTP, route by Host header. The per-project traefik
# handles the 80→443 redirect, so web_demux just forwards.
# -----------------------------------------------------------------------
frontend http_in
    bind *:80
    mode http
    option httplog
    http-request deny if !{ hdr(host) -m found }

    http-request set-var(txn.proj_host) lua.project_traefik_from_host_hdr
    http-request deny if !{ var(txn.proj_host) -m found }
    http-request do-resolve(txn.target_ip,docker_dns,ipv4) var(txn.proj_host)
    http-request deny if !{ var(txn.target_ip) -m found }
    http-request set-dst var(txn.target_ip)

    use_backend project_pool_http

backend project_pool_http
    mode http
    server target 0.0.0.0:80
```

> **Why `do-resolve` + `set-dst` instead of `server-template` or `use_backend %[var]`.** HAProxy's `server-template` reserves N static server slots — useful for known-ahead pools, but it can't compute a backend hostname per connection from a fetched value. `use_backend %[var]` works in HTTP mode for *named* backends but doesn't translate to "open a TCP connection to a hostname I just computed." The `do-resolve` action does exactly that: it runs `var(sess.proj_host)` through `docker_dns` and stores the IP in `sess.target_ip`, then `set-dst` rewrites the connection's destination. The trailing `backend project_pool_tcp` exists only to contribute the port. Caching is handled by `hold valid 10s` in the resolver block.

5. Bring up the demux:

```bash
cd /opt/docex-preinfra/web_demux
sudo docker compose up -d
```

6. Verify:

```bash
sudo docker ps --filter name=web_demux --format '{{.Names}}\t{{.Status}}\t{{.Ports}}'
# Expect: web_demux  Up <ts>  0.0.0.0:80->80/tcp, 0.0.0.0:443->443/tcp

sudo docker network inspect docex-ingress --format '{{range .Containers}}{{.Name}} {{end}}'
# Expect: includes 'web_demux' (and any project traefik containers that came up after)
```

`docex preinfra development` does NOT probe HAProxy directly (operator-managed); it only probes the `docex-ingress` bridge.

### Migrating from a legacy machine-wide traefik

If the host previously ran the pre-1.0.0 doctrine's machine-wide traefik (one shared `traefik` container on a single `web` docker network, owning host :443/:80 and routing for all projects via labels), the migration is the operator's responsibility and is not a `docex` command. The high-level shape:

1. **Stand up `docex-ingress` bridge** alongside the existing `web` network (they coexist fine; different bridges).
2. **For each project currently routed through the legacy traefik**: bring up its `${project}-traefik` per-project container (via `docex projinfra up <side>` for doctrine projects; via a hand-written compose for pre-doctrine workloads like preinfra-as-project HyperDX or the container registry). Each per-project traefik joins `docex-ingress` and the project's own `-web` networks.
3. **Stop the legacy traefik** and free host :443/:80.
4. **Bring up `web_demux`** per the steps above. It picks up the published `${project}-traefik` containers via `docex-ingress` and resumes routing.

Steps 2 and 3 trade brief downtime (seconds to a minute) per project for the migration. There is no zero-downtime path with this design — host :443 has one owner.

> TODO: refine after first migration. If the operator hits subtleties (TLS state continuity for Let's Encrypt, container-name collisions, in-flight connection drain expectations), document them here.

## The `docex-ingress` Network

### Design

The `docex-ingress` network is a docker bridge network that ties the `web_demux` resource together with all the project traefik containers. It is the standard way that ingress is provided to projects on `fixed` foundations.

It's a plain Docker user-defined bridge — no fancy driver options, no specific CIDR requirements. Docker's embedded DNS resolves container names on the bridge (`<project>-traefik`, `web_demux`, etc.) so HAProxy can forward without static IP knowledge.

### Implementation

A single `docker network create docex-ingress` invocation. No compose file owns the network — it's external from the perspective of `web_demux/docker-compose.yml` and from every project's projinfra compose file. This keeps lifecycle independent: the bridge survives `docker compose down` cycles on any individual project (or on `web_demux` itself).

### Setup Instructions

```bash
# Create the bridge (idempotent: succeeds if absent, no-op if present).
docker network inspect docex-ingress >/dev/null 2>&1 \
    || docker network create docex-ingress

# Verify
docker network ls --filter name=docex-ingress
# Expect one row.
```

`docex preinfra development` probes this bridge specifically — its existence is the doctrine-prescribed gate for any `projinfra up development` invocation. If it's missing, every project's projinfra refuses to run.

### Teardown

```bash
# Confirm nothing is still attached (project traefiks, web_demux, etc.).
docker network inspect docex-ingress --format '{{len .Containers}}'
# If non-zero, take down the attached containers first (projinfra down,
# compose down on web_demux) before proceeding.

docker network rm docex-ingress
```

In practice this bridge gets stood up once per host and lives indefinitely.

## Other Concerns

### Adding Preinfra To Machine

Some prerequisite infrastructure (like the HyperDX observability backend) must be added to a fixed-foundation host machine and be accessed over HTTP/HTTPS. It has to fit into our `web_demux` structure. The simplest way to do this is to treat preinfra as just another project. It gets set up on its own docker network with a `traefik` container that spans its network and `docex-ingress`. Naming conventions for the `traefik` instance match those of any other project, so `web_demux` routing *just works*.

The only drawback of this plan is that preinfra names might collide with project names. In practice this is unlikely, as preinfra names tend to be very specific, like `hyperdx`.

### Coexistence with non-doctrine workloads

The host machine may also be running workloads that don't follow the doctrine domain shape (legacy apps reachable via IP, internal-only services, etc.). Two coexistence patterns:

- **They don't use host :443/:80.** Anything binding other ports or relying on container-network-only access is unaffected by `web_demux`.
- **They use host :443/:80 but expect a different routing convention.** Migrate them to the doctrine domain shape (give them a project name, stand up a `${name}-traefik` per-project container, plug into the demux) — or accept that they remain on a different host while the doctrine-shaped workloads use this one.

### Single-owner-of-:443 invariant

Only one process can bind host :443 (and :80) on a Linux machine without SO_REUSEPORT trickery. `web_demux` claims them; nothing else can. This is the invariant that lets the doctrine guarantee single-source-of-truth routing: every inbound request hits HAProxy first, period.

If the operator finds another process holding these ports, the migration path is "stop that process, start web_demux." There's no shared-ownership pattern in this design.
