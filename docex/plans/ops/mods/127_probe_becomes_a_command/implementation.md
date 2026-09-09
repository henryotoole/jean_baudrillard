# Mod 127 — implementation steps

Written for a fresh context. Design rationale lives in
[`overview.md`](./overview.md); read § 2 (the elastic delivery path) and § 3 (the
three derivatives) before touching `emit/hcl.py`, because both decisions there are
counter-intuitive and were approved individually.

**Project root:** `/home/ubuntu/.claude/jean_baudrillard/docex`. Run everything with
`python3` (there is no `python` on this machine).

**Baseline to hold or beat**, both re-derived at design time on this branch at
`fa5d3fb`, not inherited from a prior report:

- unit — **1041 passed**
- integration — **18 passed, green** (`pytest tests -m integration`, 7m47s)

Re-derive both again at the end. **Do not inherit a number, including these two.**

**Do not touch:** `test_projects/` (mods 129/130 — their compiled output *will* go
stale from this change and that is booked, not a defect), `pipeline/stagetest.py`
(128), `pipeline/check.py` (126), `plans/core/masterplan.md` (131), any file under
`doctrine/`, and the three backing-service role tables
(`cache.yml`, `object_store.yml`, `relational_db.yml`).

---

## Step 1 — `tables/roles/web.yml`

### 1a. Add the probe to `defaults`

Replace the `defaults:` block. The `fixed:` body is currently `{}`.

```yml
      defaults:
        # Routing is network-driven, not role-static: the compiler emits
        # Traefik discovery labels (fixed) and an ALB target group + listener
        # rule (elastic) for ANY service on the `web` network, with
        # per-service subdomains. See networks.md and cicl.md § Domain.
        #
        # The container probe is a DEFAULT, not a field: `health.sh` is
        # emitted for every core service on both foundations and needs
        # nothing from infra.yml but the service's own name. Cadence is
        # doctrine-fixed and uniform across every core service — it is not a
        # project-tunable knob. See healthchecks.md § The orchestrator
        # carries the result.
        fixed:
          healthcheck:
            test: ["CMD", "./health.sh", "${service}"]
            interval: 30s
            timeout: 5s
            retries: 3
        elastic:
          launch_type: FARGATE
          network_mode: awsvpc
          # `CMD`, not `CMD-SHELL`: a command probe needs no shell and no
          # `|| exit 1` exit-code laundering. Exec form on both foundations is
          # what makes the two emissions one translation rather than two
          # adaptations. `./health.sh` resolves against WORKDIR /service,
          # which infrastructure.md § Codebase Containers fixes for every
          # codebase image.
          #
          # `startPeriod` is elastic-only ON PURPOSE. ECS KILLS a task whose
          # essential container fails its probe and the service replaces it,
          # so a start grace prevents a container being killed before it has
          # written its first tick. Docker only REPORTS `unhealthy` — nothing
          # on fixed acts on it except traefik, which drops the container
          # from its pool, and that is the correct treatment of a container
          # that is not ready yet. A fixed `start_period` would suppress
          # correct behavior rather than prevent a wrong consequence.
          healthCheck:
            command: ["CMD", "./health.sh", "${service}"]
            interval: 30
            timeout: 5
            retries: 3
            startPeriod: 10
```

`${service}` — **not** `${service_name}`. `compile.py:755` supplies `"service"`.

### 1b. Narrow `health_check_path` to its elastic translation

Delete the entire `fixed:` sub-block of `fields.health_check_path` (the curl
`healthcheck`). Keep the `elastic:` sub-block byte-for-byte. Add the comment:

```yml
      fields:
        health_check_path:
          # No fixed translation. On fixed, traefik takes target health from
          # the container healthcheck in `defaults` above, so the path has no
          # fixed consumer — but the field is still DECLARED here, which is
          # what makes rule 4 accept it in a fixed project's infra.yml and
          # keeps a project portable across foundations. Rule 33 requires it
          # on every `web`-network core service on both foundations.
          elastic:
            target: target_group
            ...unchanged...
```

