# Mod 125 — implementation steps

Design: [`overview.md`](./overview.md) (read it, including § Rulings). Advance:
[`006_surfaces_and_health`](../../advances/006_surfaces_and_health/advance_plan.md).

**Territory — do not leave it.** Only these are edited:

- `src/docex/cicl/model.py`
- `src/docex/cicl/validate.py`
- `tests/fixtures/sample_project*/infra/infra.yml` (five files)
- `tests/unit/**` (existing tests corrected; one new file)

**Do not touch**, under any circumstance, even if a test seems to want it:
`src/docex/pipeline/check.py`, `src/docex/emit/**`, `tables/**`, `test_projects/**`,
`doctrine/**`, `plans/core/**` (the doc step is the mod developer's, not yours).

Baseline before you start: `.venv/bin/python -m pytest tests/unit -q` → **1009 passed**.
Confirm this first. Run the suite with `-p no:randomly` while iterating; run it once
without at the end.

---

## Step 1 — `src/docex/cicl/model.py`

### 1.1 The style → format table

Add near `_SERVICE_NAME_RE` / `CURRENT_CICL_VERSION`, module level:

```py
# api_style -> contract format. Transcribed from cicl.md § Surfaces, which is
# the source of truth; contracts.md § Standards fixes each format's extension.
#
# WHY it lives in model.py and not validate.py: mod 126's contract gate resolves
# a surface to a contract FILENAME from this same table. Two copies of one
# doctrine table is the drift class docex_process.md § Additional Artifacts
# exists to warn about.
#
# Rule 29 is DERIVED from this mapping (len({format(s) for s in styles}) == 1)
# and never tabulates legal style pairs, so it cannot rot as styles are added.
API_STYLE_FORMATS = {
    "rest": "openapi",
    "stream": "openapi",
    "webhook": "openapi",
    "rpc": "asyncapi",
    "events": "asyncapi",
    "socket": "asyncapi",
    "graphql": "graphql",
    "grpc": "proto",
}

# The formats docex can actually carry. `graphql` and `proto` are DEFINED
# LANGUAGE that is not yet implemented, which is why this is a separate set
# rather than an absence from the table above: an author who declares one must
# hear "format not yet implemented", not "unknown style". See
# 006_surfaces_and_health/surfaces_and_health.md resolved decision 3 and
# contracts.md § Standards.
IMPLEMENTED_CONTRACT_FORMATS = frozenset({"openapi", "asyncapi"})
```

### 1.2 `Surface`

Add immediately after `Resources` (so it sits with the other small nested models):

```py
class Surface(BaseModel):
    """One named boundary of a core service, compiling to one contract file.

    See cicl.md § Surfaces. `extra="forbid"` is deliberate: `api_style:`
    (singular) is the typo this block invites, and under `extra="allow"` it
    would be silently ignored, producing a surface with no styles rather than
    an error. `min_length=1` makes an empty list a parse error, so rule 29
    never has to reason about the empty set.
    """

    model_config = ConfigDict(extra="forbid")

    api_styles: list[str] = Field(min_length=1)

    def formats(self) -> set[str]:
        """The contract formats this surface's styles resolve to.

        Unknown styles are OMITTED rather than raising: rule 29 reports them
        under their own issue id, and one authoring mistake must not surface
        twice. After rule 29 passes this set is a singleton — which is what
        mod 126 reads to name the surface's contract file.
        """
        return {
            API_STYLE_FORMATS[style]
            for style in self.api_styles
            if style in API_STYLE_FORMATS
        }
```

### 1.3 `CoreService.surfaces`

Add as a **real declared field** on `CoreService`, immediately after `uses`:

```py
    # cicl.md § Surfaces. Declaring a surface is what makes a core service a
    # PROVIDER; the empty default is a non-provider, which is exactly a clock's
    # state. Must be a declared field and not an accepted extra: CoreService is
    # extra="allow", so an authored `surfaces:` would otherwise land in
    # model_extra and resurface as `tt_rule_4_undeclared_field` — a message
    # about transfer-table field declarations, which is the wrong answer to a
    # correctly authored block.
    surfaces: dict[str, Surface] = Field(default_factory=dict)
```

Update the class's leading comment about role-specific fields landing in
`model_extra` only if it names `surfaces` — it does not, so leave it.

### 1.4 Rule 30 — surface names

In `CICLDocument._validate_service_names`, **nest inside the existing core-service-name
loop**, after the core-service name check:

```py
                # Rule 30. A surface name is one segment of its contract's
                # filename, which is parsed RIGHT-ANCHORED into four fields
                # (<codebase>.<service>.<surface>.<format>.<ext>), so a dot in
                # a surface name makes the path ambiguous. `_SERVICE_NAME_RE`
                # is reused rather than reinvented precisely because it is
                # already dot-free: a second pattern would be a second place
                # for that property to drift.
                for surface_name in cb.core_services[service_name].surfaces:
                    if not _SERVICE_NAME_RE.match(surface_name):
                        raise ValueError(
                            f"surface name {surface_name!r} (on core service "
                            f"{cb_name}.{service_name}) must start with a "
                            f"letter and contain only letters, digits, '_' or "
                            f"'-'. See cicl.md § Validation Rules rule 30."
                        )
```

Note the loop currently iterates `for service_name in cb.core_services:` — you need the
`CoreService` object, so index it as above (do not restructure the loop).

Also extend `model.py`'s module docstring's parenthetical list of rules it covers to
mention rule 30 alongside rule 5.

---

## Step 2 — `src/docex/cicl/validate.py`

### 2.1 Module docstring roster

Insert, in numeric position, keeping the file's existing wording style:

```
    Rule 28: RETIRED in 1.7.0 (number tombstoned). Formerly required a `port`
             alongside `health_check_path`. Rule 33 confines that field to
             `web`-network core services and rule 15 already requires a `port`
             on those, so the obligation is REDUNDANT rather than merely
             obsolete.
    Rule 29: every surface's `api_styles` resolve to exactly one contract
             format.
    Rule 31: every core-service `uses` target declares at least one surface.
    Rule 32: a `uses` target its consumer addresses DIRECTLY declares a `port`;
             one reached only through a queue or broker declares none.
    Rule 33: `health_check_path` is declared by exactly the `web`-network core
             services — required on them, forbidden off them.
```

(Rule 30 lives in `model.py` with the other name-shape rules; do not list it here.)

### 2.2 Imports and `_STANDARD_SERVICE_FIELDS`

- Import `API_STYLE_FORMATS` and `IMPLEMENTED_CONTRACT_FORMATS` from
  `docex.cicl.model`.
- Add `"surfaces"` to `_STANDARD_SERVICE_FIELDS`. **Without this every project that
  declares a surface trips `tt_rule_4_undeclared_field`** — this line and step 1.3 are
  one change.

### 2.3 Registry

In `validate_document`, replace
`issues.extend(_validate_health_check_path_port(doc))` with:

```py
    issues.extend(_validate_surfaces(doc))
    issues.extend(_validate_uses_addressing(doc))
    issues.extend(_validate_health_check_declaration(doc))
```

### 2.4 Rule 29 — `_validate_surfaces`

New function. Place it after `_validate_role_specific_fields` (surfaces are a field-shape
concern) with a section banner in the file's style.

```py
def _validate_surfaces(doc: CICLDocument) -> list[ValidationIssue]:
    """Rule 29: a surface's `api_styles` resolve to exactly one contract format.

    DERIVED from `API_STYLE_FORMATS`, never tabulated against it: the check is
    `len(surface.formats()) == 1`, so adding a style to the table cannot leave a
    stale pair-legality list behind. `[rest, stream, webhook]` passes — all
    three are openapi. `[rest, rpc]` fails, and the message says to split.

    Also enforces the implemented-format boundary here, at COMPILE, rather than
    leaving it to a later gate: a `graphql`/`proto` surface is a compile error
    per surfaces_and_health.md resolved decision 3, and the point of a separate
    `IMPLEMENTED_CONTRACT_FORMATS` set is that the author hears "not yet
    implemented" instead of "unknown style".
    """
```

Body, per core service, per `(surface_name, surface)` in `svc.surfaces.items()`, with
`where = f"{_service_where(cb_name, svc_name)}.surfaces.{surface_name}"`:

1. For each style in `surface.api_styles` not in `API_STYLE_FORMATS` → one issue,
   `rule="rule_29_unknown_api_style"`, message naming the style, the surface, and
   `sorted(API_STYLE_FORMATS)` as the known set, citing `cicl.md § Surfaces`.
2. `formats = surface.formats()`; if `len(formats) > 1` → one issue,
   `rule="rule_29_mixed_contract_formats"`. The message must name the surface, the
   offending styles grouped by the format each resolves to, and say plainly: *split
   these into two surfaces — a surface compiles to exactly one contract file.*
3. For each `fmt in sorted(formats)` not in `IMPLEMENTED_CONTRACT_FORMATS` → one issue,
   `rule="rule_contract_format_not_implemented"`, naming the format, the style(s) that
   resolved to it, and stating that the style is defined language but the format is not
   yet implemented (cite `contracts.md § Standards`). This id is **un-numbered on
   purpose** — the doctrine states it in `contracts.md` prose, not in the numbered rule
   list, matching `rule_uses_on_backing_service` / `rule_clock_schedules_required`.

Steps 2 and 3 both fire for e.g. `[rest, graphql]`. That is intended: issues are
aggregated so an author fixes everything in one cycle.

### 2.5 Rule 31 — third clause in `_validate_uses`

In `_validate_uses`, at the **end** of the dotted-entry branch, after the
`if ref.service not in target.core_services:` block's `continue`:

```py
            # Rule 31. Declaring a surface is what makes a core service a
            # provider; a target declaring none has no boundary to be used
            # across, so the EDGE is the error rather than a missing contract.
            #
            # WHY nested here rather than a sibling function: this branch has
            # already parsed the ref and resolved the target, and has already
            # decided which malformed entries to stop reporting on. A sibling
            # would duplicate both, and would make a typo'd `uses:` entry report
            # twice — once as rule 25, once as a mystifying "declares no
            # surface" for a target that does not exist. The self-uses and
            # unresolved-target `continue`s above are what buy that.
            if not target.core_services[ref.service].surfaces:
                issues.append(ValidationIssue(
                    rule="rule_31_uses_target_declares_no_surface",
                    message=(
                        f"core service {label!r} lists {raw!r} in `uses:`, but "
                        f"{raw!r} declares no `surfaces:`. Declaring a surface "
                        f"is what makes a core service a provider — one that "
                        f"declares none has no boundary to be used across. "
                        f"Either give {raw!r} a surface or drop the edge. "
                        f"See cicl.md § Validation Rules rule 31."
                    ),
                    where=where,
                ))
```

`where` here is the existing `<consumer>.uses` path — the edge is the fault, not the
target.

### 2.6 Rule 32 — `_validate_uses_addressing`

**First, a no-behavior-change refactor.** `_validate_magic_refs` collects a core
service's ref-bearing templates inline (effective env values, `command`, and
`walk_strings` over `model_extra`). Extract exactly that into a module-level helper and
call it from both places:

