# Mod 111 — Implementation

Execute the rename-residue sweep designed in [`overview.md`](./overview.md). Read
that document first: it explains *why* several of these are defects rather than
cosmetics, and it records three operator decisions you must not re-litigate.

## Ground rules

1. **No behavior changes.** Exactly one emitted value moves (Step 4). Everything
   else is comments, docstrings, terminal strings, and internal identifiers. If a
   change alters compiled output, you have made a mistake — revert it.
2. **`CURRENT_CICL_VERSION` stays `"2"`.** Do not touch it, the test projects'
   `cicl_version:`, or `cicl.md`. The 2 → 3 bump belongs to a later mod.
3. **Do not touch these**, all frozen deliberately:
   - `docex/plans/modifications/**` (except this mod's own folder)
   - `docex/plans/advances/**`
   - `upgrades/upgrade_{1.1.0,1.2.0,1.3.0,1.4.0,1.5.0,1.6.0,1.6.1}.md`
   - `docex/test_projects/{fixed,elastic}/CHANGELOG.md`
   - `docex/test_projects/*/core/*/dist/**` (gitignored build artifacts)
   - `doctrine/**` — verified clean; every remaining `process` hit there is the
     workflow or OS sense
4. **Do not update `docex/plans/core/*.md`.** Those are core planning docs and
   belong to a later step of the mod cycle, driven by someone else.
5. **Protected tokens — never touch.** A naive `s/process/service/` corrupts
   ~700 unrelated occurrences:
   - `subprocess`, `subprocess_client`, `subprocess_runner`,
     `SubprocessGitClient`, `SubprocessSshClient`, `subprocesses`
   - `processor`, `processors`, `processor_service`, `processor.md`
   - `processed`, `processed_at`, `processed_before`, `processed_idx`,
     `processing`
   - `docex_process`, `docex_process.md`
   - `proceed`, `proceeds`
   - 12-factor "processes" in the OS sense, and every
     `"Returns process exit code"` / `"Return the appropriate process exit
     code"` docstring (~15 sites). These describe an **OS process**. Keep.
   - `masterplan.md:8`'s "single-process tool" — OS sense, and that file is
     out of scope anyway.

**Work file by file, not with a global sed.** Every step below is scoped to
named files.

## Vocabulary target

| Concept | Word | Local identifier |
| ------- | ---- | ---------------- |
| One source tree, one build artifact, one image | **codebase** | `cb`, `cb_name`, `codebase` |
| One named, independently-scaled deployment of that artifact | **core service** | `svc`, `svc_name`, `service` |
| Reference form | `<codebase>.<service>` | — |
| Emitted form | `<codebase>-<service>` | — |
| CICL path | `codebases.<cb>.core_services.<svc>` | — |

Retired entirely: "process type", "process name", "process-scoped",
"process-level", "process dimension", "per-process".

---

## Step 1 — Botched substitutions

Five sites where the sweep substituted both halves of a two-level distinction,
leaving text that says nothing.

### 1a. `src/docex/cicl/model.py`

Line ~188, the comment above `_MOVED_TO_PROCESS`:

```python
# Fields that moved from the core service to the core service in CICL v2.
```
→
```python
# Fields that moved from the codebase to the core service in CICL v2.
```

Line ~230, inside `_reject_v1_shape` — **this prints to the operator**:

```python
f"{stray} moved from the core service to the core service in "
f"CICL v2. Nest them under a named entry in a `core_services:` "
f"block. Only {{core_services, secrets, config, env}} are valid "
f"at the service level (cicl.md § Field scoping, rule 22). "
```
→
```python
f"{stray} moved from the codebase to the core service in "
f"CICL v2. Nest them under a named entry in a `core_services:` "
f"block. Only {{core_services, secrets, config, env}} are valid "
f"at the codebase level (cicl.md § Field scoping, rule 22). "
```

Keep the `upgrades/upgrade_1.6.0.md` reference on the following line as-is —
that guide is what moved these fields.

**Then immediately fix `tests/unit/test_service_nesting.py:201`:**

```python
assert "moved from the core service to the core service" not in msg
```
→
```python
assert "moved from the codebase to the core service" not in msg
```

That assertion exists to prove the nesting error does not leak into the *v1*
message. Its string was rewritten by the same bad sweep, so it currently passes
by coincidence. If you fix `model.py` and not this line, the test keeps passing
while asserting nothing.

### 1b. `src/docex/cicl/compile.py`

Line ~659: `# Core core services have a single engine per role; pick the`
→ `# Core services have a single engine per role; pick the`

Line ~826: `# Core core service never publish a host port. A `web``
→ `# Core services never publish a host port. A `web``

### 1c. `src/docex/cicl/validate.py`

Line ~228: `# Core core services have a single canonical engine per role. We`
→ `# Core services have a single canonical engine per role. We`

---

## Step 2 — Operator-facing output

### 2a. `src/docex/orchestrate/build.py`

The `run_build` docstring (~46-49):

```
"""Run ``build.sh`` for one or all core services.

``service=None`` builds every core service in deterministic order.
```
→
```
"""Run ``build.sh`` for one or all codebases.

``codebase=None`` builds every codebase in deterministic order.
```

Rename the parameter `service` → `codebase` on `run_build` (keyword-only after
`*`), and the local `svc` loop variable to `cb`. Update the dispatcher call site
in `src/docex/__main__.py` (see 2d).

The error at ~81-83:

```python
raise EnvNotSupported(
    f"service {service!r} is not a core service; "
    f"known core services: {all_cores}"
)
```
→
```python
raise EnvNotSupported(
    f"{codebase!r} is not a codebase in infra.yml; "
    f"known codebases: {all_codebases}"
)
```

Rename the local `all_cores` → `all_codebases` (it is `codebases(ctx)`).

`_build_one`'s `svc: str` parameter → `codebase: str`, its docstring
"for a single service" → "for a single codebase", and the `core / svc / dist`
path construction accordingly. Line ~11 in the module docstring:
`Clear ``$pr/core/<svc>/dist/`` on the host` → `core/<codebase>/dist/`.
Line ~111's `# MOD 099 DELETED the per-service "is this container running" gate`
→ `per-codebase`.

### 2b. `src/docex/orchestrate/_common.py`

Module docstring line ~10:
`  * Enumerate the core services / schema-owning services.`
→ `  * Enumerate the codebases / schema-owning codebases.`

`codebases()` docstring (~95-103):

```
"""Return the codebase keys of every core service, sorted.
...
    same per-service order both times.
```
→
```
"""Return the key of every codebase, sorted.
...
    same per-codebase order both times.
```
and `(``core/<svc>/``, the image ref, ``build.sh``)` → `core/<codebase>/`.

`scheduler_only_services()` (~111-113): "Codebase keys with NO long-running core
service" → "core services"; "Every core service of such a codebase is a
``scheduler``" is already correct.

`services_with_schema` → **rename the function to `codebases_with_schema`** and
fix its docstring:

```
"""Return the codebases that own a backing-service schema.

These are the codebases whose ``migrate.sh`` must be invoked by
``up`` (dev/test), ``migrate`` (dev/test), and ``test``. Sorted
for determinism, matching ``codebases``.
"""
```

Its body comment "A core service \"owns a schema\" by declaring schema_owned_by
on the backing service; we look at backing services whose value points at a core
service" → "A codebase owns a schema by … whose value points at a codebase".
Rename the local `valid_core` → `valid_codebases`.

Update **every** caller and import:
- `src/docex/orchestrate/migrate.py:36, 100, 216, 230`
- `src/docex/orchestrate/test.py:30, 101`
- `src/docex/orchestrate/up.py:28, 267`
- `src/docex/pipeline/check.py:43, 664`
- `src/docex/pipeline/release.py:29, 547`
- `tests/unit/test_pipeline_release.py:367, 372` — the `monkeypatch.setattr`
  target string must move too, or the patch silently no-ops

In `migrate.py:216`, `2. For each ``services_with_schema(ctx)`` core service:`
→ ``` ``codebases_with_schema(ctx)`` codebase:```. In `test.py:101`, rename the
loop var `svc` → `cb`.

`_codebase_naming_policy` (~162-219) — fix the plural agreement throughout:

- `"A codebase-keyed name has no core service and therefore no single role"` →
  `"has no core service of its own"` (it genuinely has none; keep singular but
  make it read)
- `"Every core service of the codebase must agree"` — already correct
- `"Mirrors the compiler's own per-process engine resolution"` → `per-service`
- `"(unknown codebase, no core service, or no engine supporting ``foundation``)"`
  → `no core services`
- `"Raises when the core service *disagree*"` → `"when the core services
  *disagree*"`
- the disagreement-message comment `# policy name -> the first core service that
  resolved to it` — already correct; rename its comprehension variable `proc` →
  `svc`

The raised message at ~213:

```python
f"core service {codebase!r}: its core service resolve to "
f"different naming policies ({detail}), so the codebase-keyed "
```
→
```python
f"codebase {codebase!r}: its core services resolve to "
f"different naming policies ({detail}), so the codebase-keyed "
```

`exec_service_key`'s raise at ~248:

```python
f"in {env!r}: it is not a core service in infra.yml, declares no "
f"core service, or none of its roles has an engine supporting "
```
→
```python
f"in {env!r}: it is not a codebase in infra.yml, declares no "
f"core services, or none of its roles has an engine supporting "
```

### 2c. `src/docex/errors.py`

Line ~127: ``"""A required ``infra/contracts/<svc>.<proc>.<fmt>.yml`` is absent."""``
→ ``<codebase>.<service>.<fmt>.yml``

Line ~135: `"""``docker buildx build`` for a core service exited non-zero."""`
→ `for a codebase exited non-zero.`

Leave line ~256's "Return the appropriate process exit code" — OS sense.

### 2d. `src/docex/__main__.py`

- Line ~36: `"build": "Refresh dist/ for one or all core services."`
  → `"Refresh dist/ for one or all codebases."`
- Line ~41: `"containerize": "Build and push core service prod images."`
  → `"Build and push per-codebase prod images."`
- Line ~388-389:
  ```python
  parser.add_argument("service", nargs="?", default=None,
                      help="core service to build (omit to build all)")
  ```
  → `"codebase"`, `help="codebase to build (omit to build all)"`.
  Follow the `args.service` read through to the `run_build(...)` call and move it
  to `args.codebase` / `codebase=`. Positionals carry no name on the command
  line, so there is **no CLI compatibility surface** here.
- Line ~31: `"roles": "List the available service roles (with descriptions)."`
  is correct — roles are declared by core services. Leave.

### 2e. `src/docex/cicl/validate.py` — rule 14's message

At ~1399-1415:

```python
# A process name is the second segment of the emitted host label, so it
# is bound by the same blacklist: `api` + a process named `prod` renders
```
→ `A core service name is the second segment … + a core service named `prod``

```python
f"process name {service_name!r} (on core service "
...
f"<service>-<process>.<env>.<project>.<apex_domain>: a "
f"process named {service_name!r} renders "
```
→
```python
f"core service name {service_name!r} (on codebase "
...
f"<codebase>-<service>.<env>.<project>.<apex_domain>: a "
f"core service named {service_name!r} renders "
```

Also the function docstring at ~1382: `"""Rule 14: service *and process* names
cannot be ``dev``, ``test``,` → `"""Rule 14: codebase *and core service* names
cannot be …`

### 2f. `src/docex/cicl/model.py` — the pydantic name validator

Same message, at ~346-356:

```python
# A process name is emitted as the second segment of a compiled
# identity, so it is bound by exactly the same character rule as a
# service name.
...
f"process name {service_name!r} (on core service "
f"{svc_name!r}) must start with a letter and "
```
→
```python
# A core service name is emitted as the second segment of a compiled
# identity, so it is bound by exactly the same character rule as a
# codebase name.
...
f"core service name {service_name!r} (on codebase "
f"{cb_name!r}) must start with a letter and "
```
(the loop variable renames per Step 5).

Also line ~285, in the `domain_default_service` field comment:
```python
# ``<service>-<process>.<env>.<project>.<apex_domain>`` — the canonical
```
→ ``<codebase>-<service>.<env>.<project>.<apex_domain>``
and the surrounding `Other web core service live at` → `Other web core services
live at`.

Line ~268 (`apex_domain`): `The canonical service host form is
``<service>.<env>.<project>.<apex_domain>``` → ``<codebase>-<service>.<env>.<project>.<apex_domain>``.

Line ~196-201, `class Codebase`:
```python
"""A core service in ``infra.yml``: one codebase, one build artifact.

The service level accepts only ``{core_services, secrets, config, env}``
(rule 22). Everything invocation-determined lives on a CoreService.
"""
```
→
```python
"""A codebase in ``infra.yml``: one source tree, one build artifact.

The codebase level accepts only ``{core_services, secrets, config, env}``
(rule 22). Everything invocation-determined lives on a CoreService.
"""
```

Line ~232's `# A stray service-level `role:` / `resources:` / `command:`` →
`codebase-level`. Line ~239-243's comment: "migration sizing is now the
per-dimension max across the codebase's core service" → `core services`.

### 2g. `src/docex/cicl/magic_refs.py`

- ~159: `" A backing service has no core service, so there is nothing "`
  → `has no core services,`
- ~185: `f"magic ref {ref.text} in {consumer_label!r} references the process "`
  → `references the core service `
- ~241: `# Cycle guard, keyed on (kind, target, process, part).`
  → `(kind, target, service, part).`

Leave the `four-segment` mentions at ~51, 75, 132, 138 — they describe the
**pre-1.7.0** ref form in a migration hint, and that form genuinely had four
segments. `_REF_SEGMENT_WORD`'s `"five-segment"` for the current form is correct.

---

## Step 3 — The v1 rejection message

`src/docex/cicl/model.py`, `_validate_cicl_version` (~320-327). Replace:

```python
if version == "1":
    raise ValueError(
        "cicl_version '1' is no longer supported. CICL v2 makes the "
        "`core_services:` block mandatory on every core service and adds "
        "the `consumes` relation and four-segment core magic refs. "
        "Follow upgrades/upgrade_1.6.0.md to migrate this infra.yml, "
        "then set cicl_version: \"2\"."
    )
```
with:
```python
if version == "1":
    raise ValueError(
        "cicl_version '1' is no longer supported. The current generation "
        "nests a `core_services:` block under each entry in `codebases:`, "
        "and adds the `consumes` relation and five-segment core magic refs "
        "(${codebases.<cb>.core_services.<svc>.<part>}). Follow "
        "upgrades/upgrade_1.6.0.md then upgrades/upgrade_1.7.0.md to "
        "migrate this infra.yml, then set cicl_version: \"2\"."
    )
```

**Why** (operator decision 1): the old text described 1.6.0's v2 — top-level
`core_services:`, four-segment refs — while the parser now enforces 1.7.0's v2.
An operator who followed it produced a document the compiler rejects.

`tests/unit/test_service_nesting.py` asserts `"upgrade_1.6.0.md" in msg`; that
still holds. If it also asserts the old phrasing, update it to match the new
text. `CURRENT_CICL_VERSION` is untouched, so the trailing `"2"` is correct.

Also fix the comment at ~302: `"a compatibility parser accepting both forms
would reintroduce the flat pre-``core_services:`` shape"` — accurate (v1 was
flat), leave. But ~308's `"the operator saw a wall of per-service field-scoping
errors"` → `per-codebase`.

---

## Step 4 — `describe --format llm`

`src/docex/describe/llm.py`, ~40-46. This is the mod's **one intentional
emitted-output change**, mandated by the rename plan's emitted-surface table.

```python
# ... None for a
# backing service, which has no process dimension.
"core_service": svc.codebase,
"service": svc.service,
```
→
```python
# ... None for a
# backing service, which has no service dimension.
"codebase": svc.codebase,
"service": svc.service,
```

Key order stays where it is so the surrounding diff is one line. Check
`tests/` for any assertion on the `core_service` key in LLM output and move it:

```
grep -rn '"core_service"' tests/
```

---

## Step 5 — Identifier renames

The mechanical core. **Do these as renames, then run the suite** — the suite is
the only proof they landed.

### 5a. The `all_core_services()` unpacking — the big one

`CICLDocument.all_core_services()` returns
`(codebase_name, service_name, codebase, core_service)`. Almost every consumer
unpacks it as `for svc_name, service_name, _svc, proc in …`, which names the
codebase `svc` and the core service `proc` — the exact inversion the rename
existed to remove.

Rewrite every such loop to:

```python
for cb_name, svc_name, cb, svc in doc.all_core_services():
```

using `_cb` / `_svc` where an element is unused. Then rename the body's uses of
`proc.` → `svc.` and `svc_name` (codebase) → `cb_name`.

Sites — **check each with grep after editing, the list is by line and lines will
shift**:

- `src/docex/cicl/validate.py` — ~15 loops at 140, 258, 466, 545, 594, 738,
  804, 941, 985, 1076, 1403, 1464, 1510, 1565, 1599. Also the non-loop locals:
  `target_proc` → `target_svc` (326, 327, 345, 356) and `proc = svc.core_services.get(...)`
  → `svc = cb.core_services.get(...)` at 913-924.
- `src/docex/cicl/compile.py` — 440, 650. In `compile_env`, `svc_name` is the
  codebase throughout the main loop (~650-1100): rename to `cb_name`. Note the
  loop **already** has a correctly-named `codebase: Codebase | None` local at
  ~741 — keep that name and let `cb_name` be its key, or collapse the two if
  cleaner. `docex.codebase={svc_name}` at ~964 becomes `{cb_name}`.
- `src/docex/pipeline/check.py` — 376, 382, 520.
- `src/docex/cicl/model.py` — `all_core_services()`'s own body (~420-423) and
  `_validate_service_names`' loop (~349).

In `cicl/validate.py`, also rename:
- `_effective_env(svc: Codebase, proc: CoreService)` →
  `_effective_env(cb: Codebase, svc: CoreService)`, and fix its docstring — it
  currently calls **both** levels "service-level":
  ```
  """A core service's effective env: the codebase-level ``env:`` block
  with the core service's own ``env:`` merged over it
  (cicl.md § Field scoping)."""
  ```
- `_service_where(svc_name, service_name)` → `_service_where(cb_name, svc_name)`

### 5b. `_STANDARD_*` field sets — a **swap**, not two renames

`src/docex/cicl/validate.py` ~50-60. Currently:

```python
_STANDARD_SERVICE_FIELDS = {"core_services", "secrets", "config", "env"}
_STANDARD_PROCESS_FIELDS = {
    "role", "command", "networks", "depends_on", "consumes", "port", "env",
    "resources", "replicas",
}
```

`_STANDARD_SERVICE_FIELDS` holds the **codebase**-level set. Rename both
together:

```python
# Standard CICL field sets (not subject to the "must be declared in
# engine.fields" check).
# Codebase level is model-enforced (Codebase.extra="forbid"); listed for
# documentation only.
_STANDARD_CODEBASE_FIELDS = {"core_services", "secrets", "config", "env"}
# Core-service level: everything CoreService declares as a real field.
# Anything else must be declared in the engine's `fields:` block (tt rule 4).
_STANDARD_SERVICE_FIELDS = {
    "role", "command", "networks", "depends_on", "consumes", "port", "env",
    "resources", "replicas",
}
```

⚠ **Editing either alone either collides or silently swaps which field set a
rule enforces.** Move both in one edit, then confirm the rule-22 and rule-4
field-scoping tests pass — they are what prove the swap landed the right way
round. Update the read site at ~261 (`_STANDARD_PROCESS_FIELDS` →
`_STANDARD_SERVICE_FIELDS`) and any read of the old
`_STANDARD_SERVICE_FIELDS`.

### 5c. Straight renames

| Old | New | Sites |
| --- | --- | ----- |
| `_validate_process_role_rules` | `_validate_service_role_rules` | `cicl/validate.py:115, 1496` |
| `_MOVED_TO_PROCESS` | `_MOVED_TO_SERVICE` | `cicl/model.py:190, 227` |
| `default_process_compiled` | `default_service_compiled` | `cicl/compile.py:383, 390, 394, 396, 412, 732, 1036` (param of `_web_hosts` + local) |
| `procs` / `p` | `svcs` / `svc` | `emit/compose.py:697-740`, `emit/hcl.py:576-679`, `emit/ansible.py:41-44`. Watch for a shadowing conflict with an outer `svc` in `hcl.py`. |
| `t_svc, t_proc_name, t_proc` | `t_cb, t_svc_name, t_svc` | `pipeline/check.py:504-509, 525-531` |
| `proc` (local) | `svc` | `pipeline/check.py:182-185, 376-396, 477-500`; `orchestrate/_common.py:210` |

### 5d. `CompiledService.service_env` → `codebase_env`

`src/docex/cicl/compile.py:520` — the field holds the **codebase**-scoped
surface, so its name is inverted. Its own docstring is self-contradictory
("the service-level `env:` block resolved … EXCLUDING any service-level `env:`
overlay"). Rename the field and rewrite the docstring:

```python
# The codebase-scoped env surface: the CODEBASE-level `env:` block
# resolved, plus secrets / config / doctrine-injected keys, EXCLUDING any
# core service's `env:` overlay. Consumed by the migrate task definition
# (and by Mod 099's exec service). See overview.md § Migration carrier.
codebase_env: dict[str, Any] = field(default_factory=dict)
```

Move every reader and the local at the construction site:
- `src/docex/cicl/compile.py:870, 976, 1004, 1073` (local `service_env` → `codebase_env`)
- `src/docex/emit/compose.py:30, 716, 724, 725`
- `src/docex/emit/hcl.py:586, 591`
- `tests/unit/test_service_expansion_emit.py:255`
- `tests/unit/test_telemetry.py:497` — the tuple label string moves too

### 5e. `core_service_names` → `codebase_names`

The value passed is `list(ctx.infra.codebases.keys())`; one ECR repo per codebase
is correct, only the name is inverted.

- `src/docex/emit/hcl.py:1201` (param), `1232`, `1258`, `1320`
- `src/docex/emit/templates/project.tf.j2:594, 649, 658, 776` — the Jinja
  variable. Also fix `:591`'s comment `# ECR repositories — one per core
  service.` → `one per codebase.` and `:598`'s
  `{# Mod 060: per-service differentiation rides in descriptor (the service` →
  `per-codebase differentiation … (the codebase`. Rename the loop var `svc` →
  `cb` in all four `{% for %}` blocks and their bodies.
- `src/docex/cicl/compile.py:1320` (the keyword at the call site)
- Test call sites — the kwarg name must move or they `TypeError`:
  `tests/integration/test_compile.py:712`,
  `tests/unit/test_naming_policy_leak.py:212, 241`.
  Also `tests/integration/test_compile.py:657`'s comment.

### 5f. `emit/hcl.py` — leave `svc_name` at 158-269 alone

`_log_configuration` / `_ssm_data_name` / their callers use `svc_name` for a
**compiled identity** (`api-web`), which correctly names a core service. No
change.

---

## Step 6 — Prose residue

Comment and docstring text only. Apply the vocabulary target; the full site list
is in `overview.md` § 6. Work through these files:

**`src/docex/cicl/compile.py`** — `159` (`codebases.<svc>.core_services.<proc>.resources`
→ `<cb>`/`<svc>`), `337` ("the service's Dockerfile" → "the codebase's"),
`347` ("one ECR repo per core service" → "per codebase"), `383-396`
(`_web_hosts` docstring: "The default process additionally answers" → "default
core service"; "prod's default process" → "default core service"),
`504` (`--- Process expansion (Mod 096) ---` → `--- Service expansion (Mod 096) ---`),
`508` (`core/<svc>/` → `core/<codebase>/`), `643-646` ("one core service of one
core service" → "one core service of one **codebase**"; "is per-process now" →
"is per-service now"; the tuple comment `(key, model, core_service_name | None,
service_name | None)` → `(key, model, codebase_name | None, service_name | None)`),
`704-707` ("omits the `process` tag" → "`service` tag"; "before process
expansion" → "before service expansion"; "for the elastic `service` tag: the tag
block splits the two dimensions (`service = api`, `service = web`)" →
"(`codebase = api`, `service = web`)"), `721-723` (the `core_owning_schema`
comment: "Which core services own a backing-service schema" → "Which
codebases…"), `827-828` ("A `web` process is reached" → "core service";
"a non-web process's port" → "core service's"), `911-925` ("Core-service
`secrets:`" / "`config:`" read `codebase.secrets` / `.config`, so →
"Codebase `secrets:`" / "Codebase `config:`"), `985-1001` ("whenever the process
declared no `env:` overlay" → "core service"; "Carrying a process segment" →
"service segment"; "whenever a process declared an overlay" → "a core service"),
`1044-1049` ("across the codebase's core service" → "core services"),
`1154` ("per-service body" — correct, leave), `1198` ("no process dimension" →
"no service dimension").

**`src/docex/cicl/validate.py`** — `19` (`<service>.<process>` →
`<codebase>.<service>`), `340` ("process's role" → "core service's role"),
`783` ("collisions process expansion makes" → "service expansion"),
`885` (`# Domain default process + web-process ports.` → `# Domain default
service + web core-service ports.`), `890` ("names a web-network *process" →
"*core service"), `967` ("(service ∪ process)" → "(codebase ∪ service)"),
`1066` ("is per-process in CICL v2" → "per-service"), `1237-1262`
("reported once for the codebase" — correct; "Per-core-service env." — correct),
`1531` ("{proc.role} core service" — becomes `{svc.role}` via Step 5a).

**`src/docex/emit/compose.py`** — `16` ("per-process app containers" →
"per-core-service"), `26-30` ("Its ``environment:`` is the **service-level**
``env:`` surface only (``CompiledService.service_env``)" → "**codebase-level**
… ``CompiledService.codebase_env``"), `370` (`<codebase>-<process>` →
`<codebase>-<service>`), `551` (`core/<svc>/` → `core/<codebase>/`),
`565` ("every core service to ship a Dockerfile" → "every codebase"),
`716-723` ("identical across a codebase's core service" → "core services";
"leaked `procs[0]`'s process segment" → "`svcs[0]`'s service segment").

**`src/docex/emit/hcl.py`** — `324` ("a per-process renderer" → "per-core-service"),
`561` ("a per-*process* renderer" → "per-*core-service*"), `589` ("whichever
process was picked" → "core service"), `596` ("a process segment in it" →
"a service segment"), `620` ("across the codebase's process types" → "core
services"), `627` ("A single-process codebase's max is that process's value" →
"single-core-service codebase's … that core service's value"), `676-680`
("on the three-process fixture" → "three-core-service fixture"; "`process` is
omitted" → "`service` is omitted"), `436` ("for every core service" — correct),
`586-591` (the `service_env` WHY → `codebase_env`).

**`src/docex/emit/ansible.py`** — `26` ("that core service's `env:` overlay" —
correct), `33-37` ("so a filter … type" reads "…would emit one duplicate migrate
task per process type" at `36` → "per core service").

**`src/docex/pipeline/check.py`** — `142` (`${service}.${process}.${format}.yml`
→ `${codebase}.${service}.${format}.yml`), `145` ("discarded the process
entirely" → "the core service"), `149` ("dots in a service or process name" →
"a codebase or core service name"), `357-363` (`<svc>.<proc>.<fmt>.yml` →
`<codebase>.<service>.<fmt>.yml`; "The path is process-keyed unconditionally: one
codebase may run two HTTP process types" → "service-keyed … two HTTP core
services"; "the provider process refs" → "provider core service refs"),
`434` ("Three things, per core service:" — correct), `455` ("which is what lets a
sibling `web` process reach its `/health`" → "`web` core service"),
`660` ("``build.sh`` and ``test.sh`` for every core service" → "every codebase"),
`671-677` (`core/{svc}/` messages — rename the loop var to `cb` so the f-strings
read `core/{cb}/…`; the emitted *path* is unchanged).

**`src/docex/orchestrate/migrate.py`** — `4-7` (already correct), `216`
(see 5b), `352-357` ("how many process types it declares" → "how many core
services"; "resolved across all of the codebase's core service" → "core
services"), `12` ("the per-service migration" — correct).

**`src/docex/orchestrate/test.py`** — `9` ("Run each core service's test.sh" →
"each codebase's test.sh"), `117` (already correct). Leave `46`'s "Returns
process exit code".

**`src/docex/orchestrate/up.py`** — `36`, `104` (`core/<svc>/` →
`core/<codebase>/`), `199` ("pre-populate the host dist/ for each core service"
→ "for each codebase").

**`src/docex/pipeline/containerize.py`** — `1` ("build + push core service prod
images" → "per-codebase prod images"), `8` ("For each core service:" → "For each
codebase:"), `59` ("for every core service" → "for every codebase"). Also
`_image_tag`'s `service` param → `codebase` and the local loop var.

**`src/docex/pipeline/rollback.py`** — `10` ("every core service's image" →
"every codebase's image"), `328` ("Probe every core service's image" → "every
codebase's image"), and `_missing_images`' loop var `svc` → `cb` (it iterates
`codebases(ctx)`; the built ref string is unchanged).

**`src/docex/aws/client.py`** — `246` ("confirm every core service has an image"
→ "every codebase"). Leave `35`'s "mid-process".

**`src/docex/describe/dag.py`** — verified clean, no change.

**`src/docex/cicl/fargate.py`** — the three fallback `where=` paths at `105`,
`137`, `162` render `codebases.{service_name}.resources`, a path that cannot
exist under rule 22. Rename the parameter `service_name` → `where_name` (it
receives a compiled identity from some callers and a codebase from others) and
change the fallbacks to `f"codebases.*.core_services.*.resources"`, or simply
drop the fallback and require `where` — every current caller passes it
explicitly. **Prefer requiring `where`**: make it non-optional and delete the
`where or …` fallbacks. Confirm all four call sites
(`cicl/compile.py:189, 202`, `emit/hcl.py:641`) pass it, then update any test
that calls these helpers directly.

**`tables/roles/worker.yml`** — `13`: `# ``image:``, ``cpu:``, ``memory:``,
``tmpfs:`` are derived per-core-service by the compiler` — `image:` is derived
per **codebase**. Split the sentence:
```
# `cpu:`, `memory:`, `tmpfs:` are derived per-core-service by the
# compiler, exactly as for `web`; `image:` is derived per codebase, so
# every core service of a codebase runs one tag.
```

**`docex/test_projects/`** (working files only — **not** `CHANGELOG.md`, **not**
`dist/`):
- `fixed/core/api/src/root.py:12` and `elastic/…:12` — "not one per process" →
  "not one per core service"
- `fixed/core/api/src/root.py:128` and `elastic/…:128` — `/health/<service>/<process>`
  → `/health/<codebase>/<service>`
- `*/core/api/src/entrypoints/web.py:23` — "for this process" → "for this core
  service"
- `*/infra/contracts/api.web.openapi.yml:3` — `<svc>.<proc>.<format>.yml` →
  `<codebase>.<service>.<format>.yml`; `:12` — "every `web`-network process" →
  "core service"
- `elastic/infra/infra.yml:94` — "process reach its /health" → "core service
  reach its /health"
- `*/infra/stage/tests/test_smoke.py:13` — "processes it" is the **verb**, keep;
  `:55` "process alive" is the OS sense, keep
- `fixed/plans/core/masterplan.md:21, 32` — `<codebase>-<process>` →
  `<codebase>-<service>`; `<service>-<process>.<env>…` →
  `<codebase>-<service>.<env>…`
- `PRE_CUT_CHECKLIST.md:96` ("two-segment process hostnames" → "core service
  hostnames"), `:168` ("a **dotted, fully qualified** process reference" → "core
  service reference"), `:177` (`<svc>.<proc>.<format>.yml` →
  `<codebase>.<service>.<format>.yml`). Leave `:185`'s "the process's" — it
  contrasts a loop's liveness with the **OS process's**, which is the point.
  Leave `:7`'s `docex_process.md` link.
- `*/plans/core/api/api.md:5` and `db_schema.md:9` — "processes those pings" /
  "processes it" are verbs. Keep.

---

## Step 7 — `docex why codebase`

Create `docex/doctrine_excerpts/codebase.md`, matching the house style of the
existing excerpts (short, declarative, closes with a `Doctrine reference:` line).
Read `doctrine_excerpts/core_service.md` and `build_image.md` first and mirror
their shape and length.

Content to convey — do not exceed the length of `core_service.md`:

- A codebase is one source tree and the single build artifact / image compiled
  from it. It is the unit of *code*; the core service is the unit of
  *deployment*.
- A codebase declares one or more core services in `infra.yml` under
  `codebases.<name>.core_services`. Every one of them runs that same image.
- **Codebases never share code.** Each is a distinct source tree; one codebase
  never imports from another. All that ties them together is a shared purpose,
  shared backing services, and the project-wide version.
- Codebase-scoped, not per-core-service: the image ref and its registry repo,
  `schema_owned_by` (so `migrate.sh` runs once per codebase), the `core/<name>/`
  source folder, `build.sh` / `test.sh` / `migrate.sh`, and the `secrets:` /
  `config:` / codebase-level `env:` blocks.
- Lives at `$pr/core/<name>/` with a Dockerfile declaring the four canonical
  stages.
- `Doctrine reference:` `infrastructure/infrastructure.md` § Repository
  Structure; `infrastructure/cicl.md` § Core Services; `lexicon.md`.

Then add to `docex/doctrine_excerpts/index.yml`, immediately **above** the
existing `core_service:` line so the code-unit reads before the deployment-unit:

```yml
codebase: codebase.md
core_service: core_service.md
```

Check whether any test enumerates the index (`grep -rn "index.yml\|doctrine_excerpts" tests/`)
and extend its expected set if so.

---

## Step 8 — Tests

Sweep `tests/` for the same vocabulary. No new tests — the mod adds no behavior.
Renames that must happen because the code moved (these will otherwise fail):

- `services_with_schema` → `codebases_with_schema`, incl. the
  `monkeypatch.setattr` **string** in `test_pipeline_release.py:372`
- `service_env` → `codebase_env` (`test_service_expansion_emit.py:255`,
  `test_telemetry.py:497`)
- `core_service_names=` kwarg (`test_compile.py:712`,
  `test_naming_policy_leak.py:212, 241`)
- the `"core_service"` LLM JSON key, if asserted
- `test_service_nesting.py:201`'s assertion string (Step 1a)
- anything asserting the old v1 message wording (Step 3)

Cosmetic renames — fixture, helper, and test-function names carrying the retired
vocabulary:

- `test_validate.py` — `_WORKER_PROCESS` → `_WORKER_SERVICE`,
  `_with_process_block` → `_with_service_block`,
  `test_rule_domain_default_unknown_process` → `…_unknown_service`,
  `test_rule_domain_default_web_process_clean` → `…_web_service_clean`,
  `test_rule_16_process_env_vs_service_secrets` → `…_service_env_vs_codebase_secrets`
- `test_service_nesting.py` (38 hits) — `_WEB_PROCESS` → `_WEB_SERVICE`,
  `_two_process_doc` → `_two_service_doc`,
  `test_1_processes_absent_rejected` → `test_1_core_services_absent_rejected`,
  `test_2_processes_empty_rejected`, `test_3_service_level_resources_names_processes_block`
  → `test_3_codebase_level_resources_names_core_services_block`,
  `test_4_service_level_role_or_command_names_processes_block` likewise,
  `test_5_process_without_command_rejected` → `test_5_service_without_command_rejected`,
  `test_9_rule_5_collision_form_a_two_process_pairs` → `…_two_service_pairs`,
  `test_17_health_check_path_without_port_on_process_rejected` → `…_on_service_rejected`,
  `test_18_reserved_process_name_rejected` → `…_reserved_service_name_rejected`,
  plus the comment text at 67, 282-369, 530, 544
- `test_service_expansion_emit.py` (21) —
  `test_28_fixed_all_processes_share_one_image` → `…_all_services_share_one_image`,
  and the comment at 41
- `test_exec_service.py` — `_multi_process_project` → `_multi_service_project`,
  comments at 4, 123-148; `test_exec_service_resolution.py` likewise
- `test_web_hostnames.py` — `test_non_web_process_gets_no_host` →
  `…_non_web_service_…`, comment at 27
- `test_hcl_emitter.py:793` — `<project>_<env>_<service>_<process>` →
  `<project>_<env>_<codebase>_<service>`
- `test_scheduler.py:37, 358` — "a service-level ref obliges every core service"
  → "codebase-level ref"; `<codebase>-<process>` → `<codebase>-<service>`
- `test_magic_refs.py:419` — `test_dependency_records_target_process` →
  `…_target_service`
- `test_orchestrate_up.py:80` — "declares a ``web`` process" → "core service"
- `test_consumes_relation.py`, `test_contract_health_gates.py`,
  `test_pipeline_preinfra.py:218`, `test_aws_ecr_image_exists.py:3`,
  `test_telemetry.py:4, 157, 448`, `test_opentofu_destroy.py`,
  `test_replicas.py` — comment sweeps
- `tests/integration/conftest.py` (11), `test_check_real.py` (12),
  `test_containerize_real.py` (17), `test_merge_real.py` (15),
  `test_hcl_validate_real.py`, `test_migrate_real.py`, `test_stagetest_real.py`,
  `test_up_down_real.py`, `test_check_hcgate_real.py`, `test_compile.py`

**Do NOT touch**: `test_subprocess_docker_client.py`,
`test_subprocess_ssh_client.py`, `test_shim_exit_code.py`'s "process exit code",
`test_secretsmgmt.py`'s `…_warns_but_proceeds`,
`test_pipeline_rollback.py:369`'s `…_proceeds_to_release`.

---

## Verification

Run in order. Do not report success until all four pass.

### V1 — Unit suite

```
cd ~/.claude/jean_baudrillard/docex && python -m pytest tests/unit -q
```

Must be green with the same test count as before the mod (renames preserve
count; nothing is added or removed). If a count changes, a test was accidentally
dropped or a rename collided — find it before continuing.

Integration tests (`-m integration`) hit real docker/AWS/git and are the
operator's to run; do not attempt them.

### V2 — Compiled output byte-identical

The only intentional output change (Step 4) is in `describe`, not in `compile`.
So the compile diff must be **empty**.

```
cd ~/.claude/jean_baudrillard
mkdir -p /tmp/mod111 && git stash list  # ensure a clean baseline exists
# Capture BEFORE from HEAD (the design-done commit), for both projects:
git stash push -u -- docex/  &&  \
  for f in fixed elastic; do cp -r docex/test_projects/$f/infra/output /tmp/mod111/$f-before; done  &&  \
  git stash pop
# Recompile both projects with the modified docex, then:
diff -r /tmp/mod111/fixed-before  docex/test_projects/fixed/infra/output
diff -r /tmp/mod111/elastic-before docex/test_projects/elastic/infra/output
```

If recompiling in place is impractical from your context, the checked-in
`infra/output/` trees are the baseline: any diff in them after the mod is a
defect. **Any** change to a container name, tag key *or value*, domain label,
image ref, ECR repo name, or contract path is a defect — revert and re-examine.

### V3 — Protected-token counts unchanged

```
cd ~/.claude/jean_baudrillard/docex
for t in subprocess processor processed processing docex_process proceed; do
  printf '%s: %s\n' "$t" "$(grep -rIn "$t" src tables tests doctrine_excerpts plans/core test_projects 2>/dev/null | grep -v '/dist/' | wc -l)"
done
grep -rIn 'process exit code' src | wc -l
```

Compare each against the same command run at the design-done commit
(`git stash` the working tree, or run against `git archive HEAD`). Every count
must be **identical**. A drop means collateral damage — find and restore it.

### V4 — No inverted identifier survives

```
cd ~/.claude/jean_baudrillard/docex
# Should return NOTHING:
grep -rnE 'for (svc_name|svc), (service_name|svc_name), .*all_core_services' src tests
grep -rn '_STANDARD_PROCESS_FIELDS\|_MOVED_TO_PROCESS\|default_process_compiled' src tests
grep -rn 'core_service_names\|services_with_schema\|\.service_env\|service_env=' src tests
grep -rniE '\bprocess type|per-process|process-scoped|process-level|process dimension' src tables tests doctrine_excerpts
# Should show the codebase-level set:
grep -n -A2 '_STANDARD_CODEBASE_FIELDS' src/docex/cicl/validate.py
```

Then a final residue sweep — every remaining hit must be a protected token or a
documented keep (`emit/tags.py`'s historical `(service, process)` reference,
`magic_refs.py`'s pre-1.7.0 "four-segment" hints, the `process exit code`
docstrings, `PRE_CUT_CHECKLIST.md:185`'s OS-process contrast):

```
grep -rniE '\bprocess(es)?\b|\bprocs?\b' src tables tests doctrine_excerpts test_projects \
  | grep -v '/dist/' | grep -v CHANGELOG.md \
  | grep -viE 'subprocess|processor|processed|processing|docex_process|proceed'
```

## Reporting back

State plainly: the unit-suite result (count + pass/fail), whether the compile
diff was empty, whether protected-token counts held, and any site where you
chose different wording than this document specifies and why. If V2 shows a
diff, **stop and report it** rather than adjusting the baseline.
