# Mod 100 — Replicas: implementation steps

Execute against `/home/ubuntu/.claude/jean_baudrillard/docex`. All paths below
are relative to that directory unless stated otherwise. Read
[`overview.md`](./overview.md) first — it carries the *why* for every step here
and settles two questions you must not re-litigate.

**Run tests with `uv run pytest …`** (there is no bare `python` on this
machine).

Baseline, verified before you start: `uv run pytest tests/unit -q` → **902
passed**; `uv run pytest tests/ -q` → **966 passed, 17 deselected**;
`uv run pytest -m integration --collect-only -q` → **17 collected**. Those are
the bars. If you cannot clear them, stop and report — do not delete or skip a
test to get green.

**The tree is dirty on purpose.** There are ~10 `campaigns/` → `advances/`
renames staged in the index plus an unrelated modification to
`tests/unit/test_pipeline_projinfra.py`. **They are not yours.** Do not stage
them, do not revert them, do not `git add -A`. You are not asked to commit at
all — the C.O. commits after review.

## The governing principle

> **A replica is an emission detail, not a topology node.**

`CompiledEnv.services` is the topology model — `describe`, the `check.py`
gates, `group_by_codebase`, `_named_volumes` and the network section all read
it. It must keep **exactly one entry per process type**. Nothing in this mod
adds a `CompiledService`. The multiplication happens in the compose emitter
only; on elastic the same declaration becomes a count on one resource.

If you find yourself adding entries to `compiled.services`, you have taken a
wrong turn.

---

## Step 1 — `effective_replicas` in `cicl/compile.py`

Add a module-level function immediately **after** `group_by_codebase`
(which ends at `compile.py:581`, `return {cb: groups[cb] for cb in sorted(groups)}`)
and before `def compile_env(`.

```python
def effective_replicas(svc: CompiledService, env: str) -> int:
    """The number of instances of ``svc`` to emit in ``env``.

    The declared ``replicas`` count applies in ``prod`` only, per
    ``shape.md``'s Runtime Shape paragraphs: "`prod` environments may also
    have multiple core service containers running in parallel." Every other
    env runs exactly one of everything.

    WHY a function and not a pre-clamped field on ``CompiledService``: the
    clamp needs the env, and storing the clamped value would erase the
    distinction between *declared* and *effective*, which the rule-5 collision
    check reads (it seeds replica suffixes off the declaration, before any env
    exists). Both emitters call this so the prod-only rule is stated once.
    """
    if not svc.is_core or env != "prod":
        return 1
    return max(1, svc.replicas)
```

Notes for the implementer:

- `svc.replicas` is already on `CompiledService` (`compile.py:520`) and is
  already `1` for every backing service (`compile.py:985` sets
  `replicas=(svc.replicas if is_core else 1)`). The `is_core` guard is belt and
  braces, not load-bearing.
- Update the stale comment at `compile.py:518-519` — it currently reads
  *"Carried only — NOTHING is emitted from it in this mod. Fixed unroll and
  elastic desired_count are Mod 100."* Replace with a short note that the
  declared value is read by `effective_replicas` and consumed by the compose
  unroll and the ECS `desired_count`. Do the same for the matching comment on
  `model.py:133-134`.

---

## Step 2 — Elastic: `desired_count` in `emit/hcl.py`

`hcl.py:678`, inside `render_ecs_service`:

```python
    out.append( '  desired_count   = 1')
```

becomes

```python
    # Mod 100: `replicas`, clamped to 1 outside prod. No deployment_
    # configuration block is emitted, so ECS's defaults
    # (minimum_healthy_percent = 100, maximum_percent = 200) apply — correct
    # for a static count. Sidecars need no thought: the collector is a
    # container INSIDE the task definition, so N tasks give N sidecars.
    out.append(f'  desired_count   = {effective_replicas(svc, ctx.env)}')
```

Extend the existing import at `hcl.py:38`:

```python
from docex.cicl.compile import (
    CompiledEnv, CompiledService, effective_replicas, group_by_codebase,
)
```

