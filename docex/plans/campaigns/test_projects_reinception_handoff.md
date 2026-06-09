# Test-Projects Re-Inception — Fresh-Context Handoff Prompt

Paste the block below into a fresh agent context to drive the test-project re-inception that follows the docex 1.0.0 cut.

---

## Prompt

You are picking up a doctrine-faithful re-inception of two bundled test projects after docex 1.0.0 was just cut. Your predecessor (whose context is now gone) ran the 16-mod shape-and-tier campaign that produced 1.0.0. The test projects at `~/.claude/jean_baudrillard/docex/test_projects/{fixed,elastic}/` are now substantially out of sync with the doctrine — the operator and the prior agent agreed to defer test-project work to a full re-inception at the major-cut boundary, which is now.

Per [`docex/plans/core/docex_process.md § Lifecycle`](~/.claude/jean_baudrillard/docex/plans/core/docex_process.md), a major cut requires "a full re-inception (a successor agent re-walks PARTs I–IV from scratch against the current doctrine, replacing this seed)". That successor agent is you.

### Read first, in this order

1. **The CHANGELOG entry for 1.0.0** at `~/.claude/jean_baudrillard/docex/CHANGELOG.md` (the most recent `[1.0.0]` block). This is the most efficient summary of what changed in the campaign and what the new test projects must conform to. Every entry carries a `(mod NNN)` attribution if you need to dig deeper.

2. **The campaign mod list** at `~/.claude/jean_baudrillard/docex/plans/campaigns/shape_overhaul_mod_list.md`. Each mod folder under `plans/modifications/` has an `overview.md` and `implementation.md` with deeper context per topic. Skim these on-demand.

3. **The doctrine** at `~/.claude/jean_baudrillard/doctrine/`. Especially:
   - `practices/inception.md` — the canonical inception flow (PARTs I–V).
   - `infrastructure/cicl.md` — the new `infra.yml` surface (`apex_domain`, `reverse_proxy`, validation rules).
   - `infrastructure/shape2.md` — the doctrine's runtime shape per foundation.
   - `infrastructure/specifics/projinfra/` — the per-resource project-tier specs you'll be exercising.

4. **The existing test-project state** at `~/.claude/jean_baudrillard/docex/test_projects/{fixed,elastic}/`. These are the "seed" projects to replace. Read their `infra.yml`, `project.yml`, `plans/core/masterplan.md`, and `core/*` shapes to understand what existed pre-1.0.0. You're replacing them, not iterating on them — but their high-level design (web + worker + postgres `pings` table) is fine to preserve.

5. **Test-project test process** at `~/.claude/jean_baudrillard/docex/plans/core/test_projects.md` and `~/.claude/jean_baudrillard/docex/test_projects/PRE_CUT_CHECKLIST.md`. Explains the inception-flow carve-outs, git structure (inner repos nested in the outer jean_baudrillard repo), commit cadence, and the smoke-walk procedure you'll execute at the end.

### Your job, in three phases

**Phase A — Re-inception of both test projects.** Per the inception flow (PARTs I–IV, with the carve-outs from `test_projects.md`):

- Re-write both `test_projects/fixed/` and `test_projects/elastic/` from scratch against the 1.0.0 doctrine. Same architectural intent (two cores `web` + `worker`, one postgres backing service `appdb`, a shared `pings` table demonstrating `schema_owned_by` + migrations), but the file surface needs to match the new doctrine — apex_domain, reverse_proxy field, new canonical host form, new project structure, etc.
- The two projects should share identical `core/` code so the "code identity between fixed and elastic" property documented in `test_projects.md` is preserved.
- Each test project is its own git repo nested inside the outer `jean_baudrillard` repo. Initialize each with `git init -b main`. The outer repo also tracks the same files as a directory snapshot. Per `test_projects.md`, inner-first commit cadence.
- Bump each inner-repo `project.yml` version (e.g. `0.0.1` for the fresh start since the project itself is new) and tag the HEAD `v0.0.1`.
- Install docex into each project via `bash ~/.claude/jean_baudrillard/docex_install.sh test_projects/<foundation>`. Verify with `./bin/docex --version` (should print `1.0.0`).

**Phase B — Pre-walk infrastructure setup.**

- **Master VPC preinfra (elastic only).** Per mod 041, the elastic project consumes a shared master VPC via tag discovery. The VPC must exist before `docex projinfra up production` will succeed. Tags:
  - VPC: `Name = "docex-master-vpc"`, `managed_by = "docex-preinfra"`.
  - Subnets: `tier = "public"` or `tier = "private"`. Primary-AZ subnet discovered via `availability-zone = "us-east-1a"` filter (no tag required for AZ).
  - Doctrine spec: 4 subnets total (public + private pair in us-east-1a, redundant public + private pair in a secondary AZ for two-AZ AWS requirements).
  - The `docex-preinfra` skill at `~/.claude/skills/docex-preinfra/SKILL.md` likely needs updating to document this scheme — that's separate but worth doing as you go.
