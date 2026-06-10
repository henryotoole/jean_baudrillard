# Mod 051 — Implementation Steps

Fresh-context guide for [`overview.md`](./overview.md). Three traefik-shaped gaps: **A** (HTTP-01 certs on fixed), **B** (project-scope the traefik), **I** (mandate curl on web images + a check gate). All doctrine changes for this mod are **already done and committed** — do **not** edit `doctrine/**`.

**Plan context:** this mod feeds a *single* later `1.1.0` cut. **Do NOT bump the version** (`pyproject.toml` / `__init__.py` stay at `1.0.3`); only append to `CHANGELOG.md`'s `[Unreleased]`. Do **not** commit, tag, or `docker build`. Leave changes uncommitted. Don't touch the `engineer/tmp/*` deletions or `plans/core/*` / `plans/campaigns/*`.

Use `pytest` directly (no `python` on PATH; no venv).

---

## Step 1 — Gap A: HTTP-01 challenge in the project traefik

All in `src/docex/emit/compose.py::emit_project_compose`, the traefik service's `command` list (currently ends with the two `dnschallenge` lines). Match the doctrine command block now in `fixed_reverse_proxy.md`:

- **Replace** the two lines:
  ```
  "--certificatesresolvers.doctrine.acme.dnschallenge=true",
  "--certificatesresolvers.doctrine.acme.dnschallenge.provider=${TRAEFIK_DNS_PROVIDER:-}",
  ```
  **with:**
  ```
  "--certificatesresolvers.doctrine.acme.httpchallenge=true",
  "--certificatesresolvers.doctrine.acme.httpchallenge.entrypoint=web",
  ```
- The `${TRAEFIK_DNS_PROVIDER:-}` reference is now gone. **Keep** `--certificatesresolvers.doctrine.acme.email=${TRAEFIK_ACME_EMAIL:-}` (HTTP-01 still registers an LE account). If `TRAEFIK_DNS_PROVIDER` is referenced/documented anywhere else in docex (grep the tree), remove the now-dead reference.

No env block, no creds, no shim change — that's the point of HTTP-01.

---

## Step 2 — Gap B: constrain the traefik to its project + label every container

### 2a. The constraint (project traefik command)
In `emit_project_compose`, add to the traefik `command` list, right after `--providers.docker.exposedbydefault=false`:
```
f"--providers.docker.constraints=Label(`docex.project`,`{project_dns_label}`)",
```
(`project_dns_label` is already a parameter of `emit_project_compose`.)

### 2b. The `docex.project` label on EVERY emitted container
Stamp `docex.project=<project_dns_label>` on every container docex emits on fixed. Add it uniformly — prefer a single helper (e.g. `_docex_project_label(project_dns_label) -> str` returning `f"docex.project={project_dns_label}"`) used at all emit sites:

- **Env-tier core + backing service blocks** (`emit_compose`): every service dict gets a `labels` entry including the `docex.project` label. For `web` services that already get Traefik discovery labels (via `_traefik_labels`), **append** the `docex.project` label to that list — don't create a second `labels` key. For non-web services (no current labels), create a `labels` list with just the `docex.project` label.
- **OTel sidecars** (`_sidecar_block`): add the label to the sidecar's block too.
- **The project traefik itself** (`emit_project_compose`): add a `labels` list with the `docex.project` label to the traefik service dict.

The value must be **identical** to the constraint's value (`project_dns_label`) — that string equality is what makes the constraint match. (Docker labels can be a list `["k=v"]` or map `{k: v}`; match whatever style each existing block uses — `_traefik_labels` uses the list style.)

---

## Step 3 — Gap I: `_gate_healthcheck_tooling` in `docex check`

New gate in `src/docex/pipeline/check.py`, following the existing `_gate_*` + `CheckReport` pattern (mirror `_gate_health_endpoints`, which already iterates web services). For each **core service on the `web` network that declares `health_check_path`**:

