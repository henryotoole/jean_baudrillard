# Mod 100 — Replicas

Phase 3 of the **service process types** advance
([plan](../../advances/004_next/service_processes_implementation_plan.md),
[design record](../../advances/004_next/service_processes_refactor.md)).
The rule of record is the design record's
[§ Replicas](../../advances/004_next/service_processes_refactor.md#replicas),
including its § Validation and caveats.

**One doctrine edit lands here: rule 5's text in `cicl.md`, and nothing else in
that file** — the same precedent as Mod 095 (rule 28) and Mod 099 (rule 5's
first widening), since Mod 106's file list does not include `cicl.md`. Every
other doctrine consequence of this mod, including `shape.md`'s factually wrong
claim that the reverse proxy load-balances *worker* replicas, is Mod 106's and
is planned, not drift.

Baseline verified before design: **902 passed** (`pytest tests/unit`),
**966 passed / 17 deselected** (`pytest tests/`), **17 collected**
(`pytest -m integration --collect-only`).

## Goal

`replicas` has been declared, range-checked, allow-listed, documented in
`cicl.md` and `shape.md`, and carried onto `CompiledService` (Mod 096) — and
read by **no emitter at all**. `hcl.py:678` hardcodes `desired_count = 1`.
"Two web, four workers", this advance's motivating capability, does not work
today even with nesting landed. This mod makes the field do what it says.

Two halves that share exactly one rule (the prod clamp) and nothing else:
elastic sets a count; fixed unrolls into distinct services because it cannot
set a count.

## What lands

### 1. One clamp rule, in one place

```python
# cicl/compile.py, beside group_by_codebase
def effective_replicas(svc: CompiledService, env: str) -> int:
    """Declared `replicas`, clamped to 1 outside `prod`."""
```

Returns `1` for a non-core service and for every env but `prod`; otherwise
`max(1, svc.replicas)`. Both emitters call it, so "replicas apply only in
prod" is stated once and testable on its own rather than being asserted twice
in two different languages.

It lives in `compile.py` rather than on `CompiledService` as a property because
the clamp needs the env, and storing a pre-clamped value on the compiled
service would destroy the distinction between *declared* and *effective* —
which `describe` (Mod 104) will want, and which the rule-5 check below reads.

### 2. Elastic — `desired_count`

`render_ecs_service` (`hcl.py:678`) emits
`desired_count = effective_replicas(svc, ctx.env)` in place of the literal `1`.
That is the entire elastic change.

No deployment-configuration work, per the design record: nothing is emitted
today, so ECS's defaults (`minimum_healthy_percent = 100`,
`maximum_percent = 200`) apply, and those are correct for a static count.
Sidecars need no thought — the collector is a container *inside* the task
definition, so N tasks give N sidecars by construction.

Nothing else on elastic assumes a count of one: there is no
`wait services-stable` call anywhere in `src/` (`ecs_wait_for_task` exists only
for the migration `RunTask`, which is not a service), and no renderer reads a
task count.

**Mod 095 earns its keep twice here.** A worker ECS service has no target
group, so without the container-level `healthCheck` that mod routed through the
new `container_definition` destination, ECS would consider a task healthy the
instant it reached RUNNING and roll a broken deploy through all four replicas.

### 3. Fixed — unroll, do not scale

`deploy.replicas` cannot work, and the reason is the sidecar. On fixed the
collector pairs via `network_mode: "service:<svc>"` to share the app
container's netns; Compose has no replica-to-replica pairing semantics, so one
sidecar cannot pair with N replicas. `deploy.replicas` additionally forces
dropping `container_name` (Compose refuses both together), costing the
container-name DNS entry and the readable names operators debug with.

So `emit/compose.py` emits **N distinct compose services**:

```yml
  sample-prod-api-web-1:
    container_name: sample-prod-api-web-1
    image: sample/api:0.1.0
    networks:
      internal:
        aliases: [sample-prod-api-web]     # ← load-bearing
      web:
        aliases: [sample-prod-api-web]
    labels:
      - traefik.http.routers.sample-prod-api-web.rule=Host(`api-web.prod...`)
      - traefik.http.services.sample-prod-api-web.loadbalancer.server.port=8080
      # …identical on every replica…
  sample-prod-api-web-1-otelcol:
    container_name: sample-prod-api-web-1-otelcol
    network_mode: "service:sample-prod-api-web-1"
  sample-prod-api-web-2:
    …
```

Mechanically: where the per-service loop today does
`services[svc.global_name] = block`, it instead writes `N` copies keyed
`{global_name}-{i}` for `i` in `1..N`, each a `deepcopy` of the same block with
`container_name` and `networks` rewritten. The sidecar pass pairs one collector
per emitted replica rather than per compiled service.

#### Why the emitter and not the compiler

The plan's one-line docex-work bullet reads *"`cicl/compile.py` — … unroll
`replicas` on fixed-prod"*. Taken literally — unrolling into N
`CompiledService` entries — that is wrong, and the mod deliberately does not do
it.

**A replica is an emission detail, not a topology node.** That is the principle;
everything below is why it holds.

`CompiledEnv.services` is the advance's **topology model**, not its emission
list. It is consumed by `describe/{dag,llm}.py` (nodes), `pipeline/check.py`
(contract and health gates), `group_by_codebase` (the exec service, the migrate
task definition, the ansible playbook), `_named_volumes`, and the network
section. Four `api.worker` replicas are one process type, one contract, one
health target, one exec service, one image. Unrolling into the compiled model
would make `describe` render four worker nodes, make the contract gate see four
providers, and emit four exec services per codebase — each a separate bug in a
separate file.

The advance plan's docex-work bullet placing the unroll in `cicl/compile.py` is
**corrected on the C.O.'s side**; this mod is the record of why.

So the compiled model keeps `replicas: int` as an attribute (exactly where Mod
096 put it), and the *emission* multiplies. On elastic the same attribute
becomes a count on one resource, which is the same statement in the other
foundation's language. The blast radius is one emitter and one literal.

#### Every invariant, and how it survives

| Invariant | Mechanism | Test |
| --------- | --------- | ---- |
| **`provides.host` unchanged** | Shared network alias `{global_name}` on **every** network of **every** replica; Docker DNS returns all N and round-robins. `provides.host` still resolves to "the process type", which is what it always meant. | 3 |
| **Sidecar stays 1:1, stays on loopback** | One sidecar per *emitted replica*, keyed `{replica_key}-otelcol`, `network_mode: service:{replica_key}`. `OTEL_EXPORTER_OTLP_ENDPOINT` is untouched and identical across foundations. | 4 |
| **Traefik aggregates** | `_traefik_labels` is called with the *compiled* service and therefore keys on the **unqualified** `{global_name}`; the label list is byte-identical across replicas, so traefik's docker provider sees N containers declaring one router and one service and loads them as N servers. Written down in a `WHY` comment at the call site, not left to chance. | 5 |
| **`container_name` survives** | `{global_name}-{i}`, so `docker logs …-api-web-3` works. | 2 |
| **No host-port collisions** | Nothing to do: Mod 096 removed host-port publishing for non-`web` core process types and `web` never published. There is no `ports` key in the fixed core-service emission path at all. Pinned anyway, because it is the property that makes the unroll viable. | 8 |

The **networks list→map conversion is new machinery** — there is no `aliases`
handling anywhere in the emitter today; `_apply_fixed_invariants` writes
`networks: [internal, web]` short-form and the compose emitter passes it
through. The conversion happens **only on the unroll path**, so the N==1 output
keeps the short-form list byte-for-byte.

The alias is placed on **every** network the process type joins, per the design
record's example. A consumer resolves `{global_name}` from whichever network it
shares with the target; restricting the alias to non-`web` networks would break
a web→web reference for no gain.

### 4. Rule 5's uniqueness domain gains the replica index

Mod 099 widened rule 5 to cover compiler-emitted derivatives (`-otelcol`,
`-scheduler`, `-exec`, `-migrate`). The replica index is exactly such a
derivative and it collides the same way:

