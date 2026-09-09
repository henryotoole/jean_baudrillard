# Mod 078 — Implementation steps

Self-contained guide. Modifying `docex` at `~/.claude/jean_baudrillard/docex`.
Read [`overview.md`](./overview.md) first. Paths relative to the docex project
root. **Do not edit doctrine files. Do not edit any `emit/` file** (the overview
explains why the emitter needs no change — config flows through the existing
secrets path).

## Context (current shapes)

- `src/docex/cicl/model.py`: `CoreService` has `env: dict[str, Any]` and
  `secrets: dict[str, str]` (KEY→desc). `_ServiceBase` is `extra="allow"`.
- `src/docex/cicl/compile.py` ~lines 710-717: after resolving `env:`, the
  compiler wires each `secrets:` key as `env_block[key] = f"$[{key}]"`, then
  injects `PROJECT_VERSION` and the `OTEL_*` quartet.
- `src/docex/emit/secrets.py`: `emit_example_env` (Mod 076) emits secret-kind
  backing env vars + core `secrets:` + a hardcoded `TELEMETRY_API_KEY`.
- Backing engine env vars now carry `EnvVarSpec` (Mod 076): `.kind` ∈
  {fixed, minted, secret}. `EngineEntry.env: dict[str, EnvVarSpec]`.
- Resolving a backing service's candidate engines (foundation-agnostic union)
  is done in `emit_example_env` — mirror that pattern (`tables.engine(role,
  cand)` over the `engine` list) for the classifier.

## Step 1 — `CoreService.config` (`model.py`)

Add below `secrets`:

```python
    # Declared, non-secret, per-env config values (e.g. a URL that differs by
    # environment). KEY -> human description. Each key is auto-injected into the
    # container as an env var of the same name, sourced from infra/config/<env>.env
    # (a plain SSM String, not SecureString, on elastic). See config_and_secrets.md.
    config: dict[str, str] = Field(default_factory=dict)
```

## Step 2 — `cicl/categories.py` (new — the backbone)

```python
"""Source-key categorization — the single source of truth for which of the
three configurable-value categories (TTE / secret / config) each source key
belongs to. Pure function of (infra.yml, transfer tables); no values, no
per-env state, no I/O. See config_and_secrets.md § The Three Categories and
cicl.md validation rule 20.
"""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from docex.cicl.model import BackingService, CICLDocument
from docex.cicl.transfer import TransferTables

# Secrets docex injects itself (not declared by any project service). Reserved:
# a project may not redeclare these in any category. Single source of truth —
# emit/secrets.py may import this in a later cleanup.
DOCTRINE_INJECTED_SECRETS: frozenset[str] = frozenset({"TELEMETRY_API_KEY"})

class Category(str, Enum):
    TTE = "tte"
    SECRET = "secret"
    CONFIG = "config"

@dataclass(frozen=True)
class SourceKeyCategories:
    tte: frozenset[str]
    secret: frozenset[str]
    config: frozenset[str]

    def all_keys(self) -> frozenset[str]:
        return self.tte | self.secret | self.config

    def conflicts(self) -> dict[str, list[Category]]:
        """Keys claimed by more than one category (rule 20 violations)."""
        out: dict[str, list[Category]] = {}
        for key in self.tte | self.secret | self.config:
            cats = [c for c, s in (
                (Category.TTE, self.tte),
                (Category.SECRET, self.secret),
                (Category.CONFIG, self.config),
            ) if key in s]
            if len(cats) > 1:
                out[key] = cats
        return out

    def category_of(self, key: str) -> Category | None:
        """The single category of a key. Assumes disjointness (validated at
        compile via rule 20); if a key is in multiple sets this returns the
        first by TTE<SECRET<CONFIG precedence — callers run after validation."""
        if key in self.tte: return Category.TTE
        if key in self.secret: return Category.SECRET
        if key in self.config: return Category.CONFIG
        return None

def classify_source_keys(doc: CICLDocument, tables: TransferTables) -> SourceKeyCategories:
    tte: set[str] = set()
    secret: set[str] = set(DOCTRINE_INJECTED_SECRETS)
    config: set[str] = set()

    # Backing engine env vars — union across candidate engines (foundation-
    # agnostic), split by kind. `fixed` vars are inlined at compile and enter
    # no store, so they are excluded from every category.
    for _name, svc in doc.backing_services.items():
        cands = svc.engine if isinstance(svc.engine, list) else [svc.engine]
        for cand in cands:
            try:
                entry = tables.engine(svc.role, cand)
            except Exception:
                continue
            for var_name, spec in (entry.env or {}).items():
                if spec.kind == "minted":
                    tte.add(var_name)
                elif spec.kind == "secret":
                    secret.add(var_name)
                # kind == "fixed": inlined, no store — skip.

    # Core service declarations.
    for _name, svc in doc.core_services.items():
        secret.update(svc.secrets or {})
        config.update(getattr(svc, "config", {}) or {})

    return SourceKeyCategories(
        tte=frozenset(tte), secret=frozenset(secret), config=frozenset(config)
    )
```

