# Mod 051 — Traefik UX (Gaps A, B, I)

Third of three mods (049/050/051) feeding the **single** `1.1.0` minor cut. Three traefik-shaped gaps, bundled because they all touch the project reverse-proxy / cert / routing path. Gaps A and I were designed jointly with the operator (the stop-and-ask gate); Gap A's design changed substantially from the campaign's original framing.

No per-mod cut, no version bump — changes accumulate under `CHANGELOG.md`'s `[Unreleased]`.

---

## Gap A — fixed project traefik can't issue certs

**Symptom:** the per-project traefik on fixed (and the dev side of elastic projects) can never issue a Let's Encrypt cert; routers fall back to traefik's self-signed default; stage tests reject the cert (`CERTIFICATE_VERIFY_FAILED`), so the fixed smoke project resorts to `httpx.Client(verify=False)`.

**Root cause:** `emit_project_compose` configured the **DNS-01** ACME challenge (`--certificatesresolvers.doctrine.acme.dnschallenge…provider=${TRAEFIK_DNS_PROVIDER:-}`), which requires DNS-provider API credentials that never reach the traefik container (no `environment:` block, and the shim doesn't forward them).

**Decision — switch fixed to HTTP-01, per-host certs.** This *eliminates* the credential requirement rather than plumbing around it: HTTP-01 proves control by serving a token on `:80` (which the HAProxy demux already forwards by Host header), needing **no DNS-provider creds** — provider-agnostic, no shim change. Cost: no wildcards on fixed (one cert per service hostname, issued on demand) — immaterial at the doctrine's scale, and dev↔prod cert airgapping is preserved for free. Elastic keeps its ACM wildcards (DNS-validated by tofu). Full rationale: we walked HTTP-01 vs DNS-01-with-creds vs DNS-01-with-CNAME-delegation and landed on HTTP-01 as simplest.

**Doctrine — DONE this session:** `cicl.md § TLS Implications` (split into Fixed TLS = HTTP-01 per-host / Elastic TLS = ACM wildcards), `shape2.md` fixed + elastic `cert_manager` rows, `fixed_reverse_proxy.md` cert section + traefik command block.

**docex change:** in `emit_project_compose`, replace the two `dnschallenge` command lines with:
```
--certificatesresolvers.doctrine.acme.httpchallenge=true
--certificatesresolvers.doctrine.acme.httpchallenge.entrypoint=web
```
Drop the now-dead `${TRAEFIK_DNS_PROVIDER:-}` reference. **Keep** `${TRAEFIK_ACME_EMAIL:-}` (HTTP-01 still registers an LE account). Mirror exactly the doctrine command block now in `fixed_reverse_proxy.md`.

**Follow-up (not docex code):** once real certs issue, the fixed smoke project can drop its `verify=False` stage-test workaround — handled at the smoke walk during the cut, not here.

---

## Gap B — project traefik not constrained to its project

**Symptom:** the per-project traefik watches **every** `traefik.enable=true` container reachable on `docex-ingress` (other projects' preinfra traefiks for the registry/HyperDX, other projects' env services), tries to register foreign routers, and spams cross-project ACME failures on every reconcile. Routing is internally correct but the logs are noisy and the cert path churns.

**Root cause:** `emit_project_compose`'s traefik command has `--providers.docker=true --providers.docker.exposedbydefault=false` but **no constraint expression**.

**Fix (clear-cut):**
1. Emit `--providers.docker.constraints=Label(\`docex.project\`,\`<project_dns_label>\`)` on the traefik command.
2. Stamp a `docex.project: <project_dns_label>` label on **every** container docex emits on fixed — env-tier services *and* their otelcol sidecars (`emit_compose`), compose-emitted container-backing services, and the project traefik itself (`emit_project_compose`). Uniform label, added at each emit site (not just web services — uniformity, and so the constraint is unambiguous).

**Doctrine touch (light, pending approval):** the campaign tagged Gap B "no doctrine question," but two docs document the surfaces this changes, so alignment needs a touch:
- `fixed_reverse_proxy.md` — add the `--providers.docker.constraints` line to the traefik command block + a sentence on the project-scoping.
- `transfer_tables.md § Per-container (fixed)` — add `docex.project: ${project_dns_label}` to the universal per-container label set listed there.

---

## Gap I — curl-based healthcheck breaks on minimal images

**Symptom:** `web.yml`'s `health_check_path` emits a Docker healthcheck `CMD curl -f http://localhost:${port}${path}`. Minimal base images (python-slim, alpine, distroless) lack curl → the check errors → container is perpetually `unhealthy` → Traefik 3.x's docker provider drops the route.

**Decision — mandate curl on web-service images + a `docex check` gate.** Keeps Docker's internal healthcheck (which we explicitly want — `depends_on: service_healthy`, the `docker ps` signal, the Gap-K diagnostic). The docex *emit* (`web.yml`'s curl healthcheck) is **unchanged**. Resolution refinements agreed with the operator:
- **Scope to services declaring `health_check_path`** (web services), not "all containers" — a port-less worker with no healthcheck needs no curl.
- **Add a `docex check` gate** that converts the silent unhealthy-route-death into a loud, early, actionable failure.

