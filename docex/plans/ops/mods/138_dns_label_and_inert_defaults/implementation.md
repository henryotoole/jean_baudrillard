# Mod 138 — Implementation steps

Executor: doctrine `mod-implementor`. Run all commands from `docex/`. The Python
interpreter is `docex/.venv/bin/python` (`python` is NOT on PATH). Do NOT touch core
planning docs (`plans/core/*`) — those are updated later by the CO in the docs step.
Do NOT commit — the CO handles commits.

This mod has three independent parts. Do them in order; each is self-contained.

---

## Part 1 — Project-name DNS-label enforcement

### 1a. Reject a non-conforming project name at load

File: `src/docex/cicl/model.py`, class `ProjectManifest` (around line 116-123).

Add a pydantic `field_validator` on `name` enforcing the pattern
`^[a-z0-9]([a-z0-9_-]*[a-z0-9])?$`. This permits lowercase alphanumerics with
interior hyphens/underscores (underscores are doctrine-sanctioned and converted to
hyphens by `dns_label`); it rejects uppercase and other characters that would make
the name compile to two spellings.

- Import `field_validator` from pydantic (check the existing import line; the module
  already imports `BaseModel, ConfigDict, Field`).
- Define a module-level compiled regex, e.g.:
  `_PROJECT_NAME_RE = re.compile(r"^[a-z0-9]([a-z0-9_-]*[a-z0-9])?$")` (add `import re`
  if absent).
- Add the validator raising a clear `ValueError` when the name does not match, e.g.:
  ```python
  @field_validator("name")
  @classmethod
  def _validate_name(cls, v: str) -> str:
      if not _PROJECT_NAME_RE.match(v):
          raise ValueError(
              f"project name {v!r} is not a valid DNS label: it must be "
              f"lowercase and match {_PROJECT_NAME_RE.pattern} (letters a-z, "
              f"digits, hyphen, underscore; underscores are converted to "
              f"hyphens when the name enters a data-plane identifier). A "
              f"mixed-case name compiles to two disagreeing spellings of its "
              f"own project segment."
          )
      return v
  ```
- `context.py::_load_project_manifest` already wraps `PydanticValidationError` into
  `ProjectManifestError`, so no change is needed there. Confirm by reading it.

### 1b. Thread `project_dns_label` into HCL template context

File: `src/docex/emit/hcl.py`.

- Add `dns_label` to the `from docex.naming import (...)` block (around line 47-52).
- In `emit_hcl` (env-tier `main.tf`), add to the `tpl.render(...)` kwargs (around
  line 1359-1383): `project_dns_label=compiled.project_dns_label,`. The field
  already exists on `CompiledEnv` — do not recompute it.
- In `emit_hcl_project` (project-tier `project.tf`), the function receives `project`
  as a raw string. Compute `project_dns_label = dns_label(project)` near where
  `project_subdomain` is computed (around line 1210), and add
  `project_dns_label=project_dns_label,` to the `tpl.render(...)` kwargs (around line
  1278-1300).

### 1c. Change the four template sites to read `project_dns_label`

Replace the inline re-derivations. Exact edits:

- `src/docex/emit/templates/project.tf.j2:325`
  - from: `  name        = "{{ project | replace('_', '-') }}-traefik"`
  - to:   `  name        = "{{ project_dns_label }}-traefik"`
- `src/docex/emit/templates/main.tf.j2:63`
  - from: `  name        = "{{ project | replace('_', '-') }}-{{ env }}-{{ short }}"`
  - to:   `  name        = "{{ project_dns_label }}-{{ env }}-{{ short }}"`
- `src/docex/emit/templates/main.tf.j2:128`
  - from: `  name        = "{{ project | replace('_', '-') | lower }}-{{ env }}"`
  - to:   `  name        = "{{ project_dns_label }}-{{ env }}"`
- `src/docex/emit/templates/main.tf.j2:130`
  - from: `  description = "ECS Service Connect namespace for {{ project | replace('_', '-') | lower }} {{ env }}"`
  - to:   `  description = "ECS Service Connect namespace for {{ project_dns_label }} {{ env }}"`

After editing, verify no inline project-segment re-derivation remains:
```sh
grep -rn "replace('_', '-')\|replace(\"_\", \"-\")" src/docex/emit/templates/
```
Expected: no hits in `main.tf.j2` / `project.tf.j2` for the project segment. (Other
templates/uses unrelated to the project segment, if any, are out of scope — but
these two files should show none for `project`.)

### 1d. Tests for Part 1

File: `tests/unit/test_naming_policy_leak.py` (extend — it already builds an
underscored project and asserts hyphenated HCL output).

