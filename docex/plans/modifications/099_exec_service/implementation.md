# Mod 099 — Implementation

Execute against `/home/ubuntu/.claude/jean_baudrillard/docex`. Read
[`overview.md`](./overview.md) first — it carries the *why* for every decision
below and settles two questions you must not re-open (migration sizing is the
per-dimension max; rule 5's domain grows rather than rule 14's list).

**Staged in two passes. Both must end green.** Pass 1 leaves `primary_process`
standing with two remaining consumers; that is intentional, not an oversight.
Pass 2 removes them and deletes it.

Baseline: `pytest tests/unit` → **869 passed**. `pytest tests/` → **933 passed,
17 deselected**. `pytest -m integration --collect-only` → **17 collected**. The
bar is 869+ and 17 integration tests still collecting.

**Do not touch any doctrine file.** `cicl.md` rule 5 was already edited as part
of this mod's design step; nothing else under `doctrine/` moves.

**Commit discipline:** the working tree has a large pre-existing dirty set
(`campaigns/` → `advances/` renames staged in the index, plus unrelated files).
Never `git add -A` or `git commit -a`. Always use an explicit pathspec listing
only the files you changed.

---

## Pass 1 — compiler, validator, emitters

### 1.1 `src/docex/cicl/compile.py`

**(a) Export a public codebase-name derivation.** `_global_service_name`
(`:286-301`) already supports the codebase form via `process=None`. Add a public
wrapper immediately after it so `orchestrate/` can share the derivation instead
of growing a third copy:

```python
def codebase_global_name(
    project: str, env: str, codebase: str, policy: NamingPolicy
) -> str:
    """The codebase-keyed global name, ``{project}-{env}-{codebase}``.

    Public because two identities outside the compiler derive from it and must
    match it byte-for-byte: the per-codebase exec service's compose key
    (``…-exec``, resolved by ``orchestrate/_common.py::exec_service_key``) and
    the elastic migration task-definition family (``…-migrate``, reconstructed
    by ``orchestrate/migrate.py::_migration_task_family``). Mod 099.
    """
    return _global_service_name(project, env, codebase, policy)
```

**(b) Add the codebase grouping helper.** Place next to `CompiledEnv`. All three
emitters use it, so the grouping rule exists exactly once:

```python
def group_by_codebase(
    compiled: "CompiledEnv",
) -> dict[str, list[CompiledService]]:
    """Core compiled services grouped by codebase, both levels sorted.

    The per-codebase emissions — the exec service (compose), the migration task
    definition (HCL), the playbook's migrate task (ansible) — all iterate this
    rather than picking a representative process type. Mod 099 deleted the
    "pick one" rule (``primary_process``); this is what replaced it.
    """
```

Include every core `CompiledService`, **including `scheduler` process types** —
a scheduler-only codebase must still get an exec service. Exclude backing
services.

**(c) Retire the carrier flag.** At `:918-922`, `schema_owned_by_db` is set only
on `primary_process(core_svc)`. Change the condition to
`is_core and svc_name in core_owning_schema` — drop the `proc_name ==
primary_process(...)` clause and the `primary_process` import at `:34`.

Rewrite the comment. The field now means *"this compiled service's codebase owns
a backing DB schema"* — an honest codebase property, true of every process type
of that codebase. Explicitly note that the "exactly one carrier" invariant it
used to encode is now provided structurally by `group_by_codebase`, so nothing
downstream may reintroduce a "pick one" read of this flag.

### 1.2 `src/docex/cicl/validate.py` — rule 5 derivatives

Extend `_validate_rendered_identity` (`:778-816`). It is already bucket-shaped,
so this is purely additive. After the existing two loops, seed the buckets with
the derivatives the compiler appends:

- per process type: `{ref.compiled}-otelcol` when `role != "scheduler"`, else
  `{ref.compiled}-scheduler`
- per codebase (once, from `doc.core_services`): `{codebase}-exec` and
  `{codebase}-migrate`

Label them distinctly, e.g. `"the collector sidecar for core process type
'api.web'"`, `"the exec container for codebase 'api'"`. The point of the label
is that the error names a *derivative* rather than a service the author never
wrote — otherwise the message is baffling.

