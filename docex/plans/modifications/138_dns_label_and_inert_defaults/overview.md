# Mod 138 — Project-name DNS-label enforcement, inert elastic defaults, rule-32 prose

Advance 008 ("Housekeeping"). Three briefs, all rulings fixed at plan review; this
mod implements them as stated. Briefs live in
`plans/advances/008_housekeeping/references/`.

## Goal

1. **`project_name_dns_label_divergence.md`** — a mixed-case project name compiles to
   two disagreeing spellings of its own project segment, because four HCL template
   sites re-derive the segment inline and two lack `| lower`. Reject a
   non-conforming project name at entry, and thread `project_dns_label` into HCL
   template context so all four sites read the one shared expression.
2. **`inert_elastic_defaults.md`** — `launch_type`/`network_mode` in the three core
   roles' `defaults.elastic` are read by nothing (the emitter hardcodes both).
   Delete them (Answer A), and add a fail-loud compile guard rejecting any
   `defaults.elastic` key no renderer reads on the ECS task-definition path
   (Answer C).
3. **`rule_32_unused_target_port.md`** — won't-fix on code. Soften one prose bullet
   in `healthchecks.md` that overstates rule 32's `uses`-target scoping.

## Design

### 1. Project-name DNS-label (reject at entry + thread `project_dns_label`)

**Rule of record confirmed.** `cicl.md § Domain` puts `<project_name>` in the
domain as a DNS segment; `cicl.md` (Networks) states an underscored project name is
converted to hyphens when a name is formed; `transfer_tables.md`'s `http_host`
policy is the DNS-label rule (hyphen + lower). `naming.dns_label`
(`naming.py:127`) is the single source of the underscores→hyphens, lowercase rule.
So this mod aligns names to an existing doctrine rule; it does not invent one.

**What "reject at entry" must and must not reject.** The defect is *case*: all four
template sites already `replace('_','-')`, so underscores are handled uniformly and
never cause identity divergence; only the missing `| lower` at two sites does.
Underscored project names are explicitly doctrine-sanctioned and in active use —
the test projects are literally named `docex_smoke_elastic`, and `dns_label`'s own
docstring celebrates converting it. Therefore the entry validation must **reject
uppercase (and other non-label characters) while permitting underscores** as
word separators. A strict RFC-1123 label pattern (which forbids underscores) would
break the smoke walk and contradict `cicl.md`; that reading is rejected as
incoherent. The coherent reading of the brief's "`dns_label` idempotent" is
"idempotent up to the doctrine-sanctioned underscore↔hyphen substitution", i.e. the
name carries no uppercase and no other character that would change its identity.

- **Pattern:** `^[a-z0-9]([a-z0-9_-]*[a-z0-9])?$` (single-char names allowed via the
  optional inner group). Lowercase alphanumeric start/end; interior `-`/`_`. This
  rejects `MyProject`; accepts `docex_smoke_elastic`, `sample`, `my-proj`, `a`.
- **Where:** `ProjectManifest.name` (`cicl/model.py:122`), enforced with a pydantic
  `field_validator` raising a clear message. `context.py::_load_project_manifest`
  already wraps `PydanticValidationError` → `ProjectManifestError`, so the message
  surfaces cleanly at load, and the name fails its next `compile`/`check`.
- **Thread `project_dns_label` into HCL context.** `emit_hcl` passes
  `project_dns_label=compiled.project_dns_label` (the field already exists on
  `CompiledEnv`). `emit_hcl_project` computes `dns_label(project)` (import
  `dns_label` into `emit/hcl.py`) and passes it. The four sites then read
  `{{ project_dns_label }}`:
  - `project.tf.j2:325` → `{{ project_dns_label }}-traefik`
  - `main.tf.j2:63` → `{{ project_dns_label }}-{{ env }}-{{ short }}`
  - `main.tf.j2:128` → `{{ project_dns_label }}-{{ env }}`
  - `main.tf.j2:130` → `{{ project_dns_label }} {{ env }}` (description string)
  The *number of re-derivations* is the defect; equalizing values is not the fix.