**Preserve the exact spacing** of the emitted line (`desired_count   = `, three
spaces, aligning with `task_definition` and `launch_type` above it) so a
1-replica project's `main.tf` is byte-identical to today.

That is the entire elastic change. Do **not** add a `deployment_configuration`
block, do not touch the target group, and do not unroll anything on elastic —
one `aws_ecs_service` and one `aws_ecs_task_definition` per process type, as
today.

---

## Step 3 — Fixed: the unroll in `emit/compose.py`

Three edits inside `emit_compose`, plus one helper.

### 3a. The helper

Add near `_sidecar_block` (after it is fine):

```python
def _replica_networks(svc: CompiledService) -> dict[str, Any]:
    """Convert compose short-form ``networks: [a, b]`` to map form with a
    shared alias, so all N replicas answer to the unqualified name.

    This is what keeps ``provides.host`` — ``${global_service_name}`` on the
    fixed side — working after the unroll: no container is named
    ``{global_name}`` any more, so the name is carried by an alias that
    Docker's embedded DNS resolves to all N containers, round-robin.

    The alias goes on EVERY network the process type joins. A consumer
    resolves the target over whichever network the two share, so restricting
    the alias to non-``web`` networks would break a web→web reference for no
    gain.

    Called only on the unroll path (N > 1). The N == 1 path keeps the
    short-form list byte-for-byte — there is no `aliases` handling anywhere
    else in this emitter and none is added.
    """
    return {n: {"aliases": [svc.global_name]} for n in svc.networks}
```

`import copy` at the top of the module (there is no `copy` import today).

### 3b. The per-service loop

At the end of the first loop, `compose.py:566`:

```python
        services[svc.global_name] = block
```

becomes:

```python
        # Mod 100: the replica unroll. `deploy.replicas` CANNOT work here —
        # the collector sidecar pairs via `network_mode: "service:<svc>"` to
        # share the app container's netns, and Compose has no
        # replica-to-replica pairing semantics, so one sidecar cannot pair
        # with N replicas. `deploy.replicas` also forces dropping
        # `container_name` (Compose refuses both together), costing the
        # container-name DNS entry and the readable names operators debug
        # with. So the compiler emits N DISTINCT compose services instead.
        #
        # WHY the traefik labels above are left exactly as they are: they key
        # on the UNQUALIFIED `svc.global_name`, so N containers declare one
        # router and one service and traefik's docker provider loads them as
        # N servers. Qualifying them per replica would produce N routers
        # fighting over one Host() rule. This is a constraint, not an
        # accident — see `tests/unit/test_replicas.py`.
        count = effective_replicas(svc, compiled.env)
        if count == 1:
            services[svc.global_name] = block
        else:
            for i in range(1, count + 1):
                replica_key = f"{svc.global_name}-{i}"
                replica = copy.deepcopy(block)
                replica["container_name"] = replica_key
                replica["networks"] = _replica_networks(svc)
                services[replica_key] = replica
```

`_LoggingAnchor` instances survive `deepcopy` fine (it is an empty marker
class), but confirm the emitted YAML still renders `*default-logging` on every
replica — the string replacement in `emit_compose` is global, so it will.

### 3c. The sidecar loop

`compose.py:574-594` pairs one sidecar per compiled core non-scheduler service.
It must now pair one per **emitted replica**. Replace the body of that loop's
tail so that, in place of the single:

```python
        sidecar_name = (
            f"{compiled.project_dns_label}-{compiled.env}-{svc.name}-otelcol"
        )
        services[sidecar_name] = _sidecar_block(...)
```

you emit one sidecar per replica. `_sidecar_block` currently derives both its
`container_name` and its `network_mode` internally from
`project_dns_label`/`env`/`svc.name` and `svc.global_name` respectively. Give
it an optional parameter carrying the **container key it is pairing with**, and
derive both names from that:

```python
def _sidecar_block(
    svc: CompiledService, project_dns_label: str, env: str,
    observability_backend_url: str, *, paired_key: str | None = None,
) -> dict[str, Any]:
    ...
    # Mod 100: `paired_key` is the compose key of the container this sidecar
    # shares a netns with — `{global_name}-{i}` on the replica unroll,
    # `{global_name}` otherwise. The sidecar's own name is that key plus
    # `-otelcol`, which keeps the suffix last and `docker logs
    # …-api-web-3-otelcol` readable.
    target = paired_key or svc.global_name
    sidecar_name = f"{target}-otelcol"
    return {
        ...
        "container_name": sidecar_name,
        "network_mode": f"service:{target}",
        ...
    }
```

and the caller:

```python
        count = effective_replicas(svc, compiled.env)
        if count == 1:
            keys = [svc.global_name]
        else:
            keys = [f"{svc.global_name}-{i}" for i in range(1, count + 1)]
        for target in keys:
            services[f"{target}-otelcol"] = _sidecar_block(
                svc, compiled.project_dns_label, compiled.env,
                compiled.observability_backend_url, paired_key=target,
            )
```

**Byte-identity hazard, read carefully.** Today the sidecar's compose key and
`container_name` are built from
`f"{project_dns_label}-{env}-{svc.name}-otelcol"`, while its `network_mode`
uses `svc.global_name`. The refactor above derives *both* from
`svc.global_name`. For every naming policy in the tree these are the same
string (the `ecs` policy is `separator: hyphen, max_len: 255`, and
`_global_service_name` builds `{project}_{env}_{service}` before applying it),
which is why the N==1 output stays byte-identical — and test 6 will prove it.
Keep the two derivations unified rather than special-casing; unifying is the
point, since the sidecar name and the netns target must agree or the pairing
breaks.

Leave the `configs` gate (`compose.py:711-716`) alone: one `otelcol_config`
entry serves every sidecar, replicas included.

### 3d. What must NOT change

- The exec-service pass (`compose.py:607-659`) is **per codebase** and does not
  multiply. One `{codebase}-exec` in prod regardless of replica counts.
- The `depends_on` second pass (`compose.py:673-687`) iterates
  `services.values()`, so it already reaches the derived replica blocks and
  rewrites their short-form `depends_on` to `condition: service_healthy`
  without any edit. Verify, do not modify.
- `_named_volumes`, `_network_section`, the ofelia pass, and the header are
  untouched.
- `_traefik_labels` is untouched.

---

## Step 4 — Rule 5's uniqueness domain, in `cicl/validate.py`

In `_validate_rendered_identity` (`validate.py:778-852`), inside the existing
`for svc_name, proc_name, _svc, proc in doc.all_processes():` loop, after the
`-otelcol` / `-scheduler` seeding, add:

```python
        # Mod 100: the replica index. On fixed-prod the compiler unrolls a
        # process type with `replicas: N` into N compose services keyed
        # `{compiled}-{i}`, so `api` with process types `web` (replicas: 3)
        # and `web-1` renders `api-web-1` twice — one container silently
        # clobbering the other, in prod-fixed only, which is the worst place
        # to discover it.
        #
        # Gated on `replicas > 1` because with a count of 1 the suffix is
        # never emitted by anything, and rule 5 does not forbid a name that
        # collides with nothing. Unlike `-migrate` (seeded unconditionally
        # because whether it exists depends on a DIFFERENT service's
        # `schema_owned_by` — action at a distance), bumping `replicas` is an
        # edit on this very process type, so the error surfaces in the
        # reader's hand at the moment they create the collision.
        #
        # Seeding the container identity alone is sufficient: a sidecar
        # collision needs `{P}-otelcol == {Q}-{i}-otelcol`, i.e. `P == Q-i`,
        # which is exactly the container-level collision seeded here. Do not
        # "complete" this by also seeding `{compiled}-{i}-otelcol`.
        if proc.replicas > 1:
            for i in range(1, proc.replicas + 1):
                buckets.setdefault(
                    _normalized_identity(f"{ref.compiled}-{i}"), []
                ).append(
                    f"replica {i} of core process type {ref.dotted!r}"
                )