```py
def _ref_templates(cb: Codebase, svc: CoreService) -> list[str]:
    """Every string on one core service that may carry a magic ref.

    Its EFFECTIVE env (codebase-level merged under its own), its `command`, and
    every string reachable inside a role-specific field. Extracted so rule 7 and
    rule 32 read the same set — two template walks would drift, and rule 32's
    whole detection rests on seeing the same refs rule 7 sees.
    """
```

Replace the inline collection in `_validate_magic_refs`'s core loop with a call to it.
Leave the *backing-service* loop's own collection alone (it uses `getattr` because
`_ServiceBase` declares neither `env` nor `command`).

Then:

```py
def _core_ref_targets(cb: Codebase, svc: CoreService) -> set[str]:
    """Dotted core-service targets this core service holds a magic ref to.

    Malformed refs are dropped — rule 3 reports them once, and a bad ref must
    not also become a rule-32 verdict.
    """
```

Implement with `find_magic_refs` over `_ref_templates(cb, svc)`, `match.parse()` inside
`try/except MagicRefArityError`, keeping only `ref.kind == "codebases"`, and adding
`ServiceRef(ref.target, ref.service).dotted`.

Then the rule itself:

```py
def _validate_uses_addressing(doc: CICLDocument) -> list[ValidationIssue]:
    """Rule 32: a `uses` target its consumer addresses DIRECTLY declares a
    `port`; one reached only through a queue or broker declares none.

    HOW "directly addressed" is detected: the consumer holds a magic ref to the
    target — ${codebases.<cb>.core_services.<svc>.<part>} — in its effective
    `env:`, its `command`, or a role-specific field.

    WHY that signal and not one derived from the target's `api_styles`: rule 32's
    unit is the EDGE, not the target. Its own wording is "a `uses` target that
    ITS CONSUMER addresses directly", and two consumers can legitimately reach
    one target differently — `api.web` calling a worker's rpc surface while
    `api.clock` enqueues to it through a broker. A per-target derivation
    structurally cannot express that and must collapse the two edges into one
    answer. A style-derived mapping is also not available to us honestly: no
    doctrine file states one, so deriving from styles would mean inventing
    doctrine. (Secondary: the refs cost nothing to see — rule 7 already walks
    exactly this set.) cicl.md § Rules item 2 is what makes the magic ref the
    doctrine-sanctioned way to address an in-project service at all: "when
    services communicate over URLs, those URLs are built from provided fields
    at startup."
    """
```

