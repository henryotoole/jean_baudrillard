# Mod 080 — Implementation steps

Self-contained guide. Modifying `docex` at `~/.claude/jean_baudrillard/docex`.
Read [`overview.md`](./overview.md) first. Paths relative to project root.
**Do not edit doctrine files, `tables/`, or `emit/`.**

## Context (current shapes)

- `env_file_for(ctx, env)` (`src/docex/orchestrate/_common.py:60`) → returns
  `infra/secrets/<env>.env` if it exists else `None`; passed to compose
  `--env-file`. Callers: `up.py:178`, `migrate.py:89`, `test.py:63` (with an
  `env_file_override`), `build.py:59`, `down.py:83`, `check.py:743`.
- `up.py` also passes `DOCEX_SECRETS_ENV_FILE=<abs env file>` as `extra_env`
  (mod 075, scheduler mount) at line ~214-218.
- Mod 078: `cicl/categories.py::classify_source_keys(doc, tables)` +
  `DOCTRINE_INJECTED_SECRETS`. Mod 076: `cicl/generate.py::generate(policy)` +
  `GenerationPolicy`; `EngineEntry.env: dict[str, EnvVarSpec]` (`.kind`,
  `.policy`); `TransferTables.generation_policies.get(name)`.
- `ProjectContext` (`src/docex/context.py`) carries `project_root`, `infra`
  (CICLDocument | None), `transfer_tables`, `project`.

## Step 1 — `docex/envfile.py` (new, standard-form read/write)

Implements `config_and_secrets.md § Standard Form`: flat `KEY=value`, split on
the **first** `=`, value is the literal bytes to EOL (no quote/escape/trim
processing), `#`-lines are full-line comments, `KEY` matches `[A-Z][A-Z0-9_]*`.

```python
"""Flat KEY=value env-file read/write — the standard form used by every
configurable-value store (secrets/tte/config) and the aggregate. See
config_and_secrets.md § Standard Form. Raw-literal values: split on the first
'=', no quote/escape/interpolation/trim processing."""
from __future__ import annotations
import re
from pathlib import Path
from typing import Mapping

_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")

def read_env_file(path: Path) -> dict[str, str]:
    """Parse a standard-form env file into an ordered dict. Missing file → {}.
    Full-line `#` comments and blank lines skipped. Split on first '='.
    A line whose key is malformed raises ValueError (fail loud, not silent)."""
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for raw in path.read_text().splitlines():
        line = raw.rstrip("\n")
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"{path}: malformed line (no '='): {line!r}")
        key, _, value = line.partition("=")
        key = key.strip()
        if not _KEY_RE.match(key):
            raise ValueError(f"{path}: invalid key {key!r} (must match [A-Z][A-Z0-9_]*)")
        out[key] = value  # raw literal — no strip, no unquote
    return out

def write_env_file(path: Path, values: Mapping[str, str], *, header: list[str] | None = None) -> None:
    """Write a standard-form env file, keys sorted for determinism. `header`
    lines are written as `#` comments at the top. Creates parent dirs."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"# {h}" for h in (header or [])]
    if header:
        lines.append("")
    for k in sorted(values):
        lines.append(f"{k}={values[k]}")
    path.write_text("\n".join(lines) + "\n")
```

(A single-key line-preserving `set` for the hand-edited secrets file is Mod 083;
not needed here.)

## Step 2 — `categories.minted_policies` (`cicl/categories.py`)

Add a helper that maps each minted source key to its resolved `GenerationPolicy`
(reusing the same backing-engine walk as `classify_source_keys`):

```python
def minted_policies(doc, tables) -> dict[str, "GenerationPolicy"]:
    """minted source key -> its resolved GenerationPolicy. Used by ensure_tte."""
    out = {}
    for _name, svc in doc.backing_services.items():
        cands = svc.engine if isinstance(svc.engine, list) else [svc.engine]
        for cand in cands:
            try:
                entry = tables.engine(svc.role, cand)
            except Exception:
                continue
            for var_name, spec in (entry.env or {}).items():
                if spec.kind == "minted":
                    out[var_name] = tables.generation_policies.get(spec.policy)
    return out
