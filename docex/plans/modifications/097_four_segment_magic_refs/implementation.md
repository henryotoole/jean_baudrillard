# Mod 097 — Implementation

Execute against `$jb/docex`. Design and rationale: [`overview.md`](./overview.md).
The rule of record is `doctrine/infrastructure/cicl.md § Magic Refs` and
validation rules 3 and 7 — read those before starting. **Do not edit any
doctrine file.** If you find you need one, stop and raise.

**Baseline: `pytest tests/unit` → 821 passed.** Re-run it first and confirm the
number before changing anything. The bar at the end is 821 or more. Do not
delete, skip, or `xfail` a test to get there — if a test's *intent* becomes
wrong rather than its literal, stop and raise it instead of retargeting it.

Three files of source, two of tests:

| Stage | File | What |
| ----- | ---- | ---- |
| 1 | `src/docex/cicl/magic_refs.py` | generic capture, arity check, four-segment resolution, self-ref, deps, cycle key |
| 2 | `src/docex/cicl/substitute.py` | `_COMPILE_RE` charset gains `-` |
| 3 | `src/docex/cicl/validate.py` | core-target branch of rule 3; rule-id unification; self-ref issue |
| 4 | `tests/unit/test_magic_refs.py`, `tests/unit/test_process_nesting.py` | coverage |

Stages 1-3 are one coherent change; the suite is expected to be red between
stage 1 and stage 3 (validate.py imports `find_magic_refs`, whose return type
changes). Do not stop at a red suite mid-stage — stop only if it is red for a
reason not on this page.

---

## Stage 1 — `cicl/magic_refs.py`

### 1.1 The pattern becomes kind-prefixed and body-agnostic

Replace `_MAGIC_RE` (`:39-43`):

```python
# Matches ANY ``${<kind>.<body>}`` where kind ∈ {core_services,
# backing_services}. Deliberately body-agnostic: whether a string IS a magic
# ref must be decided independently of whether that ref is WELL-FORMED.
#
# WHY: the previous pattern hard-coded three segments and an identifier
# charset, so a four-segment ref, or any ref carrying a '-' in a name, matched
# neither this pattern nor substitute._COMPILE_RE and was emitted into the
# compose/HCL output as literal '${...}' text — silent corruption of
# infrastructure config rather than a compile error. Claiming every
# kind-prefixed ref here and arity-checking after the split is what closes it.
_MAGIC_RE = re.compile(r"\$\{(core_services|backing_services)\.([^{}$]*)\}")
```

`[^{}$]` keeps a match from running across an adjacent ref or swallowing a
nested `${`.

### 1.2 Arity, in exactly one place

Add, above the dataclasses:

```python
# Segment counts are stated the way cicl.md states them — INCLUDING the kind
# segment. A core ref is four segments; the body this module splits is three.
_REF_FORM = {
    "core_services": "${core_services.<service>.<process>.<part>}",
    "backing_services": "${backing_services.<service>.<part>}",
}
_REF_BODY_SEGMENTS = {"core_services": 3, "backing_services": 2}
_REF_SEGMENT_WORD = {"core_services": "four-segment", "backing_services": "three-segment"}


class MagicRefArityError(SubstitutionError):
    """A magic ref whose segment count is wrong for its kind."""


@dataclass(frozen=True)
class ParsedMagicRef:
    kind: str
    target: str
    process: str | None  # None for backing services — they have no processes
    part: str
    raw: str  # the literal "${...}" text, for messages

    @property
    def text(self) -> str:
        """Canonical rendering — the form the author should have written."""
        if self.process is None:
            return f"${{{self.kind}.{self.target}.{self.part}}}"
        return f"${{{self.kind}.{self.target}.{self.process}.{self.part}}}"


@dataclass(frozen=True)
class MagicRefMatch:
    """One raw ``${<kind>.<body>}`` hit, not yet arity-checked."""

    kind: str
    body: str
    raw: str

    @property
    def segments(self) -> list[str]:
        return self.body.split(".")

    def parse(self) -> ParsedMagicRef:
        """Arity-check by kind. Raises MagicRefArityError."""
        segs = self.segments
        if len(segs) != _REF_BODY_SEGMENTS[self.kind] or not all(s.strip() for s in segs):
            raise MagicRefArityError(self._arity_message())
        if self.kind == "core_services":
            return ParsedMagicRef(self.kind, segs[0], segs[1], segs[2], self.raw)
        return ParsedMagicRef(self.kind, segs[0], None, segs[1], self.raw)
```

`_arity_message` is the **single** generator for both kinds, so the two stay
recognizable siblings:

