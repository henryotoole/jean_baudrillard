# Mod 012 — Implementation Steps

Read `overview.md` in this folder first. Fresh context. Work through the steps in order. Run tests. Leave everything uncommitted.

## Scope

Make transfer-table loading strict and source-attributed. Hard-error on every unknown top-level key, unknown engine sub-key, unknown naming-policy sub-key, and unknown emit-destination value. Every error names the source YAML file. Plausible typos get "did you mean X?" hints.

No semantic change to existing well-formed tables — bundled tables and any conforming project-local table compile identically before and after. Only the failure modes change.

The doctrine edits for this mod are already landed (in `transfer_tables.md` and `cicl.md`). No further doctrine edits.

## Step 1 — Allowlist constants

File: `src/docex/cicl/transfer.py`. Near the top, after the imports and after the `_BUNDLED_TABLES_CANDIDATES` block (around line 37), add:

```python
# Strict allowlists for transfer-table schema validation. Per
# transfer_tables.md § Failure-mode contract, anything outside these sets
# is rejected at load time. Adding to these is a doctrine change (extend
# the schema), not a permissive workaround.

_ALLOWED_TOPLEVEL_KEYS: frozenset[str] = frozenset({
    "roles",
    "naming_policies",
})

# Role-level keys reserved for metadata. Anything else under a role is
# treated as an engine name (since engine names are user-defined).
_RESERVED_ROLE_KEYS: frozenset[str] = frozenset({
    "description",
})

# Engine-entry sub-keys. Must match `_parse_entry`'s consumed set
# exactly. Mod 015 will add `persistent_storage` here when EFS lands.
_ALLOWED_ENGINE_KEYS: frozenset[str] = frozenset({
    "foundation",
    "default_port",
    "emits",
    "defaults",
    "fields",
    "provides",
    "env",
    "naming",
    "reserved_names",
})
```

## Step 2 — `_did_you_mean` helper

File: `src/docex/cicl/transfer.py`. Above `_deep_merge`, add a small Levenshtein helper:

```python
def _levenshtein(a: str, b: str) -> int:
    """Iterative Levenshtein edit distance. Two short strings — O(len(a)*len(b))."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        curr = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            curr[j] = min(curr[j - 1] + 1, prev[j] + 1, prev[j - 1] + cost)
        prev = curr
    return prev[-1]


def _did_you_mean(needle: str, haystack: frozenset[str] | set[str]) -> str:
    """Return a `— did you mean 'X'?` suffix, or a `— allowed: ...` list.

    Cutoff of edit distance 2 keeps suggestions tight. Below that, list
    the full allowlist so the developer sees the schema.
    """
    if not haystack:
        return ""
    closest = min(haystack, key=lambda k: _levenshtein(needle, k))
    if _levenshtein(needle, closest) <= 2:
        return f" — did you mean {closest!r}?"
    return f" — allowed: {', '.join(sorted(haystack))}"
```

## Step 3 — Source-path display helper

File: `src/docex/cicl/transfer.py`. Above `_read_yaml_files`, add:

```python
def _display_path(path: Path, root: Path, kind: str) -> str:
    """Render a YAML file path as a developer-friendly relative form.

    For bundled tables: ``tables/roles/<file>.yml``.
    For project-local tables: ``infra/transfer_tables/<file>.yml``.

    `kind` is 'bundled' or 'project'. `root` is the layer root the file
    was discovered under.
    """
    rel = path.relative_to(root)
    if kind == "bundled":
        return f"tables/{rel}"
    if kind == "project":
        return f"infra/transfer_tables/{rel}"
    return str(path)
```

## Step 4 — Per-file strict validation

File: `src/docex/cicl/transfer.py`. Add a new function `_validate_file(display_path, doc)` that walks one YAML doc and raises `TransferTableError` with source attribution on any allowlist violation.

