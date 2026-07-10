# Mod 077 — Implementation steps

Self-contained guide. You are modifying `docex` at
`~/.claude/jean_baudrillard/docex`. Read [`overview.md`](./overview.md) first.
Paths are relative to the docex project root. **Do not edit doctrine files.**

## Prerequisite understanding (already in the codebase)

- `src/docex/cicl/substitute.py`: `$[VAR]` (regex `_RUNTIME_RE = \$\[([A-Z_][A-Z0-9_]*)\]`)
  is **left verbatim** by `substitute_string` — only collected into
  `RenderedValue.runtime_refs`. `${var}` is compile-time; `@expr` is HCL.
- `src/docex/cicl/magic_refs.py`: `MagicRefResolver` holds `engines:
  dict[str, EngineEntry]` (service name → its resolved engine).
  - `resolve_in_string(template, consumer)` — resolves magic refs (first pass)
    then substitutes against the consumer's ctx (second pass). This is the leaf
    resolver for **backing-service body strings** (called from
    `compile.py::_apply_substitution` with `consumer=<service>`).
  - `_resolve_part(kind, target, part)` — renders a provider's `provides[part]`
    template against the provider's ctx; `engine` (the provider engine) is a
    local var here.
- Mod 076 added `EnvVarSpec(name, kind, desc, value, policy)`;
  `EngineEntry.env: dict[str, EnvVarSpec]`. A fixed var has `kind == "fixed"` and
  a non-None `value`.

## Step 1 — add `_inline_fixed_refs` to the resolver (`magic_refs.py`)

Add a module-level regex (reuse the runtime-ref shape) and a helper. Put the
helper as a private method on `MagicRefResolver` (it needs no instance state but
lives naturally there):

```python
# top of file, near _MAGIC_RE
_RUNTIME_REF_RE = re.compile(r"\$\[([A-Z_][A-Z0-9_]*)\]")

# on MagicRefResolver:
def _inline_fixed(self, rendered: RenderedValue, engine: "EngineEntry | None") -> RenderedValue:
    """Replace $[VAR] with its literal when `engine` declares VAR kind:fixed.

    minted/secret vars are left as runtime refs. Inlined vars are also
    dropped from `rendered.runtime_refs` (they no longer reach the runtime
    layer). No-op when `engine` is None or declares no fixed env vars.
    """
    if engine is None or not engine.env:
        return rendered
    fixed = {n: s.value for n, s in engine.env.items() if s.kind == "fixed"}
    if not fixed:
        return rendered
    inlined: set[str] = set()
    def repl(m: "re.Match[str]") -> str:
        var = m.group(1)
        if var in fixed:
            inlined.add(var)
            return fixed[var]  # the literal value
        return m.group(0)      # leave minted/secret refs untouched
    new_value = _RUNTIME_REF_RE.sub(repl, rendered.value)
    if not inlined:
        return rendered
    return RenderedValue(
        value=new_value,
        raw_hcl=rendered.raw_hcl,
        runtime_refs=rendered.runtime_refs - inlined,
    )
```

`EngineEntry` is already imported in `magic_refs.py`.

## Step 2 — call it at the two resolution sites

**Site 2 (provides template) — in `_resolve_part`:** the provider `engine` is in
scope. Wrap the two return paths so the provides value is inlined against the
provider engine:

```python
    if _MAGIC_RE.search(template):
        return self._inline_fixed(self.resolve_in_string(template, consumer=target), engine)
    return self._inline_fixed(
        substitute_string(template, target_ctx, foundation=self.foundation), engine
    )
```

**Site 1 (backing body & any consumer value) — at the end of
`resolve_in_string`:** after the second-pass `rendered` is built (and before the
`self.runtime_refs.setdefault(...)` bookkeeping), inline against the
**consumer's own** engine:

```python
    rendered = self._inline_fixed(rendered, self.engines.get(consumer))
    rendered.runtime_refs |= runtime_refs   # existing line — keep AFTER inline? see note
```