**Doctrine touch (pending approval):** a convention statement that web-service images must contain `curl`, sited near the `/health` mandate in `contracts.md § Health Checks` (and/or `infrastructure.md § Core Service Containers`).

**docex change:** new `_gate_healthcheck_tooling(...)` in `pipeline/check.py` (fits the existing `_gate_*` / `CheckReport` pattern). For each core service on the `web` network that declares `health_check_path`: build its image (or reuse the check's build) and run `docker run --rm <image> sh -c 'command -v curl'`; on absence, `report.add(..., passed=False, detail=…)` with the resolution ("add curl to `<svc>`'s Dockerfile; the Docker healthcheck will otherwise fail and Traefik will drop the route").

---

## Doctrine status across this mod

| Gap | Doctrine touch | Status |
| --- | -------------- | ------ |
| A | `cicl.md`, `shape2.md`, `fixed_reverse_proxy.md` (cert/TLS) | **done this session** |
| B | `fixed_reverse_proxy.md` (constraint), `transfer_tables.md` (per-container label) | **pending — draft for approval** |
| I | `contracts.md` (and/or `infrastructure.md`) — curl convention | **pending — draft for approval** |

Per `docex_process.md` (doctrine-first), I'll draft the **B** and **I** wording for operator approval and make those doctrine edits *before* writing `implementation.md`.

---

## What lands in this mod (docex code)

| Change | File(s) |
| ------ | ------- |
| HTTP-01 challenge flags; drop dead `TRAEFIK_DNS_PROVIDER` (Gap A) | `src/docex/emit/compose.py` (`emit_project_compose`) |
| Traefik `--providers.docker.constraints` (Gap B) | `src/docex/emit/compose.py` (`emit_project_compose`) |
| `docex.project` label on every emitted container (Gap B) | `src/docex/emit/compose.py` (env-tier service block, `_sidecar_block`, traefik block) |
| `_gate_healthcheck_tooling` (Gap I) | `src/docex/pipeline/check.py` |
| `[Unreleased]` entries (no version bump) | `CHANGELOG.md` |

Tests:
- **Gap A:** assert the emitted project compose carries `httpchallenge=true` + `.entrypoint=web` and **no** `dnschallenge` / `TRAEFIK_DNS_PROVIDER`.
- **Gap B:** assert every emitted container (web service, sidecar, backing, traefik) carries `docex.project: <dns_label>`, and the traefik command carries the `constraints=Label(...)` expression.
- **Gap I:** unit-test `_gate_healthcheck_tooling` with a fake `DockerClient` reporting curl present (pass) vs absent (fail with the resolution detail). A real-docker integration test (build a curl-less image, assert the gate fails) is appropriate since the boundary is real.

## Cut shape

No own cut; contributes to the batched **1.1.0**. Gaps A and B touch the fixed cert/routing path, so the **fixed smoke walk** at cut time is the real integration proof: a genuine LE cert issued via HTTP-01 (no `verify=False`), and the project traefik routing only its own labelled containers.
