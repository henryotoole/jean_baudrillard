# Post-Shape-Overhaul Open Gaps

The 1.0.0 shape-and-tier campaign + the subsequent post-1.0.0 test-project re-inception + two smoke walks (fixed → mod 047; elastic → mod 048) surfaced a set of gaps that mods 046–048 did not fix in-band. They land here as a campaign-shaped roadmap so a future operator (or agent) can pick them up in priority order without having to re-derive them from changelogs and walk transcripts.

Each gap entry follows the same shape: **Symptom → Root cause → Severity → Workaround → Fix shape**. The cut sequence the gaps belong to is open: a "post-shape-overhaul polish" campaign that retires them on whatever cadence the operator chooses.

---

## Gap A — Project traefik has no path for ACME-provider creds

### Symptom

Per-project traefik on `fixed`-foundation projects (and the dev side of `elastic`-foundation projects) can never issue a Let's Encrypt cert. Traefik logs show ACME failing with one of two errors depending on what's missing:

- `cannot get ACME client ACME challenge not specified, please select TLS or HTTP or DNS Challenge` — when `TRAEFIK_DNS_PROVIDER` is unset.
- `acme: error presenting token: route53: failed to determine hosted zone ID: ... no EC2 IMDS role found, no creds` — when the DNS provider is set but no AWS creds are reachable.

Routers fall back to traefik's self-signed default cert; downstream stage tests reject the cert with `httpx.ConnectError: [SSL: CERTIFICATE_VERIFY_FAILED]`.

### Root cause