Body:

1. `direct: dict[str, set[str]]` — dotted target → the dotted consumers holding a ref to
   it. Built from `_core_ref_targets` over every core service.
2. `used: dict[str, set[str]]` — dotted target → its dotted consumers, from
   `svc.core_uses()`. **Skip self-uses** (`(ref.codebase, ref.service) == (cb, svc)`);
   rule 25 owns that.
3. For each `dotted, consumers` in `sorted(used.items())`: resolve the target, skipping
   silently if the codebase or core service does not exist (rule 25 owns that too). Let
   `addressers = consumers & direct.get(dotted, set())` and
   `where = f"{_service_where(t_cb, t_svc)}.port"` — both arms' fix is on the target.
   1. **Positive arm.** `addressers and target.port is None` →
      `rule_32_direct_target_needs_port`. Message names the target, `sorted(addressers)`
      as the consumers that hold a magic ref to it, and says the target must declare the
      `port` those consumers build an address from.
   2. **Negative arm.** `not addressers and target.port is not None and "web" not in
      (target.networks or [])` → `rule_32_unaddressed_target_declares_port`. Message
      names the target, its port, `sorted(consumers)`, and states that none of them hold
      a magic ref to it — they reach it through a queue or broker — so the port is
      decoration and should be deleted.

The `web` guard carries this comment **verbatim in substance** (do not paraphrase it
away):

