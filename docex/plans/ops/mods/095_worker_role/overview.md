# Mod 095 — The `worker` role + the `container_definition` destination

Phase 1 of the **service process types** advance
([plan](../../advances/004_next/service_processes_implementation_plan.md),
[design record](../../advances/004_next/service_processes_refactor.md)).

## Goal

Make `role: worker` a real, bundled role that compiles on both foundations, and
build the one piece of emit machinery it needs: a route from a transfer-table
field into the ECS **container definition**.

**Purely additive.** Nothing about `processes:` nesting exists yet and none of it
is built here. What lands is a *flat* `role: worker` core service — a sibling of
`role: web` and `role: scheduler` at the top level of `core_services:` — that
compiles clean today. That is deliberate: it keeps this diff separately
reviewable, and it means Mod 096 inherits a working role rather than building one
inside the break.

## Why the worker needs new machinery at all

`web` routes `health_check_path` to `target_group` on elastic. A worker has no
target group — it is not an ingress target — so its natural destination is the
ECS **container-level** `healthCheck`. There is no route there today:
`render_task_definition` (`emit/hcl.py:311-540`) builds `container_def`
procedurally and reads only four *task-level* keys off `svc.body` (`cpu`,
`memory`, `ephemeral_storage`, `image`). There is **no `healthCheck` key anywhere
in `src/`**.

That container healthCheck earns its keep twice. Beyond probing the consume loop,
it is what makes a worker's rolling deploy gated at all: with no target group,
ECS would otherwise call a task healthy the instant it reaches RUNNING and roll a
broken deploy through every replica (design record § Replicas → Elastic).

## The five changes

### 1. `docex/tables/roles/worker.yml` (new)

Shape per the design record § The `worker` Role, checked against the loader
(`cicl/transfer.py`) and against the sibling tables. Verified properties:

| Property | Value | Checked against |
| -------- | ----- | --------------- |
| engine key | `container` | matches `web`/`scheduler`; `compile.py:514-520` picks the first foundation-supporting engine of the role |
| `emits.fixed` | `[compose_service]` | only legal fixed destination (`transfer.py:84`) |
| `emits.elastic` | `[task_definition, ecs_service, container_definition]` | `task_definition` first ⇒ it is the default target, so `defaults.elastic` lands there, as for `web` |
| `target_group` | **absent** | a worker is not an ingress target |
| `health_check_path` fixed | compose `healthcheck` (no `target:` ⇒ default target) | identical to `web` |
| `health_check_path` elastic | `target: container_definition`, body `healthCheck: {...}` | needs changes 2-4 |
| `provides` | `{host, port}` | both `${global_service_name}` / `${port}`, as `web` |
| `default_port` | **absent** | see below |
| `naming` | `ecs` | resolves in `tables/naming_policies.yml` |
| `defaults.elastic` | `launch_type: FARGATE`, `network_mode: awsvpc` | as `web` |

**No `default_port`**, per the design record: an implicit health port would
silently oblige the app to bind it, and a missed binding would become an ECS kill
loop rather than a compile error. Change 5 is what makes that choice safe.

Nothing else in the compiler is role-keyed in a way that needs teaching about
`worker`. The two role tests in the emitters (`compose.py:454,552,618,661`) all
gate on `scheduler`, so a worker takes the `web`-shaped path: a normal compose
service, a paired OTel sidecar (correct — it is long-running and emits
application telemetry), an ECS service with a Service Connect `service {}` block
(correct — that is what makes it discoverable for the one-hop health probe).
Everything else is network-driven, not role-driven: traefik labels, target
groups, and the check step's provider set all key off `"web" in networks`, and a
worker is not on `web`.

### 2. `container_definition` as an emit destination

Added to `EMIT_DESTINATIONS["elastic"]` (`cicl/transfer.py:83-95`). The comment
there is explicit that this is not a free extension surface — a new destination
obliges growth in the routing layer, which is changes 3 and 4.

### 3. Registered as a **no-op** renderer

`container_definition` is a **merge target, not a resource**. It has no HCL block
of its own; it modifies a block another destination already emits. But
`_DESTINATION_RENDERERS` (`hcl.py:927-936`) is the dispatch loop's lookup table,
and an unregistered destination falls into the defensive branch at `:983` that
emits `# unknown destination …` into the output. So it is registered, returning
`""`, with a docstring that says plainly why — a bare `return ""` reads as a bug.

