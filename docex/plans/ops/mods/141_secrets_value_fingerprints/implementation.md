# Mod 141 — Implementation steps

Feature: value fingerprints for the value-blind `docex secrets` tooling. A
fingerprint is a short, salted, one-way hash of a secret value, safe to display,
for equality/drift comparison across environments. Scoped to the **secret**
category only.

Environment: `python` is NOT on PATH. Interpreter is `docex/.venv/bin/python`,
run from the `docex/` directory. Run test suites synchronously in the foreground
with a generous timeout.

Do **not** edit `docex/plans/advances/floating_todo/` or the repo-root
`RELEASING.md` — those are a concurrent operator's uncommitted WIP. Stage only
the paths listed at the end.

---

## Step 1 — `secretsmgmt/engine.py`: add the fingerprint primitive

File: `docex/src/docex/secretsmgmt/engine.py`.

Add `hashlib` to the stdlib imports at the top (alongside `getpass`, `json`,
`sys`).

Add a module-level helper after the `CONFIG_POLICY` definition (after line ~54):

```python
# Fingerprints are a value-blind equality/drift check, NOT a confidentiality
# guarantee. 8 hex chars over a project-name-derived (guessable) salt reveal no
# value directly, but a LOW-ENTROPY / placeholder secret is inherently
# dictionary-attackable from any hash of it. Use them to compare whether two
# envs hold the SAME value, never to prove a value is safe to disclose.
_FP_LEN = 8  # hex chars (32 bits) — enough to spot drift, far too short to
             # brute-force a high-entropy secret back out.


def _salt(ctx: ProjectContext) -> bytes:
    """Fixed, project-local, NON-secret salt. Project-local so a value
    fingerprints identically within one project (the whole point — cross-env
    equality) but differently across projects, defeating a global rainbow
    table of common tokens. Derived purely from the public project name, so it
    is stable and carries no confidential material."""
    return ("docex-secret-fingerprint:" + ctx.project.name).encode("utf-8")


def fingerprint(ctx: ProjectContext, value: str) -> str:
    """Short, salted, one-way fingerprint of a secret value, safe to display.

    ``hex(sha256(SALT || value))[:8]``. Equality/drift comparison only —
    reveals no value directly, but is NOT a confidentiality guarantee for a
    low-entropy value (see ``_FP_LEN``)."""
    digest = hashlib.sha256(_salt(ctx) + value.encode("utf-8")).hexdigest()
    return digest[:_FP_LEN]
```

Notes:
- `fingerprint` takes `ctx` so it can read the project name for the salt. Keep
  the signature `(ctx, value)`.
- Do not export a config path to this — it is only called for the secret
  category (see Steps 2–4).

## Step 2 — extend `status()` with an opt-in fingerprint

File: `docex/src/docex/secretsmgmt/engine.py`, function `status` (line ~114).

Add a keyword-only parameter `show_fingerprint: bool = False` to the signature:

```python
def status(
    ctx: ProjectContext, policy: CategoryPolicy, env: str, *,
    fmt: str = "text", show_fingerprint: bool = False,
) -> int:
```

Compute the fingerprint per row **only** for the secret category with the flag
on and a non-empty value. It is a hard invariant that a fingerprint is never
computed for the config category (config is value-visible; a hash there is
pointless and would muddy the value-blind guarantee). Add a small local:

```python
    fp_on = show_fingerprint and not policy.values_visible
```

- **JSON branch:** when `fp_on`, add `item["fingerprint"] = fingerprint(ctx, val)
  if val != "" else None` to each row dict. When `fp_on` is False, do not add the
  key at all (output byte-identical to today).
- **Text branch:** when `fp_on`, append a `FINGERPRINT` column. Render the
  fingerprint for a SET value, and **blank** for UNSET. Keep the existing
  columns and spacing; append the new column at the end of each line, e.g.:

  ```python
      for key, state, source, desc, val in rows:
          line = f"{key:<{width}}  {state:<5}  [{source}]  {desc}"
          if policy.values_visible and val != "":
              line += f"  = {val}"
          elif fp_on:
              line += f"  {fingerprint(ctx, val) if val != '' else ''}"
          print(line)
  ```

  (The `elif` is correct: `fp_on` is only ever true for the secret category,
  where `policy.values_visible` is False, so the value branch and the
  fingerprint branch are mutually exclusive.)

Update the `status` docstring to note the opt-in `--fingerprint` column and that
it is secret-category-only.

## Step 3 — add the `fingerprints` cross-env matrix op

