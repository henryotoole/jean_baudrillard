# Mod 079 — Implementation steps

Self-contained guide. Modifying `docex` at `~/.claude/jean_baudrillard/docex`.
Read [`overview.md`](./overview.md) first. Paths relative to project root.
**Do not edit doctrine files, `tables/`, or `emit/`.** All changes are in
`src/docex/cicl/validate.py` + tests.

## Context (current `validate.py`)

- `validate_document(doc, tables)` calls a series of `_validate_*` helpers and
  aggregates `ValidationIssue`s. It already receives `tables`.
- `_validate_env_secrets_overlap(doc)` — checks `set(svc.env) & set(svc.secrets)`
  per core service, rule `rule_env_secrets_overlap`.
- `_validate_reserved_env_keys(doc)` — checks core `env:`/`secrets:` against
  `_RESERVED_CORE_ENV_KEYS = {PROJECT_VERSION, OTEL_SERVICE_NAME,
  OTEL_EXPORTER_OTLP_ENDPOINT, OTEL_EXPORTER_OTLP_PROTOCOL,
  OTEL_RESOURCE_ATTRIBUTES}`, rule `rule_reserved_env_key`.
- Mod 078 added `src/docex/cicl/categories.py`:
  `classify_source_keys(doc, tables) -> SourceKeyCategories` (`.conflicts() ->
  dict[key, list[Category]]`), `Category`, `DOCTRINE_INJECTED_SECRETS`
  (`frozenset({"TELEMETRY_API_KEY"})`).

## Step 1 — broaden rule 16 to three-way (`_validate_env_secrets_overlap`)

Rename to `_validate_env_secrets_config_overlap` (update the call site in
`validate_document`) and check all three pairwise overlaps per core service:

```python
def _validate_env_secrets_config_overlap(doc) -> list[ValidationIssue]:
    """Rule 16: a core service's env:, secrets:, config: don't share a key —
    each has distinct provenance/wiring, so a shared key is ambiguous."""
    issues = []
    for name, svc in sorted(doc.core_services.items()):
        blocks = {
            "env": set(svc.env or {}),
            "secrets": set(svc.secrets or {}),
            "config": set(getattr(svc, "config", {}) or {}),
        }
        for a, b in (("env", "secrets"), ("env", "config"), ("secrets", "config")):
            for key in sorted(blocks[a] & blocks[b]):
                issues.append(ValidationIssue(
                    rule="rule_env_secrets_config_overlap",
                    message=(f"core service {name!r}: key {key!r} appears in both "
                             f"`{a}:` and `{b}:` — declare it in exactly one"),
                    where=f"core_services.{name}",
                ))
    return issues
```

Keep the existing rule name? No — the doctrine rule is now three-way; a fresh
rule id `rule_env_secrets_config_overlap` is clearer. Update any test that
asserted `rule_env_secrets_overlap` (grep).

## Step 2 — reserved-key check across config + doctrine-injected secrets

Extend `_validate_reserved_env_keys(doc)`:

1. Add `"config"` to the `(source, block)` tuples it iterates, so `config:` is
   checked against `_RESERVED_CORE_ENV_KEYS` (the auto-injected core env vars)
   just like `env:`/`secrets:`. Keep the existing "docex auto-injects it on
   every core service" message for these.
2. Add a **second** check for the doctrine-injected *secret* set: import
   `DOCTRINE_INJECTED_SECRETS` from `docex.cicl.categories`; for each core
   service, across `env:`/`secrets:`/`config:`, a declared key in
   `DOCTRINE_INJECTED_SECRETS` is an error with a tailored message:

   ```python
   for key in sorted(block_keys & DOCTRINE_INJECTED_SECRETS):
       issues.append(ValidationIssue(
           rule="rule_doctrine_injected_key_reserved",
           message=(f"core service {name!r} declares {key!r} under `{source}:`. "
                    f"This is a doctrine-injected secret managed by docex — it is "
                    f"surfaced in example.env and filled by the operator; a project "
                    f"must not declare it. Remove the declaration. See "
                    f"config_and_secrets.md § Doctrine-Injected Secrets."),
           where=f"core_services.{name}.{source}",
       ))
   ```

   (Distinct rule id and message from the `PROJECT_VERSION`/`OTEL_*` case, whose
   "auto-injected on every core service" wording does not describe
   `TELEMETRY_API_KEY`.)

## Step 3 — new rule-20 disjointness validator

```python
def _validate_source_key_disjointness(doc, tables) -> list[ValidationIssue]:
    """Rule 20: the three value categories are disjoint project-wide by source
    key. Doctrine-injected keys are handled by the reserved-key check, so skip
    them here to avoid double-reporting."""
    from docex.cicl.categories import classify_source_keys, DOCTRINE_INJECTED_SECRETS
    issues = []
    cats = classify_source_keys(doc, tables)
    for key, categories in sorted(cats.conflicts().items()):
        if key in DOCTRINE_INJECTED_SECRETS:
            continue  # reserved-key check owns this diagnostic
        names = ", ".join(c.value for c in categories)
        issues.append(ValidationIssue(
            rule="rule_source_key_category_conflict",
            message=(f"source key {key!r} is claimed by multiple value categories "
                     f"({names}) — the categories must be disjoint (a key's "
                     f"provenance, value, and read/write permission would be "
                     f"ambiguous). Declare it in exactly one. See "
                     f"config_and_secrets.md § Collision rules."),
        ))
    return issues
```

Wire both changed/new validators into `validate_document`:
- replace `_validate_env_secrets_overlap(doc)` with
  `_validate_env_secrets_config_overlap(doc)`,
- add `issues.extend(_validate_source_key_disjointness(doc, tables))`.

## Step 4 — tests (`tests/unit/`, likely `test_validate.py`)

- **Rule 16:** a core service with the same key in `env:` and `config:` → one
  `rule_env_secrets_config_overlap` issue; same for secrets∩config; a clean
  project → none. (Keep/adjust the existing env∩secrets test.)
- **Rule 20:** a project where a core `config:` key equals a backing engine's
  minted TTE key (e.g. name a config key `POSTGRES_PASSWORD`) → a
  `rule_source_key_category_conflict` issue naming `tte` + `config`. A clean
  mixed project → none.
- **Doctrine-injected reserved:** a core service declaring `TELEMETRY_API_KEY`
  in `secrets:` (or `config:`, or `env:`) → a `rule_doctrine_injected_key_reserved`
  issue, and **no** `rule_source_key_category_conflict` for that key (ownership
  split — assert the disjointness rule did NOT also fire on it).
- **Config reserved auto-injected:** a core `config: {PROJECT_VERSION: "..."}` →
  the existing `rule_reserved_env_key` fires (now that config is checked).

Grep tests for `rule_env_secrets_overlap` and update to the new rule id / shape.

## Definition of done

- `python3 -m pytest -q` green (baseline after Mod 078 was 704 passed).
- A cross-category collision (e.g. config key == minted TTE key) fails compile
  with `rule_source_key_category_conflict`.
- Declaring `TELEMETRY_API_KEY` in any block fails with exactly one issue
  (`rule_doctrine_injected_key_reserved`), not two.
- Rule 16 catches env/secrets/config pairwise overlap.
- No `tables/`, `emit/`, or doctrine change.