Leave `emits`, `provides`, `env`, `naming`, and the file header alone.

---

## Step 2 — `tables/roles/worker.yml`

1. **Add the same `defaults` probe blocks** as Step 1a (both foundations, identical
   bodies — `${service}` resolves to `worker` for a core service named `worker`).
2. **Delete `fields.health_check_path` entirely.** `fields:` has no other entry, so it
   becomes:

   ```yml
      fields: {}   # Rule 4 (tt_rule_4_undeclared_field) now REJECTS
                   # `health_check_path` on a worker, which is how rule 33's
                   # negative arm is enforced at the table layer with no
                   # second rule — the same mechanism clock.yml documents for
                   # `schedules`.
   ```

3. **Reword the `provides:` comment.** It currently reads *"A worker that declares a
   `port` registers as Service-Connect-discoverable on elastic (shape.md §
   service_discovery), which is what lets a sibling `web` core service reach its
   /health one hop away."* The fan-out justification is retired; the field is not.
   Replace the trailing clause with the surviving reason: a `port` makes the worker
   addressable by a consumer holding a magic ref to its `host`/`port` parts — rule
   32's positive arm. Keep the `shape.md` citation.
4. **Update the file header comment** if it narrates health (it currently does not —
   check, do not assume).
5. **Leave `container_definition` in `emits.elastic`.** No shipped field routes to it
   any more; it stays as a declared available destination whose renderer emits
   nothing. Removing it is a capability deletion this mod was not asked for.

---

## Step 3 — `tables/roles/clock.yml`

Identical to Step 2 with two differences:

- `fields:` keeps `schedules:` (the empty per-foundation marker bodies). Only
  `health_check_path` is deleted.
- The `provides:` comment's fan-out clause is the "same as `worker`" sentence — reword
  to match Step 2's replacement while preserving the deliberate *"it gets NO
  exemptions"* point, which is about magic-ref resolution and is unaffected.

---

## Step 4 — `src/docex/emit/hcl.py` — the elastic read

**The one behavioral change in this mod.** In `render_task_definition`, immediately
**before** the line

```python
    container_def.update(svc.target_extras.get("container_definition", {}))
```