File: `docex/src/docex/secretsmgmt/engine.py`. Add a new function (near
`status`, e.g. after it). It is **secret-only** — it takes no `policy` argument
and builds its own secret manifest.

```python
_MATRIX_ENVS = ("dev", "test", "stage", "prod")
_UNSET_CELL = "—"  # em dash — the one text sentinel for an unset cell


def fingerprints(ctx: ProjectContext, *, fmt: str = "text") -> int:
    """Cross-env fingerprint matrix for the SECRET category: one row per key,
    one column per env, each cell a fingerprint or the unset sentinel.

    The primary "did it propagate / has it drifted?" view. Value-blind:
    fingerprints carry no secret material. NOT a confidentiality guarantee for a
    low-entropy value (see ``fingerprint``)."""
    manifest = _manifest(ctx, SECRET_POLICY)
    # env -> {key: value}
    per_env = {
        env: read_env_file(_file(ctx, SECRET_POLICY, env)) for env in _MATRIX_ENVS
    }

    def cell(env: str, key: str) -> str | None:
        val = per_env[env].get(key, "")
        return fingerprint(ctx, val) if val != "" else None

    if fmt == "json":
        out = [
            {
                "key": e.key,
                "fingerprints": {env: cell(env, e.key) for env in _MATRIX_ENVS},
            }
            for e in manifest
        ]
        print(json.dumps(out, indent=2))
        return 0

    key_w = max((len(e.key) for e in manifest), default=3)
    col_w = max(len("dev"), _FP_LEN)  # each env column at least fp-wide
    header = f"{'KEY':<{key_w}}  " + "  ".join(f"{env:<{col_w}}" for env in _MATRIX_ENVS)
    print(header)
    for e in manifest:
        cells = [
            (cell(e.key, env) if False else None)  # placeholder — see below
            for env in _MATRIX_ENVS
        ]
        # build cells correctly:
        rendered = []
        for env in _MATRIX_ENVS:
            fp = cell(env, e.key)
            rendered.append(f"{(fp if fp is not None else _UNSET_CELL):<{col_w}}")
        print(f"{e.key:<{key_w}}  " + "  ".join(rendered))
    return 0
```

Clean the function up when you write it (drop the placeholder comment line — it
is only there to flag that the JSON path uses `None`/`null` while the text path
uses the em-dash sentinel). The essential contract:
- **text:** unset cell → em dash `—`; set cell → 8-hex fingerprint.
- **json:** unset cell → `null`; set cell → the fingerprint string. Shape is a
  list of `{"key": ..., "fingerprints": {env: fp_or_null}}`.

## Step 4 — `copy_key`: print source + destination fingerprints (secret only)

File: `docex/src/docex/secretsmgmt/engine.py`, function `copy_key` (line ~219).

After the existing success `print(...)` line, add a value-blind confirmation of
the transfer for the **secret** category only (config is already value-visible,
so this adds nothing there):

```python
    if not policy.values_visible:
        # Value-blind confirmation the transfer landed: identical fingerprints
        # prove src and tgt now hold the same value, without revealing it.
        fp = fingerprint(ctx, src_val)
        print(f"  fingerprint {src_env}={fp}  {tgt_env}={fp}")
```

(Source and destination necessarily share a fingerprint after the copy, since
the target now holds `src_val`; printing both mirrors the matrix view and reads
naturally.)

## Step 5 — export the new function

File: `docex/src/docex/secretsmgmt/__init__.py`.

Add `fingerprint` and `fingerprints` to the imports from
`docex.secretsmgmt.engine` and to `__all__`.

## Step 6 — wire the CLI surface

File: `docex/src/docex/__main__.py`, function `_cmd_secrets` (line ~701).

1. On the `status` subparser (`p_status`), add:
   ```python
   p_status.add_argument(
       "--fingerprint", action="store_true",
       help="add a salted, non-revealing FINGERPRINT column for equality/drift "
            "comparison (secret category only; not a confidentiality guarantee "
            "for a low-entropy value)")
   ```
2. Add a new `fingerprints` subparser:
   ```python
   p_fp = sub.add_parser(
       "fingerprints",
       help="cross-env matrix of non-revealing value fingerprints (drift check)")
   p_fp.add_argument("--format", default="text", choices=["text", "json"])
   ```
3. Import `fingerprints` in the `from docex.secretsmgmt import (...)` block.
4. Dispatch:
   - update the `status` dispatch to pass the flag:
     ```python
     if ns.op == "status":
         return status(ctx, SECRET_POLICY, ns.env, fmt=ns.format,
                       show_fingerprint=ns.fingerprint)
     ```
   - add before the final `return 64`:
     ```python
     if ns.op == "fingerprints":
         return fingerprints(ctx, fmt=ns.format)
     ```
