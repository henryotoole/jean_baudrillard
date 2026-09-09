# `defaults.elastic` is inert on every core role

All three core-service role tables carry the same `defaults.elastic` block —
`launch_type: FARGATE` and `network_mode: awsvpc` (`tables/roles/web.yml:41-42`,
`worker.yml:44-45`, `clock.yml:58-59`) — and **nothing reads either key.**

- `emit/hcl.py::render_task_definition` hardcodes `requires_compatibilities =
  ["FARGATE"]` and `network_mode = "awsvpc"` as literals (`hcl.py:552-553`); the
  service renderer hardcodes `launch_type = "FARGATE"` (`hcl.py:751`).
- `compile.py:801` reads `defaults_for("elastic")` into `body` and threads it to
  the emitter, which reads only the keys it names (`cpu`, `memory`,
  `ephemeral_storage`, `image`, `command`, and — since mod 127 — `healthCheck`).
  Every other key falls on the floor with no warning, log line, or test.

The output is correct today only because every shipped elastic engine wants
exactly FARGATE and awsvpc, so the literals and the inert entries agree by there
being one possible value. The defect is that the rule-executing layer contains
instructions nothing executes, and no mechanism can say so — which teaches, by
example, that adding a key to `defaults.elastic` makes the emitter do something.
It does not: a `healthCheck:` added that way would have compiled clean, passed
`docex check`, and shipped a fleet with no container health check (mod 127's
near-miss, caught by reading the renderer, not by a tool).

## Decision (plan review) — Answer A + Answer C

**Delete the dead keys AND add the fail-loud guard.** Remove `launch_type` /
`network_mode` from all three core roles' `defaults.elastic` (Answer A), and make
the elastic renderer/`docex compile` reject any `defaults.elastic` key no renderer
reads (Answer C). A makes the near-empty elastic block honest; C converts the
silent "key falls on the floor" into a compile error, catching the next
mod-127-style near-miss. The generic merge (Answer B) was rejected as an
over-scoped feature that reopens the command-override risk class. C needs a closed
set of "keys a renderer reads"; that set is small and bounded.

The three options are retained below as the rationale of record.

## The question the decision answered

**How much of ECS may a transfer table legitimately control?** This is a doctrine
decision, not a cleanup. `transfer_tables.md § Anatomy of a Role Definition`
calls a `defaults:` block "per-foundation blocks of YAML that get merged into the
default target's emitted resource" — a general merge, which is what the *fixed*
side does (`compose.py:_service_block` returns `dict(svc.body)` whole) but not
what the elastic side does. So the two foundations already disagree about what
`defaults` means, undocumented. Any resolution must reconcile that prose.

### Answer A — delete the dead keys

Remove `launch_type` and `network_mode` from all three core roles'
`defaults.elastic`; the emitter keeps its literals. `requires_compatibilities`
and `network_mode` are compiler-owned invariants, and the compiler already treats
them as such — `compile.py` has explicit `_apply_elastic_invariants` /
`_apply_fixed_invariants` passes (lines ~862/~886). The doctrine commits to
Fargate project-wide (`infrastructure.md § Deferred` rules out GPU workloads
*because* of it), so this is not a per-engine knob. Cost: the elastic block for
`clock`/`worker` becomes nearly empty, which is true and currently obscured.
Leaves the fixed/elastic asymmetry undocumented and still undetectable.

### Answer B — make the renderer honor the block generically

Merge unread `defaults.elastic` keys onto the emitted resource the way the fixed
side does, so `defaults` means one thing on both foundations. Cost is substantial:
the elastic resource is HCL text assembled line-by-line with per-argument quoting
(`_hcl_value`, `HCLLiteral`), not a serialized dict, so a generic merge needs a
key→argument mapping and the `aws_ecs_task_definition` schema — a real feature.
Risk: it lets a table override compiler-owned invariants; `hcl.py` argues at
length that `command` must **not** be table-overridable (with N core services on
one image, `command` is the only thing distinguishing them — a bug that shipped
and was caught by the 1.6.0 pre-cut walk), so B reopens that class and needs a
deny-list. Gains: genuine per-project ECS control via the project-local
transfer-table extension mechanism, which is that mechanism's stated point.

### Answer C — fail loudly on unread keys (not a fix, a safety net)

Make the elastic renderer raise (or `docex compile` report) when
`defaults.elastic` carries a key no renderer reads. This converts silence into an
answer without deciding what the block may contain, is cheap, would have caught
mod 127's near-miss, and is compatible with A or B landing later. It needs a
closed set of "keys a renderer reads" — the same knowledge B needs, used to reject
instead of accept.

## Note on mod 127

`render_task_definition` carries an explicit `INERT:` comment (`hcl.py:386-388`)
recording that `launch_type`/`network_mode` are inert and warning not to infer
generality from the named `healthCheck` read (`hcl.py:395-397`). That read is the
minimum that gets the probe to the container and prejudges nothing: under A the
comment and read stay; under B the read is subsumed by the generic merge.
