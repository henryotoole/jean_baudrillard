# Mod 076 — Implementation steps

Self-contained implementation guide. You are modifying `docex` (the doctrine's
executor) at `~/.claude/jean_baudrillard/docex`. Read
[`overview.md`](./overview.md) first for design intent. All paths below are
relative to the docex project root unless noted.

Doctrine is authoritative and already written — do **not** edit doctrine files.
Match the schema in `doctrine/infrastructure/specifics/transfer_tables.md`
§ "Anatomy of a Role Definition" and § "Generation Policies" exactly.

## Context: current shapes

- `src/docex/cicl/transfer.py` — `EngineEntry.env: dict[str, str]` (key→desc).
  `_ALLOWED_TOPLEVEL_KEYS = {"roles", "naming_policies"}`. `_ALLOWED_ENGINE_KEYS`
  already includes `"env"`. Loader flow: `_validate_file` (per-file, source-
  attributed) → deep-merge across layers → `_parse_entry` (post-merge, required
  fields) → cross-validate `naming` ref against policy table in
  `load_transfer_tables`.
- `src/docex/naming.py` — `NamingPolicy`/`NamingPolicies`/`parse_policies` +
  `_validate_policy_keys`. **Mirror this structure** for generation policies.
- `src/docex/emit/secrets.py::emit_example_env` — iterates backing
  `entry.env.items()` expecting `{key: descstr}`.
- `src/docex/roles/__init__.py` — reads `entry.env` at lines ~95 and ~148-150.

## Step 1 — `EnvVarSpec` + kind-aware env parsing (`transfer.py`)

Add a dataclass above `EngineEntry`:

```python
@dataclass(frozen=True)
class EnvVarSpec:
    """One engine `env:` entry. `kind` drives compile resolution + storage.

    - fixed:  `value` is inlined at compile; `policy` must be None.
    - minted: `policy` names a generation_policy; `value` must be None.
    - secret: operator-supplied; both None.
    """
    name: str
    kind: str            # 'fixed' | 'minted' | 'secret'
    desc: str = ""
    value: str | None = None    # fixed only
    policy: str | None = None   # minted only
```

Change `EngineEntry.env` type annotation to `dict[str, EnvVarSpec]`
(`field(default_factory=dict)`).

Add a parser that accepts both forms (scalar shorthand + full form):

```python
_ALLOWED_ENV_KINDS = frozenset({"fixed", "minted", "secret"})
_ALLOWED_ENV_ENTRY_KEYS = frozenset({"kind", "desc", "value", "policy"})

def _parse_env_var(role, engine, key, raw) -> EnvVarSpec:
    # Scalar shorthand: `KEY: "desc"` == {kind: secret, desc: "desc"}.
    if isinstance(raw, str):
        return EnvVarSpec(name=key, kind="secret", desc=raw)
    if not isinstance(raw, dict):
        raise TransferTableError(... "env.<key> must be a string (desc) or a mapping")
    kind = raw.get("kind", "secret")
    ... validate kind in _ALLOWED_ENV_KINDS (did_you_mean)
    ... validate no unknown keys (against _ALLOWED_ENV_ENTRY_KEYS)
    ... rule 14: fixed => value present & policy absent; minted => policy present & value absent;
        secret => neither value nor policy.
    return EnvVarSpec(name=key, kind=kind, desc=raw.get("desc",""),
                      value=raw.get("value"), policy=raw.get("policy"))
```

Wire it in `_parse_entry`: replace `env=raw.get("env", {}) or {}` with a dict
comprehension over `_parse_env_var(role, engine, k, v)`.

Also add **per-file** validation of env-entry shape in `_validate_engine_entry`
(only when `"env"` is present): each entry is a str or a mapping with allowed
keys, valid `kind`, and the fixed/minted value/policy invariants (rule 14). This
mirrors how `_validate_file` gives source-attributed errors before merge. (Do
**not** check the minted→generation-policy cross-reference here — that needs the
merged generation_policies, so it goes in `load_transfer_tables`; see Step 4.)

## Step 2 — `GenerationPolicy` + `parse_generation_policies` (`naming.py` or new `cicl/generate.py`)