Registering it is also what satisfies transfer-table validation rule 12
(`validate.py:586-610`: a field's `target:` must appear in the engine's
`emits.<foundation>`) without emitting a second resource.

One small robustness fix rides along: `render_service` (`hcl.py:979-991`) will
skip a renderer that returns empty rather than appending it plus a blank line.
Harmless today because `container_definition` sits last in the worker's emits
list, but it should not depend on ordering.

Rejected alternative: suppressing it in `_destination_applicable`
(`hcl.py:939-959`). That function answers "is this destination *conditionally*
emittable for this service" — `target_group` is there because it depends on web
membership. `container_definition` is *never* independently emittable, which is a
property of the destination, not of the service, so the registration table is the
honest home for it.

### 4. Merged into the container definition

`render_task_definition` merges `svc.target_extras.get("container_definition", {})`
into `container_def`, mirroring how `render_target_group` reads
`svc.target_extras.get("target_group", {})` at `:631`.

**Placement: after `environment`/`secrets` (`:348-351`), before the `dockerLabels`
/ `mountPoints` / `dependsOn` whole-key assignments (`:357`, `:380`, `:412`).**
Those three assign whole keys unconditionally, so placing the merge ahead of them
establishes the precedence rule: *the compiler's procedurally-derived container
keys win over table-supplied ones.* That is the right way round — traefik labels,
EFS mounts, and the sidecar `dependsOn` are compiler-owned invariants, not things
a transfer table should be able to override. Documented in a comment at the merge
site, since the ordering is load-bearing and invisible.

**The migrate container (`:503-538`) does not receive the extras.** Agreeing with
the C.O.'s instinct, for three reasons:

1. The one thing the extras carry is a `healthCheck` derived from
   `health_check_path`. The migrate container runs `/service/migrate.sh` and
   exits; it never binds the health port. It is `essential: true`, so an ECS
   healthCheck against a port nothing is listening on turns every elastic
   migration into a kill loop.
2. Precedent within the same function: the migrate container already, and
   deliberately, omits every long-running-only addition — `portMappings`,
   `dockerLabels`, `mountPoints`, `dependsOn`, and the paired sidecar. The
   comment at `:396-408` states the general rule for one-shot tasks.
3. Symmetry with `web`, whose migrate container has never received the
   target-group health check either.

### 5. Validation: `health_check_path` requires `port`

Doctrine first, per `docex_process.md` step 1. **`cicl.md § Validation Rules`
gains rule 28** — *every process type that declares `health_check_path` also
declares a `port`* — phrased in process-type terms even though the code enforces
it on flat services, because the doctrine has described process types since Mod
094 and a flat phrasing would be wrong the moment Mod 096 lands. Mod 096 re-scopes
it onto the process type along with rules 10/12/14/15/16. That is the **only**
doctrine edit in this mod.

The rule exists because change 1's deliberate omission of `default_port` leaves a
hole. `${port}` resolves to the empty string when a service omits `port:`
(`compile.py:542-543`), so the emitted probe becomes `http://localhost:/health` on
both foundations — malformed, and it surfaces as a container that never becomes
healthy rather than as a compile error. Nothing catches it today: rule 15 requires
a `port` only for *web-network* services, and a worker is not on `web`; Mod 101's
coming requirement covers only process types named as a `consumes` target, so an
unconsumed worker still slips through.

Enforcing it serves the design record's stated intent rather than extending it.
The record rejects a doctrine-fixed health port *precisely because* an explicit
`port` "keeps the requirement visible" — and nothing was making it visible.

Implementation is role-agnostic and stays that way: it is vacuous for `web`
(rule 15 already covers web-network services) and must not be special-cased away
for any role.

## Test plan

New `tests/unit/test_worker_role.py` (note: `tests/unit/test_roles.py` exists but
is a 0-byte file). Unit tests only — nothing here crosses docker, AWS, or git.

Fixtures are **not** modified. The compile tests copy `sample_project` /
`sample_project_elastic` into `tmp_path` (the `_copy`/`_compile` helpers in
`test_scheduler.py` are the pattern) and inject a `worker` core service into
`infra.yml` before compiling. Two reasons: adding a permanent service to the
shared fixtures would churn unrelated emitter tests, and Mod 096 rewrites all
four fixtures anyway — no point growing the set that has to be rewritten.

