# Implementation — Mod 032 — Telemetry Alignment

## Context for fresh-context implementer

You are executing mod 032 of a 16-mod docex campaign. Read [`overview.md`](./overview.md) first.

Invoke the `docex-edit` skill via Skill.

Authoritative doctrine reading:
- [`telemetry_infra.md`](../../../../doctrine/infrastructure/specifics/telemetry_infra.md) — every sidecar reference uses the new `-otelcol` form.
- [`transfer_tables.md § Per-core-service env (both foundations)`](../../../../doctrine/infrastructure/specifics/transfer_tables.md#per-core-service-env-both-foundations) — the four OTEL_* env vars.

## Operator decisions binding on this implementation

- **Do not touch `OTEL_*` injection in `compile.py`.** It's already correctly wired by earlier work (mods 011 + 017 per `validate.py:54` comment). Confirm by inspection only.
- **Mechanical `s/_otelcol/-otelcol/g` flip** across source + tests + core planning docs. No nuanced edits.
- **No `test_projects/{fixed,elastic}/` edits.** Campaign-wide deferral stands.

## Step-by-step plan

### Step 1 — Confirm OTEL_* injection is correct

Read `src/docex/cicl/compile.py` lines ~600–614. Verify all five env vars are emitted on every core service:

- `PROJECT_VERSION` — from `project.yml` version.
- `OTEL_SERVICE_NAME` — equal to the service's `infra.yml` name.
- `OTEL_EXPORTER_OTLP_ENDPOINT` — literal `http://localhost:4318`.
- `OTEL_EXPORTER_OTLP_PROTOCOL` — literal `http/protobuf`.
- `OTEL_RESOURCE_ATTRIBUTES` — formatted as `service.namespace={project_name},service.version={project_version},deployment.environment.name={env}`.

Cross-check against the doctrine spec in `transfer_tables.md § Per-core-service env (both foundations)`. If the format matches exactly (it should), make **no code change** to this block. If something is off, STOP and report — that's a regression to investigate, not a deviation to silently fix.

### Step 2 — Flip the sidecar name suffix `_otelcol` → `-otelcol` in source

Four sites:

1. `src/docex/emit/compose.py:179` — `_sidecar_block` builds `sidecar_name = f"{project}_{env}_{svc.name}_otelcol"`. **All three joiners plus the suffix are wrong.** New form: `f"{project}-{env}-{svc.name}-otelcol"`. This is the `container_name:` field of the sidecar — what docker actually names the container on the host.
2. `src/docex/emit/compose.py:329` — `emit_compose` builds `sidecar_name = f"{compiled.project}-{compiled.env}-{svc.name}_otelcol"`. Joiners are already hyphen (mod 030 partial flip). Suffix `_otelcol` → `-otelcol`. This is the compose service dictionary KEY under `services:`. **Must match the `container_name` form from step 2.1.**
3. `src/docex/emit/hcl.py:328` — `{"containerName": f"{svc.name}_otelcol", "condition": "START"}` in the application container's `dependsOn`. The application container waits on the sidecar; the named target must match the sidecar container's `name` exactly.
4. `src/docex/emit/hcl.py:331` — `"name": f"{svc.name}_otelcol"` in the sidecar container definition. Must agree with step 2.3.

Note the asymmetry between foundations:
- Compose: `${project}-${env}-${svc}-otelcol` (project/env prefix; one container per service per env at the host scope).
- ECS: `${svc}-otelcol` (no project/env prefix; one container per service per task at the task scope).

Both are correct per `telemetry_infra.md`. Don't add a `${project}-${env}` prefix on the ECS side just because compose has one.

### Step 3 — Update the comment block at `compose.py:327`

The comment currently reads:
> WHY: project/env/svc joiners use hyphens per mod 030's data-plane naming rule (docker container names). The `_otelcol` suffix is tracked separately for mod 032.

Rewrite to reflect current state — the suffix is now also hyphen-form. Cite mod 030 (joiners) and mod 032 (suffix) together as the unified naming.

### Step 4 — Tests — mechanical sweep

#### `tests/unit/test_compose_sidecar.py`

Every occurrence of `_otelcol` in:
- `endswith("_otelcol")` predicates (lines ~39, 53, 55, 67, 79, 91, 153, 172, 184).
- String assertions like `endswith("-api_otelcol")` (line 53) → `endswith("-api-otelcol")`.
- Any comments referencing the sidecar name form.

All flip to `-otelcol`.

#### `tests/unit/test_hcl_sidecar.py`

- `'name = "api_otelcol"'` (lines 60, 178) → `'name = "api-otelcol"'`.
- `'containerName = "api_otelcol"'` (line 75) → `'containerName = "api-otelcol"'`.
- The docstring at line 52 mentions `api_otelcol` — update.
- The comment at line 207 mentions `<backing>_otelcol` — update to `<backing>-otelcol`.
- The assertion `"appdb_otelcol" not in hcl` at line 216 → `"appdb-otelcol" not in hcl`. (This negative assertion verifies the sidecar isn't paired with backing services; the substring still uniquely identifies that.)

#### Other tests

Sweep:

```bash
cd ~/.claude/jean_baudrillard/docex
grep -rn '_otelcol' tests/
```

Update everything mechanically.

### Step 5 — Sweep `docex/plans/core/*.md`

Per operator decision:

```bash
grep -rn '_otelcol' docex/plans/core/
```

Update mechanically. Likely candidates: `compiler.md`, `release_flow.md`.

### Step 6 — Run tests

```bash
cd ~/.claude/jean_baudrillard/docex
pytest tests/unit -x
pytest tests/integration -x -m "not integration"
```

Both green. `*_real.py` deselected.

### Step 7 — Final sanity sweep

```bash
cd ~/.claude/jean_baudrillard/docex
grep -rn '_otelcol' src/ tests/ tables/ plans/core/
```

Should return **zero hits**. Every `_otelcol` reference is now `-otelcol`.

```bash
grep -rn '-otelcol' src/ | grep -v __pycache__
```

Sanity-check the new form is present where expected (4 source sites, plus comment).

## Out of scope

- **No changes to OTEL_* env injection** — already correct per Step 1.
- **No changes to the OTel collector image pin** (`OTEL_COLLECTOR_IMAGE` in `src/docex/__init__.py`).
- **No telemetry pipeline changes** (receivers, processors, exporters).
- **No `test_projects/{fixed,elastic}/` edits.**
- **No `docex-preinfra` skill or HyperDX preinfra changes.**

## Done criteria

- [ ] Step 1 confirmed: OTEL_* injection block matches doctrine; no code change made.
- [ ] All four source sites flipped (`compose.py:179`, `:329`, `hcl.py:328`, `:331`).
- [ ] Comment at `compose.py:327` rewritten to reflect unified state.
- [ ] Test files sweep complete; no `_otelcol` literals remain in tests.
- [ ] `docex/plans/core/*.md` swept for sidecar-name references.
- [ ] `pytest tests/unit -x` and offline `tests/integration -x -m "not integration"` both green.
- [ ] Final grep: zero `_otelcol` hits anywhere in `src/`, `tests/`, `tables/`, `plans/core/`.
- [ ] No `test_projects/{fixed,elastic}/` edits.

Working tree dirty when finished. Do not commit.