Put the policy type and generator together in a new module
`src/docex/cicl/generate.py` (keep `naming.py` about *formatting*; generation is
a distinct surface per the doctrine). Mirror `naming.py`'s validate/parse split:

```python
_ALLOWED_GENERATION_POLICY_KEYS = frozenset({"length", "alphabet"})
_ALPHABETS = {
    "url_safe": string.ascii_letters + string.digits + "-_",  # [A-Za-z0-9-_]
    "alnum":    string.ascii_letters + string.digits,
}

@dataclass(frozen=True)
class GenerationPolicy:
    name: str
    length: int
    alphabet: str  # named set key in _ALPHABETS

@dataclass(frozen=True)
class GenerationPolicies:
    by_name: Mapping[str, GenerationPolicy]
    def get(self, name) -> GenerationPolicy: ... (raise TransferTableError if unknown)

def _validate_generation_policy_keys(display_path, name, body): ...  # unknown-key gate, did_you_mean

def parse_generation_policies(raw: dict) -> GenerationPolicies:
    # length: positive int required; alphabet: must be a key in _ALPHABETS.

def generate(policy: GenerationPolicy) -> str:
    """CSPRNG value of `policy.length` chars from the named alphabet."""
    import secrets as _secrets
    alphabet = _ALPHABETS[policy.alphabet]
    return "".join(_secrets.choice(alphabet) for _ in range(policy.length))
```

Note `url_safe` = `[A-Za-z0-9]` plus `-` and `_` per `transfer_tables.md`
§ Generation Policies. Use the stdlib `secrets` module (CSPRNG) — **not**
`random`. Guard against `Math.random`-style banned calls is N/A (Python).

## Step 3 — top-level `generation_policies:` in the loader (`transfer.py`)

- Add `"generation_policies"` to `_ALLOWED_TOPLEVEL_KEYS`.
- In `_validate_file`: validate the `generation_policies` block shape (mapping of
  name → mapping), delegating per-policy key validation to
  `_validate_generation_policy_keys` (import lazily like `_validate_policy_keys`).
- In `load_transfer_tables`: after merging, also merge `generation_policies` top-
  level (add the `if "generation_policies" in doc` branch alongside the
  `naming_policies` one so it deep-merges across bundled + project layers), then
  `gen_policies = parse_generation_policies(raw_merged.get("generation_policies", {}))`.
- Add `generation_policies: GenerationPolicies` field to the `TransferTables`
  dataclass (default empty) and pass it in the constructor.

## Step 4 — cross-validate minted `policy:` refs (rule 13, `transfer.py`)

In `load_transfer_tables`, after building each `EngineEntry` (where the `naming`
ref is already cross-validated against `policies`), also validate every
`kind: minted` env var's `policy` resolves against `gen_policies`:

```python
for var in entry.env.values():
    if var.kind == "minted":
        try:
            gen_policies.get(var.policy)
        except TransferTableError as exc:
            raise TransferTableError(f"roles.{role}.{engine}.env.{var.name}.policy: {exc}")
```

## Step 5 — bundled `generation_policies.yml` + rewrite postgres `env:`

Create `tables/generation_policies.yml`:

```yaml
# Generation policies — how docex mints `kind: minted` engine env vars.
# Sibling to naming_policies (formatter) — this is the generator surface.
# See doctrine/infrastructure/specifics/transfer_tables.md § Generation Policies.
generation_policies:
  password:
    length: 32
    alphabet: url_safe
```

Rewrite the `env:` block in `tables/roles/relational_db.yml` (currently lines
175-177) to the kind schema — match the doctrine walking example exactly:

```yaml
      env:
        POSTGRES_USER:
          kind: fixed
          value: appuser
          desc: "Postgres role name — doctrine-fixed, not a secret."
        POSTGRES_PASSWORD:
          kind: minted
          policy: password
          desc: "Postgres role password — generated once per env."
```

Leave every `$[POSTGRES_USER]` / `$[POSTGRES_PASSWORD]` reference in `defaults`,
`healthcheck`, and `provides` **unchanged** — Mod 077 makes the compiler inline
the fixed one. Update the top-of-file "Phase 4 elastic translation notes" comment
that says the emitter SSM-sources *all* `$[…]` tokens: note that `fixed` vars are
now inlined at compile and only `minted`/`secret` reach SSM (a comment fix — the
emitter code change is Mod 077; this is just keeping the comment honest).

