# Mod 140 — implementation steps

Prose overhaul of `docex/doctrine_excerpts/` + `index.yml` reconciliation + a
standing unit-test consumer. `docex why` behavior does **not** change. All prose
below is final — write it verbatim; do **not** re-derive content from doctrine.

Paths are relative to the repo root `~/.claude/jean_baudrillard`. The excerpts
dir is `docex/doctrine_excerpts/`. Interpreter is `docex/.venv/bin/python`, run
from `docex/`.

Do **not** edit any file under `doctrine/`. Do **not** edit `docex/plans/core/`
(core-doc updates are handled outside this file).

---

## Step 1 — Rename two excerpt files (git mv)

```sh
cd ~/.claude/jean_baudrillard/docex/doctrine_excerpts
git mv network_web.md web_network.md
git mv network_internal.md internal_network.md
```

Their contents are fully replaced in Step 3.

## Step 2 — Delete the retired `vpc` entry

```sh
cd ~/.claude/jean_baudrillard/docex/doctrine_excerpts
git rm vpc.md
```

## Step 3 — Overwrite / create excerpt files

Write each file below **verbatim** (full file contents).

### 3a. `aws_account.md` (rewrite)

```markdown
# aws_account

The AWS account in which a project's elastic-foundation resources are provisioned. **Prerequisite infrastructure**: `docex` does not create or manage AWS accounts.

The doctrine assumes **many projects may share one AWS account**. Projects are not isolated by account; they are isolated *within* an account by naming, tags, security groups, and IAM scoping. Multiple elastic projects sit side by side in the same account and share one prerequisite **master VPC** (see `why master_network`) — its Internet Gateway, NAT gateway, and subnets are shared across every elastic project in the account. Each project still gets its own reverse proxy, ECR repository, Route53 zone, and per-env security groups, so blast-radius protection comes from those per-project resources rather than from an account boundary.

Doctrine reference: `infrastructure/shape.md § Elastic-Foundation`.
```

### 3b. `dns.md` (rewrite)

```markdown
# dns

DNS routes an incoming HTTP/S request to the right project, environment, and core service purely by hostname. The doctrine's domain anatomy is:

`<codebase>-<service>.<env>.<project_name>.<apex_domain>` — e.g. `api-web.dev.myproject.example.com`

A single `apex_domain:` field in `infra.yml` sets the project's bare apex (e.g. `example.com`); every environment and service subdomain derives from it. A few "bare" subdomains carry routing rules of their own:

| Subdomain | Routes to |
| --- | --- |
| `<env>.<project_name>.<apex_domain>` | that env's `domain_default_service` |
| `<project_name>.<apex_domain>` | prod's bare-env default (URL ergonomics) |
| `<apex_domain>` | nothing by default |

These are routing choices, not redirects.

- **Fixed:** DNS is prerequisite infrastructure configured in the registrar's console; `docex` does not manage it. The operator points each env subdomain at the host machine once at setup (see `why registrar`).
- **Elastic:** DNS is project infrastructure (AWS Route53). `docex` provisions one hosted zone per project for its `apex_domain` and emits the environment A-records; the operator NS-delegates to that zone once from the parent domain.

Doctrine reference: `infrastructure/cicl.md § Domain`.
```

### 3c. `registrar.md` (rewrite)

```markdown
# registrar

A domain registrar — NameSilo, GoDaddy, or similar — is **prerequisite infrastructure** under both foundations: the project neither provisions nor manages it. The doctrine treats the registrar as a black box that owns the project's `apex_domain`.

- **Fixed:** the registrar's own DNS routes each environment's subdomain — `dev.<project_name>.<apex_domain>`, `test.…`, `stage.…`, `prod.…`, plus the bare `<project_name>.<apex_domain>` — to the host machine's IP. `docex` does not automate this; the operator wires it once at setup.
- **Elastic:** the registrar delegates DNS authority for the project's zone to AWS Route53 via NS records, so the project's own compiled HCL drives DNS without touching the registrar console after initial delegation.

Doctrine reference: `infrastructure/shape.md § Fixed-Foundation`.
```

### 3d. `secrets.md` (rewrite)