- Add a test that calls `emit_hcl_project(project="My_Proj", ...)` (mixed case +
  underscore, bypassing model validation since the emitter takes a raw string) and
  asserts the emitted `project.tf` contains `my-proj-traefik` and NOT `My-proj` /
  `My_Proj` / any uppercase in the traefik resource name.
- Add a test that builds a `CompiledEnv` with `project="My_Proj"` and
  `project_dns_label="my-proj"`, runs `emit_hcl`, and asserts the emitted `main.tf`
  uses `my-proj-<env>` for the Service Connect namespace and `my-proj-<env>-<short>`
  for the SG names — one spelling, lowercased, no uppercase leak. Reuse the file's
  existing `_policies()` / CompiledEnv construction helpers.

File: `tests/unit/` — a new small test (or add to an existing model/manifest test)
for the rejection:
- `ProjectManifest.model_validate({"name": "MyProject", "version": "0.0.1",
  "docex_version": "..."})` raises `pydantic.ValidationError`.
- `ProjectManifest.model_validate({"name": "docex_smoke_elastic", ...})` and
  `{"name": "sample", ...}` and `{"name": "my-proj", ...}` and `{"name": "a", ...}`
  all succeed.
  (Look for an existing manifest/model test file; if none, add
  `tests/unit/test_project_manifest.py`.)

---

## Part 2 — Inert elastic defaults: delete + fail-loud guard

### 2a. Delete the dead keys from the three core roles

Remove the two lines `launch_type: FARGATE` and `network_mode: awsvpc` from the
`defaults.elastic` block of each of:
- `tables/roles/web.yml` (lines ~41-42)
- `tables/roles/worker.yml` (lines ~44-45)
- `tables/roles/clock.yml` (lines ~58-59)

After removal, each role's `defaults.elastic` block should begin directly with the
comment above `healthCheck:` and then the `healthCheck:` mapping. Do NOT remove the
`healthCheck:` block or its explanatory comments. Keep YAML indentation valid.

### 2b. Update the `INERT:` comment in the renderer

File: `src/docex/emit/hcl.py`, the comment block at ~lines 384-397 inside
`render_task_definition`. It currently says `launch_type`/`network_mode` "sit in all
three core roles' `defaults.elastic` and are read by nothing". Update it to state
that those keys have been **removed** from the tables (mod 138) and that a
compile-time guard now rejects any unread `defaults.elastic` key on the
task-definition path, so the class of inert key cannot return. Keep the surrounding
`WHY an explicit read and not a body merge` rationale and the `healthCheck` read
unchanged.

### 2c. Add the closed read-set constant

File: `src/docex/emit/hcl.py`, adjacent to `render_task_definition` (module level,
just above the function is fine). Add:
```python
# The closed set of `defaults.elastic` keys the ECS task-definition / service
# renderer reads off the merged service body. `image`, `command`, and the
# cpu/memory/ephemeral_storage sizing are injected by the compiler (see
# compile.py's elastic branch and _resources_to_fixed); `healthCheck` comes
# from the role table's defaults.elastic. FARGATE / awsvpc are compiler-owned
# literals, not table keys. This set is the guard's known-read set: the
# compile-time guard (compile.py) rejects any defaults.elastic key NOT here on
# a task_definition-target engine, so an inert key (mod 127's healthCheck
# near-miss) cannot ship silently. If you add a new read below, add it here.
TASK_DEF_DEFAULT_READ_KEYS = frozenset(
    {"cpu", "memory", "ephemeral_storage", "image", "command", "healthCheck"}
)
```
(Confirm these six are exactly what the function reads via `body.get(...)`:
`cpu` ~L328, `memory` ~L329, `ephemeral_storage` ~L330, `image` ~L353,
`healthCheck` ~L395, `command` ~L431.)

### 2d. Add the compile-time guard

File: `src/docex/cicl/compile.py`, in the per-service compile loop (the `for name,
svc, cb_name, svc_name in work:` loop). `default_target` is already computed as
`default_target = engine.default_target(foundation)` (around line 800). Immediately
after that line, add the guard:

```python
# Mod 138: fail loud on an inert `defaults.elastic` key. The ECS
# task-definition renderer reads a NAMED, closed set of keys off the merged
# body (emit/hcl.py::TASK_DEF_DEFAULT_READ_KEYS) — it does NOT merge the block
# generically the way the fixed compose path does. A key outside that set
# would fall on the floor with no warning (mod 127's healthCheck near-miss:
# it would have shipped a fleet with no container probe). Scope: only the ECS
# task-definition path, so backing engines' rich defaults.elastic (RDS
# instance_class, storage, encryption, ...) route to their own renderers and
# are untouched.
if foundation == "elastic" and default_target == "task_definition":
    stray = set(engine.defaults_for("elastic")) - TASK_DEF_DEFAULT_READ_KEYS
    if stray:
        raise ValidationError([ValidationIssue(
            rule="rule_elastic_defaults_unread_key",
            message=(
                f"engine {engine.engine!r} of role {engine.role!r}: "
                f"defaults.elastic contains key(s) {sorted(stray)} that the "
                f"ECS task-definition renderer does not read. It reads only "
                f"{sorted(TASK_DEF_DEFAULT_READ_KEYS)}. Remove the key(s), or "
                f"route them through a `fields:` translation with a `target:`."
            ),
            where=f"tables/roles/{engine.role}.yml defaults.elastic",
        )])
```
- Import `TASK_DEF_DEFAULT_READ_KEYS` from `docex.emit.hcl` at the top of
  `compile.py` (check the existing `from docex.emit ...` imports; add there or a new
  import line). `ValidationError` / `ValidationIssue` are already imported.
