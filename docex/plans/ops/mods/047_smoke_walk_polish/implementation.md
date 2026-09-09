# Implementation — Mod 047 — Smoke-Walk Polish

## Context

The fixes already landed in the source tree during the post-1.0.1 smoke walk. This document records what shipped and where, so a future reader (or a debug session into a specific bug) can find the diff site directly.

## Changes shipped

### 1. `TRAEFIK_IMAGE` pin

**File:** `src/docex/__init__.py`

`TRAEFIK_IMAGE = "traefik:v3.3@sha256:2cd5cc..."` → `TRAEFIK_IMAGE = "traefik:v3.6@sha256:cc1799c..."`. Comment block also updated to point at the new `docker pull traefik:v3.6` re-resolution recipe.

### 2. `traefik.docker.network` label

**File:** `src/docex/emit/compose.py`

`_traefik_labels` signature: `(svc: CompiledService) -> list[str]` → `(svc: CompiledService, project_dns_label: str, env: str) -> list[str]`. Body adds `f"traefik.docker.network={project_dns_label}-{env}-web"` as the first label after `traefik.enable=true`. Single call site at `emit_compose` (around `block["labels"] = _traefik_labels(svc)`) now passes `compiled.project_dns_label` and `compiled.env`.

### 3. `_gate_health_endpoints` narrowed to core deps

**File:** `src/docex/pipeline/check.py`

Inside the per-contract loop:

```python
dep_decl = (
    infra.core_services.get(dep)
    or infra.backing_services.get(dep)
)
```

becomes:

```python
dep_decl = infra.core_services.get(dep)
```

Comment block updated to cite doctrine `contracts.md § Health Checks` and the explicit "core-only" rule.

## Tests

This mod did not add new tests. The bugs are runtime / integration-class — they don't manifest against unit-test fixtures (no live docker daemon, no traefik provider, no AWS IMDS), so testing them requires either smoke walks or new integration tests that stand up a project-tier compose + a fake env-tier service and curl through. Neither is in scope for this patch cut; future work.

The existing `tests/unit/test_compose_emitter.py` was inspected after the `_traefik_labels` signature change to confirm it still passes (it does — the test indirectly exercises `_traefik_labels` through `emit_compose`, doesn't assert on the new label, and the new label's presence doesn't break any existing assertion). Full unit suite re-run: **445 passed**.

## Verification

Each fix was verified by running the smoke walk forward past the previously-blocked step:

- Bug 1: after pin bump, `docker logs <project>-traefik` no longer shows the docker-API-version error; routers begin to register.
- Bug 2: after label add, curl through traefik to a web service returns the upstream's response (not 504).
- Bug 3: `docex check` passes the `health_endpoints` gate without a `/health/<backing>` declaration on the web contract.

## Smoke-walk usage notes (for the next walker)

Things to know before walking against docex 1.0.2 — these aren't fixes but post-walk learnings:

- The walker must perform the inner-repo `merge` step by hand (`git checkout main && git merge --ff-only <feature> && git tag v<version>`); `docex merge` requires `origin` which the test projects don't have. See [overview.md § Out of scope](./overview.md#out-of-scope).
- The walker must populate `core/<svc>/dist/` once (by running the service's own `build.sh` host-side or by an ephemeral docker run); after that, `docex envinfra up dev` succeeds. See [overview.md § Out of scope](./overview.md#out-of-scope).
- The walker must `docker login <registry>` as the `deploy` user AND `root` on the target host. Without both, `docex release` fails at `docker compose pull` with 401. (Documented in PRE_CUT_CHECKLIST A.7.)
- The walker must arrange for ACME to actually succeed (real DNS provider + creds in the traefik env) OR accept that stage tests need `verify=False` per Bug 4. The smoke project committed the `verify=False` workaround at `docex_smoke_fixed v0.0.3` (and the elastic counterpart will do the same when it walks).