```py
            # WHY the `web`-network carve-out, which is NOT laxity: rule 15
            # requires a `port` on every web-network core service. A
            # `frontend.web` declaring `uses: [api.web]` reaches it by public
            # URL out of `config:` — a browser cannot resolve an internal
            # hostname — so it holds no magic ref, and an uncarved negative arm
            # would demand `api.web` drop the very port rule 15 requires. The
            # two rules would contradict each other on the doctrine's most
            # common two-codebase topology. Pinned by
            # test_surfaces.py::test_rule_32_web_target_reached_by_public_url_is_exempt.
```

Scope note to record in the docstring: both arms are keyed on being a `uses` **target**,
because that is the scope of the doctrine's sentence — a core service nobody uses may
declare a decorative `port`. Do **not** extend past that; the question is filed as
[`007_small_edges/rule_32_unused_target_port.md`](../../advances/007_small_edges/rule_32_unused_target_port.md).

### 2.7 Rule 33 — replaces rule 28

**Delete** `_validate_health_check_path_port` entirely, along with its section banner.
Add in its place:

```py
# ---------------------------------------------------------------------------
# Rule 33 (Mod 125) — `health_check_path` is a web-network field.
#
# Rule 28 is RETIRED (1.7.0) and its number tombstoned, never reused. It
# required a `port` alongside `health_check_path`. Rule 33 confines the field to
# `web`-network core services and rule 15 already requires a `port` on those, so
# the old obligation is REDUNDANT rather than merely obsolete — there is no
# document left in which it could fire.
# ---------------------------------------------------------------------------


def _validate_health_check_declaration(doc: CICLDocument) -> list[ValidationIssue]:
    """Rule 33: every `web`-network core service declares `health_check_path`,
    and no core service off the `web` network declares one.

    Keyed on NETWORK MEMBERSHIP, not on role. A `role: web` core service off
    the `web` network declares none: the field is what the reverse proxy probes
    (the ALB target group on elastic; on fixed traefik takes target health from
    the container healthcheck), and it is meaningless with nothing in front of
    the service. Required on both foundations regardless, so a project stays
    portable between them. See healthchecks.md § `web` services also serve
    GET /health.
    """
```

