# Implementation — Mod 040 — Env-Tier SG Name Hyphen Fix

## Context for fresh-context implementer

You are executing mod 040. Read [`overview.md`](./overview.md) first.

Invoke the `docex-edit` skill via Skill.

Authoritative doctrine reading:
- [`networks.md § Compiled Names`](../../../../doctrine/infrastructure/specifics/networks.md#compiled-names) — explicit doctrine statement that SG names use the hyphenated form, with no special exceptions.

## Scope clarification

Mod 040's campaign-list scope (env-tier HCL refactor) **already landed** as side effects of mods 037, 038, and earlier mod 006. The remaining work in mod 040 is a single one-line fix: the env-tier security-group `name` field still uses literal underscores in `main.tf.j2:52`, while every other data-plane-resolvable identifier was hyphenated by mod 030. Mod 040 closes the gap.

## Step-by-step plan

### Step 1 — Fix the SG name in `main.tf.j2`

Edit `src/docex/emit/templates/main.tf.j2` line 52. Change:

```hcl
name        = "{{ project }}_{{ env }}_{{ short }}"
```

to:

```hcl
name        = "{{ project | replace('_', '-') }}-{{ env }}-{{ short }}"
```

Notes:
- `project` may contain underscores (e.g. `docex_smoke_elastic`). The `replace('_', '-')` filter handles this.
- `env` is constrained to `dev`/`test`/`stage`/`prod` — no underscores possible.
- `short` is a CICL network name (e.g. `web`, `internal`) — also no underscores by convention.

Add a short comment above explaining the rule (data-plane resolvable → hyphen; cite `networks.md`):

```hcl
# Data-plane name per networks.md § Compiled Names — hyphens regardless
# of the project's underscore form.
name        = "{{ project | replace('_', '-') }}-{{ env }}-{{ short }}"
```

### Step 2 — Sanity sweep for other underscore leaks in env-tier templates

```bash
cd ~/.claude/jean_baudrillard/docex
grep -n '"{{ project }}_\|{{ project }}_{{ env }}\|{{ project }}_{{' src/docex/emit/templates/main.tf.j2
```

Hits — if any remain after Step 1 — likely fall into one of two buckets:

- **Data-plane resolvable** (ECS cluster, target group, RDS, etc.) — should use hyphens. Investigate. **HOWEVER**: most of these are now driven by `apply_policy(..., ecs)` / `apply_policy(..., alb)` / etc. in `hcl.py` and emit names that are already hyphenated. So they'll likely use template variables like `{{ ecs_cluster_name }}` (already hyphenated) rather than literal `_` joiners.
- **AWS record-key identifiers** (IAM, SSM, DDB) — should preserve underscores. Already correct.

If anything else in the template emits a raw underscore name that the doctrine wants hyphenated, fix similarly. Report what you found (if anything).

### Step 3 — Tests

Find any test assertion that pins the env-tier SG name in the underscore form:

```bash
cd ~/.claude/jean_baudrillard/docex
grep -rn 'name.*"[a-z_]*_[a-z]*_[a-z]*_web"\|name.*"[a-z_]*_[a-z]*_[a-z]*_internal"' tests/
```

More targeted:

```bash
grep -n 'aws_security_group' tests/integration/test_compile.py tests/unit/test_hcl_emitter.py
```

For each hit pinning the underscore SG name, flip to the hyphen form. Likely candidates use a project named `docex_smoke_elastic` and assert names like `docex_smoke_elastic_stage_web` → these become `docex-smoke-elastic-stage-web`.

If no test currently pins the SG name, **add one** to lock down the new behavior:

```python
def test_env_tier_sg_name_uses_hyphen_form(tmp_path: Path):
    """SG names are data-plane identifiers per networks.md — hyphens."""
    proj = _write_underscore_project(tmp_path)
    run_compile(load_project_context(proj))
    for env in ("stage", "prod"):
        tf = (proj / "infra" / "output" / env / "main.tf").read_text()
        # Web SG name in hyphen form.
        assert 'name        = "docex-smoke-elastic-' + env + '-web"' in tf
        # Internal SG name same shape.
        assert 'name        = "docex-smoke-elastic-' + env + '-internal"' in tf
```

(Adapt the assertion strings to match the actual formatting of the rendered HCL.)

### Step 4 — Run tests

```bash
cd ~/.claude/jean_baudrillard/docex
pytest tests/unit -x
pytest tests/integration -x -m "not integration"
```

Both green.

### Step 5 — Sanity sweep

```bash
# The fixed template should produce hyphen-form SG names
grep -n 'aws_security_group "{{ short }}"' src/docex/emit/templates/main.tf.j2
grep -n 'name.*{{ project }}.*{{ env }}.*{{ short }}' src/docex/emit/templates/main.tf.j2

# Old literal-underscore pattern should be gone
grep -rn '"{{ project }}_{{ env }}_{{ short }}"' src/
```

First two: confirm hyphenated form. Third: zero hits.

## Out of scope

- **No env-tier listener rule changes** — already done in mod 038.
- **No env-tier remote-state refs** — already done in mods 037/038.
- **No project-tier changes.**
- **No master VPC switchover** — mod 041.
- **No `test_projects/{fixed,elastic}/` edits.**

## Done criteria

- [ ] `main.tf.j2:52` SG name uses `{{ project | replace('_', '-') }}-{{ env }}-{{ short }}` form.
- [ ] Comment cites `networks.md`.
- [ ] Sanity sweep confirms no other raw-underscore name composition remains in env-tier templates (or, if any are found, they're either acceptable record-key identifiers or fixed).
- [ ] Tests cover the new hyphen-form SG name (existing or new).
- [ ] `pytest tests/unit -x` and offline `tests/integration -x -m "not integration"` both green.
- [ ] No `test_projects/{fixed,elastic}/` edits.

Working tree dirty when finished. Do not commit.