`src/docex/emit/compose.py::emit_project_compose` emits the traefik service with `--certificatesresolvers.doctrine.acme.dnschallenge.provider=${TRAEFIK_DNS_PROVIDER:-}` on the command line — but no `environment:` block. AWS_* (or any DNS-provider's creds) set on the operator's shell never reach the traefik container. The docex shim doesn't propagate them either; the only path is for the operator to recreate the container by hand with `-e AWS_*`.

### Severity

**High** on `fixed`. Every fixed-foundation project's stage tests have to bypass cert verification (smoke project does this at `docex_smoke_fixed v0.0.3`). Telemetry exporters that talk HTTPS to operator-supplied backends suffer the same problem if those backends are behind real CAs.

**Medium** on elastic dev-side. Same gap (the dev-side traefik comes from the same emit), but elastic stage/prod use ALB + ACM which provides real certs — the gap doesn't reach the elastic walk's stagetest.

### Workaround

Test projects: `httpx.Client(verify=False)` in stage tests, with a comment pointing back here. Operator-side: recreate the project traefik by hand with `-e AWS_ACCESS_KEY_ID -e AWS_SECRET_ACCESS_KEY -e AWS_REGION` and a `--certificatesresolvers.doctrine.acme.dnschallenge.provider=route53` cmdline arg.

### Fix shape

`emit_project_compose` grows an `environment:` block on the traefik service that picks up provider-specific env vars via compose interpolation:

```yaml
environment:
  AWS_ACCESS_KEY_ID: ${AWS_ACCESS_KEY_ID:-}
  AWS_SECRET_ACCESS_KEY: ${AWS_SECRET_ACCESS_KEY:-}
  AWS_REGION: ${AWS_REGION:-us-east-1}
  CLOUDFLARE_DNS_API_TOKEN: ${CLOUDFLARE_DNS_API_TOKEN:-}
  # … etc per-provider
```

The doctrine should pick a defaulted set of providers (route53, cloudflare, plus a few of the most common) and emit the matching env vars. The provider name is already in `TRAEFIK_DNS_PROVIDER`; the operator sets exactly the creds for the provider they picked.

A cleaner alternative: bind-mount `~/.aws` into the traefik container read-only when `TRAEFIK_DNS_PROVIDER=route53`. Cleanest for the common case but provider-specific. Discussion warranted before the cut.

### Ownership

docex source change. Surfaces a doctrine question about which providers to bless by default and how to scope provider creds.

---

## Gap B — Per-project traefik is not constrained to its project

### Symptom

A project's per-project traefik watches every container with `traefik.enable=true` reachable on `docex-ingress`, including other projects' preinfra traefiks (HyperDX, container registry) and any other doctrine projects' env-tier services. Traefik tries to register routers for foreign containers it can't reach (different docker networks), then logs ACME-cert failures for them on every reconcile.

### Root cause

`emit_project_compose`'s traefik command line includes `--providers.docker=true --providers.docker.exposedbydefault=false` but no constraint expression. Per traefik's docs, the right knob is `--providers.docker.constraints="Label(\`docex.project\`, \`<this_project>\`)"` paired with a `docex.project=<this_project>` label on every container emitted by this project.

### Severity

**Medium**. Routing is correctly internally consistent — each project's traefik picks up its own labelled containers — but it spams logs with cross-project ACME failures and makes the traefik-side debugging story noisier than it should be.

### Workaround

None needed for routing correctness. Operators may filter traefik logs by `routerName=<this_project>` to ignore foreign-router noise.

### Fix shape

1. `emit_project_compose` emits `--providers.docker.constraints="Label(\`docex.project\`, \`<this_project_dns_label>\`)"` on the traefik command line.
2. `emit_compose` (env-tier) and `emit_project_compose` (project-tier traefik itself) add a `docex.project: <this_project_dns_label>` label to every container they emit.
3. Container-backing engines (per `transfer_tables.md § Container-backing services on elastic`) that emit on fixed via `compose_service` need the label too; the emit-site adds it uniformly.

### Ownership

docex source change. No doctrine question.

---

## Gap C — `docex merge` requires `origin`

### Symptom

`docex merge` exits non-zero with `fatal: 'origin' does not appear to be a git repository` on any inner repo that has no remote configured. The test projects under `test_projects/` deliberately have no remote (per `test_projects.md`), so the smoke walker has to do the rebase + tag + push by hand:

```bash
git checkout main && git merge --ff-only <feature> && git tag v<version>
```

### Root cause

`src/docex/pipeline/merge.py` (or wherever the merge runner lives) hard-codes a `git fetch origin` step. There's no fallback path for the "no remote" case.

### Severity

**Low**. Doesn't block any real-project usage (real projects always have a remote). Only the smoke walks are affected. But the smoke walks are the doctrine's primary integration-test surface, so it's a real friction.

### Workaround

Walker performs the merge by hand. Documented in `PRE_CUT_CHECKLIST.md` C.6.1 / D.8 (walker notes).

### Fix shape

`merge` detects `git remote get-url origin` failing and switches to a no-remote path: skip `git fetch`, skip `git push` (no remote to push to), still perform the local rebase + tag. Logs a one-line note that "no origin configured; skipping push" so the operator knows.

### Ownership

docex source change. Possibly trivial — a single `try/except`-shaped check.

---

## Gap D — Empty-`dist/` chicken-and-egg on first `envinfra up dev`

### Symptom

First-time `docex envinfra up dev` against a fresh project tree crash-loops the web container with `python: can't open file '/service/dist/root.py': [Errno 2] No such file or directory`. The container restarts forever; `docex build` then refuses to populate `dist/` because the dev container "is not running" (it's restarting, which docker doesn't count as running for `compose exec` purposes).

### Root cause

The dev-stage container's compose entry has `/service/dist` bind-mounted from the host. The host `dist/` starts empty on a fresh project; the bind-mount overlays the in-image artifact with the empty host dir. `python /service/dist/root.py` then can't find the script.

`docex build` won't fire while the container is in `Restarting` state. The cycle is closed.

### Severity

**Medium**. Affects every newly-incepted project's first `envinfra up dev`. The fix is mechanical (one host-side `bash core/<svc>/build.sh` before first up) but it's a confusing experience for a brand-new project.

### Workaround

Walker runs `bash core/<svc>/build.sh` host-side (or `sudo` if `dist/` was previously root-owned by a prior container run) before the first `envinfra up dev`. Documented in `PRE_CUT_CHECKLIST.md`'s walker notes.

### Fix shape

Two reasonable paths:

1. `docex envinfra up dev` detects empty `dist/` directories before bringing the stack up and runs `build.sh` in an ephemeral dev-stage container (no bind mount → in-image artifact lives, build.sh deposits it into the bind-mounted `dist/`).
2. `docex build` learns a `--restarting-ok` flag (or just detects the case automatically): spawn an ephemeral dev-stage container with no bind mount, run build, exit.

Either fixes the chicken-and-egg. Path 1 makes first-up just-work; path 2 keeps the boundary cleaner.

### Ownership

docex source change. No doctrine question.

---

## Gap E — ECS task definitions emit no `logConfiguration`

### Symptom

ECS task definitions have no `logConfiguration` block. Container stdout/stderr is invisible by default — neither CloudWatch nor any other sink receives them. Debugging an ECS-side issue (a worker that's silently failing, a migration whose error message lives in stdout) means hand-patching a new task-def revision with `awslogs` and `RunTask`-ing it manually.

### Root cause

`src/docex/emit/templates/main.tf.j2` (and `hcl.py::render_task_definition`) don't emit `log_configuration` on the container definitions. The doctrine implicitly expects all observability to flow through the OTel sidecar — which works for telemetry signals from the app itself but doesn't capture stdout-level diagnostics (crash messages, panic stacks, etc).

Already documented in `docex/plans/core/release_flow.md § Common failure modes`.

### Severity

**Medium**. Doesn't block normal deployments but makes incident response on elastic significantly harder. The fixed walk doesn't surface this (docker logs are available on fixed by default).

### Workaround

Hand-patch a task definition + RunTask + read CloudWatch when debugging. Aware that the workaround is real friction during outages.

### Fix shape

Emit a `log_configuration` block on every container definition that points at a per-env CloudWatch log group:

```hcl
log_configuration = {
  logDriver = "awslogs"
  options = {
    "awslogs-group"         = "/${project_dns_label}/${env}/${service}"
    "awslogs-region"        = "us-east-1"
    "awslogs-stream-prefix" = "ecs"
    "awslogs-create-group"  = "true"
  }
}
```

The task-execution IAM role's inline policy already permits `logs:CreateLogStream` + `logs:PutLogEvents` on `arn:aws:logs:...:log-group:/<project>/<env>/*` (per `elastic_iam.md`), so no IAM change is required. Just the emit.

Could also be paired with a doctrine-level decision on log retention (default 30 days? operator-tunable?).

### Ownership

docex source change. Light doctrine touch (retention policy).

---

## Gap F — `docex projinfra down production` on elastic has no automated path

### Symptom

`docex projinfra down production` on elastic prints `no automated path yet for production-side down. Run teardown.sh manually to destroy elastic prod resources.` and exits 0. The operator has to run the project's `teardown.sh` manually — which is itself bespoke per project (and was buggy on the test project at first; see `docex_smoke_elastic v0.0.5`'s teardown.sh fix).

### Root cause

The dispatcher in `__main__.py::_cmd_projinfra` only has a real implementation for `(elastic, up, production)` (via `run_bootstrap`). The `(elastic, down, production)` case never got a runner. Mod 048 added the informational message but no actual destroy logic.

### Severity

**Medium**. Operator-script alternative works, but it means every elastic project has to carry its own `teardown.sh` and keep it in sync with the doctrine's emit-side changes (the test project's teardown bug was exactly this — it didn't track mod 035's path layout change).

