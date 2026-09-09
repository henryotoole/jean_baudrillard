# Mod 092 — Implementation steps (code half)

Remove `example.env` from `docex` entirely. The doctrine half is already
committed. Read `overview.md` in this folder first. All paths are relative to
the docex project root (`~/.claude/jean_baudrillard/docex`).

**Guiding principle for tests:** every `example.env` assertion is really an
assertion about the **secret manifest** (`docex.cicl.categories.secret_manifest`,
which returns an ordered `list[ManifestEntry]`: doctrine-injected first, then
core services sorted, then backing services sorted). `example.env` was just a
rendered view of it. Repoint each test to assert on `secret_manifest` directly —
same invariant, no rendered file. Do NOT weaken or drop an invariant.

## Step 1 — `src/docex/emit/secrets.py`

1. **Delete the `emit_example_env` function entirely** (the `def
   emit_example_env(doc, tables, out_path)` at the bottom of the file).
2. **Keep `render_manifest_env` and `_group_header` unchanged** — `docex
   secrets/config scaffold` (`secretsmgmt/engine.py`) imports
   `render_manifest_env`.
3. **Remove now-unused imports** left by the deletion: `secret_manifest` (from
   the `from docex.cicl.categories import ManifestEntry, secret_manifest` line —
   keep `ManifestEntry`), `from docex.cicl.transfer import TransferTables`, and
   `from pathlib import Path`. Verify none are used elsewhere in the file before
   removing (they are not, at time of writing).
4. **Rewrite the module docstring** (currently "Emit
   ``infra/secrets/example.env``…"). New docstring should describe the file's
   surviving role: the shared grouped-`KEY=value` renderer
   (`render_manifest_env`) used by `docex secrets/config scaffold`. Do not
   mention `example.env`.

## Step 2 — `src/docex/cicl/compile.py`

1. Remove the import `from docex.emit.secrets import emit_example_env` (~line
   922).
2. Remove the emit block (~lines 1022-1026): the `# Always emit example.env.`
   comment, the `secrets_dir = …` / `secrets_dir.mkdir(…)` / `emit_example_env(…)`
   lines, and the accompanying `files_written += 1`. **Check the summary
   `print(...)` right after** (`f"Compiled … {files_written} files written"`) —
   dropping the increment keeps the count correct; leave the print otherwise
   intact. (If `secrets_dir` is used nowhere else after removal, it goes with the
   block.)
3. Module docstring (~line 12): remove the list item `3. Always emit
   infra/secrets/example.env.`
4. Comment (~lines 710-714): the core-`secrets:` wiring comment ends "… and
   surfaces it in example.env. Validation forbids a key in both env and
   secrets." Drop the `example.env` clause — reword to e.g. "… so the existing
   secret path delivers it — compose `${KEY}` (fixed) / ECS `secrets[]`
   (elastic). Validation forbids a key in both env and secrets."

## Step 3 — comment/string touch-ups in other source files

- `src/docex/cicl/categories.py` (~line 43): the `secret_manifest` docstring says
  "single source of truth for ``example.env``, ``secrets scaffold``, and …".
  Drop `example.env`; it is now the source of truth for `secrets scaffold` /
  `status` and the mod-091 required-secret guard.
- `src/docex/cicl/model.py` (~line 88): comment "Surfaced in example.env and
  wired into …" → "Surfaced via `docex secrets scaffold` and wired into …".
- `src/docex/cicl/validate.py`:
  - ~line 722 (comment): "surfaced in example.env — a project must not declare" →
    drop the `example.env` phrasing.
  - ~line 731 (**user-facing error string**): "it is surfaced in example.env and
    filled by the operator" → "it is surfaced by `docex secrets scaffold`/`status`
    and filled by the operator". Keep the rest of the message intact.

## Step 4 — tests

Run `grep -rn "example\.env\|emit_example_env" tests` first to get the live line
numbers; then:

- **`tests/unit/test_telemetry.py`** — remove `from docex.emit.secrets import
  emit_example_env`. The two tests that call it
  (`test_example_env_contains_telemetry_api_key`,
  `test_example_env_telemetry_key_position`) must be rewritten to assert on
  `secret_manifest(doc, tables)` instead:
  - "contains telemetry key" → assert a `ManifestEntry` with
    `key == "TELEMETRY_API_KEY"` and `source == "doctrine"` is present.
  - "telemetry key position" → assert the `TELEMETRY_API_KEY` entry's index in
    the manifest list is before the core service's own secret key
    (`API_KEY`) — the doctrine-injected-first ordering invariant, checked at the
    manifest level rather than the rendered-file level. Keep the fixture edit
    that adds the core `secrets:` block. Fix the module docstring / section
    comment that mention `example.env`.
- **`tests/unit/test_config_block.py`** — `test_config_key_absent_from_example_env`
  reads `example.env` and asserts a `config:` key is absent. Repoint to
  `secret_manifest`: the config key must not appear in
  `{e.key for e in secret_manifest(doc, tables)}`. Rename to
  `test_config_key_absent_from_secret_manifest`. Fix the module docstring line
  ("never leaks into example.env" → "never leaks into the secret manifest").
- **`tests/integration/test_compile.py`**:
  - Remove the `# example.env is always emitted.` assertion (~56-57).
  - Remove `"infra/secrets/example.env"` from the expected-outputs list (~309).
  - `test_example_env_excludes_postgres_keys` (~445): if the "postgres
    minted/fixed keys are excluded from the secret manifest" invariant is
    already covered by a unit test (check `test_categories.py` /
    `test_config_block.py`), **delete** this test; otherwise repoint it to assert
    on `secret_manifest`. State which you did in your report.
  - `test_core_secret_in_example_env_and_compose` (~490): keep the **compose**
    half (the core `secrets:` key surfaces as a compose runtime ref). Replace the
    `example.env` half with a `secret_manifest` membership assertion (or drop it
    if redundant). Rename away from `example_env`.
- **`tests/unit/test_categories.py`** (~158): comment only — drop `example.env`.
- **`tests/fixtures/sample_project/README.md`** (~34): the sentence "The Phase 1
  compiler writes `infra/secrets/example.env` automatically; …" is stale —
  rewrite to reflect that secret keys are reconciled via `docex secrets scaffold
  <env>` (or remove the sentence).

## Step 5 — verify

```
cd ~/.claude/jean_baudrillard/docex
grep -rn "example\.env\|emit_example_env" src tests   # expect: no matches
python3 -m pytest -q                                   # full suite green
```

The grep must come back empty across `src` and `tests` (the egg-info under
`src/docex.egg-info/` is generated — ignore it if it still matches; do not
hand-edit it).

## Out of scope / do not do

- Do NOT touch `docex/plans/core/*` (design agent updates those post-impl).
- Do NOT bump the version or edit CHANGELOG.
- Do NOT remove or alter `render_manifest_env` or `secret_manifest`.
- Do NOT hand-edit the smoke `test_projects/` (walk-time cleanup).
- Do NOT commit — leave changes unstaged for review.