| # | Test | Asserts |
| - | ---- | ------- |
| 1 | role table loads | `worker/container` present; exact `emits` per foundation; **no** `target_group`; `default_port is None`; `provides` = `{host, port}`; `naming == "ecs"` |
| 2 | fixed compile | one compose service for the worker, carrying a `healthcheck` block with the substituted `${port}${field_value}` URL; the app image; no traefik router labels |
| 3 | elastic compile | `aws_ecs_task_definition` + `aws_ecs_service` emitted; **no** `aws_lb_target_group`; the *app* container's JSON carries `healthCheck` (command / interval / timeout / retries / startPeriod); the sidecar container does not |
| 4 | rule 12 rejection | a project-local table routing a field to `target: container_definition` without declaring it in `emits.elastic` yields `FIELD_TARGET_UNDECLARED` (mirror `test_validate.py:394-423`) |
| 5 | no stray output | the `container_definition` destination contributes no HCL resource block and no `# unknown destination` comment |
| 6 | rule 28 | `health_check_path` without `port` is rejected; with `port` it passes; a `web` service is unaffected |

Full `pytest` unit suite must be green; the result gets reported honestly.

`tests/unit/test_roles.py` is **deleted** — it is a 0-byte file that reads as
"roles are tested" to anyone grepping.

## Artifact alignment

Per `docex_process.md § Additional Artifacts`, with the C.O.'s exception:

| Artifact | This mod |
| -------- | -------- |
| `doctrine/**` | **`cicl.md § Validation Rules` rule 28, and nothing else.** The rest of the rule of record landed in Mod 094 (`cicl.md` already carries `role: worker`). `specifics/transfer_tables.md` is **Mod 106's** and explicitly off-limits here — see the note below. |
| `docex/plans/core/*.md` | No edit needed. `masterplan.md` does not enumerate roles or emit destinations (verified by grep). |
| `tables/roles/*.yml` | New `worker.yml`. |
| `src/docex/**` | `cicl/transfer.py`, `emit/hcl.py`, `cicl/validate.py`. |
| `tests/**` | New `tests/unit/test_worker_role.py`; delete the 0-byte `tests/unit/test_roles.py`. |

Nothing in `transfer_tables.md` is *contradicted* by this mod — it is merely
silent. Its bundled-engine list (`:436`) omits `worker` and its destination
examples (`:285`) omit `container_definition`; both are additions, not
corrections. Left for Mod 106.

No version artifact is touched (Mod 107).

## Out of scope, deliberately

- Anything `processes:`-shaped. Mod 096.
- `replicas` (still inert). Mod 100.
- Contract format derivation for `worker` providers, and the `consumes`-driven
  health gates. Mod 101.
- A container-level `healthCheck` for the `web` role — recorded as deferred in
  the design record; changing existing `web` behavior here would defeat the point
  of a separately-reviewable diff.

---

## Design questions — resolved

Both were raised at design review and ruled on; recorded here so the reasoning
survives the mod.

**1. A `worker` declaring `health_check_path` with no `port` emits a broken probe,
silently.** **Ruled: implement the rule.** It serves the design record's stated
intent rather than extending it — the record rejects a doctrine-fixed health port
*because* an explicit `port` "keeps the requirement visible", and nothing was
making it visible. Scoped narrowly and role-agnostically, doctrine first as
`cicl.md` rule 28. See [change 5](#5-validation-health_check_path-requires-port).

**2. Fixed host-port publishing for a port-declaring non-web core service becomes
live with this mod.** **Ruled: leave it to Mod 100.**

`compile.py:647-648` publishes `{port}:{port}` to the host for any core service
with a `port` that is not on the `web` network. Until now no such service
existed — `web` is on `web`, and schedulers declare no port. A `worker` with a
health port is the first, so **from this commit onward a `worker` on fixed
publishes its health port to the docker host.** That is live-but-wrong behavior
for five mods.

Accepted, and recorded here so it is discoverable to anyone who bisects to this
commit. It is acceptable because nothing ships before the cut, no fixture
exercises it, and no test in this mod depends on the behavior in either
direction — so Mod 100's fix (stop publishing host ports for non-`web` core
process types) costs nothing extra for having waited. It is already tracked as
operator item #2 against Mod 100, where unrolled replicas turn it from untidy
into an actual host-port collision.