- **HAProxy web demux + `docex-ingress` docker bridge** (both foundations, development side). The dev machine must have these for `docex projinfra up development` to work. The bridge: `docker network create docex-ingress` if missing.
- **AWS account** at the operator's standard account (operator memory should have an `aws_account` entry).
- **HyperDX observability backend URL** — per mod 042 it's not auto-probed by preinfra but is in `infra.yml` as `observability_backend_url`. Operator's memory should have a HyperDX URL.

**Phase C — Smoke walk per `PRE_CUT_CHECKLIST.md`.**

- For each project (fixed first, then elastic), run the full release pipeline against real infrastructure: `check → merge → containerize → release stage → stagetest → release prod → teardown`.
- The elastic walk will produce real AWS resources; ensure cleanup via `test_projects/elastic/teardown.sh`.
- Capture observations in the project's `CHANGELOG.md`. Report any docex bugs you uncover back to the operator for follow-up patch mods.

### Key gotchas worth knowing up-front

- **Hyphen vs underscore.** Mods 030 + 040 mean every Docker network, ECS resource, SG name uses hyphens. IAM/SSM/DDB use underscores. The project segment of host strings is DNS-labeled (`docex_smoke_elastic` → `docex-smoke-elastic`). Don't write infra.yml expecting underscored container names — the compiler will hyphenate.
- **`apex_domain` must be bare.** `example.com` or `example.co.uk` only. `myproject.example.com` will fail validation (mod 031's rule 13 with the SLD allowlist). The project subdomain (`<project>.<apex>`) is derived automatically.
- **`reverse_proxy: alb` is the default on elastic.** If you want EC2-traefik, add `reverse_proxy: ec2_traefik_eip` or `ec2_traefik_pip` to `infra.yml`. Fixed projects must not declare this field.
- **EC2-traefik LE issuance is operator-side.** Per mod 044, the user_data references `${TRAEFIK_ACME_EMAIL}` and `${TRAEFIK_DNS_PROVIDER}` env vars. If you smoke-test EC2-traefik, set these in the operator env or accept that LE issuance won't happen (traefik comes up and routes, but cert provisioning fails until configured).
- **Mod 044's SSM rerender is a known v1 gap.** Operators using EC2-traefik manage routing-rule YAML manually via `aws ssm put-parameter --name /<project>/ec2_traefik/config.yml --value @config.yml --overwrite`. The instance polls every 30s. For the elastic smoke project, **the operator decision was `reverse_proxy: alb` is the default and that's what the smoke project should use** — skip EC2-traefik unless you specifically want to exercise that path.
- **Service-name blacklist.** Service names cannot be `dev`, `test`, `stage`, `prod`, `www` (mod 031's rule 14). `web` and `worker` are fine.
- **Single-AZ ECS placement on elastic.** Per mod 041, ECS services pin to `[primary_private_subnet_id]`. RDS subnet groups and EFS mount targets stay multi-AZ per AWS requirements. This means your prod project tolerates `us-east-1a` outages but not multi-AZ outages — accepted tradeoff for v1.
- **`projinfra up production` on elastic has a two-phase NS delegation pause.** Mod 037: first invocation creates the Route53 zone via targeted apply and prints NS records + delegation instructions. You then NS-delegate `<project>.<apex>` from the parent registrar (e.g. NameSilo at the apex). Second invocation does the untargeted apply. Plan extra time for DNS propagation between phases (typically 1–5 minutes).
- **Don't expect `bootstrap` / `up` / `down` commands.** They're gone (mod 034). Use `projinfra up production`, `envinfra up dev`, `envinfra down dev`.
- **No `domain:` field.** It's `apex_domain:` (mod 031).
- **Migrate scripts must use the `sslmode` provided part.** Per the doctrine, `migrate.sh` composes its DB connection string from parts including `${DATABASE_SSLMODE}` — RDS rejects non-SSL connections so this is load-bearing on elastic.
- **Test projects' compiled output is git-tracked.** Inner-repo state includes `infra/output/` (for traceability). The outer `jean_baudrillard` repo also tracks the same snapshot — both must be kept in sync (inner-first commit cadence per `test_projects.md`).

### What "done" looks like

- Both `test_projects/{fixed,elastic}/` are fresh, doctrine-faithful, install docex 1.0.0, and their `./bin/docex compile` produces clean output with no validation errors.
- Both have completed a full smoke walk per `PRE_CUT_CHECKLIST.md` against real infrastructure. Teardown completed cleanly (verified with `verify_clean.sh` for elastic).
- Outer + inner repos are committed and in sync per `test_projects.md`'s cadence.
- Any docex bugs surfaced during the walk are either fixed (small patch mod, version bump to 1.0.1) or reported to the operator with a clear repro path.
- A new git tag exists for each cleanly-walked release (`v0.0.1` initially per inception; subsequent fix-walks bump per usual SemVer).

### Final notes

- This is potentially many hours of work. The smoke walk against real AWS for the elastic project alone is typically 1–2 hours of clock time including DNS propagation waits and convergence.
- Stop and ask the operator when uncertain about doctrine-vs-implementation drift. The campaign's 16 mods all introduced breaking changes — pre-1.0.0 conventions you've seen elsewhere likely don't apply.
- If the smoke walk uncovers regressions in docex itself, surface them — don't hack the test project to work around them. The whole point of the smoke walk is to validate the cut.

Good luck.
