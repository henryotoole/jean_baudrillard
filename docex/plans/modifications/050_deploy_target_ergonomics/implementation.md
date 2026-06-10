# Mod 050 — Implementation Steps

Fresh-context implementation guide for [`overview.md`](./overview.md). Two items: **Gap G** (preinfra SSH probe for target-host registry creds) and **Gap D** (a small `build.py` diagnostic; the gap's core is already closed by `up.py::_ensure_initial_dev_build`).

**Plan context that differs from a normal mod:** this mod feeds a *single* `1.1.0` minor cut at the end of mods 049–052. So **do NOT bump the version** (`pyproject.toml` / `__init__.py` stay at `1.0.3`); only append to `CHANGELOG.md`'s `[Unreleased]` section. **Do NOT** edit `plans/core/*` or the campaign file. **Do NOT** commit, tag, or `docker build`. Leave all changes uncommitted.

The doctrine changes for Gap G are **already done** (committed-pending: `doctrine/.../preinfra/container_registry.md` and `doctrine/.../specifics/release.md`) — do not touch doctrine.

Client-interface additions follow the established three-place pattern: Protocol in `src/docex/<area>/client.py`, concrete impl in `subprocess_client.py`, fake in `tests/conftest.py`.

---

## Step 1 — Gap G: preinfra SSH probe for target-host registry creds

### Why SSH (not a local file check)
`docex` runs as the operator user (shim `--user`). `/root/.docker/config.json` is under a mode-`700` `/root`, so a local `Path.is_file()` from a non-root process raises `PermissionError` traversing `/root` — it cannot tell "missing" from "unreadable". The reliable probe mirrors how release reaches the host: SSH as `deploy` via `infra/deploy_creds/<env>`, `sudo` for the root path. Reuses only existing creds/structure.

### 1a. New `SSHClient` (three-place)
- `src/docex/ssh/__init__.py` — new package.
- `src/docex/ssh/client.py` — `SSHClient` Protocol:
  ```python
  class SSHClient(Protocol):
      def run(self, host: str, key_path: Path, command: str, *, user: str = "deploy") -> int:
          """Run ``command`` on ``host`` over SSH as ``user`` using the
          private key at ``key_path``. Returns the remote exit code;
          255 is SSH's own connection-failure code (host unreachable /
          auth refused)."""
          ...
  ```
- `src/docex/ssh/subprocess_client.py` — `SubprocessSSHClient` implementing `run` via:
  ```
  ssh -i <key_path> -o BatchMode=yes -o StrictHostKeyChecking=accept-new \
      -o ConnectTimeout=10 <user>@<host> <command>
  ```
  Return the subprocess exit code (SSH surfaces the remote command's code, or 255 on connect failure). Mirror the style of `subprocess_client.py` in `git/`/`docker/` (a small `_run` helper if one fits).
- `tests/conftest.py` — `FakeSSHClient` with a configurable `results: dict[str, int]` keyed by host (default such that existing tests are unaffected — i.e. it's only injected where tests opt in). Add a constructor/attribute so a test can say "host X → exit 0, host Y → exit 1, host Z → 255".

### 1b. Thread `ssh` into `run_preinfra` (mirror the lazy-`aws` pattern)
- `src/docex/pipeline/preinfra.py` — add a keyword param `ssh: SSHClient | None = None` to `run_preinfra` (exactly parallel to `aws: AWSClient | None`).
- Add a new branch for **fixed + production**:
  ```python
  if (
      ctx.infra is not None
      and ctx.infra.foundation == "fixed"
      and side == "production"
  ):
      if ssh is None:
          failures.append(
              "fixed production side requires an SSH client but none "
              "was provided (this is a dispatcher bug)."
          )
      else:
          failures.extend(_check_fixed_registry_creds(ctx, ssh))
  ```
  (Defensive `None` guard mirrors the existing `aws is None` guard.)

### 1c. `_check_fixed_registry_creds`
```python
def _check_fixed_registry_creds(ctx: ProjectContext, ssh: SSHClient) -> list[str]:
    """Verify both deploy hosts carry the registry credential at the two
    paths the release playbook uses. Probes stage AND prod (the
    'production side' covers both); for a single shared fixed host the
    two probes harmlessly hit the same machine."""
```
For each `env in ("stage", "prod")`:
1. `key = ctx.project_root / "infra" / "deploy_creds" / env`. If not `key.is_file()` → append failure `f"infra/deploy_creds/{env} missing — needed to reach the {env} host to verify registry creds."` and `continue`.
2. Resolve host from `apex_domain` using `dns_label` (import from `docex.naming`):
   - `stage` → `f"stage.{dns_label(ctx.project.name)}.{ctx.infra.apex_domain}"`
   - `prod`  → `f"{dns_label(ctx.project.name)}.{ctx.infra.apex_domain}"` (the bare-project host, per `release.md § Inventory`)
3. One probe command:
   ```
   test -f /home/deploy/.docker/config.json && sudo -n test -f /root/.docker/config.json
   ```
   `rc = ssh.run(host, key, command)`  (`user="deploy"` default).
4. Interpret `rc`:
   - `0` → ok, no failure.
   - `255` → `f"could not reach {env} host {host!r} via infra/deploy_creds/{env} (SSH connect failed); cannot verify registry creds."`
   - else → `f"registry credentials not found on {env} host {host!r} (checked /home/deploy/.docker/config.json and /root/.docker/config.json). Run `docker login {registry}` as both `deploy` and `root` on the host."` where `registry = ctx.infra.container_registry` (fall back to `<registry>` if unset).

Return the accumulated list (caller extends `failures`).

### 1d. Dispatcher wiring
- `src/docex/__main__.py` — construct a `SubprocessSSHClient()` (stateless; cheap) and pass `ssh=` to the `run_preinfra` call sites that can reach **fixed production**: at minimum the user-facing `_cmd_preinfra` path and any release/projinfra **production** preflight call site. Development-side call sites may keep `ssh=None` (the branch won't use it). Grep all `run_preinfra(` call sites and pass `ssh` wherever `side` can be `"production"`.

### 1e. Tests
`tests/unit/test_pipeline_preinfra.py` — fixed-production cases with a `FakeSSHClient` and a tmp `infra/deploy_creds/{stage,prod}` present:
- Both hosts return `0` → no registry failures.
- A host returns non-zero (≠255) → the "registry credentials not found … run `docker login`" failure is enumerated.
- A host returns `255` → the "could not reach … host" failure.
- `infra/deploy_creds/prod` absent → the "missing … needed to reach" failure, and the probe for that env is skipped (no SSH call for it).
- Existing preinfra tests (development side, elastic production) must remain green — make sure adding the `ssh` param with a `None` default doesn't disturb them; pass a `FakeSSHClient` only where the fixed-production branch is exercised.

---

## Step 2 — Gap D: restarting-vs-absent diagnostic in `docex build`

`up.py::_ensure_initial_dev_build` already closes the core chicken-and-egg. The only residual: `build.py` keys off `compose_ps` (running-only), so a `Restarting` container yields a generic "not running" refusal.

- `src/docex/orchestrate/build.py` — at the per-service refusal in `_build_one` (the branch when the service isn't in the running set), consult `docker.compose_ps_status(compose_file, env_file=env_file)` (the method added in mod 049). If the service's compose key reports `restarting` or `unhealthy`, raise/print a clearer message, e.g.:
  > `dev container for service '<svc>' is restarting, not running — check `docker logs <name>`. `docex build` needs a healthy dev container; fix the crash (often a missing env var or a failed prior build) and retry.`
  Otherwise keep the existing "is not running; run 'docex up dev' first." message. **No behavior change to the success path**, and it still refuses (same exception type / non-zero) — only the message improves.
- Keep it tight: this is the "tiny diagnostic" decision, not the ephemeral-build/root-owned-dist path (explicitly out of scope).

### 2a. Tests
`tests/unit/test_orchestrate_build.py` (or the existing build test module) — `run_build`/`_build_one` where `compose_ps` does **not** list the target service but `compose_ps_status` reports it `restarting` → assert the restarting-specific message is produced (capture via `capsys`, or assert on the raised error's text). A second case: service genuinely absent (`compose_ps_status` lacks it) → the original "run 'docex up dev' first" message.

---

## Step 3 — CHANGELOG (no version bump)

Append to the existing `## [Unreleased]` section in `CHANGELOG.md` (do **not** create a version heading, do **not** touch `pyproject.toml` / `__init__.py`):
- **Added:** `SSHClient` (Protocol + subprocess impl) and the fixed-production registry-cred preinfra probe (Gap G).
- **Fixed:** `docex preinfra production` (fixed) now catches missing target-host registry creds before the release-time 401 (Gap G); `docex build` distinguishes a restarting dev container from an absent one (Gap D).

Place these under the same `### Added` / `### Fixed` subheads already present in `[Unreleased]` (mod 049's entries are there) — merge, don't duplicate the subheads.

---

## Step 4 — Run the test suite

From `docex/`:
```
pytest -q                 # unit — must pass
pytest -q -m integration  # integration — see note
```
The integration suite has a pre-existing, environment-specific failure (`test_stagetest_real`, sandbox DNS) and tests that need host docker networks created out-of-band; those are not caused by this mod. The **unit** suite is the gating artifact. Report exact counts and any new failures.

---

## Files expected to change

| File | Why |
| ---- | --- |
| `src/docex/ssh/__init__.py`, `client.py`, `subprocess_client.py` | new `SSHClient` (Gap G) |
| `src/docex/pipeline/preinfra.py` | `ssh` param + fixed-production branch + `_check_fixed_registry_creds` (Gap G) |
| `src/docex/__main__.py` | construct + inject `SubprocessSSHClient` at production-reaching `run_preinfra` call sites |
| `src/docex/orchestrate/build.py` | restarting-vs-absent diagnostic (Gap D) |
| `tests/conftest.py` | `FakeSSHClient` |
| `tests/unit/test_pipeline_preinfra.py` | Gap G tests |
| `tests/unit/test_orchestrate_build.py` | Gap D test |
| `CHANGELOG.md` | `[Unreleased]` entries (no version bump) |

Out of scope (do not implement): version bump, campaign-file edits, core-doc edits, ephemeral-build / root-owned-`dist/` handling, the remote-multi-host fixed SSH topology beyond what the single apex-derived host gives.