Body: for each core service, read `(svc.model_extra or {}).get("health_check_path")` —
the field is still role-specific and lands in `model_extra` — and `"web" in (svc.networks
or [])`.

- on web, value is `None` → `rule_33_web_service_needs_health_check_path`,
  `where=_service_where(...)`. Message: the reverse proxy has no path to probe; cite
  rule 33.
- off web, value is not `None` → `rule_33_health_check_path_off_web`,
  `where=f"{_service_where(...)}.health_check_path"`. Message: nothing routes to this
  core service, so there is no probe to declare a path for; a non-`web` core service's
  liveness is its container probe. Cite rule 33 and `healthchecks.md`.

---

## Step 3 — fixtures (five files)

These are the **measured** minimum: with them, the residual failures are all in
`tests/unit`. Do not make other fixture changes.

| Fixture | Edit |
| ------- | ---- |
| `sample_project` | `api.web` gains `health_check_path: /health` |
| `sample_project_elastic` | `api.web` gains `health_check_path: /health` |
| `sample_project_multi_fixed` | `api.web` gains `health_check_path: /health`; `reporter.worker` **loses** `health_check_path` |
| `sample_project_clock_fixed` | `api.web` gains `health_check_path: /health`; `worker` and `clock` **lose** `health_check_path`; `worker` gains `surfaces: {events: {api_styles: [events]}}` and **loses** `port: 8081` |
| `sample_project_clock_elastic` | same as `clock_fixed` |

On the clock fixtures, the existing comments above `worker`/`clock`'s `provides` block in
the *transfer tables* are not yours — but the fixture's own inline comments should not be
left claiming a port exists. Add a one-line comment on the clock fixtures' `worker` noting
its surface is `events` and that `api.clock` reaches it through a queue, which is why it
declares no `port` (rule 32).

Do **not** add `surfaces:` anywhere rules 29–33 do not force it. In particular
`api.web` in the non-clock fixtures is not a `uses` target and gains none — mod 126 is
what makes surfaces load-bearing for the contract gate.

---

## Step 4 — existing test corrections

Run `.venv/bin/python -m pytest tests/unit -q -p no:randomly` after step 3 and work the
list. The measured shape was **40 failed, 22 errors** across twelve files. All but the
six below are mechanical; the mechanical fixes are exactly three moves:

- an inline document's core service that is a `uses` target gains a `surfaces:` block
  (use `{events: {api_styles: [events]}}` for worker-ish targets, `{rest: {api_styles:
  [rest]}}` for web-ish ones — pick by what the service *is*, not by convenience);
- a `web`-network core service in an inline document gains `health_check_path: /health`;
- a non-`web` core service loses `health_check_path`, and a queue-reached `uses` target
  loses its `port`.

Affected files, for orientation: `test_service_expansion_emit`,
`test_service_connect_reconcile`, `test_uses_relation`, `test_worker_role`,
`test_exec_service_resolution`, `test_exec_service`, `test_validate`,
`test_service_nesting`, `test_clock`, `test_telemetry`, `test_pipeline_bootstrap`,
`test_hcl_emitter`.

### 4.1 The six non-mechanical items

**Delete outright** (rule 28 has no subject left):

1. `test_worker_role.py::test_health_check_path_without_port_rejected`
2. `test_worker_role.py::test_health_check_path_with_port_passes`
3. `test_worker_role.py::test_web_service_unaffected_by_rule_28`
4. the now-unused `_WORKER_DOC` constant and the `# 9-11. Rule 28 …` section banner
   above them. Also update the file's module docstring, which advertises "validation
   rule 28".

**Delete** (its premise is now unrepresentable):

5. `test_hcl_emitter.py::test_aws_lb_target_group_omits_health_check_when_no_field`. A
   `web`-network core service declaring no `health_check_path` is a rule-33 error, and
   only a `web`-network service gets a target group, so there is no document in which
   the assertion can be made. Leave a short comment where it stood saying rule 33 is
   what now guarantees the block is always present, and that
   `test_aws_lb_target_group_emits_health_check_from_target_extras` (which stays) is the
   surviving coverage.

