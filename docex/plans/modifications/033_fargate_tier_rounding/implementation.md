# Implementation — Mod 033 — Fargate Tier Rounding Formalized

## Context for fresh-context implementer

You are executing mod 033 of a 16-mod docex campaign. Read [`overview.md`](./overview.md) first — it explains what's already done and what specifically gap this mod closes.

Invoke the `docex-edit` skill via Skill.

Authoritative doctrine reading:
- [`cicl.md § Resources`](../../../../doctrine/infrastructure/cicl.md#resources) — the doctrine surface.
- [`transfer_tables.md § Resources Translation`](../../../../doctrine/infrastructure/specifics/transfer_tables.md#resources-translation) — the algorithm and uniformity rule.

## Operator decision binding on this implementation

- **Message wording**: use the sidecar-pushed-style format with explicit cause; when both project-only and sidecar-pushed cases apply to the same service, surface as one combined message rather than two prints.

## Step-by-step plan

### Step 1 — Confirm the existing implementation

Read `src/docex/cicl/fargate.py` and `src/docex/cicl/compile.py:_resources_to_elastic` (lines ~135–200). Verify:

- `fargate_pair_from_units` is correctly rounding cpu-then-memory and raising `ValidationError` on overflow with a service-naming message.
- `_resources_to_elastic` adds 0.1 vCPU + 128 MiB sidecar overhead when `is_core=True` before calling `fargate_pair_from_units`.
- The existing rounding notice prints only when the sidecar overhead specifically bumped the task to a higher tier than the bare-core request would have.

If anything is off in the pre-existing implementation (e.g. the sidecar overhead is wrong, the overflow message is missing the service name), STOP and report — that's a regression, not this mod's scope.

### Step 2 — Broaden the rounding-notice condition

In `src/docex/cicl/compile.py:_resources_to_elastic`, at the `if is_core:` block that currently does the bare-tier comparison and conditional print:

1. After computing `cpu_units, memory_mib` (the final Fargate tier) AND `req_cpu_units, req_mem_mib` (the requested raw units including sidecar) AND `bare_cpu_tier, bare_mem_tier` (what bare-core would round to):
2. Classify the rounding cause:
   - **No rounding**: `cpu_units == req_cpu_units` AND `memory_mib == req_mem_mib`. No notice.
   - **Sidecar-pushed**: `cpu_units > bare_cpu_tier` OR `memory_mib > bare_mem_tier`. (Existing condition.)
   - **Project-only**: chosen tier differs from raw request but bare-core already lands at the same tier. (`cpu_units != req_cpu_units` OR `memory_mib != req_mem_mib`) AND (`cpu_units == bare_cpu_tier` AND `memory_mib == bare_mem_tier`).
   - **Both**: both conditions true.
3. Print one notice per service, with wording per the chosen case:
   - **Sidecar-pushed only**: keep the existing message wording (`"sidecar overhead pushed task to next Fargate tier..."`).
   - **Project-only**: use the suggested wording from [`overview.md`](./overview.md#the-change), shaped as:
     ```
     note: core service '<svc>': resources rounded to Fargate tier
     (<req_cpu_units> -> <cpu_units> vCPU units,
     <req_mem_mib> -> <memory_mib> MiB).
     Fargate accepts only discrete (vCPU, memory) pairs;
     requested values don't match a tier exactly.
     ```
     Multi-line for readability; one `print(...)` call with `\n`-joined or implicit triple-quoted text.
   - **Both**: compose a unified message that names both causes. Example:
     ```
     note: core service '<svc>': resources rounded to Fargate tier
     (request <req_cpu_units> -> <cpu_units> vCPU units,
     <req_mem_mib> -> <memory_mib> MiB).
     Non-tier-aligned project resources AND sidecar overhead
     each contributed to the bump; bare-core would have tiered
     to (<bare_cpu_tier>, <bare_mem_tier>).
     ```

The classification logic and message construction live entirely inside `_resources_to_elastic`. Don't carve out a separate helper — the function is the only consumer.

### Step 3 — Tests

Add unit tests in `tests/unit/test_compile.py` or wherever `_resources_to_elastic` is currently tested (search for existing fargate test fixtures):

```bash
grep -rn 'fargate_pair\|_resources_to_elastic' tests/
```

Add three test cases (capturing stdout via `capsys`):

1. **No rounding** — a core service with `cpu: 1.0, memory: 2GB` (which lands at Fargate (1024+102, 2048+128) = (1126, 2176) — still rounds, since 1024 isn't enough for 1126; check the actual landing). Pick values that genuinely don't round (sidecar-inclusive). Verify no `note:` is printed.

   Actually — sidecar overhead of 0.1 vCPU forces SOME rounding for any project that asks for a whole vCPU number. `cpu: 1.0` + sidecar = 1126 units, which rounds to 2048 (next Fargate tier above 1024). So the "no rounding" case is hard to hit with sidecar. Either pick a case where the project's request already includes headroom for the sidecar (e.g. `cpu: 0.15, memory: 0.4GB` if those round to a valid tier with sidecar added), or skip the no-rounding test as not practically reachable with the doctrine sidecar in place.

2. **Project-only rounding** — `cpu: 1.5, memory: 3GB`. Bare-core rounds to `(2048, 4096)`. Sidecar-inclusive also rounds to `(2048, 4096)` (sidecar overhead absorbs in the same tier). Verify the *project-only* phrasing is printed.

3. **Sidecar-pushed rounding** — `cpu: 1.0, memory: 2GB`. Bare-core rounds to `(1024, 2048)`. Sidecar-inclusive rounds to `(2048, 4096)` (sidecar pushed up). Verify the *sidecar-pushed* phrasing is printed.

4. **Both** — find a `(cpu, memory)` that triggers both. Example candidate: `cpu: 1.5, memory: 4GB`. Verify the *combined* phrasing is printed.

Use `capsys.readouterr().out` to capture and assert against the print message contents (substring match on the cause phrase).

### Step 4 — Run tests

```bash
cd ~/.claude/jean_baudrillard/docex
pytest tests/unit -x
pytest tests/integration -x -m "not integration"
```

### Step 5 — Sanity sweep

```bash
grep -rn 'fargate' src/docex/ | grep -v __pycache__
```

Confirm the only fargate-handling site is `fargate.py` + `_resources_to_elastic` in `compile.py`. No drift.

## Out of scope

- **No changes to `fargate.py`** — the existing module is correct.
- **No changes to overflow error wording** — already good.
- **No changes to sidecar overhead value** — doctrine-prescribed.
- **No changes to backing-service resource translation** — backing services don't use `_resources_to_elastic` for project-supplied `resources:`.
- **No changes to fixed-foundation resource emission** (tmpfs / deploy.resources).
- **No new `print` infrastructure** — keep using bare `print()`.

## Done criteria

- [ ] Existing implementation verified — no regressions found, or any found are reported back rather than silently fixed.
- [ ] `_resources_to_elastic` classifies rounding cause into none / project-only / sidecar-pushed / both.
- [ ] Print messages emit per the operator-selected wording for each case.
- [ ] Unit tests cover project-only, sidecar-pushed, and both cases (plus no-rounding if reachable with sidecar).
- [ ] `pytest tests/unit -x` and offline `tests/integration -x -m "not integration"` both green.
- [ ] No `test_projects/{fixed,elastic}/` edits.

Working tree dirty when finished. Do not commit.
