# Mod 087 — Implementation steps

All paths relative to `docex/` (the docex project root at
`~/.claude/jean_baudrillard/docex`).

## 1. Make the fixed project-tier Compose project name side-independent

File: `src/docex/pipeline/projinfra.py`

`_project_compose_project` currently takes `(ctx, side)` and returns
`f"{dns_label(ctx.project.name)}-projinfra-{side}"`. Change it to be
side-independent:

- Drop the `side` parameter entirely (it is no longer used).
- Return `f"{dns_label(ctx.project.name)}-projinfra"`.
- Rewrite the docstring: the name is deliberately **side-independent** so that on
  a single-machine fixed host `up development` and `up production` run under the
  same Compose project and the second `up` adopts (converges to a no-op), per
  `doctrine/.../projinfra/projinfra.md` §35/§96. Keep the note that an explicit
  `--project-name` (vs the path-derived `infra`) is what keeps `down` able to
  remove the traefik + four `-web` networks (mod 053's original fix).

Update the two call sites in the same file to call `_project_compose_project(ctx)`
(no `side` arg):
- `run_projinfra_fixed_up` (the `compose_up(... project_name=...)` call).
- `run_projinfra_fixed_down` (the `compose_down(... project_name=...)` call).

Fix the `run_projinfra_fixed_up` docstring: it currently says the second up "is a
docker-compose-up no-op because both emitted compose files declare the same
resource set." That is now TRUE (same resource set AND same Compose project
name). Keep/clarify the sentence so it reflects the shared-name mechanism.

## 2. Update unit tests

File: `tests/unit/test_pipeline_projinfra.py`

- `test_projinfra_fixed_up_runs_compose_up` (parametrized `side` in
  `["development", "production"]`): the assertion at the bottom currently expects
  `("compose_up_project_name", f"sample-projinfra-{side}")`. Change the expected
  value to the side-independent `"sample-projinfra"` (drop the `-{side}`), and
  update the mod-053 comment above it to explain the name is side-independent for
  single-host convergence (mod 087). The test stays parametrized over both sides
  — the point is now that BOTH sides yield the SAME project name.
- `test_projinfra_fixed_down_proceeds_when_env_clean`: the assertion currently
  expects `("compose_down_project_name", "sample-projinfra-production")`. Change
  to `"sample-projinfra"`. Update the adjacent comment likewise.

Add one focused regression test in the same file asserting the two sides collapse
to one name, e.g. `test_projinfra_fixed_compose_name_is_side_independent`:
run `run_compile(sample_ctx)`, then `run_projinfra_fixed_up` for `development`
and again for `production` on the same `fake_docker`, and assert both
`compose_up_project_name` calls recorded the identical `"sample-projinfra"`.
(This is the unit-level guard for the bug the smoke walk caught.)

## 3. Update the docex core doc

File: `plans/core/masterplan.md`

In the DooD section (point 4, "The compose project name is pinned explicitly"),
the line reads:
`<project_dns_label>-<env>` for env stacks, `<project_dns_label>-projinfra-<side>`
for the project tier.

Change the project-tier form to `<project_dns_label>-projinfra` (drop `-<side>`)
and add a brief clause: side-independent so single-machine fixed dev/prod sides
converge on one Compose project (per projinfra.md §35), while still being an
explicit, project-scoped name (mod 053) rather than the path-derived `infra`.

## 4. Verify

From `docex/`:

```
python -m pytest tests/unit/test_pipeline_projinfra.py -q
python -m pytest -q          # full unit suite must stay green
```

Do NOT run `-m integration` here (that is the campaign-level expensive pass). Do
not update core planning docs beyond masterplan.md step 3, and do not touch the
version artifacts or CHANGELOG (the cut handles those).

## Acceptance

- `_project_compose_project(ctx)` returns `${dns_label}-projinfra` with no `side`.
- Both `up` call sites and the `down` call site pass that name.
- `test_pipeline_projinfra.py` passes, including the new side-independence test.
- Full unit suite green.
- masterplan.md DooD §4 reflects the side-independent project-tier name.
