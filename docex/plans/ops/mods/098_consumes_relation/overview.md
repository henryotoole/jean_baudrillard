# Mod 098 — The `consumes` relation

Phase 2 of the **service process types** advance
([plan](../../advances/004_next/service_processes_implementation_plan.md),
[design record](../../advances/004_next/service_processes_refactor.md)).
The rule of record is [`cicl.md §§ Consumes Relationships, Depends-On
Relationships`](../../../../doctrine/infrastructure/cicl.md) and rules 7, 24, 25
as written by Mod 094; where the design record and the doctrine differ in
wording, the doctrine wins. **No doctrine file is touched by this mod.**

## Goal

Build the relation that has been deliberately unenforceable for two mods.

Mod 096 made a core→core `depends_on` an error (rule 24). Mod 097 extended
magic-ref *existence* checking to core process types but left rule 7's core half
unenforced, with a `# Mod 098` comment at `validate.py:349` marking the window:
a core ref must be matched by a `consumes` entry, `consumes` did not exist, and
`depends_on` was no longer a correct thing to check against. Closing that window
is the core of this mod.

Baseline to beat: **835 passed** (`pytest tests/unit`), verified before design.

## What lands

One field and its validation. Nothing else.

```yml
core_services:
  api:
    processes:
      web:
        role: web
        consumes: [api.worker]        # dotted, fully qualified
      worker:
        role: worker
        consumes: [api.web]           # the legal cycle
        depends_on: [taskqueue]       # backing services only (rule 24)
```

`consumes: list[str] = Field(default_factory=list)` on `ProcessType`, sitting
next to `depends_on` with the two-line comment that names the split. It is the
**only** model change; `CoreService`, `BackingService` and `CICLDocument` are
untouched.

`_STANDARD_PROCESS_FIELDS` (`validate.py:53`) gains `"consumes"`, so the field
is never mistaken for an undeclared role-specific one.

### Targets are fully qualified, and `ProcessRef.parse` is the parser

A bare service name is **illegal, not shorthand**: an interface edge points at a
specific boundary, and a codebase does not have one contract. Mod 096 already
built the parser that says so — `ProcessRef.parse` (`model.py:41`) — and it
already carries the doctrine's reason in its error text. This mod **reuses it**
rather than writing a second parser, exactly as Mod 097 reused one arity checker
for both magic-ref kinds.

## Rule 25 — validating `consumes` itself

> **25.** `consumes` names only core process types, fully qualified as
> `<service>.<process>`. A bare core service name is an error, and a process
> type may not consume itself.

