# Mod 072 — Implementation steps

Two code changes + tests. The doctrine changes for this mod are already applied
(`elastic_route53_zone.md § Teardown`, `projinfra.md` two-phase section) — do
**not** re-touch doctrine. Do **not** update `docex/plans/core/*` docs (handled
separately after review). No transfer-table or contract changes are needed.

All paths are relative to the docex project root: `~/.claude/jean_baudrillard/docex/`.

---

## Change 1 — `force_destroy = true` on the emitted Route53 zone

**File:** `src/docex/emit/templates/project.tf.j2`

Find the zone resource (around line 55):

```hcl
resource "aws_route53_zone" "project" {
  name = "{{ project_subdomain }}"
{{ tagblock(standard_tags("project", shape_name="dns", descriptor="zone", project=project)) }}
}
```

Add `force_destroy = true` and a `# WHY:` comment explaining it. Result:

```hcl
resource "aws_route53_zone" "project" {
  name = "{{ project_subdomain }}"
  # WHY: the zone legitimately accrues records tofu doesn't own — dev A-records
  # that NS-delegation forces into the child zone (dev is fixed/out-of-band),
  # plus stale ACM validation CNAMEs. force_destroy sweeps all records on
  # `projinfra down production` so the zone delete can't hit HostedZoneNotEmpty.
  # See elastic_route53_zone.md § Teardown. Destroy-only; no effect on up.
  force_destroy = true
{{ tagblock(standard_tags("project", shape_name="dns", descriptor="zone", project=project)) }}
}
```

Keep the existing block comment above the resource (lines ~41–54) as-is.

---

## Change 2 — Symmetric teardown reminder on successful elastic down

**File:** `src/docex/pipeline/projinfra.py`

In `run_projinfra_elastic_down`, the current success tail (Step 4) ends with:

```python
    print(
        f"projinfra down production: project {project!r} project-tier "
        f"and state backend removed."
    )
    return 0
```

Add a call to a new helper that prints the delegation-removal reminder, placed
**after** that success line and before `return 0`. The reminder must appear
**only** on the success path — both refuse gates already `return 1` before Step 3,
so they are unaffected. Do not print the reminder if `main_tf` was missing? — it
should still print: a missing `main.tf` still means the operator's intent was to
tear the project's DNS down, and the delegation may still exist at the parent.
Print it on every `return 0` path of this function.

`apex_domain` comes from `ctx.infra.apex_domain`. The child zone name is
`f"{dns_label(project)}.{apex_domain}"` — `dns_label` is already imported in this
module. Mirror `bootstrap.py::_print_delegation_instructions` in tone/shape.

Add this helper to the module (near the bottom, after `run_projinfra_elastic_down`):

```python
def _print_delegation_removal_reminder(project: str, apex_domain: str) -> None:
    """Remind the operator to remove the parent-zone NS delegation.

    The mirror of ``bootstrap.py::_print_delegation_instructions``: docex does
    not manage the parent zone (registrar / other account / other team), so it
    printed NS records for the operator to delegate on ``up`` and now prints a
    reminder to undo that delegation on ``down``. Left in place the delegation
    points at now-deleted nameservers and SERVFAILs the subtree on any later
    run. See elastic_route53_zone.md § Teardown.
    """
    project_subdomain = f"{dns_label(project)}.{apex_domain}"
    print("")
    print(
        f"  Reminder: the project's Route53 zone is gone, but the NS delegation "
        f"you added\n"
        f"  on `up` still lives in the parent zone ({apex_domain!r}). Remove it "
        "so a later\n"
        f"  run doesn't SERVFAIL on a dead delegation:\n"
        f"    delete the {project_subdomain!r} NS record from the parent zone "
        "at your\n"
        "    registrar or parent Route53 hosted zone."
    )
    print("")
```

Wire it into the success tail:

```python
    print(
        f"projinfra down production: project {project!r} project-tier "
        f"and state backend removed."
    )
    _print_delegation_removal_reminder(project, ctx.infra.apex_domain)
    return 0
```

