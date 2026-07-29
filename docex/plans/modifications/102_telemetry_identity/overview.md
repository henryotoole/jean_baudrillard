# Mod 102 — Telemetry Identity

Mod 102 of the *service process types* advance. It closes the telemetry-identity
work the advance owes, which is small because Mod 096 already delivered most of
it as a side effect of the compiled-identity change.

Rule of record: [`service_processes_refactor.md § Telemetry Identity`](../../advances/004_next/service_processes_refactor.md#telemetry-identity)
(including § The sidecar arithmetic and § Two rules restate more cleanly), and
the Mod 102 section of
[`service_processes_implementation_plan.md`](../../advances/004_next/service_processes_implementation_plan.md).

## Scope

Three things, in descending size:

1. **Two resource attributes appended** to `OTEL_RESOURCE_ATTRIBUTES` on each
   process type: `docex.core_service` and `docex.process_type`.
2. **Fix the inherited leak from Mod 099** — the process segment that a
   *per-codebase* artifact should not carry.
3. **Verify, and pin with tests, three things Mod 096 already made true** rather
   than re-implementing them.

Explicitly out of scope: any doctrine file. `telemetry.md` and
`specifics/telemetry_infra.md` will read stale after this mod; that is Mod 106's,
by plan. So is the **N × R** sidecar arithmetic, which is a documentation point —
see [Findings](#findings) for the code-side verification it asked for.

## 1. The two new attributes

Appended to the existing triple, which is unchanged in content and order:

```
service.namespace=${project_name},
service.version=${project_version},
deployment.environment.name=${env},
docex.core_service=${service},
docex.process_type=${process}
```

Built at `cicl/compile.py:921-925` (the plan's `:735-739` is pre-Mod-096 line
numbering).

**Why they exist at all**, given that `service.name` is already
`{service}-{process}`: both axes must be *queryable*. "Show me every process type
of the `api` codebase" and "show me every `worker` across all codebases" are
ordinary questions, and against a fused `service.name` the only way to ask them
is a prefix or suffix match on a hyphenated string — brittle, because both
segments may themselves contain hyphens (`_SERVICE_NAME_RE` admits `-`), so
`api-web-v2` does not decompose. The design record's own rule 5 restatement turns
on exactly that ambiguity. Two attributes carrying the authoring names make the
decomposition explicit instead of recoverable.

Three supporting points:

- **The `docex.` prefix** matches the established `docex.project` docker-label
  precedent (`emit/compose.py:67-79`). It is a vendor namespace, which is what
  OTel expects for attributes outside the semantic conventions — and neither axis
  has a semantic-convention attribute (the record notes OTel has none for the
  process-type axis).
- **The values are the raw authoring names**, not DNS labels. The docker label
  uses `project_dns_label` because it is matched by a traefik constraint in the
  data plane; these are query keys in a telemetry backend, so the authoring name
  is the right one — it is what an author greps `infra.yml` for. Safe by
  construction: `_SERVICE_NAME_RE` (`cicl/model.py:24`) admits no `,` or `=`, the
  two characters that would break the attribute encoding.
- **It mirrors what elastic already does in AWS tags.** Mod 096's envinfra tag
  block splits `service = api` / `process = web` rather than carrying the fused
  identity. This gives the telemetry backend the same split. Consistency across
  the two places docex describes a workload to an outside system.

`service.version` stays `${project_version}` and `service.instance.id` stays
unset — both per the record, neither touched.

## 2. The inherited leak: what a per-codebase artifact reports

### The defect

The compiler builds two env surfaces from one tail (`compile.py:850-939`):

| Surface | Contents | Consumed by |
| ------- | -------- | ----------- |
| `env_block` | the process type's **effective** env (service ∪ process) | the app container |
| `service_env` | the **codebase**-scoped env (service-level only) | the exec service (`emit/compose.py:696`), the elastic migrate task definition (`emit/hcl.py:562`) |

`OTEL_SERVICE_NAME` is stamped inside that shared tail, before the split, so it
lands on both surfaces carrying the *process* segment of whichever process type
was being compiled. The per-codebase consumers then read `procs[0].service_env`,
and `group_by_codebase` sorts by compiled name — so for a codebase `api` with
process types `web`, `worker`, and `nightly_cleanup`, **the migration task
definition and the exec container both report
`OTEL_SERVICE_NAME=api-nightly_cleanup`**: the name of a cron job, on a
migration.

Two things make that worse than merely wrong:

- **It is unstable.** Renaming `web` → `aweb` silently changes the identity the
  migration reports. This is the same instability argument Mod 099 used to reject
  the "pick one process type" bridge for migration *sizing*; the same reasoning
  applies to the identity, and Mod 099 routed it here rather than absorbing it.

  **The pattern is worth recording.** Mod 099's two problems — migration
  *sizing* and migration *identity* — looked unrelated and had one root shape:
  a per-codebase artifact taking a value from an arbitrarily-chosen process
  type. Sizing was fixed structurally (per-dimension max, order-independent);
  identity is fixed structurally here (de-qualify, so there is nothing to
  choose). Where a codebase-scoped artifact reads a process-scoped field, look
  for a third instance.
- **It falsifies a comment that the exec service's correctness leans on.**
  `emit/compose.py:692-695` says `service_env` "is identical across a codebase's
  process types by construction … so reading it off `procs[0]` picks nothing —
  there is nothing to pick." That is true of every key *except*
  `OTEL_SERVICE_NAME`, which is precisely why the leak is invisible on
  inspection. Closing it makes the comment true, which is worth more than the
  emitted-value change.

### The decision

**In `service_env`, the telemetry identity de-qualifies to the codebase, and the
process attribute is omitted entirely:**

| Key | `env_block` (a process type) | `service_env` (the codebase) |
| --- | --- | --- |
| `OTEL_SERVICE_NAME` | `api-web` | `api` |
| `docex.core_service` | `api` | `api` |
| `docex.process_type` | `web` | *absent* |
| everything else | unchanged | unchanged |

So a migration and an exec one-off report `service.name=api`, and the presence of
`docex.process_type` becomes a clean signal in its own right: **it appears if and
only if the emitter is a declared process type.** A per-codebase operation is
queryable as "the `api` codebase, no process type" rather than by knowing which
process name to disbelieve.

Why not the two alternatives:

- **Drop the OTel quartet from `service_env` altogether.** Superficially the
  honest answer — no sidecar is paired with either artifact, so nothing collects
  what they emit. It does not survive contact with the SDK: OTLP's *default*
  endpoint is already `http://localhost:4318`, so removing
  `OTEL_EXPORTER_OTLP_ENDPOINT` does not prevent a doomed export by a
  migration that initializes the SDK — it only degrades the identity to
  `unknown_service`. Removal costs identity and buys no honesty. The doctrine
  also already ships the quartet to a container with no paired collector:
  `scheduler` process types get it, and get no sidecar (Mod 055). "No collector"
  is therefore established as *not* the criterion for "no identity".
- **Give each surface its own identity — `api-migrate` / `api-exec`.** Attractive
  for separating migration signals from application signals, but it needs either
  a third env surface or a per-emitter override of a value the compiler owns, and
  it would have to express the distinction through `docex.process_type=migrate` —
  inventing process-type values that appear in no `infra.yml` and so cannot be
  joined against the declared set. More machinery, for a signal nobody collects,
  at the cost of the attribute's meaning.

### Implementation consequence

`_build_env_surface` must take the identity as a parameter rather than closing
over `name` / `proc_name`, and the `dict(env_block)` shortcut at `compile.py:936`
must go: the two surfaces are no longer identical when a process declares no
`env:` overlay, which is exactly the case that shortcut exists for. Both surfaces
are then always built through the helper — which already happens today whenever a
process *does* declare an overlay, so it is not a new code path. Double
resolution of the service-level block is harmless: `MagicRefResolver.deps` is
append-only with no consumer, and the cycle guard is discarded in a `finally`.

## 3. Verified, not re-implemented

All three confirmed against the tree before writing this document:

| Claim | Where | State |
| ----- | ----- | ----- |
| `OTEL_SERVICE_NAME` is `{service}-{process}` | `compile.py:918` (`out[...] = name`, the compiled identity) | already true, Mod 096 |
| Reserved-key enforcement spans both env levels | `validate.py:1224-1284` — `sources` carries the service-level `env`/`secrets`/`config` **and** each process type's own `env:`, reported against that process | already true, Mod 096; already tested (`test_process_nesting.py::test_20/21`) |
| One sidecar per long-running process type, none for `scheduler` | fixed: `emit/compose.py:632-660` iterates compiled services and `continue`s on `role == "scheduler"`; elastic: the sidecar container is added only to task definitions that emit `ecs_service`, which a scheduler does not (`emit/hcl.py:420`) | already true, per-process |
| `service.instance.id` set nowhere | no occurrence in `src/` | confirmed absent |

The first and third gain pinning tests; the second is already pinned.

## Tests

Unit only — nothing here crosses docker, AWS, or git.

1. Both new attributes present and correctly valued on a multi-process codebase,
   and `OTEL_SERVICE_NAME` distinct per process type (`api-web` vs `api-worker`)
   with `docex.core_service` identical across them.
2. The existing triple unchanged — extend the exact-equality assertion in
   `test_telemetry.py::test_otel_resource_attributes_format` to the full
   five-attribute string, keeping the triple first and in order.
3. The exec container's and the elastic migrate task definition's identity
   pinned: `OTEL_SERVICE_NAME == "api"`, `docex.core_service=api` present,
   `docex.process_type` absent — asserted on a codebase whose lowest-sorted
   process type is *not* `web`, so the test fails against today's behavior rather
   than passing vacuously.
4. Process-level `env:` cannot shadow a reserved key (exists; verify it covers
   all five keys at process level, extend if it does not).
5. No `service.instance.id` in any compiled env surface, on either foundation.

Green gate: unit ≥ 942 (baseline verified at 942 before starting), full
`pytest tests/` ≥ 1006 passed / 17 deselected.

## Findings

Reported rather than acted on.

- **The N × R arithmetic is correct in code.** The record's documentation point
  holds against the emitters, so Mod 106 can document it as written. On fixed,
  Mod 100's unroll emits one sidecar per *emitted container*
  (`compose.py:651-660` keys them `{global_name}-{i}`), so N process types × R
  replicas = N × R collectors. On elastic the collector is a container inside the
  task definition, so R tasks give R collectors per process type. The 0.1 vCPU /
  128 MB overhead is added **once per task** before Fargate-tier rounding
  (`_resources_to_elastic(..., is_core=has_sidecar)`), which is right: Fargate
  sizes a task, and replicas multiply tasks rather than the per-task total. No
  defect.
- **`scheduler` process types receive the OTel quartet with no paired
  collector.** Pre-existing and deliberate (Mod 055 deferred job-level SDK
  telemetry), and load-bearing for the § 2 decision above as the precedent that
  identity is injected independently of collection. Not changed here.
- **Handoff to Mod 106.** After this mod there are *two* telemetry identity
  forms, and no doctrine file states the second one.
  `transfer_tables.md § Per-core-service env` — already on Mod 106's list for the
  `OTEL_SERVICE_NAME` row and the two new attributes — also needs the
  per-codebase form: the exec service and the migrate task definition report
  `service.name={codebase}` with no `docex.process_type`. `telemetry.md:84/113/125`
  is already on that list.

## Design questions

None. The one decision this mod owns — what a per-codebase artifact reports — is
settled in § 2 above on the reasoning given there, within the authority the
brief granted. No doctrine file, `cicl.md` or `contracts.md` rule, or version
artifact needs to change.
