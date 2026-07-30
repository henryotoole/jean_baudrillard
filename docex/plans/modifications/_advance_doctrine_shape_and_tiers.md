# Advance Brief: Doctrine Shape & Tier Realignment

This document summarizes a large, uncommitted set of doctrine changes that have just landed in `jean_baudrillard/doctrine/`. The summary's audience is the LLM context that will drive the resulting `docex` advance — i.e. the agent designing and executing the mod cycles that bring `docex` back into alignment with the new doctrine. You are responsible for figuring out *what* changes in `docex`; this document tells you what changed *in the doctrine* and where to read the full detail.

The advance has two distinct driving forces. Their source design docs are:

- `engineer/tmp/tmp_shapechanger.md` — the **shape change** (centralized AWS egress, decentralized AWS ingress, fixed-side per-project traefik with an HAProxy demux upstream).
- `engineer/tmp/change_infra_tier_coherency.md` — the **tier and command-surface consolidation** (cleanup of project-tier vs env-tier, replacing `bootstrap`/`up`/`down` with `preinfra`/`projinfra`/`envinfra`, restructuring `specifics/`).

The doctrine has been edited to reflect both. `docex` has not. That gap is the advance.

Everything below is keyed to the doctrine as it currently sits in the working tree — read the cited files for the load-bearing detail. Treat this document as a map, not a substitute.

---

## Two Major Design Shifts

### Shift 1 — Infrastructure Shape

The "shape" of both foundations has changed substantially. Old shape: per-project VPC on elastic, machine-wide traefik on fixed. New shape: single shared master network on both, with per-project reverse proxies hanging off it.

