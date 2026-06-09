# Implementation — Mod 045 — Campaign Closeout

## Context

You are executing mod 045 — the final closeout mod of the doctrine-shape-and-tier campaign. Read [`overview.md`](./overview.md) first.

This mod is executed inline by the design-context agent (not a fresh subagent) because the CHANGELOG restructure benefits from campaign-level memory of what each mod actually did.

## Operator decisions binding

- Version: `1.0.0`.
- CHANGELOG restructured into doctrine-shaped sections.

## Step-by-step plan

### Step 1 — Bump version in `pyproject.toml`

`docex/pyproject.toml:7` — `version = "0.12.1"` → `version = "1.0.0"`.

### Step 2 — Bump version in `src/docex/__init__.py`

`docex/src/docex/__init__.py:3` — `__version__ = "0.12.1"` → `__version__ = "1.0.0"`.

### Step 3 — Restructure CHANGELOG

Replace the existing `[Unreleased]` block (which holds 13+ flat entries in reverse-chronological mod order) with a `[1.0.0] - <date>` block organized into:

- **`### Added`** — entirely new capabilities, not existed before:
  - EC2-traefik reverse-proxy variant (eip + pip) per mod 044.
  - New commands `preinfra`, `projinfra`, `envinfra` per mod 034.
  - Real `preinfra` per-foundation checks per mod 042.
  - Per-project traefik + four `-web` networks per mod 036.
  - Fargate tier rounding now surfaces every rounding cause per mod 033.
  - Polymorphic `reverse_proxy_security_group_id` project-tier output per mod 044.

- **`### Changed`** — pre-existing behavior reshaped (breaking):
  - Naming policy unification (mod 030).
  - CICL surface refresh (mod 031).
  - Telemetry sidecar suffix (mod 032).
  - Command surface refresh (mod 034).
  - Compiler output split by side (mod 035).
  - Route53 zone + ACM cert split (mod 037).
  - ALB moved to project-tier with SNI (mod 038).
  - Task-execution IAM policy tightened (mod 039).
  - Env-tier SG names hyphenated (mod 040).
  - Master VPC consumed as preinfra (mod 041).
  - Service Connect to private DNS namespace (mod 043).
  - Env-tier ALB references go through polymorphic remote-state output (mod 044).

- **`### Removed`** — eliminated entirely:
  - `bootstrap` command (replaced by `projinfra up production` on elastic).
  - `up`, `down` commands (collapsed into `envinfra <direction> <env>`).
  - `reverse_proxy` role / CICL backing-service marker (reverse proxy is project-tier infra now).
  - `domain:` top-level field (renamed `apex_domain:` with narrower semantics).
  - `ecr_repo` naming policy (ECR repo names emit structurally with `/` joiner).
  - Machine-wide-traefik model on fixed (replaced by per-project traefik behind HAProxy).
  - Per-project AWS VPC + IGW + NAT + subnets + route tables (master VPC is preinfra now).
  - `AmazonECSTaskExecutionRolePolicy` AWS-managed policy attachment.
  - Per-env ALB (one shared project-tier ALB serves stage and prod via SNI).
  - `*.dev`, `*.test`, `*.www` SANs from ACM certs.

- **`### Known v1 gaps`** — documented incompleteness in 1.0.0:
  - EC2-traefik release-flow SSM rerender not yet implemented; operators manage dynamic config manually via `aws ssm put-parameter` for v1 (mod 044).
  - Multi-machine fixed foundation deferred (single-machine only); ansible-at-project-tier emission not produced.

Each entry should keep a one-line `Mod NNN of the shape-and-tier campaign.` attribution so future contributors can `git log --grep "mod 0XX"` the commits.

Preserve the existing `[0.12.1]` and earlier sections below unchanged.

### Step 4 — Commit

Single commit per `docex_process.md` cut convention. Message: `Cut docex 1.0.0` (matches `1b69bdc Cut docex 0.12.1`, `cf85e8f Cut docex 0.12.0` style).

### Step 5 — Operator post-cut activities (out of mod 045)

Documented in `overview.md`. Operator runs:
1. `git tag docex-v1.0.0`
2. `docker build -t docex:1.0.0 .` from `docex/`
3. Re-incept test projects (separate workflow via the handoff prompt at the bottom of this mod).
4. Walk re-incepted projects per `PRE_CUT_CHECKLIST.md`.

## Done criteria

- [ ] `pyproject.toml` version = `1.0.0`.
- [ ] `src/docex/__init__.py` `__version__` = `1.0.0`.
- [ ] `CHANGELOG.md` `[Unreleased]` replaced with `[1.0.0] - <date>` block organized into Added / Changed / Removed / Known v1 gaps.
- [ ] Single `Cut docex 1.0.0` commit lands.
- [ ] Campaign tracker `shape_overhaul_mod_list.md` marks mod 045 done.