insert the block given verbatim in [`overview.md` § 2](./overview.md#2-the-elastic-delivery-path--the-one-real-mechanism-decision).
Copy the comment as written — it carries three things that will otherwise be
re-litigated: why the probe arrives in `body` at all, that `body` is **not**
generically consumed (`launch_type`/`network_mode` are inert), and why the position
ahead of the merge is load-bearing rather than arbitrary.

Do not add any other read of `body`. Do not touch
`render_migration_task_definitions`, `render_ecs_service`, or the sidecar literal.

---

## Step 5 — prose that outlived its model

Six sites. Each is a string or comment; **no logic moves at any of them.**

### 5a. `src/docex/cicl/magic_refs.py::self_uses_message`

The message currently ends *"…the core service would be its own contract provider,
and its health fan-out would proxy its own `/health` at `/health/<cb>/<svc>`."*

Keep the first clause. Replace the fan-out clause with the surviving absurdity: a
self-edge would also make the core service its own `uses` target, so rules 31 and 32
— which exist to assert that a target declares a surface and, when directly
addressed, a `port` — would be satisfied by the service against itself. Keep the
`See cicl.md § Uses Relationships.` trailer and the `_SELF_REF_RULE` interpolation
exactly as they are; the docstring's warning about co-location with
`self_reference_message` stays.

**Check for a test asserting the old substring** (`grep -rn "fan-out\|fanout" tests/`)
and update it to assert the new one.

### 5b. `src/docex/pipeline/release.py` — three sites, one theme

| Line | Current | Becomes |
| --- | --- | --- |
| ~454 (comment) | `# Hard failure: the health fan-out is doctrine-mandated, and an env whose consumers cannot reach their targets is not released.` | the reconcile is mandated because a consumer that cannot resolve a name it `uses` is broken; keep the second clause verbatim |
| ~461 (stderr) | `…the /health/<codebase>/<service> fan-out will return 503.` | `…and NOTHING EXTERNAL WILL SHOW IT: both services report healthy, the release looks clean, and the work silently does not arrive.` |
| ~479 (stdout warning) | `…the /health/<codebase>/<service> fan-out may return 503 until they do.` | the same symptom in the transient voice — consumers may fail to resolve their targets until they converge, with no external signal |

Keep both messages' actionable trailers (`Re-run 'docex release {env}', or redeploy it
by hand.`) and the exit codes. **The reconcile logic does not move** — no change to
`ecs_force_new_deployment`, the pair computation, `_RECONCILE_STABLE_TIMEOUT_S`, or
the warning-vs-failure split.

`grep -rn "503" tests/` and update any test asserting the old wording.

### 5c. `src/docex/cicl/validate.py` (~line 511)

Comment reads `…declares 'uses: [api.worker]' for the contract and the health fan-out
while holding no ref to the worker…`. Drop `and the health fan-out`. Nothing else in
that comment block changes — the one-directionality argument it makes is still exactly
right.

### 5d. `src/docex/emit/compose.py` — the exec block's `# Deliberately unset:` list

That comment enumerates `container_name`, `logging`, `command`, `restart`. Add
`healthcheck` with its reason, citing
`doctrine/infrastructure/specifics/exec_service.md` and `healthchecks.md`: the exec
container is a one-off that runs a script and exits, its liveness question is answered
by the exit code it was invoked for, and a `healthcheck:` here would additionally
change what `depends_on: service_healthy` means for anything gating on it. State that
the block is built key-by-key and inherits nothing from `svc.body` — that is *why* it
is safe, and the comment is what keeps it safe.

---

## Step 6 — flip the three `MOD 127:` tags

`grep -rn "MOD 127:" src/ tests/` finds exactly three. **All three must be gone.**
(Hits under `plans/modifications/125_*` and `126_*` are historical records of prior
mods, not code — leave them.)

### 6a. `tests/unit/test_worker_role.py::test_worker_fixed_compose_healthcheck`

Delete the `# MOD 127:` block and the interim docstring. Assert the real emission:

```python
    hc = doc["services"]["sample-dev-api-worker"]["healthcheck"]
    assert hc["test"] == ["CMD", "./health.sh", "worker"]
    assert hc["interval"] == "30s"
    assert hc["timeout"] == "5s"
    assert hc["retries"] == 3
```

Keep the existing image/command assertions. New docstring: the probe is a role-table
default, so a worker gets one **without declaring any field at all** — which is the
whole point of the move, and the reason the assertion is on the literal rather than on
presence.

### 6b. `tests/unit/test_worker_role.py::test_worker_elastic_container_healthcheck`

Same treatment against `_container_block(hcl, "api-worker", "api-worker")`. Assert
`command == ["CMD", "./health.sh", "worker"]` plus interval/timeout/retries/startPeriod.
Note in the docstring that this arrives via the `task_definition` default target and an
explicit read in `render_task_definition`, **not** via `container_definition` — with a
pointer to `overview.md § 2`. A reader who assumes the merge target will look in the
wrong place when this breaks.

### 6c. `tests/unit/test_clock.py::test_fixed_clock_is_an_ordinary_compose_service`

Replace `assert "healthcheck" not in block` with the `["CMD", "./health.sh", "clock"]`
assertion. Keep every other assertion in that test untouched.

### 6d. Module docstrings

`test_worker_role.py`'s module docstring closes with *"…the two probe-emit tests below
assert its ABSENCE until mod 127 moves the probe into the role tables' `defaults`."*
Rewrite that paragraph: the worker declares no `health_check_path` (rule 33 forbids
it) and still gets a probe, because the probe is a default. Also fix the opening line
— it describes the file as covering *"the `container_definition` destination (mod
095)"*, which is now only true of `test_container_definition_emits_no_resource`.

