---
version: "1.2.0"
severity: minor
kind: incremental
scope: [project]
---

# Upgrading a project to docex 1.2.0

The release that **formalizes elastic resource tagging** (mod 060) and adds the
`scheduler` role (mod 055), the `preinfra development` dev-DNS gate (mod 054),
and a few `check`/preinfra fixes. The full per-mod narrative is in the
[1.2.0 CHANGELOG entry](../CHANGELOG.md).

> **Predates the unified version.** Like [`upgrade_1.1.0.md`](./upgrade_1.1.0.md),
> this guide ships retroactively on the [upgrades tape](./README.md). `1.2.0`
> was a `docex`-only version (the doctrine-wide scheme starts at `1.3.0`), so it
> speaks in terms of a project's `docex` pin — which, retroactively, is the
> doctrine version that project sits on.

> **MINOR by version, breaking by tag-contract.** The bump from `1.1.x` was a
> MINOR — no `docex` CLI surface changed and the upgrade is a repin + recompile +
> **in-place** re-apply, not a rebuild. But mod 060 moved the master-VPC lookup
> onto new semantic tags, so an **elastic** project's already-deployed master
> network **must be re-tagged** or `docex` will report it missing. That re-tag
> (below) is the one load-bearing step; everything else is a normal recompile.
> Pure **fixed** projects have no elastic tags and skip the heavy section
> entirely — for them the only action is the optional `web_demux` PSL update
> (Step 5), needed only on multi-label TLDs.

## Summary

