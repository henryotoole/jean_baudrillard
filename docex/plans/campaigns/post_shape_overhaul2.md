# Post-Shape-Overhaul — Smoke-Test Handoff (Mods 049–052)

**Audience:** the fresh-context LLM that will run the pre-cut **expensive tests** (e2e integration + the two test-project smoke walks per [`PRE_CUT_CHECKLIST.md`](../../test_projects/PRE_CUT_CHECKLIST.md)) before the single `1.1.0` cut.

**Purpose:** tell you *what changed* across mods 049–052 and *what to verify / watch for* in the walks. The authoritative per-mod detail lives in `plans/modifications/049_*` … `052_*` (each has `overview.md` + `implementation.md`); the gap roadmap with per-gap rationale is [`post_shape_overhaul.md`](./post_shape_overhaul.md). This file is the orientation layer over those.

## State you're inheriting

- All four mods are **implemented, reviewed, and committed on `main`**. Unit suite green (**537 passed**).
- **No cut has been taken.** Version is still `1.0.3`; `CHANGELOG.md`'s `[Unreleased]` holds every 049–052 entry and flips to `[1.1.0]` *at the cut, after* your walks pass.
- Working tree clean except pre-existing `engineer/tmp/*` deletions (not ours — leave them).
- **Prerequisite for the walks:** the test projects run the docex *image*, not the source. These changes are committed but uncut, so build a candidate image from current `main` and (re)pin the test projects to it before walking — confirm the exact mechanism in `PRE_CUT_CHECKLIST.md` (this is a minor cut, so both walks are required).

## What changed, by where it bites

### Fixed walk (`docex_smoke_fixed`)

- **Gap A — HTTP-01 certs (big behavior change).** The per-project traefik now issues Let's Encrypt certs via the **HTTP-01** challenge, **per-host**, with **no DNS-provider credentials** (was DNS-01 + wildcards, which never had creds wired). **Verify:** the project traefik issues a *real* cert and stage tests reach it over HTTPS **without `httpx.Client(verify=False)`**. The old `verify=False` workaround (`docex_smoke_fixed v0.0.3`) should now be **removed** — if it's still there, drop it and confirm real-cert verification passes. No wildcards on fixed anymore; each web service gets its own cert on first request.
- **Gap B — project-scoped traefik.** The traefik's docker provider is constrained to `Label(docex.project, <project>)`, and every emitted container carries a `docex.project` label. **Verify:** traefik logs are free of cross-project ACME/router noise (it ignores other projects' containers on `docex-ingress`).
- **Gap I — curl gate in `docex check`.** `check` now builds each `health_check_path`-declaring web image and fails if it lacks `curl`. **Verify:** `docex check` passes (the smoke Dockerfile installs curl since `v0.0.2`). Optional: temporarily remove curl to confirm the gate fails descriptively.
- **Gap C — `docex merge` works with no remote.** The test projects have no `origin`; `merge` now detects that, skips fetch/push, rebases onto local `main`, and tags. **Use `docex merge` directly** — the manual `git checkout main && merge --ff-only && tag` workaround (old `PRE_CUT_CHECKLIST` C.6.1 / D.8) is **obsolete**.
- **Gap G — registry-cred preflight.** `docex preinfra production` (fixed) now SSH-probes the target host for `/home/deploy/.docker/config.json` **and** `/root/.docker/config.json`. **Watch:** if those creds aren't present, preinfra now *fails descriptively* (instead of a later `401` at `docker compose pull`). Ensure both are in place (still a manual `docker login` as `deploy` and `root` — see `PRE_CUT_CHECKLIST A.7`); preinfra is now the early gate that catches a miss.
- **Gaps K / D / J (minor):** `envinfra up dev` prints a per-service diagnostic on a partial bring-up; `docex build` distinguishes a `Restarting` container from an absent one; `docex bootstrap`/projinfra display strings now print the hyphenated DNS name (no behavior change, just no confusing `under_score` vs `hyphen` mismatch in output).

### Elastic walk (`docex_smoke_elastic`)

- **Gap E — container logs → CloudWatch (new; verify in the walk).** Every ECS container (app, OTel sidecar, **`_migrate`**) now emits an `awslogs` `logConfiguration` to a per-(env, service) CloudWatch log group **`/<project>/<env>/<service>`** (30-day retention, `managed_by=doctrine`), tofu-created. **Verify after release:** the log groups exist and actually receive stdout — check an app stream, the `otelcol` stream, and especially a `migrate` stream (a failing `migrate.sh` used to be invisible; that was the headline motivation). This is *Class-2 diagnostic* stdout; structured app telemetry still flows via the OTel sidecar to HyperDX as before.
- **Gap F — automated, safe teardown (new flow; replaces manual `teardown.sh`).** Teardown is now docex-driven and **layered**:
  1. `docex envinfra down prod` → 2. `docex envinfra down stage` → 3. `docex projinfra down production`.
  - **Expected gotcha — the deletion-protection gate WILL refuse, and that's correct.** The smoke RDS has `deletion_protection=true` (prod-safe default). `docex envinfra down <env>` runs a **pre-flight scan and refuses-and-reports before destroying anything** if it finds a protected RDS — *docex never disables protection itself*. So the smoke teardown must **deliberately disable `deletion_protection`** (this is exactly what the smoke `teardown.sh` wrapper does) and then re-run `envinfra down`. Treat a refusal as the gate working, not a bug.
  - `projinfra down production` **refuses if any env-tier resources still exist** (probe per env) and **refuses on a non-empty ECR repo** — both refuse-and-report before destroying. Tear envs down first; empty ECR if it complains. Then it tofu-destroys the project tier and cleans up SSM params + the state backend (S3 bucket + DynamoDB table) last.
  - `teardown.sh` now stays a **thin smoke-only wrapper** (disable protection + call the docex commands). Its aggressive `deletion_protection`-disable / `skip_final_snapshot` overrides are **smoke-specific** and were deliberately *not* promoted into docex (production safety).
- **Gap J (minor):** `docex bootstrap` now prints the hyphenated Route53 zone name matching what's actually created.

### Both walks
- `docex check`'s curl gate (Gap I) runs regardless of foundation for any `health_check_path` web service.

## Quick "is it working?" checklist

- [ ] Fixed stage tests pass over **real HTTPS** (no `verify=False`).
- [ ] Traefik logs: no foreign-project router/ACME noise.
- [ ] `docex check` green (curl present); `docex merge` works with no remote.
- [ ] `docex preinfra production` (fixed) flags missing target-host docker creds, or passes when present.
- [ ] Elastic: CloudWatch log groups `/<project>/<env>/<service>` exist and receive app/otelcol/migrate streams.
- [ ] Elastic teardown: `envinfra down` refuses on the protected RDS (✓ expected), proceeds after the wrapper disables protection; `projinfra down production` refuses-if-envs-up / non-empty-ECR, then cleanly removes project tier + state backend.
- [ ] `verify_clean.sh` reports no lingering AWS resources after teardown.

## After the walks pass

Hand back for the **`1.1.0` cut** (`docex_process.md § Cutting a version`): `[Unreleased]` → `[1.1.0]` dated, bump `pyproject.toml` + `src/docex/__init__.py`, commit, tag `docex-v1.1.0`, `docker build -t docex:1.1.0`, reinstall into consumers. A campaign closeout on [`post_shape_overhaul.md`](./post_shape_overhaul.md) (mark all gaps implemented) is a nice final tidy.