5. Update the `_cmd_secrets` docstring's subcommand list to include
   `fingerprints` and the `--fingerprint` flag.

Do **not** touch `_cmd_config`. The `fingerprints` op and `--fingerprint` flag
are secret-only.

## Step 7 — doctrine edits (surgical)

### 7a. `doctrine/infrastructure/configurable.md § Secrets`

The ops table currently ends with the `copy` row (line ~64). Add a
`fingerprints` row **after** the `copy` row, and update the `status` row to note
the `--fingerprint` flag. Then add one caveat sentence after the table.

Change the `status` row from:
```
| `docex secrets status <env> [--format json]` | **redacted read** — per key: `SET`/`UNSET`, declaring codebase, description; **never the value** | agent freely |
```
to:
```
| `docex secrets status <env> [--format json] [--fingerprint]` | **redacted read** — per key: `SET`/`UNSET`, declaring codebase, description; **never the value**. `--fingerprint` adds a non-revealing value fingerprint column | agent freely |
```

Add this row directly after the `copy` row:
```
| `docex secrets fingerprints [--format json]` | **cross-env fingerprint matrix** — one row per key, one column per env; each cell a salted, non-revealing fingerprint of the value (or unset). Compares propagation/drift across envs | agent freely |
```

After the table (before the "The `./bin/docex secrets ...`" paragraph that
already precedes it — i.e. insert immediately below the table), add:
```
A **fingerprint** is `hex(sha256(SALT || value))[:8]` under a fixed,
project-local, **non-secret** salt derived from the project name — safe to
display, stable within a project, and comparable across its environments. It
lets a value-blind caller confirm two envs hold the *same* value, or detect
drift, without ever reading the value. It is an **equality/drift check, not a
confidentiality guarantee**: it reveals no value directly, but a low-entropy or
placeholder secret is inherently guessable from any hash of it.
```

### 7b. `doctrine/infrastructure/docex.md` `### secrets`

Add a `fingerprints` invocation line to the command block (lines ~118-121) and
update the `status` line to show `[--fingerprint]`:

Change:
```
`./bin/docex secrets status <env> [--format json]`
```
to:
```
`./bin/docex secrets status <env> [--format json] [--fingerprint]`
```

Add after the `copy` invocation line (after line ~121):
```
`./bin/docex secrets fingerprints [--format json]`
```

Then add a new bullet after the existing `copy` bullet (after line ~128):
```
- **`fingerprints`** prints a cross-env matrix of non-revealing value
  fingerprints — one row per key, one column per env — the primary
  "did it propagate / has it drifted?" view. A fingerprint is
  `hex(sha256(SALT || value))[:8]` under a fixed, project-local, non-secret
  salt (derived from the project name); `status --fingerprint` adds the same
  fingerprint as a per-key column. It is an **equality/drift check, not a
  confidentiality guarantee**: it reveals no value directly, but a low-entropy
  or placeholder secret is inherently guessable from any hash of it. Secret
  category only.
```

## Step 8 — core doc drift: `masterplan.md`

File: `docex/plans/core/masterplan.md`, the Subcommand Surface table row for
`secrets` (line ~109).

Change:
```
| `secrets <scaffold\|status\|set\|copy> <env>` | both | `infra.yml` + transfer tables (via `secret_manifest`), `infra/secrets/<env>.env` | `infra/secrets/<env>.env` (value-blind: `set` reads a no-echo tty prompt or `--from-file`; `status` never prints a value) |
```
to:
```
| `secrets <scaffold\|status\|set\|copy\|fingerprints> <env>` | both | `infra.yml` + transfer tables (via `secret_manifest`), `infra/secrets/<env>.env` | `infra/secrets/<env>.env` (value-blind: `set` reads a no-echo tty prompt or `--from-file`; `status` never prints a value; `status --fingerprint` / `fingerprints` show non-revealing value fingerprints for cross-env drift) |
```

(`fingerprints` is envless, but the table row is a family summary; listing it in
the op set and describing it in the effect column is the correct granularity.)

Do not touch any other core doc — `compiler.md`, `release_flow.md`,
`docex_process.md` mentions of `secrets` are about scaffold/status/release
guards and are unaffected.

## Step 9 — tests

File: `docex/tests/unit/test_secretsmgmt.py`. Add a new section at the end.
Reuse the existing `_ctx`, `_secrets_file`, `_config_file` helpers. The
`_INFRA` fixture already yields `TELEMETRY_API_KEY` (doctrine) + `STRIPE_KEY`
(api) as secret keys.