**Ordering note:** the existing code does `rendered.runtime_refs |= runtime_refs`
(runtime refs gathered from magic-ref expansion) then updates
`self.runtime_refs[consumer]`. Apply `_inline_fixed` to `rendered` **before** the
`|= runtime_refs` merge is fine for the consumer-declared refs, but a fixed var
that arrived via a provides magic ref was already inlined in `_resolve_part`
(Site 2) and thus is not in `runtime_refs` — so no double counting. Keep it
simple: inline the second-pass `rendered` against `engines[consumer]`, then do
the existing `|= runtime_refs` and bookkeeping. Since a consumer engine (core)
has no fixed vars, this is a no-op for consumers; for a backing body it inlines
that backing engine's fixed vars. Verify the final `self.runtime_refs[consumer]`
set no longer contains inlined fixed vars (it won't, because the inlined set was
subtracted inside `_inline_fixed` and the `runtime_refs` local from Site-2 magic
refs never contained the fixed var).

Double-application is impossible: a provides `$[VAR]` is inlined in `_resolve_part`
against the provider; by the time it reaches the consumer's final inline it is a
literal, and the consumer engine has no matching env entry anyway.

## Step 3 — sanity on the parts-only check (`compile.py`)

`compile_env` has a parts-only guard (~lines 684-704) that errors if a core env
value contains `$[` but isn't a bare `$[REF]`. Confirm inlining doesn't trip it:
a `fixed` var inlines to a literal (no `$[`), and `POSTGRES_PASSWORD` remains a
bare `$[POSTGRES_PASSWORD]` full-match → no error. No code change expected here;
just verify with a test that a core service consuming `${backing.db.user}`
(→ `appuser` literal) and `${backing.db.password}` (→ `$[POSTGRES_PASSWORD]`)
compiles cleanly.

## Step 4 — tests (`tests/unit/`)

Add a focused test module (e.g. `test_inline_fixed_env.py`) plus adjust any
existing golden that asserted the old verbatim `$[POSTGRES_USER]` output.

Fixed-var inlining, **fixed foundation** (compile a project with a postgres
backing `db` + a core `web` consuming it):
- The postgres compose service's `environment.POSTGRES_USER == "appuser"`
  (literal, not `${POSTGRES_USER}`), `environment.POSTGRES_PASSWORD ==
  "${POSTGRES_PASSWORD}"` (compose runtime form of the surviving ref).
- The healthcheck test string contains `pg_isready -U appuser` (not
  `$[POSTGRES_USER]` / `${POSTGRES_USER}`).
- A core service with `env: {DATABASE_USER: "${backing_services.db.user}",
  DATABASE_PASSWORD: "${backing_services.db.password}"}` compiles to
  `DATABASE_USER == "appuser"` and `DATABASE_PASSWORD == "${POSTGRES_PASSWORD}"`.

Fixed-var inlining, **elastic foundation**:
- The RDS instance body `username == "appuser"` (plain literal → emitter quotes
  it), and there is **exactly one** `data "aws_ssm_parameter"` block for this DB
  (POSTGRES_PASSWORD), **none** for POSTGRES_USER. (Grep the emitted `main.tf`
  string for `POSTGRES_USER` — it must be absent; `POSTGRES_PASSWORD` present.)
- The consumer core task-def has `DATABASE_USER` as a plain `environment[]`
  entry with value `appuser`, and `DATABASE_PASSWORD` as a `secrets[]` entry
  (valueFrom the POSTGRES_PASSWORD SSM path).

Find the right fixtures: `tests/unit/test_hcl_emitter.py`,
`test_compose_emitter.py`, `test_substitute.py`, `test_magic_refs.py`, and
`tests/fixtures/` show the patterns for compiling a small project in a test.
Reuse an existing fixture project that has a postgres backing if one exists;
otherwise build a minimal `CICLDocument` in-test as those modules do.

**Update, do not delete**, any existing assertion that expected the old
`$[POSTGRES_USER]` / `${POSTGRES_USER}` output — those goldens are now wrong by
design. Grep tests for `POSTGRES_USER` and fix each to the inlined `appuser`
expectation.

## Definition of done

- `python3 -m pytest -q` green (baseline after Mod 076 was 687 passed).
- No `POSTGRES_USER` token survives in any compiled compose/HCL output; `appuser`
  appears where the user was referenced; `POSTGRES_PASSWORD` still flows as a
  runtime ref (compose `${POSTGRES_PASSWORD}` / one SSM data source + ECS
  `secrets[]`).
- No doctrine files, no `tables/`, no `emit/` changes (all resolution lives in
  `magic_refs.py`). If you find yourself editing `emit/hcl.py`, stop — the design
  says the emitter needs no change; a fixed var should already be a literal by
  the time it reaches emit.