```python
def _validate_file(display_path: str, doc: dict[str, Any]) -> None:
    """Strictly validate one transfer-table YAML doc's schema shape.

    Walks the doc top-down, raising TransferTableError with source path
    attribution on any unknown key, malformed structure, or invalid value.
    Does not construct typed objects — that happens after merging.
    """
    # Top-level keys.
    for key in doc:
        if key not in _ALLOWED_TOPLEVEL_KEYS:
            raise TransferTableError(
                f"{display_path}: unknown top-level key {key!r}"
                + _did_you_mean(key, _ALLOWED_TOPLEVEL_KEYS)
            )

    # naming_policies block.
    policies = doc.get("naming_policies") or {}
    if not isinstance(policies, dict):
        raise TransferTableError(
            f"{display_path}: `naming_policies:` must be a mapping"
        )
    for policy_name, body in policies.items():
        if not isinstance(body, dict):
            raise TransferTableError(
                f"{display_path}: naming_policies.{policy_name}: "
                f"must be a mapping"
            )
        # Delegate sub-key validation to naming.py — same code path
        # that parses bundled policies. Pass display_path so errors
        # attribute correctly.
        from docex.naming import _validate_policy_keys
        _validate_policy_keys(display_path, policy_name, body)

    # roles block.
    roles = doc.get("roles") or {}
    if not isinstance(roles, dict):
        raise TransferTableError(
            f"{display_path}: `roles:` must be a mapping"
        )
    for role_name, role_body in roles.items():
        if not isinstance(role_body, dict):
            raise TransferTableError(
                f"{display_path}: roles.{role_name}: must be a mapping"
            )
        for child_key, child_body in role_body.items():
            if child_key in _RESERVED_ROLE_KEYS:
                # `description:` — must be a string.
                if child_key == "description" and not isinstance(child_body, str):
                    raise TransferTableError(
                        f"{display_path}: roles.{role_name}.description: "
                        f"must be a string"
                    )
                continue
            # Otherwise it's an engine.
            _validate_engine_entry(
                display_path, role_name, child_key, child_body
            )


def _validate_engine_entry(
    display_path: str,
    role: str,
    engine: str,
    raw: Any,
) -> None:
    """Strictly validate one engine entry's schema."""
    if not isinstance(raw, dict):
        raise TransferTableError(
            f"{display_path}: roles.{role}.{engine}: must be a mapping"
        )
    # Unknown sub-keys.
    for key in raw:
        if key not in _ALLOWED_ENGINE_KEYS:
            raise TransferTableError(
                f"{display_path}: roles.{role}.{engine}: unknown key {key!r}"
                + _did_you_mean(key, _ALLOWED_ENGINE_KEYS)
            )
    # foundation.
    foundation = raw.get("foundation")
    if foundation not in ("fixed", "elastic", "both"):
        raise TransferTableError(
            f"{display_path}: roles.{role}.{engine}.foundation: must be "
            f"'fixed', 'elastic', or 'both' (got {foundation!r})"
        )
    # naming.
    naming_ref = raw.get("naming")
    if not isinstance(naming_ref, str) or not naming_ref:
        raise TransferTableError(
            f"{display_path}: roles.{role}.{engine}.naming: "
            f"must be a non-empty string naming-policy reference "
            f"(got {naming_ref!r})"
        )
    # emits: structure + destination values.
    raw_emits = raw.get("emits") or {}
    if not isinstance(raw_emits, dict):
        raise TransferTableError(
            f"{display_path}: roles.{role}.{engine}.emits: must be a "
            f"mapping of foundation -> list of destinations"
        )
    for fnd, targets in raw_emits.items():
        if fnd not in EMIT_DESTINATIONS:
            raise TransferTableError(
                f"{display_path}: roles.{role}.{engine}.emits.{fnd}: "
                f"unknown foundation {fnd!r} — allowed: "
                f"{', '.join(sorted(EMIT_DESTINATIONS))}"
            )
        if not isinstance(targets, list) or not all(isinstance(t, str) for t in targets):
            raise TransferTableError(
                f"{display_path}: roles.{role}.{engine}.emits.{fnd}: "
                f"must be a list of destination name strings"
            )
        valid_dests = EMIT_DESTINATIONS[fnd]
        for dest in targets:
            if dest not in valid_dests:
                raise TransferTableError(
                    f"{display_path}: roles.{role}.{engine}.emits.{fnd}: "
                    f"unknown destination {dest!r}"
                    + _did_you_mean(dest, valid_dests)
                )
```

The `_validate_engine_entry` function consolidates what's currently spread across `_parse_entry`. After this lands, `_parse_entry` can shrink to just the typed construction (no validation, since `_validate_file` has already run).

## Step 5 — Strict naming-policy key validation

File: `src/docex/naming.py`. Define an allowlist and add `_validate_policy_keys`:

Near the top (after imports), add:

```python
# Per transfer_tables.md § Failure-mode contract — strict allowlist of
# the keys a naming-policy body may contain. Anything else is a hard
# error at load time.
_ALLOWED_POLICY_KEYS: frozenset[str] = frozenset({
    "separator",
    "case",
    "max_len",
})
```