Mod 060 made the three elastic tag blocks (preinfra / projinfra / envinfra) a
single-source standard — see
[`cicl.md § Naming and Tagging`](../doctrine/infrastructure/cicl.md#naming-and-tagging).
Every elastic resource `docex` emits now carries `managed_by`, `infra_tier`,
`shape_name`, `descriptor`, a console-only `Name`, plus `project`/`env`/
`service`/`role` where the tier defines them. The breaking part: the master-VPC
data-source and precondition lookups moved **off** `Name=docex-master-vpc` +
`managed_by=docex-preinfra` **onto** the semantic identity tags
`managed_by=doctrine-operator` + `infra_tier=prerequisite` +
`shape_name=master_network`. The tags are the contract — no command takes an
override.

## Machine sync

`git pull` in `~/.claude/jean_baudrillard` and ensure the `docex:1.2.0` image
exists locally — it is built, not pulled:

```bash
docker images docex:1.2.0 || docker build -t docex:1.2.0 ~/.claude/jean_baudrillard/docex
```

(On a post-1.3.0 machine `doctrine-update` and `setup.sh` handle the pull; this
guide is retroactive, so the manual build line is the version-agnostic form.)

## Project upgrade

The single ordering rule, and the reason for it: **re-tag the master VPC before
you repin.** Once `project.yml` points at `1.2.0`, every elastic command that
touches the master network — `preinfra production`, `projinfra up production`,
`release <env>`, the migrate RunTask — filters it by the new semantic tags. If
the VPC still carries only the old tags, those commands report it missing and
refuse. So re-tag first (Step 1), then repin and recompile (Steps 2–3), then
redeploy (Step 4).

### 1. Re-tag the master network (elastic only; shared, once per AWS account)

The master VPC is shared preinfra — re-tagging it is a **once-per-account**
action, not once-per-project, even if `project-upgrade` walks you here for
several projects. Follow
[`elastic_master_network.md § Migration from earlier docex`](../doctrine/infrastructure/preinfra/elastic_master_network.md#migration-from-earlier-docex).
For the VPC:

```bash
aws ec2 create-tags --region us-east-1 --resources "$VPC_ID" \
    --tags Key=managed_by,Value=doctrine-operator \
           Key=infra_tier,Value=prerequisite \
           Key=shape_name,Value=master_network \
           Key=descriptor,Value=VPC \
           Key=Name,Value=master_network_VPC
```

Apply the analogous re-tag to the IGW, both route tables, the NAT EIP/gateway
(`shape_name=nat_gateway`), and the four subnets (keeping each subnet's
load-bearing `tier=public|private`).

> **Coexistence: add the new tags, don't delete the old ones yet.** `create-tags`
> only *adds* the semantic tags — it leaves the legacy `managed_by=docex-preinfra`
> / `Name=docex-master-*` tags in place. Leave them until **every** elastic
> project in the account is on `≥1.2.0`. A project still pinned to `1.1.x` looks
> the VPC up by the *old* tags; deleting them early breaks that project's deploys.
> Once all account projects are on `≥1.2.0`, remove the stale tags with
> `aws ec2 delete-tags`.

`docex preinfra production` does not probe IGW/NAT/route tables, but re-tag them
anyway for console consistency — the routing path is exercised by every env-tier
`tofu apply`.

### 2. Install docex 1.2.0 into the project

```bash
bash ~/.claude/jean_baudrillard/docex_install.sh /path/to/project
cd /path/to/project && ./bin/docex --version    # expect 1.2.0
grep docex_version project.yml                  # expect "1.2.0"
```

Do this on a **feature branch** and bump `project.yml`'s `version`, so the
eventual `containerize` ships a real version-tagged commit (Step 4).

### 3. Recompile and read the diff

```bash
./bin/docex compile
```

What to expect in the diff:

- **Elastic:** every emitted resource — env-tier (ECS, RDS, SGs, the Service
  Connect namespace) and project-tier (ALB/EC2-traefik, ECR, IAM role, Route53
  zone) — now carries the standard tag block. The state-backend S3 bucket +
  DynamoDB lock table also pick up tags (applied via boto3 on the next
  `projinfra`/`release`, not by tofu). These are **tag-only** changes: tofu
  updates them in place; no resource is replaced.
- **`test` env (both foundations):** `web`-network services drop their traefik
  discovery labels (no router/`tls`/`certresolver`) — `test` is no longer
  traefik-routed (mod 054). They keep the `docex.project` label and stay on the
  `-web` network. No action; just diff noise.

Recompile also regenerates `infra/secrets/example.env`; reconcile your
`<env>.env` files against it.

### 4. Redeploy through the normal pipeline

From the feature branch with a clean tree:

```bash
./bin/docex check
./bin/docex merge
./bin/docex containerize
./bin/docex release stage
./bin/docex stagetest
./bin/docex release prod
```

The `release` `tofu apply` reconciles the tag-only changes in place. No data
migration beyond the release's own migrate step.

### 5. Update the fixed `web_demux` — only on multi-label TLDs (fixed preinfra)

Mod 058 made the fixed-foundation HAProxy demux Public-Suffix-List-aware so it
parses projects on `.co.uk` / `.com.au`-style apexes. If your project's
`apex_domain` is a **single-label** TLD (`.com`, `.tech`, …), skip this. If it is
multi-label, update the operator-managed demux per
[`fixed_master_network.md § The web_demux Resource`](../doctrine/infrastructure/preinfra/fixed_master_network.md#the-web_demux-resource):
fetch `public_suffix_list.dat`, mount it into the container, and install the
PSL-aware `project_resolver.lua`. This is shared preinfra, not the project repo.

## Doctrine / behavior notes

Rule and gating changes to know even where nothing mechanical breaks:

- **`preinfra development` now gates on dev DNS (mod 054).** Every `dev`
  `web`-service hostname must resolve in **public** DNS, or the check fails
  before `envinfra up dev`. Bringing `dev` up fires Let's Encrypt HTTP-01
  challenges; unresolved hostnames fail every challenge and trip LE's
  failed-authorization rate limit. Route your `dev` hostnames before bringing
  `dev` up — see [`docex.md`](../doctrine/infrastructure/docex.md) (the
  `development`-side check). Resolution queries real nameservers (`dnspython`),
  not `/etc/hosts`, so it sees what LE sees.
- **`check`'s curl gate widened (mod 059).** It now covers **every** core service
  that declares `health_check_path`, not only those on the `web` network. A
  `role: web` service on a non-`web` network (e.g. `[internal]`) that omits
  `curl` from its image will now fail `check` — add `curl` to its Dockerfile.
  See [`cicd.md § Check Step`](../doctrine/infrastructure/cicd.md#check-step).
- **New `scheduler` role available (mod 055).** A core service that runs your
  image + `command` on a 5-field cron `schedule`, then exits — ofelia on fixed,
  EventBridge Scheduler → ECS `RunTask` on elastic. Purely additive and opt-in;
  no action unless you want it.

## Verification

```bash
cd /path/to/project
./bin/docex --version                 # → 1.2.0
./bin/docex preinfra production        # elastic: passes only after the master-VPC re-tag
```

Elastic: confirm the deployed resources carry the new tags, e.g. the master VPC
is found by the semantic filter —

```bash
aws ec2 describe-vpcs --region us-east-1 \
  --filters Name=tag:managed_by,Values=doctrine-operator \
            Name=tag:infra_tier,Values=prerequisite \
            Name=tag:shape_name,Values=master_network \
  --query 'Vpcs[].VpcId' --output text   # → your master VPC id
```

A green `release stage` → `stagetest` → `release prod` confirms the in-place
re-tag applied cleanly.

## Quick checklist

- [ ] **Machine** — `git pull`; `docex:1.2.0` image present
- [ ] **1 (elastic)** — master network re-tagged with semantic tags (VPC + IGW + RTs + NAT EIP/gw + 4 subnets); legacy tags **left in place** until all account projects ≥1.2.0
- [ ] **2** — `docex_install.sh` run on a feature branch; `--version` → 1.2.0; `version` bumped
- [ ] **3** — `compile` clean; tag-only diff reviewed; `test`-env traefik labels gone; `<env>.env` reconciled
- [ ] **4** — pipeline `check → merge → containerize → release stage → stagetest → release prod` green
- [ ] **5 (fixed, multi-label TLD only)** — `web_demux` updated to the PSL-aware resolver
- [ ] **Notes** — dev hostnames resolve publicly; non-`web` `health_check_path` services carry `curl`