### Workaround

`bash teardown.sh` per project. Doctrine ships test_projects/elastic/teardown.sh as a starting point operators can crib from.

### Fix shape

`docex projinfra down production` on elastic runs the inverse of `run_bootstrap`: targeted `tofu destroy` per env (prod → stage → project), then SSM cleanup, then state-backend cleanup. The script-side bits (RDS deletion-protection flip, direct-delete with skip_final_snapshot, ECR force-empty) move into docex code and become the canonical doctrine pattern. teardown.sh stays as a thin wrapper or disappears.

Adjacent: `docex projinfra down production` should refuse to run if any env-tier resources still exist (matching `projinfra/overview.md`'s layering rule). The smoke project's `teardown.sh` does this implicitly by tearing envs first; the docex version should be explicit.

### Ownership

docex source change. Doctrine touch on what "down production" means (does it tear envs too? or refuse if envs exist? probably the latter).

---

## Gap G — `docex release` doesn't manage target-host docker creds

### Symptom

First-ever `docex release stage` on fixed fails at `docker compose pull` with `unexpected status from HEAD request to https://registry.luxrnd.tech/v2/...: 401 Unauthorized`. The fix is to manually copy `~/.docker/config.json` from the operator's home into `/home/deploy/.docker/config.json` AND `/root/.docker/config.json` on the target host, OR to run `docker login` as both `deploy` and `root` on the target.

### Root cause

The ansible playbook emitted by `docex compile` doesn't push docker credentials to the deploy target. Per `release_mechanism.md § Registry Credentials`, the target host's `~/.docker/config.json` is supposed to be set up "out of band as part of `host_machine` prerequisite setup." But the doctrine doesn't document a doctrine-prescribed way to do that, and there's no `docex preinfra` hook that checks for it.

### Severity

**Medium**. Blocks the first fixed release on any new target host. Operator confusion until the 401 is decoded.

### Workaround

`PRE_CUT_CHECKLIST.md` A.7 documents the manual `docker login` steps for both `deploy` and `root`. Walker follows them.

### Fix shape

Three reasonable paths:

1. `docex preinfra production` (fixed) probes for docker-creds presence on the target via SSH (`test -f /home/deploy/.docker/config.json && test -f /root/.docker/config.json`). Adds a clear failure with the resolution.
2. `docex release` emits an ansible task that runs `docker login` against `infra/deploy_creds/registry.json` (a new file pattern), if present.
3. Doctrine documents this as out-of-band operator setup in `preinfra/container_registry.md` with a code snippet (less satisfying but lowest-effort).

Path 1 is the lightest docex change and matches the spirit of preinfra checks.

### Ownership

docex source change OR doctrine-doc change. Both could land at the same time.

---

## Gap H — Fixed walk DNS records are operator-side

### Symptom

`PRE_CUT_CHECKLIST.md` A.4.1 requires the operator to hand-create 9 DNS records in the parent zone pointing at the dev machine's public IP (one per env subdomain + wildcard + bare-project). Without them, `docex stagetest` fails with NXDOMAIN.

### Root cause

The fixed-foundation walk uses the dev machine as the deploy target; per-env DNS records aren't managed by docex (docex doesn't know what zone or what IP). The doctrine treats this as operator-side.