Add a new function for source-attributed key validation (called by `transfer.py::_validate_file`):

```python
def _validate_policy_keys(
    display_path: str, name: str, body: dict
) -> None:
    """Strictly validate a naming-policy body's keys. Source-attributed.

    Called from transfer.py::_validate_file during the per-file pass,
    before policies are merged across layers. The structural value
    checks (separator/case/max_len semantics) still happen in
    parse_policies — this function is only the unknown-key gate.
    """
    # Import lazily to avoid a circular module dependency
    # (transfer.py imports naming.py at module load).
    from docex.cicl.transfer import _did_you_mean
    for key in body:
        if key not in _ALLOWED_POLICY_KEYS:
            raise TransferTableError(
                f"{display_path}: naming_policies.{name}: "
                f"unknown key {key!r}"
                + _did_you_mean(key, _ALLOWED_POLICY_KEYS)
            )
```

Update `parse_policies` to keep its existing value-level checks (separator must be 'underscore'|'hyphen', etc.) — those run after `_validate_policy_keys`, on merged input.

## Step 6 — Wire validation into the loader

File: `src/docex/cicl/transfer.py`. Restructure `load_transfer_tables` to validate-per-file before merging:

Current shape (transfer.py:335-383):

```python
def load_transfer_tables(project_root: Path | None) -> TransferTables:
    raw_merged: dict[str, Any] = {}

    bundled_root = _bundled_tables_root()
    sources: list[Path] = []
    if bundled_root is not None:
        sources.append(bundled_root)
    proj_root = _project_tables_root(project_root)
    if proj_root is not None:
        sources.append(proj_root)

    for root in sources:
        for _path, doc in _read_yaml_files(root):
            if "roles" in doc and isinstance(doc["roles"], dict):
                raw_merged = _deep_merge(raw_merged, {"roles": doc["roles"]})
            ...
```

New shape:

```python
def load_transfer_tables(project_root: Path | None) -> TransferTables:
    raw_merged: dict[str, Any] = {}

    layers: list[tuple[Path, str]] = []
    bundled_root = _bundled_tables_root()
    if bundled_root is not None:
        layers.append((bundled_root, "bundled"))
    proj_root = _project_tables_root(project_root)
    if proj_root is not None:
        layers.append((proj_root, "project"))

    for layer_root, kind in layers:
        for path, doc in _read_yaml_files(layer_root):
            display_path = _display_path(path, layer_root, kind)
            # Validate-then-merge. Per-file validation gives source
            # attribution; the merge accumulates already-validated data.
            _validate_file(display_path, doc)
            if "roles" in doc and isinstance(doc["roles"], dict):
                raw_merged = _deep_merge(raw_merged, {"roles": doc["roles"]})
            if "naming_policies" in doc and isinstance(doc["naming_policies"], dict):
                raw_merged = _deep_merge(
                    raw_merged, {"naming_policies": doc["naming_policies"]}
                )

    policies = parse_policies(raw_merged.get("naming_policies", {}))

    by_role: dict[str, dict[str, EngineEntry]] = {}
    descriptions: dict[str, str] = {}
    for role, engines in (raw_merged.get("roles") or {}).items():
        ...
```

The `for role, engines` loop at the bottom stays the same — it constructs `EngineEntry` from validated raw dicts. `_parse_entry` continues to do its typed construction; its existing structural checks are now belt-and-suspenders.

## Step 7 — Slim down `_parse_entry`

`_parse_entry` currently re-validates `foundation`, `naming`, and `emits` structure. Those checks are now in `_validate_engine_entry` and run during `_validate_file`. Strip the duplicates from `_parse_entry`, leaving only the construction logic. Keep a single guard:

```python
def _parse_entry(role: str, engine: str, raw: dict[str, Any]) -> EngineEntry:
    # Validation has already run during load_transfer_tables; this
    # function only constructs the typed object.
    raw_emits = raw.get("emits") or {}
    emits: dict[str, list[str]] = {
        fnd: list(targets) for fnd, targets in raw_emits.items()
    }
    return EngineEntry(
        role=role,
        engine=engine,
        foundation=raw["foundation"],
        defaults=raw.get("defaults", {}) or {},
        fields=raw.get("fields", {}) or {},
        provides=raw.get("provides", {}) or {},
        env=raw.get("env", {}) or {},
        naming=raw["naming"],
        default_port=raw.get("default_port"),
        reserved_names=[
            str(item).lower()
            for item in (raw.get("reserved_names") or [])
        ],
        emits=emits,
    )
```