**Invert**, do not delete:

6. `test_worker_role.py::test_worker_fixed_compose_healthcheck` and
   `::test_worker_elastic_container_healthcheck`. `_WORKER`'s injected worker loses
   `health_check_path` (rule 33), so no container probe is emitted for it at all. Rewrite
   each to assert the **absence** of the probe, and tag it:

   ```py
       # MOD 127: this asserts the interim state. When the probe moves into the
       # role tables' `defaults`, this becomes
       #   block["healthcheck"]["test"] == ["CMD", "./health.sh", "worker"]
       # (compose) / the container definition's healthCheck command (elastic).
       # The assertion is deliberately left FAILING-ON-CHANGE rather than
       # deleted: a deletion loses the coverage silently, and an xfail would flip
       # to XPASS, which reads as noise. This stops the suite at exactly the
       # moment attention is warranted.
   ```

   Also remove `health_check_path` from the `_WORKER` injection dict itself. `_WORKER`
   keeps `port: 8090` — the injected worker is nobody's `uses` target, so rule 32 is
   silent on it (see the filed scope brief).

   The tag string `MOD 127:` must be **greppable**: `grep -rn "MOD 127:" tests/` must
   find exactly these two, and nothing else in the repo may use that spelling for
   something other than a mod-127 handoff.

`test_clock.py::test_fixed_clock_is_an_ordinary_compose_service` asserts the clock's curl
healthcheck and will fail once the clock fixture loses `health_check_path`. Treat it as
a seventh inversion: assert no `healthcheck` key on the clock block, with the same
`# MOD 127:` tag naming `["CMD", "./health.sh", "clock"]`, and reword the docstring,
which currently claims a clock has "healthcheck, exactly as a `worker`".

---

## Step 5 — new tests

### 5.1 `tests/unit/test_surfaces.py` (new)

Module docstring: this file covers the CICL *surface* language landed by mod 125 — the
`Surface` model and rules 29, 30, 31, 32. State why 31 and 32 live here rather than in
`test_uses_relation.py`: both are consequences of the surface model (31 requires one; 32's
entire justification is what a consumer does with one), and `test_uses_relation.py` is
already dedicated to rules 7/25's one-relation merge.

Follow the conventions of `test_clock.py` / `test_uses_relation.py`: a `_VALID` YAML
string, `_doc()`, `_tables()`, and a `_rules(src)` helper returning `[i.rule for i in
validate_document(...)]`. **Every rule gets a red case and a green case.**

Model / table:

1. the bundled table agrees with `cicl.md § Surfaces` — assert `API_STYLE_FORMATS`
   equals the eight-row mapping literally, and that `IMPLEMENTED_CONTRACT_FORMATS ==
   {"openapi", "asyncapi"}`. This is the anti-drift pin on a transcribed doctrine table.