```python
    def _arity_message(self) -> str:
        segs = self.segments
        msg = (
            f"magic ref {self.raw} is malformed: `{self.kind}` refs take the "
            f"{_REF_SEGMENT_WORD[self.kind]} form `{_REF_FORM[self.kind]}`."
        )
        if self.kind == "core_services":
            if len(segs) == 2 and all(s.strip() for s in segs):
                msg += (
                    f" Did you mean "
                    f"${{core_services.{segs[0]}.<process>.{segs[1]}}}?"
                )
            msg += (
                " A codebase has no single boundary, so a bare core service "
                "name has no answer."
            )
        else:
            msg += (
                " A backing service has no process types, so there is nothing "
                "to qualify."
            )
            if len(segs) == 3 and all(s.strip() for s in segs):
                msg += (
                    f" Did you mean ${{backing_services.{segs[0]}.{segs[2]}}}?"
                )
        return msg + " See cicl.md § Magic Refs."
```

**Message constraint — do not break it.** `_REF_FORM["core_services"]` must
appear verbatim in the core arity message, because
`tests/unit/test_process_nesting.py:485` asserts that exact substring and it is
the assertion carrying Mod 096's intent.

### 1.3 Self-reference message, shared by both surfaces

Add a module-level function so the resolver and the validator emit the same
string:

```python
def self_reference_message(ref: ParsedMagicRef, consumer_label: str) -> str:
    """cicl.md § Magic Refs — a process type may not reference itself.

    Sibling to rule 25's self-`consumes` clause (Mod 098); keep the two
    recognizably alike if either is reworded.
    """
    return (
        f"magic ref {ref.text} in {consumer_label!r} references the process "
        f"type itself. A process type may not reference itself: "
        f"`provides.{ref.part}` is the *internal* discovery name, so the one "
        f"plausible motive — building an absolute URL to oneself — would not "
        f"return what you expect. Use `localhost` with the process type's own "
        f"`port`. See cicl.md § Magic Refs."
    )
```

### 1.4 `MagicRefDependency`

```python
@dataclass
class MagicRefDependency:
    """One magic ref detected during compile."""

    # The COMPILED identity of whatever holds the ref: 'api-web' for a core
    # process type (Mod 096 re-keyed contexts/engines onto it), the service
    # name for a backing service.
    consumer: str
    kind: str  # 'core_services' | 'backing_services'
    target: str  # service being referenced — the CODEBASE name for core
    target_process: str | None  # process type; None for backing targets
    part: str  # the provides[] part referenced
```

Field order matters only in that every construction site is keyword-based —
keep it that way.

### 1.5 Cycle guard key

`_resolving: set[tuple[str, str, str | None, str]]` — `(kind, target, process,
part)`.

### 1.6 `resolve_in_string`

`magic_repl` becomes:

```python
        def magic_repl(m: re.Match[str]) -> str:
            nonlocal raw_hcl_flag
            ref = MagicRefMatch(
                kind=m.group(1), body=m.group(2), raw=m.group(0)
            ).parse()  # MagicRefArityError propagates — it IS the message

            # cicl.md § Magic Refs: a process type may not reference itself.
            if (
                ref.kind == "core_services"
                and ProcessRef(ref.target, ref.process).compiled == consumer
            ):
                raise SubstitutionError(self_reference_message(ref, consumer))

            self.deps.append(MagicRefDependency(
                consumer=consumer, kind=ref.kind, target=ref.target,
                target_process=ref.process, part=ref.part,
            ))

            key = (ref.kind, ref.target, ref.process, ref.part)
            if key in self._resolving:
                raise SubstitutionError(
                    f"cyclic magic-ref chain through {ref.text}"
                )
            self._resolving.add(key)
            try:
                rendered = self._resolve_part(ref)
            finally:
                self._resolving.discard(key)
            ...
```

The empty-value error below it takes its ref text from `ref.text`.

Import `ProcessRef` from `docex.cicl.model` alongside the existing imports.

### 1.7 `_resolve_part(self, ref: ParsedMagicRef) -> RenderedValue`

Signature takes the parsed ref. Delete the Mod 096 bare-core raise at `:152-167`
in full — including the `# Mod 097 makes the four-segment form resolve.`
comment — and replace the lookup head with:

```python
    def _resolve_part(self, ref: ParsedMagicRef) -> RenderedValue:
        # `key` is what contexts/engines are keyed on: the two-segment compiled
        # identity for a core process type (Mod 096), the bare name for a
        # backing service.
        if ref.kind == "core_services":
            svc = self.doc.core_services.get(ref.target)
            if svc is None:
                raise SubstitutionError(
                    f"magic ref {ref.text} -> unknown core service "
                    f"{ref.target!r}; known: {sorted(self.doc.core_services)}"
                )
            if ref.process not in svc.processes:
                raise SubstitutionError(
                    f"magic ref {ref.text} -> core service {ref.target!r} "
                    f"declares no process type {ref.process!r}; known: "
                    f"{sorted(svc.processes)}"
                )
            key = ProcessRef(ref.target, ref.process).compiled
        elif ref.kind == "backing_services":
            if ref.target not in self.doc.backing_services:
                raise SubstitutionError(
                    f"magic ref {ref.text} -> unknown service {ref.target!r}"
                )
            key = ref.target
        else:  # pragma: no cover — the pattern admits no other kind
            raise SubstitutionError(
                f"magic ref kind must be core_services or backing_services, "
                f"got {ref.kind!r}"
            )

        engine = self.engines.get(key)
        if engine is None:
            raise SubstitutionError(
                f"magic ref {ref.text} -> no engine resolved for {key!r}"
            )

        provides = engine.provides_for(self.foundation)
        if not provides:
            raise SubstitutionError(
                f"magic ref {ref.text} -> the {engine.role!r} role's "
                f"{engine.engine!r} engine exposes no parts on "
                f"{self.foundation}: it publishes no discovery surface and "
                f"therefore cannot be the target of a magic ref."
            )
        if ref.part not in provides:
            raise SubstitutionError(
                f"magic ref {ref.text} -> engine {engine.engine!r} does not "
                f"expose part {ref.part!r} on {self.foundation}; known: "
                f"{sorted(provides)}"
            )
```

**Keep the unknown-service message for backing verbatim** (`-> unknown service
'x'`) — `test_magic_ref_unknown_service` and callers rely on the wording.

The tail keeps today's behavior but **must** use `key`, not `ref.target`, in
both places — this is easy to miss and silently breaks core targets:

```python
        template = provides[ref.part]
        target_ctx = self.contexts.get(key, {})

        if _MAGIC_RE.search(template):
            return self._inline_fixed(
                self.resolve_in_string(template, consumer=key), engine
            )
        return self._inline_fixed(
            substitute_string(template, target_ctx, foundation=self.foundation),
            engine,
        )
```

### 1.8 `find_magic_refs`

```python
def find_magic_refs(template: str) -> list[MagicRefMatch]:
    """Return every raw magic-ref match in ``template``, unparsed.

    Matches are returned *without* arity checking so callers can decide how a
    malformed ref surfaces: the resolver lets ``parse()`` raise, the validator
    catches ``MagicRefArityError`` into a ``ValidationIssue``. One message,
    two surfaces.
    """
    return [
        MagicRefMatch(kind=m.group(1), body=m.group(2), raw=m.group(0))
        for m in _MAGIC_RE.finditer(template)
    ]
```

### 1.9 Module docstring

Update the two example forms at the top of the file to the doctrine's:

```
    ${core_services.<service>.<process>.<part>}     # four segments
    ${backing_services.<service>.<part>}            # three segments
```

with one line on why the asymmetry is honest (a backing service has no process
types, so there is nothing to qualify).

---

## Stage 2 — `cicl/substitute.py`

One character in the charset, plus the comment that justifies it:

```python
# ${name} or ${a.b.c} — letters, digits, '.', '_', '-'.
#
# WHY '-': without it a ${...} carrying a hyphen matched NOTHING — not this
# pattern, not magic_refs._MAGIC_RE — and was emitted verbatim into the
# compose/HCL output instead of failing. Magic refs are now claimed by
# magic_refs regardless of charset; this residual case is a mistyped
# compile-time variable (${env-name} for ${env_name}), which now raises rather
# than being emitted literally. There is NO escape form for a genuinely literal
# ${a-b}: the grammar has exactly ${var}, $[var], @expr. Do not invent one here
# — that is a doctrine change.
_COMPILE_RE = re.compile(r"\$\{([a-zA-Z_][a-zA-Z0-9_.-]*)\}")
```

`-` goes **last** inside the class so it is a literal, not a range.

Do not add a workaround hint to the undefined-variable error message: none
exists, and offering one would be a lie. Also update the module docstring's
magic-ref line (`:23`) to show both forms.

---

## Stage 3 — `cicl/validate.py`

All changes are inside `_validate_magic_refs` (`:266-392`).

### 3.1 Imports

`from docex.cicl.magic_refs import MagicRefArityError, find_magic_refs, self_reference_message, walk_strings`

### 3.2 `scan` gains the consumer's own identity

