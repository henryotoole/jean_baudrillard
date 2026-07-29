# Mod 098 — Implementation: the `consumes` relation

Execute against `/home/ubuntu/.claude/jean_baudrillard/docex` (the `docex`
package root; `src/`, `tests/`, `tables/` are directly under it). All paths
below are relative to that root.

Design is settled in [`overview.md`](./overview.md) — **read it first**; it
carries the reasoning this document only executes. The rule of record is
`doctrine/infrastructure/cicl.md` §§ Consumes Relationships, Depends-On
Relationships and validation rules 7, 24, 25 (two directories up, at
`/home/ubuntu/.claude/jean_baudrillard/doctrine/`).

**Baseline: `python3 -m pytest tests/unit -q` → 835 passed.** Confirm this
before you change anything. The bar at the end is **835 or more**, with no test
deleted, skipped, or weakened to get there.

## What this mod does not touch

- **No doctrine file.** Mod 106 owns doctrine; if you believe a doctrine edit is
  needed, stop and report it rather than making it.
- **No core planning doc** (`plans/core/*`). `compiler.md` is updated by the
  mod-cycle documentation step, which is not yours.
- **`src/docex/cicl/compile.py`** — untouched. See § 6.
- **`src/docex/pipeline/check.py`** — untouched. The contract and health gates
  that read `consumes` are Mod 101.
- **`src/docex/describe/*`** — untouched. Mod 104.
- **`tables/`**, `test_projects/`, fixtures under `tests/fixtures/` — untouched.
- Do **not** carry `consumes` onto `CompiledService`.

---

## 1. `src/docex/cicl/model.py` — the field

In `class ProcessType`, immediately after the `depends_on` field (currently
lines 124-125), add:

```python
    # Rule 25: core process types only, dotted and fully qualified
    # ("api.worker"). The interface half of the split `depends_on` used to
    # conflate — `depends_on` is a readiness gate over backing services,
    # `consumes` is an interface edge between core process types. CI-only:
    # contracts, the health fan-out, and rule 7 read it; nothing is emitted
    # from it. See cicl.md § Consumes Relationships.
    consumes: list[str] = Field(default_factory=list)
```

That is the whole model change. Entry-level validation stays in `validate.py`
(§ 3) so issues aggregate and so the backing-namespace dispatch has the
document to consult.

---

## 2. `src/docex/cicl/magic_refs.py` — one self-reference rule, two consequences

Mod 097 left `self_reference_message()` (line 137) with a docstring asking that
its sibling stay "recognizably alike". A comment cannot enforce that; a shared
constant can.

**2a.** Above `self_reference_message`, add the shared clause:

```python
# The self-reference rule, stated once. Two rules forbid a process type from
# pointing at itself — a magic ref (rule 3) and a `consumes` entry (rule 25) —
# and their messages must state the RULE identically while differing in
# consequence. A shared constant is what makes that a guarantee rather than a
# request; the previous form was a docstring asking the next editor to keep
# them alike.
_SELF_REF_RULE = "A process type may not reference itself"
```

**2b.** Rewrite `self_reference_message`'s body to use it. Keep the wording
otherwise **byte-identical** — `test_magic_refs.py` and `test_process_nesting.py`
assert against it:

```python
    return (
        f"magic ref {ref.text} in {consumer_label!r} references the process "
        f"type itself. {_SELF_REF_RULE}: "
        f"`provides.{ref.part}` is the *internal* discovery name, so the one "
        f"plausible motive — building an absolute URL to oneself — would not "
        f"return what you expect. Use `localhost` with the process type's own "
        f"`port`. See cicl.md § Magic Refs."
    )
```

Update its docstring: drop the "keep the two recognizably alike" request (the
constant now does that job) and say the sibling is `self_consumes_message`
below.

**2c.** Immediately beneath it, add the sibling. `ProcessRef` is already
imported at line 31.

