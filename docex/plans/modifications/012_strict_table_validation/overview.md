# Mod 012 — Strict transfer-table validation with descriptive failure messages

## Problem

Project-local transfer tables (`infra/transfer_tables/`) are about to become first-class load-bearing surface — Mods 013–015 add container-backing engines, EFS, and Service Connect, all of which projects will declare via project-local tables, and the campaign-end smoke walk authors clickhouse + sidecar engines as project-local entries. Before that, the loader's failure modes are dangerous:

1. **Silent drop of unknown top-level keys.** `transfer.py:347-354` merges only `roles` and `naming_policies`; any other top-level key in a project file is dropped without warning. A typo like `role:` (singular) parses cleanly and the table simply has no effect — the developer sees a downstream "unknown role" error from `validate.py`, not "you typed `role:` in `infra/transfer_tables/foo.yml`."

2. **Silent drop of unknown engine sub-keys.** `_parse_entry` in `transfer.py:313-332` uses `.get()` for every key it cares about. A typo like `defualts:` instead of `defaults:` parses with `defaults={}` and the entry has no effect on compiled output. Again, the developer sees a downstream effect — an HCL block missing fields — not a load-time error.

3. **Silent drop of unknown naming-policy sub-keys.** `naming.py::parse_policies` has the same shape: known keys read via `.get()`, unknowns ignored. A typo like `seperator:` (instead of `separator:`) triggers the existing "separator must be 'underscore' or 'hyphen' (got None)" check, which is OK but doesn't identify the typo as a typo.

4. **No emit-destination validation at load time.** `_parse_entry` validates the structural shape of `emits:` (foundation → list of strings) but not the destination values. `emits.elastic: [s3_buckets]` (plural typo) parses successfully; the failure surfaces later when the compiler tries to route to a non-existent destination. The doctrine claims rule 11 in `cicl.md § Validation Rules`: "Every destination name in those lists is one the compiler recognizes; unknown destination names fail compile at load time." That's documented behavior, but never implemented.

5. **No source attribution.** Every `TransferTableError` message names the role/engine but not the YAML file it came from. With both bundled and project-local tables, "engine 'nginx' has no foundation" doesn't tell the developer whether to fix their project file or report a bundled bug. The path information is available — `_read_yaml_files` already returns `(path, doc)` tuples — but the merge loop at `transfer.py:347` discards `_path`.

Each problem is small individually; together they make project-local authoring an exercise in trial-and-error against opaque downstream failures. Mod 012 fixes them as a coherent set.

## Design

The fix is **strict, descriptive load-time validation**, applied uniformly to bundled and project-local tables.

### Strict allowlists for every known shape

| Layer | Allowed keys | Source |
| ----- | ------------ | ------ |
| Document top level | `roles`, `naming_policies` | `transfer.py` |
| Role-level | `description`, plus engine names (free) | `transfer.py` |
| Engine entry | `foundation`, `default_port`, `emits`, `defaults`, `fields`, `provides`, `env`, `naming`, `reserved_names` | `transfer.py` |
| Naming policy entry | `separator`, `case`, `max_len` | `naming.py` |
| `emits.<foundation>` entries | values in `EMIT_DESTINATIONS[foundation]` | `transfer.py` |

Anything outside these sets is a hard error at load time, not a silent drop, not a downstream surprise.

The role layer (engine names + `description`) is the only layer where the allowlist isn't fully closed — engines are user-named. We accept this and reserve only `description` explicitly; everything else at the role level is treated as an engine (which then goes through engine-entry validation).

### Source attribution

`_read_yaml_files` already produces `(path, doc)` tuples. The change:

- Replace the merge-then-parse flow with a parse-then-merge flow. Each YAML file is independently validated (top-level keys, engine entries, policy entries) with its path threaded through. Errors carry the path.
- After validation, accumulate the validated structures into the merged `TransferTables` (engines + policies). Deep-merge semantics for engine bodies are preserved by merging the already-validated dicts at the role-engine level.

Bundled tables get attributed as `tables/roles/<file>.yml` (relative to the docex root) and project-local tables as `infra/transfer_tables/<file>.yml` (relative to the project root). The error prefix in each case is the relative path, since both are reachable from somewhere the developer knows.

### "Did you mean" hints for plausible typos

When an unknown key is rejected, compute a Levenshtein distance against the allowlist. If the closest match is within edit distance 2, include it as a suggestion:

```
infra/transfer_tables/foo.yml: unknown top-level key 'role' — did you mean 'roles'?
```

If no close match exists, list the full allowlist instead:

```
infra/transfer_tables/foo.yml: unknown top-level key 'unrelated_thing' — allowed: roles, naming_policies
```

Keep the implementation small — a 10-line Levenshtein function in a new `_did_you_mean` helper. No `python-Levenshtein` dependency.

### Error class

`TransferTableError` stays as-is structurally. The message format becomes consistent:

```
<source path>: <error description> [— did you mean <suggestion>?]
```

No new error class. `TransferTableError` already carries everything we need; we just produce better messages.

### What this mod does NOT do