- `engine` and `default_target` are already in scope at that point in the loop.

### 2e. Tests for Part 2

Add to `tests/unit/test_transfer.py` (or a new `tests/unit/test_elastic_defaults_guard.py`):
- Construct an `EngineEntry` (mirror how `test_transfer.py` builds one) with
  `emits={"elastic": ["task_definition"]}` and `defaults={"elastic": {"healthCheck":
  {...}, "bogus_key": 1}}`, drive it through `compile_env` on a minimal elastic
  project (or call the smallest path that reaches the guard), and assert a
  `ValidationError` whose issue rule is `rule_elastic_defaults_unread_key` and whose
  message names `bogus_key`.
  - If wiring a full `compile_env` is heavy, instead unit-test the guard predicate
    directly: assert `set(engine.defaults_for("elastic")) -
    TASK_DEF_DEFAULT_READ_KEYS` is non-empty for the bogus engine and empty for one
    whose only key is `healthCheck`. Prefer driving `compile_env` if a nearby
    fixture makes it cheap; otherwise the predicate-level test plus the full-suite
    run below is sufficient.
- Assert the same engine with `defaults.elastic == {"healthCheck": {...}}` produces
  no stray key.
- The three shipped core tables passing clean is covered by the full suite.

---

## Part 3 — Doctrine prose (two surgical edits)

### 3a. `healthchecks.md` rule-32 softening (brief 3)

File: `doctrine/infrastructure/healthchecks.md`, the bullet at line 97 under
`## What this doctrine does not do`.

- from:
  `- **No HTTP requirement for non-\`web\` services.** A core service needs a \`port\` only when something addresses it directly. Health is not such a thing.`
- to:
  `- **No HTTP requirement for non-\`web\` services.** A core service is required to declare a \`port\` only when another service addresses it directly, and health never does. (\`docex\` scopes this narrowly: [CICL rule 32](./cicl.md#validation-rules) requires a \`port\` only on a \`uses\` target a consumer addresses directly — a core service nobody uses may still carry a decorative one.)`

This softens the universal "a core service needs a port only when..." to match what
rule 32 actually enforces, preserving the bullet's point (health imposes no port).
Do not touch any other bullet. Confirm the `#validation-rules` anchor exists in
`cicl.md` (grep for the heading); if the exact slug differs, use the correct one.

### 3b. `transfer_tables.md` `defaults` asymmetry (brief 2)

File: `doctrine/infrastructure/specifics/transfer_tables.md`, the `- **\`defaults\`**
(required) — ...` field-reference bullet (around line 291).

Append one sentence documenting the fixed/elastic asymmetry (do not rewrite the
bullet):

- Current bullet ends with:
  `... \`defaults:\` cannot route to a non-default target — that's what \`fields:\` translations with \`target:\` are for.`
- Append after that sentence:
  ` The merge is **generic on fixed** — the whole block lands on the compose service — but **not on elastic's \`task_definition\` target**: that renderer reads a named, closed set of keys (\`cpu\`, \`memory\`, \`ephemeral_storage\`, \`image\`, \`command\`, \`healthCheck\`) and \`docex compile\` **rejects** any other \`defaults.elastic\` key rather than merging it (\`requires_compatibilities\`/\`network_mode\` are compiler-owned invariants, not table knobs).`

---

## Final verification

Run both suites synchronously in the foreground from `docex/`:

```sh
.venv/bin/python -m pytest tests -q                 # default suite (~5.5 min)
.venv/bin/python -m pytest tests -q -m integration  # integration, ALONE (~8 min)
```
(Use `python -m pytest`, never bare `pytest`. The default suite is `tests`, not
`tests/unit`.)

Baseline before this mod: default **1215 passed, 21 deselected**; integration **21
passed, 1215 deselected**. This mod ADDS tests, so the default passed-count should
rise; nothing should go red. The integration count should be unchanged (no
integration tests added) unless you added one — you should not need to.

Report: both final counts, and confirm the `grep` in step 1c shows no remaining
inline project-segment re-derivation.