> Core service `api` with process types `web` (`replicas: 3`) and `web-1`
> renders `api-web-1` twice — once as the compiled identity of the `web-1`
> process type, once as replica 1 of `web`. One compose key, one container
> silently clobbering the other, **in prod-fixed only**, which is the worst
> place to discover it.

It is reachable: `_SERVICE_NAME_RE` admits hyphens and digits after a leading
letter, so `web-1` is a legal process name (`1` alone is not — it must start
with a letter — so the reverse pairing does not arise).

`_validate_rendered_identity` seeds `{compiled}-{i}` for `i` in `1..replicas`,
**only when `replicas > 1`**. Gating on the declared value keeps the rule
faithful to its own stated principle — *"it does not forbid a name that happens
to be harmless in a project where nothing collides with it"* — since with
`replicas: 1` the suffix is never emitted by anything. Unlike `-migrate` (which
is seeded unconditionally because whether it exists depends on a *different*
service's `schema_owned_by`, i.e. action at a distance), bumping `replicas`
from 1 to 4 is an edit on the very process type in question, so the error
appears in the reader's hand at the moment they create the collision.

**Seeding the container identity alone is sufficient; the replica sidecars need
no seed.** A sidecar collision requires `{P}-otelcol == {Q}-{i}-otelcol`, i.e.
`P == Q-i`, which is precisely the container-level collision already seeded.
Recorded so a later reader does not "complete" the seeding and make the
validator quadratic in replica count for nothing.

Validation is document-level and foundation-agnostic, so an elastic-only
project also gets the check even though elastic never unrolls. That matches how
every other seed in this function already behaves, and the cost is a rename of
a process name that was confusing regardless.

### 5. `replicas` on a `scheduler` — already done

The design record's one validation requirement for this mod is already
implemented: **rule 26** (`validate.py:1469-1494`) landed in Mod 096, keyed off
`model_fields_set` so it fires on a declared `replicas: 1` too, and is pinned by
`test_process_nesting.py::test_15_replicas_on_scheduler_rejected` plus its
`_clean` twin. Nothing to add. Named here so the mod's scope reads as complete
rather than as having skipped it.

The other half of § Validation and caveats — *a process type with
`replicas > 1` must tolerate siblings* — is explicitly "a project responsibility
the doctrine cannot catch", so it is a documentation point (Mod 106) and not a
check.

## Blast radius, and the guard that pins it

`replicas` applies only in `prod`, so `dev`, `test`, and fixed `stage` unroll to
exactly one. Their output must be **byte-identical to today**, and the cheapest
possible guard on this mod not regressing five other mods' work is to assert
exactly that:

> Compile the three-process fixture twice — once as-is, once with
> `replicas: 4` on the worker and `replicas: 2` on the web process — and assert
> `dev`, `test`, and `stage` `docker-compose.yml` are byte-identical between the
> two runs.

That single assertion covers the whole N==1 path: no alias map, no `-1` suffix,
no extra sidecar, no changed key ordering, no changed top-level sections.

### The `_named_volumes` watch item — checked, not tripped

`_named_volumes` (`compose.py:90-104`) iterates `compiled.services` — the
*compiled* services, not the emitted ones — so a volume introduced by a derived
compose service would never be declared top-level. The unroll does not trip it,
for two independent reasons:

1. The unroll introduces **no new volume reference**. Each replica's block is a
   copy of the compiled service's body, so the set of volume strings across all
   emitted replicas is exactly the set `_named_volumes` already walks.
2. Core roles declare no persistent storage in the first place. `web` and
   `worker` carry only `tmpfs` (derived from `resources.disk`), which is a
   separate compose key and per-container by construction — so each replica gets
   its own scratch, correctly.

Pinned by test 7 (prod's top-level `networks:` and `volumes:` sections identical
between the 1-replica and N-replica compiles).

Worth recording for whoever reads this next: if a core role ever *did* gain a
named volume, N replicas would all mount the same one, which is a
stateless-process violation (12-factor Factor 6), not an emitter bug. The
emitter is not the right place to catch it.

## Test plan

New `tests/unit/test_replicas.py`, built on `test_process_expansion_emit.py`'s
three-process fixture pattern (copy fixture → patch `infra.yml` → `run_compile`),
with `replicas: 4` on `api.worker` and `replicas: 2` on `api.web`.

**Fixed emission**
1. `prod` emits `sample-prod-api-worker-{1..4}` and **no** bare
   `sample-prod-api-worker` key.
2. Each replica's `container_name` equals its compose key.
3. Each replica's `networks` is map form with `aliases: [sample-prod-api-worker]`
   on **every** network it joins.
4. Four sidecars `sample-prod-api-worker-{i}-otelcol`, each with
   `network_mode: service:sample-prod-api-worker-{i}`; the app containers'
   `OTEL_EXPORTER_OTLP_ENDPOINT` is unchanged.
5. Across the two `web` replicas: exactly **one** distinct traefik router key and
   **one** traefik service key, both the unqualified `sample-prod-api-web`; the
   full label list is identical between replicas.
6. **`dev`, `test`, `stage` compose bytes identical** to a compile of the same
   project with no `replicas` declared.
7. `prod`'s top-level `networks:` and `volumes:` sections identical to the
   1-replica `prod` compile (the `_named_volumes` guard).
8. No `ports` key on any replica.
9. Each replica's `depends_on` is rewritten long-form to
   `{sample-prod-appdb: {condition: service_healthy}}` — the second pass still
   reaches derived services.
10. Exactly **one** `sample-prod-api-exec` in `prod` — the exec service is
    per-codebase and does not multiply.

**Elastic**
11. `prod` `aws_ecs_service.api-worker` carries `desired_count = 4`, and there
    is still exactly **one** `aws_ecs_service` and one `aws_ecs_task_definition`
    per process type (no unroll on elastic).
12. `stage` carries `desired_count = 1` for the same declaration.
13. A project declaring no `replicas` emits `desired_count = 1` everywhere —
    byte-identical `main.tf` to the pre-mod snapshot.

**Clamp helper**
14. `effective_replicas` returns N in `prod`, 1 in `dev`/`test`/`stage`, and 1
    for a backing service.

**Rule 5**
15. `api` with `web` (`replicas: 3`) and `web-1` is rejected with
    `rule_5_rendered_identity_collision`, and the message names the replica
    rather than a service the author never wrote.
16. The identical project with `replicas: 1` is clean — the rule is not
    over-eager.

**Regression:** all four fixtures and both `test_projects` still compile
(covered by the existing suite); `pytest -m integration --collect-only` still
collects 17.

## Integration tests that exercise stale paths

Honestly: **almost none**, and that is itself the finding worth reporting.

| Test | Why / why not |
| ---- | ------------- |
| `test_compile.py` (mostly unmarked, runs in the 966) | Compiles all four envs of both fixtures, so it is the broad net that catches an accidental change to the N==1 path. Not replica-specific. |
| `test_hcl_validate_real.py` | Runs `tofu validate` over emitted HCL and therefore covers the `desired_count` line — but **only with the value `1`**, since no test project declares `replicas`. |
| everything else (`test_up_down_real`, `test_migrate_real`, `test_test_real`, `test_build_real`, `test_check_real`, `test_stagetest_real`) | All run against `dev`, which clamps to 1. Unreachable by this mod's changed code by construction. |

**No integration test exercises a replica count above 1, on either foundation,
and none can**: the replica path is prod-only, the smoke projects declare no
`replicas`, and the integration suite never brings up `prod`. Recommendation for
**Mod 107**, which is already migrating both smoke projects and adding a genuine
`worker` process type: declare `replicas: 2` on that worker in the **elastic**
smoke project, which costs nothing (elastic prod is never brought up in the
suite either) but puts a real `desired_count = 2` through `tofu validate` in
`test_hcl_validate_real.py`. The fixed unroll will still only ever be exercised
by unit tests and by the pre-cut smoke walk if that walk reaches prod.

## Out of scope

`check.py` gates (101) · telemetry (102) · ofelia (103) · `describe` and
preinfra (104) · rollback (105) · **any doctrine file** (106) · any version
artifact (107).

`describe` is untouched deliberately: `replicas` is an attribute of a node, not
a node, and whether the DAG should surface the count is Mod 104's call. Nothing
in `describe` breaks — it reads `compiled.services`, whose cardinality this mod
does not change.

## Observation for the operator (not a blocker)

The prod-only clamp is `shape.md`'s rule and I am implementing it as directed.
It does have a consequence worth having on the record before the cut: **the
replica shape is never rehearsed in `stage`.** `stage` exists to "test a release
with production-equivalent infrastructure", and with the clamp, a four-replica
prod worker runs multi-instance for the first time in production — the first
place a sibling-intolerance bug (the very caveat § Validation and caveats warns
about) can surface. This is pre-existing doctrine, not something this mod
introduces, and changing it means changing `shape.md`. Noting it, not acting on
it.

**Escalated.** The C.O. judged this less non-blocking than framed — a
dev/prod-parity hole in a doctrine that cites 12-factor for parity — and is
raising it to the operator as an open question rather than leaving it in a mod
overview. It remains out of this mod's scope either way.

## Design questions — both resolved by the C.O. before implementation

**Recorded as settled.** Q1 → **Option A**: the `cicl.md` rule 5 clause lands
**here**, alongside the validator, on the Mod 095 (rule 28) and Mod 099 (rule 5)
precedent that `cicl.md` has no downstream owner — Mod 106's file list excludes
it, so Option B would leave the enumeration incomplete with no mod owning the
gap, which is exactly the drift `docex_process.md § Additional Artifacts`
exists to prevent. The rule text and the validator's error message must say the
same thing. Q2 → **seeding confirmed**, gated on `replicas > 1`; that the
collision only bites in prod-fixed makes it *more* worth catching at compile,
not less, because it is the configuration nobody rehearses.

The original statements of both questions follow, for the record.

**1. Does the `cicl.md` rule 5 text edit land here, or in Mod 106?**

Rule 5's text (`cicl.md:569`) enumerates the compiler-appended derivatives as
"`-otelcol` …, `-scheduler` …, `-exec` …, and `-migrate` …" and then states the
rule is "keyed on **collision, not on a list of forbidden names**, which is what
makes it cover every suffix the compiler learns in future **without a further
edit**."

So the validator seeding in [§ 4](#4-rule-5s-uniqueness-domain-gains-the-replica-index)
is authorized by the existing text on its own terms and needs no doctrine change
to be correct. But the enumeration reads as exhaustive to a human, and the
error message enumerates too, so a reader hitting a replica collision would find
the doctrine silent on the suffix that bit them.

- **Option A (recommended).** Add one clause to rule 5 naming the replica index,
  here, alongside the validator — matching Mod 099's precedent exactly (it
  updated rule 5's text in `cicl.md` and nothing else in that file, because Mod
  106's file list does not include `cicl.md`, and Mod 095 did the same for rule
  28). Doctrine text and validator ship together; nothing about rule 5 is left
  for 106.
- **Option B.** Seed the validator here and leave the text alone, on the
  strength of the "without a further edit" clause. Costs nothing mechanically,
  but leaves the enumeration and the error message quietly incomplete, and there
  is no mod downstream that owns closing it.

Your standing instruction is that a `cicl.md` change is your call. This is the
only doctrine edit this mod would make.

**2. Confirm the rule 5 seeding itself** (gated on `replicas > 1`) is wanted at
all. You asked me to decide and say so, and I have decided **yes** — the
argument is in [§ 4](#4-rule-5s-uniqueness-domain-gains-the-replica-index). If
you would rather the domain stop at Mod 099's four fixed suffixes and leave the
replica index uncovered, say so and it comes out; the rest of the mod is
unaffected either way.
