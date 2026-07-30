# Mod 019 — Reachability probe and test-project updates

## Problem

After mods 017 and 018, every project compiles with `observability_backend_url`, every core service gets OTEL env vars, every core service is paired with an OTel Collector sidecar, and `TELEMETRY_API_KEY` is documented in `example.env`. The last missing piece from the telemetry advance:

1. **Reachability probe in `docex check`.** Per [doctrine/infrastructure/specifics/telemetry_infra.md § Validation Rules](../../../doctrine/infrastructure/specifics/telemetry_infra.md#validation-rules) and [doctrine/infrastructure/cicd.md § Check Step](../../../doctrine/infrastructure/cicd.md#check-step) (the operator added line item #9 to the doctrine's check process), `docex check` should HTTP GET `observability_backend_url` before letting a merge through. Catches typos, expired DNS, broken cert, dead backend — anything that would surface as broken telemetry on release.

2. **Smoke-test project updates.** Both smoke projects need `observability_backend_url` in their `infra.yml` (otherwise they fail compile on docex ≥ 0.11.0 from mod 017's required field). The gitignored `stage.env` / `prod.env` files on the dev machine need `TELEMETRY_API_KEY` populated for stage/prod walks. The smoke projects' own version bumps reflect the substantive `infra.yml` change.

After this mod the advance is feature-complete. The cut of 0.11.0 happens immediately after, per `docex_process.md § Cutting a version`.

## Scope

In scope:

1. **`_gate_observability_backend_url_reachable` in `pipeline/check.py`.** New gate, added to the existing gate-check sequence. HTTP GET against `infra.yml`'s `observability_backend_url`. Any 2xx / 3xx / 4xx response passes (host resolves, TLS handshake completes). DNS failure, TLS failure, connection refusal, or timeout fails. Per the doctrine.
2. **Test-project `infra.yml` updates.** Both `test_projects/fixed/infra/infra.yml` and `test_projects/elastic/infra/infra.yml` declare `observability_backend_url`.
3. **Test-project `stage.env`/`prod.env` updates.** Both projects' `stage.env` and `prod.env` get a `TELEMETRY_API_KEY=<value>` line. These files are gitignored (per the doctrine's secret-flow model); we ALSO update each project's outer-repo-tracked README near `infra/secrets/` to remind the operator the key is required.
4. **Project version bumps.** Both smoke projects bump their own `version:` in `project.yml` — `0.0.3 → 0.0.4` for fixed, `0.0.5 → 0.0.6` for elastic — to reflect the substantive `infra.yml` change. Per [version_control.md § Format](../../../doctrine/infrastructure/version_control.md#format) this is a patch bump (additive infra config).
5. **Smoke-project changelogs.** Each project's `CHANGELOG.md` gets a new `[<v>]` entry documenting the new field.
6. **Unit tests for the new gate.** Mock `urllib.request.urlopen` to verify: 200 passes; 401 passes; HTTPError-with-401 passes; URLError fails; TimeoutError fails; absent `infra.yml` is gracefully skipped (consistent with sibling gates).

Out of scope:

- **The cut itself.** Mod 019 lands `_gate_observability_backend_url_reachable` and updates the smoke projects so they're ready to walk. The actual cut steps (1–7 of `docex_process.md § Cutting a version`) happen *after* mod 019's commit, when the operator runs the PRE_CUT_CHECKLIST walk and validates everything end-to-end.
- **Re-pinning the smoke projects to `0.11.0`.** That happens during step 7 of the cut, via `docex_install.sh`. Until then both smoke projects still pin `docex_version: "0.10.0"` in their `project.yml`.
- **Actually walking the smoke projects.** The walk is real-infrastructure (AWS, DNS, real registry) work the operator drives via `PRE_CUT_CHECKLIST.md`. The agent's contribution is to make the projects walk-ready.

## Design

### Reachability probe

New gate function in `src/docex/pipeline/check.py`:

```python
def _gate_observability_backend_url_reachable(
    ctx: ProjectContext,
    report: CheckReport,
) -> None:
    """HTTP GET against ``observability_backend_url``. Any 2xx/3xx/4xx
    response passes — the check verifies the host resolves and the TLS
    handshake completes. DNS resolution failure, TLS handshake failure,
    connection refusal, or timeout fails the gate.

    See doctrine/infrastructure/specifics/telemetry_infra.md § Validation
    Rules and cicd.md § Check Step.
    """
    infra = ctx.infra
    if infra is None:
        report.add(
            "observability_backend_reachable",
            True,
            "no infra.yml — skipped",
        )
        return

    url = infra.observability_backend_url
    try:
        # 10 s timeout: enough for slow ACME-backed TLS handshakes but
        # short enough that an unreachable host fails the gate quickly.
        with urllib.request.urlopen(url, timeout=10):  # nosec B310
            pass
    except urllib.error.HTTPError as exc:
        # Server responded with non-2xx — host is up. 401/404 are common
        # for OTLP-only endpoints lacking a generic GET handler; either
        # confirms reachability sufficient to catch DNS/cert typos.
        report.add(
            "observability_backend_reachable",
            True,
            f"{url} responded HTTP {exc.code}",
        )
    except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
        report.add(
            "observability_backend_reachable",
            False,
            f"{url} unreachable: {exc}",
        )
    else:
        report.add(
            "observability_backend_reachable",
            True,
            f"{url} reachable",
        )
```

Add imports at the top of `pipeline/check.py`:

```python
import socket
import urllib.error
import urllib.request
```

Invocation in `run_check` lives alongside the existing `_gate_health_endpoints` / `_gate_service_scripts` block. The probe runs unconditionally (not gated on `empty_origin`) because it doesn't depend on git state — it depends on `infra.yml`'s declared URL.

The doctrine ([telemetry_infra.md § Validation Rules](../../../doctrine/infrastructure/specifics/telemetry_infra.md#validation-rules)) notes: "The reachability probe runs only when `stage` or `prod` are within the check's scope — `dev` and `test` don't have a backend URL to probe." `docex check` is always preparing a merge that will eventually reach stage/prod, so the probe always runs.

### Test-project `infra.yml`

`test_projects/fixed/infra/infra.yml`: add toplevel field after the existing `repo_url:`:

```yaml
# Project-wide observability backend (self-hosted HyperDX). Sidecars in
# stage/prod export OTLP signals here. See doctrine/infrastructure/
# specifics/telemetry_infra.md.
observability_backend_url: "https://hyperdx.luxrnd.tech"
```

Identical line for `test_projects/elastic/infra/infra.yml`.

The URL `hyperdx.luxrnd.tech` matches the doctrine's prereq pattern for the operator's self-hosted HyperDX instance (per `prereq/telemetry_preinfra.md`'s `${base_domain}` convention). It assumes the operator has stood up HyperDX at that address before walking the smoke projects, which is a separate preinfra step.

### Test-project gitignored secrets

The `<env>.env` files are gitignored, but they exist on the dev machine alongside the smoke projects. We append a line to each one as a side-effect of this mod:

- `test_projects/fixed/infra/secrets/stage.env` and `prod.env`: add `TELEMETRY_API_KEY=<placeholder value>`. The operator replaces with the real key from HyperDX before walking C.7 / C.9.
- Same for `test_projects/elastic/infra/secrets/stage.env` and `prod.env`.

`dev.env` / `test.env` do not need the key (debug exporter doesn't authenticate).

We do NOT add the key to `example.env` here — that file is regenerated by `docex compile` on every run, and mod 017's `emit_example_env` already includes `TELEMETRY_API_KEY=` automatically.

### Test-project changelogs

Each smoke project has its own `CHANGELOG.md`. Add an entry under each:

```
## [0.0.4] - 2026-06-03                  (fixed; was 0.0.3 → 0.0.4)
## [0.0.6] - 2026-06-03                  (elastic; was 0.0.5 → 0.0.6)

### Added

- Declare `observability_backend_url: "https://hyperdx.luxrnd.tech"`
  in `infra/infra.yml`. Required as of docex 0.11.0 (added by mod 017).
  Sidecars in stage/prod export telemetry to this backend; the API key
  goes in `infra/secrets/{stage,prod}.env` as `TELEMETRY_API_KEY=`.
```

Date is today's `2026-06-03`. Both projects keep their separate version tracks.

### Project.yml version bump

`test_projects/fixed/project.yml`: `version: "0.0.3"` → `"0.0.4"`.
`test_projects/elastic/project.yml`: `version: "0.0.5"` → `"0.0.6"`.

`docex_version` stays at `"0.10.0"` — gets repointed to `"0.11.0"` during step 7 of the cut, via `docex_install.sh`.

### Inner-repo commit handling

Per `test_projects.md § Commit cadence`, the inner repo for each smoke project commits first, then the outer doctrine repo catches up. For mod 019:

1. Commit inside `test_projects/fixed/.git` with message `"Bump 0.0.4: declare observability_backend_url in infra.yml"`.
2. Move the version tag: `git tag -f v0.0.4` at the new inner HEAD.
3. Same shape for `test_projects/elastic/` (`Bump 0.0.6: ...`, tag `v0.0.6`).
4. The outer doctrine repo then includes those inner-repo state changes as part of mod 019's tracked commit.

This is the standard cadence for any mod that touches the smoke projects.

## Five-artifact alignment

| Artifact | Change |
| -------- | ------ |
| `doctrine/.../*.md` | None in this mod (operator already added cicd.md item #9 for the reachability probe in their parallel edits). |
| `docex/plans/core/*.md` | `compiler.md` unchanged (probe isn't part of compile). Could optionally add a row in `release_flow.md` "where to look" table for `docex check` gate ordering, but that file isn't really a check.py guide — skipping. |
| `tables/roles/*.yml` | None. |
| `src/docex/**` | `src/docex/pipeline/check.py` (+ new gate, + imports, + invocation). |
| `tests/**` | New `tests/unit/test_check_observability_gate.py` covering the gate's success and failure modes via mocked `urlopen`. |

## Risk and rollback

- **Local-only check failures from the probe.** If the operator's local environment can't reach the configured backend (DNS misconfig, firewall, expired cert), `docex check` will fail. This is the gate's *purpose* — it should fail loudly in those cases. The fix is to repair the backend; the doctrine treats a non-reachable backend as a release-blocker.
- **Smoke project gitignored env file edits.** Adding `TELEMETRY_API_KEY=` to `<env>.env` files is a side-effect operation. The operator can re-pin those keys later via the standard secret-rotation workflow. No commit risk — those files are gitignored.
- **Rollback:** revert the mod's commit. Gate is purely additive; the smoke projects' `infra.yml` changes are reverted by the same git operation.

## What this mod does NOT do

- Does not cut 0.11.0. That's a separate sequence after this mod's commit.
- Does not run the PRE_CUT_CHECKLIST walk. The operator walks both projects after this mod lands.
- Does not regenerate compiled output in the smoke projects. The operator's walk includes `./bin/docex compile` against each project (with the new pin).
- Does not update doctrine prose. The doctrine has the reachability probe documented at `cicd.md § Check Step` step 9 and `specifics/telemetry_infra.md § Validation Rules` already.
- Does not touch the example.env emission again (mod 017 covers it).
