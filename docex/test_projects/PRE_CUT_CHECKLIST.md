# Pre-Cut Checklist

The operator's manual procedure before cutting a `docex` minor or major version. Walks the two smoke-test projects ([`fixed/`](./fixed/) and [`elastic/`](./elastic/)) through their full release paths against real infrastructure. Surfaces bugs that unit tests can't reach.

**Skip this for patch cuts.** Patches fix unit-testable bugs; the smoke test would burn real AWS spend without proportionate value.

If anything in this checklist fails, **the cut does not happen.** Fix the bug (in doctrine, `docex`, the seed, or all three — per the five-artifact alignment in [`docex_process.md`](../plans/core/docex_process.md)) and restart from the failing step.

---

## A. Prerequisites — verify once before starting

Every box below must be checked off on the dev machine before the walk begins.

### A.1 Tooling

- [ ] Docker daemon running and reachable.
- [ ] `~/.aws/credentials` present, with permissions covering Route53, ACM, ECR, ECS, RDS, S3, DynamoDB, SSM, IAM, EC2 (VPC + SG).
- [ ] AWS region: `us-east-1` (the doctrine's pinned region).
- [ ] `~/.docker/config.json` present, with push permissions for the fixed-project container registry (see A.4) **and** for ECR (AWS creds handle this).
- [ ] `~/.gitconfig` and `~/.ssh/` populated so git operations work from inside the docex container.

### A.2 The docex image to be tested

- [ ] The candidate `docex` image is built locally: `docker images docex:<v>` shows the tag.
- [ ] Re-pin each test project to the candidate version:
  ```
  bash ~/.claude/jean_baudrillard/docex_install.sh test_projects/fixed
  bash ~/.claude/jean_baudrillard/docex_install.sh test_projects/elastic
  ```
- [ ] `cd test_projects/fixed && ./bin/docex --version` prints the candidate version. Same for `elastic/`.

### A.3 DNS — fixed foundation

The fixed project's domain is `doctrine-fixed.luxrnd.tech`, served from this dev machine. The operator's Route53 zone for `luxrnd.tech` must contain records pointing the env subdomains (and their per-service wildcards) at the dev machine's public IP `$DEV_IP`:

- [ ] `dev.doctrine-fixed.luxrnd.tech    A → $DEV_IP`
- [ ] `*.dev.doctrine-fixed.luxrnd.tech  A → $DEV_IP`
- [ ] `test.doctrine-fixed.luxrnd.tech   A → $DEV_IP`
- [ ] `*.test.doctrine-fixed.luxrnd.tech A → $DEV_IP`
- [ ] `stage.doctrine-fixed.luxrnd.tech  A → $DEV_IP`
- [ ] `*.stage.doctrine-fixed.luxrnd.tech A → $DEV_IP`
- [ ] `www.doctrine-fixed.luxrnd.tech    A → $DEV_IP`
- [ ] `*.www.doctrine-fixed.luxrnd.tech  A → $DEV_IP`

Verify each subdomain resolves: `dig +short <subdomain>` should return `$DEV_IP`.

### A.4 DNS — elastic foundation

The elastic project's domain is `doctrine-elastic.luxrnd.tech`. `docex bootstrap` creates a Route53 hosted zone for it (project-tier). Between bootstrap phase 1 and phase 2, the operator NS-delegates from the parent `luxrnd.tech` zone using the NS records that phase 1 prints.

No DNS records to pre-create — just confirm the operator has Route53 admin on the parent zone.

### A.5 Container registry — fixed

- [ ] A Docker Registry V2 instance is reachable at `https://registry.luxrnd.tech` from the dev machine and from itself when serving as the `prod` host.
- [ ] `~/.docker/config.json` has credentials for this registry.
- [ ] If running the registry locally on the dev machine: it persists images to a volume (so the `release prod` pull side finds them after `release stage` pushed them).

### A.6 Reverse proxy + cert manager — fixed

- [ ] Traefik is installed and running on the dev machine, configured machine-wide.
- [ ] Traefik is attached to the bare external Docker network named `web`. (docex's fixed-foundation compose emits `web` as this shared network; Traefik must share it to route to project containers.)
- [ ] Traefik has a single ACME cert resolver named exactly `doctrine`, configured with the **DNS-01** challenge against the Route53 zone for `luxrnd.tech` (HTTP-01 won't work for the per-env wildcards). Traefik's Route53 IAM is a dedicated narrow user with permissions scoped to the `luxrnd.tech` zone.
- [ ] Traefik is listening on `:443` with the docker provider enabled so it auto-discovers the test project's compose containers.

### A.7 Fixed deploy credentials

- [ ] Generate an SSH keypair for each env if not already present:
  ```
  ssh-keygen -t ed25519 -f test_projects/fixed/infra/deploy_creds/stage -N ''
  ssh-keygen -t ed25519 -f test_projects/fixed/infra/deploy_creds/prod -N ''
  ```
- [ ] Append both public keys (`stage.pub`, `prod.pub`) to `~/.ssh/authorized_keys` on the dev machine (which is also the deploy target).

### A.8 Per-project secrets — both foundations

The doctrine's `infra/secrets/<env>.env` files are gitignored. They must exist with real values before any `up`/`release` runs against an env.

For each project (`fixed/`, `elastic/`), after step C.2's `docex compile` writes `example.env`:

- [ ] Create `infra/secrets/dev.env`, `test.env`, `stage.env`, `prod.env` by copying `example.env` as a template.
- [ ] Fill in every `POSTGRES_*` value (the operator chooses; these are also the prod credentials).
- [ ] The fixed project's `prod.env` reuses the same machine as `dev`/`test`, so be careful not to collide on ports (compose namespacing per env handles this automatically).

---

## B. Doctrine-conformance audit — run before any provisioning

Before running `docex compile` or any release command, walk this audit against each test project's tree. Each item cites the doctrine doc that prescribes it. If any item fails, the seed is out of alignment with current doctrine and must be repaired (in the seed, in doctrine, or both — per the five-artifact alignment rule in [`docex_process.md`](../plans/core/docex_process.md)) before the smoke test proceeds.

Run this audit *once per cut*, against each project independently.

- [ ] **B.1 Project root layout** — `project.yml`, `README.md`, `CHANGELOG.md`, `.gitignore`, `bin/docex`, `core/`, `infra/`, `plans/` all present. Per [`inception.md`](../../doctrine/practices/inception.md) PART I step 7 and [`infrastructure.md § Codebase Structure`](../../doctrine/infrastructure/infrastructure.md#codebase-structure).
- [ ] **B.2 `project.yml` shape** — declares `name`, `version`, `docex_version`. Per [`infrastructure.md § Project Config`](../../doctrine/infrastructure/infrastructure.md#project-config).
- [ ] **B.3 CHANGELOG conventions** — follows Keep a Changelog + SemVer (Unreleased section present). Per [`version_control.md § Changelog`](../../doctrine/infrastructure/version_control.md#changelog).
- [ ] **B.4 `infra.yml` validates** — `docex compile` succeeds with no errors. Per [`cicl.md § Validation Rules`](../../doctrine/infrastructure/cicl.md#validation-rules).
- [ ] **B.5 Core service Dockerfiles** — every core service has a Dockerfile with `build`, `dev`, `prod`, `test` stages. Per [`infrastructure.md § Core Service Containers`](../../doctrine/infrastructure/infrastructure.md#core-service-containers).
- [ ] **B.6 Core service scripts** — every core service has `build.sh` and `test.sh`; services owning a relational_db schema additionally have `migrate.sh` and `migrations/`. Per [`cicd.md § Build Step`, § Build Test Step, § Migrate Step](../../doctrine/infrastructure/cicd.md).
- [ ] **B.7 Provider contracts present** — every provider core service has a contract at `infra/contracts/<svc>.<format>.yml`. Per [`contracts.md`](../../doctrine/infrastructure/contracts.md).
- [ ] **B.8 Health endpoints declared** — every `web`-network core service's contract declares `GET /health`; if it depends on other core services, also `GET /health/<other>`. Per [`contracts.md § Health Checks`](../../doctrine/infrastructure/contracts.md#health-checks).
- [ ] **B.9 Hex layout** — each core service contains `src/root.py` (composition root); each hex module contains `domain/`, `ports/{driving,driven}/`, `adapters/{driving,driven}/`, `alogic/`. Per [`hex_overview.md § Project Structure`](../../doctrine/hexagonal_architecture/hex_overview.md#project-structure) and [`internal_dependency_rules.md § Composition Root`](../../doctrine/hexagonal_architecture/internal_dependency_rules.md#composition-root).
- [ ] **B.10 Migrations idempotent + reversible** — every `core/<svc>/migrations/*.sql` has both `-- migrate:up` and `-- migrate:down` sections. Per [`databases.md § Migrations`](../../doctrine/practices/databases.md#migrations).
- [ ] **B.11 Stage tester present** — `infra/stage/Dockerfile`, `infra/stage/stage_test.sh`, `infra/stage/tests/` all populated. Per [`tests.md § Staging Tests`](../../doctrine/infrastructure/tests.md#staging-tests).
- [ ] **B.12 Foundation-irrelevant code parity** — `diff -r test_projects/fixed/core test_projects/elastic/core` produces no output. If it does, application code has begun leaking foundation knowledge — that's a doctrine bug in the parts-only env model. Per the [elastic project's masterplan § Code duplication](./elastic/plans/core/masterplan.md).

---

## C. Walk: docex_smoke_fixed

`cd test_projects/fixed/` for everything below. Each `./bin/docex` invocation re-uses the version pinned in `project.yml`.

### C.1 Bootstrap

Fixed foundation: bootstrap is a no-op. Skip.

### C.2 Compile

- [ ] `./bin/docex compile` — succeeds, produces `infra/output/{dev,test,stage,prod}/docker-compose.yml` + the stage/prod `playbook.yml` and `inventory.yml`, plus `infra/secrets/example.env`.

### C.3 Secrets

- [ ] Confirm A.8 was performed for `fixed/` — `dev.env`, `test.env`, `stage.env`, `prod.env` all populated.

### C.4 Dev sanity (optional but recommended)

- [ ] `./bin/docex up dev` — stack comes up; `https://dev.doctrine-fixed.luxrnd.tech/health` returns 200 with a `version` field.
- [ ] `./bin/docex down dev` — stack tears down.

### C.5 Test

- [ ] `./bin/docex test` — exits 0. Includes unit + integration + contract tests.

### C.6 Containerize

- [ ] `./bin/docex containerize` — succeeds; both `registry.luxrnd.tech/docex_smoke_fixed/web:<v>` and `registry.luxrnd.tech/docex_smoke_fixed/worker:<v>` push successfully.

### C.7 Release stage

- [ ] `./bin/docex release stage` — ansible playbook completes; `https://stage.doctrine-fixed.luxrnd.tech/health` returns 200.

### C.8 Stagetest

- [ ] `./bin/docex stagetest` — exits 0. The smoke test in `infra/stage/tests/` POSTs to `/pings` and probes `/health`.

### C.9 Release prod

- [ ] `./bin/docex release prod` — completes; `https://www.doctrine-fixed.luxrnd.tech/health` returns 200.
- [ ] POST a ping to `https://www.doctrine-fixed.luxrnd.tech/pings` — returns 201.
- [ ] After ~5s, query the postgres prod database directly: the ping row exists and has a non-NULL `processed_at` (worker picked it up).

### C.10 Teardown

- [ ] `bash teardown.sh` — succeeds. Removes all four envs' containers + named volumes; deletes registry images for this project.
- [ ] `bash verify_clean.sh` — exits 0. No lingering containers, networks, volumes, or registry images carry the project's name prefix.

---

## D. Walk: docex_smoke_elastic

`cd test_projects/elastic/` for everything below.

### D.1 Bootstrap (two phases)

Elastic foundation: `docex bootstrap` runs in two phases separated by an operator NS-delegation step.

- [ ] `./bin/docex bootstrap` — phase 1 runs: creates the tofu state backend (S3 + DynamoDB), then applies just the project Route53 zone, prints the zone's NS records, and exits.
- [ ] Manually NS-delegate from the `luxrnd.tech` parent zone: create an NS record at `doctrine-elastic.luxrnd.tech` whose value is the four NS hostnames phase 1 printed. Wait for propagation (`dig NS doctrine-elastic.luxrnd.tech` returns the AWS nameservers from a non-local resolver).
- [ ] `./bin/docex bootstrap` (again) — phase 2 runs: applies the rest of the project-tier HCL (VPC, subnets, ACM cert with DNS-01 validation, ECR repos, IAM execution role).

### D.2 Compile

- [ ] `./bin/docex compile` — succeeds; produces `infra/output/{dev,test}/docker-compose.yml`, `infra/output/{stage,prod}/main.tf`, `infra/output/project/main.tf` (already applied by D.1), and `infra/secrets/example.env`.

### D.3 Secrets

- [ ] Confirm A.8 was performed for `elastic/` — `dev.env`, `test.env`, `stage.env`, `prod.env` all populated.

### D.4 Dev sanity (optional but recommended)

`dev` and `test` envs run as fixed compose stacks even on an elastic-foundation project (per [`shape2.md § Shape and Environment`](../../doctrine/infrastructure/shape2.md#shape-and-environment)).

- [ ] `./bin/docex up dev` — stack comes up locally. (No DNS for `dev.doctrine-elastic.luxrnd.tech` exists — hit the service directly via the dev machine.)
- [ ] `./bin/docex down dev`.

### D.5 Test

- [ ] `./bin/docex test` — exits 0.

### D.6 Containerize

- [ ] `./bin/docex containerize` — succeeds; images push to the project ECR (`<account>.dkr.ecr.us-east-1.amazonaws.com/docex_smoke_elastic/{web,worker}:<v>`).

### D.7 Release stage

- [ ] `./bin/docex release stage` — first-time-release path detected (cluster absent); ordering swaps to `SSM push → tofu apply → migrate`. ALB, ECS cluster, ECS services, RDS instance all come up. `https://stage.doctrine-elastic.luxrnd.tech/health` returns 200.

### D.8 Stagetest

- [ ] `./bin/docex stagetest` — exits 0.

### D.9 Release prod

- [ ] `./bin/docex release prod` — first-time-release path again for prod env. Provisions a separate prod ALB + ECS cluster + RDS. `https://www.doctrine-elastic.luxrnd.tech/health` returns 200.
- [ ] POST a ping to `https://www.doctrine-elastic.luxrnd.tech/pings` — returns 201; after ~5s the prod RDS shows the row with non-NULL `processed_at`.

### D.10 Teardown

- [ ] `bash teardown.sh` — runs `tofu destroy` for `prod`, then `stage`, then the project tier; then boto3-driven cleanup of ECR image tags + SSM parameters; then deletes the tofu state bucket + DynamoDB lock table (full retirement).
- [ ] `bash verify_clean.sh` — exits 0. AWS API queries for every doctrine-emitted resource type filtered by project-name prefix return empty.

---

## E. After both walks succeed

- [ ] Both `verify_clean.sh` runs are green.
- [ ] No leftover state in Route53 except the parent `luxrnd.tech` zone and any other unrelated records the operator runs.
- [ ] No registry images for `docex_smoke_fixed` or `docex_smoke_elastic` remain.
- [ ] AWS cost report for the smoke-test window matches expectations (~$X for 1-2 hours of stage+prod elastic infra; verify against operator's running tally).

The cut is now safe to perform per [`docex_process.md § Cutting a version`](../plans/core/docex_process.md#cutting-a-version).