```markdown
# secrets

Environment-specific runtime values — database passwords, API keys, signing keys — that must never be committed. Doctrine uses a `.env`-per-environment source-of-truth model across both foundations, stored at `$pr/infra/secrets/<env>.env` (gitignored).

The **schema** of each `<env>.env` — which keys must exist — is derived deterministically from two sources: the `secrets:` blocks codebases declare in `infra.yml`, and doctrine-mandated keys such as `TELEMETRY_API_KEY`. `docex` manages that schema; only the values are supplied by hand.

- `docex secrets scaffold <env>` reconciles the required key set into `<env>.env`, preserving any values already present. There is **no** committed `example.env` — the schema lives in `docex`, not in a checked-in template.
- The operator fills values by editing `<env>.env` directly, or via `docex secrets set <env> <KEY>` (write-only, so values never enter an agent's context).

Materialization at release:

- **Fixed:** Ansible renders `<env>.env` onto the host; docker-compose reads it at container start.
- **Elastic:** `docex release` pushes each key to SSM Parameter Store at `/<project>/<env>/<KEY>` as a `SecureString`; ECS task definitions reference those paths via `secrets[]`.

The `.env` is authoritative on every release — manual edits to the deployed copy are clobbered — so rotation means editing the `.env`.

Doctrine reference: `infrastructure/configurable.md § Secrets`.
```

### 3e. `cert_manager.md` (rewrite)

```markdown
# cert_manager

TLS certificate provisioning and rotation.

- **Fixed:** built into the project's own traefik (one per project, at the project tier — see `why reverse_proxy`), so each project owns its certs. Traefik uses Let's Encrypt over **HTTP-01**, issuing one cert per `web`-network service per env, fetched lazily as new subdomains appear in its router config and renewed on its own schedule. Zero project-side configuration.
- **Elastic:** a project-tier resource whose mechanism follows the chosen `reverse_proxy`. With an **ALB**, TLS terminates on AWS **ACM** certs; with **`ec2_traefik`**, on traefik's built-in Let's Encrypt. Both use **DNS-01** and provision **two** certs per project — a `stage` cert (`*.stage.<project>.<apex>`, `stage.<project>.<apex>`) and a distinct `prod` cert (`*.prod.<project>.<apex>`, `prod.<project>.<apex>`, `<project>.<apex>`) — keeping production airgapped from staging. Renewal is automatic.

Both paths satisfy the doctrinal guarantee that no project embeds a private key in its repo or treats cert expiry as an operational concern.

Doctrine reference: `infrastructure/cicl.md § Elastic TLS`; `infrastructure/cicl.md § Fixed TLS`.
```

### 3f. `reverse_proxy.md` (rewrite)

```markdown
# reverse_proxy

The doctrine handles HTTP/S ingress asymmetrically across foundations because the natural primitive on each is different.

- **Fixed: Traefik.** One traefik **per project**, at the project tier — brought up by `docex projinfra up development` and named `${project_dns_label}-traefik` — sitting behind a single host-wide HAProxy `web_demux` (see `why web_demux`) that reads the request domain and forwards to the right project's traefik over the shared `docex-ingress` network. (Preinfra services that are not projects — the container registry and the observability backend — run their own dedicated traefiks.) Per-project rather than host-wide is what gives blast-radius protection: one project cannot misconfigure another's routing. Each traefik watches the docker socket, auto-discovers containers carrying the doctrinal `traefik.enable=true` labels, and routes each env's subdomain to the right container. TLS terminates at the project's traefik via Let's Encrypt (see `why cert_manager`), so each project owns its own certs.

- **Elastic: AWS ALB or EC2-with-traefik.** Each project gets its **own** reverse proxy, chosen in `infra.yml` via `reverse_proxy:` (`alb`, `ec2_traefik_eip`, or `ec2_traefik_pip` — elastic only). It lives in the shared master VPC (see `why master_network`). **One reverse proxy per project serves both `stage` and `prod`** via host-based listener rules — not one per environment. An ALB terminates TLS with the project's ACM certs; an EC2-traefik instance uses built-in Let's Encrypt (see `why cert_manager`). Either doubles as the load balancer for a replicated `web` core service in `prod`; internal core services are balanced by service discovery instead. Doctrine-provisioned — not declared as a service in `infra.yml`.

The two answer the same question — "how do requests reach the right container?" — using the primitives each foundation already offers natively, rather than forcing a single cross-foundation abstraction.

Doctrine reference: `infrastructure/shape.md § Elastic-Foundation`; `infrastructure/cicl.md § Reverse Proxy`.
```