- Does not change the merge semantics. Bundled-then-project-local deep merge, with project values overriding bundled values at every leaf, stays as documented.
- Does not change the engine schema. Adding `persistent_storage` (Mod 015) extends the allowlist in that mod, not here.
- Does not validate that `defaults.<foundation>` body keys are themselves "valid" — those are role/engine-specific and validated downstream when the compiler routes them to an emit destination. This mod is about table-shape correctness, not body-correctness.
- Does not validate magic refs against the table. That's `cicl/validate.py`'s job and already works (rule 7).

## Proposed doctrine edit

A new section in `doctrine/infrastructure/specifics/transfer_tables.md`, after "## Anatomy of a Role Definition" (around line 311, before "## Foundation Invariants"). Single subsection, 5-bullet list:

````markdown
## Failure-mode contract

Errors raised while loading transfer tables — bundled or project-local — are strict and self-describing. The compiler will not silently drop unknown shapes; every malformed entry must be surfaced at load time with enough information to fix it.

1. **Source attribution.** Every error names the YAML file from which the offending value was read (relative to the project root for project-local tables, relative to the docex source for bundled tables). A developer should be able to copy the path from the error and open the file immediately.

2. **Position attribution.** Where the position within the file is recoverable — top-level key, role name, engine name, policy name — the message names it explicitly.

3. **Suggestions on plausible typos.** Unknown keys within a short edit distance of a known key produce a "did you mean X?" hint. Where no close match exists, the full allowed-key list is included instead.

4. **No silent drop.** Unknown top-level keys, unknown engine sub-keys, unknown naming-policy sub-keys, and unknown emit destinations are hard errors at load time. The transfer-table surface is strict — anything outside the schema is rejected at load time, not at use time and not silently.

5. **Identical strictness across both layers.** The same rules apply to doctrine-bundled tables and project-local tables. A bug in a bundled table should fail the same way a bug in a project-local table does.

The full set of allowed keys at each layer is defined in `src/docex/cicl/transfer.py` (`_ALLOWED_*` constants) and in `src/docex/naming.py` (policy keys); they are the source of truth.
````

Also a small addition to `doctrine/infrastructure/cicl.md § Validation Rules` to call out that rules 11 and 15 are enforced at table load, not at compile (closing the documented-but-not-enforced gap for rule 11). Wording:

> Rules 11 and 15 are enforced at transfer-table load time, before any compilation begins. Rules 1–10 and 12–14 are enforced at compile time against the loaded tables and `infra.yml`.

These edits land first as a "Doctrine: …" commit before the mod design/impl commits, mirroring the pattern from Mod 011 (`a7ed926` doctrine commit preceded `d8d1339` design and `76938c4` impl).

## Five-artifact alignment

| Artifact | Change |
| -------- | ------ |
| `doctrine/.../*.md` | `transfer_tables.md`: new "Failure-mode contract" subsection. `cicl.md` § Validation Rules: short paragraph clarifying load-time vs. compile-time enforcement. |
| `docex/plans/core/*.md` | `compiler.md`: small update to the "Validation" subsection noting that transfer-table load-time validation is now strict (paths attributed, allowlists enforced, suggestions emitted). |
| `tables/*.yml` | No change — the canonical tables already conform to the schema this mod enforces. |
| `src/docex/**` | `cicl/transfer.py`: restructure to parse-then-merge with source attribution; add allowlist constants; add `_did_you_mean` helper; emit-destination value validation in `_parse_entry`. `naming.py`: strict key validation in `parse_policies` with source attribution. |
| `tests/**` | Unit tests, one per failure mode: (a) unknown top-level key; (b) unknown engine sub-key; (c) unknown naming-policy sub-key; (d) unknown emit destination; (e) source path appears in every error; (f) "did you mean" hints fire on within-edit-distance-2 typos; (g) full-list hint fires on unrelated unknowns. |

## Validation

1. `python3 -m pytest tests/unit/` — green, including all new tests.
2. `python3 -m pytest tests/integration/test_compile.py` — green (no semantic change; existing bundled tables conform).
3. Hand-construct a malformed project-local table fixture in `tests/fixtures/`, point a unit test at it, confirm the error message names the file and the typo.

## Decisions captured

1. **Strict allowlists over feature flags.** The transfer-table schema is closed. Extending it is a doctrine change (and a docex code change to update the allowlist). Future doctrine extensions add to the allowlist; they don't make it permissive.
2. **Parse-then-merge, not merge-then-parse.** Per-file validation gives source attribution for free; the deep-merge happens on already-validated structures so error attribution stays clean.
3. **`TransferTableError` reused, not subclassed.** A single error class with rich messages is simpler than a tree of subtypes the dispatcher would have to handle.
4. **Levenshtein-2 cutoff for "did you mean".** Tight enough to avoid noisy suggestions, loose enough to catch most authoring typos. No dependency — 10-line implementation.
5. **Identical strictness for bundled and project tables.** The doctrine prose calls this out explicitly. A bug in a bundled table should be surfaced the same way as a project-local bug.

## Open questions

None — design is fully derivable from existing patterns. Implementation is mechanical.
