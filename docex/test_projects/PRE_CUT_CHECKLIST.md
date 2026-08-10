# Pre-Cut Checklist

The agent's manual procedure before cutting a doctrine minor or major version. Walks the two smoke-test projects ([`fixed/`](./fixed/) and [`elastic/`](./elastic/)) through their full release paths against real infrastructure. Surfaces bugs that unit tests can't reach.

**Skip this for patch cuts.** Patches fix unit-testable bugs; the smoke walk would burn real AWS spend without proportionate value.

If anything in this checklist fails, **the cut does not happen.** Fix the bug (in doctrine, `docex`, the seed, or all three — per the six-artifact alignment in [`docex_process.md`](../plans/core/docex_process.md)) and restart from the failing step.

---

## A. Prerequisites — verify once before starting

Every box below must be checked off on the dev machine before the walk begins.

### A.1 Tooling

- [ ] Docker daemon running and reachable.
- [ ] AWS credentials resolve, with permissions covering Route53, ACM, ECR, ECS, RDS, EFS, S3, DynamoDB, SSM, IAM, EC2 (VPC + SG + EIP). `aws sts get-caller-identity` succeeding is the check. **A `~/.aws/credentials` file is not required** — on a dev box that is itself an EC2 instance the instance role supplies them and `~/.aws` holds only `config` + `sso`. The shim mounts `~/.aws:ro` and in-container AWS calls work either way; a missing credentials file is not a finding.
- [ ] AWS region: `us-east-1` (the doctrine's pinned region).
- [ ] `~/.docker/config.json` present, with push permissions for the fixed-project container registry (see A.5) **and** for ECR (AWS creds handle this).
- [ ] `~/.gitconfig` and `~/.ssh/` populated so git operations work from inside the docex container.

### A.2 The docex image to be tested

- [ ] The candidate `docex` image is built locally: `docker images docex:1.7.0` shows the tag.
- [ ] Re-pin each test project to the candidate version. This moves each project's `docex_version` from `1.6.0` to `1.7.0` — the seeds sit at `1.6.0` today because mod 117 deliberately left repinning to the cut:
  ```
  bash ~/.claude/jean_baudrillard/docex_install.sh test_projects/fixed
  bash ~/.claude/jean_baudrillard/docex_install.sh test_projects/elastic
  ```
- [ ] `cd test_projects/fixed && ./bin/docex --version` prints the candidate version. Same for `elastic/`.
- [ ] **Commit the repin inward before assessing A.2.1.** The repin edits `project.yml`, which dirties both repos; A.2.1 requires a **clean** inner tree with the version tag at HEAD. Commit in the inner repo per [`test_projects.md § Commit cadence`](../plans/core/test_projects.md#commit-cadence) and force-move `v<version>` to the new HEAD. Skipping this does not fail here — it fails at A.2.1, or worse, silently leaves `containerize` pointed at a commit that predates the repin.

### A.2.1 Test projects are self-contained git repos

The doctrine assumes a project is its own git repository (per [`inception.md`](../../doctrine/practices/inception.md)). The smoke-test projects under `test_projects/` are also tracked at the doctrine-repo level for distribution convenience, but each MUST additionally be its own git repo so docex's CI/CD gate checks (`check`, `merge`, `containerize`) can introspect a real repo state inside the docex container. This is one-time setup at first walk and persists; later walks just verify it's still present.

- [ ] `test_projects/fixed/.git` exists, on branch `main`, with a tag `v<version>` (matching the inner `project.yml`'s `version:`) at HEAD and a clean working tree. If not, initialize per [`test_projects.md § Why the test projects are their own git repos`](../plans/core/test_projects.md#why-the-test-projects-are-their-own-git-repos).
- [ ] Same for `test_projects/elastic/`.

> **Ordering carve-out — A.2.1 vs. C.6 / D.8.** A.2.1 describes each inner
> repo's *resting* state (on `main`, clean, `v<version>` at HEAD) and is asserted
> **before** [C.6](#c6-check--containerize) / [D.8](#d8-check--containerize).
> Those steps then deliberately restructure the history into the feature-branch
> shape their prerequisite demands — `main` at the **prior** release, the new
> version on a feature branch checked out now — and `merge` returns the repo to
> `main` with the new version at HEAD. The two states are mutually exclusive by
> design. Re-asserting A.2.1 between the restructure and `merge` will fail, and
> that failure is expected: **do not "repair" it by moving the tag**, which
> silently defeats the `check` version-bump gate.

Edits inside `test_projects/*/` dirty both the inner repo and the outer doctrine repo. Commit inner-first per [`test_projects.md § Commit cadence`](../plans/core/test_projects.md#commit-cadence).

### A.3 Preinfra — both sides

The post-1.0.0 doctrine separates preinfra (machine-/account-wide), projinfra (per-project), and envinfra (per-env). Preinfra must exist before any `projinfra up` will run. Use the `docex-preinfra` skill if anything below is missing or drifted.

#### A.3.1 Development side (fixed-style, on the dev machine)

- [ ] **HAProxy `web_demux`** is installed and running on the dev machine, listening on `:443` (SNI pass-through) and `:80` (HTTP host routing). HAProxy parses the request domain and forwards to the project traefik container named `${project_dns_label}-traefik` on the `docex-ingress` network — `project_dns_label` is the underscored project name with underscores translated to hyphens and lowercased (e.g. `docex_smoke_fixed` → `docex-smoke-fixed`). See [`fixed_master_network.md`](../../doctrine/infrastructure/preinfra/fixed_master_network.md).
- [ ] **`docex-ingress`** docker bridge network exists on the dev machine. `docker network ls | grep docex-ingress` returns one entry. Created with `docker network create docex-ingress` if absent.

No traefik env vars are required. Fixed-foundation certs use the **HTTP-01** ACME challenge (Gap A / mod 051), served on the `web` entrypoint (`:80`) that the HAProxy demux already forwards by Host header — there is **no** `TRAEFIK_DNS_PROVIDER` prerequisite (HTTP-01 needs no DNS-provider credentials). `TRAEFIK_ACME_EMAIL` is **optional**: Let's Encrypt registers fine with no contact email; setting it only enables LE expiry-reminder emails. (Threading it through docex is a deferred future option — mod 053 / F2 decision A.)

`./bin/docex preinfra development` (run from either test-project root, since it checks dev-side machine state which is project-agnostic) probes the bridge + HAProxy and exits 0 only when both are present.

#### A.3.2 Production side (elastic; only for the elastic walk)

- [ ] **Master VPC** exists in the operator's AWS account with the tags `Name=master_network_VPC`, `managed_by=doctrine-operator`, `shape_name=master_network`, and `infra_tier=prerequisite` — matching the [`cicl.md § Elastic Foundation`](../../doctrine/infrastructure/cicl.md) preinfra convention. (Earlier revisions of this checklist named `Name=docex-master-vpc` / `managed_by=docex-preinfra`; that was always stale — the infrastructure was right and the checklist wrong. Discover with `--filters "Name=tag:shape_name,Values=master_network"`.) The four subnets (public + private in primary AZ `us-east-1a`; redundant public + private in a secondary AZ) carry `tier=public` / `tier=private` tags. The primary-AZ subnet is discovered via `availability-zone=us-east-1a` filter (no tag required for AZ). See [`elastic_master_network.md`](../../doctrine/infrastructure/preinfra/elastic_master_network.md) and mod 041.
- [ ] **NAT gateway** is present in the public subnet of the primary AZ.
- [ ] **`docex-preinfra` skill** at `~/.claude/skills/docex-preinfra/SKILL.md` documents the tag scheme above. If the skill is stale, fix it as part of pre-walk setup.

`./bin/docex preinfra production` (run from the elastic project root) probes the master VPC + 4 subnets + primary-AZ subnet via tag discovery and exits 0 only when all are present.

### A.4 DNS — apex zone

Both test projects share the parent apex `luxrnd.tech` (Route53). The fixed project resolves the host machine via env-subdomain wildcards under the parent zone; the elastic project uses a delegated child zone (provisioned by `projinfra up production`).

#### A.4.1 Fixed walk DNS

The fixed project's bare apex is `luxrnd.tech` and the project segment derives to `docex-smoke-fixed`. The dev machine's public IP (`$DEV_IP`) needs to be reachable at every per-env host.

**These nine records are created once, in the parent `luxrnd.tech` Route53 zone, as `A` records → `$DEV_IP`, and they are permanent.** They are *standing* records: they survive teardown by design, and [§ E](#e-after-both-walks-succeed) exempts them explicitly. Two reasons. First, `teardown.sh` disclaims DNS as the operator's responsibility (see its header) and always has — this section is now the other half of that statement rather than the only mention. Second, unlike the elastic walk, the fixed project has **no zone lifecycle** for a walk to create and destroy: A.4.2's child-zone records are temporary because `projinfra up/down production` creates and destroys the child zone around them, and no equivalent exists here. Per-walk churn would buy nothing and cost a DNS-propagation stall at the front of every walk.

**Creation.** If `dig +short <subdomain>` returns nothing for any of the nine, create it in the parent `luxrnd.tech` zone as an `A` record → `$DEV_IP` before proceeding. Do this at the Route53 console alongside A.4.2's records; the checklist is operator-driven and deliberately does not script it.

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

**No new records are needed for the CICL-v3 core-service migration.** The per-env `*.<env>.…` wildcards above already cover the new two-segment hostnames (`api-web.dev.…`, `api-web.prod.…`), because the core-service segment shares the *same DNS label* as the codebase, hyphen-joined. The `worker` and `clock` core services take no ingress ([rule 27](../../doctrine/infrastructure/cicl.md#validation-rules)) and are never routed, so **no** DNS record of any kind is needed for them on either foundation — the wildcard question does not arise for them at all. This is worth saying because the tree now carries a third core service, and a reader counting hostnames will go looking for `api-clock.<env>.…`. Stated explicitly because [`upgrades/upgrade_1.6.0.md`](../../upgrades/upgrade_1.6.0.md) tells downstream projects the **opposite** — a fixed project must add a public A-record per new web hostname before `envinfra up`. Both are correct: those projects hold per-host records, these smoke projects hold wildcards. A reader comparing the two documents should not conclude one is wrong.

#### A.4.2 Elastic walk DNS

`docex projinfra up production` creates a Route53 zone for `docex-smoke-elastic.luxrnd.tech` (project zone, child of `luxrnd.tech`). Between phase 1 and phase 2 of the projinfra apply, the operator NS-delegates from the parent `luxrnd.tech` zone.

- [ ] Operator has Route53 admin on `luxrnd.tech`.
- [ ] **Elastic dev/test hosts must resolve before D.1.** `docex preinfra development` (D.1) also runs for the elastic project (its `dev`/`test` envs are local fixed stacks) and fails until `dev`, `*.dev`, `test`, `*.test`.`docex-smoke-elastic.luxrnd.tech` resolve to the dev machine. These are **out-of-band** dev/test A-records (deliberately not in projinfra — see the doctrine's elastic-dev-DNS note). Create them in the parent `luxrnd.tech` zone → `$DEV_IP` (low TTL) before D.1.
- [ ] **⚠ Re-create the same four records in the CHILD zone immediately after D.3 phase 1, before probing anything.** Delegating the child zone at D.3 makes it authoritative for everything under `docex-smoke-elastic.luxrnd.tech`, which **shadows** the parent-zone dev/test records. An earlier revision of this checklist said the shadowing "is fine — `preinfra development` only runs at D.1." **That is wrong: `envinfra up dev` re-runs `preinfra development` as a precondition**, so D.6 fails after D.3 with `dev host '…' does not resolve in public DNS`.

  Two further traps make this expensive rather than merely annoying:

  1. **A failed probe seeds a negative cache.** The child zone's SOA yields a 900 s negative TTL, and the AWS VPC resolver's caches expire independently across its backends — resolution *flapped* for ~9 minutes after the records were added. Create the child-zone records **before** anything queries those names and the stall never happens.
  2. **The dev-side check now names two-segment core service hostnames** (`api-web.dev.…`). The per-env `*.dev.…` wildcard covers them, so no extra records are needed — but only if the wildcard is in the *authoritative* zone.

  The project-tier HCL already expects this: `aws_route53_zone.project` carries a `force_destroy` comment about "records tofu doesn't own — dev A-records". Alternatively, run D.6's dev sanity **before** D.3 and skip the child-zone copies entirely.
- [ ] Remove both sets at teardown, **including the parent-zone `NS` delegation record**, which otherwise dangles at a deleted zone. `verify_clean` checks the child *zone*, not parent-zone records.
- [ ] The child zone itself: **nothing to pre-create** — D.3 phase 1 prints the NS records to delegate on the parent.

### A.5 Container registry — fixed

- [ ] A Docker Registry V2 instance is reachable at `https://registry.luxrnd.tech` from the dev machine and from itself when serving as the `prod` host.
- [ ] The **operator's** `~/.docker/config.json` has credentials for this registry. This is the push side, used by `docex containerize`. Pull-side credentials (`deploy` and `root` on the target host) are covered in A.7.
- [ ] If running the registry locally on the dev machine: it persists images to a volume (so the `release prod` pull side finds them after `release stage` pushed them).
- [ ] `cd test_projects/fixed && ./bin/docex preinfra development` reports **no registry failure and no registry declination**. A *failure* naming `REGISTRY_STORAGE_DELETE_ENABLED` means the registry refuses manifest deletes, which breaks `teardown.sh`. A *declination* means something weaker: the probe could not reach or authenticate to the registry, so it did not learn anything either way — not that deletion is broken. Fix the boxes above and re-run rather than reading a declination as a verdict.

> **A green box above exercises the PASS arm only.** This machine's registry
> already has `REGISTRY_STORAGE_DELETE_ENABLED=true`, so the walk can only ever
> confirm that the probe agrees with a correctly configured registry. It proves
> **nothing whatever** about the failure branch. That branch is covered
> exclusively by `tests/integration/test_preinfra_registry_delete_real.py`,
> which brings up a flag-off `registry:2` and asserts the finding. Do not read a
> green box here as having tested the failure path.

### A.6 Observability backend

- [ ] HyperDX (or equivalent OTLP-receiving backend) reachable at `https://hyperdx.luxrnd.tech` (the URL declared in both test projects' `infra.yml` as `observability_backend_url`). `curl -k https://hyperdx.luxrnd.tech/` returns 2xx/3xx/4xx (anything but a connection error). Sidecars in stage/prod will export here; without the backend the sidecars start cleanly but exports fail at runtime.
- [ ] A `TELEMETRY_API_KEY` value usable against the backend, obtained from HyperDX. Goes into `infra/secrets/{stage,prod}.env` per A.8.

### A.7 Fixed deploy credentials and deploy-target user

Per [`release.md § Fixed Foundation: Ansible`](../../doctrine/infrastructure/specifics/release.md#fixed-foundation-ansible), the rendered playbook lands on the deploy target as a dedicated `deploy` user — member of the `docker` group, with passwordless sudo so `become: true` tasks can elevate without prompting. The dev machine doubles as the deploy target for this smoke walk, so the user must exist on it locally.

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

For each project (`fixed/`, `elastic/`):

- [ ] Reconcile each env with `./bin/docex secrets scaffold <env>` (dev/test/stage/prod). This derives the required-secret key set on demand from `secret_manifest` (no `example.env` file is emitted — mod 092). Under the envmageddon three-category model, `POSTGRES_USER` is a `kind: fixed` inline and `POSTGRES_PASSWORD` is a `kind: minted` TTE value (docex mints it into `infra/tte/`), so **neither belongs in `infra/secrets/`**. The only project secret here is the doctrine-injected `TELEMETRY_API_KEY`.
- [ ] Set `TELEMETRY_API_KEY` (required for `stage`/`prod`) with `./bin/docex secrets set <env> TELEMETRY_API_KEY` (value from A.6), or confirm it via `./bin/docex secrets status <env>`. `dev`/`test` need no secrets (their sidecars use the debug exporter).
- [ ] No `POSTGRES_*` values are entered anywhere — the TTE store is minted automatically during aggregation at first `up`/`release`.

---

## B. Doctrine-conformance audit — run before any provisioning

Before running `docex compile` or any release command, walk this audit against each test project's tree. Each item cites the doctrine doc that prescribes it. If any item fails, the seed is out of alignment with current doctrine and must be repaired (in the seed, in doctrine, or both — per the six-artifact alignment rule in [`docex_process.md`](../plans/core/docex_process.md)) before the smoke walk proceeds.

Run this audit *once per cut*, against each project independently.

> **Two things only this walk covers.** Both are stated here so a decision to shorten the walk is made knowingly, not by accident.
>
> 1. **No test anywhere runs a real clock container.** The codebase suite covers the dispatch table and the queue, and unit tests cover the emit — but a clock **process** reading a compiler-delivered `DOCEX_SCHEDULES_YAML`, firing on its own cron loop, and having **`./health.sh clock` enforced by the container probe** exists only in a walk. A clock has **no `/health`** — it binds no application socket at all; it has a probe. That probe is its **only** enforcement: nothing routes to it, so no stage test can reach it ([`clock.md § Caveats`](../../doctrine/infrastructure/specifics/clock.md#caveats)). Being unreachable from outside is now true of **every** non-`web` core service rather than the clock alone — the worker included — so the clock is no longer a special case; it is the *first* case of the general rule. The clock steps in [C.9](#c9-release-prod) and [D.11](#d11-release-prod) are where that is checked.
> 2. **No test of any kind covers the fixed replica unroll.** See the note at the top of [C.9](#c9-release-prod).

- [ ] **B.1 Project root layout** — `project.yml`, `README.md`, `CHANGELOG.md`, `.gitignore`, `bin/docex`, `core/`, `infra/`, `plans/` all present. Per [`inception.md`](../../doctrine/practices/inception.md) PART I step 7 and [`infrastructure.md § Repository Structure`](../../doctrine/infrastructure/infrastructure.md#repository-structure).
- [ ] **B.2 `project.yml` shape** — declares `name`, `version`, `docex_version`. Per [`infrastructure.md § Project Config`](../../doctrine/infrastructure/infrastructure.md#project-config).
- [ ] **B.3 `infra.yml` shape** — declares `cicl_version: "3"`; `apex_domain` as a bare apex (no project segment); `domain_default_service` as a **dotted, fully qualified** core service reference (`api.web`), with the 1.6.0 spelling `domain_default_process` absent; and (elastic only) `reverse_proxy` (default `alb`). Old `domain:` field absent. Per [`cicl.md`](../../doctrine/infrastructure/cicl.md) mod 031 and [§ CICL Version](../../doctrine/infrastructure/cicl.md#cicl-version).
- [ ] **B.3.1 `core_services:` on every codebase** — present and **non-empty** on each. There is no flat form and no single-service shorthand. The codebase level accepts only `{core_services, secrets, config, env}`; anything else there is a hard error. `role`, `command`, `networks`, `resources`, `port`, `uses`, `surfaces`, `replicas`, and every role-specific field (`health_check_path`, `schedules`) live on a **core service**. `env:` is the one field valid at both levels. Note that `health_check_path` is keyed on **network membership, not role** ([rule 33](../../doctrine/infrastructure/cicl.md#validation-rules)): a `role: web` core service off the `web` network declares **none**, and every `web`-network one declares it whatever its role. Per [`cicl.md § Core Services`](../../doctrine/infrastructure/cicl.md#core-services) and [`cicl_reasoning.md § Field Scoping`](../../doctrine/infrastructure/reasoning/cicl_reasoning.md#field-scoping).
- [ ] **B.3.2 `uses` is one relation, keyed on target kind** — a `uses` entry names either a **backing service**, bare (`appdb`), or a **core service**, dotted and fully qualified (`api.worker`). A bare codebase name is an error, not shorthand, and a core service may not use itself (rule 25). **Only core services declare `uses`**; a backing service has no outbound edges at all and is a graph sink. `depends_on:` and `consumes:` are hard errors, not silent aliases — rules 6 and 24 are retired and carry tombstones at their original numbers. Core magic refs are **five-segment** (`${codebases.api.core_services.worker.host}`); backing refs stay at three. Per [`cicl.md § Uses Relationships`](../../doctrine/infrastructure/cicl.md#uses-relationships) and [§ Magic Refs](../../doctrine/infrastructure/cicl.md#magic-refs).
- [ ] **B.4 CHANGELOG conventions** — follows Keep a Changelog + SemVer (Unreleased section present). Per [`version_control.md § Changelog`](../../doctrine/infrastructure/version_control.md#changelog).
- [ ] **B.5 `infra.yml` validates** — `docex compile` succeeds with no errors. Per [`cicl.md § Validation Rules`](../../doctrine/infrastructure/cicl.md#validation-rules).
- [ ] **B.6 Codebase Dockerfiles** — every **codebase** has a Dockerfile with `build`, `dev`, `prod`, `test` stages. One per codebase, not one per core service: the codebase's core services all run the same image. Per [`infrastructure.md § Codebase Containers`](../../doctrine/infrastructure/infrastructure.md#codebase-containers).

  Additionally: the image must be able to run **`./health.sh <service>`** for every
  core service it hosts — per [`infrastructure.md § Codebase Containers`](../../doctrine/infrastructure/infrastructure.md#codebase-containers),
  which states the capability and leaves the tool to the project. **`curl` is no
  longer doctrine-mandated.** The seeds carry it for exactly one line — `health.sh`'s
  `web` arm curls its own route — and that is a project choice, not conformance. A
  box that reads "curl is in the image" as a pass would accept an image that cannot
  run its own probe.
- [ ] **B.7 Codebase scripts** — scripts are per **codebase**, never per core service: every codebase has one `build.sh` and one `test.sh` (which runs *all* the codebase's tests, across every core service's modules); a codebase owning a relational_db schema additionally has one `migrate.sh` and one `migrations/`, and `migrate.sh` runs **once per codebase** per release regardless of core-service count. Per [`cicd.md § Build Step, § Build Test Step, § Migrate Step`](../../doctrine/infrastructure/cicd.md).

  **`health.sh` is the fourth codebase shim**, required **unconditionally** — unlike
  `migrate.sh`, which is conditional on schema ownership. It is also **the only shim
  invoked per core service**, as `./health.sh <service>`. Still one file per codebase
  like the other three — but a web edge and a queue consumer of one codebase have
  genuinely different probes, and argv is cheaper than four shims. **The compiler
  emits the argv**, so the script never guesses which core service it is running in.
  Confirm the script *branches on `$1`* and that its fall-through case **fails
  loudly** — a `*)` arm that exits 0 reports every core service healthy forever,
  which is the one outcome worse than a wrong probe. Per
  [`healthchecks.md`](../../doctrine/infrastructure/healthchecks.md).
- [ ] **B.7.1 The three shims read codebase-level `env:` only** — `migrate.sh`, `test.sh`, and `build.sh` are invoked per codebase, so a core-service-scoped `env:` key is simply **absent** in them. Confirm every var they read is declared at the *codebase* level of `infra.yml`. This break is silent: a migration that reads a core-service-scoped `DATABASE_HOST` gets an empty string, not an error. Per [`cicl_reasoning.md § Field Scoping`](../../doctrine/infrastructure/reasoning/cicl_reasoning.md#field-scoping).

  **`health.sh` is the exception, and extending this box to it would be wrong.**
  `build.sh` / `test.sh` / `migrate.sh` run in the one-off per-codebase `-exec`
  container, whose `environment:` is the **codebase** env surface — which is why a
  core-service-scoped key is simply absent in them. `health.sh` runs **inside the
  running core-service container**, invoked by the orchestrator's probe, so it sees
  that core service's **full** env surface including its core-service-scoped keys.
  Stated rather than left inferred because getting it backwards is silent in both
  directions: a `health.sh` written to the codebase surface would needlessly avoid
  keys it can read, and a `migrate.sh` reading a core-service key gets an empty
  string, not an error.
- [ ] **B.8 `migrate.sh` builds DSN from parts** — including `${DATABASE_SSLMODE}`. No hard-coded `sslmode=disable` or `sslmode=require`. RDS rejects non-SSL on elastic; the doctrine's parts-only model keeps the shim foundation-agnostic. Per [`migrations.md`](../../doctrine/infrastructure/specifics/migrations.md).
- [ ] **B.9 Provider contracts present** — **a core service is a provider iff it
  declares `surfaces:`.** Nothing else makes one: the old
  `(core-targeted uses entries) ∪ (`web`-network core services)` union is gone, and a
  `web`-network core service that declares no surface (a frontend serving a browser)
  correctly needs **no** contract. A `uses` edge onto a core service declaring no
  surface is a **compile error** (rule 31), not a missing contract.

  One contract per surface at
  `infra/contracts/<codebase>.<service>.<surface>.<format>.<ext>` — **four**
  segments, parsed right-anchored. The **format follows the surface's `api_styles`**
  (`rest`/`stream`/`webhook` → `openapi`; `rpc`/`events`/`socket` → `asyncapi`),
  never the provider's `role`, and there is **no fallback**. Exactly one extension
  per format, so `api.web.rest.openapi.yml` resolves while `api.web.openapi.yml` and
  `api.web.rest.openapi.yaml` do not.

  A `clock` carries no contract because it **declares no surface** — not because of
  an exemption. Nothing addresses it and nothing may `uses` it, so it has no
  boundary to describe.

  **Key this box on `docex check`'s own output, not on a filename list.** The
  `contracts_exist` gate reports both directions: a declared surface with no file,
  **and** a file matching no declared surface (the *orphan* arm, whose message names
  the four-segment form and says to rename or delete). The orphan arm is the only
  thing that catches a leftover three-segment contract sitting **beside** its
  correct replacement — an existence check is blind to that, because the file it
  wants is also there. Reaching `check` needs the walk's feature-branch restructure
  ([C.6](#c6-check--containerize) / [D.8](#d8-check--containerize)), so at audit
  time confirm the *shape* here and record the gate's line when you get there.
  Per [`contracts.md`](../../doctrine/infrastructure/contracts.md).
- [ ] **B.10 Health is a command, not an endpoint** — five parts, all per **core
  service**.

  1. **The container probe.** Every core service's container carries
     `["CMD", "./health.sh", "<service>"]` on both foundations — a compose
     `healthcheck:` on fixed, an ECS container `healthCheck` on elastic. It is
     **compiler-emitted from the role tables' `defaults`, not authored**: a queue
     consumer or a cron loop gets a probe while declaring nothing. Cadence is
     doctrine-fixed and uniform; a project-local interval knob is a finding.
     `startPeriod: 10` appears on **elastic only** — ECS kills and replaces a task
     whose essential container fails, Docker only reports.
  2. **`health.sh` exists, branches on argv, and fails loudly on an unknown one.**
     See **B.7** above.
  3. **A loop-owning core service reports the LOOP's liveness, not the process's.**
     The loop touches a known path each iteration **from inside itself**; the probe
     `stat`s its mtime from a separate process. An **absent** tick file must
     **fail** — a loop that has never completed an iteration has never been alive.
     Checking that the process exists proves nothing (a deadlocked process exists),
     and a separate liveness *thread* proves less than nothing: it answers healthy
     forever while no work moves, converting a loud failure into a silent one.
  4. **The 10 s / 30 s pair, and where each number lives.** ≤10 s tick cadence even
     when idle, 30 s staleness threshold. Both doctrine-fixed — a project-local knob
     for either is a finding. The **cadence** belongs in the entrypoint (the only
     thing that can honour it) and the **threshold** in `health.sh` (the only thing
     that judges it); confirm each file names the other half, because 30 being three
     times 10 is what the pair means. Reference implementation:
     `test_projects/*/core/api/{health.sh,src/entrypoints/{worker,clock}.py}`.
  5. **`GET /health` survives only on the `web` network, and only because a load
     balancer reads it.** It is one role's requirement, not the universal mechanism.
     Rule 33 both arms: **every** `web`-network core service declares
     `health_check_path`, and **no** core service off it does. Where a `web`-network
     core service also declares an `openapi` surface, that contract declares a `GET`
     on its **declared** path (not a hardcoded `/health`) — `docex check`'s
     `contract_health_path` gate, satisfied by *any one* openapi surface.

  **There is no fan-out, and its absence is checked rather than assumed:**

  ```sh
  grep -rn 'health/api/worker\|/health/<codebase>\|_build_health_app' core/ infra/ plans/ | grep -v CHANGELOG
  ```

  Zero hits, except prose that names the deletion in negation. Per
  [`healthchecks.md`](../../doctrine/infrastructure/healthchecks.md).

  ---

  **⚠ How to wedge a probe — read before you try.** Both of these cost mod 129 real
  time, and both produce a result that *looks* like an answer:

  1. **`kill -STOP 1` inside a container wedges nothing.** PID 1 in a PID namespace
     is immune to `SIGSTOP` **from inside that namespace**. The first attempt was a
     silent no-op and the probe kept reporting green — which would either condemn a
     correct probe or record a pass from a wedge that never happened. **Wedge from
     the host, against the real pid:**
     ```bash
     PID=$(docker inspect --format '{{.State.Pid}}' <container>)
     sudo kill -STOP "$PID"      # ... observe ...
     sudo kill -CONT "$PID"      # ALWAYS un-wedge before moving on
     ```
  2. **After any source edit, run `./bin/docex build` before probing.**
     `envinfra up dev` leaves the host `dist/` stale, so the stack runs **pre-mod**
     entrypoints and the probe answers "no tick file" — indistinguishable from the
     absent-tick arm working correctly. This is the dev model behaving as designed
     (source arrives by bind mount; `dist/` is refreshed by `build`), which is
     exactly why it is a trap and not a bug. Order: `up` → `build` → restart.

  ---

  **Probe census over both seeds' compiled artifacts.** Asserts the *negative* half
  of the rule — that the probe lands on exactly the core services and on nothing
  else. **Key this box on what it prints: `VIOLATIONS 0` and exit 0.** The
  `CONTAINERS` line is a corroborating census and is **deliberately not a hard
  number** — hard-coding it is the mistake `N ≠ 2` avoids and goes wrong the moment
  a seed gains an environment or a replica. Run from `docex/`:

  ```python
  """Probe census over both seeds' compiled artifacts. Run from docex/.

  Prints one PROBE/BARE/ENGINE line per container in every compiled artifact, then
  a VIOLATIONS count. Expected: VIOLATIONS 0, exit 0.

  Rules asserted (healthchecks.md, exec_service.md):
    * a core-service container carries exactly ["CMD", "./health.sh", "<service>"]
    * an `-otelcol` sidecar, an `-exec` block, and a migrate task carry NO probe
    * a backing service's own engine probe (CMD-SHELL) is not this check's business
  """

  import glob
  import json
  import re
  import sys

  import yaml

  CORE = {"web", "worker", "clock"}
  viol: list[str] = []
  lines: list[str] = []


  def judge(artifact: str, name: str, probe: list[str] | None) -> None:
      core = re.search(r"-api-(web|worker|clock)(-\d+)?$", name) or name in {
          f"api-{s}" for s in CORE
      }
      forbidden = name.endswith("-otelcol") or "-api-exec" in name or name == "api"
      if probe is None:
          lines.append(f"BARE  {artifact} {name}")
          if core:
              viol.append(f"MISSING   {artifact} {name}")
          return
      lines.append(f"PROBE {artifact} {name} {json.dumps(probe)}")
      if forbidden or not core:
          viol.append(f"FORBIDDEN {artifact} {name} {json.dumps(probe)}")
      elif probe[:2] != ["CMD", "./health.sh"] or len(probe) != 3 or probe[2] not in CORE:
          viol.append(f"MALFORMED {artifact} {name} {json.dumps(probe)}")


  for path in sorted(glob.glob("test_projects/*/infra/output/*/docker-compose.yml")):
      for name, svc in sorted(yaml.safe_load(open(path)).get("services", {}).items()):
          test = (svc.get("healthcheck") or {}).get("test")
          if test and test[0] == "CMD-SHELL":
              lines.append(f"ENGINE {path} {name} {json.dumps(test)}")
              continue
          judge(path, name, test)

  for path in sorted(glob.glob("test_projects/elastic/infra/output/*/main.tf")):
      name: str | None = None
      probe: list[str] | None = None
      for raw in open(path):
          if raw.rstrip("\n") == "    {":
              name, probe = None, None
          elif m := re.match(r'^      name = "([^"]+)"$', raw.rstrip("\n")):
              name = m.group(1)
          elif m := re.match(r"^        command = (\[\"CMD.*\])$", raw.rstrip("\n")):
              probe = json.loads(m.group(1))
          elif raw.rstrip("\n") in ("    },", "    }") and name:
              judge(path, name, probe)
              name, probe = None, None

  print("\n".join(lines))
  print(f"CONTAINERS {len(lines)}")
  for v in viol:
      print(v)
  print(f"VIOLATIONS {len(viol)}")
  sys.exit(1 if viol else 0)
  ```

  Two properties of the script worth preserving if you edit it. The HCL arm is a
  **line-oriented block walk**, not one regex per container name: a first attempt
  used a single regex and reported four false `FORBIDDEN`s per `main.tf`, because
  the pattern matched the file's *first* `healthCheck` for every name — a checker
  that reports violations where none exist is the mirror image of this advance's
  recurring defect and would have condemned a correct emitter. And `judge`'s
  `forbidden` **and** `not core` arms are **both** checked, so a probe appearing on
  something new and unclassified is caught, not only the three shapes known today.
- [ ] **B.11 Hex layout** — each **codebase** contains **exactly one** `src/root.py` (composition root — never `root_web.py` / `root_worker.py`, which would put two drifting copies of the driven wiring in the tree); each hex module contains `domain/`, `ports/{driving,driven}/`, `adapters/{driving,driven}/`, `alogic/`. Per [`hex_overview.md § Project Structure`](../../doctrine/hexagonal_architecture/hex_overview.md#project-structure) and [`internal_dependency_rules.md § Composition Root`](../../doctrine/hexagonal_architecture/internal_dependency_rules.md#composition-root).
- [ ] **B.11.1 `src/entrypoints/` present, one module per core service** — and each core service's `command` in `infra.yml` invokes exactly one of them. **The composition root constructs; it does not activate**: grep each `root.py` for a `uvicorn.run`, a `serve`, a `while True`, a bound/listening socket, or an `if __name__ == "__main__"` block. Any of those is a failure. **Grep `socket` with judgement, not mechanically:** a health handler that *constructs* a `socket.create_connection` to probe a backing service is legitimate (the seed's `api/src/root.py` does exactly this for `/health/events`) — what the rule forbids is the root *binding* or *listening*. The test is whether the root returns its graph un-activated — the runtime host (uvicorn, a broker's consume loop, a poll loop) belongs to the entrypoint, not to the root and not to an adapter. Without this item the audit cannot catch a project whose `root.py` still starts a server, which is precisely the shape CICL v2 makes inexpressible: with more than one core service sharing one image, at most one could be what `root.py` starts. Per [`internal_dependency_rules.md § Entrypoints`](../../doctrine/hexagonal_architecture/internal_dependency_rules.md#entrypoints).
- [ ] **B.12 Migrations idempotent + reversible** — every `core/<codebase>/migrations/*.sql` has both `-- migrate:up` and `-- migrate:down` sections. Per [`databases.md § Migrations`](../../doctrine/practices/databases.md#migrations).
- [ ] **B.13 Stage tester present** — `infra/stage/Dockerfile`, `infra/stage/stage_test.sh`, `infra/stage/tests/` all populated. Per [`tests.md § Staging Tests`](../../doctrine/infrastructure/tests.md#staging-tests).
- [ ] **B.14 Foundation-irrelevant code parity** — `diff -r test_projects/fixed/core test_projects/elastic/core` produces no output (other than `__pycache__` / `dist/` which are gitignored). This covers the entrypoints too: a core service whose entrypoint differs by foundation means the parts-only env model is leaking foundation specifics into application code — that's a doctrine bug.
- [ ] **B.15 Data-plane names hyphenate** — `grep -rE '{project_name_with_underscores}' infra/output/` (e.g. `docex_smoke_elastic`) finds only AWS record-key identifiers (IAM, SSM, DDB), tags, comments, and ECR repo names. No occurrence of an underscored project segment on a docker network/container/volume name, ECS Service Connect namespace, Route53 zone or record, or ACM cert. Per mod 030's hyphen-on-data-plane rule plus mod 046's leak fix.
- [ ] **B.16 No compiled compose gates a core service** — `grep -n 'depends_on' infra/output/*/docker-compose.yml` returns hits **only** inside the per-codebase `-exec` block. The compiler emits no `depends_on:` / `condition:` on any core-service block; the exec block still carries a `depends_on` entry over the union of that codebase's **backing-targeted** `uses` edges — `condition: service_healthy` where the target block declares a `healthcheck:`, `condition: service_started` where it does not (the fixed project's committed output shows `appdb → service_healthy`, `probe`/`events` → `service_started`) — and it is the one remaining ordering emission in existence. Per [`cicl.md § Uses Relationships`](../../doctrine/infrastructure/cicl.md#uses-relationships), which carries the connection-resilience mandate that replaced the retired startup gate. Both projects' `infra/output/` are git-tracked, so this is a grep, not a compile.
- [ ] **B.17 The schedule table renders and is delivered as a literal** — `infra/output/{dev,test,stage,prod}/schedules.yml` exists (the git-tracked, diff-visible aggregate an operator reads), and each clock's compose `environment:` / task-definition env carries **`DOCEX_SCHEDULES_YAML` holding the rendered YAML itself, not a path**. Grep for a mount or a `configs:` entry naming `schedules` and confirm there is **none** — a mount would mean the single-variable delivery seam regressed to a file, which is precisely what the design deleted. Per [`clock.md § How the schedule reaches the container`](../../doctrine/infrastructure/specifics/clock.md#how-the-schedule-reaches-the-container).

---

## C. Walk: docex_smoke_fixed

`cd test_projects/fixed/` for everything below. Each `./bin/docex` invocation re-uses the version pinned in `project.yml`.

### C.1 Preinfra + Projinfra

- [ ] `./bin/docex preinfra development` — exits 0. (HAProxy + `docex-ingress` present per A.3.1.)
- [ ] `./bin/docex projinfra up development` — brings up the four `${project_dns_label}-{dev,test,stage,prod}-web` networks and the per-project traefik container. The traefik joins all four `-web` networks plus `docex-ingress`. No traefik env vars are required: fixed certs use HTTP-01 (Gap A), and `TRAEFIK_ACME_EMAIL` is optional (see A.3.1).
  - **Ordering:** this must run *after* C.2's `docex compile`, since `projinfra up development` reads the compiled `infra/output/project/development/docker-compose.yml`. The numbered C.1/C.2 order here is presentational; in practice run `compile` first (compile is also idempotent and re-run defensively by most commands).
- [ ] For single-machine fixed (dev box also hosts prod): `./bin/docex projinfra up production` — idempotent no-op since dev and prod converge on the same host.

### C.2 Compile

- [ ] `./bin/docex compile` — succeeds, produces `infra/output/{dev,test,stage,prod}/docker-compose.yml`, `infra/output/{dev,test,stage,prod}/schedules.yml`, `infra/output/stage/{playbook.yml,inventory.yml,ansible.cfg}`, same for `prod`, and `infra/output/project/{development,production}/docker-compose.yml`. Nothing is written under `infra/secrets/` (mod 092 removed the `example.env` emit; the secret key set is derived on demand by `docex secrets scaffold`/`status`).

### C.3 Secrets

- [ ] Confirm A.8 was performed for `fixed/` — `dev.env`, `test.env`, `stage.env`, `prod.env` all populated.

### C.4 Dev sanity (optional but recommended)

> The `docex build` ordering note at [D.6](#d6-dev-sanity-optional-but-recommended) applies here too — the trap is a dev-compose property, not an elastic one.

- [ ] `./bin/docex build` — see the note above for the ordering (`envinfra up dev` first; there is nothing to `compose run` against until the stack is up).
- [ ] `./bin/docex envinfra up dev` — stack comes up; `https://dev.docex-smoke-fixed.luxrnd.tech/health` returns 200 with a `version` field.
- [ ] `./bin/docex envinfra down dev` — stack tears down (named volumes preserved).

### C.5 Test

- [ ] `./bin/docex test` — exits 0. One test run per **codebase**, and there is one codebase, so exactly **one** run — covering every module the codebase's three core services drive: `pings` (api.web), `processor` (api.worker), and `jobs` + `retention` (api.clock's deferrals and api.worker's draining of them).

### C.6 Check + Containerize

> **Feature-branch prerequisite (mod 053 / F8).** `check` and `merge` require a real feature-branch shape: `main` must sit at the **prior** release, and the **new** version (bumped `project.yml`) must live on a **feature branch** checked out now. `check` creates an ephemeral worktree merging the feature branch with `origin/main` and runs the gate checks (including "version bumped" and "version not yet released") against that merge. On a single-commit `main` with no feature branch the version-bump gate has nothing to compare against. Restructure the seed's git history to this shape by hand before C.6 if it isn't already (this is the by-hand restructure the smoke walk performs). This deliberately conflicts with [A.2.1](#a21-test-projects-are-self-contained-git-repos)'s resting state — see its ordering carve-out.
>
> **A reachable `origin` is required.** `check`/`merge` run `git fetch origin` from **inside** the docex container, which mounts the project root and specific `$HOME` subdirs (`~/.docker`, `~/.aws`, `~/.gitconfig`, `~/.ssh`) — **not** arbitrary `$HOME` paths. So a local bare remote must live **under the project root** to be container-visible. Create one in the gitignored `.docex/` (e.g. `git init --bare .docex/origin.git`), `git remote add origin .docex/origin.git`, and `git push origin main v<prior>` so `origin/main` sits at the prior release. The restructure: delete the current `v<new>` tag (merge recreates it), branch the new-version work onto a feature branch, move `main` back to `v<prior>`, push `main` to origin, and check out the feature branch.

- [ ] `./bin/docex check` — exits 0. Runs gate checks against an ephemeral worktree (feature branch ⊕ `origin/main`).
- [ ] `./bin/docex merge` — **required, and easy to miss: `containerize` refuses to run off `main`.** The real chain is `check` (on the feature branch) → `merge` → `containerize`. `merge` rebases onto `main`, tags `v<version>` at the new HEAD, and pushes both. Note it prints `error: failed to push some refs` while still **exiting 0** when the feature branch was never pushed to origin (it tries to delete a remote branch that does not exist) — alarming, harmless.
- [ ] `./bin/docex containerize` — succeeds; **one image per codebase**, and there is one codebase, so exactly **one** repo: `registry.luxrnd.tech/docex_smoke_fixed/api:<v>` pushes successfully. The old `…/web` and `…/worker` are gone: `api-web`, `api-worker`, and `api-clock` all share the `api` tag and differ only by `command`. Confirm no **second** repo appears — a second one means a codebase was reintroduced. (Repo names preserve project-segment underscores per mod 030's structural emitter — this is correct.)

### C.7 Release stage

- [ ] `./bin/docex release stage` — ansible playbook completes; `https://stage.docex-smoke-fixed.luxrnd.tech/health` returns 200.

### C.8 Stagetest

- [ ] `./bin/docex stagetest` — exits 0. **It now runs the orchestrator
  liveness/version gate BEFORE the tester image is built**, reading every core
  service's health and version by `docker inspect` **over SSH** to the deployed host
  (fixed `stage`/`prod` do not run on the operator's machine). A failure here is
  `DeployedServiceUnhealthy` (the orchestrator's honest bad answer) or
  `OrchestratorStateUnreadable` (`docex` could not get an answer at all) and happens
  **before any image build** — record which one you got, because it is a strictly
  earlier and cheaper failure than a tester failure.
  **An empty result set never reads as healthy**: zero core services, zero running
  containers, and an unreadable container all fail loudly. **There is no flag that
  disables the gate** — if the walk hurts here, the gate is reporting something.
- [ ] Then the tester's own probes: `/health` on the web edge,
  `/diagnostics/{probe,events}` for the two project-local container backings, the
  `POST /pings` critical path, and the **defer-then-drain round trip** that replaced
  the deleted liveness fan-out test. That round trip asserts **no exact count** — the
  worker's own poll loop legitimately races it.

### C.9 Release prod

> **Do not skip this step.** `replicas` is honoured in **`prod` only** — it clamps to 1 in `dev`, `test`, and `stage`, and every integration test runs against `dev`. **This prod release is the only thing in existence that exercises the fixed replica unroll.** Nothing else — no unit test, no integration test, no stagetest, no elastic walk — ever emits or runs the multi-service form. Stopping the walk after C.8 means shipping that code untested, with the first execution happening in a downstream project's production environment. The unroll is what turns one declared core service into `…-api-worker-1` and `…-api-worker-2`, each with its own `container_name` and its own otelcol sidecar, sharing one network **alias** equal to the unqualified global name (which is what the five-segment magic refs resolve to, so a broken alias breaks `WORKER_HOST` resolution and therefore `api.web`'s `POST /drain` call onto the worker's `rpc` surface — an application path, and a *better* canary than the retired fan-out route was, because it carries real traffic).

- [ ] `./bin/docex release prod` — completes. Three URLs must all return 200 with the same `version` field (prod's `domain_default_service`, `api.web`, answers at all three):
  - `https://api-web.prod.docex-smoke-fixed.luxrnd.tech/health` (canonical, **two-segment** service label)
  - `https://prod.docex-smoke-fixed.luxrnd.tech/health` (bare-env → `domain_default_service`)
  - `https://docex-smoke-fixed.luxrnd.tech/health` (bare-project → prod's bare env → `domain_default_service`)
- [ ] **Every core service's container probe reports healthy.** This is the probe's
  enforcement point and, for the two non-`web` core services, the **only**
  externally-available statement about their liveness:
  ```bash
  for c in api-web api-worker-1 api-worker-2 api-clock; do
    printf '%s\t' "$c"
    docker inspect --format '{{.State.Health.Status}}' "…-prod-$c"
  done
  ```
  All `healthy`. A `starting` that never converges on a worker or the clock means the
  loop has not completed a first iteration — `health.sh` fails an absent tick file
  deliberately. There is no fan-out route to check and no stage test that can reach
  these two; the probe **is** the check.
- [ ] **The defer → drain round trip is the externally-observable proof of worker
  liveness** — the clock group below already walks it. A wedged worker shows as
  `jobs: 'heartbeat' deferred` with no matching `performed`, plus an `unhealthy`
  probe above.
- [ ] `docker ps` shows **two** worker containers, `…-prod-api-worker-1` and `…-prod-api-worker-2`, plus one otelcol sidecar each. `docker network inspect …-prod-internal` shows both carrying the alias `…-prod-api-worker`.
- [ ] POST a ping to `https://docex-smoke-fixed.luxrnd.tech/pings` — returns 201. The body field is `payload` and it is required (`infra/contracts/api.web.rest.openapi.yml`, `required: [payload]`); a `{"message": …}` body returns **422**, not 201.
  ```bash
  curl -sS -X POST https://docex-smoke-fixed.luxrnd.tech/pings \
    -H 'Content-Type: application/json' -d '{"payload": "walk-ping"}'
  ```
- [ ] After ~5s, query the prod postgres database directly: the ping row exists and has a non-NULL `processed_at` (a worker replica picked it up).

> **Clock — fire → defer → drain.** The minutely `heartbeat` job exists solely so this path is observable inside a walk window; `prune_pings` is `0 3 * * *` and will **not** fire during the walk, so do not wait for it.

- [ ] The clock started and its schedule arrived. `docker logs …-prod-api-clock` shows `clock: 2 scheduled job(s): heartbeat, prune_pings; image implements: …`. This line is still the evidence the schedule **arrived**, so read it — but the comparison itself is now **asserted by the clock at startup** ([`clock.md § How the schedule reaches the container`](../../doctrine/infrastructure/specifics/clock.md#how-the-schedule-reaches-the-container)): a scheduled name with no binding makes the process exit non-zero before entering its loop. So the symptom of a mismatch is a **crash-looping clock container**, not a silently-wrong one — and if the clock is running and logging this line, the binding check has already passed.
- [ ] A fire deferred. Within ~65 s the same log shows `jobs: 'heartbeat' fired` followed by `jobs: 'heartbeat' deferred as job <uuid>`. **Both lines, not one** — "fired" without "deferred" is the clock reaching the queue and failing.
- [ ] The worker drained it. `docker logs …-prod-api-worker-1` (or `-2`) shows `jobs: 'heartbeat' performed (job <uuid> …)` carrying the **same uuid**. Matching the uuid is what makes this a proof of the deferral path rather than of two unrelated log lines.
- [ ] Confirmed in the database: the `jobs` row for that uuid has non-NULL `finished_at` and NULL `error`. Use the same prod postgres access the ping check above already established.
- [ ] The clock answers its own probe: `docker inspect --format '{{.State.Health.Status}}' …-prod-api-clock` is `healthy`, and so does `…-prod-api-worker-1` / `-2`. **This is the only enforcement any non-`web` core service gets** — nothing routes to them, so no stage test can reach them — so an operator who skips this box has verified nothing about their liveness surface. The clock stopped being a special case here: it is the *first* case of what is now the general rule, and the worker is the second.

> **⚑ Data collection, not a gate.** `cicl.md` rule 33 states that nothing on fixed
> reroutes traffic away from an unhealthy container, and that whether traefik's
> Docker provider **passively** withholds routing is a property of that tool the
> doctrine does not verify. The fixed walk can answer it empirically for the price
> of four commands. **Record the observation either way** — *neither outcome fails
> the cut.* A walk that answers this converts a doctrinal hedge into a fact about
> the traefik version in use; a walk that skips it leaves the hedge exactly as
> strong as it already is, which is the honest fallback.

- [ ] **Does an unhealthy container still receive traffic on fixed?**
  1. Wedge `api-web`'s probe **from the host** per **B.10**'s wedging block —
     `kill -STOP` against `{{.State.Pid}}`. (Inside the container it is a no-op.)
  2. Poll until Docker reports it: `docker inspect --format '{{.State.Health.Status}}' …-prod-api-web`
     is `unhealthy`. Three failed 30 s intervals, so allow ~2 minutes.
  3. `curl -sS -o /dev/null -w '%{http_code}\n' https://docex-smoke-fixed.luxrnd.tech/health`
     — **record the code**, and record the traefik image tag from
     `docker inspect --format '{{.Config.Image}}' …-traefik`.
  4. `kill -CONT` the pid; confirm the status returns to `healthy`.

  Write the result into the walk log as an observation about that traefik version,
  **not** as a doctrine claim. If traffic still arrives, rule 33's "do not rely on
  it" is confirmed as necessary. If it does not, the doctrine may later be able to
  state the passive behavior — but only after a second walk reproduces it, since one
  observation of one version is not a doctrine.

### C.10 Rollback walk

Exercises `docex rollback` against the real fixed-foundation prod env. The current version was just deployed (C.9); to roll back, we need a *prior* version in the registry. Bump the test project once and re-deploy so two versions coexist, then roll back to the older one.

**Coverage note.** Both versions in this rollback are created *after* the `cicl_version` `"2"` → `"3"` bump, so the cross-generation rollback refusal documented in [`upgrade_1.7.0.md`](../../upgrades/upgrade_1.7.0.md) is **not** exercised here. A green rollback walk is not evidence that the trap is gone.

- [ ] Bump the test project's `project.yml` version (e.g. 0.0.X → 0.0.X+1). Inner-repo commit per `test_projects.md § Commit cadence`; force-move (or re-create) the `v<version>` tag at the new HEAD.
- [ ] `./bin/docex containerize` — pushes `v0.0.X+1` to the registry alongside `v0.0.X`.
- [ ] `./bin/docex release prod` — deploys v0.0.X+1; the three `/health` URLs report v0.0.X+1.
- [ ] `./bin/docex rollback prod 0.0.X` — recompiles v0.0.X in an ephemeral worktree, ansible re-renders the older compose with `--skip-tags migrate`, prod converges on v0.0.X.
- [ ] The three `/health` URLs report v0.0.X. The prior ping row still has its `processed_at` populated (schema unchanged across this micro-version step).
- [ ] `./bin/docex rollback prod 0.0.X --dry-run` (against the now-rolled-back env) — exits 0 and prints `release: prod dry-run completed (ansible --check).` with no state mutation. Optional sanity check; skip if pressed for time.

### C.11 Teardown

- [ ] `bash teardown.sh` — succeeds. Brings down every env's compose stack with named volumes, deletes registry images for this project, then removes the project traefik / four `-web` networks (the `projinfra down` step). Compiled output is cleared.
- [ ] `bash verify_clean.sh` — exits 0. No lingering containers, networks, volumes, local images, or registry images carry the project's name prefix (underscored OR hyphenated form).

  **The script now fails whenever any check cannot be *answered*, not only when a leftover is found.** That covers a missing `~/.docker/config.json` credential for `registry.luxrnd.tech`, a non-200 from `/v2/_catalog` or `/v2/<repo>/tags/list`, an unparseable body, **and an unreachable docker daemon** — the container/network/volume checks now report `the check could not answer` with the docker error attached, where they previously counted zero lines and printed `OK`. Every one of those cases exits non-zero; the previous version swallowed all of them and reported "clean". A green run is therefore now evidence that each check actually *ran*, which was not previously true: the registry query was unauthenticated, 401'd on every call, and reported zero tags for several releases while the registry held thirty.

  Repositories whose tag list is **null** are expected and are not leftovers. The Registry V2 API keeps a repository entry after its last manifest is deleted, until the operator runs [`container_registry.md § Garbage Collection`](../../doctrine/infrastructure/preinfra/container_registry.md#garbage-collection). The check keys on tags, not on repository presence.

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

- [ ] `./bin/docex compile` — succeeds; produces `infra/output/{dev,test}/docker-compose.yml`, `infra/output/{stage,prod}/main.tf`, `infra/output/{dev,test,stage,prod}/schedules.yml`, `infra/output/project/{development/docker-compose.yml,production/main.tf}` (production was already applied by D.3). Nothing is written under `infra/secrets/` (mod 092 — the secret key set is derived on demand by `docex secrets scaffold`/`status`).

### D.5 Secrets

- [ ] Confirm A.8 was performed for `elastic/` — `dev.env`, `test.env`, `stage.env`, `prod.env` all populated.

### D.6 Dev sanity (optional but recommended)

`dev` and `test` envs run as fixed compose stacks even on an elastic-foundation project (per [`shape.md § Shape and Environment`](../../doctrine/infrastructure/shape.md#shape-and-environment)).

> **`docex build` is required first on a fresh or restructured codebase.** The dev compose bind-mounts `./core/<codebase>/dist:/service/dist`, so the **host's** `dist/` shadows whatever `docker build` put in the image. A codebase whose entrypoints changed (or that is new) leaves a stale host `dist/`, and every core service crash-loops with `python: can't open file '/service/dist/entrypoints/<service>.py'` — taking its netns-paired otelcol sidecar down with it (`cannot join network namespace of container … is restarting`).
>
> `docex build` gates on the *whole stack* being up, not the individual container, so the working order is: `envinfra up dev` (backings come up, core crash-loops) → `docex build` → `envinfra up dev` again. Running `build` first does not work — there is nothing to `compose run` against.
>
> **This is the same trap as B.10's second wedging hazard, and it bites the probe too:** a stale host `dist/` means the stack runs **pre-mod** entrypoints, so a loop-owner's probe answers "no tick file" — indistinguishable from the absent-tick arm working correctly. Stated in full once, in **B.10**.

- [ ] `./bin/docex build` — see the note above; run it before or after a failed first `envinfra up dev`.
- [ ] `./bin/docex envinfra up dev` — stack comes up locally. With the A.4.2 child-zone records in place, `https://dev.docex-smoke-elastic.luxrnd.tech/health` and the two-segment `https://api-web.dev.…/health` both answer 200, and `/diagnostics/probe` + `/diagnostics/events` answer for the two project-local container backings. There is **no** `/health/<codebase>/<service>` route to probe — the fan-out is deleted, and the diagnostics routes deliberately do not live under `/health/` so no reader concludes it survived under a narrower name.
- [ ] `./bin/docex envinfra down dev`.

### D.7 Test

- [ ] `./bin/docex test` — exits 0.

### D.8 Check + Containerize

> **Feature-branch prerequisite (mod 053 / F8).** As in C.6: `check`/`merge` need `main` at the prior release and the new version on a feature branch checked out now (the worktree merges feature ⊕ `origin/main`). Also note the D.3/D.7 ordering — `compile` must run before any `projinfra up`, since `projinfra up production`'s phase-2 `tofu apply` reads the compiled project-tier `main.tf`. This deliberately conflicts with [A.2.1](#a21-test-projects-are-self-contained-git-repos)'s resting state — see its ordering carve-out.

- [ ] `./bin/docex check` — exits 0.
- [ ] `./bin/docex merge` — **required; `containerize` refuses to run off `main`** (see C.6 for the full note).
- [ ] `./bin/docex containerize` — succeeds; **one ECR repo and one image per codebase**: `<account>.dkr.ecr.us-east-1.amazonaws.com/docex_smoke_elastic/api:<v>`. The old `{web,worker}` repos are gone — `api-web`, `api-worker`, and `api-clock` all share the `api` tag. Confirm D.3 phase 2 provisioned exactly **one** ECR repo; a second appearing means a codebase was reintroduced. Authenticates against ECR via `aws ecr get-login-password` per invocation.

### D.9 Release stage

- [ ] `./bin/docex release stage` — first-time-release path detected (ECS cluster absent); ordering swaps to `SSM push → tofu apply → migrate`. ALB listener rules, ECS cluster, ECS services for `api-web`/`api-worker`/`api-clock`/`probe`/`events`, RDS instance, EFS filesystem + mount targets for `events`, all come up. `https://stage.docex-smoke-elastic.luxrnd.tech/health` returns 200.
- [ ] `api-clock` came up as an **ordinary ECS service** — an `aws_ecs_task_definition` **and** an `aws_ecs_service`, its own CloudWatch log group, a paired otelcol sidecar, and a container-level `healthCheck`. It is a long-running singleton, not an invocation. Confirm `aws ecs list-services` shows exactly **five**: `api-web`, `api-worker`, `api-clock`, `probe`, `events`.
- [ ] **Record both reconcile operands, and the verdict.** The consumers are the
  core services that declare a **core-targeted** `uses` entry — here `api-web`
  and `api-clock`, both targeting `api.worker`. `api.worker` itself declares
  `uses: [appdb]` only, and a backing-targeted entry never makes a consumer, so
  the worker is a target and never a consumer; **there is no `uses` cycle in
  this project.** For each consumer:
  ```bash
  aws ecs describe-services --cluster docex-smoke-elastic-stage \
    --services api-web api-clock \
    --query "services[].[serviceName,deployments[?status=='PRIMARY']|[0].createdAt]"
  aws servicediscovery list-services \
    --query "Services[].[Name,CreateDate]"
  ```

  `release`'s own output states the count it used — `N consumer(s) checked`.
  **If `N` is not 2, the consumer set has changed and this box is stale**;
  re-derive it from `infra.yml` before recording anything.

  Write both timestamps into the walk log. **Expected verdict: `fire` on this
  first `stage` release** — deployment and name are created seconds apart — and
  **`skip` on the code-only 0.0.21 release**, where the gap is days.

  The two verdicts are distinguishable in `release`'s own output, and both are
  explicit — neither is silence:

  | Verdict | What `release` prints |
  | ------- | --------------------- |
  | **fire** | one `release: reconciling Service Connect consumer '<name>' — its current deployment predates …` line per consumer, then the bounded steady-state wait |
  | **skip** | ``release: Service Connect reconcile — N consumer(s) checked, all deployments postdate the endpoints they `uses`; nothing to redeploy.`` |

  **Neither line appearing is itself a finding** — it means the step
  short-circuited before comparing anything, and the two other paths say so
  (``no endpoints registered in the <env> namespace …`` / ``no core service
  declares a core `uses` target …``). Whichever line you get must agree with the
  two timestamps you recorded.

  > **Why this box exists.** The 1.7.0 walk measured the wrong timestamp (task
  > `startedAt`, mod 114) and `force-new-deployment` overwrote the evidence
  > before anyone knew which one mattered — so the failure had to be inferred
  > from a 503 rather than read off the operands. Recording both is what lets a
  > walk *confirm* the predicate instead of inferring it from a green fan-out.

- [ ] **Nothing scheduler-shaped exists anywhere.** Assert twice, because the two assertions catch different failures. **Emission:** `grep -nE 'aws_scheduler_schedule|scheduler\.amazonaws\.com' infra/output/*/main.tf` returns nothing. **Leak:** `aws scheduler list-schedules` returns no schedule carrying the project prefix, and no IAM role matching `docex-smoke-elastic-*-scheduler*` survives. The first proves the compiler stopped emitting; the second proves nothing was orphaned by a teardown filter that no longer matches — the silent failure mode the upgrade guide flags.
- [ ] Exactly **one** `…-migrate` task-definition family exists for the `api` codebase — not one per core service.
- [ ] `api-worker` has a container-level `healthCheck` and **no** target group; `api-web` has the target group. Its `desired_count` is **1** here (`replicas: 2` clamps outside prod).

### D.10 Stagetest

- [ ] `./bin/docex stagetest` — exits 0. **It now runs the orchestrator
  liveness/version gate BEFORE the tester image is built**, reading every core
  service's health and version through ECS `list_tasks` / `describe_tasks` /
  `describe_task_definition`. A failure here is `DeployedServiceUnhealthy` or
  `OrchestratorStateUnreadable` and happens **before any image build** — record which
  one you got. **An empty result set never reads as healthy**: zero core services,
  zero RUNNING tasks, and an unreadable container all fail loudly. **There is no flag
  that disables the gate** — if the walk hurts here, the gate is reporting something.
- [ ] Then the tester's own probes: `/health` on the web edge,
  `/diagnostics/{probe,events}`, the POST `/pings` critical path, and the
  **defer-then-drain round trip** that replaced the deleted liveness fan-out test
  (it asserts **no exact count** — the worker's own poll loop legitimately races it).

### D.11 Release prod

- [ ] `./bin/docex release prod` — first-time-release path for prod env. Provisions the prod ECS services + RDS + EFS alongside stage on the same project-tier ALB.
- [ ] Three `/health` URLs return 200 (same shape as fixed C.9):
  - `https://api-web.prod.docex-smoke-elastic.luxrnd.tech/health` (canonical, **two-segment** service label)
  - `https://prod.docex-smoke-elastic.luxrnd.tech/health` (bare-env → `domain_default_service`)
  - `https://docex-smoke-elastic.luxrnd.tech/health` (bare-project → prod's bare env → `domain_default_service`)
- [ ] **Every core service's ECS container health is `HEALTHY`**, and for
  `api-worker` / `api-clock` this is the only externally-available statement about
  their liveness:
  ```bash
  aws ecs list-tasks --cluster docex-smoke-elastic-prod --query 'taskArns[]' --output text \
    | xargs aws ecs describe-tasks --cluster docex-smoke-elastic-prod --tasks \
    --query 'tasks[].{group:group,health:healthStatus,containers:containers[].{n:name,h:healthStatus}}'
  ```
  On elastic the probe is load-bearing in a way it is not on fixed: **ECS kills and
  replaces** a task whose essential container fails, so a wrong probe is a crash
  loop rather than a stale status. `startPeriod: 10` is what keeps a normal start
  from tripping it.
- [ ] **Service Connect still resolves the sibling core service.** The old fan-out
  box proved this incidentally; nothing else does, so assert it directly: `api.web`
  reaching `api.worker`'s `rpc` surface (`POST /drain`) is what the worker's `port`
  makes discoverable. The defer → drain round trip below is the end-to-end proof; a
  resolution failure shows as `api-web` logging a connection error to
  `WORKER_HOST`, **while both services report healthy** — no external signal at all,
  which is why [D.9](#d9-release-stage)'s reconcile box exists.
- [ ] **Record both reconcile operands, and the verdict.** The consumers are the
  core services that declare a **core-targeted** `uses` entry — here `api-web`
  and `api-clock`, both targeting `api.worker`. `api.worker` itself declares
  `uses: [appdb]` only, and a backing-targeted entry never makes a consumer, so
  the worker is a target and never a consumer; **there is no `uses` cycle in
  this project.** For each consumer:
  ```bash
  aws ecs describe-services --cluster docex-smoke-elastic-prod \
    --services api-web api-clock \
    --query "services[].[serviceName,deployments[?status=='PRIMARY']|[0].createdAt]"
  aws servicediscovery list-services \
    --query "Services[].[Name,CreateDate]"
  ```

  `release`'s own output states the count it used — `N consumer(s) checked`.
  **If `N` is not 2, the consumer set has changed and this box is stale**;
  re-derive it from `infra.yml` before recording anything.

  Write both timestamps into the walk log. **Expected verdict: `fire` on this
  first `prod` release** — deployment and name are created seconds apart — and
  **`skip` on the code-only 0.0.21 release**, where the gap is days.

  The two verdicts are distinguishable in `release`'s own output, and both are
  explicit — neither is silence:

  | Verdict | What `release` prints |
  | ------- | --------------------- |
  | **fire** | one `release: reconciling Service Connect consumer '<name>' — its current deployment predates …` line per consumer, then the bounded steady-state wait |
  | **skip** | ``release: Service Connect reconcile — N consumer(s) checked, all deployments postdate the endpoints they `uses`; nothing to redeploy.`` |

  **Neither line appearing is itself a finding** — it means the step
  short-circuited before comparing anything, and the two other paths say so
  (``no endpoints registered in the <env> namespace …`` / ``no core service
  declares a core `uses` target …``). Whichever line you get must agree with the
  two timestamps you recorded.

  > **Why this box exists.** The 1.7.0 walk measured the wrong timestamp (task
  > `startedAt`, mod 114) and `force-new-deployment` overwrote the evidence
  > before anyone knew which one mattered — so the failure had to be inferred
  > from a 503 rather than read off the operands. Recording both is what lets a
  > walk *confirm* the predicate instead of inferring it from a green fan-out.

- [ ] `aws ecs describe-services` reports `desired_count = 2` and two RUNNING tasks for prod's `api-worker` (`replicas: 2` is honoured in prod only).
- [ ] POST a ping to `https://docex-smoke-elastic.luxrnd.tech/pings` — returns 201; after ~5s the prod RDS shows the row with non-NULL `processed_at`. Same body shape as [C.9](#c9-release-prod): the field is `payload` and it is required, so `{"message": …}` returns 422.
  ```bash
  curl -sS -X POST https://docex-smoke-elastic.luxrnd.tech/pings \
    -H 'Content-Type: application/json' -d '{"payload": "walk-ping"}'
  ```

> **Clock — fire → defer → drain.** Same group as [C.9](#c9-release-prod), translated to elastic. The minutely `heartbeat` job exists solely so this path is observable inside a walk window; `prune_pings` is `0 3 * * *` and will **not** fire during the walk, so do not wait for it.

- [ ] **Expect one failed fire before the migration lands, and do not read it as a regression.** The first-release ordering is `SSM → tofu apply → migrate`, so `api-clock` starts before the schema exists; its first `heartbeat` logs `psycopg2.errors.UndefinedTable: relation "jobs" does not exist`. This is the documented ordering ([`migrations.md § First-Time Release of an Env`](../../doctrine/infrastructure/specifics/migrations.md#first-time-release-of-an-env)) and it self-heals ([`clock.md § Caveats`](../../doctrine/infrastructure/specifics/clock.md#caveats)); the next tick ~60 s later succeeds. The same happens on the D.9 `stage` release, where no box reads the clock's log. **A clock still failing two ticks after the migration completed is a genuine finding.**
- [ ] The clock started and its schedule arrived. The `/docex_smoke_elastic/prod/api-clock` CloudWatch log group shows `clock: 2 scheduled job(s): heartbeat, prune_pings; image implements: …`. This line is still the evidence the schedule **arrived**, so read it — but the comparison itself is now **asserted by the clock at startup** ([`clock.md § How the schedule reaches the container`](../../doctrine/infrastructure/specifics/clock.md#how-the-schedule-reaches-the-container)): a scheduled name with no binding makes the task exit non-zero before entering its loop. So the symptom of a mismatch is an **ECS task that never reaches RUNNING steady state**, not a silently-wrong clock — and if the clock is logging this line, the binding check has already passed.
- [ ] A fire deferred. Within ~65 s the same log group shows `jobs: 'heartbeat' fired` followed by `jobs: 'heartbeat' deferred as job <uuid>`. **Both lines, not one** — "fired" without "deferred" is the clock reaching the queue and failing.
- [ ] The worker drained it. The `/docex_smoke_elastic/prod/api-worker` log group shows `jobs: 'heartbeat' performed (job <uuid> …)` carrying the **same uuid**. Matching the uuid is what makes this a proof of the deferral path rather than of two unrelated log lines.
- [ ] Confirmed in the database: the `jobs` row for that uuid has non-NULL `finished_at` and NULL `error`. Use the same prod RDS access the ping check above already established.
- [ ] The clock answers its own probe: `aws ecs describe-tasks` reports the `api-clock` task's container health status as `HEALTHY` — and so does `api-worker`'s. **This is the only enforcement any non-`web` core service gets** — nothing routes to them, so no stage test can reach them — so an operator who skips this box has verified nothing about their liveness surface. The clock stopped being a special case here: it is the *first* case of what is now the general rule, and the worker is the second.
- [ ] `aws ecs describe-services` reports `desired_count = 1` for `api-clock`. A clock declares no `replicas` and rule 26 forbids it — a 2 here means two cron loops and a double fire on every tick.

### D.12 Rollback walk

Same intent as C.10 but against elastic prod. The rollback path pushes SSM and runs an unrestricted `tofu apply` against the recompiled v0.0.X HCL — no migration RunTask, no pre-migrate targeted apply.

**Coverage note.** Both versions in this rollback are created *after* the `cicl_version` `"2"` → `"3"` bump, so the cross-generation rollback refusal documented in [`upgrade_1.7.0.md`](../../upgrades/upgrade_1.7.0.md) is **not** exercised here. A green rollback walk is not evidence that the trap is gone.

- [ ] Bump the test project's `project.yml` version (e.g. 0.0.X → 0.0.X+1). Inner-repo commit + tag move.
- [ ] `./bin/docex containerize` — pushes `v0.0.X+1` to ECR alongside `v0.0.X`.
- [ ] `./bin/docex release prod` — deploys v0.0.X+1 (steady-state path now that prod exists).
- [ ] `./bin/docex rollback prod 0.0.X` — recompiles v0.0.X in an ephemeral worktree, pushes SSM, runs `tofu apply` (no targets), ECS rolls v0.0.X out.
- [ ] The three `/health` URLs report v0.0.X. RDS data preserved.
- [ ] `./bin/docex rollback prod 0.0.X --dry-run` — exits 0; `tofu plan` runs, SSM push and `tofu apply` do NOT. Optional.

### D.13 Teardown

- [ ] `bash teardown.sh` — disables RDS deletion_protection (polled until landed in AWS), direct-deletes RDS instances with `--skip-final-snapshot` (polled until gone), purges ECR images/repos, then runs `tofu destroy` for prod, stage, project tier in that order. Cleans SSM parameters and the tofu state bucket + lock table.
- [ ] `bash verify_clean.sh` — exits 0. AWS API queries for every doctrine-emitted resource type filtered by project-name prefix return empty.

  **The script now fails whenever a check cannot be *answered*, not only when a resource is found.** This matters more here than on fixed. Previously every one of the ~20 checks swallowed its `aws` error, so **expired credentials, an unset/wrong region, or one missing IAM permission produced twenty `OK:` lines and exit 0** — a "clean" verdict on an account that was still running RDS instances and ALBs and still billing for them. Now a failed call prints `the check could not answer` with the AWS error attached, and a failed `sts get-caller-identity` **aborts before any check runs** rather than emitting twenty meaningless greens.

  **Eyeball the first line.** The script opens with `==>   interrogating AWS account <id> in region <region>`. Confirm both are the ones you meant to tear down — a completely clean run against the *wrong account* is the one false green that reading the rest of the output cannot detect, because every line is `OK:` and every line is true.

---

## E. After both walks succeed

> **Neither walk may stop at stagetest.** Two pieces of shipped code are covered by the **prod release steps alone**:
>
> - **The fixed replica unroll (C.9).** `replicas` clamps to 1 in `dev`, `test`, and `stage`, and every integration test runs against `dev`, so the multi-service form — `-1`/`-2` suffixes, per-replica `container_name`, per-replica sidecar, the shared network alias — is emitted and executed nowhere else. Skipping C.9 ships it untested.
> - **The elastic `desired_count > 1` path (D.11).** Same clamp, same consequence, and the first place a core service that does not tolerate siblings will fail.
>
> A core service that cannot run alongside a copy of itself therefore first surfaces in **production**. That is a known limitation of the prod-only clamp, and it is the reason these two steps are not optional.

- [ ] Both `verify_clean.sh` runs are green.
- [ ] No leftover state in Route53 except: the parent `luxrnd.tech` zone; **the nine standing fixed-walk `A` records from [A.4.1](#a41-fixed-walk-dns)**; and any other unrelated records the operator runs. Those nine are *expected* to remain — deleting them breaks the next fixed walk at A.4.1, which is the contradiction this exemption repairs. The elastic walk's records, by contrast, are temporary and A.4.2 requires their removal, **including the parent-zone `NS` delegation**.
- [ ] No registry images for `docex_smoke_fixed` or `docex_smoke_elastic` remain.
- [ ] AWS cost report for the smoke-test window matches expectations (~$X for 1–2 hours of stage+prod elastic infra; verify against running tally).

The cut is now safe to perform per [`RELEASING.md § The Cut Procedure`](../../RELEASING.md#the-cut-procedure).