Update the docstring and the message text to match `cicl.md` rule 5 as it now
reads (already edited): the domain is core process types, backing services, and
compiler-emitted derivatives; the rule is keyed on collision, not on a reserved
name list.

Do **not** grow rule 14's reserved-name list. That was considered and rejected.

**Pre-verified:** all four fixtures and both `test_projects` are collision-free
under the extended rule (see `overview.md § Decisions taken`). If a fixture you
add for another purpose collides, rename *your fixture*.

### 1.3 `src/docex/emit/compose.py` — the exec service

Add a per-codebase pass after the sidecar loop and **before** the `depends_on`
second pass (`:570` region), so the exec service's `depends_on` gets rewritten
to long-form by the existing machinery rather than a duplicate of it.

For each `(codebase, procs)` from `group_by_codebase(compiled)`, build one block
and register it under key `f"{procs[0].codebase_global_name}-exec"`:

| Key | Value |
| --- | ----- |
| `profiles` | `["exec"]` — always. First `profiles:` key in the codebase. |
| `image` | `procs[0].body["image"]` — codebase-keyed, so identical across process types. |
| `build` | `{"context": f"./core/{codebase}", "dockerfile": "Dockerfile", "target": compiled.env}` — **only** when `compiled.env in ("dev", "test")`. Must be byte-identical to the app services' block so Docker's cache makes the image free. |
| `environment` | `_translate_tree(procs[0].service_env)` when non-empty — **service-level env only**. Never `svc.env`. |
| `volumes` | `[f"./core/{codebase}/src:/service/src", f"./core/{codebase}/dist:/service/dist"]` — **only** when `compiled.env == "dev"`, mirroring the app-service rule. |
| `networks` | sorted union over `procs` of `[n for n in p.networks if n != "web"]`; **omit the key entirely** when empty. |
| `depends_on` | sorted union over `procs` of `p.depends_on`, as a **list** (short form); omit when empty. The second pass converts it. |
| `labels` | `[_docex_project_label(compiled.project_dns_label)]` |

Do **not** set `container_name` (`compose run` generates its own; a fixed name
would collide or be ignored), `logging` (the container is `--rm`), `command`
(supplied at the call site), or `restart`.

`service_env` is identical across a codebase's process types by construction, so
reading it off `procs[0]` is safe — add a `WHY` comment saying so.

Write a module-level docstring paragraph or a block comment on the pass covering:
the exec service is the per-codebase operations container; `profiles: [exec]`
keeps `up` from starting it while `compose run` implicitly enables it; it carries
service-level `env:` only, which is what makes *`migrate.sh`, `test.sh`, and
`build.sh` may depend only on codebase-scoped env* an enforceable rule rather
than a convention.

### 1.4 `src/docex/emit/hcl.py` — hoist the migration task definition

**(a) Remove** the `if svc.is_core and svc.schema_owned_by_db:` block from
`render_task_definition` (`:519-580`, through the closing `out.append("}")` of
the migrate resource). `render_task_definition` goes back to rendering exactly
one task definition.

**(b) Add** `render_migration_task_definitions(compiled, ctx) -> str`, which
iterates `group_by_codebase(compiled)` and, for each codebase whose process
types carry `schema_owned_by_db`, emits one migrate task definition. Preserve
verbatim from the removed block:

- family `f"{procs[0].codebase_global_name}-migrate"`
- resource address `f'aws_ecs_task_definition."{codebase}_migrate"'` — **must**
  stay `{core_service}_migrate` so `migrate.py:351` and `release.py:401` keep
  matching. `release.py` therefore needs **no edit**.
- `image` from `procs[0].body["image"]` (codebase-keyed)
- container `name`, `logConfiguration(..., "migrate")`, `command:
  ["/service/migrate.sh"]`, `essential: True`
- env from `_container_env_entries(procs[0].service_env, ...)` — service-level
  only; Mod 096's proof that a process-level key is absent must still hold
- the `standard_tags(... descriptor="migrate-task-def" ...)` block