```python
def self_consumes_message(ref: ProcessRef) -> str:
    """cicl.md rule 25 — a process type may not consume itself.

    Lives in this module, beside :func:`self_reference_message`, despite being
    a `consumes` concern rather than a magic-ref one: the two messages must
    state ``_SELF_REF_RULE`` identically, and co-location is what makes that
    visible to whoever edits either. Do not "tidy" it into validate.py.
    """
    return (
        f"process type {ref.dotted!r} lists itself in `consumes:`. "
        f"{_SELF_REF_RULE}: a self-edge makes both derivations `consumes` "
        f"feeds nonsensical — the process type would be its own contract "
        f"provider, and its health fan-out would proxy its own `/health` at "
        f"`/health/{ref.service}/{ref.process}`. "
        f"See cicl.md § Consumes Relationships."
    )
```

---

## 3. `src/docex/cicl/validate.py` — rule 25

**3a.** Import `self_consumes_message` alongside `self_reference_message` in the
`docex.cicl.magic_refs` import block (lines 30-35).

**3b.** Add `"consumes"` to `_STANDARD_PROCESS_FIELDS` (line 53) so the field is
never mistaken for an undeclared role-specific one. (It is a declared pydantic
field and therefore not in `model_extra`, so this is belt-and-braces — the set
also documents the process-level surface, which is reason enough.)

**3c.** Add the header comment for rule 25 to the module docstring's rule list
(lines 6-16), matching the existing style.

**3d.** New pass, placed immediately **after** `_validate_depends_on` in the
file so the two relations read together:

```python
# ---------------------------------------------------------------------------
# Rule 25: `consumes` names core process types, fully qualified, not itself.
# ---------------------------------------------------------------------------


def _parsed_consumes(proc: ProcessType) -> set[str]:
    """A process type's `consumes:` targets, normalized to dotted form.

    Entries that do not parse are dropped rather than passed through: rule 25
    reports each one once, and a malformed entry must not ALSO surface as a
    mystifying rule-7 miss against a target the author plainly named.
    """
    out: set[str] = set()
    for raw in (proc.consumes or []):
        try:
            out.add(ProcessRef.parse(raw).dotted)
        except ValueError:
            continue
    return out


def _validate_consumes(doc: CICLDocument) -> list[ValidationIssue]:
    """Rule 25. `ProcessRef.parse` is the parser — Mod 096 already wrote the
    bare-name-is-illegal rule and its reasoning into it, and a second parser
    would be a second place for that rule to drift."""
    issues: list[ValidationIssue] = []
    for svc_name, proc_name, _svc, proc in doc.all_processes():
        label = ProcessRef(svc_name, proc_name).dotted
        where = f"{_process_where(svc_name, proc_name)}.consumes"

        def backing_message(entry: str) -> str:
            return (
                f"process type {label!r} lists {entry!r} in `consumes:`, which "
                f"names the backing service {entry.split('.')[0]!r}. `consumes` "
                f"is an interface edge between core process types; readiness "
                f"coupling to a backing service lives in `depends_on:`. "
                f"See cicl.md § Depends-On Relationships."
            )

        for raw in (proc.consumes or []):
            # WHY the namespace is consulted before the parser: `consumes:
            # [appdb]` is the mistake this field invites — an author reaching
            # for the relation they know — and "a codebase has no single
            # boundary" is the wrong answer to it.
            if "." not in raw and raw in doc.backing_services:
                issues.append(ValidationIssue(
                    rule="rule_25_consumes_malformed",
                    message=backing_message(raw), where=where,
                ))
                continue
            try:
                ref = ProcessRef.parse(raw)
            except ValueError as exc:
                issues.append(ValidationIssue(
                    rule="rule_25_consumes_malformed",
                    message=(
                        f"process type {label!r}: invalid `consumes:` entry — "
                        f"{exc} Rule 25 requires the same fully-qualified form "
                        f"(cicl.md § Consumes Relationships)."
                    ),
                    where=where,
                ))
                continue
            # Before the existence check: an author who consumes themselves
            # should get the self message, not a redundant pair.
            if (ref.service, ref.process) == (svc_name, proc_name):
                issues.append(ValidationIssue(
                    rule="rule_25_self_consumes",
                    message=self_consumes_message(ref), where=where,
                ))
                continue
            target = doc.core_services.get(ref.service)
            if target is None:
                message = (
                    backing_message(raw) if ref.service in doc.backing_services
                    else (
                        f"process type {label!r} lists {raw!r} in `consumes:`, "
                        f"but no core service {ref.service!r} is declared; "
                        f"known: {sorted(doc.core_services)}"
                    )
                )
                issues.append(ValidationIssue(
                    rule="rule_25_unresolved_consumes",
                    message=message, where=where,
                ))
                continue
            if ref.process not in target.processes:
                issues.append(ValidationIssue(
                    rule="rule_25_unresolved_consumes",
                    message=(
                        f"process type {label!r} lists {raw!r} in `consumes:`, "
                        f"but core service {ref.service!r} declares no process "
                        f"type {ref.process!r}; known: "
                        f"{sorted(target.processes)}"
                    ),
                    where=where,
                ))
    return issues