This is a refactor, not a behavior change — the same `EngineEntry` instances come out.

## Step 8 — Cross-validate naming refs against the policy table

The current `load_transfer_tables` does `policies.get(entry.naming)` at line 377 — that raises `TransferTableError` from `naming.py`'s `NamingPolicies.get`. Enrich that error site so the message includes the source attribution of the engine that referenced the bad policy:

```python
for engine, raw_entry in engines.items():
    ...
    entry = _parse_entry(role, engine, raw_entry)
    try:
        policies.get(entry.naming)
    except TransferTableError as exc:
        raise TransferTableError(
            f"roles.{role}.{engine}.naming: {exc}"
        ) from exc
    by_role.setdefault(role, {})[engine] = entry
```

We don't have a source-path attribution at this layer (the entry came from possibly multiple files via deep merge), but the role + engine name is enough — the developer can grep their tables for it. Keep the change small here.

## Step 9 — Unit tests

File: `tests/unit/test_transfer_validation.py` (new file). Use the existing test-fixture pattern — write small malformed YAML strings to a tmp_path and load against them.

```python
"""Mod 012: strict transfer-table validation with descriptive failure messages."""

from __future__ import annotations

from pathlib import Path

import pytest

from docex.cicl.transfer import load_transfer_tables
from docex.errors import TransferTableError


def _write_project_table(project_root: Path, content: str, name: str = "extra.yml") -> None:
    """Write a project-local transfer-table file at the conventional path."""
    tt_dir = project_root / "infra" / "transfer_tables"
    tt_dir.mkdir(parents=True, exist_ok=True)
    (tt_dir / name).write_text(content)


def test_unknown_toplevel_key_typo_suggests_correction(tmp_path: Path) -> None:
    """`role:` (singular) at top level — error names the file and suggests `roles`."""
    _write_project_table(tmp_path, "role:\n  sidecar:\n    nginx:\n      foundation: both\n")
    with pytest.raises(TransferTableError) as exc:
        load_transfer_tables(tmp_path)
    msg = str(exc.value)
    assert "infra/transfer_tables/extra.yml" in msg
    assert "unknown top-level key 'role'" in msg
    assert "did you mean 'roles'" in msg


def test_unknown_toplevel_key_unrelated_lists_allowed(tmp_path: Path) -> None:
    """A wholly-unrelated top-level key falls back to listing allowed keys."""
    _write_project_table(tmp_path, "frobnicate: true\n")
    with pytest.raises(TransferTableError) as exc:
        load_transfer_tables(tmp_path)
    msg = str(exc.value)
    assert "frobnicate" in msg
    assert "allowed: naming_policies, roles" in msg


def test_unknown_engine_subkey_with_typo(tmp_path: Path) -> None:
    """`defualts:` typo under an engine entry — error names file + role + engine + key."""
    _write_project_table(
        tmp_path,
        "roles:\n"
        "  sidecar:\n"
        "    nginx:\n"
        "      foundation: both\n"
        "      naming: ecs\n"
        "      defualts:\n"
        "        fixed: {}\n",
    )
    with pytest.raises(TransferTableError) as exc:
        load_transfer_tables(tmp_path)
    msg = str(exc.value)
    assert "infra/transfer_tables/extra.yml" in msg
    assert "roles.sidecar.nginx" in msg
    assert "'defualts'" in msg
    assert "did you mean 'defaults'" in msg


def test_unknown_emit_destination_value(tmp_path: Path) -> None:
    """`s3_buckets` (plural typo) — error names file + role + engine + foundation + bad value."""
    _write_project_table(
        tmp_path,
        "roles:\n"
        "  storage:\n"
        "    bespoke:\n"
        "      foundation: elastic\n"
        "      naming: s3\n"
        "      emits:\n"
        "        elastic: [s3_buckets]\n",
    )
    with pytest.raises(TransferTableError) as exc:
        load_transfer_tables(tmp_path)
    msg = str(exc.value)
    assert "infra/transfer_tables/extra.yml" in msg
    assert "roles.storage.bespoke.emits.elastic" in msg
    assert "unknown destination 's3_buckets'" in msg
    assert "did you mean 's3_bucket'" in msg


def test_unknown_naming_policy_subkey(tmp_path: Path) -> None:
    """`seperator:` typo on a policy — error names file + policy + key."""
    _write_project_table(
        tmp_path,
        "naming_policies:\n"
        "  custom:\n"
        "    seperator: hyphen\n",
    )
    with pytest.raises(TransferTableError) as exc:
        load_transfer_tables(tmp_path)
    msg = str(exc.value)
    assert "infra/transfer_tables/extra.yml" in msg
    assert "naming_policies.custom" in msg
    assert "'seperator'" in msg
    assert "did you mean 'separator'" in msg


def test_unknown_foundation_in_emits(tmp_path: Path) -> None:
    """An invalid foundation key under `emits:` is rejected with the allowed list."""
    _write_project_table(
        tmp_path,
        "roles:\n"
        "  weird:\n"
        "    bespoke:\n"
        "      foundation: both\n"
        "      naming: ecs\n"
        "      emits:\n"
        "        mainframe: [compose_service]\n",
    )
    with pytest.raises(TransferTableError) as exc:
        load_transfer_tables(tmp_path)
    msg = str(exc.value)
    assert "infra/transfer_tables/extra.yml" in msg
    assert "emits.mainframe" in msg
    assert "unknown foundation 'mainframe'" in msg


def test_bundled_table_passes_clean(tmp_path: Path) -> None:
    """Sanity: with no project-local table, loading still succeeds with bundled tables only."""
    tables = load_transfer_tables(tmp_path)
    # Bundled-only load should return all canonical roles.
    assert "web" in tables.by_role
    assert "relational_db" in tables.by_role


def test_well_formed_project_table_loads(tmp_path: Path) -> None:
    """A correctly-shaped project table merges cleanly — no spurious errors."""
    _write_project_table(
        tmp_path,
        "roles:\n"
        "  sidecar:\n"
        "    nginx:\n"
        "      foundation: both\n"
        "      naming: ecs\n"
        "      emits:\n"
        "        fixed: [compose_service]\n"
        "        elastic: [task_definition, ecs_service]\n"
        "      defaults:\n"
        "        fixed: {image: 'nginx:1.27-alpine'}\n"
        "        elastic: {image: 'nginx:1.27-alpine'}\n"
        "      provides: {}\n"
        "      env: {}\n",
    )
    tables = load_transfer_tables(tmp_path)
    assert "sidecar" in tables.by_role
    assert "nginx" in tables.by_role["sidecar"]
```

