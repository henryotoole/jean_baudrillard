# Mod 081 — Implementation steps

Self-contained guide. Modifying `docex` at `~/.claude/jean_baudrillard/docex`.
Read [`overview.md`](./overview.md) first. **Do not edit doctrine files or
`tables/`.**

## Context (current shapes)

- `src/docex/ssh/client.py` — `SSHClient` Protocol with only
  `run(host, key_path, command, *, user="deploy") -> int` (stdout inherits).
  `src/docex/ssh/subprocess_client.py` — `SubprocessSSHClient` (the sole
  ssh-subprocess chokepoint).
- `src/docex/pipeline/release.py::_release_fixed(ctx, *, env, ansible_runner,
  skip_migrations=False, dry_run=False)` — validates key + `infra/secrets/<env>.env`
  exist, ensures compiled, runs the playbook. `run_release` dispatches to it
  (fixed branch) and passes `ansible_runner`.
- `src/docex/__main__.py::_cmd_release` builds `aws` + tofu runners; `_cmd_rollback`
  builds `docker`/`git`/`aws`; `_make_ssh_client()` already exists.
- `src/docex/pipeline/rollback.py::run_rollback` recompiles at the target tag in
  a worktree and mirrors gitignored `infra/deploy_creds/<env>` +
  `infra/secrets/<env>.env` into the worktree (search for the mirror step), then
  calls `_release_fixed(worktree_ctx, ..., skip_migrations=True)`.
- `src/docex/emit/templates/playbook.yml.j2` — copies `.env` from
  `{{ playbook_dir }}/../../secrets/{{ env }}.env`. Migrate tasks carry
  `tags: [migrate]`.
- `src/docex/ansible/subprocess_runner.py::run_playbook` already supports
  `extra_vars: dict`.
- Mod 080: `orchestrate/aggregate.py` (`aggregate`, `ensure_tte`, `aggregate_path`,
  path helpers, `AggregationError`), `envfile.py` (`read_env_file`,
  `write_env_file`), `categories.minted_policies`. `aggregate(ctx, env=...)`
  currently raises for non-dev/test.
- Host/user/key: host = `compiled.subdomain` = `f"{env}.{dns_label(project)}.{apex_domain}"`
  (see `up.py` ~line 253-256 for the exact inline form); user `deploy`; key
  `infra/deploy_creds/<env>`.

## Step 1 — `SSHClient.capture`

Add to the Protocol (`ssh/client.py`):

```python
    def capture(
        self, host: str, key_path: Path, command: str, *, user: str = "deploy",
    ) -> tuple[int, str]:
        """Run ``command`` over SSH and return (exit_code, stdout). stderr
        inherits (so auth/host-key errors stay visible). Used to read a small
        remote file (the host TTE store) into docex. 255 = SSH connection
        failure."""
        ...
```

Implement in `SubprocessSSHClient` (same arg/-o flags as `run`, but
`subprocess.run(args, check=False, stdout=subprocess.PIPE, text=True)`; return
`(res.returncode, res.stdout or "")`; on `FileNotFoundError` return `(127, "")`).

## Step 2 — fixed stage/prod aggregation (`orchestrate/aggregate.py`)

Add a fixed stage/prod path. Keep dev/test exactly as-is. Introduce:

```python
_STAGE_PROD = ("stage", "prod")
_HOST_DEPLOY_ROOT = "/opt/{project}/{env}"   # host paths

def _host_for(ctx, env) -> str:
    from docex.naming import dns_label
    apex = ctx.infra.apex_domain
    return f"{env}.{dns_label(ctx.project.name)}.{apex}"

def _staged_tte_path(ctx, env) -> Path:
    return ctx.project_root / ".docex" / "agg" / f"{env}.tte.env"

def ensure_tte_fixed(ctx, *, env, ssh, key) -> dict[str, str]:
    """Read the HOST tte.env (authoritative), mint missing minted keys, stage
    the superset to .docex/agg/<env>.tte.env. Returns the current minted map."""
    host = _host_for(ctx, env)
    remote = _HOST_DEPLOY_ROOT.format(project=ctx.project.name, env=env) + "/tte.env"
    rc, out = ssh.capture(host, key, f"cat {remote} 2>/dev/null || true")
    if rc == 255:
        raise AggregationError(f"cannot reach host {host!r} to read the TTE store (ssh 255)")
    existing = _parse_env_text(out)          # reuse envfile parsing on a string (see note)
    policies = minted_policies(ctx.infra, ctx.transfer_tables)
    updated = dict(existing)
    for k, policy in policies.items():
        if k not in updated:
            updated[k] = generate(policy)
    write_env_file(_staged_tte_path(ctx, env), updated,
                   header=["docex TTE store (host-authoritative superset).",
                           "Rendered to /opt/<project>/<env>/tte.env by the playbook."])
    return {k: updated[k] for k in policies}
```

Add a small `parse_env_text(text: str) -> dict` to `envfile.py` (factor the line
loop out of `read_env_file`, or add a sibling) so the SSH-captured string can be
parsed without a temp file. `read_env_file` becomes
`parse_env_text(path.read_text())` when the file exists.

Then the fixed-prod aggregate:

```python
def aggregate_fixed_prod(ctx, *, env, ssh, key) -> tuple[Path, Path]:
    """Returns (aggregate_path, staged_tte_path). ensure_tte_fixed reads the
    host store; the caller hands both files to ansible to render onto the host."""
    tte = ensure_tte_fixed(ctx, env=env, ssh=ssh, key=key)
    secrets = read_env_file(_secrets_path(ctx, env))
    config = read_env_file(_config_path(ctx, env))
    merged = _disjoint_union(tte, secrets, config)   # factor the union+collision guard out of dev/test aggregate
    out = aggregate_path(ctx, env)
    write_env_file(out, merged, header=[...])
    return out, _staged_tte_path(ctx, env)
```

Factor the disjoint-union-with-collision-guard into a private `_disjoint_union`
used by both dev/test and fixed paths (DRY).

Keep the dispatcher `aggregate(ctx, *, env)` for dev/test; the fixed-prod entry
is a distinct function called by `_release_fixed` (it needs the ssh/key
transports and returns two paths). Do NOT make dev/test require ssh.

## Step 3 — wire `_release_fixed` (`pipeline/release.py`)

- Add `ssh: SSHClient` parameter to `_release_fixed` (import the Protocol).
- After `ensure_compiled(ctx)` and the key/secrets checks, when NOT `dry_run`:
  build `agg_file, tte_file = aggregate_fixed_prod(ctx, env=env, ssh=ssh, key=private_key)`.
  (Under `dry_run`, skip aggregation — `ansible --check` shouldn't mint/push;
  mirror the elastic dry-run's side-effect-free rule.)
- Pass both to the runner as `extra_vars={"agg_env_file": str(agg_file),
  "tte_store_file": str(tte_file)}` (merge with any existing extra_vars).
- `run_release` fixed branch: accept an `ssh` param and pass it through. The
  elastic branch ignores it.

## Step 4 — dispatcher + rollback threading

- `__main__._cmd_release`: build `ssh = _make_ssh_client()` and pass `ssh=ssh`
  to `run_release`.
- `run_release(ctx, *, env, ansible_runner, aws, tofu_init, tofu_apply, ssh=None)`
  — thread `ssh` to `_release_fixed`.
- `__main__._cmd_rollback`: build `ssh` and pass to `run_rollback`.
- `run_rollback(...)`: accept `ssh`; pass to `_release_fixed`. Add
  `infra/config/<env>.env` to the worktree **mirror step** (alongside
  `infra/secrets/<env>.env` and `infra/deploy_creds/<env>`) so the recompiled
  worktree release can read config. (The host tte.env is read over SSH, so no
  tte mirroring is needed.)

## Step 5 — playbook template (`emit/templates/playbook.yml.j2`)

- Change the "Render .env onto host" task `src` from the secrets path to
  `"{{ '{{' }} agg_env_file {{ '}}' }}"`.
- Add a task before it (or after the deploy-dir task) "Render TTE store onto host":
  `ansible.builtin.copy: { src: "{{ '{{' }} tte_store_file {{ '}}' }}", dest:
  "{{ '{{' }} deploy_root {{ '}}' }}/tte.env", mode: "0600" }`.
- These two copy tasks are untagged, so `docex migrate --tags migrate` skips
  them and never renders `agg_env_file`/`tte_store_file` (ansible renders task
  args lazily). Do NOT add `migrate` tags to them.
- No change to `emit/ansible.py` (it passes no vars for these; they arrive via
  `--extra-vars`). Confirm the emitter doesn't need the new vars in its render
  context — it doesn't (they're runtime extra-vars, not compile-time template
  fills).