Import `fingerprint` and `fingerprints` at the top alongside the existing
imports.

Add these tests (names indicative):

1. `test_fingerprint_is_stable` — `fingerprint(ctx, "abc") == fingerprint(ctx,
   "abc")`, and it is 8 lowercase-hex chars.
2. `test_fingerprint_differs_for_different_values` — different values → different
   fingerprints.
3. `test_fingerprint_salt_varies_by_project` — build a second ctx with a
   different `project.name` (e.g. `_ctx(tmp_path)` vs one with
   `ProjectManifest(name="other", ...)`); assert `fingerprint(ctx1, "abc") !=
   fingerprint(ctx2, "abc")`.
4. `test_status_fingerprint_column_set_and_unset` — set `STRIPE_KEY`; call
   `status(ctx, SECRET_POLICY, "dev", fmt="text", show_fingerprint=True)`;
   assert the STRIPE fingerprint string appears, `TELEMETRY_API_KEY` shows as
   UNSET with no fingerprint, and the raw value does not appear.
5. `test_status_fingerprint_json_shape` — same with `fmt="json"`; the STRIPE row
   has `"fingerprint"` == the expected value, the UNSET row has
   `"fingerprint": null`, and the raw value is absent from the output.
6. `test_status_without_flag_has_no_fingerprint_field` — `fmt="json"` and
   `show_fingerprint=False`: no `"fingerprint"` key in any row (byte-compatible
   default).
7. `test_status_config_never_fingerprints` — call `status(ctx, CONFIG_POLICY,
   "dev", fmt="json", show_fingerprint=True)` with `PARTNER_URL` set; assert no
   `"fingerprint"` key appears (secret-only invariant even if the flag is
   forced on).
8. `test_fingerprints_matrix_text_shape` — set `STRIPE_KEY` in `dev` and `test`
   (same value) and leave `stage`/`prod` unset; call `fingerprints(ctx,
   fmt="text")`; assert the header has `dev test stage prod`, the STRIPE row's
   dev and test cells are equal 8-hex fingerprints, the stage/prod cells are the
   `—` sentinel, and the raw value does not appear.
9. `test_fingerprints_matrix_json_shape` — same setup, `fmt="json"`: shape is a
   list of `{"key", "fingerprints": {dev,test,stage,prod}}`; dev==test
   fingerprint, stage/prod are `null`, raw value absent.
10. `test_fingerprints_drift_detectable` — set `STRIPE_KEY` to different values
    in `dev` vs `stage`; assert their cells differ in the matrix (JSON is
    easiest to assert on).
11. `test_copy_prints_fingerprints_secret` — set `STRIPE_KEY` in `dev`, copy
    `dev`→`test`; assert the captured stdout contains a `fingerprint` line with
    matching `dev=`/`test=` fingerprints and no raw value.
12. `test_no_secret_value_leaks_in_fingerprint_surfaces` — the value-blind
    guarantee: put a distinctive value (e.g. `"sk_LEAK_CANARY_9f"`) in several
    envs, then assert it appears in **none** of: `status --fingerprint` text,
    `status --fingerprint` json, `fingerprints` text, `fingerprints` json, and
    the `copy` confirmation output.

Use `capsys` to capture stdout for the CLI-shaped assertions, matching the
existing tests' style.

## Step 10 — run the suites (foreground, timeout 600000)

From `docex/`:

```
.venv/bin/python -m pytest tests -q
.venv/bin/python -m pytest tests -q -m integration
```

Expected: default suite = previous baseline **+ the new tests**, all passing,
21 deselected; integration = 21 passed, everything else deselected. Nothing red.

Then from the **repo root**, run `linkcheck` and confirm green (a BROKEN FILE in
`RELEASING.md` or under `floating_todo/` is the operator's concurrent WIP — report
it but do not touch it; it is not part of this mod).

## Paths this mod may stage (explicit `git add` each — never `-A`/`.`)

- `docex/src/docex/secretsmgmt/engine.py`
- `docex/src/docex/secretsmgmt/__init__.py`
- `docex/src/docex/__main__.py`
- `docex/tests/unit/test_secretsmgmt.py`
- `doctrine/infrastructure/configurable.md`
- `doctrine/infrastructure/docex.md`
- `docex/plans/core/masterplan.md`
- `docex/plans/modifications/141_secrets_value_fingerprints/overview.md`
- `docex/plans/modifications/141_secrets_value_fingerprints/implementation.md`