### 2. Inert elastic defaults (delete dead keys + fail-loud guard)

- **Delete** `launch_type: FARGATE` and `network_mode: awsvpc` from
  `tables/roles/{web,worker,clock}.yml` `defaults.elastic`. After deletion each
  core role's `defaults.elastic` holds only `healthCheck`. `requires_compatibilities
  = ["FARGATE"]` / `network_mode = "awsvpc"` remain compiler-owned literals in
  `render_task_definition` / the service renderer; the `INERT:` comment at
  `hcl.py:386-397` is updated to say the keys are now *gone* (and the guard forbids
  their return).
- **Fail-loud guard.** A closed set of the keys the ECS task-definition/service
  renderer reads off the merged `body` — **confirmed against `emit/hcl.py`**:
  `cpu`, `memory`, `ephemeral_storage`, `image`, `command`, `healthCheck`. Pinned as
  a named constant in `emit/hcl.py` adjacent to `render_task_definition`
  (e.g. `TASK_DEF_DEFAULT_READ_KEYS`) with a comment naming it the renderer's
  known-read set, so a future author who adds a read updates it in the same place.
  The compile-time guard rejects any `defaults.elastic` key **not** in that set, and
  is **scoped to engines whose elastic default target is `task_definition`** — i.e.
  the three core roles only. Backing engines (`rds_instance`, `elasticache`,
  `s3_bucket`, …) route to other renderers with their own rich `defaults.elastic`
  (instance class, storage, encryption) and are **out of scope** — the guard must
  not false-positive on them. Scoping key: `engine.default_target("elastic") ==
  "task_definition"`. Error names the engine and offending key.

### 3. Rule-32 prose softening (doctrine, brief 3)

`healthchecks.md § What this doctrine does not do` overstates rule 32's
`uses`-target scoping. Minimal one-bullet softening (exact wording reported to CO in
the final report). No `validate.py` change.

## Doctrine edits (both pre-approved in principle; minimal/surgical)

- `healthchecks.md § What this doctrine does not do` — rule-32 softening (brief 3).
- `transfer_tables.md § Anatomy of a Role Definition`, the `defaults` field-reference
  bullet — document the fixed/elastic asymmetry: the merge is generic on fixed (whole
  block → compose service) but on elastic's `task_definition` target the renderer
  reads a named closed set and rejects other keys, rather than merging generically.
  One appended sentence; the section is not rewritten.

Both edits stay within their rulings' intent; no escalation triggered.

## Drift / artifact alignment (six live artifacts)

- **Doctrine (rule of record):** the two edits above.
- **`plans/core/compiler.md`:** § *Output layout* currently books the four-site
  divergence as an unfixed defect ("Do not add a fifth re-derivation") — rewrite to
  FIXED (project_dns_label threaded, four sites read it). Add the project-name
  load-time validation and the `defaults.elastic` closed-set guard to § Validation.
  Check `masterplan.md`.
- **Transfer tables:** `tables/roles/{web,worker,clock}.yml` (deletions).
- **src + tests:** as above.
- **`doctrine_excerpts/` + `index.yml`:** no resource introduced/retired — confirm,
  don't assume (expected: no change).

## Tests (unit sufficient)

1. Project-name rejection: `ProjectManifest.model_validate({name:"MyProject", …})`
   raises; underscored `docex_smoke_elastic` and plain `sample` pass.
2. One project spelling: extend `test_naming_policy_leak.py` — call `emit_hcl` /
   `emit_hcl_project` with a mixed-case raw project + correct `project_dns_label`;
   assert all four HCL sites render the lowercased, hyphenated spelling and no
   uppercase leaks.
3. `defaults.elastic` guard: an engine with elastic target `task_definition` and a
   stray key is rejected; the same engine with only the closed-set keys passes; the
   three shipped core tables compile clean (full suite).

## Design questions

None. All three rulings are fixed; gating checks (rule of record exists; both
doctrine edits achievable minimally) pass.