```

## Step 3 — `orchestrate/aggregate.py` (new)

```python
"""Aggregation — merge the three configurable-value categories into the
container-facing env just before bring-up. Foundation-dispatched like
run_migrate. Mod 080 implements dev/test; stage/prod land in Mods 081/082.
See config_and_secrets.md § Aggregation."""
from __future__ import annotations
from pathlib import Path
from docex.context import ProjectContext
from docex.cicl.categories import minted_policies
from docex.cicl.generate import generate
from docex.envfile import read_env_file, write_env_file
from docex.errors import DocexError  # or an appropriate existing error type

_DEV_TEST = ("dev", "test")

def _tte_store_path(ctx, env) -> Path:
    return ctx.project_root / "infra" / "tte" / f"{env}.env"
def _secrets_path(ctx, env) -> Path:
    return ctx.project_root / "infra" / "secrets" / f"{env}.env"
def _config_path(ctx, env) -> Path:
    return ctx.project_root / "infra" / "config" / f"{env}.env"
def aggregate_path(ctx, env) -> Path:
    return ctx.project_root / ".docex" / "agg" / f"{env}.env"

def ensure_tte(ctx: ProjectContext, *, env: str) -> dict[str, str]:
    """dev/test: generate-if-absent minted values into infra/tte/<env>.env
    (the authoritative store compose reads). Preserves existing values; returns
    the current minted key->value map."""
    store = _tte_store_path(ctx, env)
    existing = read_env_file(store)
    policies = minted_policies(ctx.infra, ctx.transfer_tables)
    updated = dict(existing)
    for key, policy in policies.items():
        if key not in updated:
            updated[key] = generate(policy)  # impure — never at compile
    if updated != existing:
        write_env_file(store, updated,
            header=["docex TTE store — generated engine credentials.",
                    "Authoritative for dev/test; gitignored; do not hand-edit."])
    # Only currently-declared minted keys go to the aggregate.
    return {k: updated[k] for k in policies}

def aggregate(ctx: ProjectContext, *, env: str) -> Path:
    """Build .docex/agg/<env>.env = TTE ∪ secrets ∪ config; return its path.
    dev/test only in Mod 080."""
    if env not in _DEV_TEST:
        raise DocexError(
            f"aggregate({env!r}) — stage/prod aggregation lands in Mods 081/082; "
            f"dev/test only for now."
        )
    tte = ensure_tte(ctx, env=env)
    secrets = read_env_file(_secrets_path(ctx, env))
    config = read_env_file(_config_path(ctx, env))
    merged: dict[str, str] = {}
    for source_name, src in (("tte", tte), ("secrets", secrets), ("config", config)):
        for k, v in src.items():
            if k in merged:
                # Compile guarantees disjointness (rule 20); defensive only.
                raise DocexError(
                    f"aggregation key collision on {k!r} (env {env}) — should "
                    f"have been caught at compile; check infra.yml categories."
                )
            merged[k] = v
    out = aggregate_path(ctx, env)
    write_env_file(out, merged,
        header=["Generated by docex aggregation — derived, ephemeral.",
                "TTE ∪ secrets ∪ config. Do not edit; regenerated every bring-up."])
    return out
```

Use whatever concrete `DocexError` subclass fits (check `src/docex/errors.py`;
add a small `AggregationError(DocexError)` if nothing fits — mirror the existing
error-class style).

## Step 4 — repurpose `env_file_for` (pure) (`orchestrate/_common.py`)

Change `env_file_for` to return the **aggregate** path if it exists, else None:

```python
def env_file_for(ctx: ProjectContext, env: str) -> Path | None:
    """The container-facing env file compose reads: the derived aggregate at
    .docex/agg/<env>.env (TTE ∪ secrets ∪ config), if it exists. Pure — does
    NOT build it (that's aggregate()); returns None when absent so teardown /
    read-only paths degrade gracefully rather than error."""
    from docex.orchestrate.aggregate import aggregate_path
    candidate = aggregate_path(ctx, env)
    return candidate if candidate.is_file() else None