## Step 10 — Run the suite

```sh
cd /home/ubuntu/.claude/jean_baudrillard/docex
python3 -m pytest tests/unit/ -q
python3 -m pytest tests/integration/test_compile.py -q
```

All must pass. Pre-existing tests that constructed malformed transfer tables to test downstream error paths may now fail at load time instead of downstream — if so, update them to match the new error site (or move them to `test_transfer_validation.py` and consolidate). Inspect any failing test before changing it; if the existing assertion was about the downstream effect of a typo, the test should now assert against the load-time message.

The bundled tables under `tables/roles/*.yml` and `tables/naming_policies.yml` must continue to load without errors — the schema this mod enforces is the schema the bundled tables already conform to.

## Step 11 — Leave everything uncommitted

No git commits. Design-context LLM reviews before commit.

## Hand-off report

In ≤250 words:

- Files changed: docex source (`transfer.py`, `naming.py`), new test file, any pre-existing test files updated.
- Test pass counts: all unit, integration. Confirm `test_transfer_validation.py` runs and all 8 tests pass.
- Whether the bundled tables still load cleanly — i.e., `load_transfer_tables(tmp_path)` with no project tables returns the expected roles.
- Any pre-existing test you had to update (likely some test_transfer or test_compile tests that constructed malformed tables to exercise downstream behavior). What kind of update.
- Any decision made beyond implementation.md, especially around: (a) circular import handling for `_did_you_mean` between transfer.py and naming.py; (b) whether `_parse_entry`'s slim-down created any subtle behavior change; (c) test-fixture path/style choices.
- Anything that smelled off — places where the validation wanted to grow beyond the scope of this mod, or places where the existing schema is sloppier than the doctrine documents.

## Out of scope

- Validation of body keys inside `defaults.<foundation>` — those are engine/role-specific and validated downstream when the compiler routes them to an emit destination. This mod only checks table-shape correctness.
- New emit destinations. Mods 013–015 add to `EMIT_DESTINATIONS` as needed; this mod just enforces against the current set.
- Changes to the merge semantics. Bundled-then-project-local deep merge with project values winning at every leaf remains as documented.
- Magic-ref validation. That's `cicl/validate.py`'s job (rule 7) and unrelated.
- Refactoring `_parse_entry` to be data-driven (e.g., a single schema dict). Future cleanup if the schema grows; not motivated today.