The container `name` and the log-configuration service segment previously used
the *carrier's* two-segment `svc.name` (e.g. `api-web`). Use the **codebase**
form (`procs[0].codebase_global_name`'s source codebase, i.e. `codebase`) —
these belong to a per-codebase artifact and a process segment in them is now a
lie. Note this in a `WHY` comment; it is a deliberate emitted-value change.

**(c) Resources — the per-dimension max.** Replace the carrier's `cpu`/`memory`:

```python
cpu = max(int(p.body.get("cpu", "256")) for p in procs)
memory = max(int(p.body.get("memory", "512")) for p in procs)
cpu, memory = fargate_pair_from_units(cpu, memory, service_name=..., where=...)
```

Take the maxima **per dimension**, never over pairs — `overview.md` proves the
result is always a valid Fargate tier and that the proof depends on this. The
`fargate_pair_from_units` round-trip is a no-op for valid input and exists to
turn that proof into an enforced guarantee; leave a comment saying exactly that
so nobody deletes it as redundant.

For a single-process codebase this is the pre-mod value, so existing HCL
snapshots must not move except for the container-name/log-segment change in (b).

**(d)** Wire it into `emit_hcl` (`:1225`) and `main.tf.j2`: render the string
once and pass it as e.g. `migrations_hcl`, emitted after the per-service loop.
Emit nothing (not even a blank section) when no codebase owns a schema.

### 1.5 `src/docex/emit/ansible.py` + `templates/playbook.yml.j2`

Replace the `schema_owned_by_db` filter at `:31-34` with `group_by_codebase`.
Build a list of small records, sorted by codebase:

```python
{"codebase": codebase, "exec_service": f"{procs[0].codebase_global_name}-exec"}
```

for each codebase whose process types carry `schema_owned_by_db`.

In `playbook.yml.j2:50-59`, change the loop to use these records:

```jinja
    - name: Run migrations for {{ svc.codebase }}
      ansible.builtin.command:
        cmd: docker compose -p {{ compose_project_name }} run --rm {{ svc.exec_service }} /service/migrate.sh
      ...
      register: {{ svc.codebase }}_migrate_result
```

`register:` must remain a valid Ansible identifier — the codebase key is an
`infra.yml` key so it already is.

Rewrite the `WHY` comment in `ansible.py`: fixed stage/prod migration now runs
in the **exec service**, so production migration reads codebase-scoped env only.
This is the half of justification #2 that a dev/test-only exec service would
have left open, and it is why the exec service is emitted in all four fixed envs.

### 1.6 Pass 1 tests

New `tests/unit/test_exec_service.py` (emission) plus additions to the existing
HCL/ansible/validate suites. Cover items **1-8, 15-18, 19-21** of
`overview.md § Test plan`:

1. One exec service per codebase, key `{project}-{env}-{cb}-exec`, for a
   multi-process codebase.
2. `profiles: ["exec"]`; no other emitted service `depends_on` it.
3. **Plant a process-level `env:` key** on one process type; assert it is
   present on that process's own block and **absent** from the exec block.
   Assert a service-level key *is* present on the exec block. This is the
   headline test — mirror the shape Mod 096 used for migrate.
4. `build.context`/`target` in `dev` and `test`; `image` present and `build`
   **absent** in `stage`/`prod`; `image` equals the app services' image in all
   four envs.
5. Bind mounts in `dev`, absent in `test`.
6. `networks` is the union of non-`web` nets and never contains `web`.
7. `depends_on` is long-form with `condition: service_healthy` on the codebase's
   backing services (relies on running *after* the existing second pass).
8. Scheduler-only codebase (use `sample_project_scheduler_fixed`): exec service
   emitted in `dev` **and** `test`, and in `test` it is the only compose service
   that codebase contributes. This is the seam Mod 103 depends on — say so in
   the test's docstring.

15. Exactly one `aws_ecs_task_definition."<cb>_migrate"` for a multi-process
    schema-owning codebase; family is `{codebase_global_name}-migrate`.
16. Resources are the per-dimension max; a single-process codebase's emitted
    resources are unchanged from pre-mod.
17. The migrate container's env is `service_env` — the planted process-level key
    is absent. Adapt Mod 096's existing assertion
    (`tests/unit/test_process_expansion_emit.py:280`) rather than deleting it.
18. Playbook emits one migrate task per schema-owning codebase, targeting the
    exec service key, not an app service key.

19. Rule 5 rejects a process named `exec`, `otelcol`, `scheduler`, or `migrate`
    where it collides with the corresponding derivative of its own codebase.
20. Rule 5 does **not** over-reject: codebase `api-exec` with process `x`
    renders `api-exec-x`, which does not collide with codebase `api`'s
    `api-exec`.
21. All four fixtures still compile.

Existing tests that will need updating (find them; the list is not exhaustive):
`tests/unit/test_emit_dispatch.py:142-149` and
`tests/unit/test_process_expansion_emit.py:280` both set or read
`schema_owned_by_db`; any test asserting the exact set of compose service keys
will now see one more per codebase.

**Run `pytest tests/unit` and `pytest tests/`. Both must be green before Pass 2
starts.** If a test fails because the exec service is legitimately new output,
update the expectation. If a test fails because behavior regressed, fix the
behavior — do not delete the test. If you believe a test must be deleted, stop
and report instead.

---

## Pass 2 — orchestrate, and the deletions

### 2.1 `src/docex/docker/subprocess_client.py`

Add `-T` to `compose_run_one_off` (`:177`): `+ ["run", "--rm", "-T"]`. `run`
allocates a TTY by default; `compose_exec` (`:198`) already passes `-T` for
exactly this reason and the asymmetry is a bug waiting to bite CI. Add the same
one-line `WHY` comment `compose_exec` carries.

Leave the rest of the method alone — in particular do **not** add `--no-deps`.
Dependency start-up with `condition: service_healthy` gating is the point.

### 2.2 `src/docex/orchestrate/_common.py`

**Delete** `compose_service_key` (`:165-210`) entirely.

**Add** `exec_service_key(ctx, env, codebase) -> str`, which **constructs then
verifies** — no suffix scan, no silent fallback:

1. Resolve the codebase's naming policy (helper below).
2. `key = codebase_global_name(ctx.project.name, env, codebase, policy) + "-exec"`
   using the function exported from `cicl/compile.py` in Pass 1.
3. If the compiled compose file exists and `key` is not among its `services:`,
   raise a clear error naming the codebase, the constructed key, **and the
   `-exec` keys that *are* present**, telling the operator to run
   `docex compile`. Listing the near misses is what turns a policy mismatch from
   a mystery into a diagnosis — do not skip it.

Add the private policy helper:

```python
def _codebase_naming_policy(ctx, codebase, *, foundation):
    """The naming policy for a codebase-keyed identity.

    A codebase-keyed name has no process type and therefore no single role to
    resolve an engine from. Every process type of the codebase must agree on
    the policy for the name to be well-defined, so we resolve all of them and
    require agreement rather than picking one — picking one is precisely the
    instability Mod 099 removed from migration sizing. All bundled core roles
    use `ecs`.
    """
```

Resolve each process type's `role` → `ctx.transfer_tables.role(role)` → the
first engine supporting `foundation` → `engine.naming`. If the resolved policy
names disagree, raise with both values named. Note in the docstring that this is
the same derivation `migrate.py::_migration_task_family` uses, which is why both
now call it.

### 2.3 `src/docex/orchestrate/migrate.py`

- Drop the `primary_process` import (`:22`) and the `compose_service_key` import.
- `_migration_task_family` (`:331-362`): replace the
  `core.processes[primary_process(core)]` policy resolution with
  `_codebase_naming_policy(..., foundation="elastic")`, and build the name with
  the exported `codebase_global_name` instead of the local `raw = f"..."` +
  `apply_policy`. Keep both existing best-effort fallbacks. Update the docstring
  — the `primary_process` explanation is now wrong.
- `:101-108`: `key = exec_service_key(ctx, env, svc)` and
  `docker.compose_run_one_off(compose_file, key, ["./migrate.sh"], ...)`.
  Update the module docstring's first line: dev/test migrate is now
  `docker compose run --rm` against the per-codebase exec service, not
  `compose exec` into a running container.

### 2.4 `src/docex/orchestrate/test.py`

- `:121-126` (migrate) and `:146-151` (`test.sh`): `exec_service_key` +
  `compose_run_one_off`.
- **Leave `_run_scheduler_tests` and the `svc in schedulers` branch at `:141-146`
  exactly as they are.** Deleting them is Mod 103's, and keeping the two diffs
  separable is deliberate. Add a one-line comment at the branch noting that Mod
  099's exec service now makes the carve-out unnecessary and Mod 103 removes it.
- Drop the `compose_service_key` import.

### 2.5 `src/docex/orchestrate/build.py`

- `:112`: `service_key = exec_service_key(ctx, _BUILD_ENV, svc)`.
- **Delete `:113-134`** — the `if service_key not in running:` gate, the
  `compose_ps_status` call, and the `restarting`/`unhealthy` diagnostic. See
  `overview.md § Deletions` for why mod 050 Gap D's intent is deliberately
  retired; carry a condensed version of that argument into a comment at the
  deletion site so a future reader finds reasoning rather than absence.
- **Keep** the whole-stack `if not running: raise EnvNotRunning` at `:69-72`.
- `:150-153`: `compose_run_one_off(compose_file, service_key, ["./build.sh"], ...)`.
- `running` is now used only by the whole-stack check; drop it from
  `_build_one`'s signature if it becomes unused.
- Update the module docstring's step 3 ("`compose exec` the service's
  `./build.sh`") to say `compose run --rm` against the exec service. Note that
  `cicd.md § Build Step` still says `exec` and is Mod 106's to fix.
- Drop the `compose_service_key` import.

### 2.6 `src/docex/orchestrate/up.py`

- `:238` post-up migrate loop: `exec_service_key` + `compose_run_one_off`.
- `_diagnose_unhealthy` (`:136-168`): **stop deriving keys.** Iterate
  `status.items()` and print a line for every entry whose state is in
  `_DIAGNOSTICS`, using the compose key as the name. Drop the
  `for svc in core_services(ctx)` loop and the `compose_service_key` call.
  Comment the improvement: the old form iterated core *codebases* only, so an
  unhealthy backing service — the likeliest reason `up` fails — was invisible to
  the very function that exists to diagnose `up` failures.
- Drop now-unused imports (`compose_service_key`, possibly `core_services`).

### 2.7 `src/docex/cicl/model.py`

**Delete `primary_process`** (`:214-242`). Verify zero remaining references
across `src/` and `tests/` before finishing.

### 2.8 Pass 2 tests

Cover items **9-14** and **22** of `overview.md § Test plan`:

9. **The wrong-container bug is gone.** Build a project with a codebase literally
   named `web` (process `web`) alongside `api` (process `web`). Assert
   `exec_service_key(ctx, "dev", "web")` is `{p}-dev-web-exec` and that nothing
   resolves to `{p}-dev-api-web`. Reference the live bug in the docstring — this
   test is the reason it can't come back.
10. `exec_service_key` raises (never returns a bare name) when the compose file
    lacks the key, and the message lists the `-exec` keys present.
11. `run_migrate` dev/test issues `compose_run_one_off(exec_key, ["./migrate.sh"])`
    and **zero** `compose_exec` calls.
12. `run_test` routes both `./migrate.sh` and `./test.sh` through the exec key.
13. `run_build` routes `./build.sh` through the exec key, still clears host
    `dist/` beforehand and still asserts it is non-empty afterward.
14. `run_up`'s post-up migrate goes through the exec key; `_diagnose_unhealthy`
    reports an unhealthy **backing** service (the case the old form missed).
22. `primary_process` and `compose_service_key` no longer exist — importing
    either raises `ImportError`.

The fake `DockerClient` in `tests/conftest.py:98-111` already records
`compose_run_one_off` calls keyed by `(name, file, service, command)`; use it
rather than adding a new fake.

---

## Finishing

1. `pytest tests/unit` — must be **869 or more**, all passing.
2. `pytest tests/` — must be green.
3. `pytest -m integration --collect-only` — must still collect **17**. This is
   the check that nothing you deleted broke integration-test collection; those
   tests cannot be run here.
4. `grep -rn "primary_process\|compose_service_key" src/ tests/` — must return
   nothing.
5. Report the exact numbers. **If the suite is not green, stop and report rather
   than deleting or skipping a test.**

Do not commit. The mod driver reviews the diff and commits.