## Step 6 — fixture cleanup (fixed stage/prod)

Strip engine-managed `POSTGRES_*` (and the never-real `POSTGRES_DB`/`POSTGRES_HOST`
placeholders) from the **fixed-foundation** stage/prod fixture secrets so the
release aggregate doesn't hit the disjointness collision guard:
- `tests/fixtures/sample_project/infra/secrets/stage.env`
- `tests/fixtures/sample_project/infra/secrets/prod.env`
- any fixed scheduler fixture stage/prod secrets present.

Leave a comment (mirror the dev/test fixture wording from Mod 080). Leave the
ELASTIC fixtures' stage/prod for Mod 082.

## Step 7 — tests (`tests/unit/`)

Use a **fake `SSHClient`** whose `capture` returns a canned host tte.env string
and a **fake ansible runner** that records its `extra_vars`.

1. `ensure_tte_fixed`: host store empty → mints `POSTGRES_PASSWORD`, stages it;
   host store already has `POSTGRES_PASSWORD=live` → preserves it (no re-mint),
   staged file contains `live`; ssh 255 → `AggregationError`.
2. `aggregate_fixed_prod`: staged aggregate = host-tte ∪ secrets ∪ config; a
   secrets/tte collision (fixture with `POSTGRES_PASSWORD` in secrets) raises.
3. `_release_fixed`: with the fakes, asserts `run_playbook` was called with
   `extra_vars` containing `agg_env_file` + `tte_store_file` pointing at the
   staged files; asserts `dry_run=True` does NOT aggregate (no ssh.capture call).
4. Playbook render (extend `test_ansible_emitter.py`): the emitted `playbook.yml`
   copies `.env` from `{{ agg_env_file }}` and has a `tte.env` copy task from
   `{{ tte_store_file }}`.
5. Rollback: assert the worktree mirror step now also copies
   `infra/config/<env>.env` (extend the existing rollback test's mirror
   assertions), and that `run_rollback` threads `ssh`.

Update any existing `_release_fixed` / `run_release` / `run_rollback` /
`_cmd_release` / `_cmd_rollback` test that broke on the new `ssh` parameter (grep
for `_release_fixed(`, `run_release(`, `run_rollback(`).

## Definition of done

- `python3 -m pytest -q` green (baseline after Mod 080 was 729 passed).
- A fixed release builds `.docex/agg/<env>.env` (aggregate) + `.docex/agg/<env>.tte.env`
  (host-superset store) and passes both to ansible as extra-vars; the playbook
  renders `.env` from the aggregate and `tte.env` from the store.
- `ensure_tte_fixed` never re-mints a key the host already has; ssh-unreachable
  fails loud.
- Rollback mirrors config into the worktree and threads ssh.
- No doctrine or `tables/` change. Report clearly that end-to-end fixed release
  is validated only by the (deferred) fixed smoke walk; unit tests mock SSH +
  ansible.