---

## Step 7 — the derivative pins (§ 3 and § 4 of the overview)

These are the mod's most important tests. **Every one needs a positive control in the
same document**, or it passes vacuously against a change that emits no probes at all.

### 7a. Narrow `tests/unit/test_hcl_sidecar.py::test_sidecar_has_no_healthcheck`

It currently asserts `"healthCheck" not in api_td` over the **whole `api-web` task
definition**. That was equivalent to "not on the sidecar" only while no core container
had a probe. Narrow it to the sidecar container block (use `_container_block`, as
`test_worker_role` does, or slice the sidecar out of `api_td`), and **add the positive
control**: the `api-web` app container *does* carry a `healthCheck` whose command is
`["CMD", "./health.sh", "web"]`. Keep the `wget` assertion — it is about mod 024's
retired probe and is still meaningful, but scope it to the sidecar too.

### 7b. `tests/unit/test_compose_sidecar.py::test_sidecar_has_no_healthcheck`

Add the same positive control: in the same compose document, `sample-dev-api-web`
carries the probe and `sample-dev-api-web-otelcol` does not. State mod 024's reason in
the docstring — the collector image is `FROM scratch` and carries no probe tool, so a
probe there would leave compose reporting `health: starting` forever
(`telemetry_infra.md`).

### 7c. NEW — the fixed `-exec` block carries no `healthcheck:`

In `tests/unit/test_compose_emitter.py`. Assert that every `*-exec` block has no
`healthcheck` key, **and** that every core-service block in the same document does.
Docstring cites `exec_service.md`: *"`health.sh` is the one codebase shim that does not
run here… its own liveness question is answered by the exit code it was invoked for"*,
and names the second consequence — an exec block with a healthcheck changes what
`depends_on: service_healthy` means for anything gating on it.

Record in the test that this passes **by construction**, not by a filter: the exec
block is built as a fresh dict and reads exactly one key off a core service
(`head.body.get("image")`). The test exists to keep that true, not to have made it
true.

### 7d. NEW — the elastic `_migrate` task definition carries no `healthCheck`

In `tests/unit/test_hcl_sidecar.py` (beside the existing `_migrate` coverage) or
`test_worker_role.py` — wherever the `_migrate` slice helper already lives. Same
positive control against the app container. Same "by construction" note.

### 7e. NEW — the `depends_on` predicate did not leak

In `tests/unit/test_compose_emitter.py`, beside the two existing exec-gate tests.
Assert: for every `*-exec` block's `depends_on`, **no key names a core service**, in a
document where every core service demonstrably carries a `healthcheck:`.

`emit/compose.py:606` resolves `service_healthy` vs `service_started` by asking whether
a target block contains a `healthcheck:`, and it reads **backing** blocks only
(`exec_deps = uses_backing`, a partition derived from `"." in entry`). "Every core
service now has a healthcheck" is exactly the kind of change that leaks into a
predicate written when only some did — this test is what makes the non-leak
load-bearing.

The existing `test_exec_gate_is_service_healthy_and_no_other_block_is_gated` and
`test_exec_gate_is_service_started_when_target_has_no_healthcheck` must both still pass
**unchanged**. If either needs editing, the predicate leaked — **stop and report
rather than adjusting the test.**

---

## Step 8 — new emission coverage

All in existing files where the fixture is already set up.

1. **`web` fixed probe** — `sample-dev-api-web` carries `["CMD", "./health.sh", "web"]`
   with the full cadence.
2. **`web` elastic probe** — the `api-web` app container's `healthCheck.command` is the
   same, with `startPeriod: 10`.