2. `api_styles: []` is a parse error (`pydantic.ValidationError`).
3. `api_style: [rest]` (singular) is a parse error — `extra="forbid"` catches the typo.
4. `surfaces:` absent leaves `svc.surfaces == {}`, and the document validates clean
   (a non-provider is legal — this is a clock's state).
5. an authored `surfaces:` block does **not** produce `tt_rule_4_undeclared_field`
   (the step-2.2 pin — the failure mode if `_STANDARD_SERVICE_FIELDS` is missed).
6. `Surface(api_styles=["rest", "stream", "webhook"]).formats() == {"openapi"}`.

Rule 29:

7. `[rest, stream, webhook]` → no issues.
8. `[rest, rpc]` → `rule_29_mixed_contract_formats`, and assert the message says to
   split into two surfaces.
9. `[bogus]` → `rule_29_unknown_api_style` and **no** `rule_29_mixed_contract_formats`.
10. `[graphql]` → `rule_contract_format_not_implemented`, and assert the message
    contains "not yet implemented" (this is the honesty of the boundary, per ruling 4).
11. `[grpc]` → same id, naming `proto`.
12. two surfaces of the same format on one core service (`rest_public` / `rest_admin`,
    both `[rest]`) → no issues. `cicl.md § Surfaces`' own worked case.

Rule 30:

13. a surface named `rest.public` → `pydantic.ValidationError` mentioning rule 30.
14. a surface named `rest_public` and one named `rest-public` → both accepted.

Rule 31:

15. `api.web uses api.worker`, worker declares `surfaces` → no
    `rule_31_uses_target_declares_no_surface`.
16. same, worker declares none → the rule fires.
17. a **backing** `uses` target is untouched by rule 31 (a backing service has no
    surfaces and never will) — `uses: [appdb]` raises nothing.
18. a typo'd core target (`api.wroker`) reports `rule_25_unresolved_uses` and **not**
    rule 31. This pins the reason rule 31 is nested in `_validate_uses`.

Rule 32:

19. **positive arm, red**: `api.web` holds `WORKER_HOST:
    ${codebases.api.core_services.worker.host}` and `uses: [api.worker]`; worker declares
    a surface and **no** `port` → `rule_32_direct_target_needs_port`.
20. **positive arm, green**: same document, worker declares `port` → no rule-32 issue.
21. **negative arm, red**: `api.clock uses [api.worker]` with **no** magic ref; worker
    declares a surface and `port: 8081` → `rule_32_unaddressed_target_declares_port`.
22. **negative arm, green**: same, worker declares no `port` → clean.
23. **the carve-out**, named exactly
    `test_rule_32_web_target_reached_by_public_url_is_exempt`: two codebases,
    `frontend.web uses [api.web]` with **no** magic ref (the URL comes from `config:`),
    `api.web` on `networks: [web, internal]` with a `port` and a `rest` surface → **no
    rule-32 issue**, and assert rule 15 is also silent. Docstring states the tension:
    without the carve-out rules 15 and 32 contradict each other here.
24. a ref in a **codebase-level** `env:` counts for every core service of that codebase
    (mirrors rule 7's clarification) — the target's port obligation holds.
25. a self-`uses` entry produces `rule_25_self_uses` only, no rule-32 verdict.

### 5.2 `tests/unit/test_validate.py`

Add rule 33 beside `test_rule_web_service_needs_port` (rule 15 is its sibling):

26. a `web`-network core service with no `health_check_path` →
    `rule_33_web_service_needs_health_check_path`.
27. the same service declaring it → clean.
28. a non-`web` core service declaring `health_check_path` →
    `rule_33_health_check_path_off_web`.
29. a non-`web` core service declaring none → clean.
30. **`role: web` off the `web` network declares none** — the rule keys on network
    membership, not role. Red if it declares one, green if it does not. This is the
    distinction the doctrine calls out explicitly and the one a reader will get wrong.

And a tombstone comment for rule 28 in the exact style of the existing rule-6 one
(around line 249), stating that rule 33 plus rule 15 make it redundant rather than
merely obsolete.

---

## Step 6 — verify

1. `.venv/bin/python -m pytest tests/unit -q` → green, and the count must be **≥ 1009
   plus the new tests minus the four deletions**. Report the exact number.
2. **Observe every new rule failing.** Not "the red test passes" — for each of
   `rule_29_unknown_api_style`, `rule_29_mixed_contract_formats`,
   `rule_contract_format_not_implemented`, rule 30's parse error,
   `rule_31_uses_target_declares_no_surface`, `rule_32_direct_target_needs_port`,
   `rule_32_unaddressed_target_declares_port`,
   `rule_33_web_service_needs_health_check_path`, `rule_33_health_check_path_off_web`:
   confirm the id appears in a real `validate_document` result and that the *message* is
   the one an author would need. Paste the nine messages into your report.
3. Confirm the carve-out test (#23) fails if the `web` guard is removed — comment the
   guard out, watch it go red, restore it. Report that you did this. An unpinned
   carve-out is the clause most likely to be "simplified" away.
4. `grep -rn "rule_28" src/ tests/` → only tombstone prose, no live code.
5. `grep -rn "MOD 127:" tests/` → exactly the three inverted assertions.
6. `.venv/bin/python -m pytest tests/unit -q` once more **without** `-p no:randomly`.

Do not run `pytest -m integration`, `docex compile` against `test_projects/`, or any
docker/AWS/git path. Nothing in this mod's territory touches them.

## Report back

- final unit count vs. the 1009 baseline, and the arithmetic that explains the delta;
- the nine rule messages from step 6.2, verbatim;
- confirmation of step 6.3 (carve-out observed failing);
- anything you had to decide that is not settled above — especially any test whose fix
  was not one of the three mechanical moves.