```

The id family mirrors the rule-3 family Mod 097 settled: one id for
malformation, one covering all three ways to not resolve, one for the self
case.

**3e.** Register it in `validate_document`, on the line after
`issues.extend(_validate_depends_on(doc))`:

```python
    issues.extend(_validate_consumes(doc))
```

---

## 4. `src/docex/cicl/validate.py` — rule 7 becomes kind-aware

All inside `_validate_magic_refs` (line 270 onward). The **backing** half is
behavior-unchanged; do not reword its message.

**4a.** `scan`'s signature gains one parameter after `depends_on`:

```python
    def scan(
        label: str, where_label: str, own_ref: tuple[str, str] | None,
        templates: list[str], depends_on: list[str],
        consumes: set[str] | None,
    ) -> None:
```

Document the parameter where the function starts: `depends_on` answers rule 7
for backing targets, `consumes` answers it for core targets, and `None` means
the referencer is a backing service, which cannot answer it at all (§ 4c).

**4b.** In the core branch, replace the `# Rule 7 is NOT checked for core
targets in this mod …` comment block and its trailing `continue` (currently
lines 345-352) with the check. It goes **after** the part-exposure check and is
not gated on it — a missing edge is a fact independent of whether the part
resolves, and issues aggregate:

```python
                    # Rule 7, core half. ONE-DIRECTIONAL by construction: the
                    # walk is over refs, looking each up in the consumes set.
                    # There is no walk in the other direction and none may be
                    # added — `api.web` declares `consumes: [api.worker]` for
                    # the contract and the health fan-out while holding no ref
                    # to the worker, because it reaches it through the broker.
                    # A bidirectional rule would reject the most common
                    # web/worker topology in existence.
                    if consumes is None:
                        # A backing service holds this ref. Rule 7 is worded
                        # "on the referencing PROCESS TYPE"; a backing service
                        # has no `consumes:` and (rule 24) may not depends_on a
                        # core service, so there is nothing it could declare.
                        # WHY skipped rather than rejected: the ref can be
                        # perfectly legitimate — an object_store CORS origin set
                        # to ${core_services.api.web.host} — and it is not a
                        # CALL. Embedding a hostname in your own config implies
                        # no readiness coupling and crosses no interface
                        # boundary, so there is nothing for either relation to
                        # express. This is rule 7 correctly not applying, not a
                        # hole in it. Pinned by
                        # test_consumes_relation.py::test_backing_referencer_*.
                        continue
                    dotted = ProcessRef(ref.target, ref.process).dotted
                    if dotted not in consumes:
                        msg = (
                            f"process type {label!r} references {dotted!r} via "
                            f"{ref.text} but does not list it in consumes"
                        )
                        if own_ref is not None and ref.target == own_ref[0]:
                            # SAME-CODEBASE IS NOT EXEMPT. The check compares
                            # dotted targets and never compares codebases; this
                            # clause exists because it is the case an author
                            # will argue with.
                            msg += (
                                "; same-codebase is not exempt — sharing source "
                                "does not make it not a boundary"
                            )
                        issues.append(ValidationIssue(
                            rule="rule_7_magic_ref_implies_consumes",
                            message=(
                                msg + ". See cicl.md § Consumes Relationships."
                            ),
                            where=where_label,
                        ))
                    continue