```

Then extend the issue message's derivative enumeration (`validate.py:843-848`)
so the error text and the doctrine say the same thing — it currently reads
`"(-otelcol, -scheduler, -exec, -migrate)"`. Make it
`"(-otelcol, -scheduler, -exec, -migrate, and the -1..-N replica index)"`.
Keep the rest of the message identical.

The function is document-level and foundation-agnostic; that is deliberate and
matches every other seed in it. An elastic-only project gets the check too.

---

## Step 5 — The one doctrine edit: `cicl.md` rule 5

**This is the only doctrine file this mod touches, and rule 5 is the only thing
in it that changes.** Approved by the C.O. as Option A, on the Mod 095 (rule 28)
and Mod 099 (rule 5's first widening) precedent that `cicl.md` has no downstream
owner in this advance — Mod 106's file list excludes it.

File: `/home/ubuntu/.claude/jean_baudrillard/doctrine/infrastructure/cicl.md`,
line 569. The clause listing the compiler's derivatives currently reads:

> — `-otelcol` (the paired collector sidecar), `-scheduler` (the Ofelia
> trigger), `-exec` (the per-codebase operations container), and `-migrate`
> (the migration task definition) —

Add the replica index to that list, e.g.:

> …, `-migrate` (the migration task definition), and `-1`…`-N` (the replica
> index, on a process type declaring `replicas: N`) —

and, in the same rule, extend the worked example sentence with the replica case
so a reader meets it concretely: a core service `api` declaring process types
`web` with `replicas: 3` and `web-1` is an error, because replica 1 of `web`
renders `api-web-1`, byte-identical to the `web-1` process type's own compiled
identity.

Keep the rule's closing sentence about being *keyed on collision, not on a list
of forbidden names* exactly as it is — that sentence is the reason the
validator change is authorized in the first place. Match the surrounding prose
style; do not restructure the rule or touch any other rule.

**Nothing else in any doctrine file.** In particular `shape.md`'s Runtime Shape
paragraphs contain a factual error (they claim the reverse proxy load-balances
replicas and illustrate it with *workers* — wrong; the proxy balances `web`
replicas, while internal replicas are balanced by Docker DNS on fixed and
Service Connect on elastic, with no proxy involved). **That fix is Mod 106's.
Do not edit `shape.md`. Do not build to its wrong claim either.**

---

## Step 6 — Tests

New file `tests/unit/test_replicas.py`. Model its fixture harness on
`tests/unit/test_process_expansion_emit.py` (copy fixture → patch `infra.yml`
→ `run_compile` → read `infra/output/<env>/…`), including its `_compose`,
`_hcl`, `_resources` and `_slice` helpers where useful.

The fixture: the three-process project from `test_process_expansion_emit.py`
(`api` with `web` / `worker` / `nightly_cleanup`), with `replicas: 4` on
`api.worker` and `replicas: 2` on `api.web`. Build a **second** compile of the
identical project with no `replicas` key at all — test 6 diffs the two.

Fixed foundation → `tests/fixtures/sample_project`; elastic →
`tests/fixtures/sample_project_elastic` (whose `dev`/`test` are still fixed;
only `stage`/`prod` emit HCL).

### Fixed emission

1. `prod` compose contains `sample-prod-api-worker-1` … `-4` and **no** bare
   `sample-prod-api-worker` key.
2. Each replica's `container_name` equals its compose key.
3. Each replica's `networks` is **map** form, and every network it joins
   carries `aliases: ["sample-prod-api-worker"]`. Assert on the worker
   (`[internal]`) and on the web process (`[web, internal]`) so the
   "alias on every network" rule is pinned on a multi-network service.
4. Four sidecars `sample-prod-api-worker-{i}-otelcol`, each with
   `network_mode: "service:sample-prod-api-worker-{i}"`; the app containers'
   `OTEL_EXPORTER_OTLP_ENDPOINT` is unchanged (still the loopback value) and
   identical across replicas.
5. Across the two `web` replicas: exactly **one** distinct traefik router key
   and **one** distinct traefik service key in the emitted labels, both the
   unqualified `sample-prod-api-web`; and the full `labels` list is identical
   between the two replicas. (Parse the `traefik.http.routers.<key>.` /
   `traefik.http.services.<key>.` segment out of the label strings.)
6. **The byte-identity guard.** `dev`, `test` and `stage`
   `docker-compose.yml` are byte-identical between the replicas compile and
   the no-replicas compile. Compare `read_text()`, not parsed YAML — the point
   is that nothing about ordering, spacing or key set moved.
7. `prod`'s top-level `networks:` and `volumes:` sections are identical between
   the two compiles (the `_named_volumes` guard: the unroll introduces no
   volume, so the top-level declaration must not move).
8. No `ports` key on any replica block.
9. Each replica's `depends_on` is the long-form
   `{"sample-prod-appdb": {"condition": "service_healthy"}}` — the second pass
   reaches derived services.
10. Exactly one `sample-prod-api-exec` key in `prod`; the exec service does not
    multiply.

### Elastic

11. In `prod` `main.tf`, `aws_ecs_service."api-worker"` carries
    `desired_count   = 4` and `aws_ecs_service."api-web"` carries `= 2`; there
    is still exactly one `aws_ecs_service` and one `aws_ecs_task_definition`
    per process type.
12. The same declarations in `stage` `main.tf` carry `desired_count   = 1`.
13. The no-replicas elastic compile emits the literal line
    `  desired_count   = 1` — exact three-space spacing — for **every**
    `aws_ecs_service` in both `stage` and `prod`, so the pre-mod line survives
    verbatim for a project that declares nothing. (The replicas compile's
    `prod` output differs from it by design, so do not diff the two files;
    assert the literal.)

### Clamp helper

14. `effective_replicas` directly: returns `N` for a core service in `prod`;
    `1` in `dev`, `test`, `stage`; `1` for a backing service even in `prod`.
    Construct `CompiledService` instances by hand or pull them off a compiled
    env — either is fine.

### Rule 5

15. A project whose `api` declares `web` with `replicas: 3` **and** a process
    type `web-1` is rejected with `rule_5_rendered_identity_collision`, and the
    message mentions the replica (e.g. contains `replica 1`), not only the two
    process types. Follow `tests/unit/test_process_nesting.py`'s existing
    `_issues(src)` pattern for driving the validator off a source string.
16. The identical project with `replicas: 1` on `web` produces **no** rule 5
    issue — the seeding is not over-eager.

---

## Step 7 — Verify

```
uv run pytest tests/unit -q          # expect >= 902 + your new tests
uv run pytest tests/ -q              # expect >= 966 + your new tests, 17 deselected
uv run pytest -m integration --collect-only -q   # must still collect exactly 17
```

Then confirm all four fixtures and both `test_projects` still compile — the
existing suite covers this, but if anything in `tests/integration/test_compile.py`
goes red, that is a real regression in the N==1 path and not a test to adjust.

## Do not

- Add entries to `compiled.services`, or otherwise unroll in `cicl/compile.py`.
- Emit a `deployment_configuration` block on elastic.
- Unroll anything on elastic.
- Touch `describe/`, `pipeline/check.py`, `orchestrate/`, `emit/ansible.py`,
  the ofelia pass, or any version artifact (`CHANGELOG.md`, `VERSION`,
  `pyproject.toml`, `__init__.py`) — the changelog for this whole advance is
  deliberately deferred to Mod 107.
- Touch any doctrine file other than the rule 5 clause in `cicl.md`.
- Touch `docex/plans/core/*` — the C.O. updates core planning docs after review.
- Stage or revert the pre-existing dirty tree.
- Delete or `skip` a failing test. If you cannot reach the bars, stop and
  report what failed and why.

## Contracts

No core-service contract changes. `replicas` is invisible at every service
boundary: it changes how many instances answer a name, never the name, the
port, the health path, or the message schema. `infra/contracts/*` is untouched.
