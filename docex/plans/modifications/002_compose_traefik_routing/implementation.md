# Mod 002 — Implementation Steps

Self-contained instructions for executing this mod. Read `overview.md` in the same folder for the design rationale.

## Context for a fresh agent

You are working in the `docex` project at `~/.claude/jean_baudrillard/docex/`. `docex` is the executor of the doctrine; full background is in `plans/core/masterplan.md` and `plans/core/docex_process.md`. The doctrine itself lives at `~/.claude/jean_baudrillard/doctrine/`.

**The bugs.** Two compose-emitter shortcomings collude to break HTTPS routing for fixed-foundation projects. Bug A: the emitter creates a project-scoped Docker network `${project}_${env}_web` for web-tier services, but the machine-wide Traefik can only attach to ONE network and uses the bare name `web`, so it can't reach project-scoped networks. Bug B: the emitter produces `traefik.http.routers.X.tls=true` with no `tls.certresolver`, which suppresses Traefik's entrypoint-default resolver — no ACME request is ever made, default self-signed cert is served, browsers refuse.

**The fixes.**
- The `web` network is special-cased to compile as a bare external Docker network named `web`, in fixed-foundation output only. Every other network keeps the existing `${project}_${env}_${name}` scoping.
- The Traefik label set gains one entry: `traefik.http.routers.<global_service_name>.tls.certresolver=doctrine`. The literal name `doctrine` is the doctrine's prescribed handle for the single machine-wide cert resolver.

**Doctrine prose changes are settled.** Four documents get updates with operator-approved wording. The exact wording for each is included verbatim in the step where it gets applied — do not rewrite, only paste.

## Steps

### 1. Compose emitter — special-case the `web` network

File: `src/docex/emit/compose.py`

The current `_network_section` function (around lines 64–79) compiles every network as a project-scoped Docker network:

```python
def _network_section(compiled: CompiledEnv) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for short in sorted(compiled.networks):
        full = f"{compiled.project}_{compiled.env}_{short}"
        cfg: dict[str, Any] = {"name": full}
        if short != "web":
            cfg["internal"] = True
        out[short] = cfg
    return out
```

Replace the body of the loop so that when `short == "web"`, the emitted block is `{"name": "web", "external": True}` instead. Every non-`web` network keeps its existing project-scoped name and `internal: true`. Update the docstring to explain the carve-out: `web` is the machine-wide public-routing plane the host's Traefik attaches to, so it's a shared external network rather than a project-scoped one; this matches the rule in `doctrine/infrastructure/specifics/networks.md § Network Definition Name vs. Compiled Name`. Add a `WHY:` comment referencing the Bug A diagnosis: short-form project-scoped naming on `web` would force per-project Traefik instances, which can't coexist on port 443.

### 2. Compose emitter — emit `tls.certresolver=doctrine` for web-routed services

File: `src/docex/emit/compose.py`

The current `_traefik_labels` function (around lines 82–101) produces this label set:

```python
[
    "traefik.enable=true",
    f"traefik.http.routers.{gname}.rule={rule}",
    f"traefik.http.routers.{gname}.entrypoints=websecure",
    f"traefik.http.routers.{gname}.tls=true",
    f"traefik.http.services.{gname}.loadbalancer.server.port={svc.port}",
]
```

Insert one additional label immediately after the `tls=true` line:

```python
f"traefik.http.routers.{gname}.tls.certresolver=doctrine",
```

The literal name `doctrine` is hardcoded — it is the doctrine's prescribed handle for the machine-wide cert resolver. Update the function's docstring to mention the certresolver line and reference the doctrine rule (`doctrine/infrastructure/specifics/transfer_tables.md § Foundation Invariants § Per-container (fixed)`).

### 3. Unit tests — both branches

File: `tests/unit/test_compose_emitter.py`

Add two new test functions. Use the existing helpers (`_copy_fixture`, `_compose_services`, `_find_core_service_block`) and the existing `sample_project` fixture (which has core service `api` on `[web, internal]` and backing service `db` on `[internal]`).