```

(Import inside the function to avoid an import cycle: aggregate.py imports from
categories/generate/envfile, not _common — so a top-level import here would be
fine too, but keep it local to be safe.)

## Step 5 — wire the bring-up sites

At each bring-up site, run `aggregate(ctx, env=…)` and use its returned path as
the compose `--env-file`. Import `from docex.orchestrate.aggregate import aggregate`.

- **`up.py`** (`run_up`): replace `env_file = env_file_for(ctx, env)` with
  `env_file = aggregate(ctx, env=env)`. Also point the `DOCEX_SECRETS_ENV_FILE`
  extra_env at this aggregate path (`str(env_file)`), replacing the current
  `abs_env_file = .../infra/secrets/<env>.env` (line ~214).
- **`migrate.py`** (dev/test branch, ~line 89): `env_file = aggregate(ctx, env=env)`.
- **`build.py`** (~line 59): `env_file = aggregate(ctx, env=_BUILD_ENV)`.
- **`test.py`** (`run_test`, ~line 63): when `env_file_override` is None,
  `env_file = aggregate(ctx, env=_TEST_ENV)`; when an override is given, use it
  (the override is check's already-aggregated path — see below).
- **`check.py`** (~line 743): the worktree test run. It computes an env_file for
  the worktree's `test` env and passes it as `run_test(..., env_file_override=…)`.
  Change it to `aggregate(worktree_ctx, env="test")` so the worktree stack gets
  a real aggregate. **Delicate:** the worktree must have the `test` env's
  source files present. Inspect how check currently makes secrets available in
  the worktree (it may rely on `infra/secrets/test.env` being tracked or
  mirrored). If secrets/config are gitignored, the worktree won't have them —
  in that case mirror `infra/{secrets,config,tte}/test.env` from the real
  project_root into the worktree before aggregating (mirror the pattern
  `pipeline/rollback.py` uses for gitignored creds). Preserve check's current
  behavior; if the pre-existing check test passes with your change, you're good.
- **`down.py`** (~line 83): leave `env_file_for` as-is (now the aggregate path;
  reuses the last bring-up's aggregate, or None). Do **not** call `aggregate`
  in down — teardown must not mint.

## Step 6 — tests

**Unit (`tests/unit/`):**
1. `test_envfile.py` (new): round-trip; first-`=` split (value `A=B=C`);
   comment + blank line skipping; missing file → `{}`; malformed key / no-`=`
   line → ValueError; raw-literal (no trim, quotes preserved literally).
2. `test_aggregate.py` (new):
   - `ensure_tte` mints the postgres `POSTGRES_PASSWORD` into `infra/tte/dev.env`
     when absent; a second call returns the same value (no re-mint); an existing
     value is preserved.
   - `aggregate` writes `.docex/agg/dev.env` = TTE ∪ secrets ∪ config; contains
     the minted password + a secret from `infra/secrets/dev.env` + a config
     value from `infra/config/dev.env`.
   - a defensive cross-source collision raises.
   - `aggregate(ctx, env="stage")` raises the "Mods 081/082" error.
   Build the fixture project on a tmp path (copy an existing fixture that has a
   postgres backing; add `infra/secrets/dev.env` + `infra/config/dev.env`).
3. `test_categories.py`: add a `minted_policies` case (postgres →
   `{POSTGRES_PASSWORD: <password policy>}`).

**Wiring:** the existing `up`/`test`/`build`/`check` unit tests use a fake
docker client — run the full suite and fix any that broke because the env-file
path changed (they may assert the old `infra/secrets/<env>.env` path was passed
to `compose_up`; update to the aggregate path, or assert `aggregate` ran). Grep
tests for `env_file_for`, `secrets/dev.env`, `secrets/test.env`,
`DOCEX_SECRETS_ENV_FILE`.

**Integration:** if a docker-backed `up`/`test` integration test exists
(`tests/integration/`), extend or add one under `@pytest.mark.integration`
asserting a real `docex up dev` mints the TTE store and brings the stack up.
Only add if the harness already runs such tests; otherwise the unit + fake-docker
coverage is sufficient (integration is run separately with `pytest -m integration`).

## Definition of done

- `python3 -m pytest -q` green (baseline after Mod 079 was 713 passed).
- `docex up dev` on a postgres-backed project mints `infra/tte/dev.env`, writes
  `.docex/agg/dev.env` = union, and feeds it to compose; re-running does not
  re-mint.
- `down` does not mint (no `aggregate` call in `down`).
- No `tables/`, `emit/`, or doctrine change.
