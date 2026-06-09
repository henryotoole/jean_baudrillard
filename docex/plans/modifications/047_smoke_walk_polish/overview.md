# Mod 047 — Smoke-Walk Polish (Bug Bundle)

Patch mod bundling four runtime bugs surfaced during the post-1.0.1 fixed-foundation smoke walk on the test project. None of the bugs were caught by unit tests; they only appeared once the projinfra + envinfra + release pipeline ran end-to-end against a real host. This mod ships fixes for each, plus the docex-side polish so the next walker doesn't trip on the same things.

The mod was authored *during* a smoke walk — fixes already landed in the source tree before the cut. This is non-standard process (the mod usually lands before the walk) but acceptable here because each bug blocked progress and the next bug was hidden by the previous; cutting + re-walking each time would have cost too much.

## Bug 1 — Traefik 3.3 docker-provider docker-API mismatch

**Symptom:** `docex projinfra up <side>` brought up the per-project traefik successfully, but the traefik's docker-provider loop emitted `Error response from daemon: client version 1.24 is too old. Minimum supported API version is 1.40` and never picked up any env-tier service labels. Routing dead-on-arrival.

**Root cause:** docex's `TRAEFIK_IMAGE` was pinned to `traefik:v3.3`. The 3.3 docker provider defaults to a long-deprecated Docker API version (1.24) when negotiating with the daemon, and modern Docker daemons (24+) refuse it. v3.4+ fixed the negotiation. The doctrine's per-project traefik path was effectively unreachable on any host running a recent Docker daemon.

**Fix:** Bump pin to `traefik:v3.6` (digest resolved + recorded in `src/docex/__init__.py`). The operator's other workloads on the dev host were already running v3.6 with no issue, which served as the "known good" datapoint for the bump.

## Bug 2 — Traefik service-label emit missing `traefik.docker.network`

**Symptom:** After Bug 1 was fixed, the web container's router got registered in traefik but every request returned 504 (Gateway Timeout). Traefik logs showed the backend URL with the container's `-internal` network IP (`172.25.0.5:8080`) — unreachable from traefik because traefik is on `-web`, not `-internal`.

**Root cause:** A `web`-network service is on at least two docker networks (the project's per-env `-web` network shared with traefik, plus the env's `-internal` network not shared). Traefik 3.x's docker provider needs `traefik.docker.network=<network-name>` to pick the right network deterministically when forming the backend URL; without it, traefik picks one of the container's networks non-deterministically. The `_traefik_labels` emit in `src/docex/emit/compose.py` didn't include the label, so docex projects on multi-network configurations got 504s on every routed request.

**Fix:** Add `traefik.docker.network=${project_dns_label}-${env}-web` to the label set. The `_traefik_labels` function now takes `project_dns_label` and `env` as additional parameters; the single call site at `emit_compose` passes them from `compiled`. Net: one extra label per `web`-network service. Mirrors the pattern the project's other preinfra traefiks already use (HyperDX, container registry).

## Bug 3 — `health_endpoints` check too strict

**Symptom:** `docex check` failed with `health_endpoints: web.openapi.yml: missing 'GET /health/appdb' (required because 'web' depends on non-web 'appdb')`. But `appdb` is a backing service (postgres), and the doctrine's `contracts.md § Health Checks` says only CORE service downstream deps need `/health/<dep>` entries.

**Root cause:** The check at `src/docex/pipeline/check.py::_gate_health_endpoints` iterated over every entry in `svc_decl.depends_on` and asked both `core_services` AND `backing_services` for the matching declaration. Whether the dep was core or backing didn't influence the requirement — both ended up gated. The doctrine prose is unambiguous: backings are exempt.

**Fix:** Narrow the dep lookup to `infra.core_services.get(dep)` only. Backings no longer trip the gate. Projects voluntarily exposing `/health/<backing>` endpoints (as the test projects do for `probe` and `events`) remain free to do so — the check just doesn't *require* them.

## Bug 4 — Per-project traefik can't issue Let's Encrypt certs (project doctrine gap, not strictly a bug fix in this mod)

**Symptom:** Stage tests fail with `httpx.ConnectError: [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: self-signed certificate`. Traefik logs show ACME provider attempting to register but failing with `acme: error: 429 ... too many new registrations` (rate-limited after enough churn) or, before that, `no EC2 IMDS role found, no creds` (no AWS credentials available in the traefik container).