(Do not raise on conflicts here — that is Mod 079's job via `.conflicts()`. The
classifier just reports; validation decides.)

## Step 3 — wire config keys in the compiler (`compile.py`)

In `compile_env`, in the `isinstance(svc, CoreService)` block, right after the
`for key in sorted(svc.secrets): env_block[key] = f"$[{key}]"` loop, add the
config loop:

```python
            # Core-service `config:` are declared, non-secret, per-env values.
            # Wired exactly like secrets — a self-referential runtime ref that
            # the existing secret path delivers (compose ${KEY} / ECS secrets[]).
            # The value is non-secret (String on elastic); the compiled shape is
            # identical to a secret. See config_and_secrets.md.
            for key in sorted(getattr(svc, "config", {}) or {}):
                env_block[key] = f"$[{key}]"
```

Do **not** add anything to `CompiledEnv` and do **not** touch any emitter — the
bare `$[KEY]` is handled by the existing compose/HCL emit paths.

## Step 4 — tests (`tests/unit/`)

1. `test_categories.py` (new):
   - A project with a postgres backing + a core service with `secrets: {STRIPE_KEY: "..."}` and `config: {PARTNER_URL: "..."}` classifies:
     `tte == {POSTGRES_PASSWORD}`, `secret == {STRIPE_KEY, TELEMETRY_API_KEY}`,
     `config == {PARTNER_URL}`. (`POSTGRES_USER` is fixed → in none.)
   - `conflicts()` empty for a disjoint project; non-empty when the same key is
     put in two categories (e.g. a core `config: {STRIPE_KEY}` colliding with its
     `secrets: {STRIPE_KEY}`).
   - `category_of` returns the right `Category`; `None` for an unknown key.
   - Two core services sharing a secret key dedupe into one entry.
2. Config compilation (extend an existing compile test or add one): a core
   service with `config: {PARTNER_URL: "desc"}` compiles so that its resolved
   `env` block contains `PARTNER_URL` wired as the runtime ref (fixed: compose
   `environment` shows `PARTNER_URL: ${PARTNER_URL}`; elastic: task-def has a
   `secrets[]` entry named `PARTNER_URL` with `valueFrom` the
   `/<project>/<env>/PARTNER_URL` SSM path). Reuse fixture patterns from
   `test_compose_emitter.py` / `test_hcl_emitter.py`.
3. Confirm `config:` does **not** appear in `example.env` (it's secrets-only).

## Definition of done

- `python3 -m pytest -q` green (baseline after Mod 077 was 695 passed).
- `classify_source_keys` correctly partitions a mixed project; `conflicts()`
  detects a cross-category collision.
- A `config:` key compiles to the same runtime-ref shape as a secret on both
  foundations; no emitter, `CompiledEnv`, or doctrine change.