1. Build its image at the `prod` target: `docker.build_image(svc_dir, target="prod", tag=f"docex-hcgate-{svc}:check")`. If the build fails (non-zero), `report.add("healthcheck_tooling", False, "<svc>: image build failed")` and move on (the build gate will also catch it).
2. Probe for curl: `docker.run_one_shot(tag, ["sh", "-c", "command -v curl >/dev/null 2>&1"], remove=True)`. Exit 0 → curl present; non-zero → absent.
3. On absence: `report.add("healthcheck_tooling", False, detail=...)` with the resolution: `"service '<svc>' declares health_check_path but its image lacks curl; the Docker healthcheck will fail and Traefik will drop the route. Add curl to its Dockerfile (apt-get/apk install curl)."`
4. If all qualifying services pass (or there are none), `report.add("healthcheck_tooling", True, ...)`.

Wire it into `run_check`'s gate sequence after the build/test images are available (it does its own `prod`-target build, so it's self-contained — place it alongside the other per-service gates). The `web.yml` healthcheck emit is **unchanged**.

If iterating every web service's `prod` build proves heavy, that's an acceptable cost for a pre-merge gate; note it but don't pre-optimize.

---

## Step 4 — CHANGELOG (no version bump)

Append to the existing `## [Unreleased]` `### Added` / `### Fixed`:
- **Fixed (Gap A):** fixed-foundation project traefik now issues Let's Encrypt certs via **HTTP-01** (per-host), eliminating the DNS-provider-credential requirement that left it unable to issue certs. Elastic keeps ACM wildcards.
- **Fixed (Gap B):** the per-project traefik is now constrained to its own project (`--providers.docker.constraints` + a `docex.project` label on every emitted container), so it no longer registers foreign routers / spams ACME failures for other projects on `docex-ingress`.
- **Added (Gap I):** `docex check` now gates on `curl` presence in every `health_check_path`-declaring service's image, turning a silent unhealthy-route-death into a loud, early failure.

---

## Step 5 — Tests

- **Gap A:** assert `emit_project_compose` output's traefik command contains `httpchallenge=true` + `httpchallenge.entrypoint=web` and contains **no** `dnschallenge` / `TRAEFIK_DNS_PROVIDER`.
- **Gap B:** assert the traefik command contains the `constraints=Label(\`docex.project\`,\`<label>\`)` expression; and assert that env-tier emit puts `docex.project=<label>` on a core service, a backing service, a sidecar, and the project traefik (one assertion per container kind).
- **Gap I:** unit-test `_gate_healthcheck_tooling` with a fake `DockerClient` — curl present (`run_one_shot`→0) passes; curl absent (→non-zero) fails with the resolution detail; a service without `health_check_path` / not on web is skipped. Add a real-docker integration test (`@pytest.mark.integration`): build a tiny curl-less image, assert the gate fails — mirror how existing integration tests are marked.

Run `pytest -q` (must pass) and `pytest -q -m integration` (known pre-existing `test_stagetest_real` sandbox-DNS failure is not yours).

---

## Files expected to change

| File | Why |
| ---- | --- |
| `src/docex/emit/compose.py` | HTTP-01 flags (A); traefik constraint + `docex.project` label on all emit sites incl. `_sidecar_block` (B) |
| `src/docex/pipeline/check.py` | `_gate_healthcheck_tooling` (I) |
| `tests/conftest.py` | fake `DockerClient` `run_one_shot`/`build_image` scripting for the gate, if not already present |
| `tests/unit/test_emit_compose.py` (or equivalent) | Gap A + Gap B emit assertions |
| `tests/unit/test_pipeline_check.py` | Gap I gate unit tests |
| `tests/integration/…` | Gap I real-docker curl-less-image test |
| `CHANGELOG.md` | `[Unreleased]` entries (no version bump) |

Out of scope: version bump, doctrine edits (done), the smoke project's `verify=False` removal (handled at the cut's smoke walk), DNS-01/cred plumbing (deleted, not plumbed).