**Root cause:** docex's `emit_project_compose` emits a traefik with command-line `--certificatesresolvers.doctrine.acme.dnschallenge=true --certificatesresolvers.doctrine.acme.dnschallenge.provider=${TRAEFIK_DNS_PROVIDER:-}`. The DNS provider needs creds — for Route53 those are `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` / `AWS_REGION` environment variables on the traefik process. docex's traefik compose has no `environment:` block; there's no path for those creds to reach the container even when set on the operator's shell. Traefik silently falls back to its self-signed default cert and serves with that.

**Scope decision:** The fix here is not landing in mod 047. Properly propagating DNS-provider creds requires deciding which provider's env vars to thread through (Route53 vs. Cloudflare vs. many others), how to scope creds securely (mount path? per-provider env-var list? operator-supplied compose fragment?), and how to surface a "no creds; degraded path" mode in compile output. Each of those is a real design decision that warrants its own discussion. Mod 047 instead:

- Documents the gap clearly in this overview.
- Lets the smoke project pragmatically use `httpx.Client(verify=False)` in its stage tests (with a comment pointing back here). The test-project decision was committed as `docex_smoke_fixed v0.0.3` and parallels what the elastic walk will need.
- Leaves the doctrine emit unchanged for this cut. A future mod (call it 048) will land the proper traefik-cred propagation; the doctrine acknowledges the gap until then.

## Out of scope

- **Per-project-traefik network constraint.** The current per-project traefik watches every container with `traefik.enable=true` visible on `docex-ingress`, including other projects' preinfra traefiks (HyperDX, container registry, etc.). That's a doctrine layering concern: a project's traefik picking up non-project labels is wrong. Fix is straightforward (set `--providers.docker.constraints` and a project-scoped label on every emitted container) but deserves its own mod. Tracked separately.
- **`docex merge` without `origin`.** The test projects deliberately have no git remote (per `test_projects.md`); `docex merge` exits non-zero on `git fetch origin`. The smoke walker did the rebase + tag by hand. Worth handling cleanly in a future mod; not blocking the walk.
- **First-up `docex envinfra up dev` against empty `dist/`.** Containers crash-loop with `python: can't open file '/service/dist/root.py'` because the host `dist/` bind-mount overlays the in-image artifact. `docex build` refuses to populate `dist/` while the dev container isn't running, creating a chicken-and-egg. The walker worked around it by running `build.sh` host-side once. Fix path: docex should detect the empty-`dist/` case during `envinfra up` and either populate from a no-bind-mount ephemeral container or pre-emptively warn. Future mod.
- **Traefik 3.x routers with broken cert resolvers.** The doctrine claim "routing still works without certs" doesn't match traefik 3.x behavior — routers with a `tls.certresolver=doctrine` that fails to issue end up unable to serve. Same root cause as Bug 4 (no creds reaching traefik). Will resolve naturally when 4's fix lands; documented here for clarity.

## What lands in this mod

| Change | File(s) |
| ------ | ------- |
| `TRAEFIK_IMAGE` bumped to `traefik:v3.6` | `src/docex/__init__.py` |
| `traefik.docker.network` label emit | `src/docex/emit/compose.py` (`_traefik_labels` + caller) |
| `_gate_health_endpoints` narrowed to core deps | `src/docex/pipeline/check.py` |
| Mod-047 design + impl docs (this folder) | `plans/modifications/047_smoke_walk_polish/` |
| CHANGELOG entry + version bump (1.0.1 → 1.0.2) | `CHANGELOG.md`, `pyproject.toml`, `src/docex/__init__.py` |

## Cut shape

Patch cut: docex 1.0.2. Per [`docex_process.md § Lifecycle`](../../core/docex_process.md), patch cuts skip the test-project smoke walk — though as with mod 046, the patch was *driven by* a smoke walk, so the walk happened anyway as part of post-cut work. The fixed walk against 1.0.2 (rebuilt with these fixes) ran clean through C.11 teardown.

The elastic walk is gated on operator-side master-VPC creation (currently blocked by the 5/5 us-east-1 VPC quota); a future session resumes it after the operator either deletes a non-doctrine VPC or requests a quota increase.