**Elastic — new shape** (see [`shape.md § Elastic-Foundation`](../../../doctrine/infrastructure/shape.md#elastic-foundation), [`preinfra/elastic_master_network.md`](../../../doctrine/infrastructure/preinfra/elastic_master_network.md), [`reasoning/ingress_and_egress.md`](../../../doctrine/infrastructure/reasoning/ingress_and_egress.md)):

- **One shared master VPC** across all projects in an AWS account. Contains the IGW, a single shared NAT gateway, and four subnets (public/private × two AZs). This is **preinfra**, not project-tier — `docex` does not create it.
- **Centralized egress**: the single NAT gateway serves every project. No more per-project NAT, no more per-project EIP from the finite pool.
- **Decentralized ingress**: every project gets its own reverse proxy on the master VPC. Route53 routes by domain to that proxy.
- **`reverse_proxy:` top-level field in `infra.yml`** (elastic-only) chooses the reverse-proxy implementation:
  - `alb` (default) — AWS ALB.
  - `ec2_traefik_eip` — single EC2 instance running traefik, with an Elastic IP. Stable IP, EIP-quota cost.
  - `ec2_traefik_pip` — same but with an AWS-assigned public IP. No EIP quota; IP changes on stop/start, so a doctrine-emitted systemd unit updates Route53 records on boot.
- **ALB is now project-tier**, not env-tier. One ALB serves both stage and prod via host-based listener rules. Two ACM certs (stage + prod) attached as SNI bindings. **Listener rules** remain env-tier (one per `web` service).
- **Single AZ commitment**. `us-east-1a` is the primary AZ across all projects. Secondary-AZ subnets exist only to satisfy AWS's two-AZ requirements for ALB and RDS; they're unused in practice.
- **Service Connect**: now uses a Cloud Map **private DNS** namespace (was HTTP), named `${project}-${env}` (hyphen, was underscore). Resolvable as `<discoveryName>` from inside a task, `<discoveryName>.<namespace>` from elsewhere in the master VPC.

**Fixed — new shape** (see [`shape.md § Fixed-Foundation`](../../../doctrine/infrastructure/shape.md#fixed-foundation), [`preinfra/fixed_master_network.md`](../../../doctrine/infrastructure/preinfra/fixed_master_network.md), [`projinfra/fixed_reverse_proxy.md`](../../../doctrine/infrastructure/specifics/projinfra/fixed_reverse_proxy.md)):

- **Machine-wide traefik is gone.** Replaced by a **`web_demux` HAProxy** on the host's 443/80 ports — preinfra — that does SNI routing (443) and HTTP routing (80) to the right *per-project* traefik based on the request's domain.
- **Per-project traefik** (`${project_name}-traefik`) is now project-tier. One traefik container per project per side, in the project's projinfra compose stack. Terminates TLS via Let's Encrypt (DNS-01 preferred, HTTP-01 fallback). Joins the host-wide `docex-ingress` bridge plus all four of the project's `-web` networks.
- **`docex-ingress` bridge network** — preinfra docker network that ties HAProxy and every project traefik together.
- **Per-project `-web` networks** (`${project}-${env}-web`, four per side). Project-tier. Declared `external: true` in env compose files; envs *attach* but do not *own*.
- **Container registry is now preinfra** on fixed (Docker Registry V2 on a host, one per host, shared across projects). It is *not* project-tier; `docex` does not create it. See [`preinfra/container_registry.md`](../../../doctrine/infrastructure/preinfra/container_registry.md).

**Domain anatomy — rigidly enforced** (see [`cicl.md § Domain`](../../../doctrine/infrastructure/cicl.md#domain)):

- New canonical form: **`<service>.<env>.<project_name>.<apex_domain>`** (e.g., `api.dev.myproject.example.com`).
- Old top-level field `domain:` → renamed **`apex_domain:`**. The apex must be bare (no subdomains).
- New bare-form routing rules: bare env → env's `domain_default_service`; bare project → prod's bare env; bare apex → nothing.
- **Service-name blacklist**: services cannot be named `dev`, `test`, `stage`, `prod`, `www` (HAProxy needs unambiguous domain parsing).
- **Three-cert TLS structure**: development cert (covers `dev` + `test`), stage cert, prod cert. DNS-01 with wildcards is preferred; HTTP-01 falls back to per-endpoint SANs. See [`cicl.md § TLS Implications`](../../../doctrine/infrastructure/cicl.md#tls-implications).

**Naming policy unification — hyphens become the default** (see [`transfer_tables.md § Naming Policies`](../../../doctrine/infrastructure/specifics/transfer_tables.md#naming-policies)):

- Anything name-resolvable on the data plane uses hyphens: Docker (container/network/volume), ECS (cluster/service/task-def/Service Connect), ALB/target groups, RDS, S3, hostnames.
- Underscores survive **only** for inert AWS record-key identifiers: IAM, SSM path segments, DynamoDB tables.
- Net effect: a service's compiled name is **identical** on fixed Docker and elastic ECS — `${project}-${env}-${svc}` everywhere.
- `docker` policy changed `separator: underscore` → `separator: hyphen`. `ecs` policy changed `separator: underscore` → `separator: hyphen`.
- The **`ecr_repo` policy was removed** entirely. ECR repo names are a two-segment path joined by `/` with each segment's underscores preserved — a shape the single-separator policy machinery cannot express. ECR repo emission is now a hardcoded structural emit, not policy-driven. See [`transfer_tables.md § How structural emitters reference a policy`](../../../doctrine/infrastructure/specifics/transfer_tables.md#how-structural-emitters-reference-a-policy).

**CICL surface changes** (see [`cicl.md`](../../../doctrine/infrastructure/cicl.md)):

- `domain:` → `apex_domain:`.
- `reverse_proxy:` field added (elastic-only); validation rule 18 enforces.
- The `reverse_proxy` *role / backing service* is **gone**. It was previously declarable as a backing service in `infra.yml`; that's no longer valid — the reverse proxy is now project-tier infra, not a CICL service.
- `${backing_services.<db>.sslmode}` is now a provided part on the postgres engine. Load-bearing on elastic because RDS rejects non-SSL connections by default. `migrate.sh` shims must compose the connection string from parts including sslmode.
- New validation rules 13 (`apex_domain` bare), 14 (service-name blacklist), 18 (`reverse_proxy` elastic-only). Old rule 13 ("`web`-network service other than `reverse_proxy` role declares a port") simplified to "every `web`-network service declares a port" since the `reverse_proxy` role is gone.
- **Fargate tier rounding** is now formalized in the doctrine. The compiler computes `(cpu + sidecar_overhead, memory + sidecar_overhead)`, rounds up to the smallest supported Fargate tier, and surfaces the rounding in compile output. Exceeding the largest tier (16 vCPU / 120 GB) is a compile error. See [`cicl.md § Resources`](../../../doctrine/infrastructure/cicl.md#resources) and [`transfer_tables.md § Resources Translation`](../../../doctrine/infrastructure/specifics/transfer_tables.md#resources-translation).

### Shift 2 — Tier Coherency and Command Surface

The doctrine had grown muddled on what counted as "project tier" vs "env tier." It also still treated `bootstrap` (one-shot elastic-only setup) as separate from `up`/`down` (env-tier control). Both are fixed.

**Tier reframe** (see [`infrastructure.md § Infrastructure Tiers`](../../../doctrine/infrastructure/infrastructure.md#infrastructure-tiers), [`lexicon.md`](../../../doctrine/lexicon.md)):

- **Tier = "what scope controls it"**, not "is it replicated across envs." Project-tier resources are *shared by* every env; env-tier resources are *duplicated across* envs.
- Project-tier is no longer elastic-only. **Fixed projects also have project-tier infra now** (the per-project traefik + the four `-web` networks).
- New lexicon synonyms: **`preinfra`**, **`projinfra`**, **`envinfra`**.
- **New first-class concept: "side"** ([`infrastructure.md § Infrastructure Sides`](../../../doctrine/infrastructure/infrastructure.md#infrastructure-sides)). Project-tier infra is duplicated across **development side** (dev + test, always fixed-style) and **production side** (stage + prod, fixed or elastic). The duplication exists because both sides need their own routing surface. For single-machine fixed projects the two sides converge.
- Lexicon adds: `Prerequisite Infrastructure`, `Project Infrastructure`, `Environment Infrastructure`, `Infrastructure Side`, `Apex Domain`, `Master Network`.

**Command surface** (see [`docex.md`](../../../doctrine/infrastructure/docex.md)):

| Old | New | Notes |
| --- | --- | ----- |
| `bootstrap` | **removed** | Elastic-only one-shot, replaced by `projinfra up production` |
| `up <env>` | `envinfra up <env>` | Same behavior, symmetric naming |
| `down <env>` | `envinfra down <env>` | Same behavior, symmetric naming |
| *(none)* | **`preinfra <side>`** | Read-only check of prereq infra existence for development/production side. Does not create. Required to pass before `projinfra up <side>` or `envinfra up`. |
| *(none)* | **`projinfra <direction> <side>`** | Idempotent up/down of project-tier infra for a given side. Replaces `bootstrap` and adds teardown. `down` refuses if envinfra still up; `up` refuses if `preinfra <side>` fails. |
| *(implicit only)* | **`migrate <env>`** | Was always implicit-inside-other-commands. Now an explicit standalone command surface; still invoked implicitly by `envinfra up dev`, `test`, and `release`. |

Other commands keep their names. `release` and `rollback` have docstring updates pointing at the renamed/split specifics files.

**Compiler output layout** (see [`cicl.md § Compiler Output`](../../../doctrine/infrastructure/cicl.md#compiler-output)):

Old layout:
```
infra/output/
├── <env>/...                  # env-tier
└── project/main.tf            # elastic-only, single file
```

New layout:
```
infra/output/
├── <env>/...                  # env-tier (unchanged)
└── project/
    ├── development/
    │   └── docker-compose.yml         # always emitted (dev side is always fixed-style)
    └── production/
        ├── docker-compose.yml         # fixed projects
        ├── playbook.yml / inventory.yml / ansible.cfg  # fixed + remote prod host
        └── main.tf                    # elastic projects
```

Both sides emit on **every** project regardless of foundation. An elastic project still emits `infra/output/project/development/docker-compose.yml` (for the operator's dev machine). All four `-web` networks are emitted on every side regardless of which envs that side hosts — see [`projinfra/projinfra.md § Why all four -web networks live on every side`](../../../doctrine/infrastructure/specifics/projinfra/projinfra.md#why-all-four--web-networks-live-on-every-side).

**Specifics folder restructure** (see [`projinfra/projinfra.md`](../../../doctrine/infrastructure/specifics/projinfra/projinfra.md), [`preinfra/preinfra.md`](../../../doctrine/infrastructure/preinfra/preinfra.md)):

- Old `doctrine/infrastructure/prereq/` → **renamed and expanded** to `doctrine/infrastructure/preinfra/`. Now contains per-resource files (master networks, container registry, telemetry preinfra).
- New folder `doctrine/infrastructure/specifics/projinfra/` — one file per project-tier resource, mirroring the `preinfra/` shape.
- `specifics/elastic_bootstrap.md` — **deleted**. Content dissolved into `projinfra/elastic_*.md` files.
- `specifics/release_mechanism.md` — **split three ways**: `specifics/release.md` (the operation), `specifics/secrets.md`, `specifics/migrations.md`.
- `specifics/networks.md` — **narrowed**. Now scoped to env-tier per-service network attachment only. Project-tier `-web` networks moved to `projinfra/fixed_reverse_proxy.md`; master networks moved to `preinfra/`.
- New folder `doctrine/infrastructure/reasoning/` with `ingress_and_egress.md` documenting the cost-driven case for centralized egress + decentralized ingress.
- New folder `doctrine/charts/` with `ing.md` (ASCII diagram of the new elastic ingress/egress topology).

**Telemetry sidecar — name changes propagate**:

- All `<svc>_otelcol` → `<svc>-otelcol`. Container name, compose service name, ECS container name, log paths, error-message references.
- New doctrine-injected env vars on every core service (in addition to the existing `PROJECT_VERSION`): `OTEL_SERVICE_NAME`, `OTEL_EXPORTER_OTLP_ENDPOINT` (always `http://localhost:4318`), `OTEL_EXPORTER_OTLP_PROTOCOL` (`http/protobuf`), `OTEL_RESOURCE_ATTRIBUTES`. See [`transfer_tables.md § Per-core-service env`](../../../doctrine/infrastructure/specifics/transfer_tables.md#per-core-service-env-both-foundations).

**IAM and ECR move tier**:

- Task-execution IAM role moved from env-tier to **project-tier** (one role per project, used by both stage and prod). See [`projinfra/elastic_iam.md`](../../../doctrine/infrastructure/specifics/projinfra/elastic_iam.md).
- ECR repos moved from env-tier to **project-tier** (one per core service, shared across envs). See [`projinfra/elastic_ecr.md`](../../../doctrine/infrastructure/specifics/projinfra/elastic_ecr.md).
- Route53 zone, ACM certs, OpenTofu state backend (S3 + DDB) are all confirmed project-tier in the new `projinfra/` files. The state backend is the **one** project-tier resource still created directly via the AWS API (because `tofu` can't create the thing it needs to track itself).

**Two-phase elastic projinfra apply** (see [`projinfra/projinfra.md § Two-Phase Production-Side Apply (Elastic)`](../../../doctrine/infrastructure/specifics/projinfra/elastic_route53_zone.md#two-phase-apply-rationale) and [`projinfra/elastic_route53_zone.md`](../../../doctrine/infrastructure/specifics/projinfra/elastic_route53_zone.md)):

- Same two-phase NS-delegation pause as the old `bootstrap`. First invocation runs `tofu apply -target=aws_route53_zone.project`, prints the NS records, exits. Operator NS-delegates at the registrar. Second invocation runs untargeted `tofu apply`.
- Phase detection from `tofu state list`, not separate persisted state.

**Inception flow updates** (see [`practices/inception.md`](../../../doctrine/practices/inception.md)):

- PART III now starts with `./bin/docex preinfra development` check; renumbered subsequent steps.
- PART V now uses `./bin/docex preinfra production` then `./bin/docex projinfra up production` (replacing the old generic prereq check + `bootstrap`).
- `migrate.sh` is noted as "Only if needed" in the example codebase tree.

---

## Per-File Delta Index

### New files

| Path | Purpose |
| ---- | ------- |
| `doctrine/infrastructure/preinfra/preinfra.md` | Preinfra tier overview, pointer to per-resource files |
| `doctrine/infrastructure/preinfra/fixed_master_network.md` | HAProxy `web_demux` + `docex-ingress` bridge — fixed-side preinfra |
| `doctrine/infrastructure/preinfra/elastic_master_network.md` | Master VPC + IGW + NAT + four subnets — elastic preinfra |
| `doctrine/infrastructure/preinfra/container_registry.md` | Docker Registry V2 setup — fixed preinfra |
| `doctrine/infrastructure/preinfra/telemetry_preinfra.md` | HyperDX setup (moved from `prereq/`, updated for new preinfra terms) |
| `doctrine/infrastructure/specifics/projinfra/projinfra.md` | Project-tier overview, four-cell `(foundation × side)` matrix, `projinfra` command behavior |
| `doctrine/infrastructure/specifics/projinfra/fixed_reverse_proxy.md` | Per-project traefik + four `-web` networks; applies to fixed everywhere and elastic dev-side |
| `doctrine/infrastructure/specifics/projinfra/elastic_state_backend.md` | S3 + DynamoDB for OpenTofu state. Created directly via AWS API |
| `doctrine/infrastructure/specifics/projinfra/elastic_route53_zone.md` | Route53 zone, NS delegation, **two-phase apply rationale lives here** |
| `doctrine/infrastructure/specifics/projinfra/elastic_acm_certs.md` | Two ACM certs (stage + prod). ALB-path only |
| `doctrine/infrastructure/specifics/projinfra/elastic_alb.md` | Default reverse-proxy variant. Listener rules are env-tier |
| `doctrine/infrastructure/specifics/projinfra/elastic_ecr.md` | One ECR repo per core service; emitter hardcodes the `/` separator |
| `doctrine/infrastructure/specifics/projinfra/elastic_iam.md` | One task-execution role per project (was per-env) |
| `doctrine/infrastructure/specifics/projinfra/ec2_traefik.md` | Cheaper reverse-proxy alternative. EIP and PIP variants. EBS for cert persistence. SSM Parameter for config delivery. IAM with route53/ssm/ec2-volume perms |
| `doctrine/infrastructure/specifics/migrations.md` | Extracted from old `release_mechanism.md` |
| `doctrine/infrastructure/specifics/release.md` | Successor to `release_mechanism.md`, narrowed to the operation itself |
| `doctrine/infrastructure/specifics/secrets.md` | Extracted from old `release_mechanism.md`; `.env`-as-source-of-truth model |
| `doctrine/infrastructure/reasoning/ingress_and_egress.md` | Cost-driven rationale for centralized egress / decentralized ingress / single AZ |
| `doctrine/charts/ing.md` | ASCII diagram of the new elastic ingress/egress topology |

### Deleted files

| Path | Reason |
| ---- | ------ |
| `doctrine/infrastructure/prereq/overview.md` | Replaced by `preinfra/preinfra.md` |
| `doctrine/infrastructure/prereq/telemetry_preinfra.md` | Moved to `preinfra/telemetry_preinfra.md` |
| `doctrine/infrastructure/specifics/elastic_bootstrap.md` | Dissolved into `projinfra/elastic_*.md` |
| `doctrine/infrastructure/specifics/release_mechanism.md` | Split into `release.md` + `secrets.md` + `migrations.md` |

### Modified files

| Path | What changed |
| ---- | ------------ |
| `doctrine/lexicon.md` | Added `Prerequisite Infrastructure`, `Project Infrastructure`, `Environment Infrastructure`, `Infrastructure Side`, `Apex Domain`, `Master Network` |
| `doctrine/infrastructure/infrastructure.md` | Tier definitions rewritten; **new "Infrastructure Sides" section**; new "Networking" section (ingress / egress); compiler-output paragraph updated; minor wording on `migrate.sh` ("only if needed") |
| `doctrine/infrastructure/shape.md` | Both foundation tables rewritten — most ingress/egress / network / reverse-proxy / cert-manager rows changed tier, mechanism, or both. `[master_network]`, `[nat_gateway]`, `[web_demux]`, `[web_network]`, `[internal_network]` are new resource handles. Concrete example fully rewritten |
| `doctrine/infrastructure/cicl.md` | `domain:` → `apex_domain:`. Domain section rewritten with new canonical form + bare-form rules + TLS-implications subsection. `reverse_proxy:` field added. `reverse_proxy` role removed from example. `DATABASE_SSLMODE` added as a provided part. Validation rules renumbered, several new rules. Compiler-output section rewritten for new tier/side layout. Fargate tier rounding formalized |
| `doctrine/infrastructure/docex.md` | Command surface rewritten: `bootstrap` removed; `up`/`down` merged into `envinfra`; `preinfra` + `projinfra` + `migrate` added. Internal pointers updated to `release.md` / `migrations.md` |
| `doctrine/infrastructure/cicd.md` | `up` → `envinfra up` references throughout. Containerize step gained doctrine prose for the per-invocation `docker login` (fixed vs elastic uniformity). Pointer updates from `release_mechanism.md` → `release.md` and `migrations.md` |
| `doctrine/infrastructure/credentials.md` | One pointer update (release_mechanism → release) |
| `doctrine/infrastructure/tests.md` | `STAGING_URL` derivation now references `apex_domain` + new domain rules |
| `doctrine/infrastructure/telemetry.md` | `<svc>_otelcol` → `<svc>-otelcol` |
| `doctrine/infrastructure/specifics/networks.md` | **Narrowed** to env-tier per-service network attachment only. Project-tier `-web` networks moved to `projinfra/fixed_reverse_proxy.md`; master networks moved to `preinfra/`. Compiled-name section: hyphens are now the rule, no longer just a fixed-foundation exception. Egress documented per foundation |
| `doctrine/infrastructure/specifics/transfer_tables.md` | Naming-policy table: `ecs` underscore→hyphen; `docker` underscore→hyphen; `ecr_repo` row removed. ECR repo emission now structural (hardcoded `/` joiner, per-segment verbatim). Doctrine-default rule rewritten ("hyphens for data-plane, underscores only for IAM/SSM/DDB"). `${env_subdomain}` redefined to match new domain form; `${apex_domain}` and `${bare_project_subdomain}` magic vars added. Per-core-service env extended with four OTEL_* vars. Per-container fixed labels: cert resolver wording updated for per-project traefik. Resources-translation rewritten with explicit Fargate-tier-rounding algorithm. `reverse_proxy` role dropped from the "ships with" list. ECS Service Connect description references private-DNS namespace and hyphenated form |
| `doctrine/infrastructure/specifics/telemetry_infra.md` | `<svc>_otelcol` → `<svc>-otelcol` throughout. Pointers updated for `preinfra/` move and the `release_mechanism.md` split. Task-level resource allocation reworked to defer Fargate-tier-rounding logic to `transfer_tables.md` |
| `doctrine/practices/inception.md` | PART III adds `preinfra development` check; PART V uses `preinfra production` + `projinfra up production` instead of generic prereq check + `bootstrap`. `migrate.sh` is now "only if needed." Internal step numbering bumped. `docex_install.sh` reference updated to "PART I step 8" |
| `skills/docex-preinfra/SKILL.md` | Skill now loads the expanded `preinfra/` set (master networks for both foundations, container registry) instead of just overview + telemetry |

---

## Open Holes and Caveats

A few things in the doctrine are explicitly marked as `TODO` or surface gaps the new doctrine acknowledges but doesn't fix:

- [`docex.md § projinfra`](../../../doctrine/infrastructure/docex.md#projinfra) has two TODOs: deeper foundation-specific behavior, and the two-step elastic flow when NS delegation hasn't yet been performed. The behavior is fully described in [`projinfra/projinfra.md`](../../../doctrine/infrastructure/specifics/projinfra/projinfra.md) and [`projinfra/elastic_route53_zone.md`](../../../doctrine/infrastructure/specifics/projinfra/elastic_route53_zone.md); the TODOs are doctrine-prose follow-ups, not implementation gaps.
- [`preinfra/fixed_master_network.md`](../../../doctrine/infrastructure/preinfra/fixed_master_network.md) has TODO blocks under "Implementation" and "Setup Instructions" — to be filled in after the operator runs the new fixed master setup for the first time.
- [`preinfra/elastic_master_network.md`](../../../doctrine/infrastructure/preinfra/elastic_master_network.md) is similarly thin — explicit TODO to flesh out post-first-setup.
- Old open items still apply: no externally-rotated secrets, single-machine fixed only (no multi-host swarm yet), no path-based ALB routing, no automatic CI/CD triggers.

---

## Suggested Reading Order

If you're going to drive a `docex` advance from this, the doctrine reading order that gives you the cleanest mental model is:

1. **The two driving briefs** in `engineer/tmp/` (the design intent before the doctrine prose was finalized).
2. **`lexicon.md`** — the new vocabulary (preinfra/projinfra/envinfra, side, apex domain, master network).
3. **`infrastructure.md`** — Infrastructure Tiers + Infrastructure Sides + Networking sections. This is the conceptual spine.
4. **`shape.md`** — both foundation tables, then the concrete example. This is where the new shape actually lives.
5. **`cicl.md`** — the new `infra.yml` surface. Domain section, reverse_proxy field, validation rules, compiler output, fargate tier rounding.
6. **`docex.md`** — the new command surface.
7. **`preinfra/`** — what `docex` does *not* manage but does check for.
8. **`specifics/projinfra/`** (overview first, then per-resource) — the heart of what `projinfra up <side>` will create.
9. **`specifics/release.md` + `secrets.md` + `migrations.md`** — the three pieces of what used to be one `release_mechanism.md`.
10. **`specifics/networks.md`** + **`specifics/transfer_tables.md`** — the env-tier emission specifics, plus the naming-policy hyphen unification.
11. **`reasoning/ingress_and_egress.md`** — the *why* behind the elastic shape change. Useful when you hit "but couldn't we just…" moments.
12. **`practices/inception.md`** — the operator workflow these changes plug into.

You'll know you've absorbed it when the answer to "what does `docex` need to do differently?" stops feeling like a list of file edits and starts feeling like a small set of structural moves with predictable ripples.