## Step 6 — reshape `emit_example_env` (`emit/secrets.py`)

`example.env` is now a **committed, keys-only, secrets-only manifest** (cicl.md
:392, config_and_secrets.md §2.1). It must contain:
- doctrine-injected `TELEMETRY_API_KEY` (unchanged),
- each core service's `secrets:` keys (unchanged),
- each backing engine's env vars **with `kind == "secret"` only** (exclude
  `fixed` and `minted`).

Change the backing loop: `for k, spec in entry.env.items(): if spec.kind !=
"secret": continue; ... use spec.desc`. Because postgres now has zero
`kind: secret` env vars, its section will be empty and should be omitted (the
existing `if not env_for_service: continue` still works — the dict will be empty).

Update the file header comment: it currently says "Copy this to <env>.env … and
fill in real values." Replace with wording that it's a keys-only manifest of
required secrets, reconciled into `<env>.env` via `docex secrets scaffold <env>`
(forward-reference to the Mod 083 command is fine in a comment). Do not print
values.

## Step 7 — update the other `EngineEntry.env` readers (`roles/__init__.py`)

- Line ~95 (`describe_role` llm/dict form): `"env": dict(entry.env or {})` — the
  values are now `EnvVarSpec` objects, not strings. Emit a serializable shape,
  e.g. `{k: {"kind": s.kind, "desc": s.desc} for k, s in entry.env.items()}`.
- Line ~148-150 (text form "required env" list): iterate `entry.env.items()` and
  render `f"{key} ({spec.kind}) — {spec.desc}"`. Adjust the "required env
  (infra/secrets/<env>.env)" label since not all are secrets now — e.g.
  "engine env vars:" with the kind shown per line.

Grep the rest of `src/` for any other `EngineEntry.env` / `.env` access on an
engine entry and fix to the new shape (`entry.env[...]` is now `EnvVarSpec`).

## Step 8 — tests

Add/adjust under `tests/unit/`:

1. `test_generate.py` (new): `generate()` returns `policy.length` chars, all from
   the named alphabet; `url_safe` includes `-`/`_` and excludes `@:/#?%&+`;
   `alnum` excludes `-`/`_`; two calls differ (CSPRNG variance — assert not
   equal over a couple of tries); unknown alphabet name → error at parse.
2. `test_transfer.py` / `test_transfer_validation.py`: loader parses the kind
   schema (full form + scalar shorthand); rejects unknown `kind`, `fixed`
   without `value`, `fixed` with `policy`, `minted` without `policy`, `minted`
   with `value`, unknown env-entry sub-key; a `minted` var whose `policy` names
   no defined generation policy fails at load (rule 13). `generation_policies`
   parse: unknown top-level sibling accepted; unknown policy sub-key rejected;
   bad `alphabet`/`length` rejected; deep-merge (project override of
   `password.length`) works.
3. `test_emit_example_env` (wherever it lives — grep): update assertions —
   `POSTGRES_USER` / `POSTGRES_PASSWORD` **no longer appear** in `example.env`;
   `TELEMETRY_API_KEY` and any core `secrets:` keys still do.
4. Fix any other existing test that asserted the old `entry.env` string shape or
   the old example.env content (grep `POSTGRES_USER`, `POSTGRES_PASSWORD`,
   `example.env`, `emit_example_env`, `entry.env`).

## Definition of done

- `python3 -m pytest -q` green (was 663 passed before this mod).
- Loader accepts the new postgres table; `docex roles`/`role relational_db`
  render without error (the `env` reader change).
- `example.env` for a project with a postgres backing + a core `secrets:` key
  shows `TELEMETRY_API_KEY` + the core secret key, **not** `POSTGRES_*`.
- No doctrine files modified. No compiler-resolution behavior changed (that's
  Mod 077 — `$[POSTGRES_USER]` still emits verbatim for now; a compose/HCL
  golden test may still show `$[POSTGRES_USER]` / `${POSTGRES_USER}` — that is
  expected and unchanged by this mod).
