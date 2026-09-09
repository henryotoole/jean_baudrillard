# Mod 083 — Implementation steps

Self-contained guide. Modifying `docex` at `~/.claude/jean_baudrillard/docex`.
Read [`overview.md`](./overview.md) first. **Do not edit doctrine files or
`tables/`.**

## Context (current shapes)

- `cicl/categories.py` (Mod 078): `classify_source_keys`, `Category`,
  `DOCTRINE_INJECTED_SECRETS = frozenset({"TELEMETRY_API_KEY"})`,
  `minted_policies` (Mod 080). `EngineEntry.env: dict[str, EnvVarSpec]`
  (`.kind`, `.desc`).
- `emit/secrets.py::emit_example_env(doc, tables, out_path)` — currently walks
  core `secrets:` + backing `kind:secret` env vars + a hardcoded
  `TELEMETRY_API_KEY` block, grouped by service with `#` desc comments.
- `envfile.py` (Mod 080): `read_env_file`, `write_env_file`, `parse_env_text`.
- `__main__.py`: flat handler table + `_HELP_TEXT` + `_GROUPS`; each `_cmd_*`
  builds its own `argparse`. `load_project_context(Path.cwd())` yields `ctx`
  (`.infra`, `.transfer_tables`, `.project`, `.project_root`).
- `bin/docex` shim: builds `RUN_FLAGS`, runs `docker run` (no `-it`).

## Step 1 — `secret_manifest` + refactor `emit_example_env`

In `cicl/categories.py` add:

```python
@dataclass(frozen=True)
class SecretEntry:
    key: str
    desc: str
    source: str   # declaring service name, or "doctrine"

# desc + source for each doctrine-injected secret (single source of truth;
# replaces emit/secrets.py's hardcoded TELEMETRY_API_KEY comment).
_DOCTRINE_INJECTED_SECRET_META: dict[str, tuple[str, str]] = {
    "TELEMETRY_API_KEY": (
        "doctrine",
        "The OTel collector sidecar's auth key against observability_backend_url. "
        "Required in stage/prod; dev/test sidecars use the debug exporter and ignore it.",
    ),
}

def secret_manifest(doc, tables) -> list[SecretEntry]:
    """Every required secret: key + description + declaring source. The single
    source of truth for `example.env`, `secrets scaffold`, and `secrets status`.
    Order: doctrine-injected first, then core services (sorted), then backing
    services (sorted). A key shared across services keeps its first source +
    desc (dedup)."""
    out: list[SecretEntry] = []
    seen: set[str] = set()
    def add(key, desc, source):
        if key in seen: return
        seen.add(key); out.append(SecretEntry(key, desc, source))
    for key in sorted(DOCTRINE_INJECTED_SECRETS):
        src, desc = _DOCTRINE_INJECTED_SECRET_META.get(key, ("doctrine", ""))
        add(key, desc, src)
    for name in sorted(doc.core_services):
        for k, desc in sorted((doc.core_services[name].secrets or {}).items()):
            add(k, desc, name)
    for name in sorted(doc.backing_services):
        svc = doc.backing_services[name]
        cands = svc.engine if isinstance(svc.engine, list) else [svc.engine]
        for cand in cands:
            try: entry = tables.engine(svc.role, cand)
            except Exception: continue
            for k, spec in (entry.env or {}).items():
                if spec.kind == "secret":
                    add(k, spec.desc, name)
    return out
```

Refactor `emit_example_env` to build its key set from `secret_manifest(doc,
tables)` (keep the grouped-by-source rendering + `#` desc lines; the content is
the same keys). Remove the hardcoded `TELEMETRY_API_KEY` literal (now via the
manifest). Update `emit/secrets.py`'s imports accordingly. Preserve the header
comment. Keep `example.env` output stable enough that existing tests pass with
minimal adjustment (adjust ordering assertions if needed).

## Step 2 — `envfile.set_env_key`

Add to `envfile.py` a single-key, structure-preserving writer:

```python
def set_env_key(path: Path, key: str, value: str) -> None:
    """Set KEY=value in `path`, replacing the existing KEY= line in place (all
    other lines/comments preserved) or appending if absent. Creates the file
    (and parents) if missing. `key` must match [A-Z][A-Z0-9_]*."""
```

Implement: validate key; read existing text (or empty); split into lines; find
the first line whose pre-`=` token (stripped) == key and replace it with
`f"{key}={value}"`; if none, append. Write back (ensure trailing newline).

## Step 3 — `secretsmgmt/` engine (category-parametrized)

`src/docex/secretsmgmt/__init__.py` (exports) + `src/docex/secretsmgmt/engine.py`:

```python
@dataclass(frozen=True)
class CategoryPolicy:
    name: str            # "secret" | "config"
    subdir: str          # "secrets" | "config"
    values_visible: bool # status shows values (config) vs SET/UNSET (secret)
    set_positional_ok: bool  # `set` accepts a positional value (config only)

SECRET_POLICY = CategoryPolicy("secret", "secrets", values_visible=False, set_positional_ok=False)
```

Functions (all take `ctx`, `policy`, and use `ctx.infra`/`ctx.transfer_tables`):

- `_file(ctx, policy, env) -> Path` → `ctx.project_root/"infra"/policy.subdir/f"{env}.env"`.
- `_manifest(ctx, policy)` → `secret_manifest(...)` for secret; (Mod 084 adds
  config_manifest). For now, keyed on `policy.name`.
