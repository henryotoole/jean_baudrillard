---
version: "1.1.0"
severity: major
kind: rebuild
scope: [project]
---

# Upgrading a project to docex 1.1.0

A runbook for moving an existing project from a **pre-1.0.0** `docex` pin up to
**1.1.0**. The jump crosses the shape-and-tier overhaul (mods 030–045, cut as
1.0.0) plus the polish campaign (mods 049–053, cut as 1.1.0); the full per-cut
narrative is in [`../CHANGELOG.md`](../CHANGELOG.md).

> **Predates the unified version.** This is the oldest guide on the
> [upgrades tape](./README.md). `1.1.0` was a `docex`-only version (the
> doctrine-wide scheme starts at `1.3.0`), so this guide speaks in terms of a
> project's `docex` pin — which, retroactively, is the doctrine version that
> project sits on. As a `kind: rebuild` guide it is start-point-agnostic: it
> carries its own internal branches (full rebuild below; the `1.0.x` shortcut in
> Appendix A), so the chain applies it whole regardless of where you start.

> **Already on 1.0.x?** You have the new shape already. Skip to
> [Appendix A](#appendix-a-shortcut-for-projects-already-on-10x) — it's a repin
> + recompile + redeploy, not a rebuild.

---

## Why this is a rebuild, not an in-place upgrade

The 1.0.0 cut changed two things that make `tofu apply` / `compose up` over the
old deployment impossible:

1. **Data-plane names flipped underscore → hyphen (mod 030).** Every Docker
   container/network/volume and every ECS cluster/service/task-def/RDS/SG name
   went from `project_env_svc` to `project-env-svc`. OpenTofu and Compose see
   the renamed resources as *brand-new* resources, not as the old ones moved —
   so an apply would try to stand up a parallel hyphenated stack beside the
   still-running underscored one rather than reconcile it.

2. **The elastic shape was rebuilt around new tiers (mods 035–044).** The
   per-project VPC became the shared **master VPC** (preinfra); the per-env ALB
   became one **project-tier** ALB; **ECR**, **IAM task-execution role**, and the
   **Route53 zone** moved to the project tier; the zone name changed from the
   bare apex to `<project>.<apex_domain>`. The old env-tier HCL and the new HCL
   describe structurally different infrastructure under the same state keys.

Because old compiled output and old tofu/compose state describe resources the
new `docex` will never recognize as the same, the safe path is: **tear the old
stage/prod infra down to bare metal first, then rebuild fresh under 1.1.0.**

This guide assumes a **bare-metal** teardown — everything project-related on the
production side is destroyed, including the elastic state backend, ECR, and the
Route53 zone. Nothing reusable is preserved; the rebuild re-creates it all.

---

## Order of operations (and why)

```
A. Pre-flight          — back up data, record NS + secrets, confirm old state is intact
B. Tear down old infra — BARE METAL, using the still-pinned old docex / old output / old state
C. Install docex 1.1.0 — build image (if needed) + docex_install.sh (repins + updates shim)
D. Update infra.yml    — 1.1.0 CICL surface; recompile
E. Stand up preinfra   — dev-side docex-ingress + HAProxy demux; elastic prod-side master VPC
F. Rebuild & re-release— projinfra up → envinfra smoke → CI/CD pipeline → restore data
```

The single rule that fixes the ordering: **do not run the new `docex` against
the project until the old infra is gone.** Phase B leans on the old compiled
output (`infra/output/`, git-tracked) and the old tofu/compose state, which
still match what's deployed. Phase C's repin and Phase D's `docex compile`
*overwrite* `infra/output/` with the new shape — once you do that, you've lost
the clean teardown reference. So teardown (B) happens while the old version is
still pinned, before install (C).

Installing the 1.1.0 shim + repinning (Phase C) is itself harmless — it neither
compiles nor deploys. The danger is only `compile` / `projinfra up` / `release`.
Hold those until Phase B is verified complete.

---

## Phase A — Pre-flight

1. **Back up every stateful backing service. This is the one irreversible
   step.** Bare-metal teardown deletes databases and object stores along with
   everything else.
   - **Postgres / relational DBs:** `pg_dump` (or the engine's equivalent) each
     `stage` and `prod` database to a file you keep off the torn-down infra.
   - **Object stores (S3/minio):** sync bucket contents somewhere durable.
   - **EFS-backed container backings** (ClickHouse, persistent Redis, etc.): copy
     the data directory off.
   You will restore from these after the new `prod` is live (Phase F).

2. **Record the parent-registrar NS delegation (elastic).** Note which
   nameservers the parent zone currently delegates to. The new Route53 zone is a
   *different* zone with *different* NS records, so you will re-delegate in
   Phase F — but you want the current state recorded in case you need to roll
   back the registrar change.

3. **Confirm your secrets are in `infra/secrets/`.** Bare-metal teardown wipes
   SSM (elastic) and the host `.env` (fixed). The source of truth —
   `infra/secrets/{stage,prod}.env` — must be present and complete, because
   re-release re-pushes from it. Confirm `TELEMETRY_API_KEY` is set for stage/prod
   (doctrine-injected secret; see
   [`config_and_secrets.md`](../doctrine/infrastructure/specifics/config_and_secrets.md)).

4. **Confirm the old compiled output and state are intact.** `infra/output/`
   should be committed and match what's deployed (the old `docex compile`
   output). For elastic, confirm you can reach the old state backend (the S3
   bucket the old `bootstrap` created). Do **not** recompile yet.

5. **Note your current pin.** `grep docex_version project.yml` — this is the
   version whose image (still in your local Docker store) drives Phase B.

---

## Phase B — Tear down old infra to bare metal

Run everything in this phase with the **old** version still pinned in
`project.yml`. Where the old version had a teardown command, use it; pre-1.0.0
elastic had none, so the elastic path is manual `tofu destroy` + an AWS sweep.

### B-fixed — Fixed-foundation teardown

For each production-side env (`stage`, then `prod`) on the host(s) that run them:

1. **Take the env stack down with volumes.** Against the old env compose file:
   ```bash
   docker compose -f infra/output/stage/docker-compose.yml down -v
   docker compose -f infra/output/prod/docker-compose.yml down -v
   ```
   `-v` removes named volumes (bare metal — this is where the DB data lived; you
   backed it up in Phase A). On a split-machine fixed project, run these on the
   remote prod host.

2. **Take dev/test down too** (they're moving to the new shape as well):
   ```bash
   docker compose -f infra/output/dev/docker-compose.yml down -v
   docker compose -f infra/output/test/docker-compose.yml down -v
   ```

3. **Remove the legacy machine-wide reverse proxy.** Pre-1.0.0 fixed used a
   single machine-wide `traefik` container on a single `web` Docker network
   (replaced in 1.0.0 by the per-project traefik + four `-web` networks behind
   HAProxy). Stop and remove it, its `web` network, and its ACME volume:
   ```bash
   docker rm -f traefik                 # or whatever the legacy container was named
   docker network rm web                # the legacy shared web network
   docker volume rm <legacy-acme-volume>
   ```
   This frees host :443/:80 for the new `web_demux` you install in Phase E.

4. **Verify nothing project-related remains:**
   ```bash
   docker ps -a    --filter "name=<project>" --format '{{.Names}}'
   docker network ls --filter "name=<project>" --format '{{.Name}}'
   docker volume ls  --filter "name=<project>" --format '{{.Name}}'
   ```
   All three should be empty. (Check both `<project>` and the hyphenated
   `<project-dns>` forms.) The external container registry is prerequisite infra
   — leave it; old image tags there are harmless.

### B-elastic — Elastic-foundation teardown

Pre-1.0.0 had no elastic teardown command, so destroy via OpenTofu against the
old output + state, then sweep AWS for anything tofu didn't track, then delete
the state backend itself.

1. **`tofu destroy` each env, newest dependency first.** The old per-env
   `main.tf` (per-project VPC, per-env ALB, ECS, RDS, etc.) is tracked under the
   per-env state key in the old S3 backend. From the old output:
   ```bash
   tofu -chdir=infra/output/prod  init
   tofu -chdir=infra/output/prod  destroy
   tofu -chdir=infra/output/stage init
   tofu -chdir=infra/output/stage destroy
   ```
   - **Disable RDS deletion protection first** if your old RDS carried it, or
     `destroy` will refuse: `aws rds modify-db-instance
     --db-instance-identifier <old-id> --no-deletion-protection --apply-immediately`,
     poll until it lands, then destroy. (The smoke `teardown.sh` automates this
     dance — see
     [`test_projects.md § Smoke-project safety overrides`](../docex/plans/core/test_projects.md).)
   - If the old project ever emitted a project-tier state
     (`project/terraform.tfstate`), destroy that last, after both envs.

2. **Sweep AWS for orphans by project name.** Some resources weren't
   tofu-tracked (ECR repos created ad-hoc by the old `containerize`; the state
   backend; possibly the Route53 zone). Check **both** the underscored
   (`<project>`) and hyphenated (`<project-dns>`) forms — `verify_clean.sh` in
   the smoke projects does exactly this and is the pattern to mirror. Delete any
   survivors:
   - ECS clusters/services, ALBs + target groups + listener rules, security
     groups, EFS filesystems
   - RDS instances (deletion-protection-disabled, `--skip-final-snapshot`)
   - Route53 **hosted zone** (old zone = the bare apex) + its records
   - ACM certs, ECR repositories, SSM parameters under `/<project>/...`,
     the IAM task-execution role, and the **per-project VPC** if the old version
     predated the master-VPC switchover (mod 041)

3. **Delete the state backend last.** Once every tofu-tracked resource is gone:
   ```bash
   aws s3 rb s3://<project-dns>-tofu-state --force      # versioned bucket
   aws dynamodb delete-table --table-name <project>_tofu_locks
   ```
   (Bucket name uses the `s3` policy — hyphen+lower; lock table uses `ddb` —
   underscore-preserving. See
   [`elastic_state_backend.md`](../doctrine/infrastructure/specifics/projinfra/elastic_state_backend.md).)

4. **Verify bare metal.** Re-run the name/tag sweep from step 2 for both name
   forms. Nothing project-related should remain in the account.

> **Leave the master VPC alone.** If your account already has the shared master
> VPC (`Name=docex-master-vpc`), it's prerequisite infra shared across projects —
> do not destroy it. If this is the account's first elastic project and there is
> no master VPC yet, you'll create it in Phase E.

---

## Phase C — Install docex 1.1.0

1. **Ensure the `docex:1.1.0` image exists in the local Docker store.**
   ```bash
   docker images docex:1.1.0
   ```
   If absent, build it from the docex tree (the image is built locally, not
   pulled — see [`masterplan.md § Distribution`](../docex/plans/core/masterplan.md)):
   ```bash
   docker build -t docex:1.1.0 ~/.claude/jean_baudrillard/docex
   ```

2. **Install into the project.** From the doctrine-side installer — it copies
   the (version-agnostic) shim to `bin/docex` and writes the shipped version
   into `project.yml`'s `docex_version` pin:
   ```bash
   bash ~/.claude/jean_baudrillard/docex_install.sh /path/to/project
   ```

3. **Verify:**
   ```bash
   cd /path/to/project && ./bin/docex --version    # expect 1.1.0
   grep docex_version project.yml                  # expect "1.1.0"
   ```

The shim itself never changes between versions; the pin is what selects the
image. See [`docex.md § Project Installation`](../doctrine/infrastructure/docex.md#project-installation).

---

## Phase D — Bring `infra.yml` up to the 1.1.0 CICL surface

The shape overhaul changed the CICL surface (mod 031). Edit `infra/infra.yml`:

1. **Rename `domain:` → `apex_domain:`, and narrow the value to the bare apex.**
   The value is now the bare apex domain only (e.g. `example.com` /
   `example.co.uk`), **not** the full project domain. The canonical service host
   is derived as `<service>.<env>.<project>.<apex_domain>`. Validation rule 13
   rejects an apex that carries subdomains.

2. **Add `reverse_proxy:` on elastic projects.** New elastic-only top-level
   field. Set it explicitly:
   - `alb` — the default-shaped variant (one project ALB + ACM certs).
   - `ec2_traefik_eip` / `ec2_traefik_pip` — the cheaper single-instance traefik
     variant (see
     [`ec2_traefik.md`](../doctrine/infrastructure/specifics/projinfra/ec2_traefik.md)).
   Validation rule 18 rejects `reverse_proxy` on a fixed project.

3. **Rename any blacklisted service.** Service names can no longer be `dev`,
   `test`, `stage`, `prod`, or `www` (validation rule 14). Rename in `infra.yml`,
   `core/<svc>/`, contracts, and any magic refs.

4. **Delete any `role: reverse_proxy` backing service.** The reverse proxy is
   project-tier infrastructure now, not a CICL service; declaring it fails
   validation.

5. **Confirm `observability_backend_url:` is set** (https-only). Required since
   0.11.0; if you're coming from before that, add it.

6. **Recompile and read the diff:**
   ```bash
   ./bin/docex compile
   ```
   New output now includes `infra/output/project/{development,production}/` in
   addition to the per-env directories (mod 035). Recompile also regenerates
   `infra/secrets/example.env`; reconcile your `<env>.env` files against it.

> This `infra.yml` edit + repin is itself a normal change — do it on a **feature
> branch** and bump `project.yml`'s `version` so the eventual `containerize`
> has a real version-tagged commit to ship (Phase F).

---

## Phase E — Stand up the new preinfra

1.0.0 introduced first-class preinfra tiers. The development-side machine needs
the new master network; elastic projects also need the production-side master
VPC. Preinfra is operator-managed and created via the **`docex-preinfra`
skill** — `docex` only *checks* it, never creates it.

### Development-side machine (both foundations)

The dev machine's master network is two pieces (see
[`fixed_master_network.md`](../doctrine/infrastructure/preinfra/fixed_master_network.md)):

1. **`docex-ingress` Docker bridge** — ties the per-project traefik containers to
   the demux. Idempotent create:
   ```bash
   docker network inspect docex-ingress >/dev/null 2>&1 \
     || docker network create docex-ingress
   ```

2. **HAProxy `web_demux`** — owns host :443/:80 and SNI/Host-routes by domain to
   each project's `${project}-traefik`. Lives at
   `/opt/docex-preinfra/web_demux/`. The full compose + `haproxy.cfg` +
   `project_resolver.lua` are in
   [`fixed_master_network.md § Setup Instructions`](../doctrine/infrastructure/preinfra/fixed_master_network.md#setup-instructions).
   If a legacy machine-wide traefik still owned :443/:80, you removed it in
   Phase B-fixed — that port is now free for `web_demux`.

3. **Verify:**
   ```bash
   ./bin/docex preinfra development     # must pass before projinfra up development
   ```
   This probes the `docex-ingress` bridge (it does not probe HAProxy directly).

### Production-side machine (elastic)

Elastic production needs the shared **master VPC** (master VPC + IGW + NAT +
public/private subnets, tagged `Name=docex-master-vpc`,
`managed_by=docex-preinfra`). If the account already hosts another elastic
project, it exists — leave it. If not, create it via the `docex-preinfra` skill
(see
[`elastic_master_network.md`](../doctrine/infrastructure/preinfra/elastic_master_network.md)).
Then:
```bash
./bin/docex preinfra production      # must pass before projinfra up production
```
For **fixed** production (remote prod host), `preinfra production` also verifies
the prod host's `docex-ingress` + HAProxy and the registry credential in
`~/.docker/config.json` (Gap G); set those up on the prod host the same way as
the dev machine.

> Whenever `docex preinfra <side>` reports a gap, load the **`docex-preinfra`
> skill** and create/fix the named resource. `projinfra up <side>` and
> `envinfra up <env>` now *refuse* to run while preinfra is failing.

---

## Phase F — Rebuild and re-release

With bare-metal teardown done, 1.1.0 installed, `infra.yml` recompiled, and
preinfra in place, rebuild the project's infra and ship it through the standard
pipeline. The command surface is new (mod 034): `bootstrap`/`up`/`down` are gone,
replaced by `preinfra` / `projinfra` / `envinfra`.

### 1. Bring up project-tier infrastructure

```bash
./bin/docex projinfra up development     # 4 -web networks + ${project}-traefik (local docker)
./bin/docex projinfra up production
```

- **Fixed `up production`:** per-project traefik + `-web` networks on the prod
  host (local docker if single-machine; Ansible if remote).
- **Elastic `up production` is two-phase** (NS delegation pause — see
  [`projinfra/projinfra.md § Two-Phase Production-Side Apply`](../doctrine/infrastructure/specifics/projinfra/projinfra.md#two-phase-production-side-apply-elastic)):
  1. First invocation creates the state backend, then applies **only** the
     Route53 zone (`<project>.<apex_domain>`), prints its NS records, and exits.
  2. **Re-delegate at the parent registrar** to those new NS records (the zone
     name changed from the old bare-apex zone, so this is a fresh delegation).
  3. Re-run `./bin/docex projinfra up production` — the untargeted apply now
     validates the ACM certs against the delegated zone and brings up the ALB
     (or EC2-traefik), ECR repos, and the task-execution IAM role.

### 2. Smoke the dev environment

Confirm the new shape actually runs locally before the production pipeline:
```bash
./bin/docex envinfra up dev      # builds images, brings up the stack, runs migrations
# ... exercise it ...
./bin/docex envinfra down dev
```

### 3. Run the CI/CD pipeline to release

From a feature branch with the version bumped in `project.yml` (Phase D) and a
clean tree:
```bash
./bin/docex check            # gate checks on the merged worktree
./bin/docex merge            # rebase onto main, tag v<version>, push
./bin/docex containerize     # build + push prod images (elastic: to the fresh project ECR)
./bin/docex release stage    # pushes secrets from stage.env, migrates, applies
./bin/docex stagetest
./bin/docex release prod
```
`release` re-pushes secrets from `infra/secrets/<env>.env` (SSM on elastic, host
`.env` on fixed) and runs migrations as part of the deploy — so the *schema* is
recreated automatically.

### 4. Restore data

Migrations recreate the **schema**, not the **data**. Restore the dumps you took
in Phase A into the new `stage`/`prod` databases and object stores. Do this after
the env is live and migrated; verify the application reads the restored data
before considering the upgrade complete.

---

## Quick checklist

- [ ] **A** — DB/object-store/EFS backups taken; NS + secrets recorded; old `infra/output` + state intact
- [ ] **B** — old stage/prod (and dev/test) infra destroyed to bare metal; verified by name/tag sweep (both `_` and `-` forms); state backend + ECR + zone gone (elastic); legacy machine-wide traefik removed (fixed)
- [ ] **C** — `docex:1.1.0` image present; `docex_install.sh` run; `./bin/docex --version` → 1.1.0
- [ ] **D** — `infra.yml` updated (`apex_domain`, `reverse_proxy`, no blacklisted names, no `reverse_proxy` role, `observability_backend_url`); `docex compile` clean; `<env>.env` reconciled against new `example.env`; version bumped on a feature branch
- [ ] **E** — `docex-ingress` + `web_demux` up on dev machine; master VPC present (elastic); `docex preinfra development` and `preinfra production` pass
- [ ] **F** — `projinfra up development` + `production` (NS re-delegation done on elastic); `envinfra up dev` smoke clean; pipeline `check → merge → containerize → release stage → stagetest → release prod` green; data restored

---

## Appendix A — Shortcut for projects already on 1.0.x

A project already on 1.0.0–1.0.3 has the new shape; the 1.1.0 jump (mods 049–053)
is polish, not a reshape. No teardown needed:

1. `bash ~/.claude/jean_baudrillard/docex_install.sh /path/to/project` (repins to 1.1.0).
2. `./bin/docex compile` and review the diff. Expect mostly:
   - **ECS task definitions** now carry `awslogs` `logConfiguration` on every
     container (app, OTel sidecar, `_migrate`) → a per-(env,service) CloudWatch
     log group (Gap E, mod 052). The next `release` rolls task defs to pick this up.
   - **Compose project identity** is now explicit and project-scoped
     (`<dns_label>-<env>`, project-tier `<dns_label>-projinfra-<side>`) and the
     ACME volume gets an explicit `name:` (mod 053). If your dev-side projinfra
     stack came up under the old generic `infra` project name, take it down with
     the **old** pin first (`projinfra down development`), then repin and
     `projinfra up development` so the four `-web` networks are recreated under
     the correct project-scoped name.
   - **Fixed traefik** switched DNS-01 → **HTTP-01** for Let's Encrypt (Gap A,
     mod 051); drop any `TRAEFIK_DNS_PROVIDER` you were setting (`TRAEFIK_ACME_EMAIL`
     stays, now optional).
3. Re-release through the normal pipeline (`check → merge → containerize →
   release stage → stagetest → release prod`). No infra teardown, no NS
   re-delegation, no data migration beyond what the release's own migrate step does.

See the [1.1.0 CHANGELOG entry](../CHANGELOG.md) for the full Gap A–K list.