3. **The probe does not follow `health_check_path`** — copy the fixture, set
   `health_check_path: /healthz` in its `infra.yml`, compile, and assert the fixed
   probe is *still* `./health.sh web` **and that the string `curl` appears nowhere in
   the compose document**. This is the assertion that catches a half-done table edit
   that left the field's fixed translation in place, which no other test here would.
4. **The ALB check survives** — with `health_check_path: /healthz`, the elastic
   `aws_lb_target_group.api-web` block's `health_check` still carries
   `path = "/healthz"`. Narrowing the field must not silently drop its one real
   consumer.
5. **`health_check_path` on a `worker` and on a `clock` is rejected** — compile a
   document declaring it and assert `tt_rule_4_undeclared_field` is **among** the
   reported rule ids. Membership, not exclusivity: rule 33 also fires, and asserting a
   single id would make the test brittle against the aggregation the validator is
   built on.
6. **Backing services get no `health.sh` probe** — `sample-dev-appdb`'s fixed
   healthcheck is still the postgres engine's own, and no backing block on either
   foundation carries `./health.sh`.
7. **The `${service}`-is-`None` hazard fails loudly** — a project-local transfer table
   that puts `${service}` in a **backing** engine's `defaults.fixed` raises
   `SubstitutionError` at compile, quoting the template, rather than emitting the
   string `"None"`. `test_compose_emitter.py` already has a project-local-table
   fixture pattern (`test_exec_gate_is_service_started_when_target_has_no_healthcheck`)
   to copy. Docstring: this cannot bite the three core roles, which are core-only —
   the test pins the *failure mode* for the future table author who tries it, because
   "cannot happen" and "fails safe" are different claims and only the second survives.

---

## Step 9 — verification

Run in this order and **record the actual numbers**, not expected ones.

1. **Red before green.** For each of Step 7c/7d/7e and Step 8's items 1–7, observe the
   new test failing against the pre-change code (or, where the test is only meaningful
   post-change, observe the *positive control* failing before the table edit lands).
   Advance 005's standing rule. Note each observation in the report.
2. `python3 -m pytest tests/unit -q` — **must be ≥ 1041 passed, zero failed.** The
   count rises by the number of tests added.
3. `python3 -m pytest tests -m integration -q` — **re-derive the number; do not
   inherit one.** Report what you measure. If a member is red, determine whether this
   change caused it before assuming it did.
4. `grep -rn "MOD 127:" src/ tests/` → **zero hits.** Completion criterion.
5. `grep -rn "fan-out\|fanout\|/health/" src/docex/` → zero hits outside
   `docex.egg-info/` (a build artifact — ignore it).
6. `python3 -m pytest tests/unit/test_worker_role.py tests/unit/test_clock.py
   tests/unit/test_compose_emitter.py tests/unit/test_hcl_sidecar.py
   tests/unit/test_compose_sidecar.py -q` — the churn set, green.

**Expected red and NOT to be fixed here:** anything under `test_projects/`. Those seed
projects are already failing `docex check` for two reasons (no `health.sh`,
three-segment contract filenames) and this change adds a third — their checked-in
compiled output no longer matches a recompile. **All three are mods 129/130's.**

---

## Step 10 — what NOT to do

- Do not add `start_period` to the fixed probe. The asymmetry is deliberate and its
  mechanism is verified in `overview.md` Q2.
- Do not remove `container_definition` from `worker`/`clock`'s `emits.elastic`.
- Do not make `render_task_definition` merge `body` generically. That is the open
  question in
  [`advances/007_small_edges/inert_elastic_defaults.md`](../../advances/007_small_edges/inert_elastic_defaults.md)
  and it is explicitly not answered by this mod.
- Do not edit any file under `doctrine/`. Two `transfer_tables.md` defects are known
  and routed to sarge (`overview.md` § 8).
- Do not "fix" `launch_type`/`network_mode`. Same brief.
- Do not update `plans/core/*` — that is the mod cycle's documentation step, run by
  the corporal after review, and § *The contract and health gates* is mod 131's
  regardless.