```

**4c.** Update the two `scan(...)` call sites:

- Core process types (line ~426): pass `_parsed_consumes(proc)` as the new last
  argument.
- Backing services (line ~458): pass `None`, with a short comment pointing at
  the reasoning in 4b rather than repeating it.

**4d.** The comment above the core call site (lines 409-412) says a
service-level `env:` ref "obliges EVERY process type of that codebase to carry
the depends_on edge". Extend it to say *the edge its kind calls for* —
`depends_on` for a backing target, `consumes` for a core one. **This is the
third clarification and it needs no code**: the scan already runs once per
process type over its effective env, so a service-level ref is seen on every
pass.

---

## 5. `src/docex/cicl/validate.py:480` — one stale string

The rule-24 message says `consumes:` is *"(arriving in Mod 098)"*. Drop that
parenthetical; it is now a live field. Leave the rest of the message alone —
`test_process_nesting.py:258` asserts only that `"consumes:"` appears in it.

Also drop the now-answered `# Mod 098 owns it` marker wherever it survives in
`validate.py`, and update `magic_refs.py:140`'s reference if § 2b has not
already removed it.

---

## 6. Why `compile.py` is not in this list

The implementation plan's touch list for Mod 098 names `cicl/compile.py`. It is
wrong, and the check below is what establishes that rather than assuming it.

A process-type field reaches emitted output exactly one way: field translation
iterates `svc.model_extra` (`compile.py:701`) and routes each entry through the
engine's `fields:` block. A **declared** pydantic field is never in
`model_extra`, so `consumes` cannot reach a body, a translation, or
`target_extras`. `_apply_fixed_invariants` (`compile.py:996`) copies
`depends_on` by name and nothing else.

Do not add a read site. Test 13 (§ 7) pins the outcome.

---

## 7. Tests

### 7a. New module `tests/unit/test_consumes_relation.py`

Follow `tests/unit/test_process_nesting.py`'s in-memory style exactly — the
`_tables()` / `_doc()` / `_issues()` helpers, a `_HEAD` constant, and a
`test_base_document_is_clean` guard so no assertion below can pass vacuously.
Build a two-process base (`api.web` + `api.worker`, both on `internal`, worker
with `role: worker`) plus a second codebase and a backing service where a test
needs them.

Assert on **rule ids** plus the substring of each message that carries the
intent. Do not assert whole messages.