Replace the `own_name: str` parameter with `own_ref: tuple[str, str] | None` —
`(service, process)` for a core consumer, `None` for a backing one. The
existing `if target != own_name` guard on the rule-7 branch was only ever
meaningful for the backing self-case; keep it as `own_ref is None and target ==
label` behavior by leaving the backing branch's rule-7 test as
`ref.target != label`, where `label` for a backing consumer is its own name.
(Backing call site at `:390` passes `scan(name, name, None, templates, ...)`.)

### 3.3 The loop head

```python
        for template in templates:
            for match in find_magic_refs(template):
                try:
                    ref = match.parse()
                except MagicRefArityError as exc:
                    issues.append(ValidationIssue(
                        rule="rule_3_magic_ref_arity",
                        message=f"{exc} (referenced by {label!r})",
                        where=where_label,
                    ))
                    continue

                if ref.kind == "core_services":
                    _scan_core(ref)
                    continue
                # ... existing backing-service body, reading ref.target /
                # ref.part instead of the old tuple unpack ...
```

Delete the whole `if kind == "core_services": ... continue` block at `:277-296`
(the `rule_3_bare_core_magic_ref` issue). Its content is now one output of the
arity checker, and `rule_3_bare_core_magic_ref` ceases to exist.

### 3.4 The core-target branch

Implement `_scan_core` inline in the closure:

```python
                # --- core target -------------------------------------------
                if ref.kind == "core_services":
                    if own_ref is not None and (ref.target, ref.process) == own_ref:
                        issues.append(ValidationIssue(
                            rule="rule_3_self_magic_ref",
                            message=self_reference_message(ref, label),
                            where=where_label,
                        ))
                        continue
                    target_svc = doc.core_services.get(ref.target)
                    if target_svc is None:
                        issues.append(ValidationIssue(
                            rule="rule_3_unresolved_magic_ref",
                            message=(
                                f"magic ref {ref.text} in {label!r} references "
                                f"unknown core service {ref.target!r}"
                            ),
                            where=where_label,
                        ))
                        continue
                    target_proc = target_svc.processes.get(ref.process)
                    if target_proc is None:
                        issues.append(ValidationIssue(
                            rule="rule_3_unresolved_magic_ref",
                            message=(
                                f"magic ref {ref.text} in {label!r}: core "
                                f"service {ref.target!r} declares no process "
                                f"type {ref.process!r}; known: "
                                f"{sorted(target_svc.processes)}"
                            ),
                            where=where_label,
                        ))
                        continue
                    # The part must be exposed by an engine of the target
                    # process's role. Collected across foundations, exactly as
                    # the backing branch does — validate_document has no
                    # foundation.
                    exposed: set[str] = set()
                    try:
                        role_engines = tables.role(target_proc.role)
                    except Exception:
                        role_engines = {}
                    for entry in role_engines.values():
                        for part_name in (entry.provides or {}).keys():
                            exposed.add(part_name)
                    if ref.part not in exposed:
                        issues.append(ValidationIssue(
                            rule="rule_3_unresolved_magic_ref",
                            message=(
                                f"magic ref {ref.text} in {label!r}: role "
                                f"{target_proc.role!r} does not expose part "
                                f"{ref.part!r}; known: {sorted(exposed)}"
                            ),
                            where=where_label,
                        ))
                    # Rule 7 is NOT checked for core targets in this mod. A
                    # core ref must be matched by a `consumes` entry, and
                    # `consumes` does not exist until Mod 098; `depends_on` has
                    # been backing-only since Mod 096's rule 24, so there is
                    # nothing correct to check against. Mod 098 owns it.
                    continue
```

Everything below (rule 3 for backing targets, rule 7 against `depends_on`) is
unchanged except for reading `ref.target` / `ref.part` / `ref.text`.

### 3.5 Call sites

- Core: `scan(ProcessRef(svc_name, proc_name).dotted, _process_where(...), (svc_name, proc_name), templates, list(proc.depends_on or []))`
- Backing: `scan(name, f"backing_services.{name}"…, None, templates, …)` — keep
  today's `where_label`, whatever it currently is.

---

## Stage 4 — tests

### 4.1 `tests/unit/test_process_nesting.py`

Only line 483: `rule == "rule_3_bare_core_magic_ref"` → `"rule_3_magic_ref_arity"`.
**Leave line 485's message assertion exactly as it is** — it is the assertion
carrying the intent, and it must keep passing. Rename the test function to
`test_22_bare_core_magic_ref_rejected_with_arity_message` and update the
section comment above it.

### 4.2 `tests/unit/test_magic_refs.py`

