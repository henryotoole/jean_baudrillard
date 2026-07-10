---
stratum: conditional
---

# Release Mechanism

This file describes how `./bin/docex release <env>` pushes a built release out to a target environment. It covers the **operation itself** — push semantics, credential handling, idempotency, ansible/tofu execution flow — and cross-references the projinfra and envinfra resources the operation touches rather than re-describing them.

This is documentation for the implementer of `docex` and the curious developer; it is not meant to be force-loaded as general doctrine context. The shorter doctrine-prose summary is in [cicd.md § Release Step](../cicd.md#release-step).

## General Flow

A release combines three orthogonal inputs into a running stack:
- A `build_image` pulled from the project's `container_registry`
- The `environment_config` emitted by `./bin/docex compile` for the target environment
- The environment's `secrets` (per [`config_and_secrets.md`](./config_and_secrets.md))

The operation is **push-initiated** and **idempotent**. A control node (the developer's machine, a CI runner, or `docex` running in its own container on either) initiates the deploy; the target converges to the declared desired state; re-running the same release against an already-converged target is a no-op. This holds for both foundations.

The control node needs **credentials** for the target. The exact form differs by foundation, but the rule is the same: credentials come from the operator's environment (CI secret store, local keychain, OS env vars) and `docex` consumes them from well-known locations. `docex` does not manage credential storage itself.

## Preconditions

`./bin/docex release <env>` refuses to run unless the target's prerequisite and project-tier infrastructure are in place:

1. **Preinfra exists.** `./bin/docex preinfra production` must pass — the master VPC (elastic) or the production host's `docex-ingress` bridge and registry credentials (fixed) must already be in place via the `preinfra-setup` skill.
2. **Projinfra is applied.** `./bin/docex projinfra up production` must have completed — the project's reverse proxy, web networks, ECR repos, etc. must exist before any env-tier resources can attach to them. See [`projinfra/projinfra.md`](./projinfra/projinfra.md).

If either check fails, `release` exits with a clear error pointing at the missing precondition. The operator brings the missing tier up first, then re-runs release.

This precondition chain is the doctrinal layering: preinfra → projinfra → envinfra (or release). Each tier sits on the one below; you cannot deploy an env if its surrounding project infrastructure is missing, and you cannot bring up project infrastructure if its preinfra is missing.

## Fixed Foundation: Ansible

For fixed-foundation projects, `./bin/docex release <env>` invokes `ansible-playbook` (from inside the `docex` container) against an inventory of stage/prod hosts. The playbook itself is emitted by `./bin/docex compile` alongside the compose files for that environment, at `infra/output/<env>/playbook.yml` and `inventory.yml`.

The playbook's tasks, in order:
1. `docker pull` the project's `build_image` at the tagged version. Uses the registry credentials already present in the target host's `~/.docker/config.json` — see [Registry Credentials](#registry-credentials) below.
2. Render the env's compose file and `.env` from the compiled templates onto the host at `/opt/<project>/<env>/`. The compose file declares the env's services and `internal` networks, plus `external: true` references to the project-tier `-web` networks owned by [`projinfra/fixed_reverse_proxy.md`](./projinfra/fixed_reverse_proxy.md).
3. Run the [migration step](./migrations.md#stage-and-prod-on-fixed-foundation) against the new image for any service with `schema_owned_by`. If any migration fails, abort here — `docker compose up -d` is not run.
4. Run `docker compose up -d` from that directory; Docker reconciles running containers to declared state. Env-tier services join the project-tier `-web` networks, where the project traefik (already running) picks them up via its docker provider and routes accordingly.

Each task uses an idempotent Ansible module (`community.docker.docker_image`, `template`, `community.docker.docker_compose_v2`, etc.). Re-running the playbook against an unchanged target produces zero changes.

**The project traefik is *not* touched by release.** It lives at the project tier and was brought up by `./bin/docex projinfra up production`. `release` only adds and removes env-tier containers that *join* the project traefik's networks; the traefik picks up the new services automatically via its docker provider. See [`projinfra/fixed_reverse_proxy.md`](./projinfra/fixed_reverse_proxy.md).

### Host Preinfra Assumed

The playbook does *not* set up the machine-wide HAProxy web demux or the `docex-ingress` bridge network — both are [prerequisite infrastructure](../shape.md#fixed-foundation) on the host, shared across every fixed-foundation project. `./bin/docex preinfra production` verifies the `docex-ingress` bridge exists before release (the demux is operator-managed and not probed directly); if the check fails, set the missing pieces up via the `preinfra-setup` skill before running release.

### SSH Credentials

An SSH private key authorized on each target host for a dedicated `deploy` user (member of the `docker` group, with passwordless sudo so the playbook's `become: true` tasks can elevate without prompting). The keypair is provisioned to the host during fixed-foundation prerequisite setup. The doctrine prescribes one keypair per `(project, env)` — generated once, never shared across projects. The `deploy` user also requires `~/.docker/config.json` populated with credentials for the project's `container_registry` (the playbook's image pulls run as `deploy`); `root` requires the same (`docker compose up` runs under `become: true`).

The private key is placed by the operator at `infra/deploy_creds/<env>` (e.g., `infra/deploy_creds/prod`); `./bin/docex release <env>` reads from this fixed path. The `deploy_creds/` directory is created by the project inception flow pre-populated with a `.gitignore` (so its contents can never be committed) and a `README.md` explaining what belongs there.

This `deploy_creds/` folder is the doctrine's single prescribed home for *file-based* deploy-time credentials introduced by the doctrine itself. Cloud credentials with established conventions (AWS via `~/.aws/credentials`, the docker registry via `~/.docker/config.json`) continue to live in their conventional locations — see [credentials.md § Fixed](../credentials.md#fixed).

### Registry Credentials

The release playbook does not `docker login` during release. The target host's `~/.docker/config.json` is populated out of band as part of `host_machine` prerequisite setup, and `docker pull` succeeds against the project's `container_registry` using whatever creds are already there.

The credential *source* on the operator's machine is symmetric — `~/.docker/config.json` carries the same static creds, placed there by a one-time setup login per the [registry-credentials convention](../credentials.md#fixed-container-registry) — but the operator's side does *not* skip docker login the way release does. `./bin/docex containerize` re-runs `docker login` against those stored creds on every invocation before pushing, per [cicd.md § Containerize Step](../cicd.md#containerize-step). The doctrine accepts the redundant per-invocation login on fixed as the cost of one uniform containerize codepath across both foundations (elastic genuinely needs the per-invocation login because ECR tokens expire after 12 hours).

If the host's creds are missing or stale, `docker pull` fails loudly and the release aborts before any compose changes. The fix is to re-run `docker login` on the host as the deploy user; the doctrine does not attempt to manage this from the operator's side.

`./bin/docex preinfra production` now pre-checks the *presence* of these credentials on the target host (see [container_registry.md § Verification by `docex preinfra`](../preinfra/container_registry.md#verification-by-docex-preinfra)), so a missing credential surfaces at the preinfra tier rather than only as a release-time `docker pull` failure. The release-time failure remains the backstop for the *stale*-credential case, which a presence check cannot catch.

### Inventory

Generated by the compiler from `project.yml`'s name and `infra.yml`'s `apex_domain` field. The stage host resolves to `stage.<project>.<apex_domain>`; the prod host resolves to `<project>.<apex_domain>` (the bare-project domain that points at the same host). Both names resolve to the same machine IP for fixed-foundation projects that share a host, so the inventory entry is just a deterministic handle docex can SSH to. There is no override mechanism: DNS resolution and deployment reachability share the same path, so if a host can't be reached by its domain name, the right fix is to repair DNS, not to introduce a workaround in `infra.yml`. When multi-machine fixed-foundation support is added (currently deferred), this section will grow a list-shaped form to accommodate it.

## Elastic Foundation: OpenTofu

For elastic-foundation projects, `./bin/docex release <env>` performs three operations in sequence:

1. **Push secrets to SSM Parameter Store** per [`config_and_secrets.md`](./config_and_secrets.md). If this fails, no further steps run — the release fails cleanly with no infrastructure changes attempted.
2. **Run migrations** against the existing database per [`migrations.md`](./migrations.md#stage-and-prod-on-elastic-foundation). On non-first releases, this runs *before* the main `tofu apply`; on first-time-ever releases, ordering swaps (see [`migrations.md § First-Time Release of an Env`](./migrations.md#first-time-release-of-an-env)).
3. **Run `tofu apply`** against the env's HCL at `infra/output/<env>/main.tf`. This is where the env-tier rolling deploy happens.

OpenTofu reads the emitted HCL, diffs against the current AWS state, and applies. The env-tier HCL pulls from two places:

- **Preinfra** (master VPC, subnets, NAT, IGW) via tag-based data sources — see [preinfra/elastic_master_network.md](../preinfra/elastic_master_network.md).
- **Projinfra** (Route53 zone, ACM certs, ALB or EC2-traefik, ECR repos, task-execution role) via `data "terraform_remote_state" "project"` — see [`projinfra/projinfra.md`](./projinfra/projinfra.md).

The env-tier resources `tofu apply` actually creates or modifies are:
- The env's security groups (`${project}-${env}-web`, `${project}-${env}-internal`, etc.) — see [networks.md](./networks.md).
- The ECS services for the env's core services (attached into the project-tier `${project}-${env}` cluster, which projinfra already created — see [shape.md](../shape.md#elastic-foundation)).
- Backing services for the env (RDS instances, ElastiCache clusters, etc.).
- For `web`-network services, the reverse-proxy routing wiring: ALB listener rules and target groups on the `alb` path, or the `traefik.*` `dockerLabels` on each service's ECS task definition on the `ec2_traefik_*` path (the traefik ECS provider discovers these; there is no separate release step for it).
- Route53 A-records in the project zone, aimed at the project's reverse proxy.

For a typical release where only the image tag has changed, this updates each core service's ECS task definition, causing ECS to roll the service: pull the new image from ECR, drain old tasks, start new tasks, run health checks. For initial provisioning or for releases that include infrastructure changes, the same apply additionally creates or modifies the env-tier ECS, RDS, listener-rule, and DNS-record resources.

### Credentials

An AWS access key or assumed role with permission to manage the project's resources. Sourced by `tofu` from standard AWS environment variables (`AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`, `AWS_PROFILE`, or OIDC tokens supplied by CI). The doctrine prescribes a dedicated IAM role per project, with least-privilege permissions.

### State

OpenTofu requires a state file to track the mapping between HCL resources and real-world AWS resources. This state is stored in an S3 bucket with DynamoDB locking, both provisioned by [`./bin/docex projinfra up production`](../docex.md#projinfra) once per project — see [`projinfra/elastic_state_backend.md`](./projinfra/elastic_state_backend.md) for the full description. Subsequent `./bin/docex release <env>` runs assume the state backend exists and use it transparently.

Each env has its own state key (`stage/terraform.tfstate`, `prod/terraform.tfstate`) in the shared backend, so a release to `stage` cannot accidentally modify `prod` resources.

### Master VPC Preinfra Assumed

Like the fixed-side HAProxy, the master VPC and its associated resources (NAT gateway, IGW, public/private subnets, VPC endpoints) are prerequisite infrastructure not managed by release. `./bin/docex preinfra production` verifies their existence before release; if it fails, set them up via the `preinfra-setup` skill before running release.

## Why Symmetric Push

Both foundations use push-initiated releases. This is intentional: `./bin/docex release <env>` has the same shape regardless of foundation — compile, decide, run from a place with credentials, watch convergence, re-run any time to reconcile.