| # | Test | Assert |
| - | ---- | ------ |
| 1 | bare target naming a core service (`consumes: [api]`) | `rule_25_consumes_malformed`; message carries "no single boundary" |
| 2 | bare target naming a **backing** service (`consumes: [appdb]`) | `rule_25_consumes_malformed`; message names `depends_on:` — this is the dispatch of § 3d and the test that proves the author gets the right answer |
| 3 | dotted target whose service segment is backing (`appdb.main`) | `rule_25_unresolved_consumes`; message names `depends_on:` |
| 4 | unknown codebase (`ghost.web`); unknown process of a real codebase (`api.ghost`) | `rule_25_unresolved_consumes`; the second lists the known process types |
| 5 | wrong arity (`a.b.c`) | `rule_25_consumes_malformed` |
| 6 | self-consume (`api.web` consumes `api.web`) | `rule_25_self_consumes`; message contains `magic_refs._SELF_REF_RULE` **imported and compared against the constant, not retyped** — that is what pins the two messages together — and contains `/health/api/web` |
| 7 | rule 7, backing kind, still works | already pinned by `test_validate.py::test_rule_7_magic_ref_implies_depends_on`; add the mirror here only if the new module's base makes it free |
| 8 | rule 7, core kind | `api.worker` env holds `${core_services.api.web.host}`: without `consumes` → `rule_7_magic_ref_implies_consumes`; with it → no rule-7 issue |
| 9 | **one-directional** | `api.web` declares `consumes: [api.worker]` and holds no magic ref → clean. No rule-7 issue in either direction |
| 10 | **same-codebase not exempt** | test 8's document is the same-codebase case; assert the message carries "same-codebase is not exempt". Add a cross-codebase variant so the clause is shown to be conditional |
| 11 | **service-level `env:` obliges every process type** | one service-level `WEB_HOST: ${core_services.other.web.host}` (a *second* codebase, so 097's self-ref rule does not fire), `consumes` declared on only one of two process types → exactly **one** `rule_7_magic_ref_implies_consumes`, and its `where` names the process type that lacks the edge |
| 12 | **cycle asymmetry** | one test, two halves: `api.web ↔ api.worker` mutual `consumes` → **no** issue of any rule; a backing↔backing `depends_on` cycle in the same shape → `rule_6_depends_on_cycle`. Docstring must say why they are one test: it is the conjunction that is the doctrine, and rule 6's DFS walking the backing graph alone is what a future reader would otherwise "complete" |
| 14 | backing service declaring `consumes:` | lands in `model_extra` → `tt_rule_4_undeclared_field`. Free behavior; pinned so it cannot silently become permitted |
| — | **backing referencer** (`test_backing_referencer_core_ref_is_not_obliged`) | a backing service's env holds `${core_services.api.web.host}` → resolves, and **no** `rule_7_*` issue. Docstring carries the § 4b reasoning in one line: it is not a call, so there is nothing for either relation to express |

Test 11 is the one to get right — it is the clarification that already bit Mod
096, and the assertion that matters is the **count** (exactly one), not merely
that an issue exists.

### 7b. `tests/unit/test_process_expansion_emit.py` — the no-emission guard

This module already builds a real three-process project and compiles it on both
foundations, so it is where "nothing is emitted" can be asserted against real
output rather than a synthetic document.

1. Add `"consumes": ["api.web"]` to the `_WORKER` dict, and in
   `_three_process_project` set `procs["web"]["consumes"] = ["api.worker"]`.
   That gives the fixture the legal `web ↔ worker` cycle, so every existing
   assertion in the module becomes a second witness that the field changes no
   output.
2. Add one test:

```python
def test_consumes_reaches_no_emitted_artifact(fixed_root, elastic_root):
    """`consumes` is CI-only — contracts, health fan-out, rule 7 — and must
    reach no compose or HCL output.

    A guard, not a tautology: field translation reads `svc.model_extra` and a
    declared pydantic field is never in it, so `consumes` *cannot* be emitted
    today. But "is not read" and "cannot be read" look identical until someone
    adds a read site, and this test is what tells them apart.

    Env-tier only: the project-tier template carries the word in an unrelated
    prose comment ("docex consumes credentials..."), which is not a leak.
    """
```

  Scan every file under `infra/output/<env>/` for `env in ("dev", "test",
  "stage", "prod")` in both roots and assert `"consumes"` does not appear.
  Include the offending path in the assertion message.

---

## 8. Finish

1. `python3 -m pytest tests/unit -q`. **835 or more**, all green. If something
   is red that you cannot fix inside this mod's seam, stop and report it — do
   not delete or skip a test to reach the number.
2. Report the final count honestly, and list every file you changed.
3. Do **not** commit. The mod-developer reviews the working tree for drift and
   owns both commits.