The existing `_make_resolver` fixture already carries an `api` core service with
a `web` process, an `api-web` context, and an `api-web` engine, so most of this
is small. Extend the fixture rather than replacing it:

- add a second process `worker` to `api` (role `worker` is **not** in the
  fixture's `TransferTables`; use `role="web"` with its own `EngineEntry` under
  a distinct engine key, or add a minimal `worker` role entry — either is fine,
  this fixture is synthetic), with an `api-worker` context and engine;
- add a **hyphenated** core service `my-api` with a `web` process, and a
  hyphenated backing service `my-db`, with matching contexts/engines;
- add a `scheduler` role entry whose engine declares `provides={}` and a
  `nightly_cleanup` process using it.

Update `test_find_magic_refs` for the new return type — assert on
`[(m.kind, m.body) for m in refs]`, and add a case showing a malformed ref is
still *matched* (that is the point of body-agnostic capture) and only fails at
`.parse()`.

New tests, at minimum:

1. `test_four_segment_core_ref_resolves` — `${core_services.api.web.host}` from
   consumer `api-worker` → `p-dev-api-web`. Repeat on `foundation="elastic"`.
2. `test_three_segment_core_ref_arity_message` — resolver raises
   `MagicRefArityError`; message contains
   `${core_services.<service>.<process>.<part>}` and the did-you-mean.
3. `test_four_segment_backing_ref_arity_message` —
   `${backing_services.db.web.host}` raises; message contains
   `${backing_services.<service>.<part>}` and "no process types". Assert the two
   messages are siblings by checking both end with `See cicl.md § Magic Refs.`
4. `test_hyphenated_names_round_trip` — `${core_services.my-api.web.host}` and
   `${backing_services.my-db.host}` both resolve, and assert `"${" not in
   rendered.value` for each. This is the regression pin for the silent
   pass-through.
5. `test_self_reference_rejected` — `${core_services.api.web.host}` with
   `consumer="api-web"` raises; message mentions `localhost`.
6. `test_cycle_through_two_processes_of_one_codebase` — give `api-web`'s engine
   `provides.host = "${core_services.api.worker.host}"` and `api-worker`'s
   `provides.host = "${core_services.api.web.host}"`, resolve from a third
   consumer, assert `SubstitutionError` whose message contains
   `cyclic magic-ref chain`.
7. `test_scheduler_process_ref_rejected` — a ref at a `nightly_cleanup` process
   whose engine declares `provides={}`; assert the "exposes no parts" message.
   Add a comment naming *why* this test exists: it pins free behavior so a
   future change to `tables/roles/scheduler.yml` cannot silently open it.
8. `test_dependency_records_target_process` — after resolving a four-segment
   ref, `resolver.deps` carries `(consumer='api-worker', target='api',
   target_process='web', part='host')`; after a backing ref,
   `target_process is None`.

Validator-side coverage in the same module (build a `CICLDocument` in-memory as
`_make_resolver` already does and call `validate_document(doc, tables)`,
filtering by rule id — unrelated issues from other rules are expected and
should be filtered, not eliminated):

9. a four-segment ref to a real process → **no** `rule_3_*` issue;
10. a three-segment core ref → `rule_3_magic_ref_arity`;
11. a ref to a non-existent process of a real codebase →
    `rule_3_unresolved_magic_ref` naming the known process types;
12. a self-ref → `rule_3_self_magic_ref`.

### 4.3 `tests/unit/test_substitute.py` (or wherever `substitute_string` is covered)

13. `test_hyphenated_compile_var_raises_rather_than_passing_through` —
    `substitute_string("${some-var}", {}, foundation="fixed")` raises
    `SubstitutionError` naming the undefined variable. Comment it as the
    regression pin for a `${…}` that previously survived into emitted output.

---

## Finish

1. `pytest tests/unit` — report the exact count. **821 or more.**
2. `git status --short` — confirm you touched only the five files above. A
   pre-existing staged `campaigns/` → `advances/` rename and a modified
   `test_pipeline_projinfra.py` are **not yours**: do not commit, revert, stage,
   or unstage them.
3. Do **not** commit. Report back with: the test count, the files changed, any
   place you deviated from this page and why, and anything you hit that you
   think belongs in the drift review.

## Out of scope

`consumes` and rule 7's kind-aware split (098) · the exec service (099) ·
replica emission (100) · `check.py` gates (101) · telemetry attributes (102) ·
ofelia (103) · `describe` (104) · rollback (105) · **any doctrine file** (106) ·
any version artifact (107) · `test_projects/*` (107) · `plans/core/compiler.md`
(the mod's documentation step, not implementation).
