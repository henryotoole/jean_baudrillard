# Mod 033 — Fargate Tier Rounding Formalized

Fourth mod of the [doctrine-shape-and-tier advance](../../advances/shape_overhaul_mod_list.md). Formalizes the Fargate tier-rounding behavior the doctrine just made authoritative — most of the implementation already exists; this mod closes one specific gap.

## The Doctrine Change

From [`cicl.md § Resources`](../../../../doctrine/infrastructure/cicl.md#resources) and [`transfer_tables.md § Resources Translation`](../../../../doctrine/infrastructure/specifics/transfer_tables.md#resources-translation):

> The compiler rounds the requested `(cpu, memory)` (plus any doctrine-fixed sidecar overhead) up to the smallest supported Fargate tier that meets or exceeds both dimensions, and surfaces the rounding in compile output. Values that exceed the largest Fargate tier (currently 16 vCPU / 120 GB) fail compile cleanly. The `resources:` block stays foundation-agnostic — the project author writes the sizing that makes sense; the compiler does the tier translation.

And specifically:

> **Tier rounding is uniform across all core services**, not just those where a sidecar pushes a boundary. A project declaring `cpu: 1.5, memory: 3GB` produces a `(cpu_desired = 1536, memory_desired = 3072)` that Fargate doesn't support, so the compiler rounds up to the next valid tier (e.g., `(2048, 4096)`). Sidecar overhead is one trigger; non-tier-aligned project values are another; both produce the same behavior.

## What's already done

`src/docex/cicl/fargate.py` (mostly mod 018) already implements:

- `_FARGATE_CPUS` allowlist (256–16384 units).
- `_allowed_memory_mib(cpu)` per-CPU memory tier lookup.
- `fargate_pair_from_units(cpu_units, memory_mib, service_name)` — pre-summed input form with cpu-then-memory rounding, retries with the next larger CPU when memory exceeds the chosen CPU's allowed range, raises `ValidationError` with a descriptive message when no valid pair exists.
- `_resources_to_elastic` in `compile.py:134–...` adds the sidecar overhead (0.1 vCPU + 128 MiB) when `is_core=True` before calling `fargate_pair_from_units`.

So the doctrine bullets are largely satisfied:
- ✓ Rounding up to the smallest supported tier.
- ✓ Sidecar overhead added pre-rounding for core services.
- ✓ Overflow → `ValidationError` with helpful message naming the service.

## The gap

`_resources_to_elastic` surfaces a rounding notice (via `print(...)`) **only when the sidecar overhead specifically pushed the task into a higher Fargate tier than the bare-core request alone would have**:

```python
if is_core:
    bare_cpu_tier, bare_mem_tier = fargate_pair_from_units(
        bare_cpu_units, bare_mem_mib, service_name=service_name,
    )
    if cpu_units > bare_cpu_tier or memory_mib > bare_mem_tier:
        print(f"note: core service {service_name!r}: sidecar overhead pushed...")
```

This misses the project-only-rounding case the doctrine calls out explicitly: when the project's `resources:` block itself is non-tier-aligned (e.g. `cpu: 1.5, memory: 3GB`), the compiler still rounds (`1.5 → 2 vCPU`, `3GB → 4096 MiB`), but **no notice is printed** because the sidecar didn't add a further tier bump. The doctrine wants the rounding surfaced whenever it happens, regardless of trigger.

## The change

Broaden the surfacing condition in `_resources_to_elastic` to print a notice whenever the chosen Fargate tier differs from the operator's literal request (after unit conversion but before any rounding). Two distinguishable cases:

1. **Project-only rounding**: requested raw units (no sidecar) don't match a Fargate tier exactly. Print a notice attributing it to the request itself.
2. **Sidecar-pushed rounding**: the bare-core request would tier to X, but adding sidecar overhead bumped it to Y. Print a notice attributing it to the sidecar overhead.

Both cases reach the same Fargate tier; the difference is the *cause* the message names. The existing wording (`"sidecar overhead pushed task to next Fargate tier"`) only fits case 2; case 1 needs its own phrasing.

Suggested message shape for case 1:
> `note: core service {svc!r}: resources rounded to Fargate tier ({req_cpu_units} -> {cpu_units} vCPU units, {req_mem_mib} -> {memory_mib} MiB). Fargate accepts only discrete (vCPU, memory) pairs; requested values don't match a tier exactly.`

Case 2's existing message can stay as-is.

If both cases apply (the project value is non-aligned AND the sidecar bumps it further), surface them as one combined message rather than two prints — the operator just wants to know what happened.

### Where this lives

Single editing site: `src/docex/cicl/compile.py:_resources_to_elastic` lines ~174–190 (the `if is_core:` block that does the bare-tier comparison). The change is internal to that function.

### Print vs. structured output

Both this mod and the existing notice use `print()`. The doctrine doesn't say *how* to surface — just that the rounding be visible. `print()` is fine; the operator is running `docex compile` from a terminal. A future mod could route it through a structured emit channel; not in scope here.

## Ramifications

Operator running `docex compile` against an elastic project that uses non-tier-aligned `(cpu, memory)` requests will newly see rounding notices in compile output. Compile result itself is unchanged — the emitted task definition already carries the rounded values. Only the visibility changes.

No test-project recompile needed; no compiled output changes.

## Operator Decision

1. **Message wording for the new case** — use the suggested phrasing (sidecar-pushed-style with explicit cause). Both case-1 and case-2 produce distinct messages; when both apply, surface as one combined message.

## What This Mod Is NOT

- Not changing the Fargate-tier allowlist or memory-per-CPU table.
- Not changing the sidecar overhead value (0.1 vCPU + 128 MiB stays doctrine-prescribed).
- Not changing overflow behavior (already raises `ValidationError`).
- Not changing the `resources:` block schema or validation.
- Not formalizing rounding for backing services — backing-service `cpu`/`memory` come from engine defaults, not project `resources:`, and the doctrine v1 doesn't expose tier-rounding visibility for them.
- Not changing fixed-foundation resource translation (tmpfs sizing, deploy.resources limits).

Smallest substantive mod of the advance after mod 032. One function, one new conditional branch, one new test or two.