A new `_validate_consumes(doc)` pass, registered in `validate_document`
alongside `_validate_depends_on`. All of rule 25 lives there rather than on the
pydantic model, for two reasons: issues aggregate (an author sees every bad
entry in one compile, which is this module's stated contract), and two of the
four checks need the whole document anyway.

| Entry | Outcome | Rule id |
| ----- | ------- | ------- |
| `api.web`, and it exists | clean | — |
| `appdb` (bare, names a **backing** service) | error naming `depends_on:` | `rule_25_consumes_malformed` |
| `api` (bare, names a core service) | error: a codebase has no single boundary | `rule_25_consumes_malformed` |
| `a.b.c` / `api.` / empty | arity error | `rule_25_consumes_malformed` |
| `appdb.main` (service segment is backing) | error naming `depends_on:` | `rule_25_unresolved_consumes` |
| `ghost.web` | unknown core service | `rule_25_unresolved_consumes` |
| `api.ghost` | known codebase, unknown process; message lists the known ones | `rule_25_unresolved_consumes` |
| own dotted identity | self-consume | `rule_25_self_consumes` |

The id family deliberately mirrors the rule-3 family Mod 097 settled
(`rule_3_magic_ref_arity` / `rule_3_unresolved_magic_ref` /
`rule_3_self_magic_ref`): one id for malformation, one for "does not resolve"
covering all three ways to not resolve, one for the self case.

**The bare-name branch dispatches on the namespace before it complains.**
`consumes: [appdb]` is the migration mistake this field invites — an author
reaching for the relation they know and writing a backing service into it — and
`ProcessRef.parse`'s message ("a codebase has no single boundary") is the wrong
answer to that mistake. So the bare form is checked against
`doc.backing_services` first and, on a hit, gets a message that names
`depends_on:` and § Depends-On Relationships. Every other bare form falls
through to `ProcessRef.parse`'s own text verbatim. One parser, two audiences.

### Self-consume shares 097's wording, not just its spirit

`magic_refs.py:137`'s `self_reference_message()` was built by 097's corporal as
the sibling to write this against, and its docstring says so: *"Sibling to rule
25's self-`consumes` clause (Mod 098); keep the two recognizably alike if either
is reworded."* Two messages held alike by a comment drift the first time either
is edited. So the shared clause becomes a module-level constant:

```python
_SELF_REF_RULE = "A process type may not reference itself"
```

and `self_consumes_message(ref, consumer_label)` lands immediately beneath
`self_reference_message()` in `magic_refs.py`, both built from it. Each then
states **its own** consequence, because the consequences genuinely differ:

- magic ref (097, unchanged): `provides.host` is the *internal* discovery name,
  so building an absolute URL to oneself would not return what you expect — use
  `localhost`.
- `consumes` (this mod): a self-edge makes both derivations the field feeds
  nonsensical — the process type becomes its own contract provider, and its
  health fan-out proxies its own `/health` at `/health/<self>`.

Co-locating the `consumes` message in `magic_refs.py` is mildly off-domain — it
is not a magic ref — but it is the only placement that makes the constant
impossible to miss when either message is reworded, which is the property the
comment was asking for and could not enforce.

The self case is checked **before** the exists-check, so an author who consumes
themselves gets the self message rather than a redundant pair.

## Rule 7 becomes kind-aware

> **7.** A ref to a **backing service** must be matched by a `depends_on` entry
> on the referencing process type; a ref to a **core process type** must be
> matched by a `consumes` entry.

The backing half is untouched. The core branch of `_validate_magic_refs.scan`
(`validate.py:293-352`) currently ends at the `# Mod 098` comment and
`continue`s; it gains the edge check after its existing rule-3 checks pass, under
`rule_7_magic_ref_implies_consumes`. `scan()` takes the consumer's parsed
`consumes` set alongside the `depends_on` list it already takes, so each branch
checks against the field its kind calls for and neither can reach the other's.

Comparison is between **parsed** refs, not raw strings: the consumes set is
built as `{ProcessRef.parse(raw).dotted}` over the entries that parse, so a
malformed entry is reported once by rule 25 and does not also produce a
mystifying rule-7 miss.

### The three clarifications each fall out of a structural choice

They are not three extra conditionals. Each is a property of where the check is
placed, which is why each gets its own test — a later refactor that moves the
check loses the property silently.

1. **One-directional: ref ⇒ edge, never edge ⇒ ref.** The check is driven by
   iterating *refs* and looking each up in the consumes set. There is no walk in
   the other direction and none is added. This is load-bearing, not incidental:
   `api.web` declares `consumes: [api.worker]` for the contract and the health
   fan-out while holding no ref to the worker, because it reaches it through the
   broker. A bidirectional rule would reject the most common web/worker topology
   in existence.
2. **Same-codebase is not exempt.** The check compares the ref's *dotted target*
   against the consumes set and never compares codebases, so
   `api.worker → ${core_services.api.web.host}` is obliged like any other edge.
   Sharing source does not make it not a boundary. The message gains one clause
   saying so when target codebase == own codebase, because that is the case an
   author will argue with.
3. **A service-level `env:` ref obliges every process type.** Free from Mod
   096's structure: the scan already runs once per process type over its
   *effective* env (service-level merged under process-level), so a
   service-level `WEB_HOST: ${core_services.api.web.host}` is seen on every
   pass. Mod 096 found this bites already — it is why adding a process type to a
   fixture also means adding its `depends_on`.

Note the interaction with 097's self-ref rule, which needs no code: a
service-level ref to one of the codebase's *own* process types trips
`rule_3_self_magic_ref` on that process's own pass and `continue`s before rule 7
is reached, so it reports as a self-reference rather than as a missing edge.
That is the better message for it.

## The cycle asymmetry, tested as legal

| | `depends_on` | `consumes` |
| --- | --- | --- |
| Cycles | fatal (rule 6) | **legal** |

`consumes` is a directed graph that may legitimately contain cycles; there is
one DAG and one cyclic digraph, and no single field could carry a cycle rule
that is simultaneously fatal and fine.

Mechanically this means **doing nothing** — rule 6's DFS
(`validate.py:504-527`) walks `backing_services` only, since rule 24 made core
process types leaves of that graph. The hazard is a future reader "completing"
the graph walk. So `web ↔ worker` is pinned as **accepted** by a test rather
than left unchecked, in the same assertion as a backing↔backing `depends_on`
cycle still failing. The two facts are one test because it is their conjunction
that is the doctrine.

## `consumes` emits nothing — and compile.py is untouched

The implementation plan's touch list for this mod names `cicl/compile.py`. It
does not need touching, and that is worth recording rather than silently
diverging.

Emission of a process-type field happens exactly one way: field translation
reads `svc.model_extra` (`compile.py:701`) and routes each entry through the
engine's `fields:` block. A **declared** pydantic field is not in `model_extra`,
so `consumes` cannot reach a translation, a body, or `target_extras`.
`_apply_fixed_invariants` (`compile.py:996`) copies `depends_on` explicitly and
nothing else. The field is therefore structurally CI-only, exactly as § Consumes
Relationships says. A test pins it — compile a project carrying `consumes` on
both foundations and assert the string appears nowhere in the emitted
compose/HCL — because "it happens not to be read" and "it cannot be read" look
identical until someone adds a read site.

For the same reason `consumes` is **not** carried onto `CompiledService`. Mod
104 renders `consumes` edges in `describe`, which reads compiled services, so it
will likely want it there — but adding an unread field now is speculative, and
the field a future emitter accidentally picks up is the one that is already
sitting in the compiled struct. 104 adds it when it has a reader.

## Seams left deliberately open

- **A `consumes` target must declare `port` and `health_check_path`**
  ([`contracts.md § Health Checks`](../../../../doctrine/infrastructure/contracts.md#health-checks)).
  That is asserted by the check step, which is **Mod 101**. Not compile-time
  validation, and not here.
- **A `scheduler` may not be a `consumes` target** — stated in the same
  paragraph, and enforced by the same Mod 101 gate. Rule 25 does not say it, and
  this mod implements rule 25. (Compare 097's free behavior: a *magic ref* to a
  scheduler already fails, because `scheduler/container` exposes no parts.)
- **`check.py`'s provider set** still keys off `depends_on` + web membership,
  with the comment at `check.py:329` naming Mod 101 as its owner. Untouched.
- **A backing service that declares `consumes:`** lands in `model_extra` and is
  already rejected by transfer-table rule 4 as an undeclared role-specific
  field. Adequate, and pinned by a test; a bespoke message for it would be a
  new rule.

## Tests

On top of any mechanical churn:

1. Bare `consumes` target naming a core service → rejected, "no single
   boundary".
2. Bare `consumes` target naming a **backing** service → rejected, message names
   `depends_on:`.
3. Dotted target whose service segment is a backing service → rejected.
4. `consumes` naming a nonexistent codebase, and a nonexistent process of a real
   codebase (message lists the known process types) → rejected.
5. Wrong arity (`a.b.c`) → rejected.
6. Self-consume → rejected; the message shares 097's rule clause verbatim
   (asserted against the same constant, so the two cannot drift).
7. Rule 7, backing kind: satisfied with `depends_on`, violated without —
   unchanged behavior, pinned so the split cannot regress it.
8. Rule 7, core kind: satisfied with `consumes`, violated without.
9. **One-directional**: a `consumes` edge with no magic ref is clean.
10. **Same-codebase not exempt**: `api.worker → ${core_services.api.web.host}`
    without the edge is rejected; with it, clean.
11. **Service-level `env:` ref obliges every process type**: two process types,
    one service-level ref, edge declared on only one → exactly one issue, naming
    the other.
12. **`web ↔ worker` `consumes` cycle is accepted**, in the same test as a
    backing `depends_on` cycle still failing.
13. **Nothing emitted**: `consumes` appears in no compose or HCL output, both
    foundations.
14. A backing service declaring `consumes:` is rejected by tt rule 4.

Green at **835 or more**. No test deleted or skipped to get there.

## Out of scope

The exec service (099) · replica emission (100) · the `check.py` contract and
health gates (101) · telemetry attributes (102) · ofelia (103) · `describe`'s
rendering of `consumes` edges (104) · rollback (105) · **any doctrine file**
(106) · any version artifact (107) · `test_projects/*` (107).

The staged `campaigns/` → `advances/` rename and `test_pipeline_projinfra.py`
are pre-existing and not this mod's; every commit uses an explicit pathspec.

## Documentation (mod-cycle step 8)

Two spots in `plans/core/compiler.md`, both stale as of this mod:

- `:263` states rule 7's core half is *"unenforceable until `consumes` exists"*.
  That sentence is this mod's obituary and is rewritten to state the kind-aware
  split as implemented, plus the three clarifications in one line.
- `:58` enumerates `ProcessType`'s fields and omits `consumes`.

`:270` (rule 24 / cycle detection over the backing graph alone) stays correct
and gains the note that `consumes` cycles are legal *by construction* there,
since that is the sentence a future reader would otherwise "fix".

One stale in-code string: `validate.py:480`'s rule-24 message says `consumes:`
is *"(arriving in Mod 098)"*. Dropped in `implementation.md`, not the docs step —
it is a user-facing compile error, not documentation.
`test_process_nesting.py:258` asserts only `"consumes:" in message` and survives.

## Design questions — resolved

**1. A *backing* service holding a magic ref to a core process type — rule 7 is
inexpressible for it. C.O. ruled: (a), skip-and-pin.** `scan()` runs over
backing services too. A backing service has no `consumes:` field (and, since
rule 24, may not `depends_on` a core service), so a backing service carrying
`${core_services.api.web.host}` in its `env:` has no way to satisfy rule 7. The
options were *(a)* skip, comment, and pin; *(b)* reject the ref outright — a new
prohibition no doctrine rule states, so a doctrine change this mod may not make;
*(c)* satisfy it via the backing service's `depends_on`, which contradicts rule
24.

The C.O. added the argument that rules (b) out decisively, and it belongs in the
code comment rather than only here: **a backing→core magic ref can be
legitimate.** An `object_store` with a CORS-origin field set to
`${core_services.api.web.host}` is a reasonable thing to write. And note what an
edge would even *mean* there: a backing service embedding a core hostname in its
own config is not *calling* that service. There is no readiness implication and
no interface boundary — nothing for either relation to express. This is not a
hole in rule 7; it is rule 7 correctly not applying.

Two conditions, both binding on `implementation.md`: the skip is pinned by a
test so it survives refactoring, and the code comment states **why** it is
skipped, not merely that it is. The C.O. is adding a one-line item to Mod 106 so
the doctrine states rule 7's scope explicitly — that it governs process-type
referencers — rather than leaving it to be inferred. The exemption ends up
documented rather than discovered.

**2. Two decisions taken on my own authority — both approved.**
`self_consumes_message()` lands in `magic_refs.py` beside its sibling and shares
a `_SELF_REF_RULE` constant with it (§ Self-consume); a docstring asking two
messages to stay consistent is a wish, a shared constant is a guarantee. The
definition carries a line saying it lives there to be structurally coupled to
its sibling, so the next reader does not "tidy" it into the wrong module.

`consumes` is **not** carried onto `CompiledService` (§ `consumes` emits
nothing), diverging from the implementation plan's touch list. The C.O. checked
the thing that would have made this wrong: Mod 101's gates read the **authoring**
model (`ctx.infra.core_services`), not `CompiledEnv`, so 101 is unaffected by
the deferral; Mod 104 works off `CompiledEnv` and adds the field when it has a
reader. A field that looks load-bearing but is read by nothing is its own
hazard.

No other open questions. The mod sits inside its seam.
