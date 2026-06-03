# Mod 019 — Implementation steps

Goal: land the reachability probe in `docex check` and update both smoke-test projects so they can be walked under docex 0.11.0.

The sub-agent executing this gets a fresh context — every step below is self-contained.

## Step 1 — Add the reachability gate

File: `src/docex/pipeline/check.py`.

1. Add imports at the top of the file (after the existing imports):
   ```python
   import socket
   import urllib.error
   import urllib.request
   ```

2. Add a new gate function alongside the other `_gate_*` functions (place it right after `_gate_service_scripts` for source-order coherence):

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

3. Invoke the gate in `run_check`. Find the block where existing gates are called:
   ```python
   contracts, _providers = _gate_contracts(worktree, worktree_ctx, report)
   _gate_health_endpoints(worktree, worktree_ctx, contracts, report)
   _gate_service_scripts(worktree, worktree_ctx, report)
   ```
   Append immediately after:
   ```python
   _gate_observability_backend_url_reachable(worktree_ctx, report)
   ```
   The probe must run from the *worktree's* context (which carries the worktree's `infra.yml`), not the project root's, to align with the rest of the gates.

## Step 2 — Update test project `infra.yml` files

Add the new field to both smoke projects' `infra.yml`. Insert it after the existing `repo_url:` line (or anywhere among the top-level fields — placement doesn't change semantics).

File: `test_projects/fixed/infra/infra.yml`. After `repo_url: "https://github.com/luxedo/jean_baudrillard"`:

```yaml
# Project-wide observability backend (self-hosted HyperDX). Sidecars in
# stage/prod export OTLP signals here. See doctrine/infrastructure/
# specifics/telemetry_infra.md.
observability_backend_url: "https://hyperdx.luxrnd.tech"
```

File: `test_projects/elastic/infra/infra.yml`. Identical addition in the same location.

## Step 3 — Append TELEMETRY_API_KEY to gitignored env files

These files are gitignored but live on disk:

- `test_projects/fixed/infra/secrets/stage.env`
- `test_projects/fixed/infra/secrets/prod.env`
- `test_projects/elastic/infra/secrets/stage.env`
- `test_projects/elastic/infra/secrets/prod.env`

To each, append a line:

```
TELEMETRY_API_KEY=PLACEHOLDER_REPLACE_BEFORE_RELEASE
```

The placeholder makes it obvious the operator must replace it with the real HyperDX team API key before walking C.7 / C.9 / D.7 / D.9. Compile + check both succeed with the placeholder; only actual stage/prod release attempts against real HyperDX would fail with `401`.

Do NOT touch `dev.env` or `test.env` — the debug exporter doesn't authenticate, and those files don't need the key.

## Step 4 — Bump project versions and update changelogs

For each smoke project:

1. `test_projects/fixed/project.yml`: bump `version: "0.0.3"` → `"0.0.4"`.
2. `test_projects/elastic/project.yml`: bump `version: "0.0.5"` → `"0.0.6"`.

Leave `docex_version` alone — that gets repinned to `"0.11.0"` during step 7 of the cut, via `docex_install.sh`.

For each smoke project's `CHANGELOG.md`, add an entry above the existing entries:

`test_projects/fixed/CHANGELOG.md`:
```
## [0.0.4] - 2026-06-03

### Added

- Declare `observability_backend_url: "https://hyperdx.luxrnd.tech"` in
  `infra/infra.yml`. Required as of docex 0.11.0 (added by mod 017).
  Sidecars in stage/prod export telemetry to this backend; the API key
  goes in `infra/secrets/{stage,prod}.env` as `TELEMETRY_API_KEY=`.
```

`test_projects/elastic/CHANGELOG.md`: same body, version `[0.0.6]`.

If either CHANGELOG.md doesn't have an `[Unreleased]` section, this entry slots between the toplevel `# Changelog` block and the prior `[<version>]` entry.

## Step 5 — Commit in the inner repos first

Per [`test_projects.md § Commit cadence`](../../core/test_projects.md), the inner repo gets the project-shaped commit first, then the outer doctrine repo catches up:

```bash
cd test_projects/fixed
git add infra/infra.yml project.yml CHANGELOG.md
git commit -m "Bump 0.0.4: declare observability_backend_url in infra.yml"
git tag -f v0.0.4
```

```bash
cd test_projects/elastic
git add infra/infra.yml project.yml CHANGELOG.md
git commit -m "Bump 0.0.6: declare observability_backend_url in infra.yml"
git tag -f v0.0.6
```

Note: do NOT push the inner repos. They're local-only smoke-test trees.

## Step 6 — Unit tests

New file: `tests/unit/test_check_observability_gate.py`.

Tests to add:

1. **`test_gate_passes_on_200`** — mock `urllib.request.urlopen` to return a context-manager yielding nothing (success). Construct a minimal `ProjectContext` with an infra carrying `observability_backend_url`. Assert the gate adds a passing `observability_backend_reachable` result.

2. **`test_gate_passes_on_4xx_via_HTTPError`** — mock `urlopen` to raise `urllib.error.HTTPError(url, 401, "Unauthorized", hdrs={}, fp=None)`. Assert the gate passes with a detail mentioning `HTTP 401`.

3. **`test_gate_passes_on_404_via_HTTPError`** — same shape with `404`.

4. **`test_gate_fails_on_URLError`** — mock `urlopen` to raise `urllib.error.URLError("Name or service not known")`. Assert the gate fails with a detail naming the URL.

5. **`test_gate_fails_on_timeout`** — mock `urlopen` to raise `TimeoutError`. Assert the gate fails.

6. **`test_gate_fails_on_socket_timeout`** — same with `socket.timeout` (older Python; on 3.10+ socket.timeout is aliased to TimeoutError, but the catch clause defensively names both).

7. **`test_gate_skipped_without_infra`** — `ctx.infra is None`. Assert the gate adds a passing `observability_backend_reachable` result with detail `"no infra.yml — skipped"` and does NOT attempt any network call.

8. **`test_gate_uses_10s_timeout`** — verify the call passes `timeout=10` to `urlopen`. Use the mock's call_args.

The tests must mock `urlopen` rather than actually probe. Use `unittest.mock.patch("docex.pipeline.check.urllib.request.urlopen")` or similar. The existing `tests/unit/test_pipeline_check.py` has examples of `ProjectContext` construction the new tests can mirror.

## Step 7 — Update CHANGELOG.md for docex

`docex/CHANGELOG.md`. Under `[Unreleased]`, append to the existing `### Added` block:

```
- `docex check` now probes `observability_backend_url` for reachability
  before allowing a merge. Any HTTP response (including 4xx) confirms the
  host is up and TLS works; DNS failure, TLS failure, connection refusal,
  or timeout fails the gate. Mod 019.
```

## Step 8 — Run the full test suite

```
python3 -m pytest tests/unit -q
```

All unit tests should pass. The new `test_check_observability_gate.py` tests run with mocked `urlopen` — no network access required.

If a test fails, STOP and report. Do not invent fixes outside this spec.

## What this implementation does NOT do

- Does not cut 0.11.0 (that's a separate step sequence after mod 019).
- Does not run the PRE_CUT_CHECKLIST walk (operator does the walk).
- Does not actually probe a real backend (tests use mocks; the real probe runs only when an operator invokes `docex check`).
- Does not update doctrine prose (operator already added cicd.md item #9 for the reachability probe).
- Does not push the inner repos to any remote.
- Does not modify `docex_version` in either smoke project's `project.yml` (that's step 7 of the cut, via `docex_install.sh`).
