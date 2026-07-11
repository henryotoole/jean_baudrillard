# Mod 091 — Implementation steps

Add a stage/prod release precondition that aborts if any **required secret** is
unset. Read `overview.md` in this folder first. Doctrine reference:
`doctrine/infrastructure/specifics/config_and_secrets.md § Required-Secret
Guard` (already written).

All paths below are relative to the docex project root
(`~/.claude/jean_baudrillard/docex`).

## Step 1 — New error type

In `src/docex/errors.py`, add a new `DocexError` subclass (place it near the
other release-path errors, e.g. just after `AnsibleRunFailed` or with the
Phase-4 elastic errors — anywhere in the `DocexError` family is fine):

```python
class RequiredSecretsUnset(DocexError):
    """A stage/prod release was attempted while one or more required secrets
    are unset (absent or empty) in infra/secrets/<env>.env. Raised as a
    precondition in run_release, before any side effect. See
    config_and_secrets.md § Required-Secret Guard."""

    def __init__(self, env: str, keys: list[str]) -> None:
        self.env = env
        self.keys = keys
        listing = "\n".join(f"  - {k}   (docex secrets set {env} {k})" for k in keys)
        super().__init__(
            f"release aborted — {len(keys)} required secret(s) unset for "
            f"{env!r}:\n{listing}\n"
            f"Set them (or run `docex secrets scaffold {env}` to reconcile the "
            f"key set first), then retry."
        )
```

`__main__.py` already renders any `DocexError` as a clean, traceback-free
message, so no dispatcher change is needed.

## Step 2 — Guard helper + wiring in `run_release`

In `src/docex/pipeline/release.py`:

1. Add `RequiredSecretsUnset` to the existing `from docex.errors import (...)`
   block.

2. Add a module-level helper (place it just above `run_release`):

```python
def _require_secrets_present(ctx: ProjectContext, env: str) -> None:
    """Abort a stage/prod release if a required secret is unset.

    Required secret = any key in the secret manifest (core `secrets:` +
    backing `kind: secret` + doctrine-injected). "Unset" = absent from
    infra/secrets/<env>.env or present with an empty value. TTE (docex-minted,
    put-if-absent) and config (non-secret) do NOT gate a release.
    See config_and_secrets.md § Required-Secret Guard.
    """
    from docex.cicl.categories import secret_manifest
    from docex.envfile import read_env_file

    manifest = secret_manifest(ctx.infra, ctx.transfer_tables)
    values = read_env_file(ctx.project_root / "infra" / "secrets" / f"{env}.env")
    unset = [e.key for e in manifest if values.get(e.key, "") == ""]
    if unset:
        raise RequiredSecretsUnset(env, unset)
```

   Use function-local imports for `secret_manifest` / `read_env_file` — this
   matches the existing style in `release.py` (e.g. the inline
   `from docex.orchestrate.aggregate import aggregate_fixed_prod`).

3. Call it in `run_release`, **after** the `infra is None` check and
   **immediately before** the `if infra.foundation == "elastic":` line:

```python
    if infra is None:
        print(...)   # existing block, unchanged
        return 1

    _require_secrets_present(ctx, env)   # <-- add this line

    if infra.foundation == "elastic":
        ...
```

   Do **not** touch `_release_fixed`, `_release_elastic`, or
   `pipeline/rollback.py`. Rollback deliberately bypasses this guard (it calls
   the branch functions directly). Verify `read_env_file` returns `{}` for a
   missing file (it does — `src/docex/envfile.py`), so an entirely-absent
   secrets file correctly reports every required key as unset.

## Step 3 — Unit tests

Add `tests/unit/test_release_secret_guard.py`. Test `_require_secrets_present`
directly (import it from `docex.pipeline.release`) — it is pure (local file read
+ raise), crosses no docker/AWS/git boundary, so **unit tests only** per
`docex_process.md`.

Build the `ProjectContext` the same way existing unit tests do. Look at
`tests/unit/test_config_block.py` and `tests/unit/test_categories.py` for the
established pattern of constructing a `CICLDocument` + `TransferTables` + a
tmp-path project root; reuse whatever helper/fixture they use rather than
inventing a new one. If those tests compile a real `infra.yml` fixture, mirror
that; the guard only needs `ctx.infra`, `ctx.transfer_tables`, and
`ctx.project_root`.

Cover these cases (a postgres backing service gives a `kind: minted`
`POSTGRES_PASSWORD` (TTE) for the negative-control case; a core `secrets:` key
and the doctrine-injected `TELEMETRY_API_KEY` give required secrets):

1. **All required secrets set (non-empty)** → no raise.
2. **A required core secret empty (`KEY=`)** → `RequiredSecretsUnset`, and the
   key appears in `exc.keys` / the message.
3. **A required core secret absent** (not in the file) → raised; listed.
4. **Secrets file entirely missing** → raised; all required keys listed.
5. **`TELEMETRY_API_KEY` unset** → raised (doctrine-injected counts as
   required).
6. **A TTE key (`POSTGRES_PASSWORD`) absent/empty** → **no raise** (TTE is not a
   required secret).
7. **A config key absent/empty** → **no raise** (config does not gate).

## Step 4 — Run tests

```
cd ~/.claude/jean_baudrillard/docex
python -m pytest tests/unit/test_release_secret_guard.py -q
python -m pytest -q      # full unit suite must stay green
```

Do not run `pytest -m integration` (no boundary crossed by this mod).

## Out of scope / do not do

- Do NOT update `docex/plans/core/*` (the design agent does that post-impl).
- Do NOT bump the version or edit CHANGELOG (handled in the cut/changelog step).
- Do NOT add the guard to rollback or to the `_release_*` branch functions.
- Do NOT add a compile-time check — the guard is release-only by design.