### 3g. `environment_config.md` (rewrite)

```markdown
# environment_config

The compiler's per-environment output: the deterministic config artifacts that drive an environment's deployment.

- **Fixed envs (dev, test, and stage/prod on a fixed foundation):** `compose.yml`, plus `playbook.yml`, `inventory.yml`, and `ansible.cfg` for stage/prod.
- **Elastic envs (stage/prod on an elastic foundation):** `main.tf`, a single OpenTofu HCL file containing provider, state backend, the env's security groups, the reverse-proxy wiring (an ALB target group + listener rule, or the EC2-traefik equivalent), ECS services, RDS/S3/etc., and Route53 records. The ECS cluster itself is project-tier, not part of an env's `main.tf`.

All env config is written to `infra/output/<env>/` and is **git-tracked**: a diff shows exactly what an `infra.yml` change produces, so a reviewer sees the full infrastructure impact of a PR. The compiler is deterministic — identical `infra.yml` plus tables produce byte-identical output.

The output is consumed by `docex envinfra up` (the fixed dev loop) and `docex release` (stage/prod). It is the single source of truth for what infrastructure exists; nothing here is hand-edited.

Doctrine reference: `infrastructure/cicl.md § Compiler Output`.
```

### 3h. `network.md` (rewrite)

```markdown
# network

Networks scope which services can reach which others. Each service declares a `networks:` list in `infra.yml`; every service must belong to at least one. The compiler creates one project-scoped network per environment per declared name, formatted `${project_name}-${env_name}-${network_definition_name}` (hyphenated), so environments stay airgapped from one another.

Two foundation realizations:

- **Fixed:** docker networks. Service-to-service communication uses container DNS.
- **Elastic:** AWS security groups **within the shared master VPC** (see `why master_network`). Communication is filtered by SG ingress rules; there is no per-project VPC.

A few network names carry special meaning — see `why web_network` and `why internal_network`. Any other name defaults to closed internal networking.

Doctrine reference: `infrastructure/specifics/networks.md § CICL Interpretation`.
```

### 3i. `web_network.md` (full contents — file was `network_web.md`, renamed in Step 1)

```markdown
# network: web

A service declaring `networks: [web, ...]` is reachable from the public internet over HTTP/S.

- **Fixed:** the container gets Traefik discovery labels (`traefik.enable=true`, host rules, TLS entry-point) and joins the `${project}-${env}-web` docker network, which the **project's own** traefik watches (one per project, at the project tier — see `why reverse_proxy`). That traefik routes requests for the env's subdomain to the container.
- **Elastic:** the project's reverse proxy fronts the service — an ALB target group + listener rule, or the EC2-traefik equivalent (see `why reverse_proxy`). The service's security group accepts ingress only from the reverse proxy; TLS terminates there on the project's cert and traffic forwards inward.

The doctrine reserves `web` as a *special* name precisely so the same `infra.yml` declaration produces the right thing on either foundation without per-foundation knobs.

Doctrine reference: `infrastructure/specifics/networks.md § networks: [web]`.
```

### 3j. `internal_network.md` (full contents — file was `network_internal.md`, renamed in Step 1)

```markdown
# network: internal (and other non-special names)

Any network whose name is not in the doctrine's reserved set defaults to **internal**: reachable only from other services on the same network.

- **Fixed:** a plain user-defined docker bridge with no published host ports, so nothing outside the host can reach it. Services reach each other by container name (which equals `${global_service_name}`). Docker's `internal: true` flag is deliberately **not** used — it adds no ingress protection over this shape and would strip the bridge's masquerade rule, killing egress.
- **Elastic:** an AWS security group **within the shared master VPC** that accepts ingress only from itself — i.e., from other services attached to the same SG.

Internal networks are the doctrine's default and the right choice for backing services, worker queues, and any inter-service plumbing that should never be reachable from the public internet.

**Ingress-only, not an airgap.** A non-`web` network restricts who can reach *in*; it does not restrict reaching *out*. Containers on one have full internet egress on both foundations — via the host's NAT on fixed, via allow-all SG egress and the master VPC's NAT gateway on elastic. Constraining egress per network is deferred doctrine.

Doctrine reference: `infrastructure/specifics/networks.md § networks: [internal]`.
```

