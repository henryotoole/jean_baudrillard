# `defaults.elastic` is inert on every core role

**Found:** advance 006, mod 127, while designing the elastic delivery path for the
container probe. **Not fixed there** — mod 127 works *around* it with an explicit
read, and deliberately does not answer the question this brief states.

## The finding

All three core-service role tables carry the same `defaults.elastic` block:

```yml
      defaults:
        elastic:
          launch_type: FARGATE
          network_mode: awsvpc
```

`tables/roles/web.yml`, `worker.yml`, `clock.yml`. **Neither key is read by
anything.**

`emit/hcl.py::render_task_definition` hardcodes both:

```python
    out.append(f'resource "aws_ecs_task_definition" "{svc.name}" {{')
    out.append(f'  family                   = "{svc.global_name}"')
    out.append( '  requires_compatibilities = ["FARGATE"]')
    out.append( '  network_mode             = "awsvpc"')
```

`network_mode` names a real task-definition argument; the renderer supplies it as a
literal. `launch_type` is not a task-definition argument at all — on ECS it belongs to
the *service* or the `RunTask` call — and the service renderer hardcodes it too
(`hcl.py:721`, `launch_type = "FARGATE"`). So the value is emitted in both places and
**read from the table in neither**: the key routes to the default target
(`task_definition`), which is not even the resource that consumes it.

So the compile path is: `compile.py:801` reads `defaults_for("elastic")` into
`body`, `body` reaches the emitter, and the emitter reads only the keys it names
(`cpu`, `memory`, `ephemeral_storage`, `image`, `command`). Everything else in the
block falls on the floor without a warning, a log line, or a test.

## Why it is worth a brief

The output is **correct today**, which is why nothing has ever noticed. Every shipped
elastic engine wants exactly FARGATE and awsvpc, so the hardcoded literals and the
inert table entries agree by luck of there being only one possible value.

The defect is not the output. It is that **three tables in the rule-executing layer
contain instructions that nothing executes**, and no mechanism exists that could ever
say so. It is the shape advance 005 catalogued eight times — *something that could
not answer, and silence read as agreement* — and it is dangerous in exactly one way:
it teaches, by example, that adding a key to `defaults.elastic` is how you make the
elastic emitter do something.

Mod 127 nearly proved that the hard way. The container probe is a `defaults` entry by
doctrine (`transfer_tables.md`: *"The container probe is a default, not a field"*),
and the obvious implementation — add `healthCheck:` to `defaults.elastic` — would
have compiled clean, emitted valid HCL, passed every gate in `docex check`, and
shipped an elastic fleet with **no container health check at all**. Discoverable only
by a smoke walk against real AWS. It was caught by reading the renderer, not by any
tool.

## The real question

**How much of ECS may a transfer table legitimately control?**

This is a doctrine-shaped question, not a cleanup. `transfer_tables.md` says a
`defaults:` block is *"per-foundation blocks of YAML that get merged into the default
target's emitted resource"* — which reads as a general merge, and is not what the
elastic side does. The fixed side genuinely is a general merge
(`emit/compose.py::_service_block` returns `dict(svc.body)` whole), so **the two
foundations already disagree about what `defaults` means**, and that disagreement is
undocumented.

Two coherent answers. Both are defensible; this brief deliberately picks neither.

### Answer A — delete the dead keys

Remove `launch_type` and `network_mode` from all three core roles' `defaults.elastic`.
The emitter keeps its literals, which is honest: `requires_compatibilities` and
`network_mode` are compiler-owned invariants for the same reason `command` and the
traefik labels are (`hcl.py:383-400` argues this at length for `command`), and the
doctrine commits to Fargate outright — `infrastructure.md § Deferred` rules out GPU
workloads *because* of that commitment. A thing the doctrine has decided project-wide
is not a per-engine table knob.

- **Cost:** the elastic defaults block for `clock`/`worker` becomes `{}` — or, after
  mod 127, holds only the probe. A reader now sees that the elastic side of a core
  role is nearly empty, which is *true* and currently obscured.
- **Risk:** none to output. It removes the misleading example without adding a
  mechanism.
- **Leaves open:** the fixed/elastic asymmetry in what `defaults` means. A key added
  to `defaults.fixed` still lands; a key added to `defaults.elastic` still does not.
  Answer A makes that less tempting to try but does not make it detectable.

### Answer B — make the renderer honor the block generically

Merge unread `defaults.elastic` keys onto the emitted resource the way the fixed side
merges them onto the compose block, so `defaults` means one thing on both foundations.

- **Cost:** substantial and mostly hidden. The elastic default target is
  `task_definition`, but the *resource* it renders is HCL text assembled line by line
  with per-argument quoting rules (`_hcl_value`, `HCLLiteral`), not a dict serialized
  at the end. A generic merge needs a key→argument mapping and a quoting decision per
  argument, i.e. the renderer must learn the `aws_ecs_task_definition` schema. That is
  a real feature, not a refactor.
- **Risk:** it makes a table able to override compiler-owned invariants. `hcl.py`
  spends a paragraph arguing that `command` must **not** be table-overridable, because
  with N core services on one image `command` is the only thing distinguishing them —
  a bug that actually shipped and was caught by the 1.6.0 pre-cut walk. A generic
  merge reopens that class by default and would need an explicit deny-list, which is
  a second thing to keep current.
- **Gains:** genuine per-project control of ECS settings CICL cannot express today,
  via the project-local transfer-table extension mechanism — which is the stated point
  of that mechanism existing.

### A third option worth naming, which is not a fix

**Fail loudly on unread keys.** Rather than choosing, make the elastic renderer raise
(or `docex compile` report) when `defaults.elastic` carries a key no renderer reads.
This converts the silence into an answer without deciding what the block may contain.
It is cheap, it is the thing that would have caught mod 127's near-miss, and it is
compatible with either A or B landing later. It is listed third because it needs a
closed set of "keys a renderer reads," which is the same knowledge Answer B needs —
just used to reject instead of to accept.

## What mod 127 did instead, and why it is not a prejudgment

Mod 127 adds an explicit, named read of `body["healthCheck"]` in
`render_task_definition`, with a comment stating that the block is **not** generically
consumed and that `launch_type`/`network_mode` are inert. That is the minimum change
that makes the probe actually reach the container, and it takes no position on this
question: under Answer A the comment stays true and the read stays; under Answer B the
read is subsumed by the generic merge and the comment is deleted.

## Where to look

- `tables/roles/{web,worker,clock}.yml` — the three `defaults.elastic` blocks.
- `src/docex/cicl/compile.py:798-802` — where `defaults` become `body`.
- `src/docex/emit/hcl.py::render_task_definition` — the key-by-key reads and the
  hardcoded `requires_compatibilities` / `network_mode`.
- `src/docex/emit/compose.py::_service_block` — the fixed side's whole-body
  pass-through, i.e. the other definition of `defaults`.
- `doctrine/infrastructure/specifics/transfer_tables.md` § *Anatomy of a Role
  Definition*, the `defaults` and `emits` bullets — the prose both answers must be
  reconciled against.
