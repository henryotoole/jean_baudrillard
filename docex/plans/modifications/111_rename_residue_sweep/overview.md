# Mod 111 — Rename residue sweep

Finish the [codebase / core-service rename](../../advances/005_process_type_solidification/codebase_core_service_rename.md)
inside `docex` itself. The 1.7.0 rename moved the doctrine, the authored CICL
surface, the emitted surface, and the model classes; it left behind a layer of
**comments, docstrings, terminal output, and local identifiers** that still speak
the retired vocabulary — and, in a handful of places, speak it *wrongly enough to
mislead an operator*.

> **Status.** Design settled; three forks resolved with the operator (see
> [Decisions](#decisions)). No open questions.
> Behavior-preserving by construction: no emitted artifact changes except one
> `describe --format llm` JSON key that the rename plan already committed to.
> `cicl_version` stays `"2"` — the 2 → 3 bump is a later mod's and is explicitly
> **not** in scope here.

## Why this is a mod and not a typo pass

Three of the findings are defects rather than cosmetics, and they share a root
cause: a mechanical sweep that substituted the *word* without re-reading the
*sentence*.

**A doubled substitution produced text that says nothing.** `cicl/model.py`'s
migration error reads "moved from the core service to the core service in CICL
v2" — the same noun on both sides of a sentence whose whole job is to distinguish
two levels. This one **prints to the operator**, on the single error every
downstream project hits exactly once while upgrading.

**Terminal output now names the wrong kind of thing.** `docex build nonexistent`
answers `service 'nonexistent' is not a core service; known core services: ['api',
'reaper']` — but that list is `codebases(ctx)`, so every name it offers is a
codebase. Same class in `orchestrate/_common.py`, whose exec-key failure says "it
is not a core service in infra.yml, declares no core service" for what is a
codebase declaring core services. An operator who trusts these messages goes
looking in the wrong half of `infra.yml`.

**One emitted key was missed outright.** `describe --format llm` still emits
`"core_service": svc.codebase`. The rename plan's emitted-surface table lists
this key as moving to `codebase`; it did not move. The JSON therefore labels a
codebase as a core service, in the one output format whose entire audience is a
machine or an agent reading it as truth.

Underneath those, ~100 call sites carry `svc`/`svc_name` for a **codebase** and
`proc` for a **core service** — the exact inversion the rename existed to
eliminate. `CICLDocument.all_core_services()` returns
`(codebase_name, service_name, codebase, core_service)` and nearly every consumer
unpacks it as `for svc_name, service_name, _svc, proc in …`. That is not merely
untidy: the next person to touch `validate.py` reads `svc` and reasonably
concludes it is a service.

And one name is inverted against its own contents:
`validate.py::_STANDARD_SERVICE_FIELDS` holds `{core_services, secrets, config,
env}` — the **codebase**-level field set — while the service-level set sits in
`_STANDARD_PROCESS_FIELDS`. Renaming the latter to its correct name collides with
the former, so these two must move as a **swap**, not as two independent renames.

## What changes

### 1. Botched substitutions — text that is now nonsense

| Site | Current | Becomes |
| ---- | ------- | ------- |
| `cicl/model.py:188` | comment: "moved from the core service to the core service" | "moved from the codebase to the core service" |
| `cicl/model.py:230` | **operator-facing** error, same phrase | same fix |
| `cicl/compile.py:659` | "Core core services have a single engine per role" | "Core services have…" |
| `cicl/compile.py:826` | "Core core service never publish a host port" | "Core services never publish…" |
| `cicl/validate.py:228` | "Core core services have a single canonical engine" | "Core services have…" |

`tests/unit/test_service_nesting.py:201` asserts the broken phrase is *absent*
from the v1 message. The assertion string was rewritten by the same sweep, so it
currently passes by coincidence — it must move in lockstep with `model.py:230` or
the test silently stops asserting anything.

### 2. Operator-facing output

| Site | Fix |
| ---- | --- |
| `orchestrate/build.py:81-83` | "is not a core service; known core services:" → codebase wording |
| `orchestrate/_common.py:213` | "core service {cb}: its core service resolve to…" → "codebase {cb}: its core services resolve to…" (noun **and** agreement) |
| `orchestrate/_common.py:248` | "not a core service in infra.yml, declares no core service" → codebase / core services |
| `__main__.py:36` | `build` help: "one or all core services" → codebases |
| `__main__.py:41` | `containerize` help: "core service prod images" → codebase images |
| `__main__.py:388-389` | positional `service` → `codebase`; help text likewise |
| `errors.py:135` | `BuildxFailed`: "for a core service" → "for a codebase" |
| `cicl/validate.py:1408-1414` | "process name X (on core service Y)" → "core service name X (on codebase Y)"; host form `<service>-<process>` → `<codebase>-<service>` |
| `cicl/model.py:353` | the same message in the pydantic name validator |
| `cicl/magic_refs.py:185` | "references the process" → "references the core service" |
| `cicl/magic_refs.py:159` | "has no core service" → "has no core services" |

`docex build`'s positional is renamed `service` → `codebase`. Positionals carry
no name on the command line, so this is a help-text and internal-parameter change
with **no CLI compatibility surface**; `run_build`'s keyword moves with it.

### 3. `cicl/model.py` — the v1 rejection message

Per [decision 1](#decisions), rewritten to describe the generation the parser
**actually accepts today** and to chain both guides:

```
cicl_version '1' is no longer supported. The current generation nests a
`core_services:` block under each entry in `codebases:`, and adds the `consumes`
relation and five-segment core magic refs
(${codebases.<cb>.core_services.<svc>.<part>}). Follow upgrades/upgrade_1.6.0.md
then upgrades/upgrade_1.7.0.md to migrate this infra.yml, then set
cicl_version: "2".
```

`CURRENT_CICL_VERSION` stays `"2"`. The message previously described 1.6.0's v2
(four-segment refs, `core_services:` at top level) while the parser enforces
1.7.0's v2 — so an operator who followed it landed on a document the compiler
rejects. `upgrades/upgrade_1.7.0.md` is a pre-cut fragment, but it is the
document that explains the shape, so citing it is correct even before the guide
is finalized.

### 4. `describe --format llm` — the missed key

`describe/llm.py:45`: JSON key `core_service` → `codebase`. This is a **deliberate
emitted-output change**, mandated by the rename plan's emitted-surface table and
its adjudication note E2. The sibling `"service"` key is already correct, so
after this the node carries `codebase` + `service` — the same two axes, named the
same way, as the elastic tag block and the two `docex.*` OTel attributes.

### 5. Identifiers

The mechanical core. All internal to `docex`; none reaches an emitted artifact.

| Old | New | Sites |
| --- | --- | ----- |
| `svc_name` / `svc` / `_svc` naming a **codebase** | `cb_name` / `cb` | the ~20 `all_core_services()` unpackings in `cicl/validate.py`, `cicl/compile.py`, `pipeline/check.py` |
| `proc` naming a **core service** | `svc` | same loops, plus `_effective_env`, `_resolve_service`'s return |
| `procs` (a codebase's core services) | `svcs` | `emit/compose.py`, `emit/hcl.py`, `emit/ansible.py` |
| `t_svc, t_proc_name, t_proc` | `t_cb, t_svc_name, t_svc` | `pipeline/check.py:504, 525` |
| `_STANDARD_SERVICE_FIELDS` (holds codebase fields) | `_STANDARD_CODEBASE_FIELDS` | `cicl/validate.py` — **swap, see below** |
| `_STANDARD_PROCESS_FIELDS` (holds service fields) | `_STANDARD_SERVICE_FIELDS` | `cicl/validate.py` |
| `_validate_process_role_rules` | `_validate_service_role_rules` | `cicl/validate.py:115, 1496` |
| `_MOVED_TO_PROCESS` | `_MOVED_TO_SERVICE` | `cicl/model.py:190, 227` |
| `default_process_compiled` | `default_service_compiled` | `cicl/compile.py:383, 390, 412, 732, 1036` |
| `CompiledService.service_env` | `.codebase_env` | dataclass + `emit/compose.py`, `emit/hcl.py`, `cicl/compile.py`, tests |
| `core_service_names` | `codebase_names` | `emit/hcl.py:1201-1320`, `emit/templates/project.tf.j2` (4 sites), `cicl/compile.py:1320`, 3 test call sites |
| `services_with_schema` | `codebases_with_schema` | `orchestrate/_common.py:140` + call sites in `orchestrate/{migrate,test,up}.py` |
| `_service_where(svc_name, service_name)` | `(cb_name, svc_name)` | `cicl/validate.py:67` |

**The two `_STANDARD_*` constants swap names.** `_STANDARD_SERVICE_FIELDS`
currently holds the codebase-level set and `_STANDARD_PROCESS_FIELDS` the
service-level set. Renaming either alone either collides or silently swaps which
field set a rule enforces. They must be edited together, and the rule-22 /
rule-4 field-scoping tests are what prove the swap landed the right way round.

`CompiledService.codebase_env` is the one rename with a doc consequence:
`plans/core/compiler.md` documents it as `service_env` in prose and in a table,
so that doc moves with the field.

### 6. Prose residue

~55 comment/docstring sites in `src/` and one in `tables/roles/worker.yml`, plus
the `<svc>.<proc>` placeholder form wherever it appears (→ `<codebase>.<service>`)
and `core/<svc>/` (→ `core/<codebase>/`). Also the wrong-direction cases where a
per-codebase operation is described as per-core-service: `aws/client.py:246`,
`pipeline/rollback.py:10,328`, `pipeline/containerize.py:8,59`,
`pipeline/check.py:660`, `emit/compose.py:565`, `orchestrate/build.py:46,48`,
`orchestrate/test.py:9`, `orchestrate/_common.py:10,95,103`,
`tables/roles/worker.yml:13` (`image:` is derived per **codebase**, not
per-core-service — `cpu`/`memory`/`tmpfs` are correctly per-service).

Section headings move too: `cicl/compile.py:504`'s `--- Process expansion ---`
becomes `--- Service expansion ---`.

Two deliberate keeps:

- `emit/tags.py:48-50` explains byte-stability *across* the rename and must name
  the old `(service, process)` pair to make its argument. Historical reference,
  retained.
- Everything matching the protected-token list (`subprocess*`, `processor*`,
  `processed`/`processing`, `docex_process`, 12-factor "processes", and the ~15
  `"Returns process exit code"` docstrings) is untouched. Post-sweep counts are a
  verification step.

### 7. `docex why codebase`

Per [decision 2](#decisions), add `doctrine_excerpts/codebase.md` and its
`index.yml` entry. `core_service.md` already describes the deployment unit
correctly; the primary noun of the doctrine's service vocabulary currently has no
excerpt at all, so `docex why codebase` answers nothing. The excerpt states: one
source tree, one build artifact, one image; never imports from another codebase;
declares one or more core services; the unit of *code* against the core service's
unit of *deployment*; and what stays codebase-keyed (image ref, ECR repo,
`schema_owned_by`, `core/<codebase>/`). It is the only net-new content in the mod.

### 8. Tests

135 residual hits. Fixture and helper names carry the old vocabulary
structurally, so they move with the code: `_WEB_PROCESS`, `_WORKER_PROCESS`,
`_with_process_block`, `_two_process_doc`, `_multi_process_project`, and test
function names like `test_1_processes_absent_rejected`,
`test_18_reserved_process_name_rejected`,
`test_28_fixed_all_processes_share_one_image`. The two file *renames* already
landed in the rename mod; only their contents lag.

Densest: `test_service_nesting.py` (38), `test_service_expansion_emit.py` (21),
`test_hcl_emitter.py` (15), `test_containerize_real.py` (17),
`test_merge_real.py` (15), `test_check_real.py` (12),
`integration/conftest.py` (11), `test_validate.py` (10).

No new tests are added — the mod adds no behavior. The existing suite is the
regression harness, which is exactly why the identifier pass must be a
same-commit mechanical rename rather than a rewrite.

### 9. `docex`'s own core docs

`plans/core/compiler.md` is the worst-affected working file: `## Process
expansion` is still a heading, and lines 104-105 document
`CompiledService(name="api-web", core_service="api", process="web")` — field
names that no longer exist. Also stale: the `service_env` prose (134-160),
`all_processes()` / `CoreService is extra="forbid" over {processes,…}` /
`ProcessType is extra="allow"` in the navigation table (503-505),
`ProcessType.consumes_refs()` and `ProcessRef` (490-491), `<svc>-<proc>` forms
(166, 301-303), and the per-codebase-artifact prose (235-317).

Plus `masterplan.md:8` ("single-process tool" — the OS sense, **keep**), `:165`
and `:243-245` (`<svc>.<proc>`, "process-keyed"), and `release_flow.md:89, 199`
(`services_with_schema` returning "core services"; "probes every core service").

Per the [five-artifact alignment](../../core/docex_process.md#additional-artifacts)
these are step-8 documentation work, not implementation work — the implementation
doc must not instruct the executor to touch them.

## Explicitly out of scope

- **`CURRENT_CICL_VERSION`.** Stays `"2"`. The 2 → 3 bump rides with
  `uses_relation_merge` in a later mod, per the operator. Nothing here touches
  the constant, the test projects' `cicl_version:`, or `cicl.md`'s statement of it.
- **`plans/modifications/**` and `upgrades/upgrade_{1.2.0,1.5.0,1.6.0,1.6.1}.md`.**
  Frozen by the rename plan's [blast-radius](../../advances/005_process_type_solidification/codebase_core_service_rename.md#frozen--historical-records)
  reasoning: rewriting a record of what was designed at the time falsifies it.
- **Both test projects' `CHANGELOG.md`.** Frozen by
  [decision 3](#decisions) on the same reasoning — a changelog entry describes a
  release in the vocabulary that release used.
- **`doctrine/**`.** Verified clean: every remaining `process` hit in the
  doctrine is the workflow or OS sense. This mod is step 2 of the
  [docex process](../../core/docex_process.md) with no step-1 doctrine change.
- **The `scheduler` shape.** Per the rename plan's resolved item 2, a scheduler
  core service is still named after its job rather than its role. Reword around
  it; do not "fix" it.

## Verification

A green suite is necessary but not sufficient — the suite would stay green if an
identifier and its every reader moved together but moved wrongly. Four checks:

1. **Unit suite green.** The load-bearing gate for the identifier pass.
2. **Compiled output byte-identical.** Compile both test projects before and
   after; the only permitted difference anywhere is the `describe --format llm`
   `core_service` → `codebase` key, which is not compiled output at all — so the
   compile diff must be **empty**. Any change to a container name, tag value,
   domain label, image ref, or contract path is a defect.
3. **Protected-token counts unchanged** against `git stash`/`HEAD`:
   `subprocess*`, `processor*`, `processed`/`processing`, `docex_process`, and
   the `"process exit code"` docstrings.
4. **No inverted identifier survives.** `grep` for `svc_name` / `svc` /
   `_svc` / `proc` in the `all_core_services()` unpackings and confirm each now
   reads `cb`/`svc`; confirm `_STANDARD_CODEBASE_FIELDS` holds
   `{core_services, secrets, config, env}` and not the service-level set.

## Decisions

Settled with the operator before drafting.

| # | Question | Decision |
| - | -------- | -------- |
| 1 | The v1 rejection message describes 1.6.0's v2 while the parser enforces 1.7.0's v2 | **Describe current v2, cite both guides** as a chain (`upgrade_1.6.0.md` → `upgrade_1.7.0.md`). Accurate today; the 2 → 3 mod rewrites it again regardless. |
| 2 | `docex why codebase` has no excerpt | **Add `codebase.md` this mod**, indexed. The doctrine's primary noun should answer. |
| 3 | Both test projects' `CHANGELOG.md` still say "process types" | **Freeze.** A changelog entry records a release as it shipped; keepachangelog convention does not revise past entries. |

## Design questions

None outstanding.
