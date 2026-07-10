# Mod 084 — Implementation steps

Self-contained guide. Modifying `docex` at `~/.claude/jean_baudrillard/docex`.
Read [`overview.md`](./overview.md) first. **Do not edit any file under
`~/.claude/jean_baudrillard/doctrine/` (including `docex.md`) or `tables/`.** The
`docex.md § config` section is added by the reviewing orchestrator, not you.

## Context (current shapes)

- `cicl/categories.py`: `SecretEntry(key, desc, source)`, `secret_manifest(doc,
  tables)`, `DOCTRINE_INJECTED_SECRETS`, `minted_policies`, `classify_source_keys`.
- `emit/secrets.py`: `render_manifest_env(doc, tables, *, prefix_lines, values)`
  — builds the **secret** manifest internally and renders `KEY=value` grouped by
  source; `emit_example_env` calls it (values all `""`).
- `secretsmgmt/engine.py` (Mod 083): `CategoryPolicy`, `SECRET_POLICY`,
  `_manifest(ctx, policy)` (only `"secret"` wired; raises for others), `scaffold`,
  `status`, `set_key`, `copy_key`. `scaffold` calls `render_manifest_env`.
  Imports `SecretEntry` from categories.
- `CoreService.config: dict[str, str]` (KEY→desc) exists (Mod 078).
- `__main__.py`: `_cmd_secrets` (Mod 083) + a "Configuration" help group;
  handler table; `_HELP_TEXT`.

## Step 1 — rename `SecretEntry → ManifestEntry` (`cicl/categories.py`)

Rename the dataclass and all references (`secret_manifest`'s return type, the
engine import, any test). It's a category-agnostic `(key, desc, source)`.

## Step 2 — `config_manifest` (`cicl/categories.py`)

```python
def config_manifest(doc, tables) -> list[ManifestEntry]:
    """Every declared config key: key + description + declaring core service.
    Config is core-service-declared only — no doctrine-injected, no backing
    engine vars. Source = the declaring service."""
    out, seen = [], set()
    for name in sorted(doc.core_services):
        for k, desc in sorted((doc.core_services[name].config or {}).items()):
            if k in seen: continue
            seen.add(k); out.append(ManifestEntry(k, desc, name))
    return out
```

(`tables` is unused but kept for signature symmetry with `secret_manifest` so
`_manifest` can call either uniformly.)

## Step 3 — `render_manifest_env` takes the manifest (`emit/secrets.py`)

Change the signature so the caller supplies the entries (fixes config scaffold
rendering secret keys):

```python
def render_manifest_env(entries, *, prefix_lines, values) -> str:
    """Render a grouped-by-source KEY=value env text from `entries`
    (list[ManifestEntry]). `values` maps key -> value (use "" for a keys-only
    manifest). Grouping/`#` desc comments unchanged."""
```

Drop the internal `secret_manifest(...)` call. Update:
- `emit_example_env(doc, tables, out_path)`: `entries = secret_manifest(doc,
  tables); ...render_manifest_env(entries, prefix_lines=..., values={e.key: ""
  for e in entries})`.
- `engine.scaffold`: `render_manifest_env(manifest, prefix_lines=prefix,
  values=new_values)` where `manifest = _manifest(ctx, policy)`.

Keep `example.env` output byte-stable (same entries, same grouping) so existing
tests pass.

## Step 4 — engine: config policy, manifest branch, `get_key`

`secretsmgmt/engine.py`:

```python
CONFIG_POLICY = CategoryPolicy("config", "config", values_visible=True, set_positional_ok=True)
```

`_manifest`: add the config branch:
```python
    if policy.name == "config":
        from docex.cicl.categories import config_manifest
        return config_manifest(ctx.infra, ctx.transfer_tables)
```
(keep the `"secret"` branch; drop the NotImplementedError once both are wired,
or leave a final raise for an unknown policy name.)

Add `get_key`:
```python
def get_key(ctx, policy, env, key) -> int:
    """Print one key's value. Config only — refuses when not
    policy.values_visible (secrets have no get; a value never goes to stdout)."""
    if not policy.values_visible:
        print(f"error: `get` is not available for {policy.name} "
              f"(values never printed)", file=sys.stderr)
        return 1
    val = read_env_file(_file(ctx, policy, env)).get(key)
    if val is None:
        print(f"error: {key} is not set in {env}", file=sys.stderr)
        return 1
    print(val)  # config is non-secret — printing is fine
    return 0
```

`set_key` already honors `set_positional_ok` (True for config → a positional
value is accepted). `status` already honors `values_visible` (config shows the
value column / json `value` field). No change to those beyond the manifest fix.

## Step 5 — `docex config` CLI (`__main__.py`)

Add `_cmd_config(args)` mirroring `_cmd_secrets` but with `CONFIG_POLICY` and:
- `scaffold <env>`;
- `status <env> [--format text|json]`;
- `set <env> <KEY> [value] [--from-file PATH]` — **positional `value` allowed**
  (nargs="?"); pass it to `set_key(value=ns.value, from_file=ns.from_file)`;
- `get <env> <KEY>` → `get_key`;
- `copy <src_env> <tgt_env> <KEY>`.
Register `"config"` in `_HELP_TEXT`, the "Configuration" group (next to
`secrets`), and the handler table.

Factor shared subcommand-dispatch with `_cmd_secrets` if it's clean, but a
parallel `_cmd_config` is fine (they differ in the `set` positional + the extra
`get`).

## Step 6 — tests (`tests/unit/`)

1. `test_categories.py`: `config_manifest` for a project with core `config:
   {PARTNER_URL: "..."}` → one entry (source = service); empty when no config
   declared; `ManifestEntry` rename doesn't break `secret_manifest` tests.
2. `test_secretsmgmt.py`:
   - config `scaffold` writes the CONFIG keys (not secret keys!) into
     `infra/config/<env>.env`, preserving values.
   - config `status` **shows values** (text value column + json `value` field).
   - config `set` **accepts a positional value** (and still supports
     `--from-file`); config `get` prints the value; `get` on the SECRET policy
     is refused.
   - config `copy` behaves like secret copy (same-side/cross-side/unset/TTE-refusal).
3. `test_emit_example_env` / compile tests: still green after the
   `render_manifest_env` signature change.

## Definition of done

- `python3 -m pytest -q` green (baseline after Mod 083 was 772 passed).
- `docex config scaffold/status/set/get/copy` work with inverted permissions
  (values visible, positional set OK, get prints); config scaffold renders
  config keys, not secret keys.
- `docex secrets` unchanged (still value-blind); `get` refused on secrets.
- No `tables/` or doctrine change (the `docex.md § config` section is the
  orchestrator's follow-up).