- `scaffold(ctx, policy, env) -> int`: manifest = required entries; existing =
  `read_env_file(file)`. Build new values dict = `{e.key: existing.get(e.key, "")
  for e in manifest}`. Report added (`key not in existing`), removed
  (`existing keys not in manifest`), preserved. Write the file grouped by source
  with `#` desc headers (reuse the example.env rendering style), values inline.
  Return an exit code (0). Print a summary (counts + removed key names).
  **Idempotent**: a second run makes no value changes.
- `status(ctx, policy, env, *, fmt="text") -> int`: for each manifest entry,
  state = `SET` if `file` has a non-empty value else `UNSET`. Text: aligned
  `KEY  SET/UNSET  [source]  desc`. `--format json`: list of
  `{key, state, source, desc}` (+ `value` ONLY if `policy.values_visible`).
  **Never** print the value when `not policy.values_visible`; **never** length/hash.
- `set_key(ctx, policy, env, key, *, value=None, from_file=None) -> int`:
  - Validate `key` is in the manifest (a declared key for this category) → else
    error "unknown <name> key {key}; run `docex <name> scaffold` / declare it".
  - Resolve the value:
    - if `from_file`: read the file's entire contents, **strip a single
      trailing newline only** (raw literal otherwise), use as value.
    - elif `value is not None` (positional): **only if `policy.set_positional_ok`**
      (config); for secret, reject with "secret values may not be passed as an
      argument; use an interactive prompt or --from-file".
    - else: **no-echo tty prompt** via `getpass.getpass(f"Value for {key}: ")`.
      If stdin is not a tty (`not sys.stdin.isatty()`), error clearly telling the
      operator to use `--from-file` (non-interactive).
  - `set_env_key(file, key, value)`. Print `set <KEY>` (redacted; no value) —
    for secret, never echo; for config, fine.
- `copy_key(ctx, policy, src_env, tgt_env, key) -> int`:
  - Refuse if `key in minted_policies(...)` → "cannot copy a TTE key {key}
    (minted per env, write-once)".
  - `src_val = read_env_file(src_file).get(key)`; if None/"" → error "{key} is
    unset in {src_env}".
  - **Same-side vs cross-side**: side(dev|test)="development", side(stage|prod)=
    "production". If `side(src) != side(tgt)`: print a WARNING to stderr
    (cross-side copy seeds one side from the other) but proceed.
  - `set_env_key(tgt_file, key, src_val)`; report `set`/`overwrote` (whether
    tgt had it) in redacted terms — never the value.

## Step 4 — `docex secrets` CLI (`__main__.py`)

Add `_cmd_secrets(args)`:
- First positional = subcommand ∈ {scaffold, status, set, copy}; dispatch to a
  per-subcommand `argparse`.
- `scaffold <env>`; `status <env> [--format text|json]`;
  `set <env> <KEY> [--from-file PATH]` (NO positional value for secrets);
  `copy <src_env> <tgt_env> <KEY>`. `env` choices ∈ {dev,test,stage,prod}.
- Load ctx, call the engine with `SECRET_POLICY`.
- Register `"secrets"` in `_HELP_TEXT` and a group (add a "Configuration" group,
  or append to an existing sensible group) and the handler table.

## Step 5 — shim tty (`bin/docex`)

After the `RUN_FLAGS=(...)` base array (and its `--group-add` additions), add:

```bash
# Allocate a tty when the caller has an interactive terminal, so commands that
# prompt with no echo (e.g. `docex secrets set`) can read a value the operator
# types. Skipped for non-interactive/piped runs, which must use --from-file.
# Additive + backward-compatible: an older image tolerates an extra -it.
if [[ -t 0 && -t 1 ]]; then
  RUN_FLAGS+=(-t -i)
fi
```

Also update the smoke-project copies of the shim in Mod 085 (they're byte
copies). This mod edits only `docex/bin/docex`.

## Step 6 — tests (`tests/unit/`)

1. `test_secret_manifest` (in `test_categories.py`): manifest for a project with
   a postgres backing + core secrets = `TELEMETRY_API_KEY` (source doctrine) +
   the core keys (source = service); dedup across services; POSTGRES_* absent
   (minted/fixed).
2. `test_envfile.py`: `set_env_key` replaces in place (other lines/comments
   preserved), appends when absent, creates the file, rejects a bad key.
3. `test_secretsmgmt.py` (new):
   - `scaffold`: adds missing keys empty, removes stale keys, preserves existing
     values; idempotent (2nd run no change).
   - `status`: SET/UNSET correct; text has no value; `--format json` has no
     `value` field under the secret policy; source/desc present.
   - `set_key`: `--from-file` sets the value; a positional value is REJECTED for
     the secret policy; a non-tty interactive attempt errors telling to use
     `--from-file`; setting an undeclared key errors. (Mock/monkeypatch
     `sys.stdin.isatty`/`getpass` to test the prompt branch.)
   - `copy_key`: same-side copy sets tgt; cross-side copy warns (capture stderr)
     but proceeds; unset source errors; a TTE key is refused; overwrites tgt by
     default.
4. `test_emit_example_env` (existing, wherever): still green after the
   manifest refactor (adjust ordering assertions if the manifest reorders).

(No shim unit test — bash; the shim change is covered by the smoke walk. Add a
one-line note in the mod report.)

## Definition of done

- `python3 -m pytest -q` green (baseline after Mod 082 was 749 passed).
- `docex secrets scaffold/status/set/copy` work per the ops table; a secret
  value is never printed and `set` never accepts a positional value.
- `secret_manifest` is the single source for `example.env` + the tooling.
- The shim allocates `-it` only on an interactive terminal.
- No `tables/` or doctrine change.