```python
def test_web_network_is_shared_external_and_others_are_project_scoped(tmp_path: Path):
    """Per doctrine/infrastructure/specifics/networks.md § Network
    Definition Name vs. Compiled Name, fixed-foundation `web` compiles to
    the bare external network `web`; every other network keeps
    ${project}_${env}_${name} scoping."""
    root = _copy_fixture(tmp_path)
    ctx = load_project_context(root)
    run_compile(ctx)

    path = root / "infra" / "output" / "dev" / "docker-compose.yml"
    doc = yaml.safe_load(path.read_text())
    networks = doc["networks"]

    assert networks["web"] == {"name": "web", "external": True}, networks["web"]
    # `internal` (or any other CICL-defined network) stays project-scoped.
    internal = networks["internal"]
    assert internal["name"].endswith("_dev_internal"), internal
    assert internal.get("internal") is True, internal


def test_web_router_emits_certresolver_doctrine(tmp_path: Path):
    """Per doctrine transfer_tables.md § Foundation Invariants §
    Per-container (fixed), web-network services must carry a
    tls.certresolver=doctrine label so Traefik knows which resolver to
    use for cert acquisition."""
    root = _copy_fixture(tmp_path)
    ctx = load_project_context(root)
    run_compile(ctx)

    services = _compose_services(root, "dev")
    api = _find_core_service_block(services, "api")
    labels = api.get("labels") or []
    # Must include the certresolver label keyed by the service's global name.
    expected_suffix = ".tls.certresolver=doctrine"
    assert any(l.endswith(expected_suffix) for l in labels), labels
```

### 4. Doctrine prose updates

Apply each of these edits verbatim. The wording is operator-approved; do not rephrase.

#### 4a. `~/.claude/jean_baudrillard/doctrine/infrastructure/specifics/networks.md`

Find this paragraph (around line 20):

```
Therefore, the compiled name must be interpolated to ensure scope-uniqueness. The format is always `compiled_name = ${project}_${env}_${network_definition_name}`, whether it applies to a docker network name or an AWS SG.
```

Replace it with:

```
Therefore, the compiled name must be interpolated to ensure scope-uniqueness. The format is always `compiled_name = ${project}_${env}_${network_definition_name}`, whether it applies to a docker network name or an AWS SG.

**Exception: fixed-foundation `web`.** When compiling fixed-foundation output, the network named `web` compiles to a bare external network named `web` rather than `${project}_${env}_web`. This is the single shared public-routing plane that the machine-wide [reverse_proxy] attaches to; project-scoping it would force per-project reverse-proxy instances. See [`Implementation by Name § networks: [web]`](#networks-web) for the rationale. The exception applies only to fixed-foundation Docker networks — `web` in elastic-foundation output still compiles to a per-env, per-project security group named `${project}_${env}_web` for clarity in the AWS console.
```

Then find this bullet in the same file (around line 30, under `#### `networks: [web]``):

```
- **Fixed:** the container gets Traefik discovery labels (`traefik.enable=true`, a `Host(…)` router rule covering the service's subdomain(s), `loadbalancer.server.port=<port>`, etc.) and joins the `{project}_{env}_web` docker network, which the machine-wide Traefik watches. Traefik terminates TLS and routes each subdomain to the container over the network.
```

Replace it with:

```
- **Fixed:** the container gets Traefik discovery labels (`traefik.enable=true`, a `Host(…)` router rule covering the service's subdomain(s), `loadbalancer.server.port=<port>`, `tls.certresolver=doctrine`, etc.) and joins the bare external `web` docker network, which the machine-wide Traefik is also attached to. Traefik terminates TLS — using the resolver named `doctrine`, which the operator configures with DNS-01 against Let's Encrypt (HTTP-01 cannot issue the per-env wildcard certs this scheme requires) — and routes each subdomain to the container over the network. The `web` network is shared across all fixed-foundation projects on the host: it is the public-routing plane, and service-level authentication is the right defense against cross-tenant exposure on it.
```

#### 4b. `~/.claude/jean_baudrillard/doctrine/infrastructure/specifics/transfer_tables.md`

Find this section (around lines 255–264):

````
### Per-container (fixed)

Every compose service receives:

```yml
container_name: ${global_service_name}
logging: *default-logging
restart: unless-stopped
networks: ${networks}
```
````

Replace with:

````
### Per-container (fixed)

Every compose service receives:

```yml
container_name: ${global_service_name}
logging: *default-logging
restart: unless-stopped
networks: ${networks}
```

Additionally, services on the `web` network receive these Traefik discovery labels:

```yml
labels:
  - "traefik.enable=true"
  - "traefik.http.routers.${global_service_name}.rule=${host_rule}"
  - "traefik.http.routers.${global_service_name}.entrypoints=websecure"
  - "traefik.http.routers.${global_service_name}.tls=true"
  - "traefik.http.routers.${global_service_name}.tls.certresolver=doctrine"
  - "traefik.http.services.${global_service_name}.loadbalancer.server.port=${port}"
```

`${host_rule}` is the per-service [host rule](../cicl.md#per-service-subdomains). The literal resolver name `doctrine` is the prescribed handle for the single machine-wide cert resolver — the operator configures Traefik with a resolver of that exact name, and docex emits labels referencing it. Decoupling the *name* (a doctrine handshake) from the *implementation* (currently Let's Encrypt + DNS-01) lets the doctrine evolve the underlying mechanism without changing the handle.
````

#### 4c. `~/.claude/jean_baudrillard/docex/test_projects/PRE_CUT_CHECKLIST.md`

Find this section (around lines 60–64):

```
### A.6 Reverse proxy + cert manager — fixed

- [ ] Traefik is installed and running on the dev machine, configured machine-wide.
- [ ] Traefik's Let's Encrypt **DNS-01** challenge is configured against the Route53 zone for `luxrnd.tech` (HTTP-01 won't work for the per-env wildcards). Traefik's Route53 IAM is part of the AWS creds from A.1.
- [ ] Traefik is listening on `:443` with the docker provider enabled so it auto-discovers the test project's compose containers.
```

Replace with:

```
### A.6 Reverse proxy + cert manager — fixed

- [ ] Traefik is installed and running on the dev machine, configured machine-wide.
- [ ] Traefik is attached to the bare external Docker network named `web`. (docex's fixed-foundation compose emits `web` as this shared network; Traefik must share it to route to project containers.)
- [ ] Traefik has a single ACME cert resolver named exactly `doctrine`, configured with the **DNS-01** challenge against the Route53 zone for `luxrnd.tech` (HTTP-01 won't work for the per-env wildcards). Traefik's Route53 IAM is a dedicated narrow user with permissions scoped to the `luxrnd.tech` zone.
- [ ] Traefik is listening on `:443` with the docker provider enabled so it auto-discovers the test project's compose containers.
```

### 5. Validation

After all edits:

1. From `~/.claude/jean_baudrillard/docex`:
   ```
   python3 -m pytest tests/unit/ -v
   ```
   All previously-passing unit tests must still pass (currently 165 — 163 baseline + 2 from mod 001). New tests from step 3 must pass. Expected total: 167.

2. Rebuild the `docex:0.7.0` image:
   ```
   cd ~/.claude/jean_baudrillard/docex
   docker build -t docex:0.7.0 .
   ```

3. Recompile both test projects and inspect the compiled output:
   ```
   cd test_projects/fixed && ./bin/docex compile
   grep -A 3 "^  web:" infra/output/dev/docker-compose.yml
   grep "certresolver" infra/output/dev/docker-compose.yml
   ```
   Expected: top-level `networks.web` is `{name: web, external: true}`; the web service's labels include `traefik.http.routers.docex-smoke-fixed-dev-web.tls.certresolver=doctrine`.

   Same for `test_projects/elastic`.

4. **DO NOT** attempt `docex up dev` against the test project as part of validation in this mod. The operator's machine-wide Traefik must first be renamed/reconfigured to provide a resolver named `doctrine` and attach to the bare `web` network — that's prerequisite work, out of mod scope (called out in the overview's "Operator prerequisite work" section). The design-context agent will handle the Traefik rework after this mod is merged, then re-run C.4 manually.

## Out of scope

- No HCL emitter changes (`src/docex/emit/hcl.py` is untouched — elastic doesn't use Docker networks or Traefik).
- No transfer table changes (`tables/`).
- No `plans/core/*` changes (per `modifications.md` step 3.1).
- No version bumps (`pyproject.toml`, `__init__.py`, `CHANGELOG.md` updates handled by the design context post-implementation).
- No contract edits — this mod doesn't touch any provider service boundary.
- The operator's Traefik reconfiguration (resolver rename, removing the HTTP-01 resolver, deleting `acme.json`) is operator/ops work, not part of this mod.