### 3k. `master_network.md` (NEW)

```markdown
# master_network

The shared ingress/egress network that ties together every project on an infrastructure side. It is **prerequisite infrastructure** — stood up once per machine or account, outside any single project's control — and shared by all projects.

- **Fixed:** a docker bridge network always named `docex-ingress`. The host-wide `web_demux` (see `why web_demux`) and every project's own traefik (see `why reverse_proxy`) attach to it, so the demux can forward a request to the right project's traefik over this shared network.
- **Elastic:** a master **VPC** shared by all projects in the AWS account. It contains a centralized Internet Gateway, a centralized NAT gateway (see `why nat_gateway`), and four subnets — a public/private pair in the default AZ and a redundant public/private pair in a second AZ (present only to satisfy AWS's two-AZ requirement). Per-project and per-env resources (reverse proxies, SGs, ECS tasks, RDS) are placed *inside* this shared VPC rather than in a per-project VPC.

Because it is shared, no project's compiled output creates it; project and env HCL reference it by name via data sources.

Doctrine reference: `infrastructure/preinfra/fixed_master_network.md § The docex-ingress Network`; `infrastructure/preinfra/elastic_master_network.md § Resources`.
```

### 3l. `web_demux.md` (NEW)

```markdown
# web_demux

The host-wide ingress front door on a **fixed** foundation. **Prerequisite infrastructure** (HAProxy), stood up once per host machine and shared by every project on it; no project provisions it.

It listens on 443/80 and forwards each request to the correct project's own traefik on the basis of domain — 443 by SNI pass-through (it does **not** terminate TLS; the per-project traefik does), 80 by Host header. It and the project traefiks all sit on the shared `docex-ingress` master network (see `why master_network`), which is how it reaches them.

Routing to a per-project traefik rather than to containers directly is what gives blast-radius protection: one project cannot misconfigure another's routing. The elastic foundation has no `web_demux` — there, DNS routes straight to each project's own reverse proxy.

Doctrine reference: `infrastructure/preinfra/fixed_master_network.md § The web_demux Resource`; `infrastructure/shape.md § Fixed-Foundation`.
```

### 3m. `observability_backend.md` (NEW)

```markdown
# observability_backend

The backend application stack — HyperDX by default — that collects, indexes, and displays the project's telemetry (logs, traces, metrics). **Prerequisite infrastructure**: self-hosted or cloud-managed, shared across projects, and never provisioned by a project's compiled output.

A project points at it with the top-level `observability_backend_url:` field in `infra.yml`. That URL must be HTTPS and well-formed (the compiler rejects `http://` and unparseable values; `docex check` probes reachability). It propagates into each core service's paired OTel collector sidecar (see `why telemetry_sidecar`) as `OBSERVABILITY_BACKEND_URL`; the sidecars export OTLP to it in `stage` and `prod`. In `dev`/`test` the sidecar's exporter is `debug` and nothing is forwarded to the backend.

Doctrine reference: `infrastructure/cicl.md § Observability Backend`; `infrastructure/telemetry.md § Observability Backend`.
```

### 3n. `telemetry_sidecar.md` (NEW)

```markdown
# telemetry_sidecar

An OpenTelemetry Collector that runs **paired one-to-one with each emitting core service** — one sidecar per core service, and per replica. It accepts OTLP telemetry from its partner core service and exports it onward to the `observability_backend` (see `why observability_backend`). Application code never talks to the backend directly; it emits through its SDK to the local sidecar.

- **Fixed:** a distinct compose container paired by network namespace (`network_mode: service:<container>`), so it always reaches its partner on loopback. Its `dev`/`test` exporter is `debug`, dumping every signal to the sidecar's own stdout — the dev "watch the telemetry" path.
- **Elastic:** a second container inside the same ECS task definition, one per running task/replica.

The sidecar is environment-tier infrastructure the compiler emits automatically; the project declares nothing for it beyond `observability_backend_url`.

Doctrine reference: `infrastructure/specifics/telemetry_infra.md § Sidecar Image`; `infrastructure/telemetry.md § Collector Sidecar`.
```

### 3o. `nat_gateway.md` (NEW)

```markdown
# nat_gateway