### Severity

**Low**. The walker does it once per project. But it's friction every cut and the records can easily go stale if the dev machine's IP changes.

### Workaround

Walker creates records by hand via `aws route53 change-resource-record-sets` (per the smoke walk's actual flow — I scripted this once for the fixed walk).

### Fix shape

Either:

1. `docex preinfra production` (fixed) takes an optional `--dev-ip` or reads `infra/preinfra/dev_machine_ip.txt` and verifies records exist for the project's env hosts pointing at it.
2. `docex projinfra up production` (fixed) emits a Route53 record set (assumes operator has Route53 admin on the parent zone — which they often do but not always).
3. Doctrine ships a documented script template at `infra/preinfra/setup_dns.sh` that the walker runs.

Path 2 is cleanest if the assumption holds; path 1 + the script template is the safer fallback.

### Ownership

docex source change OR doctrine-doc change.

---

## Gap I — `health_check_path` field emits a `curl`-based docker healthcheck

### Symptom

The doctrine-emitted docker healthcheck for a `web`-network service is `CMD curl -f http://localhost:${port}${path}`. Python slim, alpine, and most other minimal base images don't carry curl. The container is perpetually `unhealthy`; traefik 3.x's docker provider filters it out; routing dies on arrival.

### Root cause

The `web/container` engine's `health_check_path.fixed` translation in `tables/roles/web.yml` (or wherever) emits a `curl`-shaped check. The check assumes the project's Dockerfile installs curl — which is an undocumented operator-side requirement.

### Severity

**Medium**. Affects every fixed-foundation project that declares `health_check_path:` on a web service unless the project's Dockerfile installs the right tool. Smoke project added `RUN apt-get install -y curl` at `docex_smoke_fixed v0.0.2`.

### Workaround

Project-side: install curl (or wget) in the Dockerfile. Document the requirement in the project's notes.

### Fix shape

Two real options:

1. Switch the doctrine emit to a traefik HTTP healthcheck via service labels (`traefik.http.services.<svc>.loadbalancer.healthcheck.path=...`). The check runs from traefik (which always has the tooling); the container's package list doesn't matter. Cleaner end-to-end.
2. Switch to a tool-free probe (Python-only `python -c 'import urllib.request; ...'`) — but that only works in Python containers, defeating the language-agnostic emit goal.

Path 1 is the right answer. Mod 047's discussion of bug 2 already gestured at this.

### Ownership

Transfer table change + doctrine clarification on healthcheck convention.

---

## Gap J — Display strings still use raw `${project}` in some places

### Symptom

User-facing messages from `docex projinfra up production` (and possibly elsewhere) say things like `Route53 hosted zone for 'docex_smoke_elastic.luxrnd.tech' created` — even though the actual zone is `docex-smoke-elastic.luxrnd.tech` (mod 046 fixed the emit; the print statement uses the raw `project_name`). Misleading but harmless.

### Root cause

Mod 046 fixed the emit-side leak but didn't sweep the print/log statements. A handful of places in `__main__.py`, `pipeline/bootstrap.py`, etc., still format with the underscored project name when reporting on resources whose actual names are hyphenated.

### Severity

**Cosmetic**. No runtime impact, but reading docex output and then `aws route53 list-hosted-zones` produces a confusing name mismatch.

### Workaround

None needed. Operator learns to mentally translate.

### Fix shape

Sweep `grep -rn "ctx.project.name\|project=" src/docex/ | grep -i print` and any message that names a DNS / docker / ECS resource uses `_dns_label(project_name)` consistently. One-pass cleanup mod.

### Ownership

docex source change. Trivial.

---

## Gap K — `docex envinfra up dev` doesn't gracefully handle a partial bring-up

### Symptom

If something fails mid-`envinfra up dev` (the empty-`dist/` case from Gap D, a healthcheck that never goes healthy, a bind-mount permission error), the stack is left in a partial state with some containers up and some in restart loops. `docex envinfra up dev` exits non-zero but doesn't auto-recover.

### Root cause

`docex envinfra up dev` orchestrates `docker compose up -d` + migrations + healthcheck waits, but doesn't have a "rescue" path that detects and surfaces what's wrong (e.g. "your dev-stage containers are restarting; possibly an empty `dist/` — try `docex build`").

### Severity

**Low**. The error is recoverable by the walker; the surface area is small.

### Workaround

Walker reads container logs (`docker logs <svc>`) and figures out the issue.

### Fix shape

`docex envinfra up dev` checks each core service's health after bring-up; if any are `restarting` or `unhealthy`, prints a one-line diagnostic per service (the common cases: empty dist, healthcheck tool missing, env var missing). Doesn't auto-fix; just makes the failure surface readable.

### Ownership

docex source change. Light.

---

## Cut sequencing

These gaps are mostly independent — there's no campaign-style ordering requirement like the original shape-and-tier mods had. Suggested grouping by mod:

- **Mod 049** (one-shot polish, patch cut 1.0.4): Gaps **C** (`docex merge` no-origin), **J** (display strings), **K** (envinfra-up diagnostic). All small, all low-risk.
- **Mod 050** (deploy-target ergonomics, minor cut 1.1.0): Gaps **G** (registry creds on deploy target), **H** (fixed-walk DNS), **D** (empty-dist chicken-and-egg). Touch the deploy path; collectively justify a minor.
- **Mod 051** (traefik UX, minor cut 1.2.0): Gaps **A** (ACME-provider creds), **B** (project-traefik network constraint), **I** (healthcheck convention). Three related traefik-shaped changes; tighter to land together.
- **Mod 052** (elastic observability + lifecycle, minor cut 1.3.0): Gaps **E** (ECS logConfiguration), **F** (`projinfra down production` automated). Both elastic-only; both deserve test-walks.

That's a 4-mod / 4-cut path from 1.0.3 to 1.3.0 to close the post-shape-overhaul gap surface. Patch (mod 049) lands first as a quality-of-life sweep; the minors land at whatever cadence makes sense for the operator's pace.

A minor cut requires a smoke walk per `docex_process.md`, so mods 050–052 each pay the smoke-walk tax. That's the cost of catching the integration-class regressions — and given that the post-1.0.0 smoke walks themselves surfaced 8 bugs across mods 046–048, the tax is genuinely earning its keep.