Note the early `return 0` inside the `if not main_tf.is_file()` warning branch is
*not* an early return — that branch falls through to Step 4 and the shared tail.
Confirm by reading the function: there is a single `return 0` at the end plus the
two gate `return 1`s. If any additional `return 0` exists, ensure the reminder
prints on it too (extract into the tail so all success exits share it).

---

## Change 3 — Tests

### 3a. HCL emit — `force_destroy` present on the zone

**File:** `tests/unit/test_hcl_emitter.py`

There is an existing `test_projinfra_tags_route53_zone(compiled_elastic_project)`
that reads the compiled `main.tf` and uses a `_block(tf, 'resource
"aws_route53_zone" "project"')` helper. Add a focused test alongside it:

```python
def test_project_route53_zone_force_destroy(compiled_elastic_project: Path):
    """The child zone is emitted force_destroy=true so teardown sweeps
    out-of-band records (dev A-records, stale ACM CNAMEs) and can't hit
    HostedZoneNotEmpty. Mod 072 / advance 002."""
    tf = (compiled_elastic_project / "infra" / "output" / "project" / "production" / "main.tf").read_text()
    blk = _block(tf, 'resource "aws_route53_zone" "project"')
    assert "force_destroy = true" in blk
```

### 3b. Elastic down — reminder printed on success, not on refusal

**File:** `tests/unit/test_pipeline_projinfra.py`

Extend the existing clean-path test
`test_projinfra_elastic_down_clean_path_orders_cleanup` (it does not currently
capture stdout — add the `capsys` fixture to its signature) OR add a new test.
Prefer a **new** test to keep the ordering test focused:

```python
def test_projinfra_elastic_down_prints_delegation_removal_reminder(
    elastic_ctx, fake_aws, fake_tofu_init, fake_tofu_apply, capsys,
):
    """On a successful teardown, docex reminds the operator to remove the
    parent-zone NS delegation it can't manage itself. Mod 072 / advance 002."""
    _compile_project_tier(elastic_ctx)
    fake_aws.cluster_has_services = False  # envs down; ECR empty by default

    rc = run_projinfra_elastic_down(
        elastic_ctx, fake_aws,
        tofu_init=fake_tofu_init, tofu_destroy=fake_tofu_apply,
    )
    assert rc == 0
    out = capsys.readouterr().out
    # Names the NS record to remove and the parent zone.
    assert "NS record" in out
    assert elastic_ctx.infra.apex_domain in out
    # The child-zone subdomain the operator delegated.
    from docex.naming import dns_label
    assert f"{dns_label(elastic_ctx.project.name)}.{elastic_ctx.infra.apex_domain}" in out
```

Also assert the reminder does **not** print on a refusal. The two existing refuse
tests (`..._refuses_when_env_cluster_exists`, `..._refuses_on_nonempty_ecr`)
already capture `out`; add to each:

```python
    assert "NS record" not in out
```

### 3c. Run the suite

From the docex project root, run the unit + integration tests the normal way for
this repo (per `docex_process.md`: unit by default, integration where a real
boundary is crossed). At minimum:

```
python -m pytest tests/unit/test_hcl_emitter.py tests/unit/test_pipeline_projinfra.py -q
```

Then the full unit suite to catch regressions:

```
python -m pytest tests/unit -q
```

The compile integration test (`tests/integration/test_compile.py`) exercises the
template end-to-end; run it too if the environment supports it:

```
python -m pytest tests/integration/test_compile.py -q
```

All must pass. Report any failures with output rather than papering over them.

---

## Done criteria

- `project.tf.j2` zone block carries `force_destroy = true` with a WHY comment.
- `run_projinfra_elastic_down` prints the delegation-removal reminder on every
  success exit, never on a refusal.
- New tests 3a and 3b pass; refuse tests assert the reminder is absent.
- Full unit suite green.
