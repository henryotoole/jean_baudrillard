# Pre-Cut Checklist

The agent's manual procedure before cutting a `docex` minor or major version. Walks the two smoke-test projects ([`fixed/`](./fixed/) and [`elastic/`](./elastic/)) through their full release paths against real infrastructure. Surfaces bugs that unit tests can't reach.

**Skip this for patch cuts.** Patches fix unit-testable bugs; the smoke walk would burn real AWS spend without proportionate value.

If anything in this checklist fails, **the cut does not happen.** Fix the bug (in doctrine, `docex`, the seed, or all three — per the five-artifact alignment in [`docex_process.md`](../plans/core/docex_process.md)) and restart from the failing step.

---

## A. Prerequisites — verify once before starting

Every box below must be checked off on the dev machine before the walk begins.

### A.1 Tooling

- [ ] Docker daemon running and reachable.
- [ ] `~/.aws/credentials` present, with permissions covering Route53, ACM, ECR, ECS, RDS, EFS, S3, DynamoDB, SSM, IAM, EC2 (VPC + SG + EIP).
- [ ] AWS region: `us-east-1` (the doctrine's pinned region).
- [ ] `~/.docker/config.json` present, with push permissions for the fixed-project container registry (see A.5) **and** for ECR (AWS creds handle this).
- [ ] `~/.gitconfig` and `~/.ssh/` populated so git operations work from inside the docex container.

### A.2 The docex image to be tested

- [ ] The candidate `docex` image is built locally: `docker images docex:<v>` shows the tag.
- [ ] Re-pin each test project to the candidate version:
  ```
  bash ~/.claude/jean_baudrillard/docex_install.sh test_projects/fixed
  bash ~/.claude/jean_baudrillard/docex_install.sh test_projects/elastic
  ```
- [ ] `cd test_projects/fixed && ./bin/docex --version` prints the candidate version. Same for `elastic/`.

### A.2.1 Test projects are self-contained git repos

The doctrine assumes a project is its own git repository (per [`inception.md`](../../doctrine/practices/inception.md)). The smoke-test projects under `test_projects/` are also tracked at the doctrine-repo level for distribution convenience, but each MUST additionally be its own git repo so docex's CI/CD gate checks (`check`, `merge`, `containerize`) can introspect a real repo state inside the docex container. This is one-time setup at first walk and persists; later walks just verify it's still present.

- [ ] `test_projects/fixed/.git` exists, on branch `main`, with a tag `v<version>` (matching the inner `project.yml`'s `version:`) at HEAD and a clean working tree. If not, initialize per [`test_projects.md § Why the test projects are their own git repos`](../plans/core/test_projects.md#why-the-test-projects-are-their-own-git-repos).
- [ ] Same for `test_projects/elastic/`.

Edits inside `test_projects/*/` dirty both the inner repo and the outer doctrine repo. Commit inner-first per [`test_projects.md § Commit cadence`](../plans/core/test_projects.md#commit-cadence).

### A.3 Preinfra — both sides

The post-1.0.0 doctrine separates preinfra (machine-/account-wide), projinfra (per-project), and envinfra (per-env). Preinfra must exist before any `projinfra up` will run. Use the `docex-preinfra` skill if anything below is missing or drifted.

#### A.3.1 Development side (fixed-style, on the dev machine)

- [ ] **HAProxy `web_demux`** is installed and running on the dev machine, listening on `:443` (SNI pass-through) and `:80` (HTTP host routing). HAProxy parses the request domain and forwards to the project traefik container named `${project_dns_label}-traefik` on the `docex-ingress` network — `project_dns_label` is the underscored project name with underscores translated to hyphens and lowercased (e.g. `docex_smoke_fixed` → `docex-smoke-fixed`). See [`fixed_master_network.md`](../../doctrine/infrastructure/preinfra/fixed_master_network.md).
- [ ] **`docex-ingress`** docker bridge network exists on the dev machine. `docker network ls | grep docex-ingress` returns one entry. Created with `docker network create docex-ingress` if absent.

No traefik env vars are required. Fixed-foundation certs use the **HTTP-01** ACME challenge (Gap A / mod 051), served on the `web` entrypoint (`:80`) that the HAProxy demux already forwards by Host header — there is **no** `TRAEFIK_DNS_PROVIDER` prerequisite (HTTP-01 needs no DNS-provider credentials). `TRAEFIK_ACME_EMAIL` is **optional**: Let's Encrypt registers fine with no contact email; setting it only enables LE expiry-reminder emails. (Threading it through docex is a deferred future option — mod 053 / F2 decision A.)

`./bin/docex preinfra development` (run from either test-project root, since it checks dev-side machine state which is project-agnostic) probes the bridge + HAProxy and exits 0 only when both are present.

#### A.3.2 Production side (elastic; only for the elastic walk)

- [ ] **Master VPC** exists in the operator's AWS account with the tags `Name=docex-master-vpc` and `managed_by=docex-preinfra`. The four subnets (public + private in primary AZ `us-east-1a`; redundant public + private in a secondary AZ) carry `tier=public` / `tier=private` tags. The primary-AZ subnet is discovered via `availability-zone=us-east-1a` filter (no tag required for AZ). See [`elastic_master_network.md`](../../doctrine/infrastructure/preinfra/elastic_master_network.md) and mod 041.
- [ ] **NAT gateway** is present in the public subnet of the primary AZ.
- [ ] **`docex-preinfra` skill** at `~/.claude/skills/docex-preinfra/SKILL.md` documents the tag scheme above. If the skill is stale, fix it as part of pre-walk setup.

`./bin/docex preinfra production` (run from the elastic project root) probes the master VPC + 4 subnets + primary-AZ subnet via tag discovery and exits 0 only when all are present.

### A.4 DNS — apex zone

Both test projects share the parent apex `luxrnd.tech` (Route53). The fixed project resolves the host machine via env-subdomain wildcards under the parent zone; the elastic project uses a delegated child zone (provisioned by `projinfra up production`).

#### A.4.1 Fixed walk DNS

The fixed project's bare apex is `luxrnd.tech` and the project segment derives to `docex-smoke-fixed`. The dev machine's public IP (`$DEV_IP`) needs to be reachable at every per-env host:

- [ ] `dev.docex-smoke-fixed.luxrnd.tech       A → $DEV_IP`
- [ ] `*.dev.docex-smoke-fixed.luxrnd.tech     A → $DEV_IP`
- [ ] `test.docex-smoke-fixed.luxrnd.tech      A → $DEV_IP`
- [ ] `*.test.docex-smoke-fixed.luxrnd.tech    A → $DEV_IP`
- [ ] `stage.docex-smoke-fixed.luxrnd.tech     A → $DEV_IP`
- [ ] `*.stage.docex-smoke-fixed.luxrnd.tech   A → $DEV_IP`
- [ ] `prod.docex-smoke-fixed.luxrnd.tech      A → $DEV_IP`
- [ ] `*.prod.docex-smoke-fixed.luxrnd.tech    A → $DEV_IP`
- [ ] `docex-smoke-fixed.luxrnd.tech           A → $DEV_IP` (bare-project; routes prod's `domain_default_service`)

Verify each: `dig +short <subdomain>` returns `$DEV_IP`.

#### A.4.2 Elastic walk DNS

`docex projinfra up production` creates a Route53 zone for `docex-smoke-elastic.luxrnd.tech` (project zone, child of `luxrnd.tech`). Between phase 1 and phase 2 of the projinfra apply, the operator NS-delegates from the parent `luxrnd.tech` zone.

- [ ] Operator has Route53 admin on `luxrnd.tech`.
- [ ] **Nothing else to pre-create.** Phase 1 prints the NS records to set on the parent.

### A.5 Container registry — fixed

- [ ] A Docker Registry V2 instance is reachable at `https://registry.luxrnd.tech` from the dev machine and from itself when serving as the `prod` host.
- [ ] The **operator's** `~/.docker/config.json` has credentials for this registry. This is the push side, used by `docex containerize`. Pull-side credentials (`deploy` and `root` on the target host) are covered in A.7.
- [ ] If running the registry locally on the dev machine: it persists images to a volume (so the `release prod` pull side finds them after `release stage` pushed them).

### A.6 Observability backend

- [ ] HyperDX (or equivalent OTLP-receiving backend) reachable at `https://hyperdx.luxrnd.tech` (the URL declared in both test projects' `infra.yml` as `observability_backend_url`). `curl -k https://hyperdx.luxrnd.tech/` returns 2xx/3xx/4xx (anything but a connection error). Sidecars in stage/prod will export here; without the backend the sidecars start cleanly but exports fail at runtime.
- [ ] A `TELEMETRY_API_KEY` value usable against the backend, obtained from HyperDX. Goes into `infra/secrets/{stage,prod}.env` per A.8.

### A.7 Fixed deploy credentials and deploy-target user

Per [`release_mechanism.md § Fixed Foundation: Ansible`](../../doctrine/infrastructure/specifics/release_mechanism.md#fixed-foundation-ansible), the rendered playbook lands on the deploy target as a dedicated `deploy` user — member of the `docker` group, with passwordless sudo so `become: true` tasks can elevate without prompting. The dev machine doubles as the deploy target for this smoke walk, so the user must exist on it locally.

- [ ] Create the `deploy` user with docker group membership and passwordless sudo, if not present:
  ```
  sudo useradd -m -s /bin/bash -G docker deploy
  echo "deploy ALL=(ALL) NOPASSWD:ALL" | sudo tee /etc/sudoers.d/deploy-nopasswd
  sudo chmod 0440 /etc/sudoers.d/deploy-nopasswd
  ```
- [ ] Generate an SSH keypair for each env if not already present:
  ```
  ssh-keygen -t ed25519 -f test_projects/fixed/infra/deploy_creds/stage -N ''
  ssh-keygen -t ed25519 -f test_projects/fixed/infra/deploy_creds/prod -N ''
  ```
- [ ] Authorize both public keys (`stage.pub`, `prod.pub`) for the `deploy` user on the deploy target:
  ```
  sudo install -d -m 700 -o deploy -g deploy /home/deploy/.ssh
  sudo install -m 600 -o deploy -g deploy /dev/null /home/deploy/.ssh/authorized_keys
  cat test_projects/fixed/infra/deploy_creds/stage.pub test_projects/fixed/infra/deploy_creds/prod.pub | sudo tee -a /home/deploy/.ssh/authorized_keys >/dev/null
  ```
- [ ] `docker login <registry>` as the `deploy` user, so unprivileged `docker compose` invocations (image pulls during release) can authenticate:
  ```
  sudo -u deploy docker login registry.luxrnd.tech
  ```
- [ ] `docker login <registry>` as `root` as well, because the emitted playbook uses `become: true` and runs `docker compose` as root:
  ```
  sudo docker login registry.luxrnd.tech
  ```

### A.8 Per-project secrets — both foundations

The doctrine's `infra/secrets/<env>.env` files are gitignored. They must exist with real values before any `envinfra up`/`release` runs against an env.

For each project (`fixed/`, `elastic/`), after step C.2's `docex compile` writes `example.env`:

- [ ] Create `infra/secrets/dev.env`, `test.env`, `stage.env`, `prod.env` by copying `example.env` as a template.
- [ ] Fill in every `POSTGRES_*` value (the agent chooses; these are also the prod credentials).
- [ ] `stage.env` and `prod.env` additionally need `TELEMETRY_API_KEY=<value from A.6>`.

---

## B. Doctrine-conformance audit — run before any provisioning

Before running `docex compile` or any release command, walk this audit against each test project's tree. Each item cites the doctrine doc that prescribes it. If any item fails, the seed is out of alignment with current doctrine and must be repaired (in the seed, in doctrine, or both — per the five-artifact alignment rule in [`docex_process.md`](../plans/core/docex_process.md)) before the smoke walk proceeds.

Run this audit *once per cut*, against each project independently.

- [ ] **B.1 Project root layout** — `project.yml`, `README.md`, `CHANGELOG.md`, `.gitignore`, `bin/docex`, `core/`, `infra/`, `plans/` all present. Per [`inception.md`](../../doctrine/practices/inception.md) PART I step 7 and [`infrastructure.md § Codebase Structure`](../../doctrine/infrastructure/infrastructure.md#codebase-structure).
- [ ] **B.2 `project.yml` shape** — declares `name`, `version`, `docex_version`. Per [`infrastructure.md § Project Config`](../../doctrine/infrastructure/infrastructure.md#project-config).
- [ ] **B.3 `infra.yml` shape** — declares `apex_domain` as a bare apex (no project segment), and (elastic only) `reverse_proxy` (default `alb`). Old `domain:` field absent. Per [`cicl.md`](../../doctrine/infrastructure/cicl.md) mod 031.
- [ ] **B.4 CHANGELOG conventions** — follows Keep a Changelog + SemVer (Unreleased section present). Per [`version_control.md § Changelog`](../../doctrine/infrastructure/version_control.md#changelog).
- [ ] **B.5 `infra.yml` validates** — `docex compile` succeeds with no errors. Per [`cicl.md § Validation Rules`](../../doctrine/infrastructure/cicl.md#validation-rules).
- [ ] **B.6 Core service Dockerfiles** — every core service has a Dockerfile with `build`, `dev`, `prod`, `test` stages. Per [`infrastructure.md § Core Service Containers`](../../doctrine/infrastructure/infrastructure.md#core-service-containers).
- [ ] **B.7 Core service scripts** — every core service has `build.sh` and `test.sh`; services owning a relational_db schema additionally have `migrate.sh` and `migrations/`. Per [`cicd.md § Build Step, § Build Test Step, § Migrate Step`](../../doctrine/infrastructure/cicd.md).
- [ ] **B.8 `migrate.sh` builds DSN from parts** — including `${DATABASE_SSLMODE}`. No hard-coded `sslmode=disable` or `sslmode=require`. RDS rejects non-SSL on elastic; the doctrine's parts-only model keeps the shim foundation-agnostic. Per [`migrations.md`](../../doctrine/infrastructure/specifics/migrations.md).
- [ ] **B.9 Provider contracts present** — every provider core service has a contract at `infra/contracts/<svc>.<format>.yml`. Per [`contracts.md`](../../doctrine/infrastructure/contracts.md).
- [ ] **B.10 Health endpoints declared** — every `web`-network core service's contract declares `GET /health`; if it depends on other core services, also `GET /health/<other>`. Per [`contracts.md § Health Checks`](../../doctrine/infrastructure/contracts.md#health-checks).
- [ ] **B.11 Hex layout** — each core service contains `src/root.py` (composition root); each hex module contains `domain/`, `ports/{driving,driven}/`, `adapters/{driving,driven}/`, `alogic/`. Per [`hex_overview.md § Project Structure`](../../doctrine/hexagonal_architecture/hex_overview.md#project-structure) and [`internal_dependency_rules.md § Composition Root`](../../doctrine/hexagonal_architecture/internal_dependency_rules.md#composition-root).
- [ ] **B.12 Migrations idempotent + reversible** — every `core/<svc>/migrations/*.sql` has both `-- migrate:up` and `-- migrate:down` sections. Per [`databases.md § Migrations`](../../doctrine/practices/databases.md#migrations).
- [ ] **B.13 Stage tester present** — `infra/stage/Dockerfile`, `infra/stage/stage_test.sh`, `infra/stage/tests/` all populated. Per [`tests.md § Staging Tests`](../../doctrine/infrastructure/tests.md#staging-tests).
- [ ] **B.14 Foundation-irrelevant code parity** — `diff -r test_projects/fixed/core test_projects/elastic/core` produces no output (other than `__pycache__` / `dist/` which are gitignored). If application code differs, the parts-only env model is leaking foundation specifics — that's a doctrine bug.
- [ ] **B.15 Data-plane names hyphenate** — `grep -rE '{project_name_with_underscores}' infra/output/` (e.g. `docex_smoke_elastic`) finds only AWS record-key identifiers (IAM, SSM, DDB), tags, comments, and ECR repo names. No occurrence of an underscored project segment on a docker network/container/volume name, ECS Service Connect namespace, Route53 zone or record, or ACM cert. Per mod 030's hyphen-on-data-plane rule plus mod 046's leak fix.

---

## C. Walk: docex_smoke_fixed

`cd test_projects/fixed/` for everything below. Each `./bin/docex` invocation re-uses the version pinned in `project.yml`.

### C.1 Preinfra + Projinfra

- [ ] `./bin/docex preinfra development` — exits 0. (HAProxy + `docex-ingress` present per A.3.1.)
- [ ] `./bin/docex projinfra up development` — brings up the four `${project_dns_label}-{dev,test,stage,prod}-web` networks and the per-project traefik container. The traefik joins all four `-web` networks plus `docex-ingress`. No traefik env vars are required: fixed certs use HTTP-01 (Gap A), and `TRAEFIK_ACME_EMAIL` is optional (see A.3.1).
  - **Ordering:** this must run *after* C.2's `docex compile`, since `projinfra up development` reads the compiled `infra/output/project/development/docker-compose.yml`. The numbered C.1/C.2 order here is presentational; in practice run `compile` first (compile is also idempotent and re-run defensively by most commands).
- [ ] For single-machine fixed (dev box also hosts prod): `./bin/docex projinfra up production` — idempotent no-op since dev and prod converge on the same host.

### C.2 Compile

- [ ] `./bin/docex compile` — succeeds, produces `infra/output/{dev,test,stage,prod}/docker-compose.yml`, `infra/output/stage/{playbook.yml,inventory.yml,ansible.cfg}`, same for `prod`, `infra/output/project/{development,production}/docker-compose.yml`, plus `infra/secrets/example.env`.

### C.3 Secrets

- [ ] Confirm A.8 was performed for `fixed/` — `dev.env`, `test.env`, `stage.env`, `prod.env` all populated.

### C.4 Dev sanity (optional but recommended)

- [ ] `./bin/docex envinfra up dev` — stack comes up; `https://dev.docex-smoke-fixed.luxrnd.tech/health` returns 200 with a `version` field.
- [ ] `./bin/docex envinfra down dev` — stack tears down (named volumes preserved).

### C.5 Test

- [ ] `./bin/docex test` — exits 0. Includes unit + integration + contract tests across both core services.

### C.6 Check + Containerize

> **Feature-branch prerequisite (mod 053 / F8).** `check` and `merge` require a real feature-branch shape: `main` must sit at the **prior** release, and the **new** version (bumped `project.yml`) must live on a **feature branch** checked out now. `check` creates an ephemeral worktree merging the feature branch with `origin/main` and runs the gate checks (including "version bumped" and "version not yet released") against that merge. On a single-commit `main` with no feature branch the version-bump gate has nothing to compare against. Restructure the seed's git history to this shape by hand before C.6 if it isn't already (this is the by-hand restructure the smoke walk performs).

- [ ] `./bin/docex check` — exits 0. Runs gate checks against an ephemeral worktree (feature branch ⊕ `origin/main`).
- [ ] `./bin/docex containerize` — succeeds; both `registry.luxrnd.tech/docex_smoke_fixed/web:<v>` and `registry.luxrnd.tech/docex_smoke_fixed/worker:<v>` push successfully. (ECR repo names preserve project-segment underscores per mod 030's structural emitter — this is correct.)

### C.7 Release stage

- [ ] `./bin/docex release stage` — ansible playbook completes; `https://stage.docex-smoke-fixed.luxrnd.tech/health` returns 200.

### C.8 Stagetest

- [ ] `./bin/docex stagetest` — exits 0. The smoke test in `infra/stage/tests/` POSTs to `/pings`, probes `/health`, and probes `/health/probe` + `/health/events` for the project-local backings.

### C.9 Release prod

- [ ] `./bin/docex release prod` — completes. Three URLs must all return 200 with the same `version` field (prod's `domain_default_service` answers at all three):
  - `https://web.prod.docex-smoke-fixed.luxrnd.tech/health` (canonical)
  - `https://prod.docex-smoke-fixed.luxrnd.tech/health` (bare-env)
  - `https://docex-smoke-fixed.luxrnd.tech/health` (bare-project ergonomic, replacing the pre-1.0.0 `www` convention)
- [ ] POST a ping to `https://docex-smoke-fixed.luxrnd.tech/pings` — returns 201.
- [ ] After ~5s, query the prod postgres database directly: the ping row exists and has a non-NULL `processed_at` (worker picked it up).

### C.10 Rollback walk

Exercises `docex rollback` against the real fixed-foundation prod env. The current version was just deployed (C.9); to roll back, we need a *prior* version in the registry. Bump the test project once and re-deploy so two versions coexist, then roll back to the older one.

- [ ] Bump the test project's `project.yml` version (e.g. 0.0.X → 0.0.X+1). Inner-repo commit per `test_projects.md § Commit cadence`; force-move (or re-create) the `v<version>` tag at the new HEAD.
- [ ] `./bin/docex containerize` — pushes `v0.0.X+1` to the registry alongside `v0.0.X`.
- [ ] `./bin/docex release prod` — deploys v0.0.X+1; the three `/health` URLs report v0.0.X+1.
- [ ] `./bin/docex rollback prod 0.0.X` — recompiles v0.0.X in an ephemeral worktree, ansible re-renders the older compose with `--skip-tags migrate`, prod converges on v0.0.X.
- [ ] The three `/health` URLs report v0.0.X. The prior ping row still has its `processed_at` populated (schema unchanged across this micro-version step).
- [ ] `./bin/docex rollback prod 0.0.X --dry-run` (against the now-rolled-back env) — exits 0 and prints `release: prod dry-run completed (ansible --check).` with no state mutation. Optional sanity check; skip if pressed for time.

### C.11 Teardown

- [ ] `bash teardown.sh` — succeeds. Brings down every env's compose stack with named volumes, deletes registry images for this project, then removes the project traefik / four `-web` networks (the `projinfra down` step). Compiled output is cleared.
- [ ] `bash verify_clean.sh` — exits 0. No lingering containers, networks, volumes, or registry images carry the project's name prefix (underscored OR hyphenated form).

---

## D. Walk: docex_smoke_elastic

`cd test_projects/elastic/` for everything below.

### D.1 Preinfra

- [ ] `./bin/docex preinfra development` — exits 0. (Elastic projects still run `dev`/`test` envs as local docker stacks, so dev-side preinfra applies here too.)
- [ ] `./bin/docex preinfra production` — exits 0. (Master VPC + 4 subnets + primary-AZ subnet present per A.3.2.)

### D.2 Projinfra dev side

- [ ] `./bin/docex projinfra up development` — same shape as the fixed-project dev side (four `-web` networks + per-project traefik). Required because `envinfra up dev`/`test` joins these networks.

### D.3 Projinfra production (two phases)

Elastic production-side projinfra applies in two phases separated by an operator NS-delegation step.

- [ ] `./bin/docex projinfra up production` — **phase 1**: creates the tofu state backend (S3 + DynamoDB), then runs `tofu apply -target=aws_route53_zone.project`. Prints the project zone's NS records and exits 0.
- [ ] Manually NS-delegate from the parent `luxrnd.tech` Route53 zone: create an NS record at `docex-smoke-elastic.luxrnd.tech` whose value is the four NS hostnames phase 1 printed.
- [ ] Wait for propagation: `dig NS docex-smoke-elastic.luxrnd.tech @1.1.1.1` returns the AWS nameservers. Typical: 1–5 minutes; worst-case: an hour at some registrars.
- [ ] `./bin/docex projinfra up production` (again) — **phase 2**: untargeted `tofu apply` against the project tier. ACM certs validate against the now-reachable zone; ALB, ECR repos, IAM role come up.

### D.4 Compile

- [ ] `./bin/docex compile` — succeeds; produces `infra/output/{dev,test}/docker-compose.yml`, `infra/output/{stage,prod}/main.tf`, `infra/output/project/{development/docker-compose.yml,production/main.tf}` (production was already applied by D.3), and `infra/secrets/example.env`.

### D.5 Secrets

- [ ] Confirm A.8 was performed for `elastic/` — `dev.env`, `test.env`, `stage.env`, `prod.env` all populated.

### D.6 Dev sanity (optional but recommended)

`dev` and `test` envs run as fixed compose stacks even on an elastic-foundation project (per [`shape2.md § Shape and Environment`](../../doctrine/infrastructure/shape2.md#shape-and-environment)).

- [ ] `./bin/docex envinfra up dev` — stack comes up locally. (No DNS for `dev.docex-smoke-elastic.luxrnd.tech` exists pre-projinfra; hit the service directly via the dev machine or check the per-project traefik routes it.)
- [ ] `./bin/docex envinfra down dev`.

### D.7 Test

- [ ] `./bin/docex test` — exits 0.

### D.8 Check + Containerize

> **Feature-branch prerequisite (mod 053 / F8).** As in C.6: `check`/`merge` need `main` at the prior release and the new version on a feature branch checked out now (the worktree merges feature ⊕ `origin/main`). Also note the D.3/D.7 ordering — `compile` must run before any `projinfra up`, since `projinfra up production`'s phase-2 `tofu apply` reads the compiled project-tier `main.tf`.

- [ ] `./bin/docex check` — exits 0.
- [ ] `./bin/docex containerize` — succeeds; images push to the project ECR (`<account>.dkr.ecr.us-east-1.amazonaws.com/docex_smoke_elastic/{web,worker}:<v>`). Authenticates against ECR via `aws ecr get-login-password` per invocation.

### D.9 Release stage

- [ ] `./bin/docex release stage` — first-time-release path detected (ECS cluster absent); ordering swaps to `SSM push → tofu apply → migrate`. ALB listener rules, ECS cluster, ECS services for `web`/`worker`/`probe`/`events`, RDS instance, EFS filesystem + mount targets for `events`, all come up. `https://stage.docex-smoke-elastic.luxrnd.tech/health` returns 200.

### D.10 Stagetest

- [ ] `./bin/docex stagetest` — exits 0. Covers `/health`, `/health/probe`, `/health/events`, and the POST `/pings` critical path.

### D.11 Release prod

- [ ] `./bin/docex release prod` — first-time-release path for prod env. Provisions the prod ECS services + RDS + EFS alongside stage on the same project-tier ALB.
- [ ] Three `/health` URLs return 200 (same shape as fixed C.9):
  - `https://web.prod.docex-smoke-elastic.luxrnd.tech/health` (canonical)
  - `https://prod.docex-smoke-elastic.luxrnd.tech/health` (bare-env)
  - `https://docex-smoke-elastic.luxrnd.tech/health` (bare-project)
- [ ] POST a ping to `https://docex-smoke-elastic.luxrnd.tech/pings` — returns 201; after ~5s the prod RDS shows the row with non-NULL `processed_at`.

### D.12 Rollback walk

Same intent as C.10 but against elastic prod. The rollback path pushes SSM and runs an unrestricted `tofu apply` against the recompiled v0.0.X HCL — no migration RunTask, no pre-migrate targeted apply.

- [ ] Bump the test project's `project.yml` version (e.g. 0.0.X → 0.0.X+1). Inner-repo commit + tag move.
- [ ] `./bin/docex containerize` — pushes `v0.0.X+1` to ECR alongside `v0.0.X`.
- [ ] `./bin/docex release prod` — deploys v0.0.X+1 (steady-state path now that prod exists).
- [ ] `./bin/docex rollback prod 0.0.X` — recompiles v0.0.X in an ephemeral worktree, pushes SSM, runs `tofu apply` (no targets), ECS rolls v0.0.X out.
- [ ] The three `/health` URLs report v0.0.X. RDS data preserved.
- [ ] `./bin/docex rollback prod 0.0.X --dry-run` — exits 0; `tofu plan` runs, SSM push and `tofu apply` do NOT. Optional.

### D.13 Teardown

- [ ] `bash teardown.sh` — disables RDS deletion_protection (polled until landed in AWS), direct-deletes RDS instances with `--skip-final-snapshot` (polled until gone), purges ECR images/repos, then runs `tofu destroy` for prod, stage, project tier in that order. Cleans SSM parameters and the tofu state bucket + lock table.
- [ ] `bash verify_clean.sh` — exits 0. AWS API queries for every doctrine-emitted resource type filtered by project-name prefix return empty.

---

## E. After both walks succeed

- [ ] Both `verify_clean.sh` runs are green.
- [ ] No leftover state in Route53 except the parent `luxrnd.tech` zone and any other unrelated records the operator runs.
- [ ] No registry images for `docex_smoke_fixed` or `docex_smoke_elastic` remain.
- [ ] AWS cost report for the smoke-test window matches expectations (~$X for 1–2 hours of stage+prod elastic infra; verify against running tally).

The cut is now safe to perform per [`docex_process.md § Cutting a version`](../plans/core/docex_process.md#cutting-a-version).