The centralized outbound gateway for the **elastic** master network. **Prerequisite infrastructure**: a single AWS NAT gateway living in the shared master VPC (see `why master_network`) and shared by every project in the account — no project provisions its own.

Egress from any private-subnet resource (ECS tasks, RDS) reaching anything outside the master VPC — third-party APIs, the observability backend, ECR pulls not covered by a VPC endpoint — flows through this one NAT gateway and out via the master VPC's Internet Gateway. Inbound traffic does not use it; that arrives via the project's reverse proxy.

This is an elastic-only resource. On a fixed foundation, outbound access is handled by the host's Docker-managed `iptables` NAT and there is no distinct gateway resource.

Doctrine reference: `infrastructure/specifics/networks.md § Egress`; `infrastructure/preinfra/elastic_master_network.md § Resources`.
```

## Step 4 — Citation-bounding edits on the six CURRENT entries

These entries are content-correct; only the `Doctrine reference:` footers (and two
inline citations) change so the `§` heading sits **inside** the same backtick span
as the path. Make each edit exactly.

### 4a. `backing_service.md`

Replace the final footer line:

- OLD: `Doctrine reference: `` `infrastructure/cicl.md` `` § Service Fields; `` `infrastructure/specifics/transfer_tables.md` ``.`
- NEW: `Doctrine reference: `` `infrastructure/cicl.md § Service Fields` ``; `` `infrastructure/specifics/transfer_tables.md` ``.`

Concretely, the line becomes:

```
Doctrine reference: `infrastructure/cicl.md § Service Fields`; `infrastructure/specifics/transfer_tables.md`.
```

### 4b. `build_image.md`

Two edits.

Inline sentence (currently `See `` `infrastructure/infrastructure.md` `` § Codebase Containers.`) becomes:

```
The image's Dockerfile must declare four canonical stages (`build`, `dev`, `prod`, `test`) — this is a strict doctrine rule, not a convention. See `infrastructure/infrastructure.md § Codebase Containers`.
```

Footer becomes:

```
Doctrine reference: `infrastructure/cicd.md § Build Step`.
```

### 4c. `codebase.md`

Footer becomes:

```
Doctrine reference: `infrastructure/infrastructure.md § Repository Structure`; `infrastructure/cicl.md § Core Services`; `lexicon.md`.
```

### 4d. `core_service.md`

Footer becomes (the inline `` `transfer_tables.md § Resources Translation` `` is already bounded — leave it):

```
Doctrine reference: `infrastructure/infrastructure.md § Repository Structure`; `infrastructure/cicl.md § Core Services`.
```

### 4e. `host_machine.md`

Two edits.

Inline sentence (currently `Multi-host fixed support ... — see `` `infrastructure.md` `` § Deferred.`) becomes:

```
The doctrine commits to **one host per environment** for now. Multi-host fixed support (docker swarm or otherwise) is deferred — see `infrastructure.md § Deferred`.
```

Footer becomes:

```
Doctrine reference: `infrastructure/shape.md § Fixed-Foundation`.
```

### 4f. `container_registry.md` and `service_discovery.md`

No change — their citations are already bounded and their content is current. Do
not touch them.

## Step 5 — Rewrite `index.yml`

Overwrite `docex/doctrine_excerpts/index.yml` with exactly:

```yaml
# Maps `docex why <resource>` to the corresponding markdown file in
# this directory. Resource names should be lowercase, underscore-
# separated, and match the doctrine's `[resource]` notation in
# shape.md. Two keys are deliberate exceptions that are NOT shape.md
# [resource] tokens — see tests/unit/test_doctrine_excerpts_index.py:
#   codebase  — the unit-of-code concept (shape's deployed nouns are
#               core_service / backing_service); a useful `why` lookup.
#   secrets   — a source of the configurable_vars resource, not itself
#               a [resource]; retained as a useful `why` lookup.
registrar: registrar.md
dns: dns.md
host_machine: host_machine.md
web_demux: web_demux.md
master_network: master_network.md
nat_gateway: nat_gateway.md
reverse_proxy: reverse_proxy.md
cert_manager: cert_manager.md
container_registry: container_registry.md
service_discovery: service_discovery.md
observability_backend: observability_backend.md
telemetry_sidecar: telemetry_sidecar.md
build_image: build_image.md
network: network.md
web_network: web_network.md
internal_network: internal_network.md
codebase: codebase.md
core_service: core_service.md
backing_service: backing_service.md
environment_config: environment_config.md
secrets: secrets.md
aws_account: aws_account.md
```

## Step 6 — Add the standing consumer test

Create `docex/tests/unit/test_doctrine_excerpts_index.py` with exactly:

```python
"""Standing consumer for the doctrine_excerpts artifact.

`docex why <resource>` serves prose keyed by `doctrine_excerpts/index.yml`.
That artifact has no compile/runtime consumer, so it drifts silently — this
is the check that catches a key that no longer names a `shape.md` resource
(the `network_web` / `vpc` class of drift). Pure unit test: reads two files,
asserts. No docker, no AWS.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

_REPO = Path(__file__).resolve().parents[3]
_EXCERPTS = _REPO / "docex" / "doctrine_excerpts"
_INDEX = _EXCERPTS / "index.yml"
_SHAPE = _REPO / "doctrine" / "infrastructure" / "shape.md"

# Keys deliberately indexed although they are not shape.md [resource] tokens.
# codebase: the unit-of-code concept (deployed nouns are core_service /
#   backing_service). secrets: a source of the configurable_vars resource.
EXCEPTIONS = {"codebase", "secrets"}

_BRACKET_RE = re.compile(r"\[([a-z][a-z0-9_]*)\]")


def _shape_resources() -> set[str]:
    """Resource nouns named in shape.md: [bracket] tokens plus table-row
    names (aws_account / ecs_cluster appear only as table rows)."""
    text = _SHAPE.read_text()
    resources = set(_BRACKET_RE.findall(text))
    for line in text.splitlines():
        s = line.strip()
        if not s.startswith("|"):
            continue
        first = s.strip("|").split("|", 1)[0].strip()
        if re.fullmatch(r"[a-z][a-z0-9_]*", first):
            resources.add(first)
    return resources


def _index() -> dict[str, str]:
    return yaml.safe_load(_INDEX.read_text())


def test_every_index_key_resolves_to_a_shape_resource() -> None:
    resources = _shape_resources()
    unknown = {k for k in _index() if k not in resources and k not in EXCEPTIONS}
    assert not unknown, (
        "index.yml keys not found as a shape.md [resource] token (nor a "
        f"documented exception {sorted(EXCEPTIONS)}): {sorted(unknown)}"
    )


def test_every_index_value_file_exists() -> None:
    missing = {k: v for k, v in _index().items() if not (_EXCERPTS / v).is_file()}
    assert not missing, f"index.yml points at missing files: {missing}"


def test_no_orphan_excerpt_files() -> None:
    referenced = set(_index().values())
    on_disk = {p.name for p in _EXCERPTS.glob("*.md")}
    orphans = on_disk - referenced
    assert not orphans, (
        f"excerpt .md files not referenced by any index.yml key: {sorted(orphans)}"
    )
```

## Step 7 — Verify

Run from `docex/`, foreground, timeout 600000:

```sh
cd ~/.claude/jean_baudrillard/docex
.venv/bin/python -m pytest tests -q
.venv/bin/python -m pytest tests -q -m integration
```

Expected: default suite = prior baseline **+3** (the three new test functions in
one file; the collection-partition guard must stay green), nothing red. Integration
suite unchanged from baseline (`21 passed`).

Then spot-check `docex why` behavior (renamed keys resolve, retired key 404s):

```sh
cd ~/.claude/jean_baudrillard/docex
.venv/bin/python -m docex why web_network >/dev/null && echo "web_network OK"
.venv/bin/python -m docex why internal_network >/dev/null && echo "internal_network OK"
.venv/bin/python -m docex why master_network >/dev/null && echo "master_network OK"
.venv/bin/python -m docex why vpc; echo "vpc exit=$?  (expect 1 / unknown resource)"
```

## Notes for the executor

- Do **not** edit anything under `doctrine/` or `docex/plans/core/`.
- Do **not** change `why/catalog.py` — behavior is unchanged; it reads `index.yml`.
- Every `Doctrine reference:` footer must have the `§` **inside** the same
  backtick span as the path. This is load-bearing for `linkcheck.py` and is
  verified by measurement after execution.
- Report the two suite counts and any surprises.
```
